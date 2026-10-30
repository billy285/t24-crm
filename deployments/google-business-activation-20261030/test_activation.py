import base64
import copy
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core as c
import preflight
import transport
import make_commands
import activation as a
import diagnostics as d

CLIENT = '58950527996-abcdefghijklmnopqrstuv.apps.googleusercontent.com'
SECRET = 'synthetic_test_secret_1234567890'
SECURITY_RESPONSE = (b'HTTP/1.1 303 See Other\r\nLocation: /media-ops?google=failed\r\nCache-Control: private, no-store\r\n'
    b'Strict-Transport-Security: max-age=31536000; includeSubDomains\r\nContent-Security-Policy: default-src self\r\n'
    b'X-Frame-Options: SAMEORIGIN\r\nX-Content-Type-Options: nosniff\r\nPermissions-Policy: camera=()\r\n'
    b'Referrer-Policy: no-referrer\r\n\r\n')


@pytest.fixture
def store(monkeypatch):
    # Real protected files under an owned parent, never production paths.
    with tempfile.TemporaryDirectory(prefix='activation-test-', dir=HERE) as temp:
        root = Path(temp)
        monkeypatch.setattr(c, 'FILE_OWNER', os.getuid())
        monkeypatch.setattr(c, 'ROOT', root / 'release')
        monkeypatch.setattr(c, 'SECRET_ROOT', root / 'google-business')
        monkeypatch.setattr(c, 'ENV_FILE', root / 'google-business/runtime.env')
        monkeypatch.setattr(c, 'TRANSFERS', root / 'google-business/transfers')
        monkeypatch.setattr(c, 'server_guard', lambda: None)
        monkeypatch.setattr(preflight, 'proof', lambda **kw: {'stage': 'synthetic'})
        yield root


def encrypted(context, value=None, *, label=None):
    payload = value if value is not None else {'client_id': CLIENT, 'client_secret': SECRET}
    clear = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    key = serialization.load_pem_public_key(context['public_pem'].encode())
    return base64.b64encode(key.encrypt(clear, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=transport.label(context) if label is None else label))).decode()


def test_rsa_real_roundtrip_stores_dedicated_key_and_no_runtime_change(store):
    context = transport.prepare()
    result = transport.receive(context['transfer_id'], encrypted(context))
    assert result['runtime_changed'] is False and result['provider_requests'] is False
    values = c.read_gbp_env()
    assert values['T24_GBP_CLIENT_ID'] == CLIENT and values['T24_GBP_CLIENT_SECRET'] == SECRET
    assert len(base64.urlsafe_b64decode(values['T24_GBP_TOKEN_KEY'])) == 32
    assert values['T24_GBP_TOKEN_KEY'] not in {SECRET, CLIENT}
    assert c.ENV_FILE.stat().st_mode & 0o777 == 0o600
    assert c.SECRET_ROOT.stat().st_mode & 0o777 == 0o700
    assert not (c.TRANSFERS / context['transfer_id'] / 'private.pem').exists()
    assert SECRET not in json.dumps(result) and SECRET not in json.dumps(context)


def test_second_transfer_cannot_overwrite_credentials(store):
    first = transport.prepare()
    second = transport.prepare()
    transport.receive(first['transfer_id'], encrypted(first))
    original = c.ENV_FILE.read_bytes()
    with pytest.raises(c.GuardError, match='EXISTING_GOOGLE_CREDENTIALS_PRESERVED'):
        transport.receive(second['transfer_id'], encrypted(second))
    assert c.ENV_FILE.read_bytes() == original


def test_transfer_is_one_use_even_after_decryption_failure(store):
    context = transport.prepare()
    with pytest.raises(c.GuardError, match='CIPHERTEXT_REJECTED'):
        transport.receive(context['transfer_id'], encrypted(context, label=b'wrong-project'))
    with pytest.raises(c.GuardError, match='TRANSPORT_ALREADY_USED'):
        transport.receive(context['transfer_id'], encrypted(context))
    assert not c.ENV_FILE.exists()


def test_expired_transport_is_rejected_without_env(store, monkeypatch):
    context = transport.prepare()
    monkeypatch.setattr(transport.time, 'time', lambda: context['expires_at'])
    with pytest.raises(c.GuardError, match='TRANSPORT_EXPIRED'):
        transport.receive(context['transfer_id'], encrypted(context))
    assert not c.ENV_FILE.exists()


@pytest.mark.parametrize('payload', [
    {'client_id': '1234567890-abcdefghijklmnop.apps.googleusercontent.com', 'client_secret': SECRET},
    {'client_id': CLIENT, 'client_secret': SECRET, 'project': 't24'},
    {'client_id': CLIENT, 'client_secret': 'short'},
    {'client_id': CLIENT, 'client_secret': SECRET + '\nT24_OTHER=oops'},
    {'client_id': CLIENT, 'client_secret': SECRET + '='},
    {'client_id': None, 'client_secret': SECRET},
    [],
])
def test_payload_scope_rejected_before_storage(store, payload):
    context = transport.prepare()
    with pytest.raises(c.GuardError):
        transport.receive(context['transfer_id'], encrypted(context, payload))
    assert not c.ENV_FILE.exists()


def test_duplicate_json_field_is_rejected(store):
    context = transport.prepare()
    raw = ('{"client_id":' + json.dumps(CLIENT) + ',"client_secret":"first_secret_123456","client_secret":' + json.dumps(SECRET) + '}').encode()
    with pytest.raises(c.GuardError, match='DUPLICATE_JSON_FIELD'):
        transport.receive(context['transfer_id'], encrypted(context, raw))


@pytest.mark.parametrize('ciphertext', ['', 'plaintext_secret', 'A' * 512, 'A' * 511 + '\n'])
def test_invalid_ciphertext_never_installs(store, ciphertext):
    context = transport.prepare()
    with pytest.raises(c.GuardError):
        transport.receive(context['transfer_id'], ciphertext)
    assert not c.ENV_FILE.exists()


def test_symlink_env_target_rejected_and_original_preserved(store):
    context = transport.prepare()
    original = store / 'original-secret'
    original.write_text('original')
    c.ENV_FILE.symlink_to(original)
    with pytest.raises(c.GuardError, match='EXISTING_GOOGLE_CREDENTIALS_PRESERVED'):
        transport.receive(context['transfer_id'], encrypted(context))
    assert original.read_text() == 'original'


def test_protected_read_rejects_mode_link_and_symlink(store):
    target = store / 'file'
    c.write(target, b'synthetic')
    assert c.read(target) == b'synthetic'
    target.chmod(0o644)
    with pytest.raises(c.GuardError, match='PROTECTED_FILE_REQUIRED'):
        c.read(target)
    target.chmod(0o600)
    link = store / 'hardlink'
    os.link(target, link)
    with pytest.raises(c.GuardError, match='PROTECTED_FILE_REQUIRED'):
        c.read(target)
    link.unlink()
    sym = store / 'symlink'
    sym.symlink_to(target)
    with pytest.raises(c.GuardError, match='PROTECTED_FILE_REQUIRED'):
        c.read(sym)


@pytest.mark.parametrize('rows', [['X=one', 'X=two'], ['X=one\nY=two'], ['X=one\x00'], ['INVALID KEY=x'], ['NO_EQUALS']])
def test_environment_parser_rejects_ambiguous_input(rows):
    with pytest.raises(c.GuardError):
        c.env_dict(rows)


def test_callback_safe_view_redacts_arbitrary_secrets():
    blob = b'''server {\nserver_name t24-crm.com;\nlocation /api/ {\nproxy_pass http://127.0.0.1:8000;\nproxy_set_header Authorization "Bearer SUPERSECRET";\nset $token SUPERSECRET;\n# SUPERSECRET\n}\n}\n'''
    value = preflight.safe_nginx_view(blob)
    assert 'SUPERSECRET' not in json.dumps(value)
    assert any(row['config'] == 'proxy_pass http://127.0.0.1:8000;' for row in value)


def test_preflight_wrapper_is_hash_bound_and_has_no_server_execution():
    script = make_commands.command('preflight', {})
    assert 'sudo python3 -B' in script
    assert 'hashlib.sha256(blob).hexdigest()!=member' in script
    assert "loaded['preflight'].main()" in script
    assert SECRET not in script


def test_transport_wrapper_accepts_only_exact_ciphertext_fields():
    with pytest.raises(ValueError):
        make_commands.command('transport-install', {'client_secret': SECRET})
    script = make_commands.command('transport-install', {'transfer_id': 'a' * 32, 'ciphertext': 'A' * 512})
    assert "receive(**arguments)" in script and SECRET not in script


def test_pins_match_actual_disabled_release():
    body = (HERE.parent / 'google-business-20261030/deployed.json').read_bytes()
    assert c.H(body) == c.PRIOR_SHA
    receipt = json.loads(body)
    assert receipt['source_sha'] == c.SOURCE and receipt['frontend_version'] == c.FRONTEND
    assert receipt['crm']['image'] == c.IMAGE and receipt['schema_revision'] == c.REVISION


NGINX = b'''server {
    listen 80;
    server_name t24-crm.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name t24-crm.com;
    root /var/www/t24-crm-public/google-business-7431d1986b81-20261030;
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }
    location / { try_files $uri $uri/ /index.html; }
}
'''


def synthetic_info():
    return {'Id': '1' * 64, 'Image': c.IMAGE, 'Config': {'Env': ['KEEP=synthetic-original', 'PATH=/usr/bin'],
        'Hostname': 'original-host', 'Image': 'old-reference', 'Cmd': ['original-cmd'], 'Entrypoint': ['original-entry'],
        'Labels': {'existing': 'unchanged'}, 'WorkingDir': '/app/backend'},
        'HostConfig': {'AutoRemove': False, 'NetworkMode': 'bridge', 'Binds': ['/protected/data:/app/backend/data:rw'],
            'RestartPolicy': {'Name': 'unless-stopped'}},
        'Mounts': [{'Source': '/protected/data', 'Destination': '/app/backend/data', 'RW': True}],
        'NetworkSettings': {'Networks': {'bridge': {'Aliases': ['kept-alias']}}},
        'State': {'Running': True, 'StartedAt': 'synthetic'}, 'RestartCount': 0, 'Name': '/t24-crm'}


def synthetic_values():
    return {'T24_GBP_CLIENT_ID': CLIENT, 'T24_GBP_CLIENT_SECRET': SECRET, 'T24_GBP_TOKEN_KEY': base64.urlsafe_b64encode(b'k' * 32).decode(),
        'T24_GBP_ENABLED': 'true', 'T24_GBP_API_APPROVED': 'true', 'T24_GBP_PUBLIC_URL': c.ORIGIN}


def synthetic_runtime(info):
    value = {key: info[key] for key in ('Config', 'HostConfig', 'Mounts', 'NetworkSettings')}
    return {'config': c.H(json.dumps(value, sort_keys=True).encode())}


def test_nginx_exact_callback_insertion_preserves_every_existing_byte():
    updated, added = a.next_nginx(NGINX)
    assert updated.replace(added, b'', 1) == NGINX
    assert updated.count(('location = ' + c.CALLBACK).encode()) == 1
    assert b'access_log off;' in added and b'error_log /dev/null crit;' in added
    assert b'proxy_pass http://127.0.0.1:8000;' in added
    assert b'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' in added
    with pytest.raises(c.GuardError, match='EXISTING_CALLBACK_LOCATION_REQUIRES_REVIEW'):
        a.next_nginx(updated)


@pytest.mark.parametrize('old,new', [
    (b'proxy_pass http://127.0.0.1:8000;', b'proxy_pass https://external.example;'),
    (b'proxy_pass http://127.0.0.1:8000;', b'proxy_pass http://127.0.0.1:8000/;'),
    (b'proxy_read_timeout 300;', b'rewrite ^ /other break;'),
    (b'proxy_set_header Host $host;', b'proxy_set_header Authorization "Bearer secret";'),
    (b'proxy_read_timeout 300;', b'if ($request_method = POST) { return 403; }'),
    (b'proxy_read_timeout 300;', b'include /some/unknown.conf;'),
])
def test_nonstandard_proxy_changes_fail_closed(old, new):
    with pytest.raises(c.GuardError):
        a.next_nginx(NGINX.replace(old, new))


def test_nginx_parser_handles_global_logs_and_comments():
    active = b'error_log /var/log/nginx/error.log warn;\nhttp {\naccess_log /var/log/nginx/access.log;\n}\n' + NGINX
    assert a.log_paths(active) == ['/var/log/nginx/access.log', '/var/log/nginx/error.log']
    a.verify_no_debug_logging(active)
    with pytest.raises(c.GuardError, match='DEBUG_LOGGING_BLOCKS_OAUTH_ACTIVATION'):
        a.verify_no_debug_logging(active.replace(b'warn;', b'debug;'))
    with pytest.raises(c.GuardError, match='EXTERNAL_LOG_DESTINATION_REQUIRES_REVIEW'):
        a.log_paths(active.replace(b'/var/log/nginx/error.log', b'syslog:server=external:514'))


def test_duplicate_tls_server_is_rejected():
    with pytest.raises(c.GuardError, match='EXACT_CRM_SERVER_REQUIRED'):
        a.next_nginx(NGINX + NGINX)


def test_clone_adds_exact_six_keys_and_preserves_original():
    original = synthetic_info()
    before = copy.deepcopy(original)
    networks = original['NetworkSettings']['Networks']
    config = a.clone_config(original, synthetic_values(), networks)
    assert original == before
    assert c.env_dict(config['Env']) == {**c.env_dict(original['Config']['Env']), **synthetic_values()}
    assert config['HostConfig'] == original['HostConfig']
    assert config['Labels'] == original['Config']['Labels']
    assert config['Cmd'] == original['Config']['Cmd'] and config['Entrypoint'] == original['Config']['Entrypoint']


def make_candidate():
    original = synthetic_info()
    config = a.clone_config(original, synthetic_values(), original['NetworkSettings']['Networks'])
    candidate = copy.deepcopy(original)
    candidate['Config'] = {key: value for key, value in config.items() if key not in {'HostConfig', 'NetworkingConfig'}}
    candidate['Config']['Hostname'] = 'new-docker-host'
    return original, candidate


def test_cloned_runtime_passes_with_only_expected_docker_identity_changes():
    original, candidate = make_candidate()
    a.verify_clone(candidate, original, synthetic_values(), synthetic_runtime)


@pytest.mark.parametrize('mutation', [
    lambda row: row['Config']['Env'].append('UNAPPROVED=value'),
    lambda row: row['Config']['Env'].__setitem__(0, 'KEEP=changed'),
    lambda row: row['Config'].__setitem__('Cmd', ['changed']),
    lambda row: row['Config']['Labels'].__setitem__('unapproved', 'value'),
    lambda row: row['HostConfig'].__setitem__('NetworkMode', 'host'),
    lambda row: row['Mounts'][0].__setitem__('RW', False),
    lambda row: row['NetworkSettings']['Networks']['bridge'].__setitem__('Aliases', ['changed']),
    lambda row: row.__setitem__('Image', 'sha256:' + 'f' * 64),
])
def test_clone_guard_rejects_unapproved_runtime_drift(mutation):
    original, candidate = make_candidate()
    mutation(candidate)
    with pytest.raises(c.GuardError):
        a.verify_clone(candidate, original, synthetic_values(), synthetic_runtime)


def review_fixture(plan_sha='a' * 64):
    return {**{name: True for name in a.REVIEW_FLAGS}, 'stage': 'GBP_ACTIVATION_MANUAL_REVIEW_APPROVED',
        'plan_sha256': plan_sha, 'project_id': c.PROJECT_ID, 'callback': c.ORIGIN + c.CALLBACK,
        'scope': a.SCOPE, 'tool_sha256': a.tool_hashes(), 'business_writes': False, 'provider_writes': False}


def test_protected_command_requires_complete_review_and_exact_hash():
    review = review_fixture()
    args = {'plan_sha256': review['plan_sha256'], 'review': review, 'review_sha256': c.H(c.encoded(review))}
    script = make_commands.command('protect-callback', args)
    assert 'provider_writes' in script and SECRET not in script
    for field in a.REVIEW_FLAGS:
        changed = copy.deepcopy(args)
        changed['review'][field] = False
        with pytest.raises(ValueError):
            make_commands.command('protect-callback', changed)
    changed = copy.deepcopy(args)
    changed['review']['client_secret'] = SECRET
    with pytest.raises(ValueError):
        make_commands.command('protect-callback', changed)
    changed = copy.deepcopy(args)
    changed['review_sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='REVIEW_HASH_DRIFT'):
        make_commands.command('protect-callback', changed)


def test_configuration_probe_blocks_network_and_never_outputs_values():
    for enabled in (True, False):
        probe = a.config_probe(enabled)
        assert 'socket.socket.connect=blocked' in probe
        assert 'print(values)' not in probe and SECRET not in probe
        compile(probe, 'synthetic-config-probe', 'exec')


def test_retained_loader_caches_but_rechecks_hash(store, monkeypatch):
    legacy_path = store / 'retained.py'
    c.write(legacy_path, b'VALUE=42\n')
    monkeypatch.setattr(c, 'LEGACY', legacy_path)
    monkeypatch.setattr(c, 'LEGACY_SHA', c.H(b'VALUE=42\n'))
    monkeypatch.setattr(c, '_LEGACY_CACHE', None)
    first = c.legacy()
    assert c.legacy() is first and first.VALUE == 42
    legacy_path.write_bytes(b'VALUE=99\n')
    with pytest.raises(c.GuardError, match='FILE_HASH_DRIFT'):
        c.legacy()


@pytest.fixture
def switch_fixture(store, monkeypatch):
    c.mkdir(c.ROOT)
    c.mkdir(a.attempt_root())
    original = synthetic_info()
    nginx = store / 'nginx.conf'
    next_body, _ = a.next_nginx(NGINX)
    nginx.write_bytes(next_body)
    values = synthetic_values()
    c.write(a.attempt_root() / 'original-container.json', original)
    c.write(c.ROOT / 'credential-receipt.json', {'stage': 'GBP_ACTIVATION_CREDENTIALS_STORED_NOT_ENABLED',
        'project_id': c.PROJECT_ID, 'project_number': c.PROJECT_NUMBER, 'runtime_changed': False})
    containers = {original['Id']: copy.deepcopy(original)}
    commands, snapshots = [], {'payments': [{'id': 7, 'amount': 198}], 'google_business_connections': []}
    static, inventory = {'index.html': 'synthetic'}, {'main.py': 'synthetic', 'services/google_business.py': 'same-source'}
    digest = lambda row: c.H(json.dumps(row, sort_keys=True).encode())

    def runtime(row):
        return {**synthetic_runtime(row), 'id': row['Id'], 'image': row['Image']}

    def inspect_optional(name):
        for row in containers.values():
            if row['Id'] == name or row['Name'] == '/' + name:
                return copy.deepcopy(row)
        return None

    def inspect(name):
        result = inspect_optional(name)
        assert result is not None, ('unexpected inspect', name)
        return result

    def docker_request(method, path, config):
        assert method == 'POST' and path == '/containers/create?name=' + a.CANDIDATE_NAME
        assert not inspect_optional(a.CANDIDATE_NAME)
        row = copy.deepcopy(original)
        row['Id'], row['Name'] = '2' * 64, '/' + a.CANDIDATE_NAME
        row['Config'] = {key: copy.deepcopy(value) for key, value in config.items() if key not in {'HostConfig', 'NetworkingConfig'}}
        row['Config']['Hostname'] = 'new-docker-host'
        row['HostConfig'] = copy.deepcopy(config['HostConfig'])
        row['NetworkSettings'] = {'Networks': copy.deepcopy(config['NetworkingConfig']['EndpointsConfig'])}
        row['State']['Running'] = False
        containers[row['Id']] = row
        commands.append(('create', row['Id']))
        return 201, json.dumps({'Id': row['Id']}).encode()

    def run(args, code, **kwargs):
        commands.append(tuple(args))
        assert args[0] == 'docker'
        if args[1] == 'exec':
            assert args[3:6] == ['python', '-B', '-c']
            assert 'socket.socket.connect=blocked' in args[6]
            return b'GBP_CONFIG_NO_NETWORK_VERIFIED\n'
        if args[1] == 'stop':
            containers[args[-1]]['State']['Running'] = False
        elif args[1] == 'rename':
            assert not inspect_optional(args[3]), 'name conflict'
            containers[args[2]]['Name'] = '/' + args[3]
        elif args[1] == 'start':
            containers[args[2]]['State']['Running'] = True
        elif args[1] == 'rm':
            assert not containers[args[2]]['State']['Running']
            del containers[args[2]]
        else:
            raise AssertionError(('unexpected command', args))
        return b''

    prior = {'schema_sha256': 'schema-unchanged', 'candidate_inventory_sha256': 'synthetic',
        'public_root': '/synthetic-public', 'public_inventory_sha256': digest(static)}

    def read(path, expected=None):
        if path == c.PRIOR / 'deployed.json':
            assert expected == c.PRIOR_SHA
            return json.dumps(prior).encode()
        if path == c.PRIOR / 'backend-candidate-inventory.json':
            return json.dumps(inventory).encode()
        if path == c.PINS:
            assert expected == c.PINS_SHA
            return b'{}'
        raise AssertionError(('unexpected protected read', path))

    fake = types.SimpleNamespace(inspect=inspect, inspect_optional=inspect_optional, runtime=runtime,
        retained=lambda: types.SimpleNamespace(clone_networks=lambda row: copy.deepcopy(row['NetworkSettings']['Networks']), docker_request=docker_request),
        sql_snapshot=lambda path: copy.deepcopy(snapshots), BUSINESS=store / 'canary.db', NGINX=nginx,
        inventory=lambda name: copy.deepcopy(inventory), read=read, schema_signature=lambda *args: 'schema-unchanged',
        tree=lambda root: copy.deepcopy(static), digest=digest, verify_secret_mount=lambda row: None,
        verify_production_worker_enabled=lambda row: None, private_boundary=lambda pins: None, ready=lambda name: None)
    active_body = b'error_log /var/log/nginx/error.log;\n' + next_body
    active_hash = c.H(active_body)
    plan = {'nginx_next_sha256': c.H(next_body), 'nginx_log_paths': ['/var/log/nginx/error.log']}
    logging = {'crm': runtime(original), 'active_nginx_config_sha256': active_hash}
    monkeypatch.setattr(c, 'legacy', lambda: fake)
    monkeypatch.setattr(c, 'read_gbp_env', lambda: copy.deepcopy(values))
    monkeypatch.setattr(c, 'run', run)
    monkeypatch.setattr(preflight, 'proof', lambda **kw: {'crm': runtime(original), 'active_nginx_config_sha256': active_hash})
    original_run = run

    def run_with_nginx(args, code, **kwargs):
        if args == ['nginx', '-T']:
            return active_body
        return original_run(args, code, **kwargs)

    monkeypatch.setattr(c, 'run', run_with_nginx)
    monkeypatch.setattr(a, '_switch_requirements', lambda args: (plan, logging))
    monkeypatch.setattr(a, 'sentinel_probe', lambda *args: {'callback_sentinel_verified': True})
    monkeypatch.setattr(a, 'verify_worker_identity', lambda active: {'uid': 33})
    monkeypatch.setattr(a, 'verify_log_identities', lambda plan: None)
    arguments = {'plan_sha256': 'a' * 64, 'review': {}, 'review_sha256': 'b' * 64, 'logging_receipt_sha256': 'c' * 64}
    return types.SimpleNamespace(fake=fake, original=original, containers=containers, commands=commands,
        snapshots=snapshots, args=arguments, values=values, plan=plan, inspect=inspect, active_hash=active_hash, active_body=active_body)


def test_fake_docker_enable_and_rollback_keep_rows_and_every_existing_setting(switch_fixture):
    fixture = switch_fixture
    before = copy.deepcopy(fixture.snapshots)
    result = a.enable(fixture.args)
    assert result['enabled'] is True and result['business_rows_unchanged_during_switch'] is True
    active = fixture.inspect('t24-crm')
    assert active['Id'] != fixture.original['Id'] and active['Image'] == c.IMAGE
    assert fixture.inspect(a.DISABLED_NAME)['State']['Running'] is False
    assert fixture.snapshots == before
    assert SECRET not in json.dumps(result)
    # OAuth or audit rows created later must survive configuration rollback.
    fixture.snapshots['google_business_connections'].append({'id': 1, 'encrypted': 'synthetic-ciphertext'})
    after_oauth = copy.deepcopy(fixture.snapshots)
    restored = a.rollback(fixture.args)
    assert restored['enabled'] is False and restored['database_restored'] is False
    assert fixture.inspect('t24-crm')['Id'] == fixture.original['Id']
    assert c.env_dict(fixture.inspect('t24-crm')['Config']['Env']) == c.env_dict(fixture.original['Config']['Env'])
    assert fixture.snapshots == after_oauth
    assert len(fixture.containers) == 1
    assert fixture.fake.NGINX.read_bytes() != NGINX  # Narrow query redaction survives.


def test_startup_failure_restores_only_same_image_configuration(switch_fixture):
    fixture = switch_fixture
    before = copy.deepcopy(fixture.snapshots)

    def ready(name):
        if name == '2' * 64:
            raise c.GuardError('SYNTHETIC_READINESS_FAILURE')

    fixture.fake.ready = ready
    with pytest.raises(c.GuardError, match='SYNTHETIC_READINESS_FAILURE'):
        a.enable(fixture.args)
    assert fixture.inspect('t24-crm')['Id'] == fixture.original['Id']
    assert fixture.inspect('t24-crm')['State']['Running'] is True
    assert fixture.snapshots == before
    assert all(row['Image'] == c.IMAGE for row in fixture.containers.values())


def test_protected_row_change_fails_and_never_restores_database(switch_fixture):
    fixture = switch_fixture
    original_ready = fixture.fake.ready

    def ready(name):
        original_ready(name)
        if name == '2' * 64:
            fixture.snapshots['payments'].append({'id': 8, 'amount': 329})

    fixture.fake.ready = ready
    with pytest.raises(c.GuardError, match='BUSINESS_ROWS_CHANGED_DURING_CONFIGURATION_SWITCH'):
        a.enable(fixture.args)
    assert fixture.snapshots['payments'] == [{'id': 7, 'amount': 198}, {'id': 8, 'amount': 329}]
    assert fixture.inspect('t24-crm')['Id'] == fixture.original['Id']


def test_unknown_active_container_stops_recovery_before_destructive_command(switch_fixture):
    fixture = switch_fixture
    a.enable(fixture.args)
    unknown = copy.deepcopy(fixture.original)
    unknown['Id'], unknown['Name'] = '9' * 64, '/t24-crm'
    fixture.containers['2' * 64]['Name'] = '/renamed-by-someone'
    fixture.containers[unknown['Id']] = unknown
    before = len(fixture.commands)
    with pytest.raises(c.GuardError, match='UNKNOWN_ACTIVE_CONTAINER_REQUIRES_MANUAL_REVIEW'):
        a.rollback(fixture.args)
    assert len(fixture.commands) == before
    assert fixture.containers[unknown['Id']]['State']['Running'] is True


def test_interrupt_after_intent_before_create_is_recoverable_without_new_image(switch_fixture):
    fixture = switch_fixture
    a._state({'stage': 'GBP_CONFIG_SWITCH_INTENT', 'original_id': fixture.original['Id'],
        'candidate_name': a.CANDIDATE_NAME, 'image': c.IMAGE, 'plan_sha256': fixture.args['plan_sha256'], 'review_sha256': fixture.args['review_sha256']})
    result = a.rollback(fixture.args)
    assert result['enabled'] is False and len(fixture.containers) == 1
    assert not any(item[0] == 'create' for item in fixture.commands)


@pytest.fixture
def preflight_fixture(store, monkeypatch):
    # Exercise the real preflight proof body against a synthetic read-only host.
    original_proof = importlib.util.spec_from_file_location('preflight_real_test', HERE / 'preflight.py')
    fresh = importlib.util.module_from_spec(original_proof)
    original_proof.loader.exec_module(fresh)
    nginx = store / 'nginx.conf'
    nginx.write_bytes(NGINX)
    db = store / 'canary.db'
    db.write_bytes(b'NOT_OPENED_BY_FAKE_READONLY_HELPER')
    public = store / 'public'
    public.mkdir(mode=0o700)
    (public / 'app-version.json').write_text(json.dumps({'version': c.FRONTEND}))
    prior = json.loads((HERE.parent / 'google-business-20261030/deployed.json').read_bytes())
    prior.update(nginx_sha256=c.H(NGINX), public_root=str(public), public_inventory_sha256='static-digest', schema_sha256='schema-digest')
    info = synthetic_info()
    info['Id'] = prior['crm']['id']
    runtime = lambda row: copy.deepcopy(prior['crm']) if row == info else {'unexpected': True}
    rows = {name: {'count': 0, 'rows_sha256': c.H(b'[]'), 'columns': ['id'], 'schema': {}, 'indexes': {}}
        for name in (list(c.TABLES) + ['protected_table_' + str(index) for index in range(119)])}
    inventory = {'main.py': 'unchanged'}
    calls = []

    def read(path, expected=None):
        if path == c.PRIOR / 'deployed.json':
            assert expected == c.PRIOR_SHA
            return json.dumps(prior).encode()
        if path == c.PRIOR / 'backend-candidate-inventory.json':
            assert expected == prior['candidate_inventory_sha256']
            return json.dumps(inventory).encode()
        if path == c.PINS:
            assert expected == c.PINS_SHA
            return b'{}'
        raise AssertionError(('unapproved read', path))

    fake = types.SimpleNamespace(read=read, inspect=lambda name: copy.deepcopy(info), runtime=runtime,
        retained=lambda: types.SimpleNamespace(require_safe_original_restart=lambda row: None),
        verify_secret_mount=lambda row: calls.append('secret-mount-stat-only'), verify_production_worker_enabled=lambda row: None,
        private_boundary=lambda pins: calls.append('private-readonly-boundary'), credential_boundary=lambda: {'stat_only': True},
        inventory=lambda name: copy.deepcopy(inventory), schema_signature=lambda path, rev: 'schema-digest',
        sql_snapshot=lambda path: copy.deepcopy(rows), tree=lambda path: {'app-version.json': 'unchanged'},
        digest=lambda value: 'static-digest' if 'app-version.json' in value else 'inventory-digest',
        NGINX=nginx, BUSINESS=db, ready=lambda name: calls.append('readiness-get'))
    monkeypatch.setattr(c, 'legacy', lambda: fake)

    def run(args, code, **kw):
        assert args == ['nginx', '-T']
        return b'# configuration file /etc/nginx/sites-enabled/t24-crm:\n' + NGINX + b'\n# elsewhere\nset $secret SUPERSECRET;\n'

    monkeypatch.setattr(c, 'run', run)
    return types.SimpleNamespace(module=fresh, fake=fake, info=info, rows=rows, inventory=inventory, calls=calls)


def test_real_preflight_body_succeeds_and_exports_no_env_or_record_values(preflight_fixture):
    fixture = preflight_fixture
    value = fixture.module.proof()
    assert value['stage'] == 'GBP_ACTIVATION_READONLY_PREFLIGHT'
    assert value['business_writes'] is False and value['configuration_changed'] is False
    assert len(value['rows']) == 124
    text = json.dumps(value)
    assert 'SUPERSECRET' not in text and 'synthetic-original' not in text
    assert 'private-readonly-boundary' in fixture.calls and 'readiness-get' in fixture.calls


def test_real_preflight_body_rejects_existing_google_env(preflight_fixture):
    preflight_fixture.info['Config']['Env'].append('T24_GBP_ENABLED=false')
    with pytest.raises(c.GuardError, match='GBP_ENVIRONMENT_MUST_BE_ABSENT'):
        preflight_fixture.module.proof()


def test_real_preflight_body_rejects_google_rows_before_authorization(preflight_fixture):
    preflight_fixture.rows['google_business_connections']['count'] = 1
    with pytest.raises(c.GuardError, match='GOOGLE_ROWS_MUST_STILL_BE_EMPTY'):
        preflight_fixture.module.proof()


def test_real_preflight_body_rejects_unexpected_schema(preflight_fixture):
    preflight_fixture.fake.schema_signature = lambda *args: 'changed-schema'
    with pytest.raises(c.GuardError, match='SCHEMA_DRIFT'):
        preflight_fixture.module.proof()


def test_real_preflight_body_catches_concurrent_business_write(preflight_fixture):
    fixture = preflight_fixture

    def ready(name):
        fixture.rows['protected_table_0']['count'] = 1

    fixture.fake.ready = ready
    with pytest.raises(c.GuardError, match='ROWS_CHANGED_DURING_PREFLIGHT'):
        fixture.module.proof()


@pytest.mark.parametrize('leak', ['none', 'access', 'error', 'stdout', 'stderr'])
def test_sentinel_checks_new_nginx_and_both_container_streams(store, monkeypatch, leak):
    c.mkdir(c.ROOT)
    c.mkdir(a.attempt_root())
    access, error = store / 'access.log', store / 'error.log'
    access.write_bytes(b'old log content\n')
    error.write_bytes(b'old error content\n')
    observed, opened = {}, []

    def open_log(path):
        fd = os.open(path, os.O_RDONLY)
        opened.append(fd)
        return fd, os.fstat(fd)

    def run(args, code, **kw):
        assert args[0] == 'curl'
        if args[-1] == c.ORIGIN + c.CALLBACK:
            return SECURITY_RESPONSE
        assert args[-1].startswith(c.ORIGIN + c.CALLBACK + '?code=')
        assert args[args.index('--resolve') + 1] == 't24-crm.com:443:127.0.0.1'
        sentinel = args[-1].split('?code=')[1].split('&')[0]
        observed['sentinel'] = sentinel
        if leak in {'access', 'error'}:
            path = access if leak == 'access' else error
            with path.open('ab') as stream:
                stream.write(('request ' + sentinel + '\n').encode())
        assert args[:2] == ['curl', '-q'] and args[args.index('--noproxy') + 1] == '*'
        return SECURITY_RESPONSE

    def logs(args, **kw):
        assert args[:3] == ['docker', 'logs', '--since'] and args[-1] == 't24-crm'
        return types.SimpleNamespace(returncode=0,
            stdout=observed['sentinel'].encode() if leak == 'stdout' else b'clean stdout',
            stderr=observed['sentinel'].encode() if leak == 'stderr' else b'clean stderr')

    monkeypatch.setattr(a, '_log_open', open_log)
    monkeypatch.setattr(c, 'run', run)
    monkeypatch.setattr(a.subprocess, 'run', logs)
    monkeypatch.setattr(a.time, 'sleep', lambda seconds: None)
    if leak == 'none':
        plan = {'nginx_log_paths': [str(access), str(error)], 'log_file_identities': {str(path): [path.stat().st_dev, path.stat().st_ino] for path in (access, error)},
            'baseline_security_header_sha256': a.security_fingerprints(SECURITY_RESPONSE)}
        result = a.sentinel_probe(None, plan)
        assert result['callback_sentinel_verified'] is True
        assert observed['sentinel'] not in json.dumps(result)
    else:
        with pytest.raises(c.GuardError, match='CALLBACK_QUERY_PRESENT'):
            a.sentinel_probe(None, {'nginx_log_paths': [str(access), str(error)], 'log_file_identities': {str(path): [path.stat().st_dev, path.stat().st_ino] for path in (access, error)},
                'baseline_security_header_sha256': a.security_fingerprints(SECURITY_RESPONSE)})
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.fixture
def callback_fixture(store, monkeypatch):
    real_readiness, real_sentinel = a.wait_callback_header_readiness, a.sentinel_probe
    c.mkdir(c.ROOT)
    c.mkdir(a.attempt_root())
    nginx = store / 'nginx.conf'
    nginx.write_bytes(NGINX)
    updated, added = a.next_nginx(NGINX)
    active = b'error_log /var/log/nginx/error.log;\n' + NGINX
    c.write(a.attempt_root() / 'nginx-before.conf', NGINX)
    c.write(a.attempt_root() / 'nginx-next.conf', updated)
    plan = {'stage': 'GBP_ACTIVATION_NGINX_PLAN_ONLY', 'source_sha': c.SOURCE, 'image': c.IMAGE,
        'schema_revision': c.REVISION, 'frontend_version': c.FRONTEND, 'prior_deployed_sha256': c.PRIOR_SHA,
        'nginx_before_sha256': c.H(NGINX), 'nginx_next_sha256': c.H(updated), 'active_config_before_sha256': c.H(active),
        'tool_sha256': a.tool_hashes(), 'callback_block_safe_view': preflight.safe_nginx_view(added), 'nginx_log_paths': ['/var/log/nginx/error.log']}
    plan['log_metadata_evidence_sha256'] = a.LOG_METADATA_EVIDENCE_SHA
    plan['attempt_namespace'] = a.ATTEMPT_NAMESPACE
    plan['baseline_security_header_sha256'] = a.security_fingerprints(SECURITY_RESPONSE)
    plan_sha = c.write(a.attempt_root() / 'nginx-plan.json', plan)
    review = review_fixture(plan_sha)
    arguments = {'plan_sha256': plan_sha, 'review': review, 'review_sha256': c.H(c.encoded(review))}
    monkeypatch.setattr(c, 'legacy', lambda: types.SimpleNamespace(NGINX=nginx))
    monkeypatch.setattr(c, 'run', lambda *args, **kw: b'error_log /var/log/nginx/error.log;\n' + nginx.read_bytes())
    monkeypatch.setattr(preflight, 'proof', lambda **kw: {'crm': {'id': 'same-disabled-container'}, 'active_nginx_config_sha256': c.H(b'error_log /var/log/nginx/error.log;\n' + nginx.read_bytes())})
    monkeypatch.setattr(a, 'sentinel_probe', lambda *args: {'callback_sentinel_verified': True, 'single_no_referrer_verified': True, 'other_security_header_fingerprints_unchanged': True})
    monkeypatch.setattr(a, 'wait_callback_header_readiness', lambda plan: {'noquery_header_readiness_verified': True, 'noquery_header_readiness_consecutive_successes': 2})
    monkeypatch.setattr(a, 'verify_worker_identity', lambda active: {'uid': 33})
    monkeypatch.setattr(a, 'verify_log_identities', lambda plan: None)
    reloads = []
    monkeypatch.setattr(a, 'reload_nginx', lambda: reloads.append('reload'))
    return types.SimpleNamespace(nginx=nginx, args=arguments, plan=plan, updated=updated, reloads=reloads,
        real_readiness=real_readiness, real_sentinel=real_sentinel)


def test_callback_protection_applies_only_reviewed_insert_and_saves_proof(callback_fixture):
    fixture = callback_fixture
    result = a.protect_callback(fixture.args)
    assert fixture.nginx.read_bytes() == fixture.updated
    assert result['stage'] == 'GBP_CALLBACK_LOGGING_PROTECTED' and result['callback_sentinel_verified'] is True
    assert fixture.reloads == ['reload']
    assert c.read(a.attempt_root() / 'approved.json') == c.encoded(fixture.args['review'])


def test_callback_missing_manual_flag_cannot_change_config(callback_fixture):
    fixture = callback_fixture
    fixture.args['review']['external_callback_logs_checked'] = False
    fixture.args['review_sha256'] = c.H(c.encoded(fixture.args['review']))
    with pytest.raises(c.GuardError, match='EXPLICIT_MANUAL_REVIEW_REQUIRED'):
        a.protect_callback(fixture.args)
    assert fixture.nginx.read_bytes() == NGINX and fixture.reloads == []


def test_nginx_test_failure_restores_only_original_bytes(callback_fixture, monkeypatch):
    fixture = callback_fixture

    def reload():
        fixture.reloads.append('reload')
        if len(fixture.reloads) == 1:
            raise c.GuardError('SYNTHETIC_NGINX_TEST_FAILED')

    monkeypatch.setattr(a, 'reload_nginx', reload)
    with pytest.raises(c.GuardError, match='SYNTHETIC_NGINX_TEST_FAILED'):
        a.protect_callback(fixture.args)
    assert fixture.nginx.read_bytes() == NGINX and fixture.reloads == ['reload', 'reload']
    assert not (a.attempt_root() / 'logging-protected.json').exists()


def test_sentinel_leak_restores_original_before_any_oauth(callback_fixture, monkeypatch):
    fixture = callback_fixture

    def leak(*args):
        raise c.GuardError('CALLBACK_QUERY_PRESENT_IN_NGINX_LOG')

    monkeypatch.setattr(a, 'sentinel_probe', leak)
    with pytest.raises(c.GuardError, match='CALLBACK_QUERY_PRESENT_IN_NGINX_LOG'):
        a.protect_callback(fixture.args)
    assert fixture.nginx.read_bytes() == NGINX and fixture.reloads == ['reload', 'reload']
    assert not (a.attempt_root() / 'logging-protected.json').exists()


def test_full_global_nginx_drift_blocks_enable_before_any_container_change(switch_fixture, monkeypatch):
    fixture = switch_fixture
    previous = c.run

    def changed(args, code, **kwargs):
        if args == ['nginx', '-T']:
            return fixture.active_body + b'\nset $global_tracing changed;\n'
        return previous(args, code, **kwargs)

    monkeypatch.setattr(c, 'run', changed)
    with pytest.raises(c.GuardError, match='FULL_ACTIVE_NGINX_CONFIGURATION_DRIFT'):
        a.enable(fixture.args)
    assert not fixture.commands and fixture.inspect('t24-crm')['Id'] == fixture.original['Id']


def test_new_log_destination_or_debug_blocks_sentinel_scan_of_old_paths(switch_fixture, monkeypatch):
    fixture = switch_fixture
    previous = c.run

    def changed(args, code, **kwargs):
        if args == ['nginx', '-T']:
            return fixture.active_body + b'\nerror_log /var/log/nginx/new.log debug;\n'
        return previous(args, code, **kwargs)

    monkeypatch.setattr(c, 'run', changed)
    with pytest.raises(c.GuardError, match='DEBUG_LOGGING_BLOCKS_OAUTH_ACTIVATION'):
        a.enable(fixture.args)
    assert not fixture.commands


def test_actual_literal_caret_prefix_keeps_api_and_private_locations_unchanged():
    actual = NGINX.replace(b'location /api/ {', b'location ^~ /api/ {')
    private = b'    location ^~ /api/v1/private-workspace/ { proxy_pass http://127.0.0.1:8001; }\n'
    actual = actual.replace(b'    location ^~ /api/ {', private + b'    location ^~ /api/ {')
    updated, added = a.next_nginx(actual)
    assert updated.replace(added, b'', 1) == actual
    assert b'127.0.0.1:8000' in added and b'127.0.0.1:8001' not in added
    assert updated.count(b'location ^~ /api/ {') == 1


def test_diagnostics_logging_parser_never_exports_format_or_syslog_values():
    blob = b'''error_log /var/log/nginx/error.log warn;
http { access_log /var/log/nginx/access.log main;
log_format main '$remote_addr SUPERSECRET $request'
  ' $http_authorization';
access_log syslog:server=SUPERSECRET:1234;
load_module modules/ngx_http_opentelemetry_SUPERSECRET.so;
server { location / { error_log /unknown/SUPERSECRET.log debug; } }
}
'''
    logs, markers = d.logging_view(blob)
    text = json.dumps({'logs': logs, 'markers': markers})
    assert 'SUPERSECRET' not in text and '$http_authorization' not in text
    assert any(row.get('format_name') == 'main' for row in logs)
    assert any(row.get('destination_type') == 'syslog' for row in logs)
    assert any(row.get('debug_enabled') is True for row in logs)
    assert markers == ['opentelemetry']


def test_public_dns_filters_private_loopback_reserved_and_fake_ip_answers():
    rows = [(None, None, None, None, (ip, 443)) for ip in ['1.1.1.1', '1.1.1.1', '2606:4700:4700::1111', '198.18.1.1', '127.0.0.1', '10.0.0.1', '203.0.113.1']]
    values, nonpublic = d.public_dns_ips(rows)
    assert values == ['1.1.1.1', '2606:4700:4700::1111'] and nonpublic is True


def test_diagnostics_actual_pin_matches_latest_readonly_proof():
    path = HERE.parents[1] / 'outputs/google-business-activation-20261030/preflight.json'
    if not path.exists():
        pytest.fail('Actual readonly preflight evidence is required for diagnostics pin')
    value = json.loads(path.read_bytes())
    assert d.ACTIVE_NGINX_SHA == value['active_nginx_config_sha256']
    assert any(row['config'] == 'location ^~ /api/ {' for row in value['nginx_safe_view'])


def test_readonly_diagnostics_exports_names_not_values(preflight_fixture, monkeypatch):
    fixture = preflight_fixture
    fixture.info['HostConfig']['LogConfig'] = {'Type': 'json-file', 'Config': {'max-size': 'SUPERSECRET_VALUE', 'max-file': 'SENSITIVE'}}
    fixture.info['Config']['Env'] += ['SENTRY_DSN=SUPERSECRET_VALUE', 'OTEL_EXPORTER_OTLP_HEADERS=SUPERSECRET_HEADER', 'DD_API_KEY=SUPERSECRET_KEY']
    fixture.info['Config']['Entrypoint'] = ['ddtrace-run', 'SUPERSECRET_ARGUMENT']
    active = b'error_log /var/log/nginx/error.log warn;\n' + NGINX
    monkeypatch.setattr(d, 'ACTIVE_NGINX_SHA', c.H(active))
    monkeypatch.setattr(c, 'run', lambda *args, **kwargs: active)

    def dns(name, port, **kwargs):
        assert name == 't24-crm.com' and port == 443 and kwargs == {'type': d.socket.SOCK_STREAM}
        return [(None, None, None, None, ('1.1.1.1', 443))]

    monkeypatch.setattr(d.socket, 'getaddrinfo', dns)
    result = d.proof()
    text = json.dumps(result)
    assert 'SUPERSECRET' not in text and 'SENSITIVE' not in text
    assert result['docker_log_option_names'] == ['max-file', 'max-size']
    assert result['apm_or_logging_environment_names'] == ['DD_API_KEY', 'OTEL_EXPORTER_OTLP_HEADERS', 'SENTRY_DSN']
    assert result['instrumentation_command_markers'] == ['ddtrace-run']
    assert result['manual_external_logging_review_still_required'] is True
    assert result['business_writes'] is False and result['configuration_changed'] is False


def test_diagnostics_wrapper_is_readonly_and_accepts_no_input():
    script = make_commands.command('diagnostics', {})
    assert "loaded['diagnostics'].main()" in script
    assert "'transport':" not in script and "'activation':" not in script
    with pytest.raises(ValueError):
        make_commands.command('diagnostics', {'arbitrary_host': 'other.example'})


@pytest.fixture
def observed_log(monkeypatch):
    item = types.SimpleNamespace(st_uid=33, st_gid=4, st_mode=stat.S_IFREG | 0o640, st_nlink=1,
        st_dev=1, st_ino=42, st_size=0, st_mtime_ns=1)
    parent = types.SimpleNamespace(st_uid=0, st_gid=4, st_mode=stat.S_IFDIR | 0o755, st_nlink=2)
    opened = types.SimpleNamespace(**vars(item))
    context = types.SimpleNamespace(item=item, parent=parent, opened=opened, closed=[], resolved='/var/log/nginx/access.log')
    old_lstat, old_resolve = Path.lstat, Path.resolve
    old_open, old_fstat, old_close = os.open, os.fstat, os.close

    def lstat(path):
        if str(path) == '/var/log/nginx':
            return parent
        if str(path) == '/var/log/nginx/access.log':
            return item
        return old_lstat(path)

    def resolve(path, **kwargs):
        if str(path) == '/var/log/nginx/access.log':
            return Path(context.resolved)
        return old_resolve(path, **kwargs)

    monkeypatch.setattr(Path, 'lstat', lstat)
    monkeypatch.setattr(Path, 'resolve', resolve)
    monkeypatch.setattr(os, 'open', lambda path, flags, *args: 999 if str(path) == '/var/log/nginx/access.log' else old_open(path, flags, *args))
    monkeypatch.setattr(os, 'fstat', lambda fd: opened if fd == 999 else old_fstat(fd))
    monkeypatch.setattr(os, 'close', lambda fd: context.closed.append(fd) if fd == 999 else old_close(fd))
    return context


def test_observed_worker_owned_log_is_accepted_without_chown(observed_log):
    fd, value = a._log_open('/var/log/nginx/access.log')
    assert fd == 999 and value.st_uid == 33 and value.st_gid == 4
    assert observed_log.closed == []
    os.close(fd)
    assert observed_log.closed == [999]


@pytest.mark.parametrize('target,key,value', [
    ('item', 'st_uid', 0), ('item', 'st_gid', 0), ('item', 'st_mode', stat.S_IFREG | 0o600),
    ('item', 'st_mode', stat.S_IFLNK | 0o777), ('item', 'st_nlink', 2),
    ('parent', 'st_uid', 33), ('parent', 'st_gid', 0), ('parent', 'st_mode', stat.S_IFDIR | 0o777), ('parent', 'st_nlink', 3),
    ('opened', 'st_ino', 43), ('opened', 'st_uid', 0), ('opened', 'st_gid', 0), ('opened', 'st_nlink', 2),
])
def test_observed_log_metadata_or_replacement_drift_is_denied(observed_log, target, key, value):
    setattr(getattr(observed_log, target), key, value)
    with pytest.raises(c.GuardError):
        a._log_open('/var/log/nginx/access.log')
    if target == 'opened':
        assert observed_log.closed == [999]


def test_observed_log_symlink_target_change_is_denied(observed_log):
    observed_log.resolved = '/dev/stdout'
    with pytest.raises(c.GuardError, match='NGINX_LOG_PATH_REJECTED'):
        a._log_open('/var/log/nginx/access.log')


def test_observed_worker_is_bound_to_actual_user_uid_and_gid(monkeypatch):
    monkeypatch.setattr(a.pwd, 'getpwnam', lambda name: types.SimpleNamespace(pw_uid=33, pw_gid=33))
    assert a.verify_worker_identity(b'user www-data;\nhttp {}')['uid'] == 33
    with pytest.raises(c.GuardError, match='OBSERVED_NGINX_WORKER_CONFIGURATION_DRIFT'):
        a.verify_worker_identity(b'user root;\nhttp {}')
    monkeypatch.setattr(a.pwd, 'getpwnam', lambda name: types.SimpleNamespace(pw_uid=33, pw_gid=4))
    with pytest.raises(c.GuardError, match='OBSERVED_NGINX_WORKER_IDENTITY_DRIFT'):
        a.verify_worker_identity(b'user www-data;\nhttp {}')


def test_actual_supplemental_receipt_exactly_matches_log_policy():
    path = HERE.parents[1] / 'outputs/google-business-activation-20261030/supplemental.json'
    blob = path.read_bytes()
    assert c.H(blob) == a.LOG_METADATA_EVIDENCE_SHA
    receipt = json.loads(blob)
    assert receipt['nginx_worker_identity']['uid'] == 33 and receipt['nginx_worker_identity']['effective_gid'] == 33
    assert {row['path']: (row['uid'], row['gid'], int(row['mode'], 8)) for row in receipt['nginx_log_path_metadata']} == a.EXPECTED_LOG_METADATA
    assert all(row['nlink'] == 1 and row['is_regular_file'] and not row['is_symlink'] and row['resolved_path'] == row['path'] and
        row['parent'] == {'uid': 0, 'gid': 4, 'mode': '0755', 'nlink': 2, 'is_directory': True, 'resolved_path': '/var/log/nginx'} for row in receipt['nginx_log_path_metadata'])


def test_plan_live_inode_pin_detects_rotation_after_approval(monkeypatch):
    identities = {name: [1, index] for index, name in enumerate(a.EXPECTED_LOG_METADATA)}
    monkeypatch.setattr(a, 'capture_log_identities', lambda paths: copy.deepcopy(identities))
    plan = {'log_metadata_evidence_sha256': a.LOG_METADATA_EVIDENCE_SHA, 'nginx_log_paths': sorted(a.EXPECTED_LOG_METADATA), 'log_file_identities': copy.deepcopy(identities)}
    a.verify_log_identities(plan)
    identities['/var/log/nginx/access.log'][1] += 1
    with pytest.raises(c.GuardError, match='OBSERVED_LOG_FILE_IDENTITY_DRIFT'):
        a.verify_log_identities(plan)


def test_v2_callback_only_referrer_override_preserves_existing_bytes_and_sibling_headers():
    original = NGINX.replace(b'    location / { try_files $uri $uri/ /index.html; }',
        b'    location / { add_header X-Frame-Options SAMEORIGIN always; try_files $uri $uri/ /index.html; }')
    updated, added = a.next_nginx(original)
    assert updated.replace(added, b'', 1) == original
    assert added.count(b'proxy_hide_header Referrer-Policy;') == 1
    assert added.count(b'add_header Referrer-Policy no-referrer always;') == 1
    assert b'add_header X-Frame-Options' not in added
    a.verify_header_inheritance(original)
    a.verify_header_inheritance(updated, callback_present=True)


@pytest.mark.parametrize('directive', [
    b'add_header X-Frame-Options SAMEORIGIN always;',
    b'proxy_hide_header X-Private-Upstream;',
    b'proxy_pass_header Referrer-Policy;',
])
def test_v2_will_not_cancel_unknown_parent_or_include_header_protections(directive):
    for original in (b'http { ' + directive + b' }\n' + NGINX, directive + b'\n' + NGINX,
                     NGINX.replace(b'    root /var/', b'    ' + directive + b'\n    root /var/')):
        with pytest.raises(c.GuardError, match='INHERITED_NGINX_HEADER_RULES_REQUIRE_REVIEW'):
            a.verify_header_inheritance(original)


@pytest.mark.parametrize('setting', ['on', 'off', 'merge'])
def test_custom_header_inheritance_mode_requires_explicit_review(setting):
    with pytest.raises(c.GuardError, match='CUSTOM_HEADER_INHERITANCE_REQUIRES_REVIEW'):
        a.verify_header_inheritance(('http { add_header_inherit ' + setting + '; }\n').encode() + NGINX)


@pytest.mark.parametrize('mutation', [
    lambda value: value.replace(b'proxy_hide_header Referrer-Policy;', b''),
    lambda value: value.replace(b'no-referrer always;', b'no-referrer;'),
    lambda value: value.replace(b'no-referrer always;', b'strict-origin-when-cross-origin always;'),
    lambda value: value.replace(b'add_header Referrer-Policy no-referrer always;', b'add_header Referrer-Policy no-referrer always; add_header X-Frame-Options DENY;'),
])
def test_v2_callback_override_must_be_exactly_the_reviewed_pair(mutation):
    updated, _ = a.next_nginx(NGINX)
    with pytest.raises(c.GuardError, match='EXACT_CALLBACK_REFERRER_OVERRIDE_REQUIRED'):
        a.verify_header_inheritance(mutation(updated), callback_present=True)


@pytest.mark.parametrize('response,expected', [
    (SECURITY_RESPONSE, None),
    (SECURITY_RESPONSE.replace(b'Referrer-Policy: no-referrer', b'Referrer-Policy: strict-origin-when-cross-origin'), 'CALLBACK_SENTINEL_RESPONSE_REJECTED'),
    (SECURITY_RESPONSE.replace(b'Referrer-Policy: no-referrer', b'Referrer-Policy: no-referrer\r\nReferrer-Policy: strict-origin-when-cross-origin'), 'CALLBACK_SENTINEL_RESPONSE_REJECTED'),
    (SECURITY_RESPONSE.replace(b'Content-Security-Policy: default-src self', b'Content-Security-Policy: default-src unsafe'), 'CALLBACK_OTHER_SECURITY_HEADERS_CHANGED'),
    (SECURITY_RESPONSE.replace(b'X-Frame-Options: SAMEORIGIN\r\n', b''), 'BASELINE_SECURITY_HEADERS_REQUIRED'),
])
def test_v2_sentinel_rejects_conflicting_referrer_or_other_security_header_drift(store, monkeypatch, response, expected):
    c.mkdir(c.ROOT)
    c.mkdir(a.attempt_root())
    monkeypatch.setattr(c, 'run', lambda *args, **kwargs: response)
    monkeypatch.setattr(a.subprocess, 'run', lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout=b'', stderr=b''))
    monkeypatch.setattr(a.time, 'sleep', lambda seconds: None)
    plan = {'nginx_log_paths': [], 'log_file_identities': {}, 'baseline_security_header_sha256': a.security_fingerprints(SECURITY_RESPONSE)}
    if expected:
        with pytest.raises(c.GuardError, match=expected):
            a.sentinel_probe(None, plan)
    else:
        proof = a.sentinel_probe(None, plan)
        assert proof['single_no_referrer_verified'] is True and proof['other_security_header_fingerprints_unchanged'] is True


def test_baseline_header_get_never_sends_query_cookie_auth_or_curlrc_defaults(monkeypatch):
    calls = []

    def run(args, code, **kwargs):
        calls.append(args)
        assert args[:2] == ['curl', '-q'] and args[args.index('--noproxy') + 1] == '*'
        assert args[-1] == c.ORIGIN + c.CALLBACK
        assert not any(value in args for value in ('--cookie', '-b', '--header', '-H'))
        return SECURITY_RESPONSE.replace(b'Referrer-Policy: no-referrer', b'Referrer-Policy: strict-origin-when-cross-origin')

    monkeypatch.setattr(c, 'run', run)
    assert a.baseline_security_headers() == a.security_fingerprints(SECURITY_RESPONSE)
    assert len(calls) == 1


def test_v2_namespace_does_not_touch_v1_plan_review_or_dedicated_credential_receipt(switch_fixture):
    fixture = switch_fixture
    originals = {'nginx-plan.json': b'prior immutable plan', 'approved.json': b'prior immutable manual review',
        'nginx-before.conf': b'prior original nginx snapshot', 'nginx-next.conf': b'prior failed-attempt proposal'}
    for name, body in originals.items(): c.write(c.ROOT / name, body)
    v2_root = c.ROOT / 'attempt-v2'
    c.mkdir(v2_root)
    c.write(v2_root / 'approved.json', b'prior v2 immutable review')
    credential_before = c.read(c.ROOT / 'credential-receipt.json')
    result = a.enable(fixture.args)
    assert result['enabled'] is True
    assert a.attempt_root().parent == c.ROOT and a.attempt_root().name == 'attempt-v3'
    assert (a.attempt_root() / 'enabled.json').exists() and not (c.ROOT / 'enabled.json').exists()
    for name, body in originals.items(): assert c.read(c.ROOT / name) == body
    assert c.read(v2_root / 'approved.json') == b'prior v2 immutable review'
    assert c.read(c.ROOT / 'credential-receipt.json') == credential_before


def test_v2_new_plan_preserves_prior_attempt_artifacts_and_stores_only_header_hashes(store, monkeypatch):
    c.mkdir(c.ROOT)
    originals = {'nginx-plan.json': b'old plan', 'approved.json': b'old review', 'nginx-before.conf': b'old nginx'}
    for name, body in originals.items(): c.write(c.ROOT / name, body)
    original = synthetic_info()
    active = b'user www-data;\nerror_log /var/log/nginx/access.log;\nerror_log /var/log/nginx/error.log;\nerror_log /var/log/nginx/t24-private-error.log;\n' + NGINX
    monkeypatch.setattr(c, 'legacy', lambda: types.SimpleNamespace(NGINX=types.SimpleNamespace(read_bytes=lambda: NGINX), inspect=lambda name: original))
    monkeypatch.setattr(c, 'run', lambda args, code, **kwargs: active if args == ['nginx', '-T'] else SECURITY_RESPONSE)
    monkeypatch.setattr(a, 'verify_worker_identity', lambda value: {'configured_user': 'www-data', 'uid': 33, 'primary_gid': 33})
    monkeypatch.setattr(a, 'capture_log_identities', lambda paths: {path: [1, index] for index, path in enumerate(paths)})
    result = a.plan_nginx()
    assert result['attempt_namespace'] == 'attempt-v3'
    assert result['baseline_security_header_sha256'] == a.security_fingerprints(SECURITY_RESPONSE)
    assert 'default-src self' not in json.dumps(result) and 'SAMEORIGIN' not in json.dumps(result)
    for name, body in originals.items(): assert c.read(c.ROOT / name) == body
    assert (a.attempt_root() / 'nginx-plan.json').exists()


def test_failure_facts_never_include_raw_header_or_query_values(store, capsys):
    c.mkdir(c.ROOT); c.mkdir(a.attempt_root())
    plan = {'baseline_security_header_sha256': a.security_fingerprints(SECURITY_RESPONSE)}
    response = SECURITY_RESPONSE.replace(b'no-referrer', b'VERY_SECRET_POLICY').replace(b'default-src self', b'VERY_SECRET_CSP').replace(
        b'/media-ops?google=failed', b'https://private.example/?code=VERY_SECRET_QUERY').replace(b'\r\n\r\n', b'\r\nSet-Cookie: VERY_SECRET_COOKIE\r\n\r\n')
    facts = a.record_header_failure(response, plan, 'sentinel', 'CALLBACK_SENTINEL_RESPONSE_REJECTED', 1, a.time.monotonic())
    paths = list(a.attempt_root().glob('header-failure-facts-*.json'))
    assert len(paths) == 1 and paths[0].stat().st_mode & 0o777 == 0o600
    assert facts['referrer_policy_enums'] == ['OTHER_REDACTED'] and facts['referrer_policy_header_count'] == 1
    assert facts['http_status'] == 303 and facts['security_header_fingerprint_matches']['content-security-policy'] is False
    assert 'VERY_SECRET' not in paths[0].read_text() and 'VERY_SECRET' not in capsys.readouterr().out


def simulated_adoption(fixture, monkeypatch, *, always_old=False, query_old=False):
    clock = types.SimpleNamespace(value=0.0)
    events = []
    old = SECURITY_RESPONSE.replace(b'Referrer-Policy: no-referrer', b'Referrer-Policy: strict-origin-when-cross-origin')
    sequence = [old, SECURITY_RESPONSE, old, SECURITY_RESPONSE, SECURITY_RESPONSE]
    current_run = c.run
    monkeypatch.setattr(a.time, 'monotonic', lambda: clock.value)
    monkeypatch.setattr(a.time, 'sleep', lambda seconds: setattr(clock, 'value', clock.value + seconds))

    def run(args, code, **kwargs):
        if args[0] != 'curl': return current_run(args, code, **kwargs)
        assert args[:2] == ['curl', '-q'] and '--http1.1' in args
        assert args[args.index('--noproxy') + 1] == '*'
        assert args[args.index('--header') + 1] == 'Connection: close'
        clock.value += 0.01
        if '?code=' in args[-1]:
            events.append('query')
            assert events.count('noquery') >= 2
            return old if query_old else SECURITY_RESPONSE
        assert args[-1] == c.ORIGIN + c.CALLBACK
        events.append('noquery')
        assert float(args[args.index('--max-time') + 1]) <= 1.0
        assert kwargs.get('timeout', 0) <= 5.0
        if 'query' in events: return SECURITY_RESPONSE
        return old if always_old else sequence[min(events.count('noquery') - 1, len(sequence) - 1)]

    monkeypatch.setattr(c, 'run', run)
    monkeypatch.setattr(a, 'wait_callback_header_readiness', fixture.real_readiness)
    monkeypatch.setattr(a.subprocess, 'run', lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout=b'', stderr=b''))

    def sentinel(m, plan):
        # Actual query/header logic, with log IO isolated in its separate tests.
        return fixture.real_sentinel(m, {**plan, 'nginx_log_paths': [], 'log_file_identities': {}})

    monkeypatch.setattr(a, 'sentinel_probe', sentinel)
    return events, clock


def test_async_reload_adoption_requires_two_consecutive_noquery_matches_before_one_sentinel(callback_fixture, monkeypatch):
    fixture = callback_fixture
    events, clock = simulated_adoption(fixture, monkeypatch)
    result = a.protect_callback(fixture.args)
    assert events == ['noquery'] * 5 + ['query']
    assert result['noquery_header_readiness_attempts'] == 5
    assert result['noquery_header_readiness_consecutive_successes'] == 2
    assert result['single_no_referrer_verified'] is True and result['callback_sentinel_verified'] is True
    assert clock.value < 5 and fixture.nginx.read_bytes() == fixture.updated


def test_readiness_timeout_has_no_query_and_records_sanitized_facts_then_restores(callback_fixture, monkeypatch):
    fixture = callback_fixture
    events, clock = simulated_adoption(fixture, monkeypatch, always_old=True)
    with pytest.raises(c.GuardError, match='CALLBACK_HEADER_READINESS_TIMEOUT'):
        a.protect_callback(fixture.args)
    assert 'query' not in events and 0 < len(events) <= 50
    assert clock.value <= 5.05 and fixture.nginx.read_bytes() == NGINX
    assert not (a.attempt_root() / 'logging-protected.json').exists()
    paths = list(a.attempt_root().glob('header-failure-facts-*.json'))
    assert len(paths) == 1
    facts = json.loads(c.read(paths[0]))
    assert facts['request_kind'] == 'noquery-readiness' and facts['http_status'] == 303
    assert facts['referrer_policy_enums'] == ['strict-origin-when-cross-origin']
    assert facts['referrer_policy_header_count'] == 1 and facts['all_other_security_headers_unchanged'] is True


def test_final_query_failure_runs_one_diagnostic_noquery_get_never_retries_query(callback_fixture, monkeypatch):
    fixture = callback_fixture
    events, clock = simulated_adoption(fixture, monkeypatch, query_old=True)
    with pytest.raises(c.GuardError, match='CALLBACK_SENTINEL_RESPONSE_REJECTED'):
        a.protect_callback(fixture.args)
    assert events == ['noquery'] * 5 + ['query', 'noquery']
    assert events.count('query') == 1 and fixture.nginx.read_bytes() == NGINX
    facts = json.loads(c.read(next(a.attempt_root().glob('header-failure-facts-*.json'))))
    assert facts['request_kind'] == 'sentinel' and facts['referrer_policy_enums'] == ['strict-origin-when-cross-origin']
    diagnostic = facts['post_failure_noquery_diagnostic']
    assert diagnostic['diagnostic_get_completed'] is True and diagnostic['referrer_policy_enums'] == ['no-referrer']
    assert diagnostic['referrer_policy_header_count'] == 1 and diagnostic['all_other_security_headers_unchanged'] is True
    assert not (a.attempt_root() / 'logging-protected.json').exists()
