"""One-use project-bound RSA transport; dedicated server key and env file only."""
import base64
import fcntl
import json
import os
import re
import resource
import secrets
import time
import core as c
import preflight

TTL = 900


def label(context):
    return ('T24_CRM_GOOGLE_OAUTH_TRANSFER_V1\n' + c.HOST + '\n' + c.PROJECT_ID + '\n' + c.PROJECT_NUMBER + '\n' +
        c.CALLBACK + '\n' + context['transfer_id'] + '\n' + context['public_sha256'] + '\n' + str(context['expires_at'])).encode()


def protected_paths():
    c.mkdir(c.SECRET_ROOT)
    c.mkdir(c.TRANSFERS)
    c.mkdir(c.ROOT)


def prepare():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    preflight.proof()
    protected_paths()
    c.need(not c.ENV_FILE.exists() and not c.ENV_FILE.is_symlink(), 'EXISTING_GOOGLE_CREDENTIALS_PRESERVED')
    transfer_id = secrets.token_hex(16)
    path = c.TRANSFERS / transfer_id
    c.mkdir(path)
    key_path = path / 'private.pem'
    c.write(key_path, b'RESERVED\n')
    c.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-pkeyopt', 'rsa_keygen_pubexp:65537', '-out', str(key_path)], 'TRANSPORT_KEY_GENERATION_FAILED')
    c.read(key_path, maximum=4096)
    public = c.run(['openssl', 'pkey', '-in', str(key_path), '-pubout'], 'TRANSPORT_PUBLIC_EXPORT_FAILED')
    c.need(public.startswith(b'-----BEGIN PUBLIC KEY-----\n') and len(public) < 1024, 'TRANSPORT_PUBLIC_KEY_REJECTED')
    now = int(time.time())
    context = {'transfer_id': transfer_id, 'public_pem': public.decode('ascii'), 'public_sha256': c.H(public),
        'created_at': now, 'expires_at': now + TTL, 'project_id': c.PROJECT_ID, 'project_number': c.PROJECT_NUMBER,
        'callback': c.ORIGIN + c.CALLBACK, 'algorithm': 'RSA-OAEP-SHA256-3072', 'payload_max_bytes': 318}
    context['oaep_label_base64'] = base64.b64encode(label(context)).decode()
    c.write(path / 'context.json', context)
    return {'stage': 'GBP_ACTIVATION_TRANSPORT_READY', **context, 'runtime_changed': False, 'business_writes': False}


def receive(transfer_id, ciphertext):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    c.server_guard()
    c.need(bool(re.fullmatch('[a-f0-9]{32}', transfer_id)), 'TRANSFER_ID_REJECTED')
    c.directory(c.SECRET_ROOT, exact_mode=0o700)
    c.directory(c.TRANSFERS, exact_mode=0o700)
    path = c.TRANSFERS / transfer_id
    c.directory(path, exact_mode=0o700)
    context = c.strict_json(c.read(path / 'context.json', maximum=8192))
    c.need(context['transfer_id'] == transfer_id and context['project_id'] == c.PROJECT_ID and context['project_number'] == c.PROJECT_NUMBER and context['callback'] == c.ORIGIN + c.CALLBACK and context['algorithm'] == 'RSA-OAEP-SHA256-3072', 'TRANSPORT_CONTEXT_REJECTED')
    now = int(time.time())
    c.need(type(context['created_at']) is int and type(context['expires_at']) is int and context['created_at'] <= now < context['expires_at'] == context['created_at'] + TTL, 'TRANSPORT_EXPIRED')
    c.need(context['oaep_label_base64'] == base64.b64encode(label(context)).decode(), 'TRANSPORT_LABEL_DRIFT')
    try:
        raw = base64.b64decode(ciphertext, validate=True)
    except (ValueError, TypeError):
        raise c.GuardError('CIPHERTEXT_REJECTED') from None
    c.need(len(raw) == 384, 'CIPHERTEXT_REJECTED')
    preflight.proof()
    # A single global lock closes simultaneous different-transfer installations.
    lock_path = c.SECRET_ROOT / 'install.lock'
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        c.read(lock_path, maximum=0)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        c.need(not c.ENV_FILE.exists() and not c.ENV_FILE.is_symlink(), 'EXISTING_GOOGLE_CREDENTIALS_PRESERVED')
        c.need(not (path / 'claimed.json').exists(), 'TRANSPORT_ALREADY_USED')
        c.write(path / 'claimed.json', {'claimed_at': now, 'transfer_id': transfer_id})
        key = path / 'private.pem'
        c.read(key, maximum=4096)
        public = c.run(['openssl', 'pkey', '-in', str(key), '-pubout'], 'TRANSPORT_PUBLIC_EXPORT_FAILED')
        c.need(c.H(public) == context['public_sha256'] and public.decode('ascii') == context['public_pem'], 'TRANSPORT_PUBLIC_KEY_DRIFT')
        clear = c.run(['openssl', 'pkeyutl', '-decrypt', '-inkey', str(key), '-pkeyopt', 'rsa_padding_mode:oaep',
            '-pkeyopt', 'rsa_oaep_md:sha256', '-pkeyopt', 'rsa_mgf1_md:sha256', '-pkeyopt', 'rsa_oaep_label:' + label(context).hex()], 'CIPHERTEXT_REJECTED', data=raw)
        c.need(0 < len(clear) <= 318, 'PAYLOAD_SIZE_REJECTED')
        client, secret = c.validate_credentials(c.strict_json(clear))
        values = {'T24_GBP_CLIENT_ID': client, 'T24_GBP_CLIENT_SECRET': secret,
            'T24_GBP_TOKEN_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
            'T24_GBP_PUBLIC_URL': c.ORIGIN, 'T24_GBP_ENABLED': 'true', 'T24_GBP_API_APPROVED': 'true'}
        rows = [name + '=' + values[name] for name in sorted(values)]
        c.validate_gbp_env(rows)
        c.need(int(time.time()) < context['expires_at'], 'TRANSPORT_EXPIRED')
        c.write(c.ENV_FILE, ('\n'.join(rows) + '\n').encode('ascii'))
        receipt = {'stage': 'GBP_ACTIVATION_CREDENTIALS_STORED_NOT_ENABLED', 'project_id': c.PROJECT_ID,
            'project_number': c.PROJECT_NUMBER, 'transfer_id': transfer_id, 'stored_at': now,
            'env_path': str(c.ENV_FILE), 'dedicated_fernet_key_generated': True, 'credential_values_exported': False,
            'runtime_changed': False, 'business_writes': False, 'provider_requests': False}
        c.write(c.ROOT / 'credential-receipt.json', receipt)
        key.unlink()
        c.fsync_dir(path)
        return receipt
    finally:
        os.close(fd)
