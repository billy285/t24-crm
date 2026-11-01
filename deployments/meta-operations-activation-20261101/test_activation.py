"""Synthetic Docker with real protected-file, metadata and boundary guards."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE/filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


c = load('meta_crm_switch_core_test', 'core.py')
b = load('meta_crm_switch_baseline_test', 'baseline.py')
a = load('meta_crm_switch_test', 'activation.py')
REAL_PRIVACY_PROBE = a._privacy_probe
r = load('meta_crm_switch_retained_guard', '../meta-business-20261031/release.py')
NEW = 'b'*64


def original():
    return {'Id': c.ORIGINAL_ID, 'Image': c.IMAGE, 'Name': '/t24-crm',
        'Config': {'Image': 'retained-image-tag', 'Hostname': 'original-host', 'Env': ['PRESERVED=private-canary',
            'T24_GBP_SCHEDULER_ENABLED=true', 'T24_GBP_SCHEDULER_ACTIVATION_FROM='+c.ACTIVATION_FROM,
            'T24_GBP_TOKEN_KEY=original-google-key'] + ['T24_META_'+key+'='+value for key,value in {'ENABLED':'true','APP_ID':'1139445441758834','APP_SECRET':'LEGACY_SECRET_CANARY','TOKEN_KEY':base64.urlsafe_b64encode(b'o'*32).decode(),'CONFIG_ID':'1146714154579519','GRAPH_VERSION':'v26.0','PUBLIC_URL':c.ORIGIN,'EXPECTED_SCOPES':','.join(('instagram_basic','pages_read_engagement','pages_show_list')),'LOGIN_CONFIG_REVIEWED':'true'}.items()], 'Labels': {'existing': 'unchanged'}, 'Cmd': ['serve']},
        'HostConfig': {'AutoRemove': False, 'OomKillDisable': None, 'NetworkMode': 'host', 'Privileged': False, 'RestartPolicy': {'Name': 'always'}},
        'Mounts': [{'Source': '/synthetic/database', 'Destination': '/app/backend/data', 'RW': True}],
        'NetworkSettings': {'Networks': {}}, 'State': {'Running': True, 'Status': 'running', 'StartedAt': 'old-start'}, 'RestartCount': 0}


def runtime(info):
    return {'id': info['Id'], 'image': info['Image'], 'started': info['State']['StartedAt'], 'restart': info['RestartCount'],
        'config': b.digest({key: info[key] for key in ('Config', 'HostConfig', 'Mounts', 'NetworkSettings')})}


def meta_rows():
    values = {'EXECUTION_ENABLED':'false','SCHEDULER_ENABLED':'false','ENABLED': 'true', 'APP_ID': c.APP_ID, 'APP_SECRET': 'synthetic-secret-not-exported',
        'TOKEN_KEY': base64.urlsafe_b64encode(b's'*32).decode(), 'CONFIG_ID': c.CONFIG_ID, 'GRAPH_VERSION': c.GRAPH_VERSION,
        'PUBLIC_URL': c.ORIGIN, 'EXPECTED_SCOPES': ','.join(c.SCOPES), 'LOGIN_CONFIG_REVIEWED': 'true'}
    return ['T24_META_OPS_'+key+'='+value for key, value in values.items()]


class Docker:
    runtime = staticmethod(runtime)
    def __init__(self):
        self.items = {c.ORIGINAL_ID: original()}; self.calls = []; self.hook = None; self.unsafe_source = set()
    def inspect_optional(self, key):
        value = next((row for row in self.items.values() if row['Id'] == key or row['Name'] == '/'+key), None)
        return copy.deepcopy(value) if value else None
    def inspect(self, key):
        value = self.inspect_optional(key); c.need(value is not None, 'SYNTHETIC_ID_MISSING'); return value
    def retained(self): return self
    def clone_networks(self, info): return copy.deepcopy(info['NetworkSettings']['Networks'])
    def docker_request(self, method, path, config):
        assert method == 'POST' and path.startswith('/containers/create?name=')
        row = original(); row.update(Id=NEW, Name='/'+path.split('=', 1)[1])
        row['Config'] = {key: copy.deepcopy(value) for key, value in config.items() if key not in {'HostConfig', 'NetworkingConfig'}}
        row['HostConfig'] = copy.deepcopy(config['HostConfig']); row['HostConfig']['OomKillDisable'] = False
        row['State'].update(Running=False, Status='created', StartedAt='0001-01-01T00:00:00Z')
        self.items[NEW] = row
        if self.hook: self.hook('created', self)
        return 201, json.dumps({'Id': NEW}).encode()
    def run(self, argv, code, *_):
        self.calls.append(copy.deepcopy(argv))
        if self.hook: self.hook(code, self)
        assert argv[0] == 'docker'
        if argv[1] == 'stop': self.items[argv[-1]]['State'].update(Running=False, Status='exited')
        elif argv[1] == 'rename':
            c.need(self.inspect_optional(argv[3]) is None, 'SYNTHETIC_NAME_COLLISION'); self.items[argv[2]]['Name'] = '/'+argv[3]
        elif argv[1] == 'start': self.items[argv[2]]['State'].update(Running=True, Status='running', StartedAt='new-start')
        elif argv[1] == 'exec': return b'EXACT_OPS_CONFIGURED_WRITES_OFF_READ_GOOGLE_ON_NO_NETWORK\n'
        else: pytest.fail('Unreviewed Docker operation')
        return b''
    def ready(self, identity):
        c.need(self.inspect(identity)['State']['Running'] is True, 'SYNTHETIC_NOT_READY')
        if self.hook: self.hook('ready', self)
    def verify_secret_mount(self, info): c.need(info['Mounts'] == original()['Mounts'], 'SYNTHETIC_MOUNT_CHANGED')
    def verify_production_worker_enabled(self, info):
        c.need('T24_GBP_SCHEDULER_ENABLED=true' in info['Config']['Env'], 'SYNTHETIC_WORKER_CHANGED')


@pytest.fixture
def switch(tmp_path, monkeypatch):
    anchor = tmp_path.resolve(); root = anchor/'stage'; root.mkdir(mode=0o700)
    secret = anchor/'secret'; secret.mkdir(mode=0o700)
    monkeypatch.setattr(c, 'ROOT', root); monkeypatch.setattr(c, 'ENV_FILE', secret/'runtime.env')
    monkeypatch.setattr(c, 'FS_ANCHOR', anchor); monkeypatch.setattr(c, 'OWNER_UID', os.geteuid())
    monkeypatch.setattr(c, 'server_guard', lambda: None)
    monkeypatch.setattr(c,'APP_ID','7777777777777777');monkeypatch.setattr(c,'SOURCE_SHA','a'*40);monkeypatch.setattr(c,'FRONTEND','6'*12);monkeypatch.setattr(c,'ORIGINAL_ID','1'*64);monkeypatch.setattr(c,'IMAGE','sha256:'+'2'*64);monkeypatch.setattr(c,'DEPLOYED_SHA','3'*64);monkeypatch.setattr(c,'RELEASE_TOOL_SHA','4'*64);monkeypatch.setattr(c,'CONFIG_ID','2222222222222222');monkeypatch.setattr(c,'GRAPH_VERSION','v26.0');monkeypatch.setattr(c,'CONFIG_FREEZE_SHA','a'*64)
    m = Docker(); counters = {'monthly_deduction_rates': 42, 'other': 7}
    sample = {'rows': {f'table_{n}': {'count': 1, 'rows_sha256': 'a'*64} for n in range(136)} |
        {name: {'count': 4, 'rows_sha256':'b'*64} for name in r.NEW_TABLES} |
        {'meta_operations_'+name:{'count':2,'rows_sha256':'c'*64} for name in ('credentials','oauth_states','bindings','media','targets','drafts','actions','schedules','requests')},
        'schema_sha256':'schema-fixed', 'database_metadata':{'pragma_sha256':'c'*64,'sequence_exists':True,'sequence_values':counters,
        'sequence_sha256':r.digest(sorted(counters.items()))}, 'active_nginx_sha256':'d'*64, 'private_boundary':'fixed','credential_boundary':'fixed'}
    proof = copy.deepcopy(sample) | {'crm': runtime(original())}
    def meta_absent(info): c.need(not any(row.startswith('T24_META_') for row in info['Config']['Env']), 'SYNTHETIC_OLD_META_CHANGED')
    def google(info):
        c.need(all(row in info['Config']['Env'] for row in original()['Config']['Env'] if row.startswith('T24_GBP_')), 'SYNTHETIC_GOOGLE_CHANGED')
    ctx = SimpleNamespace(m=m, workflow=SimpleNamespace(retained=r,pf=SimpleNamespace(google_environment=google)),
        helper=SimpleNamespace(validation_window=lambda info: c.need(info['State']['Running'], 'SYNTHETIC_WINDOW_FAILED')))
    b.configure(c); a.configure(c, b); monkeypatch.setattr(b, 'BASELINE_SHA', 'e'*64)
    monkeypatch.setattr(b, 'dependencies', lambda: ctx); monkeypatch.setattr(b, 'proof', lambda: copy.deepcopy(proof))
    monkeypatch.setattr(b, '_sample', lambda ctx:copy.deepcopy(sample))
    monkeypatch.setattr(b,'legacy_environment',lambda ctx,info:c.old_environment(info['Config']['Env']))
    monkeypatch.setattr(b, 'source', lambda ctx, info: c.need(info['Id'] not in m.unsafe_source, 'SYNTHETIC_SOURCE_CHANGED'))
    monkeypatch.setattr(a, '_privacy_probe', lambda *args: {'meta_callback_privacy_headers_verified': True})
    body = ('\n'.join(meta_rows())+'\n').encode(); c.write(c.ENV_FILE, body)
    receipt = {'stage': 'META_OPERATIONS_CREDENTIALS_STORED_RUNTIME_UNCHANGED', 'app_id': c.APP_ID, 'business_id': c.BUSINESS_ID,
        'config_id': c.CONFIG_ID, 'graph_version': c.GRAPH_VERSION, 'configuration_freeze_sha256': c.CONFIG_FREEZE_SHA,
        'env_path': str(c.ENV_FILE), 'env_sha256': c.H(body), 'independent_fernet_key_generated': True,
        'credential_values_exported': False, 'runtime_changed': False, 'business_writes': False, 'provider_requests': False,'execution_enabled':False,'scheduler_enabled':False,'existing_read_credentials_preserved':True}
    c.write(root/'credential-receipt.json', receipt)
    return SimpleNamespace(m=m, sample=sample, proof=proof, root=root, ctx=ctx)


def activate():
    if not (c.ROOT/'prepared.json').exists():
        result=a.prepare();review=result['receipt_sha256']
    else:review=c.H(c.read(c.ROOT/'prepared.json'))
    return a.activate(review)


def test_complete_same_image_exact_nine_env_only_no_secret_export(switch):
    before = copy.deepcopy(switch.sample); result = activate(); m = switch.m
    assert result['stage'] == 'META_OPERATIONS_PUBLISHER_RUNTIME_ACTIVATED' and result['same_application_image']
    assert m.inspect('t24-crm')['Id'] == NEW and not m.inspect(c.ORIGINAL_ID)['State']['Running']
    a.compare(m.inspect(NEW), m.inspect(c.ORIGINAL_ID), meta_rows(), m)
    assert len(m.inspect(NEW)['Config']['Env'])==len(original()['Config']['Env'])+11
    assert m.inspect(NEW)['Config']['Env'][:-11] == original()['Config']['Env']
    assert switch.sample == before and result['real_publisher_oauth_verified'] is False and result['provider_requests'] is False
    exported = json.dumps(result)+json.dumps(m.calls)+''.join(path.read_text() for path in switch.root.glob('*.json'))
    assert 'synthetic-secret-not-exported' not in exported and 'private-canary' not in exported and 'LEGACY_SECRET_CANARY' not in exported and base64.urlsafe_b64encode(b's'*32).decode() not in exported
    assert {argv[1] for argv in m.calls} <= {'stop', 'rename', 'start', 'exec'}


@pytest.mark.parametrize('kind', ['old_env', 'label', 'mount', 'cmd', 'host_option', 'unexpected_meta', 'ipam', 'oom'])
def test_exact_runtime_configuration_rejects_non_meta_changes(switch, kind):
    old = original(); config = a.clone_config(old, meta_rows(), switch.m); switch.m.docker_request('POST', '/containers/create?name=test', config)
    row = switch.m.items[NEW]
    if kind == 'old_env': row['Config']['Env'][0] = 'PRESERVED=other'
    elif kind == 'label': row['Config']['Labels']['new'] = 'value'
    elif kind == 'mount': row['Mounts'][0]['RW'] = False
    elif kind == 'cmd': row['Config']['Cmd'] = ['other']
    elif kind == 'host_option': row['HostConfig']['Privileged'] = True
    elif kind == 'unexpected_meta': row['Config']['Env'].append('T24_META_EXTRA=true')
    elif kind == 'ipam': row['NetworkSettings']['Networks']['bridge'] = {'IPAMConfig': {'IPv4Address': '192.0.2.1'}}
    else: row['HostConfig']['OomKillDisable'] = True
    with pytest.raises(RuntimeError): a.compare(row, old, meta_rows(), switch.m)


@pytest.mark.parametrize('kind', ['row', 'schema', 'private', 'counter', 'source'])
def test_change_before_stop_never_stops_original(switch, kind):
    def hook(stage, m):
        if stage != 'created': return
        if kind == 'row': switch.sample['rows']['table_0']['count'] = 2
        elif kind == 'schema': switch.sample['schema_sha256'] = 'changed'
        elif kind == 'private': switch.sample['private_boundary'] = 'changed'
        elif kind == 'counter':
            values = switch.sample['database_metadata']['sequence_values']; values['other'] += 1
            switch.sample['database_metadata']['sequence_sha256'] = r.digest(sorted(values.items()))
        else: m.unsafe_source.add(NEW)
    switch.m.hook = hook
    with pytest.raises(RuntimeError): activate()
    assert switch.m.inspect(c.ORIGINAL_ID)['State']['Running'] is True
    assert not any(argv[:2] == ['docker', 'stop'] and argv[-1] == c.ORIGINAL_ID for argv in switch.m.calls)
    assert not (switch.root/'activated.json').exists()


def test_candidate_identity_is_durable_before_any_original_stop(switch, monkeypatch):
    real = c.write
    def fail(path, value):
        if path.name == 'candidate-created.json': raise RuntimeError('SYNTHETIC_FSYNC_FAILURE')
        return real(path, value)
    monkeypatch.setattr(c, 'write', fail)
    with pytest.raises(RuntimeError, match='SYNTHETIC_FSYNC_FAILURE'): activate()
    assert not any(argv[:2] == ['docker', 'stop'] for argv in switch.m.calls)
    assert switch.m.inspect(c.ORIGINAL_ID)['State']['Running'] and not switch.m.inspect(NEW)['State']['Running']
    result = a.recover(); assert result['manual_orphan_review_required'] and not any(argv[:2] == ['docker', 'stop'] for argv in switch.m.calls)


@pytest.mark.parametrize('kind', ['after_start', 'independent_rows', 'privacy_failure'])
def test_failure_restores_only_known_original_without_database_restore(switch, monkeypatch, kind):
    fired = []
    def hook(stage, m):
        if stage == 'ready' and m.inspect(NEW)['State']['Running'] and not fired:
            fired.append(True)
            if kind == 'independent_rows': switch.sample['rows']['table_0']['count'] = 2
            if kind != 'privacy_failure': raise RuntimeError('SYNTHETIC_ACCEPTANCE_FAILED')
    switch.m.hook = hook
    if kind == 'privacy_failure': monkeypatch.setattr(a, '_privacy_probe', lambda *args: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_PRIVACY_FAILURE')))
    with pytest.raises(RuntimeError): activate()
    assert switch.m.inspect('t24-crm')['Id'] == c.ORIGINAL_ID and switch.m.inspect(c.ORIGINAL_ID)['State']['Running']
    assert switch.m.inspect(NEW)['State']['Running'] is False and not (switch.root/'activated.json').exists()
    if kind == 'independent_rows': assert switch.sample['rows']['table_0']['count'] == 2
    assert not any(argv[:2] in (['docker', 'rm'], ['docker', 'cp']) for argv in switch.m.calls)
    receipt = json.loads(next(switch.root.glob('recovery-*.json')).read_text())
    assert receipt['database_restored'] is False and receipt['business_writes'] is False


def test_activate_and_external_recovery_share_same_lock(switch):
    fd = a._lock()
    try:
        for operation in (activate, a.recover):
            with pytest.raises(BlockingIOError): operation()
        assert switch.m.calls == []
    finally: os.close(fd)


def test_successful_activation_cannot_be_blindly_replayed_or_recovered(switch):
    activate(); previous = copy.deepcopy(switch.m.calls)
    for operation in (activate, a.recover):
        with pytest.raises(RuntimeError): operation()
    assert previous == switch.m.calls and switch.m.inspect('t24-crm')['Id'] == NEW


def test_credential_receipt_exact_hash_and_dedicated_key_are_required(switch):
    c.ENV_FILE.write_bytes(c.ENV_FILE.read_bytes().replace(b'synthetic-secret-not-exported', b'other-synthetic-secret-value'))
    with pytest.raises(RuntimeError, match='EXACT_TRANSFERRED_META_CREDENTIAL_RECEIPT_REQUIRED'): activate()
    assert switch.m.calls == [] and NEW not in switch.m.items


def test_meta_secret_directory_must_remain_exactly_private_before_create(switch):
    c.ENV_FILE.parent.chmod(0o755)
    with pytest.raises(RuntimeError, match='PROTECTED_DIRECTORY_REQUIRED'): activate()
    assert switch.m.calls == [] and NEW not in switch.m.items


def test_unknown_reserved_primary_is_not_overwritten_during_recovery(switch):
    fired = []
    def hook(stage, m):
        if stage == 'CANDIDATE_START_FAILED' and not fired:
            fired.append(True); stranger = original(); stranger['Id'] = 'c'*64; stranger['Name'] = '/t24-crm'
            m.items[NEW]['Name'] = '/'+a._names()[1]; m.items[stranger['Id']] = stranger
            raise RuntimeError('SYNTHETIC_UNKNOWN_ROLE')
    switch.m.hook = hook
    with pytest.raises(RuntimeError): activate()
    assert switch.m.inspect('t24-crm')['Id'] == 'c'*64
    assert not any(argv[:2] == ['docker', 'stop'] and argv[-1] == 'c'*64 for argv in switch.m.calls)


def test_running_known_candidate_is_contained_even_if_other_role_has_drifted(switch):
    fired = []
    def hook(stage, m):
        if stage == 'ready' and m.inspect(NEW)['State']['Running'] and not fired:
            fired.append(True); m.items[NEW]['Name'] = '/unexpected-role'
            raise RuntimeError('SYNTHETIC_ROLE_DRIFT')
    switch.m.hook = hook
    with pytest.raises(RuntimeError, match='KNOWN_CANDIDATE_CONTAINER_REQUIRED'): activate()
    assert switch.m.inspect(NEW)['State']['Running'] is False
    assert not (switch.root/'activated.json').exists()


def test_prestart_candidate_restart_is_rejected_before_original_stop(switch):
    def hook(stage, m):
        if stage == 'created': m.items[NEW]['RestartCount'] = 1
    switch.m.hook = hook
    with pytest.raises(RuntimeError, match='CANDIDATE_RESTARTED'): activate()
    assert switch.m.inspect(c.ORIGINAL_ID)['State']['Running']
    assert not any(argv[:2] == ['docker', 'stop'] and argv[-1] == c.ORIGINAL_ID for argv in switch.m.calls)


def test_configured_probe_has_only_public_parameters_and_blocks_provider_network(switch):
    code = a._configured_probe()
    assert c.APP_ID in code and c.CONFIG_ID in code and 'socket.socket.connect=blocked' in code
    assert 'synthetic-secret-not-exported' not in code and 'private-canary' not in code


@pytest.mark.parametrize('table', ['meta_business_connections', 'meta_business_oauth_states', 'meta_operations_credentials',
    'meta_operations_oauth_states', 'meta_operations_bindings', 'meta_operations_actions'])
def test_independent_new_read_and_ops_rows_survive_recovery_without_rotation_gate(switch, table):
    original_count = switch.sample['rows'][table]['count']; fired = []
    def hook(stage, m):
        if stage == 'ready' and m.inspect(NEW)['State']['Running'] and not fired:
            fired.append(True); switch.sample['rows'][table]['count'] += 1
            switch.sample['rows'][table]['rows_sha256'] = 'f'*64
            raise RuntimeError('SYNTHETIC_INDEPENDENT_NEW_ROW')
    switch.m.hook = hook
    with pytest.raises(RuntimeError, match='SYNTHETIC_INDEPENDENT_NEW_ROW'): activate()
    assert switch.sample['rows'][table]['count'] == original_count+1
    assert switch.m.inspect('t24-crm')['Id'] == c.ORIGINAL_ID
    assert switch.m.inspect(NEW)['State']['Running'] is False
    assert c.ENV_FILE.exists()


def test_without_exact_prepared_receipt_no_candidate_can_be_created(switch):
    with pytest.raises(RuntimeError, match='ACTUAL_PREPARED_ACTIVATION_REVIEW_REQUIRED'): a.activate(None)
    assert switch.m.calls == [] and NEW not in switch.m.items
    receipt = a.prepare()
    with pytest.raises(RuntimeError, match='PROTECTED_READ_DRIFT_OR_HASH_REJECTED'): a.activate('f'*64)
    assert switch.m.calls == [] and receipt['operations_execution_enabled'] is False


def test_secret_or_key_reuse_cannot_create_candidate(switch):
    existing = c.old_environment(original()['Config']['Env'])
    for name, value, code in [('APP_SECRET', existing['T24_META_APP_SECRET'], 'PUBLISHER_SECRET_MUST_DIFFER_FROM_READ_APP'),
                              ('TOKEN_KEY', existing['T24_META_TOKEN_KEY'], 'DEDICATED_NEW_OPS_KEY_REQUIRED')]:
        rows = [('T24_META_OPS_'+name+'='+value) if row.startswith('T24_META_OPS_'+name+'=') else row for row in meta_rows()]
        with pytest.raises(RuntimeError, match=code): a.clone_config(original(), rows, switch.m)
    assert switch.m.calls == [] and NEW not in switch.m.items


@pytest.mark.parametrize('leak', [False, True])
def test_actual_jpeg_callback_privacy_facade_and_log_leak_containment(switch, monkeypatch, tmp_path, leak):
    ops = load('ops_activation_privacy_release', '../meta-operations-20261101/release.py')
    switch.ctx.module = ops
    monkeypatch.setattr(a, '_privacy_probe', REAL_PRIVACY_PROBE)
    monkeypatch.setattr(r, 'META_CALLBACK', c.CALLBACK_PATH)
    monkeypatch.setattr(r, 'DELIVERY_PREFIX', ops.OPS_DELIVERY)
    monkeypatch.setattr(r, 'FRONTEND', c.FRONTEND)
    original_headers = r.callback_headers
    monkeypatch.setattr(r, 'callback_headers', lambda body:original_headers(body.replace(b'?meta_ops=failed', b'?meta=failed')))
    nginx = ('server {location = '+c.CALLBACK_PATH+' {access_log off; error_log /dev/null crit;}}').encode()
    switch.proof['active_nginx_sha256'] = c.H(nginx); switch.sample['active_nginx_sha256'] = c.H(nginx)
    switch.proof['content_security_policy_sha256'] = 'e'*64
    log = tmp_path/'synthetic-nginx.log'; log.write_bytes(b'old-log\n'); seen = []; markers = []
    def open_log(path):
        fd = os.open(path, os.O_RDONLY); os.lseek(fd, 0, os.SEEK_END); return fd, os.stat(path)
    monkeypatch.setattr(r, 'open_nginx_log', open_log); monkeypatch.setattr(r, 'delivery_log_paths', lambda active:[str(log)])
    monkeypatch.setattr(r.time, 'sleep', lambda delay:None)
    def output(argv):
        assert argv[:2] == ['docker', 'logs']; seen.append('log-scan')
        return markers[-1].encode() if leak else b'safe synthetic container output'
    monkeypatch.setattr(r, 'bounded_output', output)
    switch.m.BUSINESS = tmp_path/'not-opened-synthetic.db'
    switch.m.sql_snapshot = lambda path:{name:{**row, 'columns':['id'], 'schema':{}, 'indexes':{}} for name,row in switch.sample['rows'].items()}
    switch.ctx.workflow.pf.security_headers = lambda m:{'content_security_policy_sha256':'e'*64}
    run = switch.m.run
    def io(argv, code, *rest):
        if argv[:2] == ['nginx', '-T']: return nginx
        if argv[0] != 'curl': return run(argv, code, *rest)
        url = argv[-1]; seen.append(url)
        if url.endswith('/app-version.json'): return json.dumps({'version':c.FRONTEND}).encode()
        if url.endswith('/ready'): return b'{"status":"ready"}'
        callback = c.CALLBACK_PATH in url
        if not callback: assert url.startswith('https://t24-crm.com'+ops.OPS_DELIVERY) and url.endswith('.jpg')
        markers.append(url.split('state=',1)[1].split('&',1)[0] if callback else url.rsplit('/',1)[1][:-4])
        return ('HTTP/1.1 '+('303 See Other' if callback else '404 Not Found')+'\r\n'+
            ('Location: /media-ops?meta_ops=failed\r\n' if callback else '')+
            'Referrer-Policy: no-referrer\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n'+
            "Content-Security-Policy: default-src 'self'\r\nStrict-Transport-Security: max-age=31536000\r\n\r\n").encode()
    switch.m.run = io
    if leak:
        with pytest.raises(RuntimeError, match='SENTINEL_PATH_PRESENT_IN_CONTAINER_LOG'): activate()
        assert switch.m.inspect('t24-crm')['Id'] == c.ORIGINAL_ID
    else:
        result = activate(); report = result['loopback_public_and_callback_privacy_verification']
        assert report['meta_callback_privacy_headers_verified'] and report['delivery_prefix_logging_protected']
        assert report['meta_callback_invalid_state_no_database_write'] and report['noncapability_get_and_head_404_verified']
        assert seen.count('log-scan') == 2


