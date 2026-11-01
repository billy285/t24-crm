import ast
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace
import zlib

import pytest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('asset_capacity_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_current_immutable_pins_and_no_old_empty_assumption():
    p = load('preflight')
    assert p.SOURCE == 'd39337fccfd622e506ca3c1a655a126f5218dc42'
    assert p.FRONTEND == '8113d14d204f' and p.REVISION == 'e10cb234c570'
    assert p.RUNTIME['id'].startswith('3000cd73')
    source = (HERE / 'preflight.py').read_text()
    assert "rows['media_monthly_workflows']['count'] == 1" in source
    assert 'recovery=True, head=REVISION, schema=SCHEMA_SHA' in source
    assert 'two_new_monthly_workflow_tables_empty' not in source


def test_engine_probe_compiles_without_app_imports_or_file_writes():
    p = load('preflight'); tree = ast.parse(p.ENGINE_PROBE)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imports <= {'pathlib', 'urllib.parse', 'PIL'}
    assert "socket.socket.connect=blocked" in p.ENGINE_PROBE
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {'write_text', 'write_bytes', 'mkdir', 'unlink', 'rename', 'replace', 'chmod', 'chown'}
    assert "Image.new('RGB',(8,8)" in p.ENGINE_PROBE
    assert "save(buf,format='PNG')" in p.ENGINE_PROBE
    assert "'/etc/apt/auth.conf'" not in p.ENGINE_PROBE
    assert 'apt-get update' not in p.ENGINE_PROBE and 'pip install' not in p.ENGINE_PROBE


def test_credentialed_apt_uri_is_not_public():
    # The exact predicate used in the real isolated metadata probe.
    from urllib.parse import urlsplit
    allowed = {'deb.debian.org', 'security.debian.org'}
    def public(raw):
        uri = urlsplit(raw)
        return uri.scheme in {'http', 'https'} and uri.hostname in allowed and uri.port in {None, 80, 443} and uri.username is None and uri.password is None and not uri.query and not uri.fragment and re.fullmatch(r'/[A-Za-z0-9/._-]*', uri.path)
    assert public('http://deb.debian.org/debian')
    assert not public('https://user:secret@deb.debian.org/debian')
    assert not public('https://deb.debian.org/debian?token=secret')
    assert not public('https://unreviewed.invalid/repo')


def baseline():
    p = load('preflight')
    names = ['old_' + str(i) for i in range(153)] + ['media_monthly_workflows', 'media_monthly_workflow_requests']
    rows = {name: {'count': 1, 'rows_sha256': 'a' * 64, 'shape_sha256': 'b' * 64} for name in names}
    value = {key: None for key in ('host', 'source_sha', 'frontend_version', 'schema_revision', 'deployed_receipt_sha256', 'crm', 'environment_sha256', 'ops_environment_sha256', 'schema_sha256', 'backend_inventory_sha256', 'backend_file_count', 'public_root', 'public_inventory_sha256', 'nginx_sha256', 'active_nginx_sha256', 'content_security_policy_sha256', 'public_content_security_policy', 'csp_environment_override_present', 'all155_current_tables_preserved', 'prepared_private_packet_preserved', 'ops_execution_enabled', 'ops_scheduler_enabled', 'google_scheduler_enabled', 'google_scheduler_activation_from')}
    value.update(rows=rows, database_metadata={'sequence': 1})
    engine = {key: None for key in ('python', 'cpu_count', 'affinity_cpu_count', 'memory', 'cgroup', 'disk', 'pillow', 'binaries', 'system')}
    engine.update(fonts={'count': 1, 'truncated': False, 'total_hashed_bytes': 4, 'files': [{'path': '/usr/share/fonts/sample.ttf'}]}, font_license_metadata=[])
    return p, value, {'host': engine, 'container': copy.deepcopy(engine), 'container_resource_limits': {}}


def setup_capture(monkeypatch, tmp_path, values):
    p, first, engines = baseline(); writes = []
    monkeypatch.setattr(p, 'ROOT', tmp_path)
    monkeypatch.setattr(p, 'sample', lambda: copy.deepcopy(values.pop(0)))
    monkeypatch.setattr(p, 'capacity', lambda: engines)
    core = SimpleNamespace(write=lambda path, body: writes.append((path, body)), read=lambda *a, **k: pytest.fail('unexpected existing receipt'))
    flow = SimpleNamespace(c=core, retained=SimpleNamespace(live_sequence_boundary=lambda *a: None))
    monkeypatch.setattr(p, 'dependencies', lambda: (None, flow, None))
    return p, writes


def test_two_current155_samples_capture_only_aggregate_receipt(monkeypatch, tmp_path):
    _, first, _ = baseline(); p, writes = setup_capture(monkeypatch, tmp_path, [first, first])
    result = p.capture()
    assert len(writes) == 1 and writes[0][0].parent == tmp_path
    assert result['stage'] == 'MEDIA_ASSET_STUDIO_PREFLIGHT_CAPTURED'
    assert result['table_count'] == 155 and result['prepared_private_packet_count'] == 1
    assert result['sha256'] == hashlib.sha256(writes[0][1]).hexdigest()
    assert result['rows_sha256'] == p.digest(first['rows'])
    assert all(result[key] is False for key in ('installation_performed', 'worker_started', 'schema_changed', 'permissions_changed', 'credential_file_content_read', 'private_content_read', 'business_writes', 'provider_requests', 'runtime_changed'))
    assert 'rows' not in result and json.loads(writes[0][1])['rows'] == first['rows']


def test_any_current155_row_drift_stops_before_receipt_write(monkeypatch, tmp_path):
    _, first, _ = baseline(); changed = copy.deepcopy(first)
    changed['rows']['media_monthly_workflows']['rows_sha256'] = 'c' * 64
    p, writes = setup_capture(monkeypatch, tmp_path, [first, changed])
    with pytest.raises(RuntimeError, match='CURRENT155_BOUNDARIES_CHANGED_DURING_CAPTURE'): p.capture()
    assert not writes


def test_bounded_numeric_resource_metadata_and_fixed_commands(monkeypatch):
    p = load('preflight'); calls = []
    engine = {'python': '3.10.15', 'writes': False, 'network_requests': False, 'credentials_read': False}
    info = {'HostConfig': {'Memory': 1073741824, 'OomKillDisable': False, 'Env': ['NEVER_EXPORT=secret']}}
    m = SimpleNamespace(inspect=lambda *a: info, runtime=lambda *a: p.RUNTIME,
        run=lambda argv, code, timeout: (calls.append(argv) or json.dumps(engine)))
    monkeypatch.setattr(p, 'dependencies', lambda: (None, SimpleNamespace(m=m), None))
    result = p.capacity()
    assert calls[0][:4] == ['python3', '-I', '-B', '-c']
    assert calls[1][:6] == ['docker', 'exec', p.RUNTIME['id'], 'python', '-I', '-B']
    assert result['container_resource_limits']['Memory'] == 1073741824
    assert 'Env' not in result['container_resource_limits'] and 'secret' not in json.dumps(result)


def test_non_numeric_resource_metadata_is_rejected(monkeypatch):
    p = load('preflight')
    engine = {'python': '3.10.15', 'writes': False, 'network_requests': False, 'credentials_read': False}
    m = SimpleNamespace(inspect=lambda *a: {'HostConfig': {'Memory': 'secret'}}, runtime=lambda *a: p.RUNTIME,
        run=lambda *a: json.dumps(engine))
    monkeypatch.setattr(p, 'dependencies', lambda: (None, SimpleNamespace(m=m), None))
    with pytest.raises(RuntimeError, match='RESOURCE_METADATA_TYPES_REQUIRED'): p.capacity()


def test_exact_wrapper_reproduces_embedded_bytes_and_hash():
    p = load('preflight'); maker = load('make_capture'); body = (HERE / 'preflight.py').read_bytes()
    command, pins = maker.generate(body); again, again_pins = maker.generate(body)
    assert command == again and pins == again_pins
    match = re.search(r'base64.b64decode\(([^,]+),validate=True\)', command)
    assert match
    decoded = zlib.decompress(base64.b64decode(ast.literal_eval(match[1]), validate=True))
    assert decoded == body and hashlib.sha256(decoded).hexdigest() == pins['preflight_sha256']
    assert hashlib.sha256(command.encode()).hexdigest() == pins['command_sha256']
    assert 'sudo python3 -I -S -B' in command and 'EXACT_ROOT_SERVER_REQUIRED' in command
    assert "namespace['capture']()" in command
    assert pins['business_writes'] is False and pins['installation_performed'] is False


def test_public_csp_filters_headers_and_requires_exact_single_existing_policy():
    p = load('preflight'); policy = "default-src 'self'; img-src 'self' data: https:"
    header = ('HTTP/1.1 200 OK\r\nContent-Security-Policy: ' + policy + '\r\nSet-Cookie: never-export-secret\r\n\r\n').encode()
    calls = []; m = SimpleNamespace(run=lambda argv, *a: calls.append(argv) or header)
    assert p.public_security_policy(m, p.H(policy.encode())) == policy
    assert '--resolve' in calls[0] and calls[0][-1] == 'https://t24-crm.com/media-ops'
    assert not any('--cookie' in arg for arg in calls[0])
    with pytest.raises(RuntimeError, match='EXACT_EXISTING_PUBLIC_CSP_REQUIRED'): p.public_security_policy(m, '0' * 64)
    m.run = lambda *a: header.replace(b'Set-Cookie:', b'Content-Security-Policy:')
    with pytest.raises(RuntimeError, match='EXACT_EXISTING_PUBLIC_CSP_REQUIRED'): p.public_security_policy(m, p.H(policy.encode()))
