"""In-memory wrapper generation against immutable synthetic carrier objects."""
import ast
import importlib.util
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('mobile_static_commands_tested', HERE / 'make_commands.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
r = c.r


@pytest.fixture
def package(tmp_path, monkeypatch):
    for key, value in {'PREFLIGHT_CODE_SHA': c.H(b'SYNTHETIC_PREFLIGHT'), 'PREFLIGHT_SHA': '2' * 64,
                       'APPLICATION_FREEZE_SHA': '3' * 64, 'SOURCE_SHA':'b'*40, 'FRONTEND':'a'*12, 'CHANGED_SOURCE_HASHES': {name:'4'*64 for name in r.FILES}}.items():
        monkeypatch.setattr(r, key, value)
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'release.py').write_bytes(b'SYNTHETIC_HELPER_NO_EXECUTION')
    (tmp_path / 'preflight.py').write_bytes(b'SYNTHETIC_PREFLIGHT')
    (tmp_path / 'artifacts/payload.tar.gz').write_bytes(b'SYNTHETIC_STATIC_ONLY')
    manifest = {'stage': 'MEDIA_META_MONTHLY_UI_STATIC_PAYLOAD', 'source_sha': r.SOURCE_SHA,
        'backend_source_sha': r.BASE_SOURCE, 'baseline_source_sha': r.BASE_SOURCE,
        'frontend_version': r.FRONTEND, 'baseline_frontend_version': r.BASE_FRONTEND,
        'schema_revision': r.HEAD, 'table_count': 162, 'preflight_sha256': r.PREFLIGHT_SHA,
        'application_freeze_sha256': r.APPLICATION_FREEZE_SHA,
        'payload_sha256': c.H((tmp_path / 'artifacts/payload.tar.gz').read_bytes()),
        'changed_source_files': r.CHANGED_SOURCE_HASHES,
        'protected_source_inventory': {'app/protected/' + str(i): '5' * 64 for i in range(1001)},
        'files': {'static/index.html': '6' * 64, 'static/app-version.json': '7' * 64},
        **{x: True for x in r.TRUE_FLAGS}, **{x: False for x in r.FALSE_FLAGS}}
    (tmp_path / 'artifacts/manifest.json').write_bytes(r.encoded(manifest))
    monkeypatch.setattr(c, 'HERE', tmp_path)
    state = {'tree_drift': False, 'member_drift': False, 'git': []}
    def git(argv):
        state['git'].append(argv)
        assert argv[0] == 'git' and argv[1] in {'show', 'rev-parse'}
        if argv[1] == 'rev-parse':
            return b'WRONG_TREE' if state['tree_drift'] and argv[2].startswith('a' * 40) else b'IMMUTABLE_TREE'
        prefix = 'a' * 40 + ':' + c.DIRECTORY + '/'; assert argv[2].startswith(prefix)
        name = argv[2][len(prefix):]; body = (tmp_path / name).read_bytes()
        return body + b'DRIFT' if state['member_drift'] and name == 'release.py' else body
    monkeypatch.setattr(c.subprocess, 'check_output', git)
    summary = {'stage': 'MEDIA_META_MONTHLY_STATIC_PREFLIGHT_CAPTURED', 'sha256': r.PREFLIGHT_SHA,
        'path': '/opt/t24-crm/releases/media-meta-monthly-static-preflight-' + r.PREFLIGHT_SHA[:12] + '.json'}
    return tmp_path, summary, state, manifest


def prepared(package):
    path, _, _, _ = package
    return {'stage': 'MEDIA_META_MONTHLY_UI_STATIC_PREPARED', 'source_sha': r.SOURCE_SHA,
        'backend_source_sha': r.BASE_SOURCE, 'frontend_version': r.FRONTEND,
        'manifest_sha256': c.H((path / 'artifacts/manifest.json').read_bytes()),
        'payload_sha256': c.H((path / 'artifacts/payload.tar.gz').read_bytes()),
        'preflight_sha256': r.PREFLIGHT_SHA,
        'public_root': '/var/www/t24-crm-public/' + r.SCOPE + '-' + r.SOURCE_SHA[:12] + '-20261102',
        'public_inventory_sha256': '7' * 64, 'nginx_next_sha256': '8' * 64,
        'boundary': {'runtime': r.RUNTIME, **{key: True for key in (
            'original162_rows_preserved', 'backend_source_unchanged', 'private_boundary_preserved',
            'credentials_preserved', 'content_security_policy_unchanged')}, **{key: '9' * 64 for key in (
            'rows_sha256', 'schema_sha256', 'environment_sha256', 'ops_environment_sha256')}}, 'static_only': True,
        **{x: False for x in ('database_writes', 'container_restarts', 'schema_changes', 'permissions_changes', 'provider_or_publication_actions')}}


def embedded(command):
    code = command.split("<<'WORKFLOW'\n", 1)[1].rsplit('\nWORKFLOW', 1)[0]
    return code, ast.parse(code)


def test_prepare_only_four_exact_carrier_members_without_receipt(package):
    path, summary, state, _ = package; before = set(path.rglob('*'))
    commands, pins = c.generate('a' * 40, summary)
    assert set(commands) == {'prepare-command.sh'} and pins['prepared_sha256'] is None
    assert set(pins['members']) == {'release.py', 'preflight.py', 'artifacts/manifest.json', 'artifacts/payload.tar.gz'}
    assert pins['executed'] is False and set(path.rglob('*')) == before
    code, _ = embedded(commands['prepare-command.sh'])
    assert "'--phase','prepare'" in code and "'--phase','activate'" not in code
    assert 'ProxyHandler({})' in code and 'CARRIER_REDIRECT_REJECTED' in code
    assert 'EXACT_CARRIER_BYTES_REQUIRED' in code and 'FRESH_RELEASE_REQUIRED' in code
    assert all(call[1] in {'show', 'rev-parse'} for call in state['git'])


def test_switch_only_after_actual_canonical_receipt_and_exact_phase_hash(package):
    _, summary, _, _ = package; body = r.encoded(prepared(package)); receipt = c.canonical_prepared(body)
    commands, pins = c.generate('a' * 40, summary, receipt)
    assert set(commands) == {'prepare-command.sh', 'activate-command.sh', 'recover-command.sh'}
    assert pins['prepared_sha256'] == c.H(body)
    for phase in ('activate', 'recover'):
        command = commands[phase + '-command.sh']; code, _ = embedded(command)
        assert "'--phase','" + phase + "'" in code and c.H(body) in code
        assert '--review-sha256' in code and 'EXACT_RELEASE_HELPER_REQUIRED' in code
        assert 'urllib' not in code and len(command.encode()) < 11000


@pytest.mark.parametrize('attack', ['tree_drift', 'member_drift'])
def test_carrier_tree_or_one_member_drift_rejected(package, attack):
    _, summary, state, _ = package; state[attack] = True
    with pytest.raises(RuntimeError): c.generate('a' * 40, summary)


@pytest.mark.parametrize('carrier', ['main', 'a' * 39, 'a' * 41, 'A' * 40, 'a' * 40 + ';bad'])
def test_only_exact_immutable_carrier_accepted(package, carrier):
    with pytest.raises(RuntimeError, match='EXACT_IMMUTABLE_CARRIER_REQUIRED'): c.generate(carrier, package[1])


@pytest.mark.parametrize('field,value', [('stage', 'OTHER'), ('sha256', '0' * 64), ('path', '/unknown')])
def test_wrong_preflight_rejected_before_git_read(package, field, value):
    _, summary, state, _ = package; summary[field] = value
    with pytest.raises(RuntimeError): c.generate('a' * 40, summary)
    assert state['git'] == []


@pytest.mark.parametrize('field', ['backend_changes', 'database_writes', 'container_restarts', 'permissions_changes', 'content_security_policy_changes'])
def test_mutation_flags_in_manifest_block_generation(package, field):
    path, summary, _, manifest = package; manifest[field] = True
    (path / 'artifacts/manifest.json').write_bytes(r.encoded(manifest))
    with pytest.raises(RuntimeError, match='NO_BACKEND_DATABASE_RUNTIME_OR_PERMISSION_MUTATIONS_ALLOWED'): c.generate('a' * 40, summary)


def test_prepared_mutation_claim_cannot_generate_switches(package):
    value = prepared(package); value['database_writes'] = True
    with pytest.raises(RuntimeError): c.generate('a' * 40, package[1], c.canonical_prepared(r.encoded(value)))


def test_prepared_missing_privacy_proof_cannot_generate_switches(package):
    value = prepared(package); value['boundary']['private_boundary_preserved'] = False
    with pytest.raises(RuntimeError, match='ALL_STATIC_PREPARED_PROTECTIONS_REQUIRED'):
        c.generate('a' * 40, package[1], c.canonical_prepared(r.encoded(value)))


def test_canonical_envelope_strips_only_marker_and_pins_actual_bytes():
    value = {'stage': 'synthetic'}; body = r.encoded(value)
    assert c.canonical_prepared(body) == {**value, '_canonical_sha256': c.H(body)}
    assert c.canonical_prepared(json.dumps({**value, 'receipt_sha256': c.H(body)}).encode())['_canonical_sha256'] == c.H(body)
    for bad in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1}', r.encoded({'_canonical_sha256': '0' * 64}),
                json.dumps({**value, 'receipt_sha256': '0' * 64}).encode()):
        with pytest.raises(RuntimeError): c.canonical_prepared(bad)


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'size'])
def test_local_members_reject_links_or_overflow_before_packaging(tmp_path, kind):
    source = tmp_path / 'source'; source.write_bytes(b'known')
    if kind == 'symlink': target = tmp_path / 'target'; target.symlink_to(source)
    elif kind == 'hardlink': target = tmp_path / 'target'; os.link(source, target)
    else: target = source
    with pytest.raises(RuntimeError): c.local_bytes(target, 2 if kind == 'size' else 100)
