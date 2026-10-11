"""Synthetic carrier transport tests; no network, account or live service."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

import acquire_candidate as acquire


class CarrierTests(unittest.TestCase):
    def setUp(self):
        self.carrier = 'c' * 40
        self.source = 'a' * 40
        self.files = {acquire.PREFIX + name: b'# reviewed synthetic helper\n' for name in acquire.TOOLS}
        self.payload = b'reviewed synthetic payload, no credentials'
        self.frozen = {'stage': 'FROZEN_PRIVATE_FINANCE_SOURCE', 'source_sha': self.source}
        self.freeze_blob = json.dumps(self.frozen).encode()
        self.manifest = {'stage': 'PRIVATE_FINANCE_PAYLOAD_PREPARED', 'source_sha': self.source,
            'frozen_manifest_sha256': acquire.sha(self.freeze_blob), 'payload_sha256': acquire.sha(self.payload),
            'credentials_included': False, 'production_access': False, 'deployed': False}
        self.files[acquire.PREFIX + 'artifacts/frozen-source.json'] = self.freeze_blob
        self.files[acquire.PREFIX + 'artifacts/private-finance-payload.tar.gz'] = self.payload
        self.files[acquire.PREFIX + 'artifacts/private-finance-manifest.json'] = json.dumps(self.manifest).encode()
        self.digests = {name: acquire.sha(self.files[acquire.PREFIX + 'artifacts/' + name]) for name in acquire.ARTIFACTS}

    def archive(self, files=None, *, selected_symlink=False, duplicate=False):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            top = 't24-crm-' + self.carrier + '/'
            archive.writestr(top, b'')
            for name, content in (files or self.files).items():
                info = zipfile.ZipInfo(top + name)
                info.external_attr = ((stat.S_IFLNK if selected_symlink and name.endswith('candidate_prepare.py')
                                       else stat.S_IFREG) | 0o644) << 16
                archive.writestr(info, content)
            if duplicate:
                archive.writestr(top + acquire.PREFIX + 'candidate_prepare.py', b'changed')
        return buffer.getvalue()

    def read(self, files=None, **kwargs):
        return acquire.reviewed_files(self.archive(files, **kwargs), self.carrier, self.source, self.digests)

    def test_fixed_public_origin_requires_full_immutable_hash(self):
        self.assertEqual(acquire.archive_url(self.carrier), 'https://codeload.github.com/billy285/t24-crm/zip/' + self.carrier)
        for value in ('main', 'abc123', '../escape', 'a' * 40 + '?token=ignored'):
            with self.assertRaises(acquire.AcquireError): acquire.archive_url(value)

    def test_complete_reviewed_files_only_and_no_unrelated_archive_extraction(self):
        files = {**self.files, 'app/backend/customer_data.db': b'not selected', 'other/unselected.txt': b'unselected'}
        result = self.read(files)
        self.assertEqual(set(result), set(acquire.TOOLS) | set(acquire.ARTIFACTS))
        self.assertNotIn('customer_data.db', result)
        self.assertEqual(result['private-finance-payload.tar.gz'], self.payload)

    def test_missing_code_or_artifact_rejected(self):
        for name in (acquire.PREFIX + 'candidate_prepare.py', acquire.PREFIX + 'artifacts/frozen-source.json'):
            files = deepcopy(self.files); del files[name]
            with self.subTest(name=name), self.assertRaisesRegex(acquire.AcquireError, 'COMPLETE_CARRIER_REQUIRED'):
                self.read(files)

    def test_reviewed_artifact_tampering_rejected(self):
        for name in acquire.ARTIFACTS:
            files = deepcopy(self.files); files[acquire.PREFIX + 'artifacts/' + name] += b'tamper'
            with self.subTest(name=name), self.assertRaisesRegex(acquire.AcquireError, 'FROZEN_ARTIFACT_HASH_DRIFT'):
                self.read(files)

    def test_scope_flags_and_source_binding_cannot_be_overridden(self):
        for field, value in (('credentials_included', True), ('production_access', True), ('deployed', True),
                             ('source_sha', 'b' * 40), ('payload_sha256', '0' * 64),
                             ('frozen_manifest_sha256', '0' * 64)):
            changed = {**self.manifest, field: value}; blob = json.dumps(changed).encode()
            files = {**self.files, acquire.PREFIX + 'artifacts/private-finance-manifest.json': blob}
            digests = {**self.digests, 'private-finance-manifest.json': acquire.sha(blob)}
            with self.subTest(field=field), self.assertRaisesRegex(acquire.AcquireError, 'CARRIER_SCOPE_BINDING_REJECTED'):
                acquire.reviewed_files(self.archive(files), self.carrier, self.source, digests)

    def test_frozen_source_mismatch_rejected_even_with_new_file_hash(self):
        blob = json.dumps({**self.frozen, 'source_sha': 'b' * 40}).encode()
        files = {**self.files, acquire.PREFIX + 'artifacts/frozen-source.json': blob}
        digests = {**self.digests, 'frozen-source.json': acquire.sha(blob)}
        with self.assertRaisesRegex(acquire.AcquireError, 'CARRIER_SCOPE_BINDING_REJECTED'):
            acquire.reviewed_files(self.archive(files), self.carrier, self.source, digests)

    def test_symlink_selected_code_is_not_executed_or_installed(self):
        with self.assertRaisesRegex(acquire.AcquireError, 'CARRIER_SELECTED_FILE_REJECTED'):
            self.read(selected_symlink=True)

    def test_duplicate_archive_entries_rejected(self):
        with mock.patch('warnings.warn'), self.assertRaisesRegex(acquire.AcquireError, 'CARRIER_ENTRY_INVENTORY_REJECTED'):
            self.read(duplicate=True)

    def test_noncanonical_or_parent_path_is_rejected(self):
        for name in ('../escape', '/absolute', 'app/../../escape', 'app//uncanonical'):
            with self.subTest(name=name), self.assertRaisesRegex(acquire.AcquireError, 'CARRIER_PATH_REJECTED'):
                self.read({**self.files, name: b'not extracted'})

    def test_empty_selected_file_is_rejected(self):
        with self.assertRaisesRegex(acquire.AcquireError, 'CARRIER_FILE_SIZE_REJECTED'):
            self.read({**self.files, acquire.PREFIX + 'candidate_prepare.py': b''})

    def test_install_writes_only_new_protected_files(self):
        files = self.read()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve() / 'carrier'
            acquire.install(files, target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            for name, value in files.items():
                self.assertEqual((target / name).read_bytes(), value)
                self.assertEqual((target / name).stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(acquire.AcquireError, 'NEW_CARRIER_DIRECTORY_REQUIRED'):
                acquire.install(files, target)
            self.assertEqual((target / 'candidate_prepare.py').read_bytes(), files['candidate_prepare.py'])

    def test_writable_release_parent_rejected_without_creating_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            for mode in (0o775, 0o777):
                parent.chmod(mode)
                with self.subTest(mode=mode), self.assertRaisesRegex(acquire.AcquireError, 'PROTECTED_RELEASE_DIRECTORY_REQUIRED'):
                    acquire.install(self.read(), parent / 'carrier')
                self.assertFalse((parent / 'carrier').exists())
            parent.chmod(0o700)

    def test_ancestor_and_owner_protection_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            with self.assertRaisesRegex(acquire.AcquireError, 'PROTECTED_RELEASE_DIRECTORY_REQUIRED'):
                acquire.protected_directory(path, owner=os.geteuid()+1)
            info = path.stat()
            with mock.patch.object(Path, 'lstat', return_value=mock.Mock(st_uid=0, st_mode=stat.S_IFDIR|0o777)):
                with self.assertRaisesRegex(acquire.AcquireError, 'PROTECTED_RELEASE_DIRECTORY_REQUIRED'):
                    acquire.protected_directory(path, ancestors=True)
            self.assertEqual(path.stat().st_ino, info.st_ino)

    def test_parent_replacement_cannot_redirect_pinned_file_writes_or_claim_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); parent = root / 'protected'; parent.mkdir(mode=0o700)
            target = parent / 'carrier'; real_open = os.open; moved = False
            def replace_during_first_write(name, flags, *args, **kwargs):
                nonlocal moved
                if kwargs.get('dir_fd') is not None and flags & os.O_CREAT and not moved:
                    parent.rename(root / 'retained'); parent.mkdir(mode=0o700); (parent / 'carrier').mkdir(mode=0o700)
                    moved = True
                return real_open(name, flags, *args, **kwargs)
            with mock.patch.object(acquire.os, 'open', side_effect=replace_during_first_write):
                with self.assertRaisesRegex(acquire.AcquireError, 'CARRIER_DIRECTORY_IDENTITY_DRIFT'):
                    acquire.install(self.read(), target)
            self.assertTrue(moved)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual((root/'retained/carrier/candidate_prepare.py').read_bytes(), self.read()['candidate_prepare.py'])

    def test_wrong_download_hash_or_oversize_rejected_before_install(self):
        for value in (b'changed', b'x' * (acquire.MAX_ARCHIVE_BYTES + 1)):
            response = mock.MagicMock(); response.__enter__.return_value = response
            response.status = 200; response.geturl.return_value = acquire.archive_url(self.carrier)
            response.read.return_value = value
            opener = mock.MagicMock(); opener.open.return_value = response
            with mock.patch.object(acquire.urllib.request, 'build_opener', return_value=opener), self.assertRaisesRegex(acquire.AcquireError, 'CARRIER_ARCHIVE_HASH_DRIFT'):
                acquire.download(self.carrier, acquire.sha(b'expected'))
            response.read.assert_called_once_with(acquire.MAX_ARCHIVE_BYTES + 1)

    def test_no_redirect_to_another_provider_or_credential_url(self):
        with self.assertRaisesRegex(acquire.AcquireError, 'UNEXPECTED_DOWNLOAD_REDIRECT'):
            acquire.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.test/untrusted')

    def test_redirected_download_origin_rejected(self):
        response = mock.MagicMock(); response.__enter__.return_value = response
        response.status = 200; response.geturl.return_value = 'https://example.test/untrusted'
        opener = mock.MagicMock(); opener.open.return_value = response
        with mock.patch.object(acquire.urllib.request, 'build_opener', return_value=opener), self.assertRaisesRegex(acquire.AcquireError, 'DOWNLOAD_ORIGIN_DRIFT'):
            acquire.download(self.carrier, 'a' * 64)
        response.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
