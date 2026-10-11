import copy
import io
import json
from pathlib import Path
import sqlite3
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import static_only_upgrade as s


def receipts():
    current = {'crm': {'id': 'synthetic-crm'}, 'private': {'api': {}, 'worker': {}},
               'private_database': {'identity': 'synthetic-identity', 'schema_sha256': 'synthetic-schema'}}
    candidate = {'stage': 'PRIVATE_FINANCE_CANDIDATE_VERIFIED', 'source_sha': s.BACKEND_SOURCE,
                 'image_id': s.BACKEND_IMAGE, 'frontend_version': s.PREVIOUS_VERSION}
    state = {'phase': 'PRIVATE_COMPLETED_RELEASE_SERVER_VERIFIED', 'source_sha': s.BACKEND_SOURCE,
             'candidate_image': s.BACKEND_IMAGE, 'new_ids': s.BACKEND_IDS, 'deployed': True,
             'business_tables_verified': 83, 'public_assets_published': False, 'bank_enabled': False,
             'ai_enabled': False, 'initializer_rerun': False, 'credential_seed_attempted': False,
             'databases_restored': False}
    previous = {'phase': 'PRIVATE_COMPLETED_PUBLIC_RELEASE_VERIFIED', 'source_sha': s.BACKEND_SOURCE,
                'frontend_version': s.PREVIOUS_VERSION, 'candidate_sha256': s.CANDIDATE_SHA,
                'switch_state_sha256': s.SWITCH_SHA, 'public_root': str(s.PREVIOUS_PUBLIC),
                'deployed': True, 'business_tables_verified': 83, 'backend_services_modified': False,
                'databases_restored': False, 'bank_enabled': False, 'ai_enabled': False,
                'new_nginx_sha256': 'd' * 64, 'private_and_crm_runtime': current}
    return candidate, state, previous


def fake_base():
    c, state, previous = receipts()
    base = SimpleNamespace(fixed_json=Mock(side_effect=[c, state, previous]),
                           runtime_snapshot=Mock(return_value=copy.deepcopy(previous['private_and_crm_runtime'])))
    return base


def test_accepted_receipts_read_only_exact_pinned_lineage():
    base = fake_base()
    candidate, state, previous = s.accepted_receipts(base)
    assert candidate['source_sha'] == s.BACKEND_SOURCE
    assert state['new_ids'] == s.BACKEND_IDS
    assert previous['frontend_version'] == s.PREVIOUS_VERSION
    assert base.fixed_json.call_args_list[0].args == (s.CANDIDATE, s.CANDIDATE_SHA)
    assert base.fixed_json.call_args_list[1].args == (s.SWITCH_STATE, s.SWITCH_SHA)
    assert base.fixed_json.call_args_list[2].args == (s.PREVIOUS_STATIC, s.PREVIOUS_STATIC_SHA)


@pytest.mark.parametrize('part,key,value', [
    (0, 'source_sha', 'a' * 40), (0, 'image_id', 'sha256:' + 'a' * 64),
    (0, 'frontend_version', 'a' * 12), (1, 'deployed', False), (1, 'bank_enabled', True),
    (1, 'ai_enabled', True), (1, 'initializer_rerun', True), (1, 'credential_seed_attempted', True),
    (1, 'databases_restored', True), (1, 'new_ids', {'api': 'different', 'worker': 'different'}),
    (2, 'phase', 'unaccepted'), (2, 'frontend_version', 'a' * 12),
    (2, 'candidate_sha256', 'a' * 64), (2, 'switch_state_sha256', 'a' * 64),
    (2, 'public_root', '/var/www/other'), (2, 'backend_services_modified', True),
    (2, 'deployed', False), (2, 'new_nginx_sha256', 'invalid'),
])
def test_unaccepted_or_rebound_runtime_proof_rejected(part, key, value):
    values = list(receipts())
    values[part][key] = value
    with pytest.raises(s.StaticError):
        s.accepted_receipts(SimpleNamespace(fixed_json=Mock(side_effect=values)))


def test_runtime_compares_accepted_services_and_schema_without_historical_rows():
    c, state, previous = receipts()
    base = fake_base()
    with patch.object(s, 'disabled_live_features') as disabled:
        assert s.runtime(base, c, state, previous) == previous['private_and_crm_runtime']
    base.runtime_snapshot.assert_called_once_with(state, c, healthy=True)
    disabled.assert_called_once_with(base, healthy=True)


@pytest.mark.parametrize('section', ['crm', 'private', 'private_database'])
def test_runtime_identity_or_configuration_or_schema_change_rejected(section):
    c, state, previous = receipts()
    base = fake_base()
    changed = copy.deepcopy(previous['private_and_crm_runtime'])
    changed[section] = {'changed': True}
    base.runtime_snapshot.return_value = changed
    with patch.object(s, 'disabled_live_features') as disabled, pytest.raises(s.StaticError):
        s.runtime(base, c, state, previous)
    disabled.assert_not_called()


def disabled_fixture(tmp_path):
    path = tmp_path / 'synthetic-private.db'
    with sqlite3.connect(path) as db:
        for table in ('private_mail_translations', 'private_translation_usage', 'private_mail_briefs',
                      'private_mail_brief_usage', 'private_workspace_briefs', 'private_bank_links'):
            db.execute('CREATE TABLE ' + table + '(id TEXT)')
        db.execute('CREATE TABLE private_connections(source_id TEXT, status TEXT, encrypted_credentials TEXT)')
        db.execute("INSERT INTO private_connections VALUES('gmail','connected','synthetic-encrypted-value')")
    env = [key + '=' + value for key, value in s.DISABLED_FLAGS.items()]
    base = SimpleNamespace(PRIVATE_DB=path, inspect=Mock(return_value={'Config': {'Env': env}}))
    return base, path


def test_live_disabled_features_check_is_read_only_and_accepts_existing_provider_data(tmp_path):
    base, path = disabled_fixture(tmp_path)
    before = path.read_bytes()
    s.disabled_live_features(base)
    assert path.read_bytes() == before
    assert [call.args[0] for call in base.inspect.call_args_list] == ['t24-private-api', 't24-private-worker']


@pytest.mark.parametrize('kind', ['enabled', 'missing', 'duplicate', 'bank_connected', 'bank_credential', 'ai_usage'])
def test_live_enabled_or_ambiguous_bank_ai_scope_rejected(tmp_path, kind):
    base, path = disabled_fixture(tmp_path)
    env = [key + '=' + value for key, value in s.DISABLED_FLAGS.items()]
    if kind == 'enabled':
        env[0] = 'PRIVATE_WORKSPACE_PLAID_ENABLED=true'
    elif kind == 'missing':
        env.pop()
    elif kind == 'duplicate':
        env.append(env[0])
    elif kind == 'bank_connected':
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO private_connections VALUES('bofa_bank','connected',NULL)")
    elif kind == 'bank_credential':
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO private_connections VALUES('bofa_bank','disconnected','synthetic')")
    else:
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO private_mail_brief_usage VALUES('synthetic')")
    base.inspect.return_value = {'Config': {'Env': env}}
    with pytest.raises(s.StaticError):
        s.disabled_live_features(base)


def file_map(root):
    return {path.relative_to(root).as_posix(): s.sha(path.read_bytes())
            for path in sorted(root.rglob('*')) if path.is_file()}


def write_new(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def archive(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz', format=tarfile.USTAR_FORMAT) as out:
        for name, content, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(content)
            if kind == tarfile.SYMTYPE:
                member.linkname = '../outside'
            out.addfile(member, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
    return stream.getvalue()


def static_fixture(tmp_path):
    contents = {'index.html': b'<script src="/assets/test.js"></script>',
                'app-version.json': json.dumps({'version': 'b' * 12}).encode(),
                'assets/test.js': b'/* synthetic navigation app */'}
    payload = archive([('payload/' + name, blob, tarfile.REGTYPE) for name, blob in contents.items()])
    manifest = {'format_version': 1, 'stage': 'FROZEN_PRIVATE_NAVIGATION_STATIC_SOURCE',
                'frontend_source_sha': 'a' * 40, 'frontend_version': 'b' * 12,
                'backend_source_sha': s.BACKEND_SOURCE, 'previous_frontend_version': s.PREVIOUS_VERSION,
                'changed_source_files': ['app/frontend/src/pages/PrivateWorkspace.tsx'],
                'backend_changes': False, 'credentials_included': False, 'databases_modified': False,
                'static_only': True, 'payload_sha256': s.sha(payload),
                'payload_files': {name: s.sha(blob) for name, blob in contents.items()}}
    (tmp_path / 'static-payload.tar.gz').write_bytes(payload)
    blob = json.dumps(manifest).encode()
    (tmp_path / 'static-manifest.json').write_bytes(blob)
    return contents, payload, manifest, s.sha(blob)


def static_base():
    return SimpleNamespace(SUFFIXES={'.html', '.js', '.css', '.json'}, write_new=write_new, file_map=file_map)


def test_exact_manifest_and_complete_archive(tmp_path):
    contents, payload, manifest, manifest_hash = static_fixture(tmp_path)
    with patch.object(s, 'protected_bytes', side_effect=lambda path, maximum: path.read_bytes()):
        accepted, fetched = s.checked_manifest(static_base(), tmp_path, manifest_hash, 'a' * 40, 'b' * 12)
    assert fetched == payload and accepted == manifest
    root = s.extract_static(static_base(), tmp_path, accepted, fetched, 'b' * 12)
    assert file_map(root) == manifest['payload_files']
    assert (root / 'assets/test.js').read_bytes() == contents['assets/test.js']


@pytest.mark.parametrize('key,value', [
    ('frontend_source_sha', 'c' * 40), ('frontend_version', 'c' * 12),
    ('backend_source_sha', 'c' * 40), ('previous_frontend_version', 'c' * 12),
    ('backend_changes', True), ('credentials_included', True), ('databases_modified', True),
    ('static_only', False), ('payload_sha256', 'c' * 64),
    ('changed_source_files', ['app/frontend/src/pages/Finance.tsx']),
    ('changed_source_files', ['app/frontend/src/pages/PrivateWorkspace.tsx'] * 2),
])
def test_manifest_cannot_rebind_source_or_expand_finance_scope(tmp_path, key, value):
    _, _, manifest, _ = static_fixture(tmp_path)
    manifest[key] = value
    blob = json.dumps(manifest).encode()
    (tmp_path / 'static-manifest.json').write_bytes(blob)
    with patch.object(s, 'protected_bytes', side_effect=lambda path, maximum: path.read_bytes()), pytest.raises(s.StaticError):
        s.checked_manifest(static_base(), tmp_path, s.sha(blob), 'a' * 40, 'b' * 12)


@pytest.mark.parametrize('name', ['../outside.js', '/outside.js', '.env', 'other.html', 'runtime.py'])
def test_non_static_manifest_file_names_rejected(tmp_path, name):
    _, _, manifest, _ = static_fixture(tmp_path)
    manifest['payload_files'][name] = 'd' * 64
    blob = json.dumps(manifest).encode()
    (tmp_path / 'static-manifest.json').write_bytes(blob)
    with patch.object(s, 'protected_bytes', side_effect=lambda path, maximum: path.read_bytes()), pytest.raises(s.StaticError):
        s.checked_manifest(static_base(), tmp_path, s.sha(blob), 'a' * 40, 'b' * 12)


@pytest.mark.parametrize('entries', [
    [('payload/../escape.js', b'x', tarfile.REGTYPE)],
    [('payload/assets/test.js', b'x', tarfile.SYMTYPE)],
    [('payload/assets/unknown.js', b'x', tarfile.REGTYPE)],
    [('payload/assets/test.js', b'wrong bytes', tarfile.REGTYPE)],
    [('payload/assets/test.js', b'/* synthetic navigation app */', tarfile.REGTYPE)] * 2,
])
def test_archive_traversal_links_unlisted_changed_or_duplicate_entries_rejected(tmp_path, entries):
    _, _, manifest, _ = static_fixture(tmp_path)
    with pytest.raises(s.StaticError):
        s.extract_static(static_base(), tmp_path, manifest, archive(entries), 'b' * 12)
    assert not (tmp_path.parent / 'escape.js').exists()


def test_missing_archive_file_and_stale_build_version_rejected(tmp_path):
    _, _, manifest, _ = static_fixture(tmp_path)
    with pytest.raises(s.StaticError, match='COMPLETE_STATIC_ARCHIVE_REQUIRED'):
        s.extract_static(static_base(), tmp_path, manifest, archive([]), 'b' * 12)


def test_rollback_restores_only_original_static_root():
    c, state, previous = receipts()
    base = SimpleNamespace(read_nginx=Mock(side_effect=[b'new', b'old']), atomic_nginx=Mock(),
                           run=Mock(), public_check=Mock(), file_map=Mock(return_value={'index.html': 'a' * 64}))
    with patch.object(s, 'runtime', return_value={}):
        s.rollback(base, b'old', b'new', c, state, previous)
    base.atomic_nginx.assert_called_once_with(b'old', {s.sha(b'new')})
    assert [call.args[0] for call in base.run.call_args_list] == [['nginx', '-t'], ['systemctl', 'reload', 'nginx']]
    base.public_check.assert_called_once_with({'index.html': 'a' * 64}, s.PREVIOUS_VERSION,
                                              s.PREVIOUS_PUBLIC, verify_services=False)


def test_rollback_never_overwrites_unrelated_concurrent_nginx_change():
    c, state, previous = receipts()
    base = SimpleNamespace(read_nginx=Mock(return_value=b'unrelated'), atomic_nginx=Mock())
    with patch.object(s, 'runtime', return_value={}), pytest.raises(s.StaticError, match='STATIC_ROLLBACK_CONCURRENT_CHANGE'):
        s.rollback(base, b'old', b'new', c, state, previous)
    base.atomic_nginx.assert_not_called()


def execution_fixture(tmp_path):
    release = tmp_path / 'release'
    release.mkdir()
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'private-finance-release.lock').write_bytes(b'')
    base = SimpleNamespace(CONFIG=config, read_nginx=Mock(side_effect=[b'old', b'old', b'old', b'new']),
                           changed_nginx=Mock(return_value=b'new'), file_map=Mock(return_value={'index.html': 'a' * 64}),
                           public_check=Mock(), install_public=Mock(return_value={'index.html': 'a' * 64}),
                           business_fingerprints=Mock(side_effect=[{'tables': 'current'}, {'tables': 'current'}]),
                           digest=lambda value: s.sha(json.dumps(value, sort_keys=True).encode()),
                           write_new=write_new, atomic_nginx=Mock(), run=Mock())
    reports = []
    def save(path, value, replace=False):
        reports.append(copy.deepcopy(value))
        path.write_text(json.dumps(value))
    base.save = Mock(side_effect=save)
    args = SimpleNamespace(execute=True, frontend_source_sha='a' * 40,
                           frontend_version='b' * 12, manifest_sha256='c' * 64)
    patches = [patch.object(s.os, 'geteuid', return_value=0), patch.object(s.socket, 'gethostname', return_value=s.HOST),
               patch.object(s, '__file__', str(release / 'static_only_upgrade.py')),
               patch.object(s, 'Path', side_effect=lambda value: release if value == '/opt/t24-crm/releases' else Path(value)),
               patch.object(s, 'protected'), patch.object(s.fcntl, 'flock'),
               patch.object(s, 'accepted_receipts', return_value=receipts()), patch.object(s, 'runtime', return_value={}),
               patch.object(s, 'checked_manifest', return_value=({'payload_sha256': 'c' * 64}, b'archive')),
               patch.object(s, 'extract_static', return_value=release / 'payload')]
    # Path construction still checks the exact source-bound release name.
    release.rename(tmp_path / ('private-navigation-' + 'a' * 12 + '-20261011'))
    release = tmp_path / ('private-navigation-' + 'a' * 12 + '-20261011')
    patches[2] = patch.object(s, '__file__', str(release / 'static_only_upgrade.py'))
    patches[3] = patch.object(s, 'Path', side_effect=lambda value: tmp_path if value == '/opt/t24-crm/releases' else Path(value))
    return release, base, reports, args, patches


def run_patched(args, base, patches):
    from contextlib import ExitStack
    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        return s.main(args, base)


def test_static_success_compares_current_round_business_and_never_runs_containers(tmp_path):
    release, base, reports, args, patches = execution_fixture(tmp_path)
    value = run_patched(args, base, patches)
    assert value['deployed'] is True and value['business_tables_verified'] == 83
    assert value['backend_source_sha'] == s.BACKEND_SOURCE
    assert base.business_fingerprints.call_count == 2
    assert reports[-1]['phase'] == 'PRIVATE_NAVIGATION_STATIC_RELEASE_VERIFIED'
    assert [call.args[0] for call in base.run.call_args_list] == [['nginx', '-t'], ['systemctl', 'reload', 'nginx']]
    assert not reports[-1]['backend_services_modified'] and not reports[-1]['databases_modified']


@pytest.mark.parametrize('failure', ['public', 'business', 'late_receipt'])
def test_post_switch_failure_rolls_back_and_never_claims_deployed(tmp_path, failure):
    _, base, reports, args, patches = execution_fixture(tmp_path)
    if failure == 'public':
        base.public_check.side_effect = [None, RuntimeError('synthetic-public-check')]
    elif failure == 'business':
        base.business_fingerprints.side_effect = [{'tables': 'before'}, {'tables': 'different'}]
    else:
        original_save = base.save.side_effect
        def save(path, report, replace=False):
            if report['phase'] == 'PRIVATE_NAVIGATION_STATIC_RELEASE_VERIFIED':
                raise OSError('synthetic-late-receipt')
            original_save(path, report, replace)
        base.save.side_effect = save
    with patch.object(s, 'rollback') as rollback, pytest.raises(s.StaticError, match='STATIC_RELEASE_REJECTED_ROLLBACK_VERIFIED'):
        run_patched(args, base, patches)
    rollback.assert_called_once()
    assert reports[-1]['phase'] == 'PRIVATE_NAVIGATION_STATIC_ROLLBACK_VERIFIED'
    assert reports[-1]['deployed'] is False


@pytest.mark.parametrize('execute,user,host', [(False, 0, s.HOST), (True, 1000, s.HOST), (True, 0, 'wrong-server')])
def test_non_authorized_execution_cannot_read_receipts_or_touch_server(execute, user, host):
    args = SimpleNamespace(execute=execute)
    with patch.object(s.os, 'geteuid', return_value=user), patch.object(s.socket, 'gethostname', return_value=host), \
            patch.object(s, 'retained_tools') as tools, pytest.raises(s.StaticError):
        s.main(args)
    tools.assert_not_called()


def test_safe_parser_does_not_echo_accidental_secret_arguments():
    parser = s.SafeParser()
    with pytest.raises(s.StaticError, match='^ARGUMENTS_REJECTED$'):
        parser.parse_args(['--unrecognized-sensitive-argument=synthetic-secret'])


def test_safe_error_preserves_reviewed_codes_but_never_discloses_record_or_secret_text():
    SwitchError = type('SwitchError', (RuntimeError,), {})
    assert s.safe_error(SwitchError('ACCEPTED_PRIVATE_RUNTIME_DRIFT')) == 'ACCEPTED_PRIVATE_RUNTIME_DRIFT'
    assert s.safe_error(SwitchError('synthetic-secret-value with spaces')) == 'STATIC_RELEASE_FAILED'
    assert s.safe_error(ValueError('synthetic-sensitive-value')) == 'STATIC_RELEASE_FAILED'
    assert s.safe_error(RuntimeError('ALL_UPPERCASE_UNREVIEWED_ERROR')) == 'STATIC_RELEASE_FAILED'


def test_retained_tool_hash_drift_fails_before_any_import(tmp_path):
    with patch.object(s, 'RETAINED_TOOLS', tmp_path), patch.object(s, 'protected'), \
            patch.object(s, 'protected_bytes', return_value=b'changed retained code'), \
            patch.object(s.importlib.util, 'spec_from_file_location') as loader, pytest.raises(s.StaticError, match='RETAINED_TOOL_HASH_DRIFT'):
        s.retained_tools()
    loader.assert_not_called()


def test_runtime_drift_during_preparation_cannot_publish_nginx(tmp_path):
    _, base, _, args, patches = execution_fixture(tmp_path)
    patches = [item for item in patches if item.attribute != 'runtime']
    patches.append(patch.object(s, 'runtime', side_effect=[{'initial': True}, {'changed': True}]))
    with pytest.raises(s.StaticError, match='PREPARATION_RUNTIME_OR_NGINX_DRIFT'):
        run_patched(args, base, patches)
    base.atomic_nginx.assert_not_called()
    base.run.assert_not_called()


def test_root_only_nginx_transformation_preserves_proxies_and_every_other_byte(tmp_path):
    import importlib.util
    root = Path(__file__).resolve().parents[1] / 'private-finance-20261011/static_completed.py'
    spec = importlib.util.spec_from_file_location('synthetic_navigation_static_primitives', root)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    new = tmp_path / 'new-public'
    original = (str(s.PREVIOUS_PUBLIC) + '; proxy_pass http://127.0.0.1:8000; '
                'proxy_pass http://127.0.0.1:8001; ' + ' '.join(base.HEADERS)).encode()
    base.OLD_PUBLIC, base.PUBLIC = s.PREVIOUS_PUBLIC, new
    changed = base.changed_nginx(original, s.sha(original))
    assert changed.replace(str(new).encode(), str(s.PREVIOUS_PUBLIC).encode(), 1) == original
    with pytest.raises(base.SwitchError):
        base.changed_nginx(original, 'f' * 64)
    ambiguous = original + str(s.PREVIOUS_PUBLIC).encode()
    with pytest.raises(base.SwitchError):
        base.changed_nginx(ambiguous, s.sha(ambiguous))


def test_no_historical_mutation_program_is_invoked():
    source = Path(s.__file__).read_text()
    assert 'seeded_repair.checked_final' not in source
    assert 'checked_state(' not in source
    assert "['docker'," not in source
    assert 'UPDATE private_' not in source and 'INSERT INTO' not in source and 'CREATE TABLE' not in source
