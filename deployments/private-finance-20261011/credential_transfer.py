#!/usr/bin/env python3
"""One-use, offline Stripe credential transfer; never connects or deploys.

prepare emits only public_pem/transfer_id/public_sha256/expires_at. Encrypt a
compact UTF-8 JSON object with exactly source_id/account_id/mode/api_key using
RSA-OAEP SHA-256 and oaep_label(context); store its raw ciphertext in the transfer
directory as ciphertext.bin (root 600), and the prepare output as context.json
(root 600). receive seals it under the existing private Fernet key and emits a
non-secret receipt. Permission claims require later actual GET-only probes.

No platform HTTP, runtime.env edits, database/service changes, dependency install,
plaintext key files, plaintext output, shell commands or credential argv/env.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import time

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
ENV_SHA = '180f945729234df79c45f5148663f8407c75be55aa8d4e79107305c03c00f82d'
CONFIG = Path('/opt/t24-crm/private-workspace/config')
ENV = CONFIG / 'runtime.env'
TRANSFERS = CONFIG / 'credential-transfers'
BOOTSTRAP = CONFIG / 'stripe-bootstrap.json'
ACCOUNT = 'acct_1QxFjbIdE9Gt7xxR'
MODE = 'live'
PRIVATE_IMAGE = 'sha256:2ed347b29ba8f29ffeaab26df75e8c5d75c7479b477a1e45e80bdf2b19d098db'
READ_CLAIMS = ('balance', 'charges_and_refunds', 'payment_disputes', 'payouts', 'account_identity')
PUBLIC_KEYS = {'public_pem', 'transfer_id', 'public_sha256', 'expires_at'}
SAFE_IMAGE_ENV_NAMES = {'PATH', 'GPG_KEY', 'PYTHON_VERSION', 'PYTHON_SHA256', 'LANG', 'LC_ALL',
    'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED', 'PIP_NO_CACHE_DIR', 'APP_ENV', 'ENVIRONMENT',
    'LOG_LEVEL', 'PORT', 'TZ', 'HOME'}


class TransferError(RuntimeError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown argv, which might contain a key
        # accidentally passed by an operator. Reject without repeating input.
        raise TransferError('ARGUMENTS_REJECTED')


def need(condition, code):
    if not condition:
        raise TransferError(code)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()


def protected_directory(path):
    need(path.is_absolute() and path.resolve() == path, 'DIRECTORY_PATH_REJECTED')
    info = path.lstat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and
         stat.S_IMODE(info.st_mode) == 0o700, 'DIRECTORY_PROTECTION_REJECTED')
    # All parents must be canonical root-owned directories, never writable by
    # another account; intermediate public 755 directories are allowed.
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and
             not stat.S_IMODE(info.st_mode) & 0o022, 'PARENT_PROTECTION_REJECTED')


def read_protected(path, maximum=65536):
    protected_directory(path.parent)
    need(path.resolve() == path, 'FILE_PATH_REJECTED')
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1 and
         stat.S_IMODE(before.st_mode) == 0o600 and 0 < before.st_size <= maximum,
         'FILE_PROTECTION_REJECTED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        current = os.fstat(stream.fileno())
        need((current.st_dev, current.st_ino, current.st_size) ==
             (before.st_dev, before.st_ino, before.st_size), 'FILE_IDENTITY_CHANGED')
        blob = stream.read(maximum + 1)
    after = path.lstat()
    need(len(blob) == before.st_size and after.st_ino == before.st_ino and
         after.st_mtime_ns == before.st_mtime_ns, 'FILE_CHANGED_DURING_READ')
    return blob


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive(path, blob):
    protected_directory(path.parent)
    need(path.is_absolute() and path.parent.resolve() == path.parent, 'FILE_PATH_REJECTED')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = None
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        fsync_directory(path.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def environment_guard():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'ROOT_HOST_REJECTED')
    protected_directory(CONFIG)
    blob = read_protected(ENV)
    need(sha(blob) == ENV_SHA, 'RUNTIME_ENV_HASH_DRIFT')
    need(blob.endswith(b'\n') and b'\r' not in blob and b'\0' not in blob, 'ENV_FORMAT_REJECTED')
    values = {}
    for row in blob.decode().splitlines():
        need('=' in row, 'ENV_FORMAT_REJECTED')
        name, value = row.split('=', 1)
        need(re.fullmatch(r'[A-Z][A-Z0-9_]*', name) and name not in values, 'ENV_FORMAT_REJECTED')
        values[name] = value
    secret = values.get('PRIVATE_WORKSPACE_ENCRYPTION_KEY', '').strip()
    need(values.get('PRIVATE_WORKSPACE_OWNER_IDS') == '4' and len(secret) >= 32 and
         'replace-with' not in secret.lower() and secret.lower() != 'x' * len(secret), 'ENCRYPTION_BOUNDARY_REJECTED')
    return secret


def run(argv, *, input=None, timeout=30):
    try:
        result = subprocess.run(argv, input=input, capture_output=True, timeout=timeout, check=False)
    except Exception:
        raise TransferError('CRYPTO_PROCESS_FAILED') from None
    # Never expose stderr: a crypto backend must not log captured plaintext.
    need(result.returncode == 0, 'CRYPTO_PROCESS_FAILED')
    return result.stdout


def host_crypto_available():
    return importlib.util.find_spec('cryptography') is not None


class Crypto:
    """Explicit sealed adapter; Docker receives secrets solely over stdin."""
    def __init__(self, sealed='auto'):
        need(sealed in {'auto', 'host', 'docker'}, 'CRYPTO_ADAPTER_REJECTED')
        self.host = host_crypto_available()
        self.sealed = ('host' if self.host else None) if sealed == 'auto' else sealed
        need(self.sealed is not None and (self.sealed != 'host' or self.host), 'HOST_CRYPTO_UNAVAILABLE')
        self.rsa = 'host' if self.host else 'openssl'
        if self.rsa == 'openssl':
            version = run(['openssl', 'version'], timeout=10)
            need(version.startswith(b'OpenSSL '), 'OPENSSL_UNAVAILABLE')
        if self.sealed == 'docker':
            found = json.loads(run(['docker', 'image', 'inspect', PRIVATE_IMAGE], timeout=10))
            need(isinstance(found, list) and len(found) == 1 and found[0].get('Id') == PRIVATE_IMAGE,
                 'PINNED_CRYPTO_IMAGE_MISSING')
            # Image inspection remains in root process memory. A helper must not
            # inherit baked credentials from its image or any runtime container.
            rows = found[0].get('Config', {}).get('Env')
            need(isinstance(rows, list) and len(rows) <= 32, 'CRYPTO_IMAGE_ENV_REJECTED')
            names = set()
            for row in rows:
                need(isinstance(row, str) and '=' in row and len(row) <= 4096, 'CRYPTO_IMAGE_ENV_REJECTED')
                name, value = row.split('=', 1)
                need(name in SAFE_IMAGE_ENV_NAMES and name not in names and
                     not re.search(r'(?:rk_(?:live|test)_|sk_(?:live|test)_|Bearer )', value), 'CRYPTO_IMAGE_ENV_REJECTED')
                names.add(name)

    def generate(self, path):
        if self.rsa == 'host':
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            write_exclusive(path, private.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            return private.public_key().public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo)
        # Reserve exclusively before OpenSSL writes, preventing replacement of
        # an existing key. Transfer directory is root-only and never shared.
        write_exclusive(path, b'RESERVED\n')
        run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072',
             '-pkeyopt', 'rsa_keygen_pubexp:65537', '-out', str(path)])
        read_protected(path, 4096)
        return run(['openssl', 'pkey', '-in', str(path), '-pubout'])

    def decrypt_rsa(self, path, ciphertext, label):
        private_blob = read_protected(path, 4096)
        if self.rsa == 'host':
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
            private = serialization.load_pem_private_key(private_blob, password=None)
            need(isinstance(private, rsa.RSAPrivateKey) and private.key_size == 3072 and
                 private.public_key().public_numbers().e == 65537, 'RSA_KEY_REJECTED')
            try:
                return private.decrypt(ciphertext, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                    algorithm=hashes.SHA256(), label=label))
            except Exception:
                raise TransferError('CIPHERTEXT_REJECTED') from None
        return run(['openssl', 'pkeyutl', '-decrypt', '-inkey', str(path), '-pkeyopt', 'rsa_padding_mode:oaep',
                    '-pkeyopt', 'rsa_oaep_md:sha256', '-pkeyopt', 'rsa_mgf1_md:sha256',
                    '-pkeyopt', 'rsa_oaep_label:' + label.hex()], input=ciphertext)

    def fernet(self, action, secret, value):
        need(action in {'seal', 'open'}, 'CRYPTO_ACTION_REJECTED')
        if self.sealed == 'host':
            from cryptography.fernet import Fernet
            cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
            return cipher.encrypt(value) if action == 'seal' else cipher.decrypt(value)
        script = (
            "import sys,json,base64,hashlib;from cryptography.fernet import Fernet;"
            "p=json.load(sys.stdin);f=Fernet(base64.urlsafe_b64encode(hashlib.sha256(p['secret'].encode()).digest()));"
            "v=base64.b64decode(p['value'],validate=True);"
            "sys.stdout.buffer.write(f.encrypt(v) if p['action']=='seal' else f.decrypt(v))")
        packet = encoded({'action': action, 'secret': secret, 'value': base64.b64encode(value).decode()})
        return run(['docker', 'run', '--rm', '-i', '--log-driver', 'none', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges', '--pids-limit', '32', '--memory', '128m',
                    '--cpus', '1', '--user', '65534:65534', '--entrypoint', 'python', PRIVATE_IMAGE, '-c', script],
                   input=packet)


def oaep_label(context):
    """Browser WebCrypto RSA-OAEP label: UTF-8 encode these exact newline rows."""
    return ('T24_PRIVATE_STRIPE_TRANSFER_V1\n' + context['transfer_id'] + '\n' +
            context['public_sha256'] + '\n' + str(context['expires_at']) + '\nstripe\n' + ACCOUNT + '\nlive').encode()


def transfer_directory(transfer_id):
    need(isinstance(transfer_id, str) and re.fullmatch(r'[a-f0-9]{32}', transfer_id), 'TRANSFER_ID_REJECTED')
    protected_directory(TRANSFERS)
    path = TRANSFERS / transfer_id
    protected_directory(path)
    return path


def prepare(*, sealed_crypto='auto'):
    environment_guard()
    crypto = Crypto(sealed_crypto)
    if not TRANSFERS.exists():
        TRANSFERS.mkdir(mode=0o700)
        fsync_directory(CONFIG)
    protected_directory(TRANSFERS)
    transfer_id = secrets.token_hex(16)
    directory = TRANSFERS / transfer_id
    directory.mkdir(mode=0o700)
    fsync_directory(TRANSFERS)
    public = crypto.generate(directory / 'private.pem')
    need(public.startswith(b'-----BEGIN PUBLIC KEY-----\n') and len(public) <= 1024, 'PUBLIC_KEY_REJECTED')
    now = int(time.time())
    context = {'public_pem': public.decode(), 'transfer_id': transfer_id,
               'public_sha256': sha(public), 'expires_at': now + 3600}
    write_exclusive(directory / 'state.json', encoded({'format_version': 1, 'host': HOST,
        'env_sha256': ENV_SHA, 'source_id': 'stripe', 'account_id': ACCOUNT, 'mode': MODE,
        'created_at': now, 'context': context, 'rsa': crypto.rsa, 'sealed_crypto': crypto.sealed}))
    write_exclusive(directory / 'context.json', encoded(context))
    return context


def validate_payload(blob):
    need(0 < len(blob) <= 318, 'PAYLOAD_SIZE_REJECTED')
    payload = json.loads(blob)
    need(isinstance(payload, dict) and set(payload) == {'source_id', 'account_id', 'mode', 'api_key'} and
         payload['source_id'] == 'stripe' and payload['account_id'] == ACCOUNT and payload['mode'] == MODE,
         'CREDENTIAL_SCOPE_REJECTED')
    need(isinstance(payload['api_key'], str) and re.fullmatch(r'rk_live_[A-Za-z0-9]{8,280}', payload['api_key']),
         'RESTRICTED_LIVE_KEY_REQUIRED')
    return {'credentials': {'api_key': payload['api_key'], 'stripe_account_id': ACCOUNT, 'mode': MODE},
            'metadata': {'source_id': 'stripe', 'stripe_account_id': ACCOUNT, 'mode': MODE,
                'connection_mode': 'restricted_api_key', 'read_only_adapter': True,
                'authorization': {'account_id': ACCOUNT, 'mode': MODE, 'read_permissions': list(READ_CLAIMS),
                    'claim_only': True, 'actual_api_verification': False}}}


def receive(transfer_id, *, ciphertext_file, context_file):
    secret = environment_guard()
    directory = transfer_directory(transfer_id)
    need(ciphertext_file == directory / 'ciphertext.bin' and context_file == directory / 'context.json',
         'INPUT_PATH_REJECTED')
    state = json.loads(read_protected(directory / 'state.json', 8192))
    context = json.loads(read_protected(context_file, 2048))
    need(isinstance(context, dict) and set(context) == PUBLIC_KEYS and context == state.get('context') and
         context.get('transfer_id') == transfer_id and sha(context['public_pem'].encode()) == context['public_sha256'] and
         state.get('format_version') == 1 and state.get('host') == HOST and state.get('env_sha256') == ENV_SHA and
         state.get('source_id') == 'stripe' and state.get('account_id') == ACCOUNT and state.get('mode') == MODE,
         'CONTEXT_BINDING_REJECTED')
    now = int(time.time())
    need(type(state.get('created_at')) is int and type(context.get('expires_at')) is int and
         context['expires_at'] == state['created_at'] + 3600 and state['created_at'] <= now < context['expires_at'],
         'TRANSFER_EXPIRED')
    need(not BOOTSTRAP.exists() and not BOOTSTRAP.is_symlink(), 'EXISTING_BOOTSTRAP_PRESERVED')
    ciphertext = read_protected(ciphertext_file, 384)
    need(len(ciphertext) == 384, 'CIPHERTEXT_SIZE_REJECTED')
    crypto = Crypto(state['sealed_crypto'])
    need(crypto.rsa == state['rsa'], 'CRYPTO_ADAPTER_DRIFT')
    try:
        write_exclusive(directory / 'claimed.json', encoded({'claimed_at': now, 'transfer_id': transfer_id}))
    except FileExistsError:
        raise TransferError('TRANSFER_ALREADY_USED') from None
    # Once claimed, failures cannot be replayed. Existing private credentials are
    # never deleted or overwritten. RSA stays until both sealed file and receipt
    # have been durably saved; an interrupted transfer requires manual review.
    payload = validate_payload(crypto.decrypt_rsa(directory / 'private.pem', ciphertext, oaep_label(context)))
    sealed = crypto.fernet('seal', secret, encoded(payload))
    need(re.fullmatch(rb'[A-Za-z0-9_-]+={0,2}', sealed) and len(sealed) <= 16384, 'SEALED_OUTPUT_REJECTED')
    need(int(time.time()) < context['expires_at'], 'TRANSFER_EXPIRED')
    envelope = {'format_version': 1, 'source_id': 'stripe', 'stripe_account_id': ACCOUNT,
        'mode': MODE, 'owner_id': '4', 'transfer_id': transfer_id, 'sealed_at': now,
        'encryption_scheme': 'fernet-sha256-existing-private-key', 'encrypted_payload': sealed.decode(),
        'requires_connection_probe': True}
    blob = encoded(envelope)
    write_exclusive(BOOTSTRAP, blob)
    receipt = {'stage': 'STRIPE_BOOTSTRAP_SEALED_NOT_CONNECTED', 'transfer_id': transfer_id,
        'source_id': 'stripe', 'account_id': ACCOUNT, 'mode': MODE, 'owner_id': '4',
        'bootstrap_sha256': sha(blob), 'sealed_at': now, 'actual_api_verification': False,
        'runtime_env_changed': False, 'databases_changed': False, 'services_changed': False}
    write_exclusive(directory / 'receipt.json', encoded(receipt))
    (directory / 'private.pem').unlink()
    fsync_directory(directory)
    return receipt


def get_bootstrap(*, sealed_crypto='auto'):
    """In-memory candidate helper input only; no CLI/automatic connection exists."""
    secret = environment_guard()
    bootstrap_blob = read_protected(BOOTSTRAP, 32768)
    envelope = json.loads(bootstrap_blob)
    need(isinstance(envelope, dict) and envelope.get('format_version') == 1 and
         envelope.get('source_id') == 'stripe' and envelope.get('stripe_account_id') == ACCOUNT and
         envelope.get('mode') == MODE and envelope.get('owner_id') == '4' and
         envelope.get('encryption_scheme') == 'fernet-sha256-existing-private-key' and
         envelope.get('requires_connection_probe') is True, 'BOOTSTRAP_SCOPE_REJECTED')
    transfer_id = envelope.get('transfer_id')
    directory = transfer_directory(transfer_id)
    receipt = json.loads(read_protected(directory / 'receipt.json', 4096))
    need(receipt.get('bootstrap_sha256') == sha(bootstrap_blob) and
         receipt.get('stage') == 'STRIPE_BOOTSTRAP_SEALED_NOT_CONNECTED' and
         receipt.get('transfer_id') == transfer_id and receipt.get('actual_api_verification') is False,
         'BOOTSTRAP_RECEIPT_REJECTED')
    payload = json.loads(Crypto(sealed_crypto).fernet('open', secret, envelope['encrypted_payload'].encode()))
    # Revalidate the bound key instead of treating the sealed metadata as API
    # permission proof. Candidate must call existing GET-only connect probes.
    credentials = payload.get('credentials', {}) if isinstance(payload, dict) else {}
    expected = validate_payload(encoded({'source_id': 'stripe', 'account_id': credentials.get('stripe_account_id'),
        'mode': credentials.get('mode'), 'api_key': credentials.get('api_key')}))
    need(payload == expected, 'BOOTSTRAP_PAYLOAD_REJECTED')
    return payload


def main(argv=None):
    parser = SafeParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--sealed-crypto', choices=('auto', 'host', 'docker'), default='auto')
    receive_parser = sub.add_parser('receive')
    receive_parser.add_argument('--transfer-id', required=True)
    receive_parser.add_argument('--ciphertext-file', required=True, type=Path)
    receive_parser.add_argument('--context-file', required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        result = prepare(sealed_crypto=args.sealed_crypto) if args.action == 'prepare' else receive(
            args.transfer_id, ciphertext_file=args.ciphertext_file, context_file=args.context_file)
    except Exception as error:
        code = str(error) if isinstance(error, TransferError) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', str(error)) else 'TRANSFER_FAILED'
        print(json.dumps({'stage': 'CREDENTIAL_TRANSFER_REJECTED', 'error': code}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
