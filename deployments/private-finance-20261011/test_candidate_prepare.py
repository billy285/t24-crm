"""Candidate preparation boundaries with synthetic files and mocked Docker only."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import candidate_prepare as candidate


class CandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.root.chmod(0o700)
        self.files = {'backend/services/private_workspace.py': b'private module',
                      'backend/tests/conftest.py': b'fixture',
                      'backend/tests/test_private_candidate.py': b'regression',
                      'frontend/dist/index.html': b'complete build',
                      'frontend/dist/assets/app-abc123.js': b'build script'}
        delta = {'app/backend/services/private_workspace.py': candidate.sha(b'private module')}
        dist = {name.removeprefix('frontend/dist/'): candidate.sha(blob)
                for name, blob in self.files.items() if name.startswith('frontend/')}
        self.frozen = {'source_sha': 'a' * 40, 'frontend_version': '123456abcdef',
                       'backend_delta_sha256': delta, 'frontend_dist_sha256': dist,
                       'dependency_file_sha256': {'app/backend/requirements.txt': 'b' * 64},
                       'backend_regression_tests_minimum': 5}
        self.manifest = {'format_version': 1, 'stage': 'PRIVATE_FINANCE_PAYLOAD_PREPARED',
            'source_sha': self.frozen['source_sha'], 'frontend_version': self.frozen['frontend_version'],
            'base_private_image': candidate.builder.BASE_IMAGE,
            'baseline_private_source_sha': candidate.builder.BASE_SOURCE,
            'payload_sha256': 'c' * 64, 'runtime_dependency_changes': False, 'credentials_included': False,
            'production_access': False, 'deployed': False,
            'payload_files': {name: candidate.sha(blob) for name, blob in self.files.items()},
            'backend_changes': list(delta),
            'source_file_sha256': {'app/' + name: candidate.sha(blob) for name, blob in self.files.items() if name.startswith('backend/')},
            'private_tests': ['app/backend/tests/conftest.py', 'app/backend/tests/test_private_candidate.py'],
            'runtime_dependency_file_sha256': self.frozen['dependency_file_sha256'],
            'backend_regression_tests_expected_minimum': 5}

    def archive(self, entries=None):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, data, kind in entries or [('payload/' + name, blob, tarfile.REGTYPE) for name, blob in self.files.items()]:
                member = tarfile.TarInfo(name); member.type = kind; member.size = len(data)
                if kind == tarfile.SYMTYPE: member.linkname = '/etc/passwd'; member.size = 0
                archive.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        return output.getvalue()

    def test_frozen_exact_scope_and_complete_inventory(self):
        self.assertEqual(candidate.checked_payload(self.manifest, self.frozen, 'c' * 64), self.manifest)
        for field, value in [('deployed', True), ('production_access', True), ('payload_sha256', 'd' * 64)]:
            damaged = deepcopy(self.manifest); damaged[field] = value
            with self.subTest(field=field), self.assertRaises(candidate.PrepareError):
                candidate.checked_payload(damaged, self.frozen, 'c' * 64)

    def test_missing_or_customer_backend_injection_rejected(self):
        for name in ('backend/services/customer_finance.py', 'backend/.env', 'frontend/dist/../.env'):
            damaged = deepcopy(self.manifest); damaged['payload_files'][name] = 'a' * 64
            with self.subTest(name=name), self.assertRaises(candidate.PrepareError):
                candidate.checked_payload(damaged, self.frozen, 'c' * 64)
        damaged = deepcopy(self.manifest); damaged['private_tests'].remove('app/backend/tests/conftest.py')
        with self.assertRaisesRegex(candidate.PrepareError, 'ALL_PRIVATE_TESTS_REQUIRED'):
            candidate.checked_payload(damaged, self.frozen, 'c' * 64)

    def test_safe_archive_is_exact_and_files_private(self):
        extracted = candidate.extract(self.archive(), self.manifest, self.root / 'payload')
        self.assertEqual(extracted, self.manifest['payload_files'])
        self.assertTrue(all((self.root / 'payload' / name).stat().st_mode & 0o777 == 0o600 for name in self.files))

    def test_archive_traversal_symlink_duplicate_unlisted_rejected(self):
        first = next(iter(self.files.items()))
        for name, kind in [('payload/../../escape', tarfile.REGTYPE), ('payload/backend/.env', tarfile.REGTYPE),
                           ('payload/backend/alias.py', tarfile.SYMTYPE), ('/payload/backend/foo.py', tarfile.REGTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=self.root) as tmp:
                with self.assertRaisesRegex(candidate.PrepareError, 'REGULAR_ALLOWLISTED_ARCHIVE_ONLY'):
                    candidate.extract(self.archive([(name, b'bad', kind)]), self.manifest, Path(tmp) / 'payload')
        duplicate = [('payload/' + first[0], first[1], tarfile.REGTYPE)] * 2
        with self.assertRaisesRegex(candidate.PrepareError, 'REGULAR_ALLOWLISTED_ARCHIVE_ONLY'):
            candidate.extract(self.archive(duplicate), self.manifest, self.root / 'duplicate')

    def test_archive_hash_mismatch_and_missing_member_rejected(self):
        name = next(iter(self.files))
        with self.assertRaisesRegex(candidate.PrepareError, 'PAYLOAD_MEMBER_HASH_DRIFT'):
            candidate.extract(self.archive([('payload/' + name, b'wrong', tarfile.REGTYPE)]), self.manifest, self.root / 'wrong')
        with self.assertRaisesRegex(candidate.PrepareError, 'PAYLOAD_INCOMPLETE'):
            candidate.extract(self.archive([('payload/' + name, self.files[name], tarfile.REGTYPE)]), self.manifest, self.root / 'missing')

    def test_frozen_hash_private_mode_and_symlink_rejected(self):
        path = self.root / 'baseline.json'; path.write_bytes(b'frozen'); path.chmod(0o600)
        self.assertEqual(candidate.frozen_file(path, candidate.sha(b'frozen')), b'frozen')
        with self.assertRaisesRegex(candidate.PrepareError, 'FROZEN_FILE_HASH_DRIFT'): candidate.frozen_file(path, 'a' * 64)
        path.chmod(0o644)
        with self.assertRaisesRegex(candidate.PrepareError, 'PROTECTED_OWNER_MODE_REQUIRED'): candidate.frozen_file(path, candidate.sha(b'frozen'))
        alias = self.root / 'alias'; alias.symlink_to(path)
        with self.assertRaises(candidate.PrepareError): candidate.frozen_file(alias, candidate.sha(b'frozen'))

    def test_recipe_pins_existing_private_image_and_complete_private_delta(self):
        tag = 't24-private-finance-base:' + self.frozen['source_sha'][:12] + '-' + 'b' * 12
        recipe = candidate.recipe(self.manifest, tag).decode()
        self.assertTrue(recipe.startswith('FROM ' + tag + '\n'))
        self.assertIn('COPY backend/tests/test_private_candidate.py /app/backend/tests/test_private_candidate.py', recipe)
        self.assertIn('COPY frontend/dist/ /app/frontend/dist/', recipe)
        self.assertNotIn('RUN ', recipe); self.assertNotIn('ENV ', recipe); self.assertNotIn('latest', recipe)
        with self.assertRaisesRegex(candidate.PrepareError, 'EXCLUSIVE_REVIEWED_BASE_TAG_REQUIRED'):
            candidate.recipe(self.manifest, candidate.builder.BASE_IMAGE)

    def test_base_runtime_preserves_actual_python_and_three_installed_versions(self):
        runtime = {'python': '3.10.22', 'packages': {**candidate.BASE_PACKAGE_VERSIONS,
                   **{name: None for name in candidate.WHEEL_VERSIONS}}}
        self.assertEqual(candidate.checked_base_runtime(runtime), runtime)
        for name, version in [('tomli', '2.2.1'), ('exceptiongroup', '1.3.0'), ('packaging', '26.2'), ('pytest', '8.4.2')]:
            changed = deepcopy(runtime); changed['packages'][name] = version
            with self.subTest(name=name), self.assertRaisesRegex(candidate.PrepareError, 'RETAINED_BASE_PYTHON_OR_TEST_TOOLS_DRIFT'):
                candidate.checked_base_runtime(changed)
        changed = deepcopy(runtime); changed['python'] = '3.12.0'
        with self.assertRaises(candidate.PrepareError): candidate.checked_base_runtime(changed)

    def test_retained_manifest_hash_is_independent_fixed_evidence(self):
        with mock.patch.object(candidate.live, 'preflight') as preflight, mock.patch.object(candidate.os, 'umask'):
            with self.assertRaisesRegex(candidate.PrepareError, 'EXACT_RETAINED_TEST_WHEEL_MANIFEST_HASH_REQUIRED'):
                candidate.main(SimpleNamespace(test_wheel_manifest_sha256='a' * 64))
            preflight.assert_not_called()

    def test_offline_loaded_test_tools_cover_nine_without_downgrading_base(self):
        versions = {**candidate.BASE_PACKAGE_VERSIONS, **candidate.WHEEL_VERSIONS}
        code = compile(candidate.VERIFY_LOADED_TEST_TOOLS, '<synthetic-tools>', 'exec')
        with mock.patch('platform.python_version', return_value='3.10.22'), mock.patch('importlib.metadata.version', side_effect=versions.__getitem__), redirect_stdout(io.StringIO()) as output:
            exec(code, {})
        report = json.loads(output.getvalue()); self.assertEqual(report['test_tool_versions'], versions)
        self.assertEqual(versions['tomli'], '2.5.0'); self.assertEqual(versions['exceptiongroup'], '1.3.1')
        with mock.patch('platform.python_version', return_value='3.10.22'), mock.patch('importlib.metadata.version', return_value='downgraded'):
            with self.assertRaises(AssertionError): exec(code, {})

    def test_base_pin_uses_new_local_tag_and_inspects_actual_image(self):
        runner = candidate.Runner(self.root)
        with mock.patch.object(candidate, 'uuid4', return_value=SimpleNamespace(hex='b' * 32)), mock.patch.object(candidate.subprocess, 'run', return_value=SimpleNamespace(returncode=1)), mock.patch.object(runner, 'run', side_effect=[b'', (candidate.builder.BASE_IMAGE+'\n').encode()]) as run:
            tag = candidate.pin_base_image(runner, self.frozen['source_sha'])
        self.assertEqual(run.call_args_list[0].args[1], ['docker','tag',candidate.builder.BASE_IMAGE,tag])
        self.assertEqual(run.call_args_list[1].args[1], ['docker','image','inspect','-f','{{.Id}}',tag])
        self.assertEqual(candidate.recipe(self.manifest,tag).decode().splitlines()[0], 'FROM ' + tag)

    def test_base_tag_collision_or_drift_cannot_build_or_replace_a_tag(self):
        runner = candidate.Runner(self.root)
        with mock.patch.object(candidate.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), mock.patch.object(runner, 'run') as run:
            with self.assertRaisesRegex(candidate.PrepareError, 'NEW_EXCLUSIVE_BASE_IMAGE_TAG_REQUIRED'):
                candidate.pin_base_image(runner, self.frozen['source_sha'])
            run.assert_not_called()
        with mock.patch.object(candidate.subprocess, 'run', return_value=SimpleNamespace(returncode=1)), mock.patch.object(runner, 'run', side_effect=[b'', b'sha256:wrong\n']):
            with self.assertRaisesRegex(candidate.PrepareError, 'PRIVATE_BASE_PIN_DRIFT'):
                candidate.pin_base_image(runner, self.frozen['source_sha'])

    def test_candidate_layer_proof_requires_exact_retained_base_ancestry(self):
        base = {'RootFS': {'Layers': ['sha256:one','sha256:two']}}
        candidate.verify_candidate_base(base, {'RootFS': {'Layers': ['sha256:one','sha256:two','sha256:new']}})
        for layers in ([], ['sha256:one','sha256:two'], ['sha256:other','sha256:two','sha256:new']):
            with self.assertRaisesRegex(candidate.PrepareError, 'CANDIDATE_RETAINED_BASE_LAYER_DRIFT'):
                candidate.verify_candidate_base(base, {'RootFS': {'Layers': layers}})

    def test_expected_backend_preserves_every_unrelated_byte(self):
        base = {'services/private_workspace.py': 'old', 'services/customer_finance.py': 'finance', 'requirements.txt': 'dependencies'}
        expected = candidate.expected_backend(base, self.manifest)
        self.assertEqual(expected['services/customer_finance.py'], 'finance')
        self.assertEqual(expected['requirements.txt'], 'dependencies')
        self.assertEqual(expected['services/private_workspace.py'], candidate.sha(b'private module'))
        self.assertNotEqual({**expected, 'requirements.txt': 'changed'}, expected)

    def test_static_build_preserves_old_hash_urls_and_rejects_reused_changed_bytes(self):
        base = {'assets/old-111.js': 'old', 'index.html': 'previous'}
        expected = candidate.expected_dist(base, self.manifest)
        self.assertEqual(expected['assets/old-111.js'], 'old')
        self.assertEqual(expected['index.html'], candidate.sha(b'complete build'))
        with self.assertRaisesRegex(candidate.PrepareError, 'EXISTING_STATIC_ASSET_HASH_COLLISION'):
            candidate.expected_dist({'assets/app-abc123.js': 'old-different'}, self.manifest)

    def test_junit_requires_minimum_count_and_zero_skips_or_failures(self):
        xml = b'<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0"><testcase/><testcase/></testsuite></testsuites>'
        self.assertEqual(candidate.test_report(xml, 2), 2)
        for bad, minimum in [(xml, 3), (xml.replace(b'skipped="0"', b'skipped="1"'), 2),
                             (xml.replace(b'<testcase/>', b'<testcase><failure/></testcase>', 1), 2),
                             (xml.replace(b'<testcase/>', b'', 1), 2)]:
            with self.assertRaisesRegex(candidate.PrepareError, 'COMPLETE_CANDIDATE_REGRESSIONS_REQUIRED'): candidate.test_report(bad, minimum)

    def test_wheels_exact_hash_version_inventory_and_immutable_modes(self):
        wheels = self.root / 'wheels'; wheels.mkdir(mode=0o700); inventory = {}
        for package, version in candidate.WHEEL_VERSIONS.items():
            path = wheels / (package.replace('-', '_') + '-' + version + '-py3-none-any.whl')
            path.write_bytes(package.encode()); path.chmod(0o644); inventory[path.name] = candidate.sha(path.read_bytes())
        self.assertEqual(len(candidate.wheel_tools(wheels, inventory)), 6)
        path.chmod(0o666)
        with self.assertRaisesRegex(candidate.PrepareError, 'IMMUTABLE_TEST_WHEEL_REQUIRED'): candidate.wheel_tools(wheels, inventory)
        path.chmod(0o600); path.write_bytes(b'drift')
        with self.assertRaisesRegex(candidate.PrepareError, 'TEST_WHEEL_INVENTORY_DRIFT'): candidate.wheel_tools(wheels, inventory)

    def test_missing_sixth_wheel_or_unneeded_base_package_wheel_is_rejected(self):
        wheels = self.root / 'six-wheels'; wheels.mkdir(mode=0o700); inventory = {}
        for package, version in candidate.WHEEL_VERSIONS.items():
            path = wheels / (package.replace('-', '_') + '-' + version + '-py3-none-any.whl')
            path.write_bytes(package.encode()); path.chmod(0o600); inventory[path.name] = candidate.sha(path.read_bytes())
        path.unlink(); incomplete = {name: value for name,value in inventory.items() if name != path.name}
        with self.assertRaisesRegex(candidate.PrepareError, 'TEST_WHEEL_INVENTORY_DRIFT'): candidate.wheel_tools(wheels,incomplete)
        path.write_bytes(b'missing restored'); path.chmod(0o600); inventory[path.name] = candidate.sha(path.read_bytes())
        unneeded = wheels/'tomli-2.2.1-py3-none-any.whl'; unneeded.write_bytes(b'forbidden downgrade'); unneeded.chmod(0o600)
        inventory[unneeded.name] = candidate.sha(unneeded.read_bytes())
        with self.assertRaisesRegex(candidate.PrepareError, 'ONLY_PINNED_TEST_TOOLS_ALLOWED'): candidate.wheel_tools(wheels,inventory)

    def test_isolated_containers_have_no_network_credentials_live_data_or_ports(self):
        runner = candidate.Runner(self.root); synthetic = self.root / 'synthetic'; synthetic.mkdir(mode=0o700)
        with mock.patch.object(runner, 'run', return_value=b'{}') as run, mock.patch.object(candidate.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            runner.isolated('synthetic', candidate.builder.BASE_IMAGE, "print('{}')", mounts=[(synthetic, '/synthetic', False)])
        command = run.call_args.args[1]
        self.assertEqual(command[command.index('--network') + 1], 'none')
        self.assertIn('--read-only', command); self.assertIn('ALL', command)
        self.assertIn('--pids-limit', command); self.assertNotIn('--env-file', command); self.assertNotIn('--publish', command)
        self.assertFalse(any('/opt/t24-crm/app/data' in arg or 'runtime.env' in arg for arg in command))
        self.assertFalse(any(arg.startswith('OPENAI_API_KEY=') or arg.startswith('PLAID_SECRET=') for arg in command))
        self.assertIn('PRIVATE_WORKSPACE_PLAID_ENABLED=false', command)

    def test_isolation_rejects_live_mount_and_mutable_image(self):
        runner = candidate.Runner(self.root)
        with mock.patch.object(runner, 'run'), mock.patch.object(candidate.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(candidate.PrepareError, 'IMMUTABLE_IMAGE_REQUIRED'): runner.isolated('bad', 'image:latest', '')
            outside = self.root.parent / ('outside-' + self.root.name); outside.mkdir(mode=0o700); self.addCleanup(outside.rmdir)
            with self.assertRaisesRegex(candidate.PrepareError, 'SYNTHETIC_OR_TEST_MOUNT_ONLY'):
                runner.isolated('bad', candidate.builder.BASE_IMAGE, '', mounts=[(outside, '/synthetic', True)])

    def test_cleanup_cannot_remove_unrelated_container(self):
        runner = candidate.Runner(self.root)
        found = SimpleNamespace(returncode=0, stdout=json.dumps([{'Image': candidate.builder.BASE_IMAGE, 'Config': {'Labels': {}}}]).encode())
        with mock.patch.object(runner, 'run', return_value=b'{}'), mock.patch.object(candidate.subprocess, 'run', return_value=found) as processes:
            with self.assertRaisesRegex(candidate.PrepareError, 'OWN_TEST_CONTAINER_CLEANUP_IDENTITY_REQUIRED'):
                runner.isolated('check', candidate.builder.BASE_IMAGE, '')
            self.assertFalse(any(call.args[0][:3] == ['docker', 'rm', '-f'] for call in processes.call_args_list))

    def test_schema_recipe_only_synthetic_storage_and_old_image_read_compatibility(self):
        self.assertEqual(len(candidate.TARGET_TABLES), 10)
        self.assertEqual(len(candidate.guard.BASE_TABLES), 4)
        for script in (candidate.FIXTURE_BASE, candidate.EMPTY_SCHEMA, candidate.INIT_MIGRATION, candidate.ROLLBACK_READ):
            self.assertNotIn('/opt/t24-crm', script); self.assertNotIn('runtime.env', script)
            compile(script, '<synthetic-candidate-check>', 'exec')
        self.assertIn('PrivateWorkspaceBase.metadata.create_all', candidate.FIXTURE_BASE)
        self.assertIn('decrypt_credentials', candidate.ROLLBACK_READ)
        self.assertNotIn('main', candidate.INIT_MIGRATION)


if __name__ == '__main__': unittest.main()
