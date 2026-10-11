"""Prove the frozen Stripe carrier scope using synthetic Git and read-only source inventories."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

BASE_SOURCE = '3c5b8c1d63b8f078e162e228750b508715699479'
SOURCE_SHA = 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
FRONTEND_VERSION = '913856b4d17b'
FROZEN_MANIFEST_SHA = '9ea752806526eba6d99d5f9df34b402cf3856a3763a875ea2e284725e8635357'
BACKEND_CHANGES = frozenset('app/backend/' + path for path in (
    'models/private_workspace.py', 'routers/private_workspace.py', 'schemas/private_workspace.py',
    'services/private_stripe_report_provider.py', 'services/private_stripe_report_service.py',
    'services/private_workspace_providers.py', 'tests/test_private_stripe_report_provider.py',
    'tests/test_private_stripe_report_service.py', 'tests/test_private_workspace_core.py'))
DEPENDENCY_PATHS = ('app/Dockerfile', 'app/backend/requirements-dev.txt', 'app/backend/requirements.default',
    'app/backend/requirements.txt', 'app/frontend/package.json', 'app/frontend/pnpm-lock.yaml',
    'app/frontend/requirements.default', 'app/frontend/requirements.txt')
PRIVATE_TEST_NAMES = frozenset(('test_private_ads_health', 'test_private_bank_auth', 'test_private_bank_provider',
    'test_private_bank_service', 'test_private_mail_brief', 'test_private_mail_brief_service',
    'test_private_mail_content', 'test_private_mail_relevance', 'test_private_mail_translation',
    'test_private_mail_translation_service', 'test_private_python310_compat', 'test_private_stripe_auth',
    'test_private_stripe_connection', 'test_private_stripe_report_provider', 'test_private_stripe_report_service',
    'test_private_workspace_app', 'test_private_workspace_brief', 'test_private_workspace_core',
    'test_private_workspace_providers', 'test_private_workspace_worker'))

spec = importlib.util.spec_from_file_location('stripe_report_payload', Path(__file__).with_name('build_payload.py'))
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def assemble_frozen_inventory(repo, frozen):
    """Read c1ae inventories from a clean descendant carrier without relaxing the builder."""
    source = frozen['source_sha']
    actual_git = builder.git
    head = actual_git(repo, 'rev-parse', 'HEAD').decode().strip()
    ancestry = subprocess.run(['git', 'merge-base', '--is-ancestor', source, head],
                              cwd=repo, capture_output=True, timeout=30, check=False)
    builder.need(ancestry.returncode == 0, 'FROZEN_SOURCE_ANCESTRY_REQUIRED')
    builder.need(not actual_git(repo, 'diff', '--name-only', source, head, '--', 'app').strip(),
                 'CARRIER_APPLICATION_DELTA_REJECTED')
    builder.need(not actual_git(repo, 'status', '--porcelain', '--untracked-files=no', '--', 'app').strip(),
                 'TRACKED_APPLICATION_DRIFT')
    def source_only_head(path, *arguments):
        if arguments == ('rev-parse', 'HEAD'):
            return (source + '\n').encode()
        return actual_git(path, *arguments)
    # Only this inventory assembly substitutes HEAD; source blobs, dependencies,
    # application cleanliness, untracked-source checks and static hashes remain real.
    with mock.patch.object(builder, 'git', side_effect=source_only_head):
        return builder.assemble(repo, frozen)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.repo = self.root / 'repo'; self.repo.mkdir()
        self.output = self.root / 'output'; self.output.mkdir()
        self.write('app/backend/services/private_workspace.py', 'old synthetic private module\n')
        self.write('app/backend/services/private_workspace_providers.py', '# old provider module\n')
        self.write('app/backend/routers/private_workspace.py', '# old private router\n')
        self.write('app/backend/schemas/private_workspace.py', '# old private schemas\n')
        self.write('app/backend/models/private_workspace.py', 'old synthetic models\n')
        self.write('app/backend/services/customer_finance.py', 'unchanged synthetic customer module\n')
        self.write('app/backend/requirements.txt', 'synthetic-runtime==1\n')
        for path in set(DEPENDENCY_PATHS) - {'app/backend/requirements.txt', 'app/frontend/package.json', 'app/frontend/pnpm-lock.yaml'}:
            self.write(path, '# unchanged synthetic dependency contract\n')
        self.write('app/backend/tests/conftest.py', '# synthetic fixture\n')
        for name in PRIVATE_TEST_NAMES - {'test_private_stripe_report_provider', 'test_private_stripe_report_service'}:
            self.write('app/backend/tests/' + name + '.py', '# baseline private regression\n')
        self.write('app/frontend/package.json', '{"name":"synthetic"}\n')
        self.write('app/frontend/pnpm-lock.yaml', 'synthetic-lock: true\n')
        self.write('app/frontend/src/App.tsx', '// synthetic frontend\n')
        self.run_git('init', '-q'); self.run_git('add', 'app'); self.commit('baseline')
        self.base = self.run_git('rev-parse', 'HEAD').strip()
        self.write('app/backend/models/private_workspace.py', 'new synthetic models\n')
        self.write('app/backend/services/private_workspace_providers.py', '# reviewed provider module\n')
        self.write('app/backend/routers/private_workspace.py', '# reviewed private router\n')
        self.write('app/backend/schemas/private_workspace.py', '# reviewed private schemas\n')
        self.write('app/backend/services/private_stripe_report_provider.py', '# reviewed Stripe report provider\n')
        self.write('app/backend/services/private_stripe_report_service.py', '# reviewed Stripe report service\n')
        self.write('app/backend/tests/test_private_workspace_core.py', '# reviewed core regression\n')
        self.write('app/backend/tests/test_private_stripe_report_provider.py', '# Stripe provider regression\n')
        self.write('app/backend/tests/test_private_stripe_report_service.py', '# Stripe service regression\n')
        self.run_git('add', 'app'); self.commit('reviewed final')
        self.source = self.run_git('rev-parse', 'HEAD').strip()
        self.version = '123456abcdef'
        self.write('app/frontend/dist/index.html', '<script src="/assets/app.js"></script>')
        self.write('app/frontend/dist/app-version.json', json.dumps({'version': self.version}))
        self.write('app/frontend/dist/assets/app.js', '/* synthetic complete build */')
        self.write('app/frontend/dist/assets/app.css', '/* synthetic complete stylesheet */')
        self.write('app/frontend/dist/assets/logo.svg', '<svg xmlns="http://www.w3.org/2000/svg" />')
        self.write('app/frontend/dist/offline.html', '<html>Synthetic offline</html>')
        self.freeze = self.frozen()
        self.freeze_path = self.root / 'frozen.json'; self.save_freeze()

    def run_git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True, stderr=subprocess.DEVNULL)

    def commit(self, message):
        self.run_git('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.test', 'commit', '-qm', message)

    def write(self, path, text):
        destination = self.repo / path; destination.parent.mkdir(parents=True, exist_ok=True); destination.write_text(text)

    def frozen(self):
        changed = self.run_git('diff', '--name-only', self.base, self.source, '--', 'app/backend').splitlines()
        deps = DEPENDENCY_PATHS
        dist = self.repo / 'app/frontend/dist'
        return {'format_version': 1, 'stage': 'FROZEN_STRIPE_REPORT_SOURCE', 'source_sha': self.source,
            'baseline_private_source_sha': self.base, 'base_private_image': builder.BASE_IMAGE, 'frontend_version': self.version,
            'backend_regression_tests_minimum': 1173,
            'backend_delta_sha256': {path: builder.sha((self.repo / path).read_bytes()) for path in changed},
            'dependency_file_sha256': {path: builder.sha((self.repo / path).read_bytes()) for path in deps},
            'frontend_dist_sha256': {path.relative_to(dist).as_posix(): builder.sha(path.read_bytes())
                                    for path in dist.rglob('*') if path.is_file()}}

    def save_freeze(self):
        self.freeze_path.write_text(json.dumps(self.freeze, sort_keys=True)); self.freeze_sha = builder.sha(self.freeze_path.read_bytes())

    def build(self):
        arguments = SimpleNamespace(repo=self.repo, output=self.output, freeze=self.freeze_path, freeze_sha256=self.freeze_sha)
        with mock.patch.object(builder, 'BASE_SOURCE', self.base), redirect_stdout(io.StringIO()) as output:
            builder.main(arguments)
        return json.loads(output.getvalue())

    def test_complete_delta_all_tests_and_full_static_build_are_deterministic(self):
        result = self.build(); self.assertFalse(result['deployed'])
        target = self.output / 'stripe-report-payload.tar.gz'; manifest = json.loads((self.output / 'stripe-report-manifest.json').read_text())
        with tarfile.open(target, 'r:gz') as archive:
            names = archive.getnames()
            self.assertIn('payload/backend/services/private_stripe_report_service.py', names)
            self.assertIn('payload/backend/tests/test_private_workspace_core.py', names)
            self.assertIn('payload/backend/tests/conftest.py', names)
            self.assertIn('payload/frontend/dist/assets/app.js', names)
            self.assertIn('payload/frontend/dist/assets/app.css', names)
            self.assertIn('payload/frontend/dist/assets/logo.svg', names)
            self.assertIn('payload/frontend/dist/offline.html', names)
            self.assertTrue(all(member.isfile() and member.mtime == 0 for member in archive))
            self.assertEqual({name for name in names if name.startswith('payload/backend/tests/')},
                {'payload/backend/tests/' + name + '.py' for name in PRIVATE_TEST_NAMES} | {'payload/backend/tests/conftest.py'})
        self.assertFalse(manifest['runtime_dependency_changes']); self.assertFalse(manifest['credentials_included'])
        self.assertEqual(manifest['stage'], 'STRIPE_REPORT_BACKEND_PAYLOAD_PREPARED')
        self.assertEqual(len(manifest['private_tests']), 21)
        self.assertEqual(manifest['backend_regression_tests_expected_minimum'], 1173)
        self.assertEqual(set(manifest['backend_changes']), BACKEND_CHANGES)
        self.assertEqual(set(manifest['runtime_dependency_file_sha256']), set(DEPENDENCY_PATHS))
        self.assertEqual((target.stat().st_mode & 0o777), 0o600)
        with mock.patch.object(builder, 'BASE_SOURCE', self.base): files, _, _ = builder.assemble(self.repo, self.freeze)
        self.assertEqual(target.read_bytes(), builder.encode(files))
        self.assertNotIn('payload/backend/services/customer_finance.py', names)

    def test_unfrozen_wrong_sha_and_missing_inventory_cannot_build(self):
        for change, code in (
            ({'stage': 'PREPARED'}, 'EXACT_REVIEWED_SOURCE_MANIFEST_REQUIRED'),
            ({'source_sha': 'not-frozen'}, 'EXACT_REVIEWED_SOURCE_MANIFEST_REQUIRED'),
            ({'frontend_dist_sha256': {}}, 'COMPLETE_REVIEWED_FILE_INVENTORY_REQUIRED'),
        ):
            with self.subTest(code=code):
                original = self.freeze; self.freeze = {**original, **change}; self.save_freeze()
                with self.assertRaisesRegex(builder.PayloadError, code): self.build()
                self.freeze = original; self.save_freeze()
        self.freeze_sha = '0' * 64
        with self.assertRaisesRegex(builder.PayloadError, 'FROZEN_MANIFEST_HASH_DRIFT'): self.build()

    def test_missing_private_delta_or_incomplete_dependencies_are_rejected(self):
        for field, code in (('backend_delta_sha256', 'COMPLETE_BACKEND_DELTA_DRIFT'),
                            ('dependency_file_sha256', 'COMPLETE_DEPENDENCY_PROOF_DRIFT')):
            with self.subTest(field=field):
                original = deepcopy(self.freeze); self.freeze[field].pop(next(iter(self.freeze[field]))); self.save_freeze()
                with self.assertRaisesRegex(builder.PayloadError, code): self.build()
                self.freeze = original; self.save_freeze()

    def test_unrelated_customer_backend_change_is_rejected_even_in_review_manifest(self):
        self.write('app/backend/services/customer_finance.py', 'changed customer calculation\n')
        self.run_git('add', 'app/backend/services/customer_finance.py'); self.commit('forbidden customer change')
        self.source = self.run_git('rev-parse', 'HEAD').strip(); self.freeze = self.frozen(); self.save_freeze()
        with self.assertRaisesRegex(builder.PayloadError, 'NON_PRIVATE_BACKEND_DELTA_REJECTED'): self.build()

    def test_private_file_deletion_is_rejected(self):
        self.run_git('rm', 'app/backend/models/private_workspace.py'); self.commit('forbidden deletion')
        self.source = self.run_git('rev-parse', 'HEAD').strip(); self.freeze['source_sha'] = self.source; self.save_freeze()
        with self.assertRaisesRegex(builder.PayloadError, 'NON_PRIVATE_BACKEND_DELTA_REJECTED'): self.build()

    def test_runtime_dependency_change_is_rejected(self):
        self.write('app/frontend/pnpm-lock.yaml', 'changed-runtime: true\n')
        self.run_git('add', 'app/frontend/pnpm-lock.yaml'); self.commit('forbidden dependency change')
        self.source = self.run_git('rev-parse', 'HEAD').strip(); self.freeze = self.frozen(); self.save_freeze()
        with self.assertRaisesRegex(builder.PayloadError, 'RUNTIME_DEPENDENCY_CHANGED'): self.build()

    def test_dirty_or_untracked_source_is_not_a_final_reviewed_build(self):
        self.write('app/frontend/src/App.tsx', '// dirty frontend\n')
        with self.assertRaisesRegex(builder.PayloadError, 'TRACKED_APPLICATION_DRIFT'): self.build()
        self.run_git('checkout', '--', 'app/frontend/src/App.tsx')
        self.write('app/backend/services/private_omitted.py', '# missing commit\n')
        with self.assertRaisesRegex(builder.PayloadError, 'UNTRACKED_APPLICATION_SOURCE_REJECTED'): self.build()

    def test_build_bytes_wrong_version_extra_file_and_symlink_are_rejected(self):
        path = self.repo / 'app/frontend/dist/assets/app.js'; original = path.read_bytes()
        path.write_text('drift')
        with self.assertRaisesRegex(builder.PayloadError, 'COMPLETE_STATIC_BUILD_DRIFT'): self.build()
        path.write_bytes(original)
        version = self.repo / 'app/frontend/dist/app-version.json'; correct = version.read_bytes()
        version.write_text('{"version":"wrong"}')
        with self.assertRaisesRegex(builder.PayloadError, 'FRONTEND_VERSION_DRIFT'): self.build()
        version.write_bytes(correct)
        secret = self.repo / 'app/frontend/dist/.env'; secret.write_text('synthetic-secret')
        with self.assertRaisesRegex(builder.PayloadError, 'NON_STATIC_PAYLOAD_REJECTED'): self.build()
        secret.unlink(); path.unlink(); path.symlink_to(self.repo / 'app/frontend/src/App.tsx')
        with self.assertRaisesRegex(builder.PayloadError, 'STATIC_SYMLINK_FORBIDDEN'): self.build()

    def test_existing_payload_cannot_be_overwritten(self):
        self.build()
        with self.assertRaisesRegex(builder.PayloadError, 'NEW_PAYLOAD_AND_MANIFEST_REQUIRED'): self.build()

    def test_untracked_frontend_test_or_source_cannot_evade_frozen_source_review(self):
        for path in ('app/frontend/tests/private_omitted.test.mjs', 'app/frontend/src/private-omitted.css'):
            with self.subTest(path=path):
                self.write(path, '// synthetic unreviewed file\n')
                with self.assertRaisesRegex(builder.PayloadError, 'UNTRACKED_APPLICATION_SOURCE_REJECTED'): self.build()
                (self.repo / path).unlink()

    def test_new_dependency_file_cannot_evade_complete_dependency_inventory(self):
        self.write('app/frontend/pyproject.toml', '[project]\nname="synthetic"\n')
        self.run_git('add', 'app/frontend/pyproject.toml'); self.commit('forbidden additional dependency')
        self.source = self.run_git('rev-parse', 'HEAD').strip(); self.freeze = self.frozen(); self.save_freeze()
        with self.assertRaisesRegex(builder.PayloadError, 'DEPENDENCY_INVENTORY_DRIFT'): self.build()

    def test_extra_allowed_static_file_still_requires_reviewed_inventory(self):
        self.write('app/frontend/dist/assets/omitted.css', '/* unreviewed synthetic static asset */')
        with self.assertRaisesRegex(builder.PayloadError, 'COMPLETE_STATIC_BUILD_DRIFT'): self.build()

    def test_blob_paths_and_git_operations_require_read_only_canonical_scope(self):
        for path in ('/app/backend/private.py', '../app/backend/private.py', 'app/backend/../private.py'):
            with self.subTest(path=path):
                with self.assertRaisesRegex(builder.PayloadError, 'CANONICAL_SOURCE_PATH_REQUIRED'):
                    builder.blob(self.repo, self.source, path)
        with self.assertRaisesRegex(builder.PayloadError, 'READONLY_GIT_COMMAND_REQUIRED'):
            builder.git(self.repo, 'checkout', '--', 'app')

    def test_inventory_only_can_read_clean_descendant_carrier_but_builder_stays_exact(self):
        destination = self.repo / 'deployments/synthetic-carrier.py'
        destination.parent.mkdir(); destination.write_text('# synthetic deployment helper\n')
        self.run_git('add', 'deployments'); self.commit('deployment-only descendant carrier')
        with mock.patch.object(builder, 'BASE_SOURCE', self.base):
            with self.assertRaisesRegex(builder.PayloadError, 'EXACT_FINAL_REVIEWED_HEAD_REQUIRED'):
                builder.assemble(self.repo, self.freeze)
            files, source_hashes, dependencies = assemble_frozen_inventory(self.repo, self.freeze)
        self.assertIn('backend/services/private_stripe_report_service.py', files)
        self.assertNotIn('deployments/synthetic-carrier.py', files)
        self.assertEqual(set(dependencies), set(DEPENDENCY_PATHS))
        self.assertEqual(len([name for name in source_hashes if name.startswith('app/backend/tests/')]), 21)

    def test_inventory_read_rejects_dirty_committed_application_delta_and_wrong_ancestry(self):
        self.write('app/frontend/src/App.tsx', '// unreviewed application drift\n')
        with mock.patch.object(builder, 'BASE_SOURCE', self.base):
            with self.assertRaisesRegex(builder.PayloadError, 'TRACKED_APPLICATION_DRIFT'):
                assemble_frozen_inventory(self.repo, self.freeze)
            self.run_git('add', 'app/frontend/src/App.tsx'); self.commit('unreviewed application descendant')
            with self.assertRaisesRegex(builder.PayloadError, 'CARRIER_APPLICATION_DELTA_REJECTED'):
                assemble_frozen_inventory(self.repo, self.freeze)
            self.run_git('checkout', '-q', self.base)
            with self.assertRaisesRegex(builder.PayloadError, 'FROZEN_SOURCE_ANCESTRY_REQUIRED'):
                assemble_frozen_inventory(self.repo, self.freeze)


class FrozenSourceReadOnlyTests(unittest.TestCase):
    def test_exact_reviewed_source_complete_private_delta_and_full_inventories(self):
        repo = Path(__file__).resolve().parents[2]
        frozen_path = Path(__file__).with_name('artifacts') / 'frozen-source.json'
        self.assertEqual(builder.BASE_SOURCE, BASE_SOURCE)
        self.assertEqual(builder.sha(frozen_path.read_bytes()), FROZEN_MANIFEST_SHA)
        frozen = builder.freeze(frozen_path, FROZEN_MANIFEST_SHA)
        self.assertEqual(frozen['source_sha'], SOURCE_SHA)
        self.assertEqual(frozen['stage'], 'FROZEN_STRIPE_REPORT_SOURCE')
        self.assertEqual(frozen['frontend_version'], FRONTEND_VERSION)
        self.assertEqual(frozen['backend_regression_tests_minimum'], 1173)
        self.assertEqual(set(frozen['backend_delta_sha256']), BACKEND_CHANGES)
        files, source_hashes, dependencies = assemble_frozen_inventory(repo, frozen)
        private_tests = {'app/backend/tests/' + name + '.py' for name in PRIVATE_TEST_NAMES}
        self.assertEqual(len(private_tests), 20)
        self.assertEqual({name for name in source_hashes if name.startswith('app/backend/tests/')},
                         private_tests | {'app/backend/tests/conftest.py'})
        self.assertEqual(set(source_hashes), BACKEND_CHANGES | private_tests | {'app/backend/tests/conftest.py'})
        self.assertEqual(dependencies, frozen['dependency_file_sha256'])
        self.assertEqual(set(dependencies), set(DEPENDENCY_PATHS))
        for name in dependencies:
            self.assertEqual(builder.blob(repo, BASE_SOURCE, name), builder.blob(repo, SOURCE_SHA, name))
        static = {name.removeprefix('frontend/dist/'): builder.sha(data)
                  for name, data in files.items() if name.startswith('frontend/dist/')}
        self.assertEqual(static, frozen['frontend_dist_sha256'])
        self.assertEqual(len(static), 113)
        self.assertEqual(json.loads(files['frontend/dist/app-version.json']), {'version': FRONTEND_VERSION})
        self.assertTrue(all(name.startswith(('backend/', 'frontend/dist/')) for name in files))
        self.assertEqual(set(files), {name.removeprefix('app/') for name in source_hashes} |
                         {'frontend/dist/' + name for name in static})


if __name__ == '__main__': unittest.main()
