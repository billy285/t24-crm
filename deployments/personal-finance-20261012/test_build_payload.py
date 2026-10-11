"""Carrier scope regressions use a synthetic repository and no provider accounts."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('personal_payload', Path(__file__).with_name('build_payload.py'))
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)

class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'; self.repo.mkdir(); self.output = Path(self.temp.name) / 'output'; self.output.mkdir()
        for path in ('app/backend/services/private_workspace.py', 'app/backend/services/private_workspace_app.py', 'app/backend/tests/test_private_workspace_core.py', 'app/backend/tests/test_private_bank_auth.py', 'app/backend/tests/conftest.py'):
            self.write(path, b'# synthetic baseline\n')
        self.write('app/backend/requirements.txt', b'synthetic==1\n')
        self.write('app/frontend/package.json', b'{"name":"synthetic"}\n')
        self.write('app/frontend/src/App.tsx', b'// synthetic app source\n')
        self.git('init', '-q'); self.git('add', 'app'); self.commit('baseline'); self.base = self.git('rev-parse', 'HEAD').strip()
        for path in builder.BACKEND_CHANGES: self.write(path, ('# synthetic reviewed ' + path + '\n').encode())
        self.git('add', 'app'); self.commit('reviewed'); self.source = self.git('rev-parse', 'HEAD').strip()
        self.version = '123456abcdef'
        self.write('app/frontend/dist/index.html', b'<script src="/assets/app.js"></script>')
        self.write('app/frontend/dist/app-version.json', json.dumps({'version': self.version}).encode())
        self.write('app/frontend/dist/assets/app.js', b'/* reviewed synthetic static output */')
        self.write('.gitignore', b'app/frontend/dist/\napp/frontend/work/\n')
        self.git('add', '.gitignore'); self.commit('local carrier')
        self.static = {p.relative_to(self.repo / 'app/frontend/dist').as_posix(): builder.sha(p.read_bytes()) for p in (self.repo / 'app/frontend/dist').rglob('*') if p.is_file()}
        for name, value in (('SOURCE_SHA', self.source), ('BASE_SOURCE', self.base), ('BASE_IMAGE', 'sha256:' + 'a' * 64), ('FRONTEND_VERSION', self.version), ('FRONTEND_SOURCE_DIGEST', self.version + '0' * 52), ('FRONTEND_DIST_SHA256', self.static)):
            mock = patch.object(builder, name, value); mock.start(); self.addCleanup(mock.stop)

    def write(self, name, data):
        path = self.repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    def git(self, *arguments):
        return subprocess.check_output(['git', *arguments], cwd=self.repo, stderr=subprocess.PIPE).decode()
    def commit(self, label): self.git('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', label)
    def build(self):
        with redirect_stdout(io.StringIO()): builder.main(SimpleNamespace(repo=self.repo, output=self.output))
        return json.loads((self.output / 'manifest.json').read_text())

    def test_exact_scope_and_deterministic_carrier(self):
        self.write('app/frontend/work/qa/credentials.json', b'{"synthetic":"not a release file"}')
        manifest = self.build()
        self.assertEqual(manifest['source_sha'], self.source)
        self.assertEqual(manifest['backend_changes'], sorted(builder.BACKEND_CHANGES))
        self.assertEqual(manifest['backend_regression_tests_expected_minimum'], 1192)
        self.assertFalse(manifest['runtime_dependency_changes'])
        self.assertEqual((manifest['private_schema_table_count_before'], manifest['private_schema_table_count_after']), (11, 20))
        with tarfile.open(self.output / 'payload.tar.gz', 'r:gz') as archive:
            names = archive.getnames()
            self.assertTrue(all(name.startswith(('payload/backend/', 'payload/frontend/dist/')) for name in names))
            self.assertFalse(any(any(word in name for word in ('work/', 'credentials', 'node_modules', '.db')) for name in names))
            actual = {member.name.removeprefix('payload/'): builder.sha(archive.extractfile(member).read()) for member in archive.getmembers()}
        self.assertEqual(actual, manifest['payload_files'])
        self.assertEqual(builder.sha((self.output / 'payload.tar.gz').read_bytes()), manifest['payload_sha256'])
        files = builder.assemble(self.repo)[0]
        self.assertEqual(builder.encode(files), (self.output / 'payload.tar.gz').read_bytes())
        self.assertEqual(manifest['source_file_sha256']['app/backend/services/private_personal_finance.py'], builder.sha(self.git('show', self.source + ':app/backend/services/private_personal_finance.py').encode()))

    def test_working_tree_runtime_drift_is_rejected(self):
        self.write('app/backend/services/private_personal_finance.py', b'# drifting working tree\n')
        with self.assertRaisesRegex(builder.PayloadError, 'TRACKED_APPLICATION_DRIFT'): builder.assemble(self.repo)

    def test_untracked_source_is_rejected_but_qa_work_is_never_included(self):
        self.write('app/backend/services/unreviewed.py', b'# untracked\n')
        with self.assertRaisesRegex(builder.PayloadError, 'UNTRACKED_APPLICATION_SOURCE_REJECTED'): builder.assemble(self.repo)

    def test_dependency_change_is_rejected(self):
        self.write('app/backend/requirements.txt', b'synthetic==2\n'); self.git('add', 'app'); self.commit('dependency drift')
        with patch.object(builder, 'SOURCE_SHA', self.git('rev-parse', 'HEAD').strip()):
            with self.assertRaisesRegex(builder.PayloadError, 'RUNTIME_DEPENDENCY_CHANGED'): builder.assemble(self.repo)

    def test_non_private_backend_delta_is_rejected(self):
        self.write('app/backend/services/customer_finance.py', b'# unrelated\n'); self.git('add', 'app'); self.commit('unrelated backend')
        with patch.object(builder, 'SOURCE_SHA', self.git('rev-parse', 'HEAD').strip()):
            with self.assertRaisesRegex(builder.PayloadError, 'EXACT_PERSONAL_BACKEND_DELTA_REQUIRED'): builder.assemble(self.repo)

    def test_static_drift_version_and_symlink_are_rejected(self):
        self.write('app/frontend/dist/assets/app.js', b'/* unreviewed change */')
        with self.assertRaisesRegex(builder.PayloadError, 'FROZEN_FRONTEND_BUILD_DRIFT'): builder.assemble(self.repo)
        self.write('app/frontend/dist/assets/app.js', b'/* reviewed synthetic static output */')
        self.write('app/frontend/dist/app-version.json', b'{"version":"wrong"}')
        with self.assertRaisesRegex(builder.PayloadError, 'FRONTEND_VERSION_DRIFT'): builder.assemble(self.repo)
        self.write('app/frontend/dist/app-version.json', json.dumps({'version': self.version}).encode())
        link = self.repo / 'app/frontend/dist/assets/secret.js'; link.symlink_to(self.repo / 'app/frontend/src/App.tsx')
        with self.assertRaisesRegex(builder.PayloadError, 'STATIC_SYMLINK_FORBIDDEN'): builder.assemble(self.repo)

    def test_archive_paths_and_no_overwrite(self):
        for name in ('../secret', 'backend/../../secret', '/backend/a.py', 'work/qa.py'):
            with self.assertRaises(builder.PayloadError): builder.encode({name: b'synthetic'})
        self.build()
        original = (self.output / 'manifest.json').read_bytes()
        with self.assertRaisesRegex(builder.PayloadError, 'NEW_ARTIFACT_OUTPUT_REQUIRED'): self.build()
        self.assertEqual(original, (self.output / 'manifest.json').read_bytes())

if __name__ == '__main__': unittest.main()
