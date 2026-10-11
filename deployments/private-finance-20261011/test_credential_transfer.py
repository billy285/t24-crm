"""Offline synthetic credentials only; no API, server, database or service use."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

spec = importlib.util.spec_from_file_location('private_credential_transfer', Path(__file__).with_name('credential_transfer.py'))
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)

KEY = 'rk_live_SYNTHETICONLY123456789'
SECRET = 'SYNTHETIC_EXISTING_PRIVATE_SECRET_ONLY_12345678'


class CredentialTransferTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.root.chmod(0o700)
        env = self.root / 'runtime.env'
        self.env_blob = ('PRIVATE_WORKSPACE_OWNER_IDS=4\nPRIVATE_WORKSPACE_ENCRYPTION_KEY=' + SECRET + '\n').encode()
        env.write_bytes(self.env_blob); env.chmod(0o600)
        self.patches = []
        for name, value in {'CONFIG': self.root, 'ENV': env, 'TRANSFERS': self.root / 'credential-transfers',
                            'BOOTSTRAP': self.root / 'stripe-bootstrap.json', 'ENV_SHA': transfer.sha(self.env_blob)}.items():
            patch = mock.patch.object(transfer, name, value); patch.start(); self.patches.append(patch)
        for patch in (mock.patch.object(transfer.os, 'geteuid', return_value=0),
                      mock.patch.object(transfer.socket, 'gethostname', return_value=transfer.HOST)):
            patch.start(); self.patches.append(patch)
        self.original_lstat = Path.lstat

        def root_owned(path, *args, **kwargs):
            value = self.original_lstat(path, *args, **kwargs)
            return SimpleNamespace(**{name: getattr(value, name) for name in dir(value) if name.startswith('st_') and name != 'st_uid'}, st_uid=0)

        patch = mock.patch.object(Path, 'lstat', root_owned); patch.start(); self.patches.append(patch)
        # The synthetic directory is under the current user's temporary root;
        # emulate only its root-owned parent chain. Real path/mode checks remain.
        def synthetic_directory(path):
            transfer.need(path.resolve() == path and path.is_dir() and
                          stat.S_IMODE(path.stat().st_mode) == 0o700, 'DIRECTORY_PROTECTION_REJECTED')

        self.real_directory_guard = transfer.protected_directory
        patch = mock.patch.object(transfer, 'protected_directory', synthetic_directory); patch.start(); self.patches.append(patch)
        self.addCleanup(lambda: [patch.stop() for patch in reversed(self.patches)])

    def encrypted_input(self, context, *, override=None, label=None):
        payload = {'source_id': 'stripe', 'account_id': transfer.ACCOUNT, 'mode': 'live', 'api_key': KEY}
        if override: payload.update(override)
        public = serialization.load_pem_public_key(context['public_pem'].encode())
        ciphertext = public.encrypt(transfer.encoded(payload), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(), label=transfer.oaep_label(context) if label is None else label))
        directory = transfer.TRANSFERS / context['transfer_id']
        for name, value in [('ciphertext.bin', ciphertext), ('context.json', transfer.encoded(context))]:
            path = directory / name
            if path.exists(): path.unlink()
            transfer.write_exclusive(path, value)
        return directory

    def receive(self, context):
        directory = transfer.TRANSFERS / context['transfer_id']
        return transfer.receive(context['transfer_id'], ciphertext_file=directory / 'ciphertext.bin',
                                context_file=directory / 'context.json')

    def test_roundtrip_seals_only_ciphertext_and_preserves_runtime_and_permissions(self):
        context = transfer.prepare(sealed_crypto='host')
        self.assertEqual(set(context), transfer.PUBLIC_KEYS)
        directory = self.encrypted_input(context)
        receipt = self.receive(context)
        self.assertFalse((directory / 'private.pem').exists())
        self.assertEqual(transfer.ENV.read_bytes(), self.env_blob)
        self.assertEqual(receipt['stage'], 'STRIPE_BOOTSTRAP_SEALED_NOT_CONNECTED')
        self.assertFalse(receipt['actual_api_verification'])
        self.assertFalse(receipt['runtime_env_changed'] or receipt['databases_changed'] or receipt['services_changed'])
        payload = transfer.get_bootstrap(sealed_crypto='host')
        self.assertEqual(payload['credentials'], {'api_key': KEY, 'stripe_account_id': transfer.ACCOUNT, 'mode': 'live'})
        self.assertEqual(payload['metadata']['authorization']['read_permissions'], list(transfer.READ_CLAIMS))
        self.assertFalse(payload['metadata']['authorization']['actual_api_verification'])
        for path in self.root.rglob('*'):
            if path.is_file() and path != transfer.ENV:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertNotIn(KEY.encode(), path.read_bytes())
                self.assertNotIn(SECRET.encode(), path.read_bytes())
        self.assertNotIn(KEY, json.dumps([context, receipt]))

    def test_host_runtime_hash_and_root_configuration_guards_fail_closed(self):
        for target, value, code in [('hostname', 'wrong-host', 'ROOT_HOST_REJECTED'),
                                   ('uid', 500, 'ROOT_HOST_REJECTED'), ('hash', '0' * 64, 'RUNTIME_ENV_HASH_DRIFT')]:
            with self.subTest(target=target):
                patch = (mock.patch.object(transfer.socket, 'gethostname', return_value=value) if target == 'hostname' else
                         mock.patch.object(transfer.os, 'geteuid', return_value=value) if target == 'uid' else
                         mock.patch.object(transfer, 'ENV_SHA', value))
                with patch, self.assertRaisesRegex(transfer.TransferError, code): transfer.prepare(sealed_crypto='host')
        self.root.chmod(0o755)
        with self.assertRaisesRegex(transfer.TransferError, 'DIRECTORY_PROTECTION_REJECTED'): transfer.environment_guard()

    def test_actual_directory_parent_chain_rejects_nonroot_or_writable_parent(self):
        real = self.original_lstat
        def safe_chain(path):
            actual = real(path)
            return SimpleNamespace(st_mode=stat.S_IFDIR | (0o700 if path == self.root else 0o755), st_uid=0)
        with mock.patch.object(Path, 'lstat', safe_chain): self.real_directory_guard(self.root)
        for changed in ({'st_uid': 501, 'st_mode': stat.S_IFDIR | 0o755},
                        {'st_uid': 0, 'st_mode': stat.S_IFDIR | 0o777}):
            def bad_chain(path):
                return SimpleNamespace(**changed) if path == self.root.parent else safe_chain(path)
            with mock.patch.object(Path, 'lstat', bad_chain), self.assertRaisesRegex(transfer.TransferError, 'PARENT_PROTECTION_REJECTED'):
                self.real_directory_guard(self.root)

    def test_environment_and_input_files_reject_symlink_hardlink_and_world_readable(self):
        target = self.root / 'regular'; target.write_bytes(b'synthetic'); target.chmod(0o600)
        linked = self.root / 'linked'; linked.symlink_to(target)
        with self.assertRaisesRegex(transfer.TransferError, 'FILE_PATH_REJECTED'): transfer.read_protected(linked)
        linked.unlink(); os.link(target, linked)
        with self.assertRaisesRegex(transfer.TransferError, 'FILE_PROTECTION_REJECTED'): transfer.read_protected(target)
        linked.unlink(); target.chmod(0o644)
        with self.assertRaisesRegex(transfer.TransferError, 'FILE_PROTECTION_REJECTED'): transfer.read_protected(target)

    def test_expired_context_and_context_swapping_cannot_claim_transfer(self):
        context = transfer.prepare(sealed_crypto='host'); directory = self.encrypted_input(context)
        for now in (context['expires_at'], context['expires_at'] + 3600):
            with mock.patch.object(transfer.time, 'time', return_value=now), self.assertRaisesRegex(transfer.TransferError, 'TRANSFER_EXPIRED'):
                self.receive(context)
        changed = dict(context, public_sha256='f' * 64)
        (directory / 'context.json').write_bytes(transfer.encoded(changed))
        with self.assertRaisesRegex(transfer.TransferError, 'CONTEXT_BINDING_REJECTED'): self.receive(context)
        self.assertFalse((directory / 'claimed.json').exists())

    def test_invalid_oaep_label_burns_transfer_without_plaintext_file(self):
        context = transfer.prepare(sealed_crypto='host'); directory = self.encrypted_input(context, label=b'wrong-label')
        with self.assertRaisesRegex(transfer.TransferError, 'CIPHERTEXT_REJECTED'): self.receive(context)
        self.assertFalse(transfer.BOOTSTRAP.exists()); self.assertTrue((directory / 'private.pem').exists())
        self.encrypted_input(context)
        with self.assertRaisesRegex(transfer.TransferError, 'TRANSFER_ALREADY_USED'): self.receive(context)

    def test_wrong_source_account_mode_key_and_extra_fields_never_seal(self):
        for changed in ({'source_id': 'gmail'}, {'account_id': 'acct_SyntheticWrongAccount'}, {'mode': 'test'},
                        {'api_key': 'rk_test_SYNTHETICONLY1234'}, {'api_key': 'sk_live_SYNTHETICONLY1234'},
                        {'write': True}):
            with self.subTest(changed=changed):
                context = transfer.prepare(sealed_crypto='host'); self.encrypted_input(context, override=changed)
                with self.assertRaises(transfer.TransferError): self.receive(context)
                self.assertFalse(transfer.BOOTSTRAP.exists())

    def test_existing_bootstrap_is_never_overwritten_deleted_or_claimed(self):
        original = b'EXISTING_ENCRYPTED_PRIVATE_CREDENTIALS'
        transfer.write_exclusive(transfer.BOOTSTRAP, original)
        context = transfer.prepare(sealed_crypto='host'); directory = self.encrypted_input(context)
        with self.assertRaisesRegex(transfer.TransferError, 'EXISTING_BOOTSTRAP_PRESERVED'): self.receive(context)
        self.assertEqual(transfer.BOOTSTRAP.read_bytes(), original)
        self.assertFalse((directory / 'claimed.json').exists())

    def test_concurrent_receive_is_one_use_and_returns_at_most_one_receipt(self):
        context = transfer.prepare(sealed_crypto='host'); self.encrypted_input(context)
        def attempted():
            try: return self.receive(context)
            except transfer.TransferError as error: return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: attempted(), range(2)))
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        self.assertIn(next(value for value in results if isinstance(value, str)),
                      {'TRANSFER_ALREADY_USED', 'EXISTING_BOOTSTRAP_PRESERVED'})

    def test_receipt_failure_retains_rsa_and_sealed_store_for_manual_review(self):
        context = transfer.prepare(sealed_crypto='host'); directory = self.encrypted_input(context)
        original = transfer.write_exclusive
        def fail_receipt(path, blob):
            if path.name == 'receipt.json': raise OSError('synthetic disk failure')
            return original(path, blob)
        with mock.patch.object(transfer, 'write_exclusive', fail_receipt), self.assertRaises(OSError): self.receive(context)
        self.assertTrue(transfer.BOOTSTRAP.exists()); self.assertTrue((directory / 'private.pem').exists())
        with self.assertRaises(FileNotFoundError): transfer.get_bootstrap(sealed_crypto='host')

    def test_bootstrap_tampering_is_rejected_before_plaintext_return(self):
        context = transfer.prepare(sealed_crypto='host'); self.encrypted_input(context); self.receive(context)
        original = transfer.BOOTSTRAP.read_bytes()
        for changed in ({'mode': 'test'}, {'stripe_account_id': 'acct_SyntheticOther'}, {'owner_id': '5'},
                        {'encrypted_payload': 'gAAAAASYNTHETICCHANGED'}):
            payload = json.loads(original); payload.update(changed)
            transfer.BOOTSTRAP.write_bytes(transfer.encoded(payload))
            with self.assertRaises(transfer.TransferError): transfer.get_bootstrap(sealed_crypto='host')
        transfer.BOOTSTRAP.write_bytes(original + b'\n')
        with self.assertRaisesRegex(transfer.TransferError, 'BOOTSTRAP_RECEIPT_REJECTED'): transfer.get_bootstrap(sealed_crypto='host')

    def test_docker_adapter_is_explicit_pinned_offline_and_secrets_only_use_stdin(self):
        captured = []
        def fake_run(argv, *, input=None, timeout=30):
            captured.append((argv, input, timeout))
            if argv[:3] == ['docker', 'image', 'inspect']: return transfer.encoded([{'Id': transfer.PRIVATE_IMAGE, 'Config': {'Env': ['PATH=/usr/bin', 'APP_ENV=production']}}])
            return transfer.Crypto('host').fernet('seal', SECRET, b'synthetic_payload')
        with mock.patch.object(transfer, 'run', fake_run):
            crypto = transfer.Crypto('docker'); sealed = crypto.fernet('seal', SECRET, b'synthetic_payload')
        self.assertGreater(len(sealed), 20)
        argv, packet, timeout = captured[-1]
        self.assertEqual(argv[:3], ['docker', 'run', '--rm'])
        self.assertIn(transfer.PRIVATE_IMAGE, argv)
        self.assertEqual(argv[argv.index('--network') + 1], 'none')
        self.assertEqual(argv[argv.index('--log-driver') + 1], 'none')
        for forbidden in ('--env', '-e', '--mount', '--volume', '-v'): self.assertNotIn(forbidden, argv)
        self.assertNotIn(SECRET, ' '.join(argv)); self.assertNotIn('synthetic_payload', ' '.join(argv))
        self.assertEqual(json.loads(packet)['secret'], SECRET); self.assertLessEqual(timeout, 30)
        with mock.patch.object(transfer, 'host_crypto_available', return_value=False), self.assertRaisesRegex(transfer.TransferError, 'HOST_CRYPTO_UNAVAILABLE'):
            transfer.Crypto('auto')

    @unittest.skipUnless(shutil.which('openssl') and subprocess.run(['openssl', 'version'], capture_output=True, check=False).stdout.startswith(b'OpenSSL '),
                         'Actual OpenSSL unavailable; local macOS has LibreSSL')
    def test_openssl_rsa_fallback_is_compatible_with_webcrypto_oaep_sha256(self):
        real_run = transfer.run
        def fixed_docker(argv, **kwargs):
            if argv[:3] == ['docker', 'image', 'inspect']: return transfer.encoded([{'Id': transfer.PRIVATE_IMAGE, 'Config': {'Env': []}}])
            return real_run(argv, **kwargs)
        with mock.patch.object(transfer, 'host_crypto_available', return_value=False), mock.patch.object(transfer, 'run', fixed_docker):
            crypto = transfer.Crypto('docker')
            public = crypto.generate(self.root / 'synthetic-rsa.pem')
            context = {'transfer_id': 'b' * 32, 'public_sha256': transfer.sha(public), 'expires_at': 2000000000}
            key = serialization.load_pem_public_key(public)
            ciphertext = key.encrypt(b'synthetic-plaintext-only', padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                algorithm=hashes.SHA256(), label=transfer.oaep_label(context)))
            self.assertEqual(crypto.decrypt_rsa(self.root / 'synthetic-rsa.pem', ciphertext, transfer.oaep_label(context)), b'synthetic-plaintext-only')

    def test_openssl_fallback_command_contract_is_fixed_and_plaintext_stays_in_memory(self):
        called = []
        private_path = self.root / 'synthetic-rsa.pem'
        label = b'SYNTHETIC_CONTEXT_ONLY'
        def fake_run(argv, *, input=None, timeout=30):
            called.append((argv, input))
            if argv == ['openssl', 'version']: return b'OpenSSL 3.0.0 synthetic-offline\n'
            if argv[:3] == ['docker', 'image', 'inspect']: return transfer.encoded([{'Id': transfer.PRIVATE_IMAGE, 'Config': {'Env': []}}])
            if argv[:2] == ['openssl', 'genpkey']:
                self.assertIn('rsa_keygen_bits:3072', argv)
                self.assertIn('rsa_keygen_pubexp:65537', argv)
                private_path.write_bytes(b'SYNTHETIC_RSA_PRIVATE_PEM_NOT_A_REAL_KEY')
                return b''
            if argv[:2] == ['openssl', 'pkey']: return b'-----BEGIN PUBLIC KEY-----\nSYNTHETIC\n-----END PUBLIC KEY-----\n'
            if argv[:2] == ['openssl', 'pkeyutl']:
                self.assertIn('rsa_padding_mode:oaep', argv)
                self.assertIn('rsa_oaep_md:sha256', argv)
                self.assertIn('rsa_mgf1_md:sha256', argv)
                self.assertIn('rsa_oaep_label:' + label.hex(), argv)
                self.assertEqual(input, b'SYNTHETIC_CIPHERTEXT')
                self.assertNotIn('PLAINTEXT', ' '.join(argv))
                return b'SYNTHETIC_PLAINTEXT'
            self.fail('Unexpected crypto command')
        with mock.patch.object(transfer, 'host_crypto_available', return_value=False), mock.patch.object(transfer, 'run', fake_run):
            crypto = transfer.Crypto('docker'); crypto.generate(private_path)
            self.assertEqual(crypto.decrypt_rsa(private_path, b'SYNTHETIC_CIPHERTEXT', label), b'SYNTHETIC_PLAINTEXT')
        self.assertEqual(len(called), 5)
        self.assertNotIn(b'SYNTHETIC_PLAINTEXT', private_path.read_bytes())

    def test_docker_image_cannot_bake_or_inherit_private_credentials(self):
        for environment in (None, ['PRIVATE_WORKSPACE_ENCRYPTION_KEY=' + SECRET], ['STRIPE_KEY=' + KEY],
                            ['PATH=' + KEY], ['APP_ENV=production', 'APP_ENV=production']):
            with self.subTest(environment=environment):
                image = {'Id': transfer.PRIVATE_IMAGE, 'Config': {'Env': environment}}
                with mock.patch.object(transfer, 'run', return_value=transfer.encoded([image])), self.assertRaisesRegex(transfer.TransferError, 'CRYPTO_IMAGE_ENV_REJECTED'):
                    transfer.Crypto('docker')

    def test_cli_never_outputs_plaintext_raw_exception_or_automatic_connect(self):
        output = io.StringIO()
        with mock.patch.object(transfer, 'prepare', side_effect=ValueError(KEY + SECRET)), redirect_stdout(output):
            self.assertEqual(transfer.main(['prepare']), 1)
        self.assertEqual(json.loads(output.getvalue()), {'stage': 'CREDENTIAL_TRANSFER_REJECTED', 'error': 'TRANSFER_FAILED'})
        self.assertNotIn(KEY, output.getvalue()); self.assertNotIn(SECRET, output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(transfer.main(['prepare', '--api-key', KEY]), 1)
        self.assertEqual(json.loads(output.getvalue())['error'], 'ARGUMENTS_REJECTED')
        self.assertNotIn(KEY, output.getvalue())
        code = Path(transfer.__file__).read_text()
        for forbidden in ('import requests', 'import httpx', 'import sqlite3', 'import services', 'os.environ[', 'shell=True'):
            self.assertNotIn(forbidden, code)


if __name__ == '__main__':
    unittest.main()
