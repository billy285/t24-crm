"""Configuration-only Google activation bounds. No provider or business writes."""
import base64
import hashlib
import json
import os
import re
import resource
import socket
import stat
import subprocess
import sys
import types
from pathlib import Path

sys.dont_write_bytecode = True
FILE_OWNER = 0  # Test seam; production commands never override this constant.
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = '7431d1986b81328fcc822e3e13641e4d03b6b9bf'
FRONTEND = 'c648c284143e'
REVISION = 'c8d3e5f6a702'
IMAGE = 'sha256:0a058c4927abd5c2216fe65a8f36a42705d7064ad91248339ca997aa3d019ccb'
PRIOR = Path('/opt/t24-crm/releases/google-business-7431d1986b81-20261030')
PRIOR_SHA = '16fbbcf5ef322684256fff82af3b25146a5efaff48f7947a398c480020895cab'
LEGACY = Path('/opt/t24-crm/releases/stripe-history-daily-scan-285c3377e6d0-20261019/release.py')
LEGACY_SHA = 'bd5f1af9c67b6e268d7d1b4d91ae4b122895480b10bb6ef777b79770ca2392c0'
PINS = Path('/opt/t24-crm/releases/commission-service-month-preflight-20261013.json')
PINS_SHA = 'af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161'
ROOT = Path('/opt/t24-crm/releases/google-business-activation-7431d1986b81-20261030')
SECRET_ROOT = Path('/opt/t24-crm/secrets/google-business')
ENV_FILE = SECRET_ROOT / 'runtime.env'
TRANSFERS = SECRET_ROOT / 'transfers'
CALLBACK = '/api/v1/google-business/oauth/callback'
ORIGIN = 'https://t24-crm.com'
PROJECT_ID = 't24-beauty-os-20260823'
PROJECT_NUMBER = '58950527996'
GBP_NAMES = frozenset('T24_GBP_' + name for name in ('ENABLED', 'API_APPROVED', 'CLIENT_ID', 'CLIENT_SECRET', 'TOKEN_KEY', 'PUBLIC_URL'))
TABLES = frozenset('google_business_' + name for name in ('connections', 'oauth_states', 'bindings', 'grants', 'actions'))
H = lambda body: hashlib.sha256(body).hexdigest()
_LEGACY_CACHE = None


class GuardError(RuntimeError):
    pass


def need(ok, code):
    if not ok:
        raise GuardError(code)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def strict_json(blob):
    def pairs(rows):
        result = {}
        for name, value in rows:
            need(name not in result, 'DUPLICATE_JSON_FIELD')
            result[name] = value
        return result
    return json.loads(blob, object_pairs_hook=pairs)


def safe_code(error):
    return str(error) if isinstance(error, GuardError) and re.fullmatch('[A-Z][A-Z0-9_]{0,95}', str(error)) else 'ACTIVATION_FAILED'


def server_guard():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_SERVER_ROOT_REQUIRED')
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def directory(path, *, exact_mode=None):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, 'PROTECTED_DIRECTORY_PATH_REQUIRED')
    for parent in (path, *path.parents):
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, FILE_OWNER} and not info.st_mode & 0o022, 'PROTECTED_PARENT_REQUIRED')
    if exact_mode is not None:
        need(stat.S_IMODE(path.lstat().st_mode) == exact_mode, 'EXACT_DIRECTORY_MODE_REQUIRED')


def mkdir(path):
    path = Path(path)
    directory(path.parent)
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
        fsync_dir(path.parent)
    directory(path, exact_mode=0o700)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read(path, expected=None, maximum=4 * 1024 * 1024):
    path = Path(path)
    directory(path.parent)
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == FILE_OWNER and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600, 'PROTECTED_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        need((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), 'FILE_CHANGED_DURING_OPEN')
        body = stream.read(maximum + 1)
    need(len(body) <= maximum, 'FILE_SIZE_REJECTED')
    after = path.lstat()
    need((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns), 'FILE_CHANGED_DURING_READ')
    need(expected is None or H(body) == expected, 'FILE_HASH_DRIFT')
    return body


def write(path, value):
    path = Path(path)
    directory(path.parent)
    body = value if isinstance(value, bytes) else encoded(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    fsync_dir(path.parent)
    return H(body)


def run(args, code, *, data=None, timeout=60):
    # Never expose subprocess stdout/stderr on failure; they can contain secrets.
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    need(result.returncode == 0, code)
    return result.stdout


def legacy():
    global _LEGACY_CACHE
    blob = read(LEGACY, LEGACY_SHA)
    if _LEGACY_CACHE is not None:
        return _LEGACY_CACHE
    module = types.ModuleType('_google_activation_retained')
    module.__file__ = str(LEGACY)
    exec(compile(blob, str(LEGACY), 'exec'), module.__dict__)
    _LEGACY_CACHE = module
    return module


def env_dict(rows):
    need(isinstance(rows, list), 'ENVIRONMENT_LIST_REQUIRED')
    values = {}
    for row in rows:
        need(isinstance(row, str) and '=' in row and not any(char in row for char in '\r\n\0'), 'ENVIRONMENT_FORMAT_REJECTED')
        name, value = row.split('=', 1)
        need(bool(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name)) and name not in values, 'DUPLICATE_OR_INVALID_ENVIRONMENT_KEY')
        values[name] = value
    return values


def no_gbp(info):
    values = env_dict(info['Config']['Env'])
    need(not any(name.startswith('T24_GBP_') for name in values), 'GBP_ENVIRONMENT_MUST_BE_ABSENT')


def validate_credentials(value):
    need(isinstance(value, dict) and set(value) == {'client_id', 'client_secret'}, 'EXACT_CLIENT_FIELDS_REQUIRED')
    client, secret = value['client_id'], value['client_secret']
    need(isinstance(client, str) and bool(re.fullmatch(PROJECT_NUMBER + r'-[A-Za-z0-9_-]{10,140}\.apps\.googleusercontent\.com', client)), 'APPROVED_PROJECT_CLIENT_REQUIRED')
    need(isinstance(secret, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{16,128}', secret)), 'CLIENT_SECRET_FORMAT_REJECTED')
    return client, secret


def validate_gbp_env(rows):
    value = env_dict(rows)
    need(set(value) == GBP_NAMES, 'EXACT_SIX_GBP_KEYS_REQUIRED')
    need(value['T24_GBP_ENABLED'] == 'true' and value['T24_GBP_API_APPROVED'] == 'true' and value['T24_GBP_PUBLIC_URL'] == ORIGIN, 'GBP_ACTIVATION_SCOPE_REJECTED')
    validate_credentials({'client_id': value['T24_GBP_CLIENT_ID'], 'client_secret': value['T24_GBP_CLIENT_SECRET']})
    try:
        key = base64.b64decode(value['T24_GBP_TOKEN_KEY'].encode(), altchars=b'-_', validate=True)
        need(len(key) == 32 and base64.urlsafe_b64encode(key).decode() == value['T24_GBP_TOKEN_KEY'], 'DEDICATED_FERNET_KEY_REQUIRED')
    except (ValueError, UnicodeError):
        raise GuardError('DEDICATED_FERNET_KEY_REQUIRED') from None
    return value


def read_gbp_env():
    body = read(ENV_FILE, maximum=4096)
    need(body.endswith(b'\n'), 'COMPLETE_ENV_FILE_REQUIRED')
    return validate_gbp_env(body.decode('ascii').splitlines())
