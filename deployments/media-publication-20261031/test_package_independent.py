"""Independent package/phase boundary checks; no real Git or remote execution."""
import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile

import pytest


HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


b = load('publication_independent_package', 'build_payload.py')
m = load('publication_independent_commands', 'make_commands.py')
CARRIER, SOURCE, VERSION = 'c' * 40, 'd' * 40, 'e' * 12
PROOF, REVIEW = 'a' * 64, 'b' * 64


def summary(r):
    return {
        'stage': 'MEDIA_PUBLICATION_PREFLIGHT_CAPTURED', 'source_sha': r.BASE_SOURCE,
        'frontend_version': r.BASE_FRONTEND, 'schema_revision': r.OLD_REVISION,
        'table_count': 129, 'deployed_sha256': r.BASE_DEPLOYED_SHA,
        'scheduler_enabled_receipt_sha256': r.BASE_ENABLED_SHA, 'scheduler_enabled': True,
        'scheduler_activation_from': r.ACTIVATION_FROM, 'gbp_feature_enabled': True,
        'callback_logging_protection_retained': True, 'private_boundary_verified': True,
        'host_docker_timestamp_parser_verified': True, 'credential_content_read': False,
        'private_content_read': False, 'executed_business_writes': False,
        'sha256': PROOF, 'path': '/opt/t24-crm/releases/media-publication-preflight-' + PROOF[:12] + '.json',
    }


@pytest.fixture
def command_data(tmp_path, monkeypatch):
    directory = tmp_path / 'new-tools'; (directory / 'artifacts').mkdir(parents=True)
    for name in ('release.py', 'preflight.py'): (directory / name).write_bytes((HERE / name).read_bytes())
    payload = b'SYNTHETIC_ONLY_PAYLOAD'
    (directory / 'artifacts/payload.tar.gz').write_bytes(payload)
    manifest = {
        'source_sha': SOURCE, 'frontend_version': VERSION, 'old_schema_revision': m.r.OLD_REVISION,
        'schema_revision': m.r.NEW_REVISION, 'preflight_sha256': PROOF,
        'database_migration': True, 'production_seed_rows': False,
        'payload_sha256': m.H(payload), 'frontend_freeze_sha256': m.r.FRONTEND_FREEZE_SHA,
        'backend_freeze_sha256': m.r.BACKEND_FREEZE_SHA,
    }
    (directory / 'artifacts/manifest.json').write_bytes(m.r.encoded(manifest))
    monkeypatch.setattr(m, 'HERE', directory); monkeypatch.setattr(m.r, 'SOURCE_SHA', SOURCE); monkeypatch.setattr(m.r, 'FRONTEND', VERSION)
    calls = []
    def fake_git(args, **kwargs):
        calls.append(args)
        assert args[0] == 'git'
        if args[1] == 'rev-parse': return b'SYNTHETIC_APP_TREE\n'
        assert args[1] == 'show' and args[2].startswith(CARRIER + ':' + m.DIRECTORY + '/')
        return (directory / args[2].split(':' + m.DIRECTORY + '/', 1)[1]).read_bytes()
    monkeypatch.setattr(m.subprocess, 'check_output', fake_git)
    prepared = {
        'stage': 'MEDIA_PUBLICATION_PREPARED_OFFLINE_VERIFIED', 'source_sha': SOURCE,
        'frontend_version': VERSION, 'old_schema_revision': m.r.OLD_REVISION,
        'schema_revision': m.r.NEW_REVISION, 'preflight_sha256': PROOF,
        'manifest_sha256': m.H((directory / 'artifacts/manifest.json').read_bytes()),
        'payload_sha256': m.H(payload), '_canonical_sha256': REVIEW,
    }
    for key in ('offline_additive_only', 'offline_original_rows_unchanged', 'offline_new_table_empty',
                'offline_own_metadata_exact', 'actual_python310_verified', 'exact_media_google_routes',
                'offline_network_none', 'offline_credentials_absent', 'offline_workers_off',
                'scheduler_on_and_cutoff_preserved', 'host_docker_timestamp_parser_verified'):
        prepared[key] = True
    for key in ('provider_requests', 'production_database_migrated', 'sequence_written_by_tool'):
        prepared[key] = False
    return summary(m.r), prepared, calls


def argv_from_wrapper(command):
    code = command.split("<<'PUBLICATION'\n", 1)[1].rsplit('PUBLICATION\n', 1)[0]
    tree = ast.parse(code)
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                           and target.value.id == 'sys' and target.attr == 'argv' for target in node.targets)]
    assert len(assignments) == 1 and isinstance(assignments[0].value, ast.List)
    values = []
    for item in assignments[0].value.elts[1:]:
        if isinstance(item, ast.Starred): values.extend(ast.literal_eval(item.value))
        else: values.append(ast.literal_eval(item))
    return values, code


def test_all_phase_arguments_are_literal_fixed_and_share_exact_proof_and_payload(command_data):
    value, prepared, calls = command_data
    commands, pins = m.generate(CARRIER, value, prepared)
    assert set(commands) == {'prepare-command.sh', 'activate-command.sh', 'recover-command.sh'}
    expected_common = [
        '--release', '/opt/t24-crm/releases/media-publication-' + SOURCE[:12] + '-20261031',
        '--manifest-sha256', prepared['manifest_sha256'], '--payload-sha256', prepared['payload_sha256'],
        '--preflight', value['path'], '--preflight-sha256', PROOF,
    ]
    for phase in ('prepare', 'activate', 'recover'):
        args, code = argv_from_wrapper(commands[phase + '-command.sh'])
        expected = ['--phase', phase, *expected_common]
        if phase != 'prepare': expected += ['--review-sha256', REVIEW]
        assert args == expected
        assert '--env-file' not in code and 'subprocess' not in code and 'os.system' not in code
    assert pins['prepared_sha256'] == REVIEW and pins['executed'] is False
    assert len(calls) == 6


def test_prepare_does_not_generate_any_switch_without_actual_review(command_data):
    value, _, _ = command_data
    commands, pins = m.generate(CARRIER, value)
    assert set(commands) == {'prepare-command.sh'} and pins['prepared_sha256'] is None
    args, code = argv_from_wrapper(commands['prepare-command.sh'])
    assert '--review-sha256' not in args
    assert code.index('os.geteuid()==0') < code.index('opener.open') < code.index('release.mkdir')
    assert 'ProxyHandler({})' in code and "'https://raw.githubusercontent.com/billy285/t24-crm/'" in code
    assert 'response.status==200 and response.geturl()==url' in code
    assert 'response.read(size+1)' in code and 'len(body)==size and H(body)==expected' in code


@pytest.mark.parametrize('key,value', [
    ('offline_new_table_empty', 1), ('offline_workers_off', 1), ('scheduler_on_and_cutoff_preserved', 1),
    ('provider_requests', 0), ('production_database_migrated', 0), ('sequence_written_by_tool', 0),
    ('_canonical_sha256', 'B' * 64), ('_canonical_sha256', 'review-later'),
])
def test_review_flags_and_hashes_do_not_use_truthy_coercion(command_data, key, value):
    summary_value, prepared, _ = command_data; prepared[key] = value
    with pytest.raises(RuntimeError): m.generate(CARRIER, summary_value, prepared)


@pytest.mark.parametrize('key,value', [('scheduler_enabled', 1), ('private_content_read', 0), ('executed_business_writes', 0), ('stage', 'MEDIA_PUBLICATION_READONLY_PREFLIGHT')])
def test_summary_requires_captured_readonly_exact_boolean_on_state(key, value):
    data = summary(b.r); data[key] = value
    with pytest.raises(RuntimeError): b.r.validate_summary(data)


@pytest.mark.parametrize('carrier', ['HEAD', 'main', 'c' * 39, 'C' * 40, 'c' * 40 + ';id'])
def test_invalid_carrier_rejected_before_any_git_or_file_access(command_data, carrier):
    value, _, calls = command_data
    with pytest.raises(RuntimeError): m.generate(carrier, value)
    assert calls == []


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo', 'duplicate'])
def test_git_archive_inventory_rejects_special_or_duplicate_members(monkeypatch, kind):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        if kind == 'duplicate':
            for content in (b'first', b'second'):
                item = tarfile.TarInfo('app/backend/one.py'); item.size = len(content); archive.addfile(item, io.BytesIO(content))
        else:
            item = tarfile.TarInfo('app/backend/one.py')
            item.type = {'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE, 'fifo': tarfile.FIFOTYPE}[kind]
            item.linkname = '/synthetic/private-content'; archive.addfile(item)
    monkeypatch.setattr(b, 'git', lambda *args: buffer.getvalue())
    with pytest.raises(RuntimeError): b.inventory(SOURCE)


@pytest.mark.parametrize('path', ['runtime.env', '.env', '/assets/test.js', 'assets/../key.js', 'assets/.private/key.js', 'assets//key.js', r'assets\key.js', 'README.md', 'assets/config.json'])
def test_static_payload_names_reject_secret_config_and_noncanonical_paths(path):
    assert b.static_path(path) is False


def test_zero_version_pin_rejects_generator_before_files_even_with_real_source(command_data, monkeypatch):
    value, _, calls = command_data; monkeypatch.setattr(m.r, 'FRONTEND', '0' * 12)
    with pytest.raises(RuntimeError, match='ACTUAL_REVIEWED_SOURCE_AND_FRONTEND_REQUIRED'): m.generate(CARRIER, value)
    assert calls == []


@pytest.fixture
def build_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); monkeypatch.setattr(b.r, 'SOURCE_SHA', SOURCE); monkeypatch.setattr(b.r, 'FRONTEND', VERSION)
    after = {}; before = {}
    for name in b.r.SOURCE_FILES:
        path = Path(name); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(('synthetic ' + name).encode())
        after[name] = b.H(path.read_bytes())
        if name != 'app/backend/' + b.r.MIGRATION: before[name] = b.H(('old ' + name).encode())
    monkeypatch.setattr(b, 'inventory', lambda ref: before if ref == b.r.BASE_SOURCE else after)
    monkeypatch.setattr(b, 'frozen_sources', lambda _: None)
    monkeypatch.setattr(b, 'frontend_version', lambda: VERSION)
    value = summary(b.r); value['backend_changed_before'] = {name: before.get('app/backend/' + name) for name in b.r.BACKEND_FILES}
    dist = Path('app/frontend/dist'); dist.mkdir(parents=True)
    (dist / 'index.html').write_text('synthetic'); (dist / 'app-version.json').write_text(json.dumps({'version': VERSION}))
    return value, tmp_path, dist


@pytest.mark.parametrize('kind', ['dist_root', 'app_version'])
def test_builder_rejects_dist_links_before_reading_target_content(build_paths, monkeypatch, kind):
    value, root, dist = build_paths
    private = root / 'synthetic-private'; private.mkdir()
    if kind == 'dist_root':
        dist.rename(private / 'contents'); dist.symlink_to(private / 'contents', target_is_directory=True)
    else:
        target = private / 'content.json'; target.write_text(json.dumps({'version': VERSION}))
        (dist / 'app-version.json').unlink(); (dist / 'app-version.json').symlink_to(target)
    read = Path.read_bytes
    def guarded_read(path):
        if path == dist / 'app-version.json': pytest.fail('opened linked version content before rejecting path')
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    opened = os.open
    def guarded_open(path, *args, **kwargs):
        if Path(path).absolute() == (dist / 'app-version.json').absolute(): pytest.fail('opened linked version target through os.open')
        return opened(path, *args, **kwargs)
    monkeypatch.setattr(b.r.os, 'open', guarded_open)
    with pytest.raises(RuntimeError): b.build(value)


@pytest.mark.parametrize('kind', ['release_leaf', 'artifacts_ancestor'])
def test_generator_rejects_local_carrier_links_before_reading_target_content(command_data, tmp_path, monkeypatch, kind):
    value, _, _ = command_data; directory = m.HERE
    if kind == 'release_leaf':
        path = directory / 'release.py'; target = tmp_path / 'synthetic-private-release.py'
        target.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(target)
        forbidden = path
    else:
        target = tmp_path / 'synthetic-private-artifacts'; (directory / 'artifacts').rename(target)
        (directory / 'artifacts').symlink_to(target, target_is_directory=True)
        forbidden = directory / 'artifacts/manifest.json'
    read = Path.read_bytes
    def guarded_read(path):
        if path == forbidden: pytest.fail('opened linked local member before rejecting path')
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    opened = os.open
    def guarded_open(path, *args, **kwargs):
        if Path(path).absolute() == forbidden.absolute(): pytest.fail('opened linked local member through os.open')
        return opened(path, *args, **kwargs)
    monkeypatch.setattr(m.r.os, 'open', guarded_open)
    with pytest.raises(RuntimeError): m.generate(CARRIER, value)


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo', 'directory'])
def test_local_reader_rejects_noncanonical_or_nonregular_input_before_open(tmp_path, monkeypatch, kind):
    source = tmp_path / 'synthetic-source'; source.write_bytes(b'SYNTHETIC_ONLY')
    path = tmp_path / 'input'
    if kind == 'symlink': path.symlink_to(source)
    if kind == 'hardlink': os.link(source, path)
    if kind == 'fifo': os.mkfifo(path)
    if kind == 'directory': path.mkdir()
    opened = os.open
    def guarded_open(name, *args, **kwargs):
        if Path(name).absolute() == path.absolute(): pytest.fail('opened rejected local input')
        return opened(name, *args, **kwargs)
    monkeypatch.setattr(b.r.os, 'open', guarded_open)
    with pytest.raises(RuntimeError, match='REGULAR_CANONICAL_LOCAL_INPUT_REQUIRED'): b.r.local_bytes(path)


def test_local_reader_rejects_oversize_regular_content_with_bounded_read(tmp_path):
    path = tmp_path / 'synthetic-large'; path.write_bytes(b'SYNTHETIC_ONLY' * 8)
    with pytest.raises(RuntimeError, match='LOCAL_INPUT_READ_DRIFT'): b.r.local_bytes(path, maximum=4)
