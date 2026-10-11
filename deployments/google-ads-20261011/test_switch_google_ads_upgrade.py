"""Offline synthetic helper and rollback tests; no production I/O or secrets."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).with_name('switch_google_ads_upgrade.py')
spec = importlib.util.spec_from_file_location('gmail_upgrade_switch', MODULE_PATH)
switch = importlib.util.module_from_spec(spec)
# Import must be inert: an accidental top-level server operation fails the suite.
with mock.patch('subprocess.run', side_effect=AssertionError('external command during import')), \
     mock.patch('sqlite3.connect', side_effect=AssertionError('database during import')), \
     mock.patch('urllib.request.urlopen', side_effect=AssertionError('network during import')):
    spec.loader.exec_module(switch)

IMAGE = 'sha256:' + '2' * 64
IDS = {'api': '3' * 64, 'worker': '4' * 64}
ATTEMPT = '5' * 32


def old_environment():
    return {
        'PRIVATE_WORKSPACE_OWNER_IDS': '4',
        'PRIVATE_WORKSPACE_PUBLIC_URL': 'https://t24-crm.com',
        'PRIVATE_WORKSPACE_DATABASE_URL': 'sqlite+aiosqlite:////private-data/workspace.db',
        'DATABASE_URL': 'sqlite:///./data/crm_prod.db', 'DATABASE_SCHEMA_MODE': 'verify_only',
        'ENFORCE_EMPLOYEE_STATUS': 'true', 'ENFORCE_EMPLOYEE_SESSIONS': 'true',
        'JWT_SECRET_KEY': 'synthetic-jwt-' + 'x' * 32,
        'PRIVATE_WORKSPACE_ENCRYPTION_KEY': 'synthetic-key-' + 'y' * 32,
    }


def encode_env(values):
    return ''.join(name + '=' + value + '\n' for name, value in values.items()).encode()


def staged_info(role='api'):
    config = {
        'Labels': {'t24.private.source.sha': switch.SOURCE, 't24.private.role': role,
                   't24.google_ads.upgrade.attempt': ATTEMPT},
        'Env': ['SYNTHETIC=value'],
        'Entrypoint': ['uvicorn' if role == 'api' else 'python'],
        'Cmd': ['services.private_workspace_app:app', '--host', '0.0.0.0', '--port', '8001', '--no-access-log']
               if role == 'api' else ['-m', 'services.private_workspace_worker'],
        'Healthcheck': {'Test': ['CMD-SHELL', 'curl -fsS http://127.0.0.1:8001/ready || exit 1'],
                        'Interval': 15_000_000_000, 'Timeout': 5_000_000_000,
                        'StartPeriod': 15_000_000_000, 'Retries': 3}
                       if role == 'api' else {'Test': ['NONE']},
    }
    host = {
        'ReadonlyRootfs': True, 'CapDrop': ['ALL'], 'CapAdd': None, 'Privileged': False,
        'NetworkMode': 'bridge', 'PidMode': '', 'IpcMode': 'private', 'Devices': [], 'VolumesFrom': None,
        'SecurityOpt': ['no-new-privileges'], 'RestartPolicy': {'Name': 'unless-stopped'},
        'LogConfig': {'Config': {'max-size': '5m', 'max-file': '3'}},
        'Tmpfs': {'/tmp': 'rw,nosuid,noexec,size=128m'},
        'PortBindings': {'8001/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8001'}]} if role == 'api' else {},
    }
    return {'Id': IDS[role], 'Image': IMAGE, 'Name': '/t24-google-ads-stage-' + role + '-' + ATTEMPT[:12],
            'Config': config, 'HostConfig': host,
            'Mounts': [{'Source': '/opt/t24-crm/app/data', 'Destination': '/app/backend/data', 'RW': False, 'Type': 'bind'},
                       {'Source': '/opt/t24-crm/private-workspace/data', 'Destination': '/private-data', 'RW': True, 'Type': 'bind'},
                       {'Source': '', 'Destination': '/tmp', 'RW': True, 'Type': 'tmpfs'}],
            'State': {'Status': 'created', 'StartedAt': '', 'Dead': False, 'Restarting': False, 'Running': False},
            'RestartCount': 0}


def private_fixture():
    return {'device':1,'inode':2,'schema_sha256':'schema','items':{'original':'hash'},'preferences':{},
            'connections':{'gmail-id':{'owner_id':'4','source_id':'gmail','status':'connected','generation':1,
                                      'account_label':'owner@example.test','scope':'https://www.googleapis.com/auth/gmail.readonly','connection_mode':'oauth'}},
            'frozen_rows':{name:'synthetic-hash' for name in switch.TABLES}}


class EnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.env = dict(old_environment(), GOOGLE_WORKSPACE_CLIENT_ID='123456789012-syntheticclient123.apps.googleusercontent.com',
                        GOOGLE_WORKSPACE_CLIENT_SECRET='synthetic-only-secret-123',
                        PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT='owner@example.test')
        self.data = encode_env(self.env)
        self.pin = mock.patch.object(switch, 'CURRENT_ENV_SHA', switch.sha(self.data)); self.pin.start(); self.addCleanup(self.pin.stop)

    def after(self,data=None):
        return switch.target_environment(self.data if data is None else data)

    def test_only_selected_direct_target_is_appended(self):
        old,new = switch.env_check(self.data,self.after(),'OWNER@example.test')
        self.assertEqual(old,self.env); self.assertEqual(new[switch.TARGET_KEY],'7539806760')
        self.assertEqual({k:v for k,v in new.items() if k != switch.TARGET_KEY},self.env)
        self.assertEqual(self.after(),self.data+b'PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=7539806760\n')

    def test_changed_secret_setting_or_added_platform_rejected(self):
        for key in ('JWT_SECRET_KEY','PRIVATE_WORKSPACE_ENCRYPTION_KEY','DATABASE_URL','GOOGLE_WORKSPACE_CLIENT_SECRET','OPENAI_API_KEY'):
            values=dict(self.env); values[key]='changed-synthetic-value';values[switch.TARGET_KEY]=switch.TARGET_CUSTOMER
            with self.subTest(key=key), self.assertRaisesRegex(switch.SwitchError,'ONLY_ADS_TARGET_ENV_CHANGE_ALLOWED'):
                switch.env_check(self.data,encode_env(values),'owner@example.test')

    def test_old_first_connection_backup_rejected(self):
        with self.assertRaisesRegex(switch.SwitchError,'ORIGINAL_ENV_HASH_DRIFT'):
            switch.env_check(encode_env(old_environment()),self.after(),'owner@example.test')

    def test_wrong_gmail_account_rejected(self):
        with self.assertRaisesRegex(switch.SwitchError,'EXPECTED_EMAIL_MISMATCH'):
            switch.env_check(self.data,self.after(),'other@example.test')

    def test_reordered_lines_rejected(self):
        with self.assertRaisesRegex(switch.SwitchError,'ONLY_ADS_TARGET_ENV_CHANGE_ALLOWED'):
            switch.env_check(self.data,encode_env(dict(reversed(list(self.env.items()))))+b'PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID=7539806760\n','owner@example.test')

    def test_invalid_credentials_even_with_pinned_hash_rejected(self):
        for key,value in [('GOOGLE_WORKSPACE_CLIENT_SECRET','short'),('GOOGLE_WORKSPACE_CLIENT_ID','not-client')]:
            values=dict(self.env);values[key]=value;data=encode_env(values)
            with mock.patch.object(switch,'CURRENT_ENV_SHA',switch.sha(data)), self.assertRaisesRegex(switch.SwitchError,'GOOGLE_CONFIGURATION_INVALID'):
                switch.env_check(data,self.after(data),'owner@example.test')

    def test_manager_and_conflicting_targets_are_refused(self):
        for key,value in [('GOOGLE_ADS_LOGIN_CUSTOMER_ID','7539806760'),('GOOGLE_ADS_CUSTOMER_ID','1111111111'),(switch.TARGET_KEY,'1111111111')]:
            with self.subTest(key=key),self.assertRaises(switch.SwitchError):
                self.after(encode_env(dict(self.env,**{key:value})))

    def test_verified_config_receipt_uses_exact_backup_and_new_env(self):
        receipt_name='google-ads-config-'+ATTEMPT+'.json';backup='runtime.env.before-google-ads-'+ATTEMPT
        value={'phase':'GOOGLE_ADS_CUSTOMER_CONFIGURED','before_env_sha256':switch.sha(self.data),
               'backup_sha256':switch.sha(self.data),'after_env_sha256':switch.sha(self.after()),'backup_basename':backup,
               'jwt_and_private_encryption_preserved':True,'existing_other_environment_values_preserved':True,
               'services_modified':False,'databases_modified':False,'changed_keys':[switch.TARGET_KEY],'changed_key_count':1}
        blob=json.dumps(value).encode();args=SimpleNamespace(config_receipt=receipt_name,config_receipt_sha256=switch.sha(blob),
                                                         env_sha256=switch.sha(self.after()),expected_email='owner@example.test')
        def read(path):
            return blob if path.name==receipt_name else self.data if path.name==backup else self.after()
        with mock.patch.object(switch,'read_protected',side_effect=read):
            old,new=switch.configured_environment(args);self.assertEqual(old,self.env);self.assertEqual(new[switch.TARGET_KEY],switch.TARGET_CUSTOMER)
        args.config_receipt='../unsafe.json'
        with self.assertRaisesRegex(switch.SwitchError,'CONFIG_RECEIPT_BASENAME_INVALID'):
            switch.configured_environment(args)
        args.config_receipt=receipt_name;args.config_receipt_sha256='f'*64
        with mock.patch.object(switch,'read_protected',side_effect=read),self.assertRaisesRegex(switch.SwitchError,'CONFIG_RECEIPT_HASH_DRIFT'):
            switch.configured_environment(args)



class PureBoundaryTest(unittest.TestCase):
    def nginx_fixture(self):
        return (str(switch.OLD_PUBLIC) + '\nproxy_pass http://127.0.0.1:8000;\n' +
                'proxy_pass http://127.0.0.1:8001;\n' + '\n'.join(switch.HEADERS)).encode()

    def test_nginx_changes_one_exact_root_and_no_other_bytes(self):
        before = self.nginx_fixture()
        with mock.patch.object(switch, 'NGINX_SHA', switch.sha(before)):
            after = switch.nginx_bytes(before)
        self.assertEqual(after.replace(str(switch.PUBLIC).encode(), str(switch.OLD_PUBLIC).encode(), 1), before)

    def test_nginx_wrong_hash_duplicate_root_or_missing_proxy_rejected(self):
        before = self.nginx_fixture()
        with self.assertRaisesRegex(switch.SwitchError, 'NGINX_BASELINE_DRIFT'):
            switch.nginx_bytes(before)
        for malformed in (before + str(switch.OLD_PUBLIC).encode(), before.replace(b'127.0.0.1:8000', b'127.0.0.1:9000')):
            with mock.patch.object(switch, 'NGINX_SHA', switch.sha(malformed)), self.assertRaises(switch.SwitchError):
                switch.nginx_bytes(malformed)

    def test_create_command_never_starts_services_and_uses_only_env_path(self):
        for role in ('api', 'worker'):
            command = switch.create_command('t24-google-ads-stage-' + role + '-synthetic', role, IMAGE, ATTEMPT)
            self.assertEqual(command[:2], ['docker', 'create'])
            self.assertIn('--read-only', command)
            self.assertIn(str(switch.ENV), command)
            self.assertIn('type=bind,src=/opt/t24-crm/app/data,dst=/app/backend/data,readonly', command)
            self.assertIn(IMAGE, command)
            self.assertNotIn('t24-crm', command)
            self.assertNotIn('--env', command)
        with self.assertRaises(switch.SwitchError):
            switch.create_command('t24-crm', 'api', IMAGE, ATTEMPT)

    def test_private_records_preserved_but_new_records_allowed(self):
        before = private_fixture()
        switch.check_private_preserved(before, dict(before, items={'original': 'hash', 'new': 'other'}))
        for after in (dict(before, inode=3), dict(before, schema_sha256='changed'), dict(before, items={}),
                      dict(before, items={'original': 'changed'})):
            with self.subTest(after=after), self.assertRaises(switch.SwitchError):
                switch.check_private_preserved(before, after)

    def test_no_store_requires_exact_directive(self):
        for value in ('no-store', 'private, no-store', 'NO-STORE, max-age=0'):
            self.assertTrue(switch.no_store({'cache-control': value}))
        for value in ('x-no-store', 'no-storeish', 'private', ''):
            self.assertFalse(switch.no_store({'cache-control': value}))

    def test_full_four_table_preservation_required_before_new_worker(self):
        before = private_fixture()
        switch.check_private_frozen(before, deepcopy(before))
        for table in switch.TABLES:
            after = deepcopy(before); after['frozen_rows'][table] = 'changed'
            with self.subTest(table=table), self.assertRaisesRegex(switch.SwitchError, 'PRIVATE_ROWS_CHANGED_BEFORE_NEW_WORKER'):
                switch.check_private_frozen(before, after)

    def test_post_worker_sync_rows_may_change_but_identity_and_user_choices_must_not(self):
        before = private_fixture()
        after = deepcopy(before); after['frozen_rows'] = {}; after['items']['new-synced-item'] = 'new-stable-key'
        switch.check_private_preserved(before, after)
        for field in ('status', 'owner_id', 'account_label', 'scope', 'generation', 'connection_mode'):
            changed = deepcopy(after); changed['connections']['gmail-id'][field] = 'changed'
            with self.subTest(field=field), self.assertRaisesRegex(switch.SwitchError, 'PRIVATE_CONNECTION_IDENTITY_OR_STATUS_CHANGED'):
                switch.check_private_preserved(before, changed)
        changed = deepcopy(after); changed['preferences']['4'] = 'overwritten-user-preference'
        with self.assertRaisesRegex(switch.SwitchError, 'PRIVATE_PREFERENCES_CHANGED'):
            switch.check_private_preserved(before, changed)

    def test_connected_owner_gmail_profile_and_readonly_scope_are_required(self):
        before = private_fixture()
        switch.connected_gmail_check(before, 'OWNER@example.test')
        for field, value in [('status','disconnected'), ('account_label','other@example.test'),
                             ('scope','https://mail.google.com/'), ('owner_id','5'), ('connection_mode','manual')]:
            changed=deepcopy(before);changed['connections']['gmail-id'][field]=value
            with self.subTest(field=field), self.assertRaisesRegex(switch.SwitchError, 'CONNECTED_GMAIL_BASELINE_REQUIRED'):
                switch.connected_gmail_check(changed,'owner@example.test')

    def test_credentials_checker_never_passes_secret_values_and_opens_private_db_readonly(self):
        commands=[]
        with mock.patch.object(switch,'run',side_effect=lambda cmd,*a: commands.append(cmd) or
                               b'{"connected_credentials_readable":true,"connected_count":1}'):
            self.assertTrue(switch.credentials_readable(IDS['api'])['connected_credentials_readable'])
        command=commands[0]
        self.assertEqual(command[:3],['docker','exec',IDS['api']])
        self.assertIn('mode=ro',command[-1]);self.assertIn('PRAGMA query_only=ON',command[-1])
        self.assertNotIn('synthetic-only-secret',str(command));self.assertNotIn('services.private_workspace',command[-1])

    def test_unstamped_template_cannot_enter_server_io(self):
        args=SimpleNamespace(execute=True,candidate_sha256='a'*64,env_sha256=switch.CURRENT_ENV_SHA,
                             expected_email='owner@example.test')
        with mock.patch.object(switch,'SOURCE','__APP_SOURCE_SHA__'), \
             mock.patch.object(switch.os,'geteuid',return_value=0), \
             mock.patch.object(switch.socket,'gethostname',return_value=switch.HOST), \
             mock.patch.object(switch,'run',side_effect=AssertionError('must not execute')), \
             self.assertRaisesRegex(switch.SwitchError,'REVIEWED_CONSTANTS_MUST_BE_STAMPED'):
            switch.main(args)


class ActualSnapshotTest(unittest.TestCase):
    """Exercise the real read-only SQL against a temporary synthetic database."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'workspace.db'
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE private_connections(id TEXT,owner_id TEXT,source_id TEXT,status TEXT,
                  generation INTEGER,metadata_json TEXT,encrypted_credentials TEXT);
                CREATE TABLE private_items(id TEXT,owner_id TEXT,source_id TEXT,external_id TEXT,
                  local_title TEXT,local_summary TEXT,action_status TEXT,snoozed_until TEXT,
                  created_at TEXT,title TEXT,priority TEXT);
                CREATE TABLE private_preferences(owner_id TEXT,preferences_json TEXT);
                CREATE TABLE private_sync_runs(id TEXT,status TEXT);
            ''')
            metadata = json.dumps({'account_label':'owner@example.test','scope':'https://www.googleapis.com/auth/gmail.readonly','connection_mode':'oauth'})
            db.execute('INSERT INTO private_connections VALUES(?,?,?,?,?,?,?)',
                       ('gmail-id','4','gmail','connected',7,metadata,'synthetic-ciphertext'))
            db.execute('INSERT INTO private_items VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       ('mail-id','4','gmail','provider-id','my title','my note','snoozed','2030-01-01','2026-10-11','synthetic source title','normal'))
            db.execute('INSERT INTO private_preferences VALUES(?,?)',('4','{"gmail":{"topics":["finance"]}}'))
            db.execute('INSERT INTO private_sync_runs VALUES(?,?)',('sync-id','succeeded'))
        self.path.chmod(0o600)

    def snapshot(self, full=False):
        # Production root/device guards are independently covered; only those
        # host-specific stat fields are replaced for this local SQL fixture.
        with mock.patch.object(switch,'secure',return_value=SimpleNamespace(st_dev=64515,st_ino=282885)), \
             mock.patch.object(switch.os.path,'samefile',return_value=False):
            return switch.private_snapshot(self.path, full=full)

    def test_full_snapshot_guards_every_row_before_worker_but_allows_provider_refresh_after(self):
        before = self.snapshot(full=True)
        switch.connected_gmail_check(before,'OWNER@example.test')
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE private_connections SET encrypted_credentials=?',('synthetic-rotated-ciphertext',))
            db.execute('UPDATE private_items SET title=?,priority=?',('new provider title','urgent'))
            db.execute('INSERT INTO private_sync_runs VALUES(?,?)',('new-sync','succeeded'))
        after = self.snapshot(full=True)
        with self.assertRaisesRegex(switch.SwitchError,'PRIVATE_ROWS_CHANGED_BEFORE_NEW_WORKER'):
            switch.check_private_frozen(before,after)
        switch.check_private_preserved(before,self.snapshot())
        self.assertEqual(self.snapshot()['frozen_rows'],{})
        self.assertNotIn('synthetic-ciphertext',json.dumps(before))
        self.assertNotIn('synthetic source title',json.dumps(before))
        self.assertNotIn('my note',json.dumps(before))

    def test_actual_snapshot_detects_local_edit_preferences_and_generation_changes(self):
        before = self.snapshot()
        for statement,arguments,error in (
            ('UPDATE private_items SET local_summary=?',('changed local note',),'PRIVATE_EXISTING_KEYS_OR_OVERRIDES_CHANGED'),
            ('UPDATE private_preferences SET preferences_json=?',('{"gmail":{}}',),'PRIVATE_PREFERENCES_CHANGED'),
            ('UPDATE private_connections SET generation=?',(8,),'PRIVATE_CONNECTION_IDENTITY_OR_STATUS_CHANGED'),
        ):
            with self.subTest(statement=statement), sqlite3.connect(self.path) as db:
                db.execute('BEGIN'); db.execute(statement,arguments); db.commit()
                with self.assertRaisesRegex(switch.SwitchError,error):
                    switch.check_private_preserved(before,self.snapshot())
                if 'local_summary' in statement:
                    db.execute('UPDATE private_items SET local_summary=?',('my note',))
                elif 'preferences_json' in statement:
                    db.execute('UPDATE private_preferences SET preferences_json=?',('{"gmail":{"topics":["finance"]}}',))
                else:
                    db.execute('UPDATE private_connections SET generation=?',(7,))
                db.commit()


class StagedProtectionTest(unittest.TestCase):
    def check(self, info, role='api'):
        with mock.patch.object(switch, 'inspect', return_value=info):
            return switch.staged_check(IDS[role], role, IMAGE, ATTEMPT, {'SYNTHETIC': 'value'}, 'created')

    def test_api_and_worker_valid_synthetic_config(self):
        for role in ('api', 'worker'):
            self.assertEqual(self.check(staged_info(role), role)['id'], IDS[role])

    def test_identity_attempt_rw_mount_and_public_port_rejected(self):
        mutations = [lambda x: x.update(Id=switch.CRM_ID),
                     lambda x: x['Config']['Labels'].update({'t24.google_ads.upgrade.attempt': 'foreign'}),
                     lambda x: x['Mounts'][0].update(RW=True),
                     lambda x: x['HostConfig']['PortBindings']['8001/tcp'][0].update(HostIp='0.0.0.0')]
        for mutate in mutations:
            info = staged_info(); mutate(info)
            with self.subTest(mutation=mutate), self.assertRaises(switch.SwitchError):
                self.check(info)

    def test_additional_runtime_privileges_rejected(self):
        for key, value in (('Privileged', True), ('CapAdd', ['SYS_ADMIN']), ('NetworkMode', 'host'),
                           ('PidMode', 'host'), ('Devices', [{'PathOnHost': '/dev/sda'}])):
            info = staged_info(); info['HostConfig'][key] = value
            with self.subTest(key=key), self.assertRaises(switch.SwitchError):
                self.check(info)

    def test_duplicate_bind_and_extra_tmpfs_mount_rejected(self):
        for extra in (deepcopy(staged_info()['Mounts'][0]),
                      {'Source': '', 'Destination': '/app/backend', 'RW': True, 'Type': 'tmpfs'}):
            info = staged_info(); info['Mounts'].append(extra)
            with self.subTest(destination=extra['Destination']), self.assertRaises(switch.SwitchError):
                self.check(info)


class CurrentAssetsAndPublicTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        files = {'index.html': b'<script src="/assets/app.js"></script><link href="/assets/main.css">',
                 'assets/app.js': b'import "./chunk.js"; const css="assets/nested.css";',
                 'assets/chunk.js': b'import "./app.js";',
                 'assets/main.css': b'body{color:black}', 'assets/nested.css': b'p{margin:0}',
                 'assets/stale-obsolete.js': b'this cached historical asset is not reachable'}
        for name, blob in files.items():
            path = self.root / name; path.parent.mkdir(exist_ok=True); path.write_bytes(blob)
        self.files = files
        self.manifest = {name: switch.sha(blob) for name, blob in files.items()}
        self.graph = {name: value for name, value in self.manifest.items() if name.startswith('assets/') and 'stale' not in name}

    def test_reachable_graph_excludes_retained_history_and_handles_cycles(self):
        self.assertEqual(switch.current_assets(self.root, self.manifest), self.graph)

    def test_missing_reference_wrong_hash_or_symlink_fails_closed(self):
        app = self.root / 'assets/app.js'
        app.write_bytes(b'import "./missing.js";')
        manifest = dict(self.manifest); manifest['assets/app.js'] = switch.sha(app.read_bytes())
        with self.assertRaisesRegex(switch.SwitchError, 'CURRENT_ASSET_SCOPE_DRIFT'):
            switch.current_assets(self.root, manifest)
        app.write_bytes(self.files['assets/app.js'])
        (self.root / 'assets/chunk.js').write_bytes(b'changed')
        with self.assertRaisesRegex(switch.SwitchError, 'CURRENT_ASSET_BYTES_DRIFT'):
            switch.current_assets(self.root, self.manifest)
        chunk = self.root / 'assets/chunk.js'; chunk.unlink(); chunk.symlink_to(app)
        with self.assertRaisesRegex(switch.SwitchError, 'CURRENT_ASSET_BYTES_DRIFT'):
            switch.current_assets(self.root, self.manifest)

    def test_public_acceptance_retries_malformed_and_stale_version_with_mocked_http(self):
        versions = iter((b'{malformed', b'{"version":"old-version"}', json.dumps({'version': switch.VERSION}).encode()))
        headers = {name.lower(): value for name, value in switch.HEADERS.items()}
        headers['cache-control'] = 'private, no-store'
        requested = []
        def request(url, *args):
            requested.append(url)
            if '/app-version.json?' in url:
                return 200, headers, next(versions)
            if '/?google_ads_upgrade=' in url:
                return 200, headers, self.files['index.html']
            if switch.PREFIX in url:
                return 401, {'cache-control': 'no-store'}, b'{"detail":"unauthorized"}'
            if url.endswith('/ready'):
                return 200, {}, b'{"ready":true}'
            name = url.removeprefix('https://t24-crm.com/')
            return 200, {}, self.files[name]
        with mock.patch.object(switch, 'request', side_effect=request), mock.patch.object(switch.time, 'sleep') as sleep:
            switch.public_check(self.manifest, switch.VERSION, self.root)
        self.assertEqual(sum('/app-version.json?' in url for url in requested), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertFalse(any('stale-obsolete' in url for url in requested))
        self.assertEqual({url.removeprefix('https://t24-crm.com/') for url in requested if '/assets/' in url}, set(self.graph))


class RollbackTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.old_public = Path(temporary.name)
        (self.old_public / 'index.html').write_bytes(b'<html>synthetic old</html>')
        (self.old_public / 'app-version.json').write_text('{"version":"synthetic-old"}')
        self.original = b'synthetic nginx original'
        self.pin = mock.patch.object(switch, 'NGINX_SHA', switch.sha(self.original)); self.pin.start(); self.addCleanup(self.pin.stop)
        self.state = {'new_ids': dict(IDS), 'new_nginx_sha256': switch.sha(b'synthetic changed'),
                      'attempt': ATTEMPT, 'old_stop_begun': True}
        self.before = private_fixture()
        self.commands = []
        self.patches = [mock.patch.object(switch, 'read_nginx', side_effect=lambda: self.original),
                       mock.patch.object(switch, 'OLD_PUBLIC', self.old_public),
                       mock.patch.object(switch, 'crm_check', return_value={}),
                       mock.patch.object(switch, 'private_snapshot', return_value=self.before),
            mock.patch.object(switch, 'credentials_readable', return_value={'connected_credentials_readable':True,'connected_count':1}),
                       mock.patch.object(switch, 'run', side_effect=lambda command, *a, **kw: self.commands.append(command) or b''),
                       mock.patch.object(switch, 'require_free_name'), mock.patch.object(switch, 'wait_ready'),
                       mock.patch.object(switch, 'unauthenticated_check'), mock.patch.object(switch, 'public_check'),
                       mock.patch.object(switch, 'old_check', side_effect=lambda role, *a: {'Name': '/backup-' + role, 'State': {'Running': False}})]
        for patch in self.patches:
            patch.start(); self.addCleanup(patch.stop)

    def call(self):
        return switch.rollback(self.state, self.original, IMAGE, {'SYNTHETIC': 'value'}, {}, {}, self.before)

    def test_removes_only_attempt_new_ids_then_restores_old_api_before_worker(self):
        with mock.patch.object(switch, 'inspect', side_effect=lambda identity: staged_info('api' if identity == IDS['api'] else 'worker')):
            self.call()
        self.assertEqual(self.commands, [
            ['docker', 'rm', '-f', IDS['worker']], ['docker', 'rm', '-f', IDS['api']],
            ['docker', 'rename', switch.OLD_IDS['api'], 't24-private-api'], ['docker', 'start', switch.OLD_IDS['api']],
            ['docker', 'rename', switch.OLD_IDS['worker'], 't24-private-worker'], ['docker', 'start', switch.OLD_IDS['worker']]])
        self.assertEqual(self.state['phase'], 'ROLLED_BACK_PRIVATE_ONLY')
        self.assertTrue(all(switch.CRM_ID not in command and 't24-crm' not in command for command in self.commands))

    def test_foreign_new_identity_stops_before_any_container_mutation(self):
        info = staged_info('worker'); info['Config']['Labels']['t24.google_ads.upgrade.attempt'] = 'foreign'
        with mock.patch.object(switch, 'inspect', return_value=info), self.assertRaisesRegex(switch.SwitchError, 'NEW_CONTAINER_LABEL_DRIFT'):
            self.call()
        self.assertEqual(self.commands, [])

    def test_nginx_concurrent_change_stops_before_container_mutation(self):
        with mock.patch.object(switch, 'read_nginx', return_value=b'unapproved change'), \
             mock.patch.object(switch, 'staged_check') as checked, self.assertRaisesRegex(switch.SwitchError, 'ROLLBACK_NGINX_CONCURRENT_CHANGE'):
            self.call()
        checked.assert_not_called(); self.assertEqual(self.commands, [])

    def test_staging_failure_does_not_start_or_rename_old_private_services(self):
        self.state['old_stop_begun'] = False
        with mock.patch.object(switch, 'staged_check'):
            self.call()
        self.assertEqual(self.commands, [['docker', 'rm', '-f', IDS['worker']], ['docker', 'rm', '-f', IDS['api']]])

    def test_name_collision_preserves_retained_old_container(self):
        with mock.patch.object(switch, 'staged_check'), \
             mock.patch.object(switch, 'require_free_name', side_effect=switch.SwitchError('CONTAINER_NAME_COLLISION')), \
             self.assertRaisesRegex(switch.SwitchError, 'CONTAINER_NAME_COLLISION'):
            self.call()
        self.assertFalse(any(command[1] in ('rename', 'start') for command in self.commands))

    def test_lost_create_output_discovers_only_this_attempt_staged_name(self):
        self.state['new_ids'] = {}
        self.state['old_stop_begun'] = False
        self.state['stage_names'] = {role: 't24-google-ads-stage-' + role + '-synthetic' for role in ('api', 'worker')}
        looked_up = []
        def inspect(identity, optional=False):
            looked_up.append((identity, optional))
            return staged_info('worker' if identity in (IDS['worker'], self.state['stage_names']['worker']) else 'api')
        with mock.patch.object(switch, 'inspect', side_effect=inspect):
            self.call()
        self.assertEqual(self.state['new_ids'], IDS)
        self.assertEqual([identity for identity, optional in looked_up if optional],
                         [self.state['stage_names']['worker'], self.state['stage_names']['api']])
        self.assertEqual(self.commands, [['docker', 'rm', '-f', IDS['worker']], ['docker', 'rm', '-f', IDS['api']]])

    def test_lost_output_name_collision_with_foreign_attempt_never_removed(self):
        self.state['new_ids'] = {}
        self.state['stage_names'] = {'worker': 't24-google-ads-stage-worker-synthetic'}
        info = staged_info('worker'); info['Config']['Labels']['t24.google_ads.upgrade.attempt'] = 'foreign'
        with mock.patch.object(switch, 'inspect', return_value=info), self.assertRaisesRegex(switch.SwitchError, 'NEW_CONTAINER_LABEL_DRIFT'):
            self.call()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.state['new_ids'], {})


class OrchestrationTest(unittest.TestCase):
    """Run main only after replacing every server/network/database boundary."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ('switch-state-' + ATTEMPT + '.json')).write_bytes(b'{}')
        self.old = old_environment(); self.new = dict(self.old, SYNTHETIC='value')
        self.old_bytes, self.new_bytes = encode_env(self.old), encode_env(self.new)
        self.original, self.changed = b'synthetic-before', b'synthetic-after'
        self.nginx_current = self.original
        self.before = private_fixture()
        self.business = {'schema_sha256': 'schema', 'tables': {'synthetic': {'count': 1, 'sha256': 'rowhash'}}}
        baseline = {'crm_container_id': switch.CRM_ID, 'crm_image_id': switch.CRM_IMAGE,
                    'crm_started_at': switch.CRM_STARTED, 'crm_configuration_sha256': switch.CRM_CONFIG,
                    'nginx_sha256': switch.sha(self.original),
                    'private': {'t24-private-' + role: dict(switch.PRIVATE_PROOFS[role], id=identity) for role, identity in switch.OLD_IDS.items()}}
        self.candidate = {'image_id': IMAGE, 'running_baseline': baseline}
        self.args = SimpleNamespace(execute=True, candidate_sha256='a' * 64,
                                    env_sha256=switch.sha(self.new_bytes),config_receipt='google-ads-config-'+ATTEMPT+'.json',
                                    config_receipt_sha256='b'*64,expected_email='owner@example.test')
        self.commands, self.saved, self.events = [], [], []
        self.fail_code = None
        def run(command, code, *args):
            self.commands.append(command)
            if code == self.fail_code:
                raise switch.SwitchError(code)
            if command[:2] == ['docker', 'create']:
                role = 'worker' if 'services.private_workspace_worker' in command else 'api'
                return IDS[role].encode() + b'\n'
            return b''
        def save(path, value, replace=False):
            self.saved.append((path.name, deepcopy(value)))
        def atomic(data, hashes):
            self.nginx_current = data; self.events.append('nginx')
        self.patches = [
            mock.patch.object(switch, 'RELEASE', self.root), mock.patch.object(switch, 'SOURCE', 'c'*40),
            mock.patch.object(switch, 'VERSION', 'd'*12), mock.patch.object(switch, 'PUBLIC', self.root/'static'),
            mock.patch.object(switch, 'CURRENT_ENV_SHA', switch.sha(self.new_bytes)), mock.patch.object(switch, 'NGINX_SHA', switch.sha(self.original)),
            mock.patch.object(switch.os, 'geteuid', return_value=0), mock.patch.object(switch.os, 'umask'),
            mock.patch.object(switch.socket, 'gethostname', return_value=switch.HOST),
            mock.patch.object(switch.os, 'open', return_value=123), mock.patch.object(switch.os, 'close'),
            mock.patch.object(switch.fcntl, 'flock'), mock.patch.object(switch, 'secure'),
            mock.patch.object(switch, 'candidate_check', return_value=(self.candidate, {'index.html': 'hash'})),
            mock.patch.object(switch, 'read_protected', side_effect=lambda path: self.new_bytes if path == switch.ENV else self.old_bytes),
            mock.patch.object(switch, 'configured_environment', return_value=(self.old, self.new)),
            mock.patch.object(switch, 'crm_check', return_value={'id': switch.CRM_ID}),
            mock.patch.object(switch, 'inspect', return_value={'Config': {'Env': ['JWT_SECRET_KEY=' + self.old['JWT_SECRET_KEY']]}}),
            mock.patch.object(switch, 'old_check', return_value={}),
            mock.patch.object(switch, 'read_nginx', side_effect=lambda: self.nginx_current),
            mock.patch.object(switch, 'nginx_bytes', return_value=self.changed),
            mock.patch.object(switch, 'private_snapshot', return_value=self.before),
            mock.patch.object(switch, 'credentials_readable', return_value={'connected_credentials_readable':True,'connected_count':1}),
            mock.patch.object(switch, 'business_fingerprints', return_value=self.business),
            mock.patch.object(switch, 'uuid4', return_value=SimpleNamespace(hex=ATTEMPT)),
            mock.patch.object(switch, 'write_new'), mock.patch.object(switch, 'save', side_effect=save),
            mock.patch.object(switch, 'require_free_name'), mock.patch.object(switch, 'run', side_effect=run),
            mock.patch.object(switch, 'staged_check', side_effect=lambda identity, *a: {'id': identity, 'restart_count': 0}),
            mock.patch.object(switch, 'wait_ready', side_effect=lambda: self.events.append('api_ready')),
            mock.patch.object(switch, 'wait_api_healthy', side_effect=lambda identity: self.events.append('api_healthy')),
            mock.patch.object(switch, 'unauthenticated_check'), mock.patch.object(switch.time, 'sleep'),
            mock.patch.object(switch, 'atomic_nginx', side_effect=atomic), mock.patch.object(switch, 'public_check'),
            mock.patch.object(switch, 'public_manifest'), mock.patch('builtins.print'),
        ]
        for patch in self.patches:
            patch.start(); self.addCleanup(patch.stop)

    def test_stages_both_before_stop_worker_then_api_and_starts_api_before_worker(self):
        with mock.patch.object(switch, 'rollback') as rollback:
            switch.main(self.args)
        rollback.assert_not_called()
        creates = [i for i, command in enumerate(self.commands) if command[:2] == ['docker', 'create']]
        stops = [(i, command[-1]) for i, command in enumerate(self.commands) if command[:2] == ['docker', 'stop']]
        self.assertEqual(len(creates), 2)
        self.assertGreater(stops[0][0], max(creates))
        self.assertEqual([identity for i, identity in stops], [switch.OLD_IDS['worker'], switch.OLD_IDS['api']])
        starts = [command[-1] for command in self.commands if command[:2] == ['docker', 'start']]
        self.assertEqual(starts, [IDS['api'], IDS['worker']])
        self.assertEqual(self.events, ['api_ready', 'api_healthy', 'nginx'])
        final = self.saved[-1][1]
        self.assertEqual(final['phase'], 'GOOGLE_ADS_UPGRADE_SERVER_VERIFIED')
        self.assertFalse(final['gmail_connected_verified'])
        self.assertFalse(final['databases_restored'])
        self.assertFalse(any(switch.CRM_ID in command or 't24-crm' in command for command in self.commands))

    def test_staged_create_failure_invokes_rollback_before_old_stop(self):
        self.fail_code = 'STAGED_CREATE_FAILED'
        with mock.patch.object(switch, 'rollback') as rollback, \
             self.assertRaisesRegex(switch.SwitchError, 'UPGRADE_REJECTED_PRIVATE_ROLLBACK_VERIFIED'):
            switch.main(self.args)
        rollback.assert_called_once()
        state = rollback.call_args.args[0]
        self.assertFalse(state['old_stop_begun'])
        self.assertEqual(state['new_ids'], {})
        self.assertEqual(len(state['stage_names']), 2)
        self.assertFalse(any(command[:2] == ['docker', 'stop'] for command in self.commands))

    def test_api_start_failure_invokes_rollback_and_never_starts_worker(self):
        self.fail_code = 'NEW_API_START_FAILED'
        with mock.patch.object(switch, 'rollback') as rollback, \
             self.assertRaisesRegex(switch.SwitchError, 'UPGRADE_REJECTED_PRIVATE_ROLLBACK_VERIFIED'):
            switch.main(self.args)
        rollback.assert_called_once()
        self.assertTrue(rollback.call_args.args[0]['old_stop_begun'])
        self.assertEqual([command[-1] for command in self.commands if command[:2] == ['docker', 'start']], [IDS['api']])
        self.assertNotIn('nginx', self.events)

    def test_frozen_private_row_drift_rolls_back_before_candidate_worker(self):
        with mock.patch.object(switch,'check_private_frozen',side_effect=switch.SwitchError('PRIVATE_ROWS_CHANGED_BEFORE_NEW_WORKER')), \
             mock.patch.object(switch,'rollback') as rollback, \
             self.assertRaisesRegex(switch.SwitchError,'UPGRADE_REJECTED_PRIVATE_ROLLBACK_VERIFIED'):
            switch.main(self.args)
        rollback.assert_called_once()
        self.assertNotIn(IDS['worker'],[c[-1] for c in self.commands if c[:2]==['docker','start']])


if __name__ == '__main__':
    unittest.main()
