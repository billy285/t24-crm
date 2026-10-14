"""Read-only local static release guard tests; no Docker/server/network actions."""
import copy
import importlib.util
import io
import json
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


r = load('sales_controls_release', Path(__file__).with_name('release.py'))
b = load('sales_controls_payload', Path(__file__).with_name('build_payload.py'))
legacy = load('read_only_legacy_primitives', Path(__file__).parents[1] / 'sales-enrichment-20261014/release.py')


def manifest():
    return {'format_version': 1, 'source_sha': '1' * 40, 'frontend_version': '2' * 12,
            'baseline_source_sha': r.BASELINE, 'baseline_deployed_source_sha': r.BASELINE_SOURCE,
            'baseline_frontend_version': r.BASELINE_FRONTEND, 'payload_sha256': 'payload',
            'runtime_guard': 'complete_mount_record_order_only',
            'retry_of_release': 'sales-note-templates-f96eaa209f2d-20261014',
            'preserved': dict(r.PRESERVED), 'static_only': True, 'credentials_included': False,
            'database_schema_changes': False, 'production_row_changes': False, 'backend_changes': False,
            'services_modified': False, 'environment_modified': False,
            'backend_before': {}, 'backend_after': {},
            'changed_source_files': ['app/frontend/src/' + name for name in r.FRONTEND] + ['app/frontend/tests/sales-note-templates-retry.spec.ts'],
            'protected_source_inventory': {'app/backend/routers/finance.py': '0' * 64,
                                           'app/frontend/src/pages/PrivateWorkspace.tsx': '0' * 64},
            'files': {'static/index.html': '0' * 64, 'static/app-version.json': '0' * 64}}


def db_snapshot():
    return {label: {'identity': {'device': 1, 'inode': 2}, 'schema_objects': {'table': {'type': 'table'}},
                   'schema_sha256': r.H(json.dumps({'table': {'type': 'table'}}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()), 'tables': {'table': {'columns_sha256': '4' * 64,
                                                               'rows': 1, 'rows_sha256': '5' * 64}}}
            for label in ('business', 'private')}


class StaticReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.helper = SimpleNamespace(static_path=legacy.static_path, digest=legacy.digest,
                                      clone_networks=legacy.clone_networks,
                                      run=Mock(side_effect=AssertionError('No real commands allowed')),
                                      write=Mock(return_value='a' * 64))
        self.addCleanup(patch.stopall)
        patch.object(r, 'helpers', return_value=self.helper).start()

    def check_manifest(self, value):
        with patch.object(r, 'read', side_effect=lambda path, expected=None: json.dumps(value).encode() if path.name == 'manifest.json' else b'payload'):
            return r.checked_manifest(self.root, SimpleNamespace(manifest_sha256='manifest', payload_sha256='payload'))

    def test_exact_static_scope_accepted_and_builder_matches(self):
        value = manifest()
        self.assertEqual(self.check_manifest(value), value)
        self.assertEqual(b.FRONTEND, r.FRONTEND)
        self.assertEqual(b.BACKEND, set())
        self.assertEqual(b.PRESERVED, r.PRESERVED)

    def test_no_backend_service_database_or_environment_change_can_be_declared(self):
        for flag in ('credentials_included', 'database_schema_changes', 'production_row_changes', 'backend_changes', 'services_modified', 'environment_modified'):
            value = manifest()
            value[flag] = True
            with self.subTest(flag=flag), self.assertRaises(RuntimeError):
                self.check_manifest(value)
        value = manifest()
        value['static_only'] = False
        with self.assertRaises(RuntimeError):
            self.check_manifest(value)

    def test_backend_payload_or_unapproved_source_is_rejected(self):
        for name in ['backend/routers/sales_leads.py', 'static/secrets.json', 'static/../index.html']:
            value = manifest()
            value['files'][name] = '0' * 64
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.check_manifest(value)
        for name in ['app/backend/tests/test_unapproved.py', 'app/frontend/src/pages/Finance.tsx', 'app/frontend/src/pages/PrivateWorkspace.tsx']:
            value = manifest()
            value['changed_source_files'].append(name)
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.check_manifest(value)

    def test_old_frontend_version_and_scope_protection_loss_are_rejected(self):
        value = manifest()
        value['frontend_version'] = r.BASELINE_FRONTEND
        with self.assertRaises(RuntimeError):
            self.check_manifest(value)
        for key in r.PRESERVED:
            value = manifest()
            value['preserved'][key] = False
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.check_manifest(value)

    def test_legitimate_business_rows_do_not_change_the_identity_and_schema_boundary(self):
        before = db_snapshot()
        after = copy.deepcopy(before)
        after['business']['tables']['table'].update(rows=900, rows_sha256='6' * 64)
        after['private']['tables']['table'].update(rows=12, rows_sha256='7' * 64)
        self.assertEqual(r.stable_databases(before), r.stable_databases(after))

    def test_compact_receipt_keeps_verified_schema_and_columns_without_sql_text(self):
        snapshot = db_snapshot()
        result = r.stable_databases(snapshot)
        for label in ('business', 'private'):
            self.assertNotIn('schema_objects', result[label])
            self.assertEqual(result[label]['schema_object_count'], 1)
            self.assertEqual(result[label]['schema_sha256'], snapshot[label]['schema_sha256'])
            self.assertEqual(result[label]['columns'], {'table': '4' * 64})
        snapshot['business']['schema_sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'DATABASE_SCHEMA_PROOF_HASH_DRIFT'):
            r.stable_databases(snapshot)

    def test_database_schema_columns_or_file_identity_change_is_detected(self):
        before = db_snapshot()
        for field in ('identity', 'schema_objects', 'schema_sha256', 'columns'):
            after = copy.deepcopy(before)
            if field == 'identity':
                after['business'][field]['inode'] = 99
            elif field == 'schema_objects':
                after['private'][field]['new_table'] = {'type': 'table'}
            elif field == 'columns':
                after['business']['tables']['table']['columns_sha256'] = '9' * 64
            else:
                after['private'][field] = '8' * 64
            with self.subTest(field=field):
                try:
                    changed = r.stable_databases(after)
                except RuntimeError:
                    continue
                self.assertNotEqual(r.stable_databases(before), changed)

    def test_boundary_rejects_current_crm_restart_or_configuration_drift(self):
        self.helper.private_boundary = Mock(return_value=(None, None, SimpleNamespace(PRIVATE_DB='private', BUSINESS='business'), SimpleNamespace(release_snapshot=lambda *args: db_snapshot()), None))
        self.helper.inspect = Mock(return_value={'State': {'Running': True}})
        patch.object(r, 'BASE_CRM', {**r.BASE_CRM, 'config': '0' * 64}).start()
        for field in ('id', 'image', 'started', 'restart', 'config'):
            changed = dict(r.BASE_CRM)
            changed[field] = 'drift'
            with patch.object(r, 'runtime', return_value=changed):
                with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'CRM_RUNTIME_MUST_REMAIN_IDENTICAL'):
                    r.boundary({})
        self.helper.run.assert_not_called()

    def raw_container(self):
        return {'Id': 'synthetic-only', 'Image': 'sha256:' + '1' * 64,
                'State': {'StartedAt': 'synthetic-start', 'Running': True}, 'RestartCount': 0,
                'Config': {'Env': ['SYNTHETIC_A=1', 'SYNTHETIC_B=2'], 'Cmd': ['server', '--serve']},
                'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}},
                'Mounts': [{'Type': 'bind', 'Source': '/synthetic/data', 'Destination': '/data',
                            'Mode': 'rw', 'RW': True, 'Propagation': 'rprivate'},
                           {'Type': 'bind', 'Source': '/synthetic/logs', 'Destination': '/logs',
                            'Mode': 'rw', 'RW': True, 'Propagation': 'rprivate'}],
                'NetworkSettings': {'Networks': {'bridge': {'Aliases': ['crm', 'app']}}}}

    def test_mount_order_only_is_accepted_and_legacy_false_reject_is_reproduced(self):
        original = self.raw_container()
        changed = copy.deepcopy(original)
        changed['Mounts'].reverse()
        self.assertNotEqual(legacy.runtime(original), legacy.runtime(changed))
        self.assertEqual(r.runtime(original), r.runtime(changed))
        self.assertEqual(original['Mounts'][0]['Destination'], '/data')

    def test_actual_mount_property_or_duplicate_count_change_is_rejected(self):
        original = self.raw_container()
        for field, value in [('Source', '/synthetic/other'), ('Destination', '/other'),
                             ('Type', 'volume'), ('Mode', 'ro'), ('RW', False),
                             ('Propagation', 'shared'), ('NewProperty', 'preserved')]:
            changed = copy.deepcopy(original)
            changed['Mounts'][0][field] = value
            with self.subTest(field=field):
                self.assertNotEqual(r.runtime(original), r.runtime(changed))
        changed = copy.deepcopy(original)
        changed['Mounts'].append(copy.deepcopy(changed['Mounts'][0]))
        self.assertNotEqual(r.runtime(original), r.runtime(changed))
        reordered = copy.deepcopy(changed)
        reordered['Mounts'].reverse()
        self.assertEqual(r.runtime(changed), r.runtime(reordered))
        del changed['Mounts'][0]['Mode']
        self.assertNotEqual(r.runtime(original), r.runtime(changed))

    def test_env_cmd_network_and_identity_order_or_values_remain_exact(self):
        original = self.raw_container()
        for section in ('Env', 'Cmd'):
            changed = copy.deepcopy(original)
            changed['Config'][section].reverse()
            with self.subTest(section=section):
                self.assertNotEqual(r.runtime(original), r.runtime(changed))
        changed = copy.deepcopy(original)
        changed['NetworkSettings']['Networks']['bridge']['Aliases'].reverse()
        self.assertNotEqual(r.runtime(original), r.runtime(changed))
        changed = copy.deepcopy(original)
        changed['HostConfig']['RestartPolicy']['Name'] = 'no'
        self.assertNotEqual(r.runtime(original), r.runtime(changed))
        for field in ('Id', 'Image', 'RestartCount'):
            changed = copy.deepcopy(original)
            changed[field] = 'different'
            self.assertNotEqual(r.runtime(original), r.runtime(changed))

    def test_wrong_mount_record_shape_rejected(self):
        for mounts in ({}, ['invalid'], None):
            original = self.raw_container()
            original['Mounts'] = mounts
            with self.assertRaisesRegex(RuntimeError, 'COMPLETE_MOUNT_RECORDS_REQUIRED'):
                r.runtime(original)

    def runtime(self):
        public = self.root / 'public'
        public.mkdir()
        version = json.dumps({'version': '2' * 12}).encode()
        (public / 'app-version.json').write_bytes(version)
        (public / 'index.html').write_bytes(b'new-html')
        value = manifest()
        value['files'] = {'static/app-version.json': r.H(version), 'static/index.html': r.H(b'new-html')}
        receipt = {'boundary': {'crm': dict(r.BASE_CRM), 'databases': {}}, 'public_root': str(public)}
        original, updated = b'old-root', b'new-root'
        nginx = self.root / 'nginx'
        nginx.write_bytes(original)
        patch.object(r, 'NGINX', nginx).start()
        patch.object(r, 'prepared_receipt', return_value=receipt).start()
        patch.object(r, 'boundary', return_value=receipt['boundary']).start()
        patch.object(r, 'next_nginx', return_value=(original, updated)).start()
        patch.object(r, 'reload_nginx').start()
        patch.object(r, 'public_check').start()
        self.helper.run = Mock(return_value=b'')
        args = SimpleNamespace(review_sha256='review')
        return value, receipt, original, updated, nginx, args

    def test_activation_only_changes_static_root_without_docker_or_database_commands(self):
        value, receipt, original, updated, nginx, args = self.runtime()
        r.activate(self.root, args, value, {})
        self.assertEqual(nginx.read_bytes(), updated)
        self.assertEqual([call.args[0] for call in self.helper.run.call_args_list], [['curl', '-fsS', 'https://t24-crm.com/ready']])
        result = self.helper.write.call_args.args[1]
        self.assertTrue(result['deployed'])
        self.assertFalse(result['services_modified'])
        self.assertFalse(result['database_restored'])

    def test_post_public_failure_restores_only_static_root(self):
        value, receipt, original, updated, nginx, args = self.runtime()
        patch.object(r, 'public_check', side_effect=RuntimeError('PUBLIC_FAILED')).start()
        with self.assertRaisesRegex(RuntimeError, 'PUBLIC_FAILED'):
            r.activate(self.root, args, value, {})
        self.assertEqual(nginx.read_bytes(), original)
        result = self.helper.write.call_args.args[1]
        self.assertEqual(result['stage'], 'SALES_NOTE_TEMPLATES_RETRY_ROLLED_BACK')
        self.assertFalse(result['database_restored'])
        self.assertFalse(result['services_modified'])

    def test_concurrent_nginx_change_is_never_overwritten_by_rollback(self):
        value, receipt, original, updated, nginx, args = self.runtime()
        def concurrent(*args):
            nginx.write_bytes(b'another-release-root')
            raise RuntimeError('PUBLIC_FAILED')
        patch.object(r, 'public_check', side_effect=concurrent).start()
        with self.assertRaisesRegex(RuntimeError, 'STATIC_ROLLBACK_INCOMPLETE'):
            r.activate(self.root, args, value, {})
        self.assertEqual(nginx.read_bytes(), b'another-release-root')
        self.assertIn('NGINX_ROLLBACK_NGINX_DRIFT', self.helper.write.call_args.args[1]['failures'])

    def test_boundary_drift_before_activation_leaves_public_root_unchanged(self):
        value, receipt, original, updated, nginx, args = self.runtime()
        patch.object(r, 'boundary', return_value={'crm': 'changed'}).start()
        with self.assertRaisesRegex(RuntimeError, 'RUNTIME_OR_DATABASE_SCHEMA_CHANGED'):
            r.activate(self.root, args, value, {})
        self.assertEqual(nginx.read_bytes(), original)
        self.helper.run.assert_not_called()
        self.helper.write.assert_not_called()

    def test_duplicate_tar_member_is_rejected_before_second_write(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for _ in range(2):
                item = tarfile.TarInfo('static/index.html')
                item.size = 4
                archive.addfile(item, io.BytesIO(b'html'))
        with patch.object(r, 'read', return_value=buffer.getvalue()):
            with self.assertRaisesRegex(RuntimeError, 'PAYLOAD_MEMBER_REJECTED'):
                r.extract(self.root, {'files': {'static/index.html': r.H(b'html')}})
        self.assertEqual(self.helper.write.call_count, 1)


if __name__ == '__main__':
    unittest.main()
