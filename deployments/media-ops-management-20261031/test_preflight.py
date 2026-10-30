"""Secret-free offline tests for the standalone read-only release proof."""
import base64
import copy
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('media_management_readonly_preflight_tests', ROOT / 'preflight.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
spec2 = importlib.util.spec_from_file_location('media_management_preflight_command_tests', ROOT / 'generate_preflight_command.py')
g = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(g)


class FakeFile:
    def __init__(self, body=b'fixture-nginx'):
        self.body = body
    def read_bytes(self): return self.body
    def stat(self): return SimpleNamespace(st_dev=p.BASE_DATABASE_IDENTITY[0], st_ino=p.BASE_DATABASE_IDENTITY[1])


class Fixture:
    def __init__(self):
        self.env = ['PATH=/usr/bin', 'T24_GBP_ENABLED=true', 'T24_GBP_API_APPROVED=true',
            'T24_GBP_CLIENT_ID=example-client', 'T24_GBP_CLIENT_SECRET=SUPER_SECRET_VALUE',
            'T24_GBP_TOKEN_KEY=SUPER_ENCRYPTION_KEY', 'T24_GBP_PUBLIC_URL=https://t24-crm.com']
        self.info = {'Id': p.BASE_RUNTIME['id'], 'Image': p.BASE_IMAGE, 'State': {'Running': True},
            'Config': {'Env': self.env}, '_runtime': copy.deepcopy(p.BASE_RUNTIME)}
        self.inventory = {'main.py': 'a' * 64, 'models/google_business.py': 'b' * 64,
            'routers/google_business.py': 'c' * 64, 'services/google_business.py': 'd' * 64, 'other.py': 'e' * 64}
        row = {'columns': ['id'], 'schema': {'id': ['INTEGER', 1, None, 1]}, 'indexes': {}, 'count': 0, 'rows_sha256': '0' * 64}
        self.rows = {f'existing_{i}': copy.deepcopy(row) for i in range(119)}
        self.rows.update({key: copy.deepcopy(row) for key in p.GOOGLE_TABLES})
        # Actual OAuth/binding data are permitted: do not require fresh empty Google tables.
        self.rows['google_business_connections']['count'] = 1
        self.rows['google_business_bindings']['count'] = 1
        self.schema = 'schema-fixture'
        self.static = {'app-version.json': 'v' * 64, 'index.html': 'x' * 64}
        self.nginx = FakeFile()
        self.active = b'# configuration file /etc/nginx/sites-enabled/t24-crm:\nfixture-nginx\n'
        self.public = Path('/var/www/t24-crm-public/google-business-7431d1986b81-20261030')
        self.prior = {'stage': 'GOOGLE_BUSINESS_DEPLOYED_VERIFIED', 'deployed': True,
            'source_sha': p.BASE_SOURCE, 'frontend_version': p.BASE_FRONTEND, 'schema_revision': p.BASE_REVISION,
            'candidate_inventory_sha256': 'inventory-fixture', 'schema_sha256': self.schema,
            'public_root': str(self.public), 'public_inventory_sha256': p.digest(self.static)}
        self.enabled = {'stage': 'GBP_CONFIG_ENABLED_EXISTING_CANDIDATE_VERIFIED', 'enabled': True,
            'source_sha': p.BASE_SOURCE, 'frontend_version': p.BASE_FRONTEND, 'schema_revision': p.BASE_REVISION,
            'crm': copy.deepcopy(p.BASE_RUNTIME), 'active_nginx_config_sha256': p.H(self.active), 'callback_sentinel_verified': True}
        self.logging = {'active_nginx_config_sha256': p.H(self.active), 'callback_sentinel_verified': True}
        self.pins = {'roles': {'api': {}, 'worker': {}}}
        self.calls = []
        self.row_reads = 0
        def read(path, expected=None):
            self.calls.append(('read', str(path), expected))
            values = {p.PINS: self.pins, p.PRIOR_RELEASE / 'deployed.json': self.prior,
                p.ENABLED_RECEIPT: self.enabled, p.LOGGING_RECEIPT: self.logging,
                p.PRIOR_RELEASE / 'backend-candidate-inventory.json': self.inventory}
            return json.dumps(values[path]).encode()
        def rows(*args):
            self.row_reads += 1
            value = copy.deepcopy(self.rows)
            if self.row_reads > 1 and getattr(self, 'row_drift', False): value['existing_0']['count'] += 1
            return value
        def inspect(name):
            self.calls.append(('inspect', name))
            return copy.deepcopy(self.info)
        self.m = SimpleNamespace(read=read, inspect=inspect, runtime=lambda info: info['_runtime'],
            retained=lambda: SimpleNamespace(require_safe_original_restart=lambda info: None),
            verify_secret_mount=lambda info: None, verify_production_worker_enabled=lambda info: None,
            credential_boundary=lambda: {'credential_content_read': False, 'inode': 9},
            inventory=lambda name: copy.deepcopy(self.inventory), digest=p.digest,
            schema_signature=lambda *args: self.schema, sql_snapshot=rows,
            NGINX=self.nginx, BUSINESS=FakeFile(), tree=lambda path: copy.deepcopy(self.static),
            run=lambda args, code: self.active, ready=lambda name: self.calls.append(('ready', name)),
            private_boundary=lambda *args: (_ for _ in ()).throw(AssertionError('PRIVATE_CONTENT_READER_FORBIDDEN')))

    def run(self):
        original = Path.read_bytes
        def file_read(path):
            if path == self.public / 'app-version.json': return json.dumps({'version': p.BASE_FRONTEND}).encode()
            return original(path)
        with patch.object(p, 'load_legacy', return_value=self.m), patch.object(p.os, 'geteuid', return_value=0), \
                patch.object(p.socket, 'gethostname', return_value=p.HOST), patch.object(p.os, 'umask'), \
                patch.object(p.resource, 'setrlimit'), patch.object(p, 'private_metadata_boundary', return_value={
                    'private_boundary_verified': True, 'private_file_content_read': False, 'private_runtime': {'api': {}, 'worker': {}}}), \
                patch.object(p, 'protected_metadata', return_value={'inode': 7, 'mode': 0o600}), \
                patch.object(p, 'NGINX_SHA', p.H(self.nginx.body)), patch.object(p, 'ACTIVE_NGINX_SHA', p.H(self.active)), \
                patch.object(Path, 'read_bytes', file_read), patch.object(Path, 'resolve', lambda path: path):
            return p.proof()


class PreflightProofTests(unittest.TestCase):
    def test_populated_google_tables_are_preserved_and_proof_has_only_hashes(self):
        f = Fixture(); value = f.run()
        self.assertEqual(value['stage'], 'MEDIA_OPS_MANAGEMENT_READONLY_PREFLIGHT')
        self.assertEqual(value['rows']['google_business_connections']['count'], 1)
        self.assertEqual(len(value['rows']), 124)
        self.assertEqual(value['original_columns'], {key: row['columns'] for key, row in f.rows.items()})
        self.assertEqual(set(value['backend_changed_before']), p.BACKEND_FILES)
        self.assertIsNone(value['backend_changed_before']['services/google_business_ai.py'])
        body = json.dumps(value)
        self.assertNotIn('SUPER_SECRET', body); self.assertNotIn('SUPER_ENCRYPTION', body)
        self.assertFalse(value['business_writes']); self.assertFalse(value['provider_requests'])
        self.assertFalse(value['credential_content_read']); self.assertFalse(value['private_file_content_read'])
        self.assertTrue(value['scheduler_disabled']); self.assertEqual(f.row_reads, 2)

    def test_exact_enabled_runtime(self):
        for key, value in [('id', 'unknown-id'), ('config', 'unknown-config'), ('restart', 1), ('started', 'new-time')]:
            with self.subTest(key=key):
                f = Fixture(); f.info['_runtime'][key] = value
                with self.assertRaisesRegex(RuntimeError, 'CURRENT_ENABLED_RUNTIME_DRIFT'): f.run()

    def test_running_container_required(self):
        f = Fixture(); f.info['State']['Running'] = False
        with self.assertRaisesRegex(RuntimeError, 'CURRENT_ENABLED_RUNTIME_DRIFT'): f.run()

    def test_prior_receipt_identity(self):
        f = Fixture(); f.prior['source_sha'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'EXACT_PRIOR_RELEASE_REQUIRED'): f.run()

    def test_enabled_receipt_identity(self):
        f = Fixture(); f.enabled['crm']['config'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'EXACT_ENABLED_RECEIPT_REQUIRED'): f.run()

    def test_callback_receipt_required(self):
        f = Fixture(); f.logging['callback_sentinel_verified'] = False
        with self.assertRaisesRegex(RuntimeError, 'EXACT_CALLBACK_PROTECTION_RECEIPT_REQUIRED'): f.run()

    def test_revision_schema_drift(self):
        f = Fixture(); f.prior['schema_sha256'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'PRIOR_RELEASE_SCHEMA_DRIFT'): f.run()

    def test_business_database_identity_pinned(self):
        f = Fixture(); f.m.BUSINESS.stat = lambda: SimpleNamespace(st_dev=1, st_ino=2)
        with self.assertRaisesRegex(RuntimeError, 'EXACT_BUSINESS_DATABASE_IDENTITY_REQUIRED'): f.run()

    def test_new_management_tables_must_not_exist(self):
        f = Fixture(); key = next(iter(p.NEW_TABLES)); f.rows[key] = f.rows.pop('existing_0')
        with self.assertRaisesRegex(RuntimeError, 'EXACT_EXISTING_TABLE_SET_REQUIRED'): f.run()

    def test_all_five_original_google_tables_required(self):
        f = Fixture(); f.rows.pop('google_business_grants')
        with self.assertRaisesRegex(RuntimeError, 'EXACT_EXISTING_TABLE_SET_REQUIRED'): f.run()

    def test_rows_changing_during_preflight_rejected(self):
        f = Fixture(); f.row_drift = True
        with self.assertRaisesRegex(RuntimeError, 'ROWS_CHANGED_DURING_PREFLIGHT'): f.run()

    def test_source_inventory_mismatch_rejected(self):
        f = Fixture(); original = f.m.inventory
        f.m.inventory = lambda name: {**original(name), 'unexpected.py': '0' * 64}
        with self.assertRaisesRegex(RuntimeError, 'PRIOR_RELEASE_SOURCE_INVENTORY_DRIFT'): f.run()

    def test_active_nginx_site_marker_required(self):
        f = Fixture(); f.active = b'fixture-nginx\n'
        f.enabled['active_nginx_config_sha256'] = p.H(f.active); f.logging['active_nginx_config_sha256'] = p.H(f.active)
        with self.assertRaisesRegex(RuntimeError, 'ACTIVE_NGINX_CONFIGURATION_DRIFT'): f.run()

    def test_static_version_and_inventory_required(self):
        f = Fixture(); f.prior['public_inventory_sha256'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'PRIOR_RELEASE_STATIC_DRIFT'): f.run()

    def test_root_and_host_before_reading(self):
        for uid, host in [(501, p.HOST), (0, 'other-host')]:
            with patch.object(p.os, 'geteuid', return_value=uid), patch.object(p.socket, 'gethostname', return_value=host), \
                    patch.object(p, 'load_legacy', side_effect=AssertionError('must not load')):
                with self.assertRaisesRegex(RuntimeError, 'EXACT_SERVER_ROOT_REQUIRED'): p.proof()


class EnvironmentTests(unittest.TestCase):
    def test_original_six_google_keys_and_absent_scheduler_accepted(self):
        proof = p.environment_proof(Fixture().info)
        self.assertTrue(proof['gbp_feature_enabled']); self.assertTrue(proof['scheduler_disabled'])
        self.assertEqual(set(proof), {'environment_sha256', 'environment_key_count', 'gbp_feature_enabled', 'scheduler_disabled', 'environment_values_exported'})

    def test_disabled_explicit_scheduler_accepted(self):
        f = Fixture(); f.env += ['T24_GBP_SCHEDULER_ENABLED=false', 'T24_GBP_SCHEDULER_ACTIVATION_FROM=']
        self.assertTrue(p.environment_proof(f.info)['scheduler_disabled'])

    def test_enabled_scheduler_rejected(self):
        for value in ['true', '1', 'TRUE', 'false ']:
            f = Fixture(); f.env.append('T24_GBP_SCHEDULER_ENABLED=' + value)
            with self.assertRaisesRegex(RuntimeError, 'GBP_SCHEDULER_MUST_REMAIN_DISABLED'): p.environment_proof(f.info)

    def test_activation_timestamp_or_unknown_scheduler_key_rejected(self):
        for item in ['T24_GBP_SCHEDULER_ACTIVATION_FROM=2026-10-31T00:00:00Z', 'T24_GBP_SCHEDULER_NEW=true']:
            f = Fixture(); f.env.append(item)
            with self.assertRaisesRegex(RuntimeError, 'GBP_SCHEDULER_MUST_REMAIN_DISABLED'): p.environment_proof(f.info)

    def test_duplicate_keys_rejected(self):
        f = Fixture(); f.env.append('T24_GBP_ENABLED=true')
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_ENVIRONMENT_KEY'): p.environment_proof(f.info)

    def test_missing_original_google_key_rejected(self):
        f = Fixture(); f.env.remove('T24_GBP_ENABLED=true')
        with self.assertRaisesRegex(RuntimeError, 'EXACT_EXISTING_GOOGLE_CONFIG_REQUIRED'): p.environment_proof(f.info)

    def test_unknown_google_scope_environment_rejected(self):
        f = Fixture(); f.env.append('T24_GBP_EXTRA_SECRET=value')
        with self.assertRaisesRegex(RuntimeError, 'EXACT_EXISTING_GOOGLE_CONFIG_REQUIRED'): p.environment_proof(f.info)

    def test_invalid_environment_cannot_escape_to_receipt(self):
        for item in ['missing-equals', 'X=secret\nOTHER=leak', 'X=zero\0byte', 'INVALID-KEY=foo']:
            f = Fixture(); f.env.append(item)
            with self.assertRaises(RuntimeError): p.environment_proof(f.info)


class PrivateMetadataTests(unittest.TestCase):
    def test_private_boundary_never_calls_content_readers(self):
        database = Path('/opt/t24-crm/private-workspace/data/workspace.db')
        env = Path('/opt/t24-crm/private-workspace/config/runtime.env')
        identity = {'device': 1, 'inode': 2, 'path_sha256': p.digest(str(database)), 'uid': 0, 'mode': 0o600}
        roles = {name: {'id': name + '-id', 'image': name + '-image', 'attempt': 'a', 'source': 's', 'runtime': {'id': name}} for name in ('api', 'worker')}
        calls = []
        def own(base, switch, identity, role, image, attempt, source, values, running):
            calls.append((role, running)); return {'id': role}
        switch = SimpleNamespace(environment=lambda info: {'SECRET': 'never-output'})
        tools = (None, SimpleNamespace(own_role=own), SimpleNamespace(PRIVATE_DB=database, ENV=env), None, switch)
        m = SimpleNamespace(retained=lambda: SimpleNamespace(tools=lambda: tools), inspect=lambda name: {})
        with patch.object(p, 'protected_metadata', side_effect=lambda path: {**identity, 'size': 44}), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('content forbidden')), \
                patch.object(Path, 'open', side_effect=AssertionError('content forbidden')):
            result = p.private_metadata_boundary(m, {'roles': roles, 'databases': {'private': {'identity': identity}}})
        self.assertEqual(calls, [('api', True), ('worker', True)])
        self.assertFalse(result['private_file_content_read']); self.assertNotIn('never-output', json.dumps(result))

    def test_private_identity_drift_rejected(self):
        database = Path('/opt/t24-crm/private-workspace/data/workspace.db')
        tools = (None, None, SimpleNamespace(PRIVATE_DB=database, ENV=Path('/opt/t24-crm/private-workspace/config/runtime.env')), None, None)
        m = SimpleNamespace(retained=lambda: SimpleNamespace(tools=lambda: tools))
        with patch.object(p, 'protected_metadata', return_value={key: 0 for key in ('device', 'inode', 'path_sha256', 'uid', 'mode')}):
            with self.assertRaisesRegex(RuntimeError, 'PRIVATE_DATABASE_IDENTITY_DRIFT'):
                p.private_metadata_boundary(m, {'databases': {'private': {'identity': {}}}})

    def test_metadata_only_guard_checks_modes_owner_and_symlink(self):
        file = Path('/fixed/credential.env')
        good = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1, st_dev=1, st_ino=2, st_size=20, st_mtime_ns=3, st_ctime_ns=4)
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        for wrong in [None, 'mode', 'owner', 'links']:
            value = copy.copy(good)
            if wrong == 'mode': value.st_mode = stat.S_IFREG | 0o644
            if wrong == 'owner': value.st_uid = 501
            if wrong == 'links': value.st_nlink = 2
            with patch.object(Path, 'resolve', lambda path: path), patch.object(Path, 'lstat', lambda path: value if path == file else directory), \
                    patch.object(Path, 'open', side_effect=AssertionError('never open')):
                if wrong:
                    with self.assertRaisesRegex(RuntimeError, 'PROTECTED_METADATA_FILE_REQUIRED'): p.protected_metadata(file)
                else: self.assertEqual(p.protected_metadata(file)['inode'], 2)
        with patch.object(Path, 'resolve', return_value=Path('/different')):
            with self.assertRaisesRegex(RuntimeError, 'PROTECTED_METADATA_PATH_REQUIRED'): p.protected_metadata(file)


class CommandTests(unittest.TestCase):
    def test_command_exact_hash_and_isolated_standalone_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); body = (ROOT / 'preflight.py').read_bytes(); (root / 'preflight.py').write_bytes(body)
            result = g.generate(root); command = (root / 'preflight-command.sh').read_text()
            self.assertIn('sudo python3 -I -S -B -', command); self.assertIn(p.H(body), command)
            self.assertEqual(result['readonly_preflight_sha256'], p.H(body))
            self.assertEqual(result['command_sha256'], p.H(command.encode()))
            self.assertEqual(stat.S_IMODE((root / 'preflight-command.sh').stat().st_mode), 0o600)
            self.assertNotIn('docker stop', command); self.assertNotIn('T24_GBP_CLIENT_SECRET=', command)

    def test_wrapper_filters_unexpected_exception_values(self):
        for error, wanted in [("ValueError('secret credential should never leave')", 'READONLY_PREFLIGHT_FAILED'),
                              ("RuntimeError('secret credential should never leave')", 'READONLY_PREFLIGHT_FAILED'),
                              ("RuntimeError('EXPECTED_GUARD_REJECTED')", 'EXPECTED_GUARD_REJECTED')]:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); (root / 'preflight.py').write_text('def main():\n raise ' + error + '\n')
                g.generate(root)
                command = (root / 'preflight-command.sh').read_text()
                code = command.split("<<'MEDIA_OPS_MANAGEMENT_READONLY'\n", 1)[1].rsplit('\nMEDIA_OPS_MANAGEMENT_READONLY', 1)[0]
                result = subprocess.run([sys.executable, '-I', '-S', '-B', '-'], input=code, text=True, capture_output=True)
                self.assertEqual(result.returncode, 1); self.assertEqual(result.stderr, '')
                self.assertEqual(json.loads(result.stdout), {'stage': 'MEDIA_OPS_MANAGEMENT_PREFLIGHT_REJECTED', 'code': wanted})

    def test_envelope_roundtrip(self):
        value = Fixture().run()
        with patch.object(p, 'proof', return_value=value), patch('sys.stdout', new_callable=io.StringIO) as stdout:
            p.main()
        envelope = json.loads(stdout.getvalue()); body = zlib.decompress(base64.b64decode(envelope['proof_zlib_base64'], validate=True))
        self.assertEqual(len(body), envelope['proof_bytes']); self.assertEqual(p.H(body), envelope['proof_sha256'])
        self.assertEqual(json.loads(body), value)


if __name__ == '__main__':
    unittest.main()
