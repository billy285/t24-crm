"""Local release guard tests: no Docker, network or production writes."""
import copy
import importlib.util
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r = load('merchant_release', Path(__file__).with_name('release.py'))
b = load('merchant_payload', Path(__file__).with_name('build_payload.py'))
legacy = load('local_sales_release_primitives', Path(__file__).parents[1] / 'sales-enrichment-20261014/release.py')


def manifest():
    return {'format_version': 1, 'payload_sha256': 'payload', 'credentials_included': False,
            'baseline_source_sha': r.BASELINE, 'baseline_deployed_source_sha': r.BASELINE_SOURCE,
            'baseline_frontend_version': r.BASELINE_FRONTEND, 'source_sha': '1' * 40,
            'frontend_version': r.BASELINE_FRONTEND, 'preserved': dict(r.PRESERVED),
            'database_schema_changes': False, 'production_row_changes': False,
            'static_files_unchanged': True, 'static_baseline_payload_sha256': r.STATIC_BASELINE_PAYLOAD_SHA,
            'backend_before': dict.fromkeys(r.BACKEND, None), 'backend_after': dict.fromkeys(r.BACKEND, '0' * 64),
            'changed_source_files': ['app/backend/' + name for name in r.BACKEND] + ['app/frontend/src/' + name for name in r.FRONTEND] + ['app/backend/tests/test_merchant_industries.py'],
            'files': {'backend/' + name: '0' * 64 for name in r.BACKEND} | {'static/index.html': '0' * 64}}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.helper = SimpleNamespace(static_path=legacy.static_path, sql_snapshot=legacy.sql_snapshot,
                                      run=Mock(side_effect=AssertionError('No real command allowed')))
        self.addCleanup(patch.stopall)
        patch.object(r, 'helpers', return_value=self.helper).start()

    def accepted_manifest(self, value):
        def reader(path, expected=None):
            if path == r.STATIC_BASELINE_MANIFEST:
                return json.dumps({'source_sha': r.BASELINE_SOURCE, 'frontend_version': r.BASELINE_FRONTEND, 'files': {'static/index.html': '0' * 64}}).encode()
            return json.dumps(value).encode() if path.name == 'manifest.json' else b'payload'
        with patch.object(r, 'read', side_effect=reader):
            return r.checked_manifest(self.root, SimpleNamespace(manifest_sha256='manifest', payload_sha256='payload'))

    def test_manifest_accepts_only_the_declared_no_migration_scope(self):
        value = manifest()
        self.assertEqual(self.accepted_manifest(value), value)
        self.assertEqual(b.BACKEND, r.BACKEND)
        self.assertEqual(b.FRONTEND, r.FRONTEND)
        self.assertEqual(b.PRESERVED, r.PRESERVED)

    def test_manifest_rejects_extra_source_or_payload_files(self):
        for section, name in [('changed_source_files', 'app/backend/routers/finance.py'),
                              ('changed_source_files', 'app/frontend/src/pages/PrivateWorkspace.tsx'),
                              ('changed_source_files', 'app/backend/alembic/versions/unapproved.py'),
                              ('files', 'backend/routers/finance.py'), ('files', 'static/credentials.json')]:
            with self.subTest(section=section, name=name):
                value = manifest()
                if section == 'files':
                    value[section][name] = '0' * 64
                else:
                    value[section].append(name)
                with self.assertRaises(RuntimeError):
                    self.accepted_manifest(value)

    def test_manifest_rejects_schema_row_or_boundary_changes(self):
        for key in ['credentials_included', 'database_schema_changes', 'production_row_changes']:
            value = manifest()
            value[key] = True
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.accepted_manifest(value)

    def test_backend_followup_rejects_any_changed_static_version_or_member(self):
        for mutation in ['version', 'hash', 'new_member', 'flag', 'baseline_payload']:
            value = manifest()
            if mutation == 'version':
                value['frontend_version'] = '2' * 12
            elif mutation == 'hash':
                value['files']['static/index.html'] = '1' * 64
            elif mutation == 'new_member':
                value['files']['static/offline.html'] = '0' * 64
            elif mutation == 'flag':
                value['static_files_unchanged'] = False
            else:
                value['static_baseline_payload_sha256'] = '2' * 64
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                self.accepted_manifest(value)
        for key in r.PRESERVED:
            value = manifest()
            value['preserved'][key] = False
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.accepted_manifest(value)

    def test_manifest_rejects_source_and_frontend_baseline_drift(self):
        for key in ['baseline_source_sha', 'baseline_deployed_source_sha', 'baseline_frontend_version', 'source_sha', 'frontend_version']:
            value = manifest()
            value[key] = 'unknown'
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.accepted_manifest(value)

    def database(self):
        target = self.root / 'crm.db'
        with sqlite3.connect(target) as database:
            database.executescript("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY); INSERT INTO alembic_version VALUES('e6c0b4f8a916'); CREATE TABLE payments(id INTEGER PRIMARY KEY, amount REAL); INSERT INTO payments VALUES(1,987.65); CREATE TABLE merchant_pool(id INTEGER PRIMARY KEY, industry TEXT); INSERT INTO merchant_pool VALUES(1,'餐饮'); CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY, finance_access TEXT); INSERT INTO customer_access_grants VALUES(1,'none'); CREATE INDEX ix_merchant_industry ON merchant_pool(industry);")
        return target

    def test_schema_and_business_row_digest_require_exact_equality(self):
        for sql in ["UPDATE payments SET amount=1", "UPDATE merchant_pool SET industry='餐厅'", "UPDATE customer_access_grants SET finance_access='profit'", 'DROP INDEX ix_merchant_industry', 'ALTER TABLE merchant_pool ADD COLUMN extra TEXT']:
            with self.subTest(sql=sql):
                target = self.database()
                before = r.require_schema(target)
                with sqlite3.connect(target) as database:
                    database.execute(sql)
                with self.assertRaisesRegex(RuntimeError, 'BUSINESS_SCHEMA_OR_ROWS_CHANGED'):
                    r.rows_unchanged(before, r.require_schema(target))
                target.unlink()

    def test_schema_head_must_match_existing_sales_enrichment_revision(self):
        target = self.database()
        with sqlite3.connect(target) as database:
            database.execute("UPDATE alembic_version SET version_num='wrong'")
        with self.assertRaisesRegex(RuntimeError, 'SCHEMA_HEAD_DRIFT'):
            r.require_schema(target)

    def test_owned_container_requires_all_scope_image_and_source_pins(self):
        receipt = {'candidate_image': 'sha256:' + '2' * 64}
        info = {'Image': receipt['candidate_image'], 'Config': {'Labels': {'t24.release.scope': 'merchant-industry-labels', 't24.release.source': '1' * 40}}}
        self.assertTrue(r.owned_release_container(info, receipt, {'source_sha': '1' * 40}))
        for wrong in [dict(info, Image='sha256:' + '3' * 64), dict(info, Config={'Labels': {'t24.release.scope': 'sales-enrichment', 't24.release.source': '1' * 40}}), dict(info, Config={'Labels': {'t24.release.scope': 'merchant-industry-labels', 't24.release.source': '4' * 40}})]:
            self.assertFalse(r.owned_release_container(wrong, receipt, {'source_sha': '1' * 40}))

    def test_clone_keeps_original_runtime_and_sets_only_release_identity(self):
        self.helper.clone_networks = legacy.clone_networks
        original = {'Id': 'old', 'Config': {'Image': r.BASE_IMAGE, 'Hostname': 'old', 'Env': ['UNCHANGED=1'], 'Labels': {'existing': 'kept'}}, 'HostConfig': {'NetworkMode': 'bridge', 'AutoRemove': True}, 'NetworkSettings': {'Networks': {'bridge': {'Aliases': ['old', 't24-crm'], 'IPAddress': '172.0.0.5', 'EndpointID': 'server-assigned'}}}}
        before = copy.deepcopy(original)
        cloned = r.clone_config('new-image', original, 'new-source')
        self.assertEqual(original, before)
        self.assertEqual(cloned['Env'], ['UNCHANGED=1'])
        self.assertEqual(cloned['Labels']['existing'], 'kept')
        self.assertEqual(cloned['Labels']['t24.release.scope'], 'merchant-industry-labels')
        self.assertEqual(cloned['NetworkingConfig'], {'EndpointsConfig': {'bridge': {'Aliases': ['t24-crm']}}})

    def test_nginx_reload_failure_restores_original_configuration(self):
        nginx = self.root / 'nginx'
        nginx.write_bytes(b'original')
        patch.object(r, 'NGINX', nginx).start()
        reload = Mock(side_effect=[RuntimeError('TEST_RELOAD_FAILED'), None])
        with patch.object(r, 'reload_nginx', reload):
            with self.assertRaisesRegex(RuntimeError, 'TEST_RELOAD_FAILED'):
                r.swap_nginx(b'original', b'candidate')
        self.assertEqual(nginx.read_bytes(), b'original')
        self.assertEqual(reload.call_count, 2)

    def test_rollback_still_restores_crm_when_nginx_recovery_fails(self):
        self.helper.inspect_optional = Mock(return_value={'Id': 'candidate', 'Image': 'new'})
        self.helper.inspect = Mock(return_value={'Name': '/t24-crm-before-release'})
        self.helper.run = Mock(return_value=b'')
        self.helper.ready = Mock()
        self.helper.private_boundary = Mock()
        self.helper.write = Mock()
        patch.object(r, 'cleanup_nginx_temp', side_effect=RuntimeError('TEMP_UNKNOWN')).start()
        patch.object(r, 'require_schema', return_value={}).start()
        patch.object(r, 'recovery_original', return_value={}).start()
        patch.object(r, 'owned_release_container', return_value=True).start()
        with self.assertRaisesRegex(RuntimeError, 'ROLLBACK_INCOMPLETE'):
            r.rollback(self.root, {}, {'source_sha': '1' * 40}, {}, b'old', b'new', 'TEST')
        self.assertIn((['docker', 'start', r.OLD_ID], 'ROLLBACK_START_FAILED'), [call.args for call in self.helper.run.call_args_list])
        receipt = self.helper.write.call_args.args[1]
        self.assertFalse(receipt['database_restored'])
        self.assertEqual(receipt['restored_crm_id'], r.OLD_ID)

    def test_rollback_rejects_an_unowned_active_container(self):
        nginx = self.root / 'nginx'
        nginx.write_bytes(b'old')
        patch.object(r, 'NGINX', nginx).start()
        patch.object(r, 'cleanup_nginx_temp').start()
        patch.object(r, 'reload_nginx').start()
        patch.object(r, 'require_schema', return_value={}).start()
        patch.object(r, 'recovery_original', return_value={}).start()
        self.helper.inspect_optional = Mock(return_value={'Id': 'unknown', 'Image': 'other', 'Config': {'Labels': {}}})
        self.helper.private_boundary = Mock()
        self.helper.write = Mock()
        with self.assertRaisesRegex(RuntimeError, 'ROLLBACK_INCOMPLETE'):
            r.rollback(self.root, {'candidate_image': 'new'}, {'source_sha': '1' * 40}, {}, b'old', b'new', 'TEST')
        self.helper.run.assert_not_called()

    def test_extract_rejects_duplicate_archive_members(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for _ in range(2):
                item = tarfile.TarInfo('backend/routers/merchant_pool.py')
                item.size = 4
                archive.addfile(item, io.BytesIO(b'code'))
        self.helper.write = Mock()
        with patch.object(r, 'read', return_value=buffer.getvalue()):
            with self.assertRaisesRegex(RuntimeError, 'PAYLOAD_MEMBER_REJECTED'):
                r.extract(self.root, {'files': {'backend/routers/merchant_pool.py': r.H(b'code')}})
        self.assertEqual(self.helper.write.call_count, 1)


if __name__ == '__main__':
    unittest.main()
