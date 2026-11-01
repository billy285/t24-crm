"""Independent Publisher credential guards; no provider, SQL or Docker access.

Filesystem/JSON primitives retain the reviewed CRM activation checks. App and
runtime identities deliberately remain unknown until the corresponding work
has been reviewed; importing this module cannot make an activation eligible.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
APP_ID = '3037236509957803'
CONFIG_ID = '2328579691236435'
CONFIG_FREEZE_SHA = '570dcfb3c372233f1fd115e59dd085247697d530a3b6248ecfb8c3d3fb48c3d4'
BUSINESS_ID = '1772407487098568'
FORBIDDEN_APP_IDS = frozenset({'1139445441758834', '1625116099132983'})
FORBIDDEN_CONFIG_IDS = frozenset({'1146714154579519', '1786801695686024', '941072098875174'})
GRAPH_VERSION = 'v26.0'
SOURCE_SHA = '95588aa2e630784a419704bb4ce3da89965586e6'
FRONTEND = 'd2dbd67fa15d'
DEPLOYED_SHA = '023f31cc430a80a47d29099cfe1c2470696073516556d9c763069f60cc735ebc'
RELEASE_TOOL_SHA = '3fe35f4fa23bb22db32134221a90eeed79b48079253c2cfbc3dc35f6bc0fcdad'
IMAGE = 'sha256:4797556daa7b98dbeeae6c31364d4f3411645c324902e0f8b922cf1180a7af53'
ORIGINAL_ID = '8df71750e65a06114286eb146aef3374ce368681a689655c16a85058fc6b82f2'
SCHEMA_REVISION = 'cefa9b12a358'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
ORIGIN = 'https://t24-crm.com'
CALLBACK_PATH = '/api/v1/meta-operations/oauth/callback'
CALLBACK = ORIGIN + CALLBACK_PATH
SCOPES = ('instagram_basic', 'instagram_content_publish', 'instagram_manage_comments', 'pages_manage_engagement',
          'pages_manage_posts', 'pages_read_engagement', 'pages_read_user_content', 'pages_show_list')
OPS_KEYS = frozenset('T24_META_OPS_' + name for name in ('ENABLED', 'EXECUTION_ENABLED', 'SCHEDULER_ENABLED', 'APP_ID',
    'APP_SECRET', 'TOKEN_KEY', 'CONFIG_ID', 'GRAPH_VERSION', 'PUBLIC_URL', 'EXPECTED_SCOPES', 'LOGIN_CONFIG_REVIEWED'))
ROOT = Path('/opt/t24-crm/releases/meta-operations-activation-20261101')
SECRET_ROOT = Path('/opt/t24-crm/secrets/meta-operations')
TRANSFERS = SECRET_ROOT / 'transfers'
ENV_FILE = SECRET_ROOT / 'runtime.env'
FS_ANCHOR = Path('/opt/t24-crm')
OWNER_UID = 0
H = lambda body: hashlib.sha256(body).hexdigest()


class GuardError(RuntimeError): pass


def need(ok, code):
    if not ok: raise GuardError(code)


def runtime_pins_ready():
    need(all(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) and value != '0'*64
             for value in (DEPLOYED_SHA, RELEASE_TOOL_SHA, ORIGINAL_ID)) and
         isinstance(SOURCE_SHA, str) and re.fullmatch('[a-f0-9]{40}', SOURCE_SHA) and SOURCE_SHA != '0'*40 and
         isinstance(FRONTEND, str) and re.fullmatch('[a-f0-9]{12}', FRONTEND) and FRONTEND != '0'*12 and
         isinstance(IMAGE, str) and re.fullmatch('sha256:[a-f0-9]{64}', IMAGE),
         'ACTUAL_DEPLOYED_OPERATIONS_RUNTIME_REQUIRED')


def pins_ready():
    runtime_pins_ready()
    need(isinstance(APP_ID, str) and re.fullmatch('[0-9]{10,25}', APP_ID) and APP_ID not in FORBIDDEN_APP_IDS and
         isinstance(CONFIG_ID, str) and re.fullmatch('[0-9]{1,80}', CONFIG_ID) and CONFIG_ID not in FORBIDDEN_CONFIG_IDS and
         isinstance(BUSINESS_ID, str) and re.fullmatch('[0-9]{1,80}', BUSINESS_ID) and
         isinstance(GRAPH_VERSION, str) and re.fullmatch(r'v[1-9][0-9]{0,2}[.][0-9]{1,2}', GRAPH_VERSION) and
         isinstance(CONFIG_FREEZE_SHA, str) and re.fullmatch('[a-f0-9]{64}', CONFIG_FREEZE_SHA) and CONFIG_FREEZE_SHA != '0'*64,
         'ACTUAL_SEPARATE_PUBLISHER_APP_CONFIG_AND_REVIEW_REQUIRED')


def server_guard():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, 'DUPLICATE_JSON_KEY_REJECTED'); value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(GuardError('NONFINITE_JSON_REJECTED')))
    except (ValueError, TypeError, UnicodeError, RecursionError): raise GuardError('STRICT_JSON_REQUIRED') from None
    need(isinstance(value, dict), 'JSON_OBJECT_REQUIRED'); return value


def _canonical(path):
    path = Path(path)
    need(path.is_absolute() and path == path.absolute() and path.resolve() == path and FS_ANCHOR in (path, *path.parents), 'CANONICAL_PROTECTED_PATH_REQUIRED')
    return path


def _parents(path):
    path = _canonical(path); rows = []; current = path if path == FS_ANCHOR else path.parent
    while True:
        rows.append(current)
        if current == FS_ANCHOR: break
        need(current != current.parent, 'EXACT_PROTECTED_ANCHOR_REQUIRED'); current = current.parent
    for parent in reversed(rows):
        row = parent.lstat()
        need(stat.S_ISDIR(row.st_mode) and row.st_uid == OWNER_UID and not row.st_mode & 0o022, 'PROTECTED_PARENT_REQUIRED')
    return path


def directory(path, exact_mode=0o700):
    path = _parents(path); row = path.lstat()
    need(stat.S_ISDIR(row.st_mode) and row.st_uid == OWNER_UID and (stat.S_IMODE(row.st_mode) == exact_mode if exact_mode is not None else not row.st_mode & 0o022), 'PROTECTED_DIRECTORY_REQUIRED')
    return row


def fsync_dir(path):
    path = _canonical(path); directory(path, exact_mode=None)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def mkdir(path):
    path = _parents(path)
    try: path.mkdir(mode=0o700)
    except FileExistsError: pass
    directory(path); fsync_dir(path.parent)


def read(path, maximum=1048576, sha=None):
    path = _parents(path); before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == OWNER_UID and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600, 'PROTECTED_FILE_REQUIRED')
    need(type(maximum) is int and 0 <= maximum <= 16*1024**2, 'BOUNDED_PROTECTED_READ_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno()); body = stream.read(maximum+1)
    after = path.lstat(); fields = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns, row.st_uid, row.st_mode, row.st_nlink)
    need(fields(before) == fields(opened) == fields(after) and len(body) <= maximum and (sha is None or isinstance(sha, str) and re.fullmatch('[a-f0-9]{64}', sha) and H(body) == sha), 'PROTECTED_READ_DRIFT_OR_HASH_REJECTED')
    return body


def write(path, value):
    path = _parents(path)
    body = value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    need(len(body) <= 16*1024**2, 'BOUNDED_PROTECTED_WRITE_REQUIRED')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        row = os.fstat(stream.fileno()); need(row.st_uid == OWNER_UID and stat.S_IMODE(row.st_mode) == 0o600 and row.st_nlink == 1, 'EXCLUSIVE_PROTECTED_FILE_REQUIRED')
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    fsync_dir(path.parent); return H(body)


def validate_credentials(value):
    pins_ready()
    need(isinstance(value, dict) and set(value) == {'app_id', 'app_secret'} and value['app_id'] == APP_ID, 'EXACT_PUBLISHER_CREDENTIAL_OBJECT_REQUIRED')
    secret = value['app_secret']
    need(isinstance(secret, str) and re.fullmatch('[A-Za-z0-9_-]{16,128}', secret), 'PUBLISHER_SECRET_FORMAT_REQUIRES_REVIEW')
    return APP_ID, secret


def validate_ops_env(rows):
    pins_ready(); need(isinstance(rows, list) and len(rows) == len(OPS_KEYS), 'EXACT_ELEVEN_OPS_KEYS_REQUIRED'); result = {}
    for row in rows:
        need(isinstance(row, str) and '=' in row and not any(ch in row for ch in '\r\n\0'), 'STRICT_OPS_ENV_ROW_REQUIRED')
        key, value = row.split('=', 1); need(key in OPS_KEYS and key not in result and value, 'EXACT_UNIQUE_NONEMPTY_OPS_KEY_REQUIRED'); result[key] = value
    need(set(result) == OPS_KEYS, 'EXACT_ELEVEN_OPS_KEYS_REQUIRED')
    expected = {'ENABLED': 'true', 'EXECUTION_ENABLED': 'false', 'SCHEDULER_ENABLED': 'false', 'APP_ID': APP_ID, 'CONFIG_ID': CONFIG_ID,
                'GRAPH_VERSION': GRAPH_VERSION, 'PUBLIC_URL': ORIGIN, 'EXPECTED_SCOPES': ','.join(SCOPES), 'LOGIN_CONFIG_REVIEWED': 'true'}
    need(all(result['T24_META_OPS_'+name] == value for name, value in expected.items()), 'EXACT_REVIEWED_PUBLISHER_CONFIG_EXECUTION_OFF_REQUIRED')
    validate_credentials({'app_id': result['T24_META_OPS_APP_ID'], 'app_secret': result['T24_META_OPS_APP_SECRET']})
    try: raw = base64.b64decode(result['T24_META_OPS_TOKEN_KEY'], altchars=b'-_', validate=True)
    except (ValueError, TypeError): raise GuardError('INDEPENDENT_FERNET_KEY_FORMAT_REQUIRED') from None
    need(len(raw) == 32 and base64.urlsafe_b64encode(raw).decode() == result['T24_META_OPS_TOKEN_KEY'], 'INDEPENDENT_FERNET_KEY_FORMAT_REQUIRED')
    return result


def old_environment(environment):
    need(isinstance(environment, list), 'VERIFIED_OLD_RUNTIME_ENVIRONMENT_REQUIRED'); values = {}
    for row in environment:
        need(isinstance(row, str) and '=' in row and not any(ch in row for ch in '\r\n\0'), 'STRICT_OLD_RUNTIME_ENV_REQUIRED')
        key, value = row.split('=', 1); need(key not in values, 'DUPLICATE_OLD_RUNTIME_KEY'); values[key] = value
    need(not any(key.startswith('T24_META_OPS_') for key in values), 'ORIGINAL_OPS_ENVIRONMENT_MUST_BE_ABSENT')
    need(values.get('T24_META_ENABLED') == 'true' and values.get('T24_META_APP_ID') == '1139445441758834' and
         values.get('T24_META_CONFIG_ID') == '1146714154579519' and values.get('T24_META_APP_SECRET') and values.get('T24_META_TOKEN_KEY'), 'EXACT_EXISTING_READ_META_ENVIRONMENT_REQUIRED')
    return values


def independent_fernet_key(environment):
    values = old_environment(environment)
    retained = {values.get(name) for name in ('T24_META_TOKEN_KEY', 'T24_GBP_TOKEN_KEY', 'MASK_KEY', 'PRIVATE_WORKSPACE_ENCRYPTION_KEY') if values.get(name)}
    for _ in range(3):
        value = base64.urlsafe_b64encode(os.urandom(32)).decode()
        if value not in retained: return value
    raise GuardError('PUBLISHER_KEY_COLLIDES_WITH_EXISTING_RUNTIME_KEY')
