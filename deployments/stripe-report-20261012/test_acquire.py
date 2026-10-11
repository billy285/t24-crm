"""Synthetic archive and filesystem checks; no downloads or production access."""
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

spec = importlib.util.spec_from_file_location('stripe_report_acquirer', Path(__file__).with_name('acquire.py'))
a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
SOURCE = 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
IMAGE = 'sha256:322968e1935a6f7bb2e6d366a9f1cdb98aefab392af28c7269660ff46262a886'
VERSION = '913856b4d17b'


def fixture():
    carrier, source = 'c' * 40, SOURCE
    payload = b'synthetic frozen payload; not an executable production artifact'
    frozen = {'format_version': 1, 'stage': 'FROZEN_STRIPE_REPORT_SOURCE', 'source_sha': source,
              'baseline_private_source_sha': a.BACKEND_SOURCE, 'base_private_image': IMAGE,
              'frontend_version': VERSION, 'backend_regression_tests_minimum': 1173}
    frozen_bytes = json.dumps(frozen, sort_keys=True).encode()
    manifest = {'format_version': 1, 'stage': 'STRIPE_REPORT_BACKEND_PAYLOAD_PREPARED',
                'source_sha': source, 'frontend_version': VERSION,
                'baseline_private_source_sha': a.BACKEND_SOURCE, 'base_private_image': IMAGE,
                'runtime_dependency_changes': False, 'credentials_included': False,
                'production_access': False, 'deployed': False, 'payload_sha256': a.sha(payload),
                'frozen_manifest_sha256': a.sha(frozen_bytes), 'backend_regression_tests_expected_minimum': 1173}
    files = {a.PREFIX + 'prepare_candidate.py': b'# synthetic hash reviewed prepare helper\n',
             a.PREFIX + 'upgrade.py': b'# synthetic hash reviewed upgrade helper\n',
             a.PREFIX + 'artifacts/frozen-source.json': frozen_bytes,
             a.PREFIX + 'artifacts/stripe-report-manifest.json': json.dumps(manifest, sort_keys=True).encode(),
             a.PREFIX + 'artifacts/stripe-report-payload.tar.gz': payload}
    digests = {target: a.sha(files[selected]) for selected, target in a.SELECTED.items()}
    return carrier, source, manifest, frozen, files, digests


def archive(carrier, files, *, link=None, duplicate=False, directory=None, fifo=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as stream:
        top = 't24-crm-' + carrier + '/'
        stream.writestr(top, b'')
        for name, data in files.items():
            info = zipfile.ZipInfo(top + name)
            mode = stat.S_IFLNK if name == link else stat.S_IFDIR if name == directory else stat.S_IFIFO if name == fifo else stat.S_IFREG
            info.external_attr = (mode | 0o644) << 16
            stream.writestr(info, data)
        if duplicate:
            stream.writestr(top + a.PREFIX + 'upgrade.py', b'duplicate')
    return output.getvalue()


def reviewed(files=None, **options):
    carrier, source, _, _, normal, digests = fixture()
    return a.reviewed_files(archive(carrier, normal if files is None else files, **options), carrier, source, digests)


def args():
    carrier, source, _, _, files, digests = fixture()
    return SimpleNamespace(source_sha=source, carrier_sha=carrier, archive_sha256=a.sha(archive(carrier, files)),
                           file_hashes_json=json.dumps(digests, sort_keys=True))


class AcquireTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.root.chmod(0o700)
        old_umask = os.umask(0o077); os.umask(old_umask)
        self.addCleanup(os.umask, old_umask)

    def test_only_full_immutable_carrier_and_fixed_public_origin_are_allowed(self):
        for value in ('main', 'c' * 12, '../path', 'c' * 40 + '?synthetic=ignored', 'C' * 40):
            with self.subTest(value=value), self.assertRaises(a.AcquireError): a.archive_url(value)
        self.assertEqual(a.archive_url('c' * 40), 'https://codeload.github.com/billy285/t24-crm/zip/' + 'c' * 40)

    def test_only_five_approved_files_selected_and_unrelated_content_not_installed(self):
        _, _, _, _, files, _ = fixture()
        selected = reviewed({**files, 'app/backend/private.db': b'unselected synthetic bytes', 'other/runtime.env': b'unselected'})
        self.assertEqual(set(selected), set(a.SELECTED.values()))
        self.assertEqual(len(selected), 5)
        self.assertFalse(any(name.endswith(('.env', '.db')) for name in selected))

    def test_missing_tampered_or_nonregular_selected_files_are_rejected(self):
        for selected in a.SELECTED:
            with self.subTest(selected=selected):
                _, _, _, _, files, _ = fixture(); changed = deepcopy(files); changed[selected] += b'tampered'
                with self.assertRaisesRegex(a.AcquireError, 'REVIEWED_SELECTED_HASH_DRIFT'): reviewed(changed)
                del files[selected]
                with self.assertRaisesRegex(a.AcquireError, 'COMPLETE_STRIPE_CARRIER_REQUIRED'): reviewed(files)
                for kind in ('link', 'directory', 'fifo'):
                    with self.subTest(kind=kind), self.assertRaisesRegex(a.AcquireError, 'REGULAR_UNENCRYPTED_SELECTED_FILE_REQUIRED'):
                        reviewed(**{kind: selected})

    def test_duplicate_entry_and_every_noncanonical_archive_entry_are_rejected(self):
        with patch('warnings.warn'), self.assertRaisesRegex(a.AcquireError, 'UNIQUE_BOUNDED_ARCHIVE_INVENTORY_REQUIRED'):
            reviewed(duplicate=True)
        for name in ('../escape', '/absolute', 'app/../../escape', 'app//uncanonical', 'app\\escape'):
            _, _, _, _, files, _ = fixture()
            with self.subTest(name=name), self.assertRaisesRegex(a.AcquireError, 'CANONICAL_ARCHIVE_PATH_REQUIRED'):
                reviewed({**files, name: b'unselected'})
        carrier, source, _, _, files, digests = fixture()
        with self.assertRaisesRegex(a.AcquireError, 'CANONICAL_ARCHIVE_PATH_REQUIRED'):
            a.reviewed_files(archive('d' * 40, files), carrier, source, digests)

    def test_file_hash_argument_set_and_new_source_must_be_exact(self):
        carrier, source, _, _, files, digests = fixture(); blob = archive(carrier, files)
        for values in ({}, {**digests, 'unreviewed.py': 'a' * 64}, {**digests, 'upgrade.py': 'invalid'}):
            with self.subTest(values=tuple(values)), self.assertRaisesRegex(a.AcquireError, 'EXACT_REVIEWED_STATIC_HASHES_REQUIRED'):
                a.reviewed_files(blob, carrier, source, values)
        for value in (a.BACKEND_SOURCE, 'invalid'):
            with self.subTest(value=value), self.assertRaisesRegex(a.AcquireError, 'NEW_REVIEWED_STRIPE_SOURCE_REQUIRED'):
                a.reviewed_files(blob, carrier, value, digests)
        with self.assertRaisesRegex(a.AcquireError, 'EXACT_STRIPE_REPORT_MANIFEST_BINDING_REQUIRED'):
            a.reviewed_files(blob, carrier, 'a' * 40, digests)

    def test_rehashed_manifest_cannot_expand_or_rebind_release(self):
        changes = (('format_version', 2), ('stage', 'OTHER_STAGE'), ('source_sha', 'd' * 40),
            ('frontend_version', 'd' * 12), ('baseline_private_source_sha', 'd' * 40),
            ('base_private_image', 'sha256:' + 'd' * 64), ('runtime_dependency_changes', True),
            ('credentials_included', True), ('production_access', True), ('deployed', True),
            ('payload_sha256', 'd' * 64), ('frozen_manifest_sha256', 'd' * 64),
            ('backend_regression_tests_expected_minimum', 1172))
        for key, value in changes:
            with self.subTest(key=key):
                carrier, source, manifest, _, files, digests = fixture()
                manifest[key] = value; content = json.dumps(manifest, sort_keys=True).encode()
                files[a.PREFIX + 'artifacts/stripe-report-manifest.json'] = content
                digests['stripe-report-manifest.json'] = a.sha(content)
                with self.assertRaisesRegex(a.AcquireError, 'EXACT_STRIPE_REPORT_MANIFEST_BINDING_REQUIRED'):
                    a.reviewed_files(archive(carrier, files), carrier, source, digests)

    def test_rehashed_frozen_document_cannot_change_reviewed_stage_or_source_binding(self):
        changes = (('format_version', 2), ('stage', 'PREPARED'), ('source_sha', 'd' * 40),
            ('baseline_private_source_sha', 'd' * 40), ('base_private_image', 'sha256:' + 'd' * 64),
            ('frontend_version', 'd' * 12), ('backend_regression_tests_minimum', 1172))
        for key, value in changes:
            with self.subTest(key=key):
                carrier, source, manifest, frozen, files, digests = fixture()
                frozen[key] = value; frozen_bytes = json.dumps(frozen, sort_keys=True).encode()
                files[a.PREFIX + 'artifacts/frozen-source.json'] = frozen_bytes
                digests['frozen-source.json'] = a.sha(frozen_bytes)
                manifest['frozen_manifest_sha256'] = digests['frozen-source.json']
                manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
                files[a.PREFIX + 'artifacts/stripe-report-manifest.json'] = manifest_bytes
                digests['stripe-report-manifest.json'] = a.sha(manifest_bytes)
                with self.assertRaisesRegex(a.AcquireError, 'EXACT_STRIPE_REPORT_MANIFEST_BINDING_REQUIRED'):
                    a.reviewed_files(archive(carrier, files), carrier, source, digests)

    def test_selected_archive_and_file_sizes_are_bounded(self):
        carrier, source, _, _, files, digests = fixture(); blob = archive(carrier, files)
        with patch.object(a, 'MAX_ARCHIVE_BYTES', len(blob) - 1), self.assertRaisesRegex(a.AcquireError, 'ARCHIVE_SIZE_LIMIT'):
            a.reviewed_files(blob, carrier, source, digests)
        with patch.object(a, 'MAX_SELECTED_BYTES', 8), self.assertRaisesRegex(a.AcquireError, 'SELECTED_TOTAL_SIZE_LIMIT'):
            a.reviewed_files(blob, carrier, source, digests)

    def test_download_checks_archive_hash_size_status_and_origin_without_network(self):
        for kind in ('hash', 'size', 'origin', 'status'):
            with self.subTest(kind=kind):
                response = Mock(); response.status = 200; response.geturl.return_value = a.archive_url('c' * 40); response.read.return_value = b'expected'
                if kind == 'hash': response.read.return_value = b'changed'
                elif kind == 'size': response.read.return_value = b'x' * (a.MAX_ARCHIVE_BYTES + 1)
                elif kind == 'origin': response.geturl.return_value = 'https://other.example.invalid/'
                else: response.status = 302
                opener = Mock(); opener.open.return_value = nullcontext(response)
                with patch.object(a.urllib.request, 'build_opener', return_value=opener), self.assertRaises(a.AcquireError):
                    a.download('c' * 40, a.sha(b'expected'))
        with self.assertRaisesRegex(a.AcquireError, 'DOWNLOAD_REDIRECT_REJECTED'):
            a.NoRedirect().redirect_request(None, None, 302, None, None, 'https://other.example.invalid/')

    def test_install_uses_fresh_protected_directory_and_exact_regular_files(self):
        destination = self.root / 'release'; files = reviewed()
        a.install(files, destination, b'{}\n')
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
        self.assertEqual({path.name for path in destination.iterdir()}, set(files) | {'acquired.json'})
        for name, data in files.items():
            self.assertEqual((destination / name).read_bytes(), data)
            self.assertEqual(stat.S_IMODE((destination / name).stat().st_mode), 0o600)
            self.assertFalse((destination / name).is_symlink())
        with self.assertRaisesRegex(a.AcquireError, 'FRESH_EXACT_RELEASE_DIRECTORY_REQUIRED'):
            a.install(files, destination, b'{}\n')
        with self.assertRaisesRegex(a.AcquireError, 'ONLY_COMPLETE_REVIEWED_STATIC_FILES_REQUIRED'):
            a.install({**files, 'unapproved.py': b'bad'}, self.root / 'other', b'{}\n')
        self.assertFalse((self.root / 'other').exists())

    def test_writable_parent_or_symlink_destination_rejected_without_writes(self):
        self.root.chmod(0o777)
        with self.assertRaisesRegex(a.AcquireError, 'PROTECTED_DIRECTORY_REQUIRED'):
            a.install(reviewed(), self.root / 'release', b'{}\n')
        self.assertFalse((self.root / 'release').exists()); self.root.chmod(0o700)
        (self.root / 'linked').symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(a.AcquireError, 'FRESH_EXACT_RELEASE_DIRECTORY_REQUIRED'):
            a.install(reviewed(), self.root / 'linked', b'{}\n')

    def test_replaced_parent_cannot_redirect_descriptor_bound_writes(self):
        parent = self.root / 'protected'; parent.mkdir(mode=0o700); target = parent / 'release'
        real_open = os.open; replaced = False
        def replacement(name, flags, *args, **kwargs):
            nonlocal replaced
            if kwargs.get('dir_fd') is not None and flags & os.O_CREAT and not replaced:
                parent.rename(self.root / 'retained'); parent.mkdir(mode=0o700); target.mkdir(mode=0o700); replaced = True
            return real_open(name, flags, *args, **kwargs)
        with patch.object(a.os, 'open', side_effect=replacement), self.assertRaisesRegex(a.AcquireError, 'RELEASE_DIRECTORY_IDENTITY_DRIFT'):
            a.install(reviewed(), target, b'{}\n')
        self.assertTrue(replaced); self.assertEqual(list(target.iterdir()), [])
        self.assertEqual((self.root / 'retained/release/upgrade.py').read_bytes(), reviewed()['upgrade.py'])

    def test_bad_archive_or_manifest_binding_never_installs(self):
        carrier, _, _, _, files, _ = fixture()
        corrupted = deepcopy(files); corrupted[a.PREFIX + 'upgrade.py'] += b'tampered'
        for blob, error in ((b'not a zip', zipfile.BadZipFile), (archive(carrier, corrupted), a.AcquireError)):
            with self.subTest(error=error), patch.object(a.os, 'geteuid', return_value=0), patch.object(a.socket, 'gethostname', return_value=a.HOST), patch.object(a, 'ROOT', self.root), patch.object(a, 'protected_directory'), patch.object(a, 'download', return_value=blob), patch.object(a, 'install') as install:
                with self.assertRaises(error): a.main(args())
                install.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_main_success_writes_only_five_bound_files_and_hash_receipt_to_fresh_local_directory(self):
        carrier, _, _, _, files, digests = fixture(); owner = os.geteuid(); first = True
        original_protected = a.protected_directory
        def local_uid():
            nonlocal first
            if first: first = False; return 0
            return owner
        def local_protected(path, ancestors=False):
            # Only the synthetic temporary ROOT's ancestors substitute for the
            # server's root-owned /opt chain; installation protection is real.
            return original_protected(path, ancestors=False)
        with patch.object(a.os, 'geteuid', side_effect=local_uid), patch.object(a.socket, 'gethostname', return_value=a.HOST), patch.object(a, 'ROOT', self.root), patch.object(a, 'protected_directory', side_effect=local_protected), patch.object(a, 'download', return_value=archive(carrier, files)), redirect_stdout(io.StringIO()):
            report = a.main(args())
        destination = self.root / ('stripe-report-' + SOURCE[:12] + '-20261012')
        self.assertEqual(report['directory'], str(destination)); self.assertEqual(report['files'], digests)
        self.assertEqual(json.loads((destination / 'acquired.json').read_bytes()), report)
        self.assertEqual({path.name for path in destination.iterdir()}, set(a.SELECTED.values()) | {'acquired.json'})
        for key in ('deployed', 'backend_services_modified', 'databases_modified', 'credentials_included', 'public_assets_published'):
            self.assertIs(report[key], False)

    def test_wrong_user_host_or_hash_arguments_cannot_download_or_install(self):
        for user, host in ((1000, a.HOST), (0, 'wrong-host')):
            with self.subTest(user=user, host=host), patch.object(a.os, 'geteuid', return_value=user), patch.object(a.socket, 'gethostname', return_value=host), patch.object(a, 'download') as download, patch.object(a, 'install') as install:
                with self.assertRaises(a.AcquireError): a.main(args())
                download.assert_not_called(); install.assert_not_called()
        for attribute, value in (('source_sha', 'main'), ('carrier_sha', 'c' * 12), ('archive_sha256', 'not-a-hash')):
            values = args(); setattr(values, attribute, value)
            with self.subTest(attribute=attribute), patch.object(a.os, 'geteuid', return_value=0), patch.object(a.socket, 'gethostname', return_value=a.HOST), patch.object(a, 'download') as download, patch.object(a, 'install') as install:
                with self.assertRaises(a.AcquireError): a.main(values)
                download.assert_not_called(); install.assert_not_called()

    def test_incomplete_cli_file_hash_json_is_rejected_before_download_or_install(self):
        for hashes in ({}, {'unexpected.py': 'a' * 64}):
            values = args(); values.file_hashes_json = json.dumps(hashes)
            with self.subTest(hashes=hashes), patch.object(a.os, 'geteuid', return_value=0), patch.object(a.socket, 'gethostname', return_value=a.HOST), patch.object(a, 'ROOT', self.root), patch.object(a, 'protected_directory'), patch.object(a, 'download') as download, patch.object(a, 'install') as install:
                with self.assertRaisesRegex(a.AcquireError, 'COMPLETE_HASH_ARGUMENTS_REQUIRED'): a.main(values)
                download.assert_not_called(); install.assert_not_called()

    def test_safe_cli_rejects_without_echoing_accidental_sensitive_arguments(self):
        with self.assertRaisesRegex(a.AcquireError, '^ARGUMENTS_REJECTED$'):
            a.SafeParser().parse_args(['--sensitive=synthetic-placeholder'])


if __name__ == '__main__': unittest.main()
