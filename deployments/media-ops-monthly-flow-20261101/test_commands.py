"""Synthetic immutable carrier/receipt attacks; never execute a server phase."""
import ast
import copy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('merchant_view_command_tests', HERE/'make_commands.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)


def test_pending_application_freeze_prevents_commands_before_any_git_or_file_read(monkeypatch):
    monkeypatch.setattr(c.r, 'APPLICATION_FREEZE_SHA', None)
    monkeypatch.setattr(c.subprocess, 'check_output', lambda *args:pytest.fail('No Git before reviewed pins'))
    with pytest.raises(RuntimeError): c.generate('f'*40, {})


def test_prepared_transport_envelope_pins_actual_canonical_server_file():
    value = {'stage':'SYNTHETIC_REVIEWED_PREPARED', 'reviewed':True, 'original_id':'a'*64}
    body = c.r.encoded(value); sha = c.H(body)
    assert c.canonical_prepared(body) == c.canonical_prepared(json.dumps({**value,'receipt_sha256':sha}).encode()) == {**value, '_canonical_sha256':sha}
    assert sha != c.H(json.dumps({**value,'receipt_sha256':sha}).encode())


@pytest.mark.parametrize('body', [b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'{"_canonical_sha256":"forged"}',
    b'{"a": 1}', b'{"a":1,"receipt_sha256":"'+b'0'*64+b'"}'])
def test_noncanonical_malformed_or_forged_prepared_input_is_rejected(body):
    with pytest.raises((ValueError, RuntimeError)): c.canonical_prepared(body)


@pytest.fixture
def carrier(monkeypatch):
    r = c.r; monkeypatch.setattr(r, 'APPLICATION_FREEZE_SHA', 'a'*64)
    monkeypatch.setattr(r, 'SOURCE_SHA', 'b'*40)
    monkeypatch.setattr(r, 'FRONTEND', 'c'*12)
    monkeypatch.setattr(r, 'FRONTEND_FILES', frozenset({'app/frontend/src/synthetic.tsx'}))
    monkeypatch.setattr(r, 'SOURCE_FILES', frozenset('app/backend/'+name for name in r.BACKEND_FILES)|r.FRONTEND_FILES|r.TEST_FILES)
    monkeypatch.setattr(r, 'FINAL_BACKEND_HASHES', {name:'d'*64 for name in r.BACKEND_FILES})
    summary={'sha256':'e'*64,'path':'/opt/t24-crm/releases/media-ops-monthly-flow-preflight-'+('e'*12)+'.json'}
    monkeypatch.setattr(r,'pins_ready',lambda:None);monkeypatch.setattr(r,'validate_summary',lambda value:None)
    values = {'release.py':b'SYNTHETIC REVIEWED SERVER TOOL\n', 'preflight.py':b'SYNTHETIC REVIEWED PREFLIGHT\n',
        'artifacts/payload.tar.gz':b'SYNTHETIC REVIEWED PAYLOAD'}
    monkeypatch.setattr(r, 'PREFLIGHT_SHA', c.H(values['preflight.py']))
    manifest = {'source_sha':r.SOURCE_SHA, 'frontend_version':r.FRONTEND,
        'baseline_source_sha':r.BASE_SOURCE, 'baseline_frontend_version':r.BASE_FRONTEND,
        'schema_revision':r.NEW_REVISION, 'old_schema_revision':r.OLD_REVISION, 'additive_tables':sorted(r.NEW_TABLES),
        'preflight_sha256':summary['sha256'], 'payload_sha256':c.H(values['artifacts/payload.tar.gz']),
        'application_freeze_sha256':r.APPLICATION_FREEZE_SHA, 'changed_source_files':sorted(r.SOURCE_FILES),
        'backend_before':dict(r.ORIGINAL_BACKEND_HASHES), 'backend_after':dict(r.FINAL_BACKEND_HASHES),
        **{key:True for key in r.TRUE_FLAGS}, **{key:False for key in r.FALSE_FLAGS}}
    values['artifacts/manifest.json'] = r.encoded(manifest)
    def local(path, maximum=16*1024**2):
        body = values[str(Path(path).relative_to(HERE))]
        assert len(body) <= maximum
        return body
    def git(argv):
        assert argv[0] == 'git'
        if argv[1] == 'rev-parse': return b'IDENTICAL_COMMITTED_APPLICATION_TREE\n'
        assert argv[1] == 'show'
        path = argv[2].split(':',1)[1].removeprefix(c.DIRECTORY+'/')
        return values[path]
    monkeypatch.setattr(r, 'local_bytes', local); monkeypatch.setattr(c.subprocess, 'check_output', git)
    checked = []
    def prepared(value, manifest_sha, payload_sha, proof_sha):
        checked.append((copy.deepcopy(value), manifest_sha, payload_sha, proof_sha))
        r.need(value.get('reviewed') is True, 'SYNTHETIC_EXACT_PREPARED_REVIEW_REQUIRED')
    monkeypatch.setattr(r, 'validate_prepared', prepared)
    return values, summary, manifest, checked


def python_body(text): return text.split("<<'WORKFLOW'\n",1)[1].rsplit('\nWORKFLOW',1)[0]


def test_prepare_downloads_only_four_exact_members_and_emits_no_switch_without_review(carrier):
    values, summary, _, checked = carrier
    commands, pins = c.generate('f'*40, summary)
    assert set(commands) == {'prepare-command.sh'} and checked == [] and pins['executed'] is False
    assert set(pins['members']) == {'release.py','preflight.py','artifacts/manifest.json','artifacts/payload.tar.gz'}
    text = commands['prepare-command.sh']; ast.parse(python_body(text))
    assert len(text.encode()) < 11000 and 'ProxyHandler({})' in text and 'CARRIER_REDIRECT_REJECTED' in text
    assert "'/opt/t24-crm/releases/media-ops-monthly-flow-bbbbbbbbbbbb-20261101'" in text
    assert "'--phase','prepare'" in text and 'APP_SECRET=' not in text and 'TOKEN_KEY=' not in text
    assert 'files.pythonhosted.org' not in text and 'pip install' not in text
    assert pins['members']['artifacts/payload.tar.gz'][1] == c.H(values['artifacts/payload.tar.gz'])


def test_switch_wrappers_pin_canonical_actual_server_prepared_receipt_and_all_scope_hashes(carrier):
    values, summary, _, checked = carrier
    prepared = {'stage':'SYNTHETIC_REVIEWED_PREPARED','reviewed':True}; sha = c.H(c.r.encoded(prepared))
    parsed = c.canonical_prepared(json.dumps({**prepared,'receipt_sha256':sha}).encode())
    commands, pins = c.generate('f'*40, summary, parsed)
    assert set(commands) == {'prepare-command.sh','activate-command.sh','recover-command.sh'}
    assert pins['prepared_sha256'] == sha and checked[0][1:] == (
        c.H(values['artifacts/manifest.json']), c.H(values['artifacts/payload.tar.gz']), summary['sha256'])
    for phase in ('activate', 'recover'):
        text = commands[phase+'-command.sh']; ast.parse(python_body(text))
        assert len(text.encode()) < 11000 and "'--review-sha256',"+repr(sha) in text
        assert "'--phase',"+repr(phase) in text and 'PROTECTED_HELPER_REQUIRED' in text
        assert 'EXACT_RELEASE_HELPER_REQUIRED' in text and 'urllib.request' not in text
        assert 'APP_SECRET=' not in text and 'TOKEN_KEY=' not in text
    assert c.H(json.dumps({**prepared,'receipt_sha256':sha}).encode()) not in commands['activate-command.sh']


@pytest.mark.parametrize('kind', ['application_tree','uncommitted_member','preflight_pin','payload_hash','freeze_hash','source_delta','backend_after',
    'schema','new_table','database_migration','dependencies','credentials','environment','execution','scheduler','provider_requests'])
def test_drift_cannot_generate_an_approvable_command(carrier, monkeypatch, kind):
    values, summary, manifest, _ = carrier
    if kind in {'application_tree','uncommitted_member'}:
        original = c.subprocess.check_output
        def git(argv):
            body = original(argv)
            if kind == 'application_tree' and argv[1] == 'rev-parse' and argv[2].startswith('f'*40): return b'OTHER_APPLICATION_TREE\n'
            if kind == 'uncommitted_member' and argv[1] == 'show' and argv[2].endswith('/release.py'): return body+b'changed'
            return body
        monkeypatch.setattr(c.subprocess, 'check_output', git)
    elif kind == 'preflight_pin': monkeypatch.setattr(c.r, 'PREFLIGHT_SHA', '0'*64)
    else:
        if kind == 'payload_hash': manifest['payload_sha256'] = '0'*64
        elif kind == 'freeze_hash': manifest['application_freeze_sha256'] = '0'*64
        elif kind == 'source_delta': manifest['changed_source_files'].append('app/backend/finance.py')
        elif kind == 'backend_after': manifest['backend_after']['services/meta_operations_provider.py'] = '0'*64
        elif kind == 'schema': manifest['schema_revision'] = 'unexpected'
        elif kind == 'new_table': manifest['additive_tables'] = ['forbidden_table']
        else:
            key = {'database_migration':'database_migration','dependencies':'dependencies_changed','credentials':'credentials_included',
                'environment':'runtime_environment_changed','execution':'operations_execution_enabled','scheduler':'operations_scheduler_enabled',
                'provider_requests':'provider_requests'}[kind]
            manifest[key] = key!='database_migration'
        values['artifacts/manifest.json'] = c.r.encoded(manifest)
    with pytest.raises(RuntimeError): c.generate('f'*40, summary)


def test_rejected_prepared_receipt_never_emits_a_switch_command(carrier):
    _, summary, _, checked = carrier
    value = c.canonical_prepared(c.r.encoded({'stage':'SYNTHETIC','reviewed':False}))
    with pytest.raises(RuntimeError, match='SYNTHETIC_EXACT_PREPARED_REVIEW_REQUIRED'): c.generate('f'*40, summary, value)
    assert len(checked) == 1
