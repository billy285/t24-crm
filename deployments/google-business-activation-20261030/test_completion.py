import ast
import copy
import json
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core as c
import activation as a
import preflight
import completion as x
import make_completion_command as g
from test_activation import store, switch_fixture, synthetic_info, synthetic_values, synthetic_runtime


@pytest.fixture
def fixture(switch_fixture, monkeypatch):
    f = switch_fixture
    monkeypatch.setattr(x, 'ORIGINAL_ID', f.original['Id'])
    f.original['HostConfig']['OomKillDisable'] = None
    f.containers[f.original['Id']]['HostConfig']['OomKillDisable'] = None
    path = a.attempt_root() / 'original-container.json'
    path.unlink(); c.write(path, f.original)
    candidate = copy.deepcopy(f.original)
    candidate.update(Id='2' * 64, Name='/' + a.CANDIDATE_NAME)
    candidate['HostConfig']['OomKillDisable'] = False
    candidate['Config']['Hostname'] = 'new-host'
    candidate['Config']['Env'] += [name + '=' + value for name, value in f.values.items()]
    candidate['State'] = {'Running': False, 'Status': 'created', 'StartedAt': '0001-01-01T00:00:00Z'}
    f.containers[candidate['Id']] = candidate
    f.candidate = candidate
    f.state = {'stage': 'GBP_CONFIG_CANDIDATE_CREATED', 'original_id': f.original['Id'],
        'candidate_name': a.CANDIDATE_NAME, 'candidate_id': candidate['Id'], 'image': c.IMAGE,
        'plan_sha256': x.PLAN_SHA, 'review_sha256': x.REVIEW_SHA}
    c.write(a.attempt_root() / 'switch-state.json', f.state)
    old_read = f.fake.read
    def read(path, expected=None):
        body = old_read(path, expected)
        if path == c.PRIOR / 'deployed.json':
            return json.dumps({**json.loads(body), 'crm': f.fake.runtime(f.original)}).encode()
        return body
    f.fake.read = read
    logging = {'crm': f.fake.runtime(f.original), 'active_nginx_config_sha256': f.active_hash}
    monkeypatch.setattr(a, '_switch_requirements', lambda args: (f.plan, logging))
    monkeypatch.setattr(x, 'arguments', lambda: {})
    monkeypatch.setattr(x, 'CREDENTIAL_SHA', c.H(c.read(c.ROOT / 'credential-receipt.json')))
    monkeypatch.setattr(preflight, 'proof', lambda **kw: {'crm': f.fake.runtime(f.original), 'active_nginx_config_sha256': f.active_hash})
    monkeypatch.setattr(x, 'verify_stopped_source', lambda *args: None)
    f.commands.clear()
    f.immutable_files = {path.name: path.read_bytes() for path in a.attempt_root().glob('*.json')}
    f.before_rows = copy.deepcopy(f.snapshots)
    return f


def assert_v3_and_rows_preserved(f):
    assert f.snapshots == f.before_rows
    assert all((a.attempt_root() / name).read_bytes() == body for name, body in f.immutable_files.items())
    assert len(f.containers) == 2
    assert not any(command[0] == 'create' or command[:2] in {('docker', 'rm'), ('docker', 'create')} for command in f.commands)


def test_audit_is_readonly_proves_actual_false_and_exports_no_credentials(fixture):
    result = x.audit()
    assert result['candidate_oom_key_present_exact_false'] is True
    assert result['original_oom_key_present_exact_null'] is True
    assert not x.root().exists() and not fixture.commands
    text = json.dumps(result)
    assert 'synthetic_test_secret' not in text and 'synthetic-original' not in text
    assert_v3_and_rows_preserved(fixture)


def test_actual_raw_clone_still_fails_frozen_guard_but_comparison_adapter_passes(fixture):
    with pytest.raises(c.GuardError, match='UNCHANGED_RUNTIME_CONFIGURATION_REQUIRED'):
        a.verify_clone(fixture.candidate, fixture.original, fixture.values, fixture.fake.runtime)
    before = copy.deepcopy(fixture.candidate)
    proxy = x.ExactDefaultRuntime(fixture.fake, fixture.original, fixture.candidate['Id'])
    a.verify_clone(fixture.candidate, fixture.original, fixture.values, proxy.runtime)
    assert fixture.candidate == before
    assert fixture.fake.runtime(fixture.candidate) != proxy.runtime(fixture.candidate)


@pytest.mark.parametrize('value', [True, 0, 1, None, 'false', [], {}])
def test_non_exact_false_candidate_is_denied_before_any_mutation(fixture, value):
    fixture.candidate['HostConfig']['OomKillDisable'] = value
    with pytest.raises(c.GuardError, match='EXACT_FALSE'):
        x.complete()
    assert not fixture.commands and not x.root().exists()
    assert_v3_and_rows_preserved(fixture)


def test_missing_candidate_key_is_denied(fixture):
    fixture.candidate['HostConfig'].pop('OomKillDisable')
    with pytest.raises(c.GuardError, match='EXACT_FALSE'):
        x.audit()
    assert not fixture.commands


@pytest.mark.parametrize('mutation', [
    lambda row: row['HostConfig'].__setitem__('Privileged', True),
    lambda row: row['HostConfig'].__setitem__('OomScoreAdj', 1),
    lambda row: row['Config'].__setitem__('Cmd', ['changed']),
    lambda row: row['Config']['Env'].__setitem__(0, 'KEEP=changed'),
    lambda row: row['Mounts'][0].__setitem__('RW', False),
    lambda row: row['NetworkSettings']['Networks']['bridge'].__setitem__('Aliases', ['changed']),
])
def test_every_other_setting_remains_strict_before_stop(fixture, mutation):
    mutation(fixture.candidate)
    with pytest.raises(c.GuardError): x.complete()
    assert not fixture.commands and not x.root().exists()


def test_complete_reuses_candidate_and_receipt_uses_actual_not_canonical_runtime(fixture):
    result = x.complete()
    assert result['enabled'] is True and result['same_existing_candidate_reused'] is True
    assert result['crm'] == fixture.fake.runtime(fixture.candidate)
    assert result['crm']['config'] != fixture.fake.runtime(fixture.original)['config']
    assert fixture.inspect('t24-crm')['Id'] == fixture.candidate['Id']
    assert not fixture.inspect(fixture.original['Id'])['State']['Running']
    assert fixture.candidate['HostConfig']['OomKillDisable'] is False
    assert_v3_and_rows_preserved(fixture)
    before = copy.deepcopy(fixture.commands)
    with pytest.raises(c.GuardError, match='EXISTING_COMPLETION'): x.complete()
    assert fixture.commands == before


def test_explicit_rollback_stops_and_retains_candidate_then_restores_original(fixture):
    x.complete()
    result = x.rollback()
    assert result['enabled'] is False and result['candidate_retained_stopped'] is True
    assert fixture.inspect('t24-crm')['Id'] == fixture.original['Id']
    assert fixture.candidate['Name'] == '/' + a.CANDIDATE_NAME and not fixture.candidate['State']['Running']
    assert_v3_and_rows_preserved(fixture)
    assert x.rollback()['receipt_sha256'] == result['receipt_sha256']


@pytest.mark.parametrize('failure', ['stop', 'rename-original', 'rename-candidate', 'start', 'verify', 'rows'])
def test_failure_at_each_stage_restores_original_without_deleting_candidate(fixture, monkeypatch, failure):
    old_run = c.run
    used = []
    def run(args, code, **kwargs):
        matches = ((failure == 'stop' and args[:2] == ['docker', 'stop']) or
            (failure == 'rename-original' and args[:3] == ['docker', 'rename', fixture.original['Id']]) or
            (failure == 'rename-candidate' and args[:3] == ['docker', 'rename', fixture.candidate['Id']]) or
            (failure == 'start' and args[:3] == ['docker', 'start', fixture.candidate['Id']]))
        if matches and not used:
            used.append(True);raise c.GuardError('INJECTED_DOCKER_FAILURE')
        return old_run(args, code, **kwargs)
    monkeypatch.setattr(c, 'run', run)
    old_verify = a.verify_active
    def verify(*args, **kwargs):
        if failure == 'verify': raise c.GuardError('INJECTED_POST_START_FAILURE')
        old_verify(*args, **kwargs)
        if failure == 'rows': fixture.snapshots['payments'].append({'id': 9, 'amount': 99})
    monkeypatch.setattr(a, 'verify_active', verify)
    with pytest.raises(c.GuardError): x.complete()
    assert fixture.inspect('t24-crm')['Id'] == fixture.original['Id']
    assert fixture.inspect('t24-crm')['State']['Running'] is True
    assert fixture.candidate['Name'] == '/' + a.CANDIDATE_NAME
    assert fixture.candidate['State']['Running'] is False
    if failure == 'rows':
        assert fixture.snapshots['payments'][-1] == {'id': 9, 'amount': 99}  # Never restore DB.
    else: assert_v3_and_rows_preserved(fixture)


def test_full_journal_disk_cannot_prevent_recovery_of_stopped_original(fixture, monkeypatch):
    old_event = x.event
    def event(name, value):
        if name in {'original-stopped', 'failure', 'recovery-intent'}:
            raise OSError('synthetic disk full')
        return old_event(name, value)
    monkeypatch.setattr(x, 'event', event)
    with pytest.raises(OSError): x.complete()
    assert fixture.inspect('t24-crm')['Id'] == fixture.original['Id']
    assert fixture.inspect('t24-crm')['State']['Running'] is True
    assert not fixture.candidate['State']['Running']
    assert_v3_and_rows_preserved(fixture)


def test_failed_candidate_metadata_does_not_block_restoring_known_original(fixture, monkeypatch):
    old_verify = a.verify_active
    def verify(*args, **kwargs):
        fixture.candidate['HostConfig']['OomKillDisable'] = True
        old_verify(*args, **kwargs)
    monkeypatch.setattr(a, 'verify_active', verify)
    with pytest.raises(c.GuardError, match='EXACT_FALSE'): x.complete()
    assert fixture.inspect('t24-crm')['Id'] == fixture.original['Id']
    assert fixture.candidate['State']['Running'] is False
    assert_v3_and_rows_preserved(fixture)


def test_schema_drift_blocks_recovery_before_any_mutation(fixture):
    x.complete();fixture.commands.clear()
    fixture.fake.schema_signature = lambda *args: 'changed-schema'
    with pytest.raises(c.GuardError, match='RECOVERY_SCHEMA_DRIFT'): x.rollback()
    assert not fixture.commands and fixture.candidate['State']['Running']


def test_unknown_primary_blocks_recovery_before_any_mutation(fixture):
    x.complete();fixture.commands.clear()
    fixture.candidate['Name'] = '/' + a.CANDIDATE_NAME
    other = copy.deepcopy(fixture.original)
    other.update(Id='3' * 64, Name='/t24-crm')
    fixture.containers[other['Id']] = other
    with pytest.raises(c.GuardError, match='UNKNOWN_PRIMARY'): x.rollback()
    assert not fixture.commands


def test_actual_evidence_pins_and_frozen_files_match():
    out = HERE.parents[1] / 'outputs/google-business-activation-20261030'
    for name, digest in [('clone-facts.json', x.CLONE_EVIDENCE_SHA), ('oom-default-facts.json', x.OOM_EVIDENCE_SHA),
        ('nginx-plan-v3.json', x.PLAN_SHA), ('logging-protected-v3.json', x.LOGGING_SHA)]:
        assert c.H((out / name).read_bytes()) == digest
    assert a.tool_hashes() == x.FROZEN_TOOLS


@pytest.mark.parametrize('phase', ['audit', 'complete', 'rollback'])
def test_generated_command_bounded_fixed_host_carrier_and_inline_hash(phase, monkeypatch):
    monkeypatch.setattr(g, 'verified_completion', lambda carrier: (g.COMPLETION_SHA, g.COMPLETION_SIZE))
    body = g.command(phase, 'a' * 40)
    assert len(body.encode()) < 12000
    assert body.index('EXACT_SERVER_ROOT_REQUIRED') < body.index('opener.open(')
    assert 'ProxyHandler({})' in body and 'class NoRedirect' in body
    assert "phase='" + phase + "'" in body
    assert g.H((HERE / 'completion.py').read_bytes()) in body
    inline = body.split("<<'GBP_EXISTING_CANDIDATE_COMPLETION_PINNED'\n", 1)[1].rsplit('\nGBP_EXISTING_CANDIDATE_COMPLETION_PINNED', 1)[0]
    ast.parse(inline)
    assert 'docker rm' not in body and 'docker create' not in body


@pytest.mark.parametrize('phase', ['enable', 'plan', '', '../complete', 'complete;id', None, 2])
def test_generator_rejects_other_phases_without_network(phase):
    with pytest.raises(g.frozen.PackagingError): g.command(phase, 'a' * 40)


def test_post_start_null_exactly_equals_original_and_receipt_retains_raw_runtime(fixture, monkeypatch):
    old_run = c.run
    def run(args, code, **kwargs):
        result = old_run(args, code, **kwargs)
        if args[:3] == ['docker', 'start', fixture.candidate['Id']]:
            fixture.candidate['HostConfig']['OomKillDisable'] = None
        return result
    monkeypatch.setattr(c, 'run', run)
    result = x.complete()
    assert result['enabled'] is True
    assert fixture.candidate['HostConfig']['OomKillDisable'] is None
    assert result['crm'] == fixture.fake.runtime(fixture.candidate)
    x.rollback()
    assert_v3_and_rows_preserved(fixture)


def test_audit_exercises_recovery_source_protocol_before_any_stop(fixture, monkeypatch):
    calls = []
    def source(*args):
        calls.append(True)
        assert not fixture.commands
        raise c.GuardError('INJECTED_SOURCE_PROTOCOL_REJECTED')
    monkeypatch.setattr(x, 'verify_stopped_source', source)
    with pytest.raises(c.GuardError, match='SOURCE_PROTOCOL'): x.complete()
    assert calls == [True] and not fixture.commands and not x.root().exists()


@pytest.fixture
def source(monkeypatch):
    import io
    import tarfile
    import types
    expected = {'main.py': b'print(1)\n', 'services/example.py': b'VALUE=1\n'}
    requests = []
    def archive(path):
        data = expected[path]
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as out:
            item = tarfile.TarInfo(path.rsplit('/', 1)[-1]);item.size = len(data)
            out.addfile(item, io.BytesIO(data))
        return stream.getvalue()
    def request(method, identity, path, timeout):
        assert identity == x.ORIGINAL_ID and 0 < timeout <= 2
        requests.append((method, path))
        name = path.rsplit('/', 1)[-1]
        if method == 'HEAD': return {'name': name, 'mode': (1 << 31) | 0o755, 'linkTarget': ''}, b''
        relative = path[len('/app/backend/'):]
        return {'name': name, 'mode': 0o644, 'size': len(expected[relative]), 'linkTarget': ''}, archive(relative)
    module = types.SimpleNamespace(read=lambda *args: json.dumps({name: c.H(data) for name, data in expected.items()}).encode())
    monkeypatch.setattr(x, '_source_request', request)
    monkeypatch.setattr(c, 'run', lambda *args, **kwargs: b'C /app/backend\nC /app/backend/services\nA /app/backend/__pycache__/main.pyc\n')
    return types.SimpleNamespace(expected=expected, requests=requests, request=request, module=module, archive=archive)


def test_no_execution_source_guard_reads_only_pinned_files_and_parent_head(source):
    x.verify_stopped_source(source.module, {'Id': x.ORIGINAL_ID}, {'candidate_inventory_sha256': 'pinned'})
    assert sorted(source.requests) == sorted([('HEAD', '/app'), ('HEAD', '/app/backend'), ('HEAD', '/app/backend/services'),
        ('GET', '/app/backend/main.py'), ('GET', '/app/backend/services/example.py')])


@pytest.mark.parametrize('mutation', ['symlink-parent', 'file-parent', 'symlink-file', 'directory-file', 'wrong-name', 'wrong-size', 'content', 'tar-extra', 'tar-traversal'])
def test_source_stat_archive_and_hash_drift_fail_closed(source, monkeypatch, mutation):
    import io
    import tarfile
    def request(method, identity, path, timeout):
        info, blob = source.request(method, identity, path, timeout)
        if method == 'HEAD':
            if mutation == 'symlink-parent': info['linkTarget'] = '/private'
            if mutation == 'file-parent': info['mode'] = 0o644
        if method == 'GET':
            if mutation == 'symlink-file': info['linkTarget'] = '/private'
            if mutation == 'directory-file': info['mode'] = 1 << 31
            if mutation == 'wrong-name': info['name'] = 'other'
            if mutation == 'wrong-size': info['size'] += 1
            if mutation in {'content', 'tar-extra', 'tar-traversal'}:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode='w') as out:
                    data = b'changed!' if mutation == 'content' else source.expected[path[len('/app/backend/'):]]
                    item = tarfile.TarInfo('../main.py' if mutation == 'tar-traversal' else path.rsplit('/', 1)[-1]);item.size = len(data)
                    out.addfile(item, io.BytesIO(data))
                    if mutation == 'tar-extra': out.addfile(tarfile.TarInfo('extra.py'), io.BytesIO())
                blob = stream.getvalue()
        return info, blob
    monkeypatch.setattr(x, '_source_request', request)
    with pytest.raises(c.GuardError):
        x.verify_stopped_source(source.module, {'Id': x.ORIGINAL_ID}, {'candidate_inventory_sha256': 'pinned'})


@pytest.mark.parametrize('diff', [b'A /app/backend/extra.py\n', b'D /app/backend\n', b'A /app/backend/services\n', b'C /app/backend/unknown\n'])
def test_unexpected_source_metadata_is_denied_without_fetching_files(source, monkeypatch, diff):
    monkeypatch.setattr(c, 'run', lambda *args, **kwargs: diff)
    with pytest.raises(c.GuardError): x.verify_stopped_source(source.module, {'Id': x.ORIGINAL_ID}, {'candidate_inventory_sha256': 'pinned'})
    assert not source.requests


@pytest.mark.parametrize('carrier', ['', 'a'*39, 'a'*41, 'b375', '../x', 'a'*40+';id', 1, None])
def test_completion_carrier_requires_full_immutable_hash(carrier):
    with pytest.raises(g.frozen.PackagingError): g.verified_completion(carrier)


def test_completion_pin_matches_reviewed_bytes():
    blob = (HERE / 'completion.py').read_bytes()
    assert g.COMPLETION_SHA == c.H(blob) and g.COMPLETION_SIZE == len(blob)


def test_actual_local_transport_allows_fixed_app_parent_and_caps_get_allocation(monkeypatch):
    import base64
    events = []
    row = {'name': 'app', 'mode': (1 << 31) | 0o755, 'linkTarget': ''}
    class Response:
        status = 200
        def getheaders(self): return [('X-Docker-Container-Path-Stat', base64.b64encode(json.dumps(row).encode()).decode())]
        def read(self, size): events.append(('read', size)); return b'synthetic'
    class Connection:
        def __init__(self, host, timeout): assert host == 'localhost' and timeout <= 2
        def request(self, method, path): events.append((method, path))
        def getresponse(self): return Response()
        def close(self): pass
    class Socket:
        def settimeout(self, timeout): assert timeout <= 2
        def connect(self, path): assert path == '/var/run/docker.sock'
        def close(self): pass
    monkeypatch.setattr(x.http.client, 'HTTPConnection', Connection)
    monkeypatch.setattr(x.socket, 'socket', lambda *args: Socket())
    info, body = x._source_request('HEAD', x.ORIGINAL_ID, '/app', 1)
    assert info == row and body == b'' and not any(item[0] == 'read' for item in events)
    x._source_request('GET', x.ORIGINAL_ID, '/app/backend/main.py', 1)
    assert events[-1] == ('read', 4 * 1024 * 1024 + 65537)
    assert all('google' not in str(item) for item in events)


@pytest.mark.parametrize('method,identity,path', [('PUT', '1'*64, '/app'), ('GET', '1'*64, '/etc/passwd'),
    ('GET', None, '/app'), ('GET', x.ORIGINAL_ID, '/app/../private'), ('GET', x.ORIGINAL_ID, '/app//private')])
def test_local_source_transport_rejects_out_of_scope_request_without_socket(monkeypatch, method, identity, path):
    monkeypatch.setattr(x.socket, 'socket', lambda *args: pytest.fail('out of scope connected'))
    with pytest.raises(c.GuardError): x._source_request(method, identity, path, 1)
