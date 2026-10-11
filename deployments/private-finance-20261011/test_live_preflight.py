"""Synthetic readonly preflight regressions; no production or network access."""
import ast
from copy import deepcopy
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('private_finance_live', Path(__file__).with_name('live_preflight.py'))
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


class LivePreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.business = self.root / 'business.db'; self.private = self.root / 'private.db'
        with sqlite3.connect(self.business) as db:
            db.executescript("CREATE TABLE alembic_version(version_num TEXT); INSERT INTO alembic_version VALUES('ab6d8e2f0411');"
                "CREATE TABLE employees(id INTEGER,role TEXT,status TEXT); INSERT INTO employees VALUES(4,'super_admin','active');")
            for number in range(81): db.execute('CREATE TABLE customer_' + str(number) + '(id TEXT,value TEXT)')
            db.execute("INSERT INTO customer_0 VALUES('synthetic','CUSTOMER SENTINEL VALUE NEVER EMITTED')")
        with sqlite3.connect(self.private) as db:
            for name in audit.PRIVATE_TABLES: db.execute('CREATE TABLE ' + name + '(id TEXT,owner_id TEXT,private_value TEXT)')
            db.execute("INSERT INTO private_items VALUES('synthetic','4','PRIVATE MAIL BANK AMOUNT NEVER EMITTED')")
            self.private_schema = audit.digest(list(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')))
        self.private.chmod(0o600)

    def databases(self):
        info = self.private.lstat()
        root_info = SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_uid=0, st_nlink=1, st_mode=info.st_mode)
        original = Path.lstat
        def lstat(path): return root_info if path == self.private else original(path)
        with mock.patch.object(audit, 'BUSINESS', self.business), mock.patch.object(audit, 'PRIVATE_DB', self.private), \
             mock.patch.object(audit, 'PRIVATE_DEVICE_INODE', (info.st_dev, info.st_ino)), mock.patch.object(Path, 'lstat', lstat):
            return audit.database_snapshots({'private_database': {'schema_sha256': self.private_schema}})

    def test_database_reads_are_unchanged_and_emit_only_hashes_and_scope(self):
        before = (self.business.read_bytes(), self.private.read_bytes())
        business, private = self.databases()
        self.assertEqual(before, (self.business.read_bytes(), self.private.read_bytes()))
        self.assertEqual(business['table_count'], 83); self.assertTrue(business['owner_4_active_super_admin_verified'])
        self.assertEqual(private['table_inventory'], sorted(audit.PRIVATE_TABLES))
        text = json.dumps([business, private]); self.assertNotIn('SENTINEL VALUE', text); self.assertNotIn('PRIVATE MAIL', text)

    def test_schema_head_owner_and_private_inventory_drift_fail(self):
        for sql, target, code in (
            ("UPDATE alembic_version SET version_num='wrong'", self.business, 'BUSINESS_HEAD_DRIFT'),
            ("UPDATE employees SET status='inactive'", self.business, 'OWNER_IDENTITY_DRIFT'),
            ("CREATE TABLE private_unknown(owner_id TEXT)", self.private, 'PRIVATE_SCHEMA_DRIFT'),
            ("UPDATE private_items SET owner_id='5'", self.private, 'PRIVATE_OWNER_SCOPE_DRIFT'),
        ):
            with self.subTest(code=code):
                originals = (self.business.read_bytes(), self.private.read_bytes())
                with sqlite3.connect(target) as db: db.execute(sql)
                with self.assertRaisesRegex(audit.PreflightError, code): self.databases()
                self.business.write_bytes(originals[0]); self.private.write_bytes(originals[1])

    def test_credential_ciphertext_and_records_are_not_selected(self):
        source = Path(audit.__file__).read_text(); tree = ast.parse(source)
        commands = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess']
        self.assertEqual(len(commands), 1)
        self.assertEqual(ast.literal_eval(commands[0].args[0].elts[0]), 'docker')
        self.assertEqual(ast.literal_eval(commands[0].args[0].elts[1]), 'inspect')
        queries = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and
                   isinstance(node.func, ast.Attribute) and node.func.attr == 'execute' and node.args and isinstance(node.args[0], ast.Constant)]
        self.assertTrue(all(query.upper().startswith(('SELECT ', 'PRAGMA ', 'BEGIN')) for query in queries))
        self.assertIn('?mode=ro', source); self.assertIn('PRAGMA query_only=ON', source)
        self.assertNotIn('encrypted_credentials', source); self.assertNotIn('import services', source)
        self.assertNotIn('requests', source.replace('DeviceRequests', '')); self.assertNotIn('urllib', source)

    def test_prior_receipt_bytes_and_scope_are_strictly_pinned(self):
        value = {'phase': 'test'}; data = json.dumps(value).encode()
        with mock.patch.object(audit, 'safe_file', return_value=data):
            self.assertEqual(audit.receipt(self.private, audit.sha(data)), value)
            with self.assertRaisesRegex(audit.PreflightError, 'PRIOR_RECEIPT_HASH_DRIFT'):
                audit.receipt(self.private, '0' * 64)

    def test_saved_receipt_chain_does_not_invent_missing_source_field(self):
        runtime = {role: {'id': identity, 'image': audit.PRIVATE_IMAGE, 'configuration_sha256': 'a' * 64,
                         'started_at': 'synthetic-start'} for role, identity in audit.PRIVATE_IDS.items()}
        private = {'phase': 'ADS_HEALTH_UPGRADE_SERVER_VERIFIED', 'new_ids': audit.PRIVATE_IDS,
            'candidate_image': audit.PRIVATE_IMAGE, 'env_sha256': audit.ENV_SHA, 'business_tables_verified': 83,
            'new_private': runtime}
        static = {'phase': 'RESPONSIVE_STATIC_UPGRADE_VERIFIED', 'frontend_version': audit.FRONTEND_VERSION,
            'backend_services_modified': False, 'databases_restored': False, 'business_tables_verified': 83,
            'new_nginx_sha256': 'b' * 64, 'private_and_crm_runtime': {'private': runtime}}
        with mock.patch.object(audit, 'receipt', side_effect=[private, static]):
            self.assertEqual(audit.prior_receipts(), (private, static))
        changed = deepcopy(static); changed['private_and_crm_runtime']['private']['api']['configuration_sha256'] = 'c' * 64
        with mock.patch.object(audit, 'receipt', side_effect=[private, changed]):
            with self.assertRaisesRegex(audit.PreflightError, 'RECEIPT_RUNTIME_CHAIN_DRIFT'): audit.prior_receipts()

    def test_environment_presence_only_and_frozen_baseline_comparison(self):
        environment = {'PRIVATE_WORKSPACE_OWNER_IDS': '4', 'PRIVATE_WORKSPACE_PUBLIC_URL': 'https://t24-crm.com',
            'PRIVATE_WORKSPACE_DATABASE_URL': 'sqlite+aiosqlite:////private-data/workspace.db', 'DATABASE_URL': 'sqlite:///./data/crm_prod.db',
            'DATABASE_SCHEMA_MODE': 'verify_only', 'ENFORCE_EMPLOYEE_STATUS': 'true', 'ENFORCE_EMPLOYEE_SESSIONS': 'true',
            'SYNTHETIC_PRIVATE_KEY': 'DO-NOT-EMIT-SECRET-VALUE'}
        blob = ''.join(name + '=' + value + '\n' for name, value in environment.items()).encode()
        nginx = (str(audit.PUBLIC) + ' 127.0.0.1:8000 127.0.0.1:8001').encode()
        database = {'device': 64515, 'inode': 282885, 'schema_sha256': 'e' * 64}
        def read(path, **kwargs):
            if path == audit.ENV: return blob
            if path == audit.NGINX: return nginx
            return json.dumps({'version': audit.FRONTEND_VERSION}).encode()
        with mock.patch.object(audit.os, 'geteuid', return_value=0), mock.patch.object(audit.socket, 'gethostname', return_value=audit.HOST), \
             mock.patch.object(audit, 'prior_receipts', return_value=({'private_database': database}, {'new_nginx_sha256': audit.sha(nginx)})), \
             mock.patch.object(audit, 'ENV_SHA', audit.sha(blob)), mock.patch.object(audit, 'safe_file', side_effect=read), \
             mock.patch.object(audit, 'crm_snapshot', return_value={'id': audit.CRM_ID}), \
             mock.patch.object(audit, 'private_runtime', return_value={'verified': True}), \
             mock.patch.object(audit, 'database_snapshots', return_value=({'schema_sha256': 'f' * 64}, database)):
            output = audit.preflight()
        self.assertTrue(output['environment_presence']['SYNTHETIC_PRIVATE_KEY'])
        self.assertNotIn('DO-NOT-EMIT-SECRET-VALUE', json.dumps(output)); audit.compare_baseline(output, deepcopy(output))
        old = deepcopy(output); old['business']['schema_sha256'] = '0' * 64
        with self.assertRaisesRegex(audit.PreflightError, 'FROZEN_BASELINE_DRIFT'): audit.compare_baseline(output, old)

    def test_private_runtime_checks_launch_mounts_ports_and_hides_environment_values(self):
        values = {'PRIVATE_WORKSPACE_OWNER_IDS': '4', 'SYNTHETIC_PRIVATE_KEY': 'DO-NOT-EMIT-RUNTIME-SECRET'}
        infos = {}
        for role, identity in audit.PRIVATE_IDS.items():
            infos['t24-private-' + role] = {'Id': identity, 'Image': audit.PRIVATE_IMAGE, 'RestartCount': 0,
                'State': {'Running': True, 'StartedAt': 'synthetic-start', 'Health': {'Status': 'healthy'}},
                'Config': {'Env': [name + '=' + value for name, value in values.items()],
                    'Labels': {'t24.private.source.sha': audit.BASE_SOURCE, 't24.private.role': role},
                    'Entrypoint': ['uvicorn'] if role == 'api' else ['python'],
                    'Cmd': ['services.private_workspace_app:app', '--host', '0.0.0.0', '--port', '8001', '--no-access-log']
                           if role == 'api' else ['-m', 'services.private_workspace_worker']},
                'HostConfig': {'ReadonlyRootfs': True, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                    'NetworkMode': 'bridge', 'PortBindings': {'8001/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8001'}]} if role == 'api' else {}},
                'Mounts': [{'Type': 'bind', 'Source': '/opt/t24-crm/app/data', 'Destination': '/app/backend/data', 'RW': False},
                           {'Type': 'bind', 'Source': '/opt/t24-crm/private-workspace/data', 'Destination': '/private-data', 'RW': True}]}
        def check():
            pinned = {'new_private': {role: {'configuration_sha256': audit.config_hash(infos['t24-private-' + role]),
                'started_at': 'synthetic-start', 'restart_count': 0} for role in audit.PRIVATE_IDS}}
            with mock.patch.object(audit, 'inspect', side_effect=lambda name: infos[name]):
                return audit.private_runtime(pinned, values)
        result = check()
        self.assertNotIn('DO-NOT-EMIT-RUNTIME-SECRET', json.dumps(result))
        original = deepcopy(infos)
        for mutate, code in (
            (lambda value: value['t24-private-api']['Mounts'][0].update(RW=True), 'PRIVATE_MOUNT_DRIFT'),
            (lambda value: value['t24-private-api']['HostConfig']['PortBindings']['8001/tcp'][0].update(HostIp='0.0.0.0'), 'PRIVATE_API_LAUNCH_DRIFT'),
            (lambda value: value['t24-private-worker']['Config'].update(Cmd=['-m', 'customer_jobs']), 'PRIVATE_WORKER_LAUNCH_DRIFT'),
            (lambda value: value['t24-private-worker']['HostConfig'].update(Privileged=True), 'PRIVATE_ISOLATION_DRIFT'),
            (lambda value: value['t24-private-api']['Config']['Labels'].update({'t24.private.source.sha': 'other'}), 'PRIVATE_SOURCE_LABEL_DRIFT'),
        ):
            infos = deepcopy(original); mutate(infos)
            with self.subTest(code=code), self.assertRaisesRegex(audit.PreflightError, code): check()

    def test_wrong_host_is_rejected_before_any_inspection(self):
        with mock.patch.object(audit.os, 'geteuid', return_value=0), mock.patch.object(audit.socket, 'gethostname', return_value='other'), \
             mock.patch.object(audit, 'prior_receipts') as prior:
            with self.assertRaisesRegex(audit.PreflightError, 'VERIFIED_ROOT_SERVER_REQUIRED'): audit.preflight()
            prior.assert_not_called()


if __name__ == '__main__': unittest.main()
