"""Meta-only credential transport primitives; no Docker, SQL or provider access."""
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
APP_ID = '1139445441758834'
FORBIDDEN_APP_ID = '1625116099132983'
BUSINESS_ID = '1772407487098568'
FORBIDDEN_CONFIG_ID = '1786801695686024'
CONFIG_ID = '1146714154579519'
FORBIDDEN_CONFIG_IDS = frozenset({'1786801695686024','941072098875174'})
GRAPH_VERSION = 'v26.0'
CONFIG_FREEZE_SHA = 'e60ab18e11e5efb3388a67d6fa4d21738a71d22d57622e555989c7b2b9fd6f5b'
SOURCE_SHA = 'a03766539ef3430f350f467652511a43ee3c4abf'
FRONTEND = '58d2c585210f'
DEPLOYED_SHA = 'a6bde4b7511061fe8a63cadd658f780de23b3e23d7bc163c7c1e9c1811bb7354'
SCHEMA_REVISION = 'bde8da01f247'
IMAGE = 'sha256:e136fbc267e7bb81d069c597eb2c4ddab7e5f39bf183bbe6cd6cbccc7a19919d'
ORIGINAL_ID = '96192b84519f1fa5b6070d4eac6529e44a8f9307833293a5d9db8af0474ea4d1'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
ORIGIN = 'https://t24-crm.com'
CALLBACK_PATH = '/api/v1/meta-business/oauth/callback'
CALLBACK = ORIGIN + CALLBACK_PATH
READ_SCOPES = ('instagram_basic', 'pages_read_engagement', 'pages_show_list')
META_KEYS = frozenset('T24_META_' + name for name in ('ENABLED','APP_ID','APP_SECRET','TOKEN_KEY','CONFIG_ID','GRAPH_VERSION','PUBLIC_URL','EXPECTED_SCOPES','LOGIN_CONFIG_REVIEWED'))
ROOT = Path('/opt/t24-crm/releases/meta-business-crm-activation-a03766539ef3-20261101')
SECRET_ROOT = Path('/opt/t24-crm/secrets/meta-business-crm')
LEGACY_ENV_FILE = Path('/opt/t24-crm/secrets/meta-business/runtime.env')
TRANSFERS = SECRET_ROOT / 'transfers'
ENV_FILE = SECRET_ROOT / 'runtime.env'
FS_ANCHOR = Path('/opt/t24-crm')
OWNER_UID = 0
H = lambda body: hashlib.sha256(body).hexdigest()


class GuardError(RuntimeError): pass


def need(ok, code):
    if not ok: raise GuardError(code)


def pins_ready():
    need(isinstance(APP_ID,str) and bool(re.fullmatch('[0-9]{1,80}',APP_ID)) and APP_ID != FORBIDDEN_APP_ID
         and isinstance(BUSINESS_ID,str) and bool(re.fullmatch('[0-9]{1,80}',BUSINESS_ID))
         and isinstance(CONFIG_ID,str) and bool(re.fullmatch('[0-9]{1,80}',CONFIG_ID)) and CONFIG_ID not in FORBIDDEN_CONFIG_IDS
         and isinstance(GRAPH_VERSION,str) and bool(re.fullmatch(r'v[1-9][0-9]{0,2}[.][0-9]{1,2}',GRAPH_VERSION))
         and isinstance(CONFIG_FREEZE_SHA,str) and bool(re.fullmatch('[a-f0-9]{64}',CONFIG_FREEZE_SHA)) and CONFIG_FREEZE_SHA != '0'*64,
         'ACTUAL_NEW_APP_USER_CONFIG_VERSION_AND_REVIEW_REQUIRED')


def server_guard():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0,0)); os.umask(0o077)


def strict_json(raw):
    def pairs(items):
        value={}
        for key,item in items:
            need(key not in value, 'DUPLICATE_JSON_KEY_REJECTED'); value[key]=item
        return value
    try:
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(GuardError('NONFINITE_JSON_REJECTED')))
    except (ValueError,TypeError,UnicodeError,RecursionError): raise GuardError('STRICT_JSON_REQUIRED') from None
    need(isinstance(value,dict),'JSON_OBJECT_REQUIRED'); return value


def _canonical(path):
    path=Path(path)
    need(path.is_absolute() and path == path.absolute() and path.resolve() == path and FS_ANCHOR in (path,*path.parents), 'CANONICAL_PROTECTED_PATH_REQUIRED')
    return path


def _parents(path):
    path=_canonical(path)
    rows=[]; current=path if path == FS_ANCHOR else path.parent
    while True:
        rows.append(current)
        if current == FS_ANCHOR: break
        need(current != current.parent,'EXACT_PROTECTED_ANCHOR_REQUIRED'); current=current.parent
    for parent in reversed(rows):
        row=parent.lstat()
        need(stat.S_ISDIR(row.st_mode) and row.st_uid == OWNER_UID and not row.st_mode & 0o022, 'PROTECTED_PARENT_REQUIRED')
    return path


def directory(path, exact_mode=0o700):
    path=_parents(path); row=path.lstat()
    need(stat.S_ISDIR(row.st_mode) and row.st_uid == OWNER_UID and (stat.S_IMODE(row.st_mode)==exact_mode if exact_mode is not None else not row.st_mode & 0o022),'PROTECTED_DIRECTORY_REQUIRED')
    return row


def fsync_dir(path):
    path=_canonical(path); directory(path, exact_mode=None)
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def mkdir(path):
    path=_parents(path)
    try: path.mkdir(mode=0o700)
    except FileExistsError: pass
    directory(path); fsync_dir(path.parent)


def read(path, maximum=1048576, sha=None):
    path=_parents(path); before=path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid==OWNER_UID and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600,'PROTECTED_FILE_REQUIRED')
    need(type(maximum) is int and 0<=maximum<=16*1024**2,'BOUNDED_PROTECTED_READ_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        opened=os.fstat(stream.fileno()); body=stream.read(maximum+1)
    after=path.lstat(); fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(after) and len(body)<=maximum and (sha is None or isinstance(sha,str) and re.fullmatch('[a-f0-9]{64}',sha) and H(body)==sha),'PROTECTED_READ_DRIFT_OR_HASH_REJECTED')
    return body


def write(path, value):
    path=_parents(path)
    body=value if isinstance(value,bytes) else (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    need(len(body)<=16*1024**2,'BOUNDED_PROTECTED_WRITE_REQUIRED')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        row=os.fstat(stream.fileno()); need(row.st_uid==OWNER_UID and stat.S_IMODE(row.st_mode)==0o600 and row.st_nlink==1,'EXCLUSIVE_PROTECTED_FILE_REQUIRED')
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    fsync_dir(path.parent); return H(body)


def validate_credentials(value):
    pins_ready()
    need(isinstance(value,dict) and set(value)=={'app_id','app_secret'} and value['app_id']==APP_ID,'EXACT_META_APP_CREDENTIAL_OBJECT_REQUIRED')
    secret=value['app_secret']
    need(isinstance(secret,str) and bool(re.fullmatch('[A-Za-z0-9_-]{16,128}',secret)), 'META_SECRET_FORMAT_REQUIRES_REVIEW')
    return APP_ID,secret


def validate_meta_env(rows):
    pins_ready(); need(isinstance(rows,list) and len(rows)==len(META_KEYS),'EXACT_NINE_META_KEYS_REQUIRED'); result={}
    for row in rows:
        need(isinstance(row,str) and '=' in row and not any(c in row for c in '\r\n\0'),'STRICT_META_ENV_ROW_REQUIRED')
        key,value=row.split('=',1); need(key in META_KEYS and key not in result and value,'EXACT_UNIQUE_NONEMPTY_META_KEY_REQUIRED'); result[key]=value
    need(set(result)==META_KEYS,'EXACT_NINE_META_KEYS_REQUIRED')
    expected={'T24_META_ENABLED':'true','T24_META_APP_ID':APP_ID,'T24_META_CONFIG_ID':CONFIG_ID,'T24_META_GRAPH_VERSION':GRAPH_VERSION,'T24_META_PUBLIC_URL':ORIGIN,'T24_META_EXPECTED_SCOPES':','.join(READ_SCOPES),'T24_META_LOGIN_CONFIG_REVIEWED':'true'}
    need(all(result[name]==value for name,value in expected.items()),'EXACT_REVIEWED_META_PUBLIC_CONFIG_REQUIRED')
    validate_credentials({'app_id':result['T24_META_APP_ID'],'app_secret':result['T24_META_APP_SECRET']})
    try: raw=base64.b64decode(result['T24_META_TOKEN_KEY'],altchars=b'-_',validate=True)
    except (ValueError,TypeError): raise GuardError('INDEPENDENT_FERNET_KEY_FORMAT_REQUIRED') from None
    need(len(raw)==32 and base64.urlsafe_b64encode(raw).decode()==result['T24_META_TOKEN_KEY'],'INDEPENDENT_FERNET_KEY_FORMAT_REQUIRED')
    return result


def independent_fernet_key(environment):
    """New entropy, explicitly distinct from available current runtime keys."""
    need(isinstance(environment,list),'VERIFIED_OLD_RUNTIME_KEYS_REQUIRED');values={}
    for row in environment:
        need(isinstance(row,str) and '=' in row and not any(ch in row for ch in '\r\n\0'),'STRICT_OLD_RUNTIME_ENV_REQUIRED')
        key,value=row.split('=',1);need(key not in values,'DUPLICATE_OLD_RUNTIME_KEY');values[key]=value
    need(bool(values.get('T24_META_TOKEN_KEY')),'VERIFIED_OLD_META_KEY_REQUIRED')
    retained={values.get(name) for name in ('T24_META_TOKEN_KEY','T24_GBP_TOKEN_KEY','MASK_KEY','PRIVATE_WORKSPACE_ENCRYPTION_KEY') if values.get(name)}
    for _ in range(3):
        value=base64.urlsafe_b64encode(os.urandom(32)).decode()
        if value not in retained:return value
    raise GuardError('NEW_META_KEY_COLLIDES_WITH_EXISTING_RUNTIME_KEY')
