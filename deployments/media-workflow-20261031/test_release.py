"""Synthetic SQLite and in-memory Docker only; no server or provider access."""
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('workflow_author_release', HERE / 'release.py')
r = importlib.util.module_from_spec(spec); sys.modules[spec.name] = r; spec.loader.exec_module(r)
OLD, NEW, IMAGE = 'a' * 64, 'b' * 64, 'sha256:' + 'e' * 64


def sql_snapshot(path):
    con = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True); result = {}
    try:
        for name, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            info = con.execute('PRAGMA table_info("' + name + '")').fetchall(); columns = [row[1] for row in info]
            rows = sorted(json.dumps(list(row)) for row in con.execute('SELECT * FROM "' + name + '"'))
            indexes = {row[1]: [row[2], row[3], row[4], [item[2] for item in con.execute('PRAGMA index_info("' + row[1] + '")')]] for row in con.execute('PRAGMA index_list("' + name + '")')}
            result[name] = {'columns': columns, 'schema': {row[1]: list(row[2:]) for row in info}, 'indexes': indexes, 'count': len(rows), 'rows_sha256': r.H('\n'.join(rows).encode())}
        return result
    finally: con.close()


def create_db(path, sequence):
    with sqlite3.connect(path) as con:
        con.executescript("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);CREATE TABLE media_operation_tasks(id INTEGER PRIMARY KEY);INSERT INTO media_operation_tasks VALUES(1);CREATE TABLE permission_canary(id INTEGER PRIMARY KEY,scope TEXT);INSERT INTO permission_canary VALUES(1,'OWNER_ONLY');PRAGMA user_version=17;PRAGMA application_id=42;")
        con.execute('INSERT INTO alembic_version VALUES(?)', (r.OLD_REVISION,))
        if sequence: con.executescript("CREATE TABLE finance_canary(id INTEGER PRIMARY KEY AUTOINCREMENT,amount INTEGER UNIQUE);INSERT INTO finance_canary(id,amount) VALUES(42,198);")


def migration(path):
    return r.migration_script().replace("'/app/backend/'+path", repr(str(REPO / 'app/backend') + '/') + '+path').replace('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true', 'sqlite:///file:' + str(path) + '?mode=rw&uri=true')


@pytest.mark.parametrize('sequence', [False, True])
def test_actual_migration_one_empty_table_preserves_original_rows_objects_pragmas_counters(tmp_path, sequence):
    path = tmp_path / 'synthetic.db'; create_db(path, sequence); before = sql_snapshot(path); old_objects = r.objects(path)
    with sqlite3.connect(path) as con:
        pragma = [con.execute('PRAGMA ' + key).fetchone() for key in ('user_version', 'application_id')]
        counters = con.execute('SELECT name,seq FROM sqlite_sequence').fetchall() if sequence else []
    exec(compile(migration(path), '<synthetic-migration>', 'exec'), {})
    after = sql_snapshot(path); r.compare_original(before, after); r.additive_objects(old_objects, r.objects(path))
    assert set(after) - set(before) == r.NEW_TABLES and all(after[n]['count'] == 0 for n in r.NEW_TABLES)
    dummy = object.__new__(r.Release); dummy.m = SimpleNamespace(schema_signature=lambda path, revision: revision)
    assert dummy.new_schema(path) == r.NEW_REVISION
    with sqlite3.connect(path) as con:
        assert [con.execute('PRAGMA ' + key).fetchone() for key in ('user_version', 'application_id')] == pragma
        assert (con.execute('SELECT name,seq FROM sqlite_sequence').fetchall() if sequence else []) == counters


@pytest.mark.parametrize('kind', ['rows', 'columns', 'indexes', 'extra_table', 'seed'])
def test_original_or_new_scope_drift_rejected(tmp_path, kind):
    path = tmp_path / 'synthetic.db'; create_db(path, True); before = sql_snapshot(path); exec(migration(path), {})
    with sqlite3.connect(path) as con:
        if kind == 'rows': con.execute("UPDATE permission_canary SET scope='STAFF'")
        if kind == 'columns': con.execute('ALTER TABLE permission_canary ADD COLUMN unexpected TEXT')
        if kind == 'indexes': con.execute('CREATE INDEX unexpected ON permission_canary(scope)')
        if kind == 'extra_table': con.execute('CREATE TABLE unexpected(id INTEGER)')
        if kind == 'seed': con.execute('INSERT INTO media_publication_image_policies(owner_id,enabled,updated_at) VALUES(1,0,?)', ('2026-10-31',))
    with pytest.raises(RuntimeError): r.compare_original(before, sql_snapshot(path))


def test_forward_recovery_can_preserve_independently_created_rows_without_restoring(tmp_path):
    path = tmp_path / 'synthetic.db'; create_db(path, True); before = sql_snapshot(path); exec(migration(path), {})
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO permission_canary VALUES(2,'INDEPENDENT')")
        con.execute('INSERT INTO media_publication_image_policies(owner_id,enabled,updated_at) VALUES(1,0,?)', ('2026-10-31',))
    r.compare_original(before, sql_snapshot(path), rows=False, empty=False)
    assert sql_snapshot(path)['permission_canary']['count'] == 2


def original():
    return {'Id': OLD, 'Image': 'sha256:' + 'd' * 64, 'Name': '/t24-crm', 'Config': {'Image': 'old', 'Hostname': 'old', 'Env': ['PRESERVED=synthetic', 'T24_GBP_SCHEDULER_ENABLED=true', 'T24_GBP_SCHEDULER_ACTIVATION_FROM=' + r.ACTIVATION_FROM], 'Labels': {'prior': 'same'}, 'Cmd': ['serve']}, 'HostConfig': {'AutoRemove': False, 'OomKillDisable': None, 'NetworkMode': 'host', 'Privileged': False}, 'Mounts': [{'Source': '/synthetic/data', 'Destination': '/app/backend/data', 'RW': True}], 'NetworkSettings': {'Networks': {}}, 'State': {'Running': True, 'Status': 'running', 'StartedAt': 'old-start'}, 'RestartCount': 0}


def runtime(info): return {'id': info['Id'], 'image': info['Image'], 'started': info['State']['StartedAt'], 'restart': info['RestartCount'], 'config': r.digest({key: info[key] for key in ('Config', 'HostConfig', 'Mounts', 'NetworkSettings')})}


def sample_rows():
    return {'alembic_version': {'columns': ['version_num'], 'schema': {'version_num': ['TEXT', 0, None, 1]}, 'indexes': {}, 'count': 1, 'rows_sha256': r.H(json.dumps([r.OLD_REVISION]).encode())}, 'finance_canary': {'columns': ['id'], 'schema': {'id': ['INTEGER', 0, None, 1]}, 'indexes': {}, 'count': 1, 'rows_sha256': 'unchanged'}}


class Docker:
    runtime = staticmethod(runtime)
    def __init__(self, nginx): self.items = {OLD: original()}; self.NGINX = nginx; self.calls = []; self.fault = None; self.head = r.OLD_REVISION; self.rows = sample_rows(); self.sources = {OLD: 'old'}
    def inspect_optional(self, key):
        found = next((row for row in self.items.values() if key == row['Id'] or '/' + key == row['Name']), None); return copy.deepcopy(found) if found else None
    def inspect(self, key):
        row = self.inspect_optional(key); r.need(row is not None, 'SYNTHETIC_CONTAINER_MISSING'); return row
    def retained(self): return self
    def expected_labels(self, old): return {**old['Config']['Labels'], 't24.release.scope': r.SCOPE, 't24.release.source': r.SOURCE_SHA}
    def clone_config(self, image, old):
        config = copy.deepcopy(old['Config']); config.update(Image=image, Hostname='', Labels=self.expected_labels(old)); config['HostConfig'] = copy.deepcopy(old['HostConfig']); return config
    def docker_request(self, method, path, config):
        assert method == 'POST'; row = copy.deepcopy(original()); row.update(Id=NEW, Image=IMAGE, Name='/' + path.split('=', 1)[1]); row['Config'] = {k: copy.deepcopy(v) for k, v in config.items() if k != 'HostConfig'}; row['HostConfig']['OomKillDisable'] = False; row['State'].update(Running=False, Status='created', StartedAt='0001-01-01T00:00:00Z'); self.items[NEW] = row; self.sources[NEW] = 'new'; return 201, json.dumps({'Id': NEW}).encode()
    def run(self, args, code, *_):
        self.calls.append(args)
        if self.fault: self.fault(args, code)
        if args[0] == 'curl': return json.dumps({'version': r.FRONTEND} if args[-1].endswith('app-version.json') else {'status': 'ready'}).encode()
        assert args[0] == 'docker'; op = args[1]
        if op == 'stop': self.items[args[-1]]['State'].update(Running=False, Status='exited')
        elif op == 'rename':
            assert not self.inspect_optional(args[3]); self.items[args[2]]['Name'] = '/' + args[3]
        elif op == 'start': self.items[args[2]]['State'].update(Running=True, Status='running', StartedAt='new-start')
        elif op == 'exec': return b'EXACT_EXISTING_ON_WORKER_CUTOFF_NO_NETWORK'
        else: pytest.fail('Unexpected command ' + repr(args[:2]))
        return b''
    def read(self, path, sha=None):
        body = path.read_bytes(); r.need(sha is None or r.H(body) == sha, 'SYNTHETIC_FILE_HASH_DRIFT'); return body
    def write(self, path, value):
        with path.open('xb') as stream: stream.write(value if isinstance(value, bytes) else r.encoded(value))
        return r.H(path.read_bytes())
    def ready(self, key): r.need(self.inspect(key)['State']['Running'] is True, 'SYNTHETIC_NOT_READY')
    def verify_secret_mount(self, info): r.need(info['Mounts'] == original()['Mounts'], 'SECRET_MOUNT_DRIFT')
    def verify_production_worker_enabled(self, _): pass
    def verify_public(self, *_): return 'static'
    def next_nginx(self, body): return body.replace(b'/public/old', b'/public/new')
    def replace_nginx(self, before, after): assert self.NGINX.read_bytes() == before; self.NGINX.write_bytes(after)
    def reload_nginx(self):
        self.calls.append(['reload-nginx'])
        if self.fault: self.fault(['reload-nginx'], 'RELOAD')


@pytest.fixture
def publisher(tmp_path):
    release = tmp_path / 'release'; release.mkdir(); nginx = tmp_path / 'nginx'; nginx.write_bytes(b'root /public/old; # callback security retained')
    w = object.__new__(r.Release); w.args = SimpleNamespace(release=release, review_sha256='f' * 64, preflight_sha256='c' * 64); w.m = Docker(nginx); w.m.BUSINESS = tmp_path / 'synthetic.db'; w.public = Path('/public/new'); w.old_name = 'reserved-old'; w.candidate_name = 'reserved-new'; w.manifest = {}
    w.proof = {'rows': r.evidence(w.m.rows), 'crm': runtime(original()), 'nginx_sha256': r.H(nginx.read_bytes())}; w.before = {'service': 'old'}; w.expected = {'service': 'new'}; w.metadata = 'same'
    w.receipt = {'candidate_image': IMAGE, 'schema_after_sha256': 'new-schema', 'nginx_next_sha256': r.H(w.m.next_nginx(nginx.read_bytes())), 'public_inventory_sha256': 'static', 'candidate_inventory_sha256': 'b' * 64}
    w.reviewed = lambda: (copy.deepcopy(w.receipt), original(), w.before, w.expected); w.current = lambda: (original(), w.before); w.rows = lambda path=None: copy.deepcopy(w.m.rows); w.revision = lambda: w.m.head
    w.new_schema = lambda *args, **kwargs: 'new-schema'
    w.delivery_sentinel = lambda candidate_id: {'delivery_prefix_logging_protected':True,'noncapability_get_and_head_404_verified':True}
    def protections(**kwargs): r.need(w.metadata == 'same', 'SYNTHETIC_METADATA_DRIFT')
    w.protections = protections; w.source_boundary = lambda info, expected: r.need(w.m.sources[info['Id']] == ('old' if expected == w.before else 'new'), 'SYNTHETIC_SOURCE_DRIFT')
    def google(info):
        values = dict(row.split('=', 1) for row in info['Config']['Env']); r.need(values['T24_GBP_SCHEDULER_ENABLED'] == 'true' and values['T24_GBP_SCHEDULER_ACTIVATION_FROM'] == r.ACTIVATION_FROM, 'SYNTHETIC_ON_CUTOFF_DRIFT')
    w.pf = SimpleNamespace(google_environment=google, ACTIVATION_FROM=r.ACTIVATION_FROM); w.helper = SimpleNamespace(validation_window=lambda _: None)
    def migrate(*args, **kwargs):
        w.m.head = r.NEW_REVISION; w.m.rows['alembic_version']['rows_sha256'] = r.H(json.dumps([r.NEW_REVISION]).encode()); w.m.rows.update({n: {'columns': ['synthetic'], 'schema': {}, 'indexes': {}, 'count': 0, 'rows_sha256': r.H(b'')} for n in r.NEW_TABLES})
    w.run_migration = migrate; w.settle_migration = lambda *args, **kwargs: {'Image': IMAGE, 'State': {'Running': False, 'ExitCode': 0}} if w.m.head == r.NEW_REVISION else None
    return w


def test_complete_additive_switch_preserves_on_environment_and_no_provider_actions(publisher):
    w = publisher; result = w.activate()
    assert result['stage'] == 'MEDIA_WORKFLOW_DEPLOYED_VERIFIED' and result['six_new_workflow_tables_empty'] and result['scheduler_enabled']
    assert w.m.inspect('t24-crm')['Id'] == NEW and w.m.inspect(OLD)['State']['Running'] is False
    assert w.m.inspect(NEW)['Config']['Env'] == original()['Config']['Env']
    assert not any(call[:2] in (['docker', 'rm'], ['docker', 'run']) for call in w.m.calls)


def test_exact_candidate_id_is_durable_before_first_original_stop(publisher):
    w = publisher
    def check(args, code):
        if args[:2] == ['docker', 'stop']: assert json.loads((w.args.release / 'candidate-created.json').read_bytes())['candidate_id'] == NEW
    w.m.fault = check; w.activate()


@pytest.mark.parametrize('op', ['rename', 'start', 'reload-nginx', 'curl'])
def test_post_migration_failures_recover_forward_only_same_new_candidate(publisher, op):
    w = publisher; fired = [False]
    def fail(args, code):
        match = args[0] == op if op in {'reload-nginx', 'curl'} else args[:2] == ['docker', op]
        if match and not fired[0]: fired[0] = True; raise RuntimeError('SYNTHETIC_SWITCH_FAILED')
    w.m.fault = fail
    with pytest.raises(RuntimeError, match='SYNTHETIC_SWITCH_FAILED'): w.activate()
    assert w.m.head == r.NEW_REVISION and w.m.inspect('t24-crm')['Id'] == NEW and w.m.inspect(OLD)['State']['Running'] is False
    assert not any(call[:3] == ['docker', 'start', OLD] for call in w.m.calls)


def test_pre_migration_failure_can_resume_old_only_on_old_schema(publisher):
    w = publisher
    w.run_migration = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_MIGRATION_FAILED'))
    with pytest.raises(RuntimeError, match='SYNTHETIC_MIGRATION_FAILED'): w.activate()
    assert w.m.head == r.OLD_REVISION and w.m.inspect('t24-crm')['Id'] == OLD and not w.m.inspect(NEW)['State']['Running']


def test_late_metadata_drift_contains_new_candidate_before_refusing_recovery(publisher):
    w = publisher
    def fail(args, code):
        if args[:3] == ['docker', 'start', NEW]: w.metadata = 'changed'
    w.m.fault = fail
    with pytest.raises(RuntimeError, match='SYNTHETIC_METADATA_DRIFT'): w.activate()
    assert w.m.head == r.NEW_REVISION and not w.m.inspect(NEW)['State']['Running'] and not w.m.inspect(OLD)['State']['Running']


def test_identity_record_failure_never_stops_original_or_guesses_orphan(publisher):
    w = publisher; write = w.m.write
    def fail(path, value):
        if path.name == 'candidate-created.json': raise OSError('synthetic full disk')
        return write(path, value)
    w.m.write = fail
    with pytest.raises(OSError): w.activate()
    assert w.m.inspect('t24-crm')['Id'] == OLD and w.m.inspect(OLD)['State']['Running']
    assert not any(call[:2] in (['docker', 'start'], ['docker', 'stop'], ['docker', 'rename']) for call in w.m.calls)


@pytest.mark.parametrize('field', ['on', 'cutoff', 'mount', 'privileged', 'oom_true', 'oom_zero', 'oom_missing'])
def test_configuration_comparison_never_disables_or_changes_existing_worker(field):
    old = original(); candidate = copy.deepcopy(old); m = SimpleNamespace(runtime=runtime, expected_labels=lambda _: old['Config']['Labels'])
    if field == 'on': candidate['Config']['Env'][1] = 'T24_GBP_SCHEDULER_ENABLED=false'
    if field == 'cutoff': candidate['Config']['Env'][2] = 'T24_GBP_SCHEDULER_ACTIVATION_FROM=2026-11-01T00:00:00Z'
    if field == 'mount': candidate['Mounts'][0]['RW'] = False
    if field == 'privileged': candidate['HostConfig']['Privileged'] = True
    if field == 'oom_true': candidate['HostConfig']['OomKillDisable'] = True
    if field == 'oom_zero': candidate['HostConfig']['OomKillDisable'] = 0
    if field == 'oom_missing': del candidate['HostConfig']['OomKillDisable']
    with pytest.raises(RuntimeError): r.compare(candidate, old, m)


def test_only_reviewed_none_to_false_oom_default_equivalence_without_mutation():
    old = original(); candidate = copy.deepcopy(old); candidate['HostConfig']['OomKillDisable'] = False; before = copy.deepcopy((old, candidate))
    r.compare(candidate, old, SimpleNamespace(runtime=runtime, expected_labels=lambda _: old['Config']['Labels'])); assert (old, candidate) == before


def test_zero_source_pin_rejects_constructor_before_any_helper_read(monkeypatch):
    monkeypatch.setattr(r, 'SOURCE_SHA', '0' * 40)
    monkeypatch.setattr(r, 'protected_read', lambda *args: pytest.fail('read before actual pins'))
    with pytest.raises(RuntimeError, match='ACTUAL_REVIEWED_SOURCE_FRONTEND_AND_FREEZE_REQUIRED'): r.Release(SimpleNamespace())


def isolated_prepare(w, tmp_path, *, ignored_startup_insert=False):
    """Real copy/migration/metadata seam, actual retained offline env builder."""
    modules = []
    for label, path in [('base', HERE.parent / 'media-ops-management-20261031/release.py'), ('metadata', HERE.parent / 'media-ops-review-refresh-retry-20261031/preflight.py')]:
        spec = importlib.util.spec_from_file_location('publication_' + label + '_synthetic', path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules.append(module)
    w.base, metadata = modules
    source = tmp_path / 'production-synthetic.db'; create_db(source, True); w.m.BUSINESS = source
    previous_metadata = metadata.db_metadata(source)
    with sqlite3.connect(source) as con: con.execute('INSERT OR IGNORE INTO finance_canary(amount) VALUES(198)')
    assert metadata.db_metadata(source)['sequence_values']['finance_canary'] > previous_metadata['sequence_values']['finance_canary']
    w.m.sql_snapshot = sql_snapshot; w.rows = lambda path=None: r.snapshot(w.m, path or source)
    w.m.schema_signature = lambda path, revision: r.digest(sorted((list(key), value) for key, value in r.objects(path).items()))
    w.metadata = lambda path: metadata.db_metadata(path)
    w.proof = {'rows': r.evidence(w.rows()), 'database_metadata': previous_metadata, 'schema_sha256': w.m.schema_signature(source, r.OLD_REVISION)}
    w.new_schema = lambda path, **kwargs: r.Release.new_schema(w, path, **kwargs)
    w.args.manifest_sha256 = '4' * 64; w.args.payload_sha256 = '5' * 64
    w.manifest = {'backend_after': w.expected}; w.offline_name = 'synthetic-publication-offline'; w.image = lambda: IMAGE
    def backup(left, right):
        with sqlite3.connect('file:' + str(left) + '?mode=ro', uri=True) as src, sqlite3.connect(right) as dst: src.backup(dst)
    w.m.backup = backup; w.m.extract = lambda *args: None
    w.run_migration = lambda data, image, **kwargs: exec(compile(migration(data / 'crm_prod.db'), '<synthetic-copy-migration>', 'exec'), {})
    w.helper = SimpleNamespace(docker_timestamp_probe=metadata.docker_timestamp_probe)
    w.m.inventory = lambda key: w.expected if key == w.offline_name else w.before
    w.m.stage_public = lambda *args: (w.public, 'static')
    for name in ('release.py', 'preflight.py', 'manifest.json', 'payload.tar.gz'): (w.args.release / name).write_bytes(b'synthetic-public-tool')
    run = w.m.run; injected = [False]
    def offline_run(args, code, *timeout):
        if args[:2] == ['docker', 'run']:
            assert '--network=none' in args and '--read-only' in args and '--env-file' not in args
            values = [args[index + 1] for index, arg in enumerate(args) if arg == '-e']
            assert 'T24_GBP_SCHEDULER_ENABLED=false' in values and 'T24_GBP_SCHEDULER_ACTIVATION_FROM=' in values
            row = original(); row.update(Id='7' * 64, Name='/' + w.offline_name); row['Config']['Env'] = values; row['HostConfig']['NetworkMode'] = 'none'; row['Mounts'] = []
            w.m.items[row['Id']] = row; return b''
        if args[:3] == ['docker', 'exec', w.offline_name]:
            if ignored_startup_insert and not injected[0]:
                injected[0] = True
                with sqlite3.connect(w.args.release / 'probe-data/crm_prod.db') as con: con.execute('INSERT OR IGNORE INTO finance_canary(amount) VALUES(198)')
            return b'EXACT_PYTHON310 EXACT_WORKFLOW_MEDIA_GOOGLE_ROUTES EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK'
        if args[:2] == ['docker', 'stop'] and args[-1] == w.offline_name:
            w.m.items['7' * 64]['State']['Running'] = False; return b''
        return run(args, code, *timeout)
    w.m.run = offline_run
    return source, metadata


def test_actual_prepare_copy_migration_and_startup_preserve_source_and_own_metadata(publisher, tmp_path):
    w = publisher; source, metadata = isolated_prepare(w, tmp_path); before = source.read_bytes()
    result = w.prepare()
    assert result['stage'] == 'MEDIA_WORKFLOW_PREPARED_OFFLINE_VERIFIED' and source.read_bytes() == before
    assert result['offline_new_table_empty'] and result['offline_own_metadata_exact'] and result['scheduler_on_and_cutoff_preserved']
    assert metadata.db_metadata(source) == metadata.db_metadata(w.args.release / 'probe-data/crm_prod.db')


def test_actual_prepare_rejects_ignored_insert_counter_during_own_startup(publisher, tmp_path):
    w = publisher; source, metadata = isolated_prepare(w, tmp_path, ignored_startup_insert=True); before = source.read_bytes()
    with pytest.raises(RuntimeError, match='OFFLINE_STARTUP_CHANGED_DATABASE'): w.prepare()
    assert source.read_bytes() == before and not (w.args.release / 'prepared.json').exists()


NGINX = b'''server {
    listen 443 ssl;
    server_name t24-crm.com;
    root /public/old;
    add_header Strict-Transport-Security "max-age=31536000" always;
    # Existing callback must remain byte-identical.
    location = /api/v1/google-business/oauth/callback {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_hide_header Referrer-Policy;
        add_header Referrer-Policy no-referrer always;
        access_log off;
        error_log /dev/null crit;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering off;
    }
    location / { try_files $uri /index.html; }
}
'''


def test_delivery_nginx_is_one_exact_log_suppressed_prefix_and_no_other_byte_changes():
    output, added = r.image_delivery_nginx(NGINX)
    assert output.replace(added, b'', 1) == NGINX
    assert added.count(b'location ^~ /api/v1/media-publication-images/delivery/') == 1
    assert b'access_log off;' in added and b'error_log /dev/null crit;' in added
    assert b'proxy_pass http://127.0.0.1:8000;' in added
    assert b'add_header' not in added  # retain server security-header inheritance
    assert NGINX[NGINX.index(b'    location ='):NGINX.index(b'    location /api/')] in output
    with pytest.raises(RuntimeError): r.image_delivery_nginx(output)


@pytest.mark.parametrize('before,after', [(b'listen 443 ssl;', b'listen 80;'),
    (b'access_log off;', b'access_log /var/log/nginx/access.log;'),
    (b'error_log /dev/null crit;', b'error_log /var/log/nginx/error.log;'),
    (b'location /api/', b'location /unrelated/'),
    (b'proxy_pass http://127.0.0.1:8000;', b'proxy_pass https://external.example/;'),
    (b'proxy_buffering off;', b'proxy_buffering maybe;'),
    (b'proxy_set_header X-Forwarded-Proto $scheme;', b'proxy_set_header X-Unsafe $token;'),
    (b'proxy_read_timeout 120s;', b'proxy_read_timeout anything;'),
    (b'proxy_buffering off;', b'proxy_buffering off; access_log /tmp/leak;'),
    (b'proxy_buffering off;', b'if ($args) { return 403; }')])
def test_delivery_nginx_refuses_unreviewed_upstream_or_log_structure(before, after):
    with pytest.raises(RuntimeError): r.image_delivery_nginx(NGINX.replace(before, after))


def test_delivery_boundary_restores_added_prefix_and_root_to_exact_active_configuration(tmp_path):
    original = tmp_path / 'nginx'; original.write_bytes(NGINX)
    release = tmp_path / 'release'; release.mkdir(); (release / 'nginx-before.conf').write_bytes(NGINX)
    next_body, added = r.image_delivery_nginx(NGINX.replace(b'/public/old', b'/public/new'))
    original.write_bytes(next_body)
    w = object.__new__(r.Release); w.public = Path('/public/new'); w.args = SimpleNamespace(release=release)
    w.proof = {'public_root':'/public/old', 'nginx_sha256':r.H(NGINX), 'active_nginx_config_sha256':r.H(b'# active\n'+NGINX)}
    w.m = SimpleNamespace(NGINX=original, read=lambda path,sha:path.read_bytes(), run=lambda *_:b'# active\n'+original.read_bytes())
    w.nginx(updated=True)
    original.write_bytes(next_body.replace(b'try_files $uri /index.html;', b'return 200;'))
    with pytest.raises(RuntimeError): w.nginx(updated=True)


def test_both_migrations_roll_back_as_one_transaction_if_second_step_fails(tmp_path):
    path = tmp_path / 'synthetic.db'; create_db(path, True); before = sql_snapshot(path); old_objects = r.objects(path)
    code = migration(path).replace('for path,revision,down in migrations:', "for path,revision,down in migrations:\n  if down=='fbc6b8c9d025':raise RuntimeError('SYNTHETIC_SECOND_MIGRATION_FAILURE')")
    with pytest.raises(RuntimeError, match='SYNTHETIC_SECOND_MIGRATION_FAILURE'): exec(code, {})
    assert sql_snapshot(path) == before and r.objects(path) == old_objects


def test_new_table_shape_rejects_wrong_foreign_keys_or_new_trigger(tmp_path):
    path = tmp_path / 'synthetic.db'; create_db(path, False); before = r.objects(path); exec(migration(path), {})
    with sqlite3.connect(path) as con: con.execute('CREATE TRIGGER unexpected AFTER INSERT ON media_content_plans BEGIN SELECT 1; END;')
    with pytest.raises(RuntimeError): r.additive_objects(before, r.objects(path))
    w = object.__new__(r.Release); w.m=SimpleNamespace(schema_signature=lambda *_:'synthetic')
    with pytest.raises(RuntimeError): w.new_schema(path)


@pytest.mark.parametrize('change', ['public_openapi','missing_head','duplicate','wrong_module'])
def test_exact_route_probe_checks_hidden_get_head_and_router_provenance(monkeypatch, change):
    import fastapi.routing
    w=object.__new__(r.Release); w.base=SimpleNamespace(GBP_ROUTES=set(), MEDIA_ROUTES=set())
    expected = {('/api/v1/google-business/bindings/{binding_id}/review','GET'):'routers.google_business'}
    expected.update({pair:'routers.media_publication_images' for pair in r.IMAGE_ROUTES})
    expected.update({pair:'routers.media_planning' for pair in r.PLANNING_ROUTES})
    def routes():
        return [SimpleNamespace(path=p,methods={m},endpoint=SimpleNamespace(__module__=module),include_in_schema='/delivery/' not in p) for (p,m),module in expected.items()]
    registered=routes(); paths={}
    for (p,m),module in expected.items():
        if '/delivery/' not in p: paths.setdefault(p,{})[m.lower()]={}
    monkeypatch.setitem(sys.modules,'main',SimpleNamespace(app=SimpleNamespace(routes=registered,openapi=lambda:{'paths':paths})))
    monkeypatch.setattr(fastapi.routing,'iter_route_contexts',lambda source:source,raising=False)
    exec(w.route_probe(), {})
    if change=='public_openapi': paths['/api/v1/media-publication-images/delivery/{token}.png']={'get':{}}
    elif change=='missing_head': registered[:]=[x for x in registered if not (x.path.endswith('/delivery/{token}.png') and x.methods=={'HEAD'})]
    elif change=='duplicate': registered.append(registered[-1])
    else: registered[-1].endpoint.__module__='routers.unreviewed'
    with pytest.raises(AssertionError): exec(w.route_probe(), {})


SENTINEL_HEADERS = b'HTTP/1.1 404 Not Found\r\nCache-Control: private, no-store\r\nReferrer-Policy: no-referrer\r\nX-Content-Type-Options: nosniff\r\nStrict-Transport-Security: max-age=31536000\r\nContent-Security-Policy: default-src self\r\n\r\n'


@pytest.fixture
def sentinel(tmp_path, monkeypatch):
    active = b'access_log /var/log/nginx/access.log;\nerror_log /var/log/nginx/error.log;\nerror_log /var/log/nginx/t24-private-error.log;\n'+r.image_delivery_nginx(NGINX)[0]
    mapping={raw:tmp_path/str(index) for index,raw in enumerate(r.NGINX_LOG_METADATA)}
    for path in mapping.values():path.write_bytes(b'old-private-record-not-read\n')
    original_stat=r.os.stat
    monkeypatch.setattr(r.os,'stat',lambda path,*args,**kwargs:original_stat(mapping.get(str(path),path),*args,**kwargs))
    def open_log(raw):
        fd=r.os.open(mapping[raw],r.os.O_RDONLY); info=r.os.fstat(fd);r.os.lseek(fd,info.st_size,r.os.SEEK_SET);return fd,info
    monkeypatch.setattr(r,'open_nginx_log',open_log)
    monkeypatch.setattr(r.time,'sleep',lambda *_:None)
    monkeypatch.setattr(r.secrets,'token_hex',lambda *_:'e'*32)
    requests=[]; output=[b'clean redacted output\n']; checked=[]
    def bounded(argv,**kwargs):checked.append(argv);return output[0]
    monkeypatch.setattr(r,'bounded_output',bounded)
    def run(argv,*args):
        if argv[:2]==['nginx','-T']:return active
        assert argv[0]=='curl';requests.append(argv);return SENTINEL_HEADERS
    w=object.__new__(r.Release);w.m=SimpleNamespace(run=run,inspect=lambda name:{'Id':NEW,'State':{'Running':True}})
    w.nginx=lambda **kwargs:r.H(active)
    return SimpleNamespace(w=w,mapping=mapping,requests=requests,output=output,checked=checked,active=active)


def test_actual_sentinel_scans_only_appended_bytes_and_exact_candidate_with_bounded_full_since(sentinel):
    s=sentinel; result=s.w.delivery_sentinel(NEW)
    assert result['delivery_prefix_logging_protected'] and result['noncapability_get_and_head_404_verified']
    assert len(s.requests)==2 and '--head' not in s.requests[0] and '--head' in s.requests[1]
    token=s.requests[0][-1].split('/delivery/')[1][:-4]
    assert len(token)!=43 and token.startswith('t24_noncapability_probe_')
    assert all('--resolve' in cmd and 't24-crm.com:443:127.0.0.1' in cmd and '?' not in cmd[-1] for cmd in s.requests)
    assert s.checked[0][:3]==['docker','logs','--since'] and s.checked[0][-1]==NEW and '--tail' not in s.checked[0]
    assert 'old-private-record-not-read' not in json.dumps(result) and token not in json.dumps(result)
    assert result['sentinel_created_image_or_lease'] is False and result['sentinel_google_or_provider_request'] is False


@pytest.mark.parametrize('sink',['nginx','container'])
def test_sentinel_marker_in_any_observed_output_rejects_without_exporting_logs(sentinel,sink):
    s=sentinel; token=b't24_noncapability_probe_'+b'e'*32
    if sink=='container':s.output[0]=b'private-prefix '+token+b' suffix'
    else:
        run=s.w.m.run
        def leak(argv,*args):
            if argv[0]=='curl':
                with next(iter(s.mapping.values())).open('ab') as stream:stream.write(b'private-prefix '+token+b' suffix')
            return run(argv,*args)
        s.w.m.run=leak
    with pytest.raises(RuntimeError,match='SENTINEL_PATH_PRESENT_IN_') as caught:s.w.delivery_sentinel(NEW)
    assert 'private-prefix' not in str(caught.value) and token.decode() not in str(caught.value)


def test_sentinel_log_rotation_is_not_silently_ignored(sentinel):
    s=sentinel; run=s.w.m.run;changed=[False]
    def rotate(argv,*args):
        if argv[0]=='curl' and not changed[0]:
            changed[0]=True;path=next(iter(s.mapping.values()));path.rename(path.with_suffix('.rotated'));path.write_bytes(b'new')
        return run(argv,*args)
    s.w.m.run=rotate
    with pytest.raises(RuntimeError,match='SENTINEL_LOG_ROTATION_OR_METADATA_DRIFT'):s.w.delivery_sentinel(NEW)


@pytest.mark.parametrize('before,after',[(b'404 Not Found',b'200 OK'),(b'no-referrer',b'strict-origin-when-cross-origin'),
    (b'nosniff',b'bad'),(b'no-store',b'public'),(b'no-store',b'not-no-store'),(b'\r\nReferrer-Policy: no-referrer',b'\r\nReferrer-Policy: no-referrer\r\nReferrer-Policy: no-referrer')])
def test_sentinel_rejects_wrong_status_or_privacy_headers(before,after):
    with pytest.raises(RuntimeError):r.sentinel_headers(SENTINEL_HEADERS.replace(before,after))


def test_log_scanner_is_bounded_during_actual_pipe_read():
    assert r.bounded_output([sys.executable,'-c','print("clean")'],maximum=32)==b'clean\n'
    with pytest.raises(RuntimeError,match='BOUNDED_LOG_OUTPUT_REQUIRED'):
        r.bounded_output([sys.executable,'-c','print("x"*65536)'],maximum=64)


def test_permanent_log_canary_failure_contains_new_candidate_without_restarting_old(publisher):
    w=publisher;w.delivery_sentinel=lambda candidate_id:(_ for _ in ()).throw(RuntimeError('SYNTHETIC_SENTINEL_REJECTED'))
    with pytest.raises(RuntimeError,match='SYNTHETIC_SENTINEL_REJECTED'):w.activate()
    assert w.m.head==r.NEW_REVISION and w.m.inspect(NEW)['State']['Running'] is False and w.m.inspect(OLD)['State']['Running'] is False
    assert not (w.args.release/'deployed.json').exists()
    assert not any(call[:3]==['docker','start',OLD] for call in w.m.calls)
