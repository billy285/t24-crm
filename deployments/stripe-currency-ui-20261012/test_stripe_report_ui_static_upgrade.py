"""Offline regressions; never import a server helper or contact production."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('stripe_ui_static_tested', HERE / 'stripe-report-ui-static-upgrade.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def file_map(root):
    return {path.relative_to(root).as_posix(): s.sha(path.read_bytes())
            for path in sorted(root.rglob('*')) if path.is_file()}


def write_new(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(value)


def archive(files, *, names=None, link=None):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz', format=tarfile.USTAR_FORMAT) as stream:
        for name in names or list(files):
            value = files[name]
            item = tarfile.TarInfo('payload/' + name)
            item.size = len(value)
            stream.addfile(item, io.BytesIO(value))
        if link:
            item = tarfile.TarInfo('payload/' + link)
            item.type, item.linkname = tarfile.SYMTYPE, '/etc/passwd'
            stream.addfile(item)
    return result.getvalue()


@pytest.fixture
def frozen(tmp_path):
    release = tmp_path / 'release'
    release.mkdir(mode=0o700)
    args = SimpleNamespace(frontend_source_sha='08e8505f5a6ea66626e91b2089394ef001c54fd7',
                           frontend_version='adfb31c0b755')
    files = {'index.html': b'<script src="/assets/new.js"></script>',
             'app-version.json': encoded({'version': args.frontend_version}),
             'assets/new.js': b'console.log("usd")'}
    payload = archive(files)
    manifest = {'format_version': 1, 'stage': 'FROZEN_STRIPE_REPORT_UI_STATIC_SOURCE',
                'frontend_source_sha': args.frontend_source_sha, 'frontend_version': args.frontend_version,
                'backend_source_sha': s.BACKEND_SOURCE, 'previous_frontend_version': s.PREVIOUS_VERSION,
                'static_only': True, 'backend_changes': False, 'credentials_included': False,
                'databases_modified': False, 'services_modified': False,
                'changed_source_files': {name: 'a' * 64 for name in s.ALLOWED_SOURCE_FILES},
                'payload_files': {name: s.sha(value) for name, value in files.items()},
                'payload_sha256': s.sha(payload)}
    args.manifest_sha256, args.payload_sha256 = s.sha(encoded(manifest)), s.sha(payload)
    (release / 'static-manifest.json').write_bytes(encoded(manifest))
    (release / 'static-payload.tar.gz').write_bytes(payload)
    base = SimpleNamespace(SUFFIXES={'.html', '.json', '.js', '.css', '.png'},
                           write_new=write_new, file_map=file_map)
    upgrade = SimpleNamespace(fixed_json=lambda path, expected: checked_json(path, expected),
                              read_protected=lambda path, maximum=4*1024**2: path.read_bytes())
    return release, args, files, payload, manifest, base, upgrade


def checked_json(path, expected):
    value = path.read_bytes()
    s.need(s.sha(value) == expected, 'FIXED_HASH_DRIFT')
    return json.loads(value)


def refreeze(frozen, manifest=None, payload=None):
    release, args, _, old_payload, old_manifest, _, _ = frozen
    manifest = copy.deepcopy(old_manifest if manifest is None else manifest)
    payload = old_payload if payload is None else payload
    manifest['payload_sha256'] = args.payload_sha256 = s.sha(payload)
    args.manifest_sha256 = s.sha(encoded(manifest))
    (release / 'static-manifest.json').write_bytes(encoded(manifest))
    (release / 'static-payload.tar.gz').write_bytes(payload)
    return manifest, payload


def test_complete_valid_frozen_payload_extracts_only_declared_bytes(frozen):
    release, args, files, _, _, base, upgrade = frozen
    manifest, payload = s.checked_manifest(upgrade, base, release, args)
    result = s.extract_static(base, release, manifest, payload, args.frontend_version)
    assert file_map(result) == {name: s.sha(value) for name, value in files.items()}
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in result.rglob('*') if path.is_file())
    with pytest.raises(s.StaticError, match='FRESH_STATIC_PAYLOAD_REQUIRED'):
        s.extract_static(base, release, manifest, payload, args.frontend_version)


def test_actual_reviewed_113_file_hotfix_artifacts_match_publisher_contract(frozen):
    release, args, _, _, _, base, upgrade = frozen
    choices = [HERE / 'artifacts', HERE.parent / 'work/t24-crm/work/release-ui/deployments/stripe-currency-ui-20261012/artifacts']
    source = next(path for path in choices if (path / 'static-manifest.json').is_file())
    for name in ('static-manifest.json', 'static-payload.tar.gz'):
        (release / name).write_bytes((source / name).read_bytes())
    args.manifest_sha256 = '68d3261cb84f6aab5070f3955a48644ff59d0659b6fc42348890b8e64f65fcb8'
    args.payload_sha256 = '34ff135b21a094645c41b7d1a606b357833f610c4755dd246bf1884a5941a16d'
    base.SUFFIXES = {'.html','.js','.css','.json','.png','.jpg','.jpeg','.webp','.gif','.svg',
                     '.ico','.txt','.woff','.woff2','.ttf','.webmanifest'}
    manifest, payload = s.checked_manifest(upgrade, base, release, args)
    root = s.extract_static(base, release, manifest, payload, args.frontend_version)
    assert len(file_map(root)) == 113
    assert set(manifest['changed_source_files']) == s.ALLOWED_SOURCE_FILES


@pytest.mark.parametrize('key,value', [
    ('backend_source_sha', 'f' * 40), ('previous_frontend_version', 'f' * 12),
    ('frontend_source_sha', 'f' * 40), ('frontend_version', 'f' * 12),
    ('stage', 'FROZEN_PRIVATE_NAVIGATION_STATIC_SOURCE'), ('static_only', False),
    ('backend_changes', True), ('credentials_included', True), ('databases_modified', True),
    ('services_modified', True), ('changed_source_files', ['app/frontend/src/lib/private-stripe-report.ts']),
    ('changed_source_files', {'app/backend/main.py': 'a'*64}),
    ('changed_source_files', {name: 'INVALID' for name in s.ALLOWED_SOURCE_FILES}),
])
def test_backend_credential_scope_and_provenance_fail_closed(frozen, key, value):
    release, args, _, _, manifest, base, upgrade = frozen
    manifest[key] = value
    refreeze(frozen, manifest)
    with pytest.raises(s.StaticError, match='EXACT_CURRENCY_FRONTEND_ONLY_MANIFEST_REQUIRED'):
        s.checked_manifest(upgrade, base, release, args)
    assert not (release / 'payload').exists()


@pytest.mark.parametrize('name', ['../escape.js', '/absolute.js', 'assets/.hidden.js',
                                 'assets/nested/../../escape.js', 'credentials.env', 'other.html'])
def test_manifest_rejects_path_and_nonstatic_files_before_extraction(frozen, name):
    release, args, _, _, manifest, base, upgrade = frozen
    manifest['payload_files'][name] = 'a'*64
    refreeze(frozen, manifest)
    with pytest.raises(s.StaticError, match='STATIC_FILE_SCOPE_REJECTED'):
        s.checked_manifest(upgrade, base, release, args)


@pytest.mark.parametrize('which', ['manifest', 'payload', 'manifest_pin', 'payload_pin'])
def test_independent_artifact_hashes_required(frozen, which):
    release, args, _, _, _, base, upgrade = frozen
    if which in {'manifest', 'payload'}:
        path = release / ('static-manifest.json' if which == 'manifest' else 'static-payload.tar.gz')
        path.write_bytes(path.read_bytes() + b'X')
    else:
        setattr(args, which.replace('_pin', '_sha256'), 'g' * 64)
    with pytest.raises(s.StaticError):
        s.checked_manifest(upgrade, base, release, args)


@pytest.mark.parametrize('case', ['duplicate', 'undeclared', 'missing', 'symlink', 'traversal', 'hash', 'version'])
def test_archive_member_attacks_and_incomplete_payload_fail_closed(frozen, case):
    release, args, files, _, manifest, base, _ = frozen
    if case == 'duplicate':
        blob = archive(files, names=['index.html', 'index.html'])
    elif case == 'undeclared':
        blob = archive({**files, 'assets/unlisted.js': b'X'})
    elif case == 'missing':
        blob = archive({key: value for key, value in files.items() if key != 'index.html'})
    elif case == 'symlink':
        blob = archive(files, link='assets/link.js')
    elif case == 'traversal':
        blob = archive({'../escape.js': b'X'})
    elif case == 'hash':
        blob = archive({**files, 'assets/new.js': b'other bytes'})
    else:
        files['app-version.json'] = encoded({'version': s.PREVIOUS_VERSION})
        manifest['payload_files']['app-version.json'] = s.sha(files['app-version.json'])
        blob = archive(files)
    with pytest.raises(s.StaticError):
        s.extract_static(base, release, manifest, blob, args.frontend_version)
    assert not (release.parent / 'escape.js').exists()


def make_runtime(frozen):
    release, args, _, _, manifest, base, upgrade = frozen
    config = release / 'config'
    config.mkdir()
    (config / 'private-finance-release.lock').write_bytes(b'')
    original, changed = b'accepted original nginx', b'new static nginx'
    current_nginx = [original]
    commands = []
    old_public, new_public = {'assets/old.js': 'a'*64}, {'assets/old.js': 'a'*64, 'assets/new.js': 'b'*64}
    roles = {'api': {'id': 'a'*64, 'image': 'sha256:'+'c'*64, 'started_at': 'accepted'},
             'worker': {'id': 'b'*64, 'image': 'sha256:'+'c'*64, 'started_at': 'accepted'}}
    baseline = {'business': {'tables': {str(i): {'count': i} for i in range(83)}},
                'private': {'identity': {'device': 1, 'inode': 2},
                            'tables': {str(i): {} for i in range(11)}}}
    receipt = {'new_nginx_sha256': s.sha(original), 'baseline_runtime': {'crm': 'unchanged'},
               'target_schema_objects': {'private_stripe_reports': 'accepted'}}
    authorization, records = {'opaque': 'generation-and-ciphertext'}, {'items': 'manual-note-hash'}
    owner = {'stage': 'STRIPE_REPORT_OWNER_UI_AFTER_VERIFIED', 'source_sha': s.BACKEND_SOURCE,
             'frontend_version': s.PREVIOUS_VERSION, 'pins': s.PINS, 'roles': roles,
             'stable_records_and_authorization_preserved': True, 'database_mutation_performed': False,
             'services_modified': False, 'stable_authorization': authorization, 'stable_records': records}
    protected_files = {s.OWNER_AFTER: owner, s.PREVIOUS_RELEASE / 'acquired.json': {},
                       s.PREVIOUS_RELEASE / 'upgrade-state.json': receipt}
    fixed_json = upgrade.fixed_json
    upgrade.fixed_json = lambda path, expected: protected_files[path] if path in protected_files else fixed_json(path, expected)
    upgrade.protected = lambda path, directory=False: path.stat()
    upgrade.stable_authorization = Mock(return_value=authorization)
    upgrade.assert_runtime_boundary = Mock()
    upgrade.assert_schema = Mock(return_value=baseline)
    upgrade.report_auth_check = Mock()
    upgrade.digest = lambda value: s.sha(encoded(value))
    nav = SimpleNamespace(disabled_live_features=Mock())
    preparation = SimpleNamespace(release_snapshot=Mock(return_value=baseline))
    switch = SimpleNamespace(preserved=lambda before, after: s.need(before == after, 'MANUAL_RECORDS_CHANGED'))
    upgrade.retained_tools = lambda ignored: (base, nav, preparation, switch)
    base.CONFIG, base.PRIVATE_DB, base.BUSINESS = config, release / 'private.db', release / 'business.db'
    base.read_nginx = lambda: current_nginx[0]
    base.changed_nginx = lambda value, expected: changed
    base.atomic_nginx = Mock(side_effect=lambda value, accepted: (s.need(s.sha(current_nginx[0]) in accepted,
        'NGINX_CONCURRENT_CHANGE'), current_nginx.__setitem__(0, value)))
    base.run = Mock(side_effect=lambda command, code: commands.append(command))
    base.public_check = Mock()
    base.save = lambda path, value, replace=False: path.write_bytes(encoded(value)) if replace else write_new(path, encoded(value))
    local_file_map = base.file_map
    base.file_map = lambda path: old_public if path == s.PREVIOUS_PUBLIC else (
        new_public if path == getattr(base, 'PUBLIC', None) else local_file_map(path))
    base.install_public = Mock(return_value=new_public)
    verifier = SimpleNamespace(load_upgrade=lambda expected: upgrade,
        checked_release=lambda *ignored: (None, receipt, None, None, None, roles, old_public),
        stable_digests=Mock(return_value=records), current_roles=Mock(return_value=(None, roles)))
    return SimpleNamespace(release=release, args=args, base=base, upgrade=upgrade, verifier=verifier,
        current_nginx=current_nginx, original=original, changed=changed, commands=commands,
        receipt=receipt, roles=roles, baseline=baseline)


def test_static_publish_preserves_backend_crm_credentials_and_old_assets(frozen):
    runtime = make_runtime(frozen)
    result = s.apply(runtime.args, runtime.release, runtime.verifier)
    assert result['deployed'] is True and result['private_tables_verified'] == 11
    assert result['business_tables_verified'] == 83
    assert runtime.current_nginx == [runtime.changed]
    assert runtime.commands == [['nginx', '-t'], ['systemctl', 'reload', 'nginx']]
    state = json.loads((runtime.release / 'static-state.json').read_bytes())
    assert state['previous_assets_preserved'] and state['same_private_inode']
    assert state['roles'] == runtime.roles and state['credentials_and_generation_unchanged']
    assert all(state[key] is False for key in ('backend_services_modified', 'database_mutation_performed', 'environment_modified'))


@pytest.mark.parametrize('drift', ['schema', 'runtime', 'credentials', 'roles', 'records'])
def test_boundary_drift_prevents_nginx_switch_and_never_mutates_backend(frozen, drift):
    runtime = make_runtime(frozen)
    if drift == 'schema':
        runtime.upgrade.assert_schema.side_effect = s.StaticError('PRIVATE_SCHEMA_CHANGED')
    elif drift == 'runtime':
        runtime.upgrade.assert_runtime_boundary.side_effect = s.StaticError('CRM_RUNTIME_CHANGED')
    elif drift == 'credentials':
        runtime.upgrade.stable_authorization.side_effect = [{'opaque': 'generation-and-ciphertext'}, {'opaque': 'rotated'}]
    elif drift == 'roles':
        runtime.verifier.current_roles.return_value = (None, {'api': {'id': 'restarted'}})
    else:
        runtime.verifier.stable_digests.side_effect = [{'items': 'manual-note-hash'}, {'items': 'changed'}]
    with pytest.raises(s.StaticError):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    runtime.base.atomic_nginx.assert_not_called()
    assert runtime.current_nginx == [runtime.original] and runtime.commands == []


def test_failed_new_public_check_restores_only_original_nginx(frozen):
    runtime = make_runtime(frozen)
    runtime.base.public_check.side_effect = [None, s.StaticError('NEW_PUBLIC_ASSET_FAILED'), None]
    with pytest.raises(s.StaticError, match='NEW_PUBLIC_ASSET_FAILED'):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    assert runtime.current_nginx == [runtime.original]
    assert runtime.commands == [['nginx', '-t'], ['systemctl', 'reload', 'nginx']] * 2
    assert json.loads((runtime.release / 'static-state.json').read_bytes())['phase'] == 'STRIPE_REPORT_UI_STATIC_ROLLED_BACK'


def test_concurrent_nginx_change_blocks_rollback_overwrite(frozen):
    runtime = make_runtime(frozen)
    def public_check(*ignored, **kwargs):
        if runtime.current_nginx == [runtime.changed]:
            runtime.current_nginx[0] = b'other reviewed release'
            raise s.StaticError('CONCURRENT_RELEASE')
    runtime.base.public_check.side_effect = public_check
    with pytest.raises(s.StaticError, match='CONCURRENT_RELEASE'):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    assert runtime.current_nginx == [b'other reviewed release']
    assert runtime.base.atomic_nginx.call_count == 1
    assert json.loads((runtime.release / 'static-state.json').read_bytes())['phase'] == 'STRIPE_REPORT_UI_STATIC_ROLLBACK_NEEDS_REVIEW'


def test_safe_errors_do_not_disclose_raw_commands_or_credentials():
    assert s.safe_error(RuntimeError('rk_live_SECRET output')) == 'STATIC_RELEASE_REJECTED'
    assert s.safe_error(s.StaticError('SAFE_UPPERCASE_CODE')) == 'SAFE_UPPERCASE_CODE'
    assert s.safe_error(s.StaticError('SELECT secret FROM private_connections')) == 'STATIC_RELEASE_REJECTED'
