"""Offline checks for payload allowlists and extraction trust boundaries."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import os
from types import SimpleNamespace
from unittest import mock

MODULE_PATH = Path(__file__).with_name('prepare_relevance_upgrade.py')
spec = importlib.util.spec_from_file_location('gmail_upgrade_prepare', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SafePayloadTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous = module.RELEASE
        module.RELEASE = self.root

    def tearDown(self):
        module.RELEASE = self.previous
        self.temporary.cleanup()

    def payload(self, files, member_name_override=None):
        memory = io.BytesIO()
        with tarfile.open(fileobj=memory, mode='w') as stream:
            for name, blob in files.items():
                member = tarfile.TarInfo(member_name_override or 'payload/' + name)
                member.size = len(blob)
                stream.addfile(member, io.BytesIO(blob))
        archive = self.root / 'payload.tar.gz'
        with gzip.open(archive, 'wb') as target:
            target.write(memory.getvalue())
        manifest = {'payload_files': {name: hashlib.sha256(blob).hexdigest() for name, blob in files.items()}}
        return archive, manifest

    def valid_files(self):
        source = {'backend/' + name: b'# private source\n' for name in module.BACKEND}
        source.update({'backend/tests/' + name: b'# synthetic tests\n' for name in (*module.TESTS, 'conftest.py')})
        source.update({'frontend/dist/index.html': b'<html></html>',
                       'frontend/dist/app-version.json': json.dumps({'version': module.VERSION}).encode()})
        return source

    def test_reviewed_payload_extracts_exactly(self):
        archive, manifest = self.payload(self.valid_files())
        root = module.extract(archive, manifest)
        self.assertEqual(module.file_map(root), manifest['payload_files'])

    def test_path_traversal_rejected_before_escape(self):
        archive, manifest = self.payload({'backend/services/private_workspace.py': b'x'}, 'payload/../escape.py')
        with self.assertRaisesRegex(RuntimeError, 'PAYLOAD_PATH_INVALID'):
            module.extract(archive, manifest)
        self.assertFalse((self.root / 'escape.py').exists())

    def test_unreviewed_backend_file_is_rejected(self):
        files = self.valid_files()
        files['backend/main.py'] = b'raise Exception("must never start")\n'
        archive, manifest = self.payload(files)
        with self.assertRaisesRegex(RuntimeError, 'BACKEND_OR_TEST_PAYLOAD_SCOPE_DRIFT'):
            module.extract(archive, manifest)

    def test_secret_file_in_dist_is_rejected(self):
        files = self.valid_files()
        files['frontend/dist/credentials.pem'] = b'not a real secret'
        archive, manifest = self.payload(files)
        with self.assertRaisesRegex(RuntimeError, 'NON_STATIC_PUBLIC_FILE_FORBIDDEN'):
            module.extract(archive, manifest)

    def test_file_hash_tampering_is_rejected(self):
        archive, manifest = self.payload(self.valid_files())
        manifest['payload_files']['backend/services/private_workspace.py'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'PAYLOAD_FILE_HASH_DRIFT'):
            module.extract(archive, manifest)

    def test_wrong_frontend_version_is_rejected(self):
        files = self.valid_files()
        files['frontend/dist/app-version.json'] = b'{"version":"older"}'
        archive, manifest = self.payload(files)
        with self.assertRaisesRegex(RuntimeError, 'PAYLOAD_FRONTEND_VERSION_DRIFT'):
            module.extract(archive, manifest)

    def test_static_file_tree_rejects_symlink(self):
        root = self.root / 'static'
        root.mkdir()
        (root / 'outside.js').symlink_to(MODULE_PATH)
        with self.assertRaisesRegex(RuntimeError, 'FILE_TREE_SYMLINK_FORBIDDEN'):
            module.file_map(root, True)

    def test_symlink_archive_member_is_rejected(self):
        archive = self.root / 'payload.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            member = tarfile.TarInfo('payload/frontend/dist/index.html')
            member.type = tarfile.SYMTYPE
            member.linkname = '/etc/shadow'
            stream.addfile(member)
        with self.assertRaisesRegex(RuntimeError, 'ONLY_REGULAR_PAYLOAD_FILES_ALLOWED'):
            module.extract(archive, {'payload_files': {}})

    def test_oversized_or_absent_manifest_members_are_rejected(self):
        archive, manifest = self.payload({'backend/main.py': b'x'})
        with self.assertRaisesRegex(RuntimeError, 'PAYLOAD_ALLOWLIST_OR_SIZE_DRIFT'):
            module.extract(archive, {'payload_files': {}})

    def test_new_static_root_readable_despite_protected_umask(self):
        previous = os.umask(0o077)
        try:
            private = self.root / 'private'; private.mkdir(mode=0o700)
            public = self.root / 'new-unserved-static'
            module.create_public_root(public)
            self.assertEqual(public.stat().st_mode & 0o777, 0o755)
            self.assertEqual(private.stat().st_mode & 0o777, 0o700)
            with self.assertRaisesRegex(RuntimeError, 'NEW_PUBLIC_DIRECTORY_REQUIRED'):
                module.create_public_root(public)
        finally:
            os.umask(previous)

    def test_exact_existing_allowlist_plus_sole_new_module(self):
        base = {name: 'old-hash' for name in module.BACKEND if name not in module.NEW_BACKEND}
        base['main.py'] = 'unchanged-crm-main'
        for name in module.BACKEND:
            path = self.root / 'backend' / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# synthetic reviewed source\n')
        expected = module.expected_backend(base, self.root)
        self.assertEqual(expected['main.py'], base['main.py'])
        self.assertEqual(set(expected) - set(base), set(module.NEW_BACKEND))
        self.assertEqual(len(module.BACKEND), 5)
        for malformed in (dict(base, **{module.NEW_BACKEND[0]: 'already-present'}),
                          {k:v for k,v in base.items() if k != 'schemas/private_workspace.py'}):
            with self.assertRaisesRegex(RuntimeError, 'REVIEWED_NEW_OR_EXISTING_BACKEND_FILE_REQUIRED'):
                module.expected_backend(malformed, self.root)

    def test_unstamped_template_cannot_enter_preparation(self):
        with mock.patch.object(module, 'SOURCE', '__APP_SOURCE_SHA__'), \
             mock.patch.object(module, 'run', side_effect=AssertionError('must not execute')), \
             mock.patch.object(module.os, 'umask'), \
             self.assertRaisesRegex(RuntimeError, 'REVIEWED_CONSTANTS_MUST_BE_STAMPED'):
            module.main(SimpleNamespace(manifest_sha256='a'*64))


if __name__ == '__main__':
    unittest.main()
