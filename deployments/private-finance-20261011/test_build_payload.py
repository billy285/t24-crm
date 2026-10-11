"""Small synthetic Git repositories prove source and archive scope boundaries."""
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

spec = importlib.util.spec_from_file_location('private_finance_payload', Path(__file__).with_name('build_payload.py'))
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.repo = self.root / 'repo'; self.repo.mkdir()
        self.output = self.root / 'output'; self.output.mkdir()
        self.write('app/backend/services/private_workspace.py', 'old synthetic private module\n')
        self.write('app/backend/models/private_workspace.py', 'old synthetic models\n')
        self.write('app/backend/services/customer_finance.py', 'unchanged synthetic customer module\n')
        self.write('app/backend/requirements.txt', 'synthetic-runtime==1\n')
        self.write('app/backend/tests/conftest.py', '# synthetic fixture\n')
        self.write('app/backend/tests/test_private_workspace_core.py', '# private regression\n')
        self.write('app/frontend/package.json', '{"name":"synthetic"}\n')
        self.write('app/frontend/pnpm-lock.yaml', 'synthetic-lock: true\n')
        self.write('app/frontend/src/App.tsx', '// synthetic frontend\n')
        self.run_git('init', '-q'); self.run_git('add', 'app'); self.commit('baseline')
        self.base = self.run_git('rev-parse', 'HEAD').strip()
        self.write('app/backend/services/private_workspace.py', 'new synthetic private module\n')
        self.write('app/backend/models/private_workspace.py', 'new synthetic models\n')
        self.write('app/backend/services/private_bank_service.py', 'synthetic bank module\n')
        self.write('app/backend/tests/test_private_bank.py', '# private bank regression\n')
        self.run_git('add', 'app'); self.commit('reviewed final')
        self.source = self.run_git('rev-parse', 'HEAD').strip()
        self.version = '123456abcdef'
        self.write('app/frontend/dist/index.html', '<script src="/assets/app.js"></script>')
        self.write('app/frontend/dist/app-version.json', json.dumps({'version': self.version}))
        self.write('app/frontend/dist/assets/app.js', '/* synthetic complete build */')
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
        deps = ['app/backend/requirements.txt', 'app/frontend/package.json', 'app/frontend/pnpm-lock.yaml']
        dist = self.repo / 'app/frontend/dist'
        return {'format_version': 1, 'stage': 'FROZEN_PRIVATE_FINANCE_SOURCE', 'source_sha': self.source,
            'baseline_private_source_sha': self.base, 'base_private_image': builder.BASE_IMAGE, 'frontend_version': self.version,
            'backend_regression_tests_minimum': 10,
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
        target = self.output / 'private-finance-payload.tar.gz'; manifest = json.loads((self.output / 'private-finance-manifest.json').read_text())
        with tarfile.open(target, 'r:gz') as archive:
            names = archive.getnames()
            self.assertIn('payload/backend/services/private_bank_service.py', names)
            self.assertIn('payload/backend/tests/test_private_workspace_core.py', names)
            self.assertIn('payload/backend/tests/conftest.py', names)
            self.assertIn('payload/frontend/dist/assets/app.js', names)
            self.assertTrue(all(member.isfile() and member.mtime == 0 for member in archive))
        self.assertFalse(manifest['runtime_dependency_changes']); self.assertFalse(manifest['credentials_included'])
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


if __name__ == '__main__': unittest.main()
