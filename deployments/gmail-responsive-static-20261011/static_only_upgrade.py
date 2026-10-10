#!/usr/bin/env python3
"""Static-only responsive patch. No container, credential or database mutation.

Pinned prior release proof controls current runtime. Raw mail/token/config values
never enter output. Only a fresh public directory and exact Nginx root change are
written. Rollback only restores Nginx static root and never private or CRM data.
"""
import argparse
import fcntl
import hashlib
import itertools
import io
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import socket
import sqlite3
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from uuid import uuid4

SOURCE = 'e23fc0556b7f8e20acd6fb98bfcb653c88f285fa'
VERSION = '5434cc26636a'
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
CRM_ID = 'ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26'
CRM_IMAGE = 'sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
CRM_STARTED = '2026-10-10T17:19:07.948520307Z'
CRM_CONFIG = '2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0'
PRIVATE_IMAGE = 'sha256:42c26eaaa6f6aa847548d4f35abb822a43cd9e9c88629c3c711453d6c1fa0fc9'
PRIVATE_IDS = {'api':'e85e70c9a9d48124cc35aa7fc683d0fb151468f2beb5a929a052f316e7a90da3',
               'worker':'584ffcb43448651568cfd44a736bdf2ee6bf1e0adbf7bfd4778dcccf331193b4'}
CURRENT_ENV_SHA = '6ebb9e3e1e947106bc8c25bdba782d631f5fd8c83ab1487120f5b16420470296'
PRIOR_STATE = Path('/opt/t24-crm/releases/gmail-relevance-938b87d-20261011/switch-state-0bd81d0f522d4cbf9d34497365693593.json')
PRIOR_STATE_SHA = '5f1e1d869c483fe80116648daa53779892d25d526befe0e90ff6e989dda87d1e'
RELEASE = Path('/opt/t24-crm/releases/gmail-responsive-e23fc05-20261011')
PUBLIC = Path('/var/www/t24-crm-public/gmail-responsive-e23fc05-20261011')
OLD_PUBLIC = Path('/var/www/t24-crm-public/gmail-relevance-938b87d-20261011')
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
CONFIG = Path('/opt/t24-crm/private-workspace/config')
ENV = CONFIG/'runtime.env'
BUSINESS = Path('/opt/t24-crm/app/data/crm_prod.db')
PRIVATE_DB = Path('/opt/t24-crm/private-workspace/data/workspace.db')
PREFIX = '/api/v1/private-workspace'
SUFFIXES = {'.html','.js','.css','.json','.png','.jpg','.jpeg','.webp','.gif','.svg','.ico','.txt','.woff','.woff2','.ttf','.webmanifest'}


HEADERS = {
    'X-Frame-Options': 'SAMEORIGIN',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https: wss:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), geolocation=(), microphone=(self)',
    'X-Content-Type-Options': 'nosniff',
}

class SwitchError(RuntimeError):
    pass

def need(condition, code):
    if not condition:
        raise SwitchError(code)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())

def secure(path, directory=False, mode=None):
    info = path.lstat()
    need(path.resolve() == path and not stat.S_ISLNK(info.st_mode), 'PATH_ALIAS_REJECTED')
    need(info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o077, 'PROTECTED_PATH_REQUIRED')
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
         'PROTECTED_TYPE_REQUIRED')
    if mode is not None:
        need(stat.S_IMODE(info.st_mode) == mode, 'PROTECTED_MODE_REQUIRED')
    return info

def read_protected(path, maximum=65536):
    before = secure(path, mode=0o600)
    need(before.st_size <= maximum, 'PROTECTED_FILE_SIZE_REJECTED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        observed = os.fstat(stream.fileno())
        need((before.st_ino, before.st_dev) == (observed.st_ino, observed.st_dev), 'PROTECTED_FILE_CHANGED')
        data = stream.read(maximum + 1)
    need(len(data) <= maximum, 'PROTECTED_FILE_SIZE_REJECTED')
    return data

def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())

def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def save(path, value, replace=False):
    data = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    if replace:
        secure(path, mode=0o600)
        temporary = path.parent / ('.' + path.name + '-' + uuid4().hex)
        write_new(temporary, data)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    else:
        write_new(path, data)

def inspect(identity, optional=False):
    result = subprocess.run(['docker', 'inspect', identity], capture_output=True, timeout=30, check=False)
    if optional and result.returncode:
        return None
    need(result.returncode == 0, 'CONTAINER_INSPECT_FAILED')
    value = json.loads(result.stdout)
    need(len(value) == 1, 'SINGLE_CONTAINER_REQUIRED')
    return value[0]

def config_hash(value):
    return digest({'Config': value['Config'], 'HostConfig': value['HostConfig'],
                   'Mounts': sorted(value['Mounts'], key=digest)})

def crm_check(require_healthy=True):
    info = inspect('t24-crm')
    need(info['Id'] == CRM_ID and info['Image'] == CRM_IMAGE and info['State']['StartedAt'] == CRM_STARTED,
         'CRM_RUNTIME_DRIFT')
    if require_healthy:
        need(info['State']['Running'] and info['State'].get('Health', {}).get('Status') == 'healthy', 'CRM_HEALTH_DRIFT')
    need(len(info['Mounts']) == 2, 'CRM_MOUNT_COUNT_DRIFT')
    variants = [digest({'Config': info['Config'], 'HostConfig': info['HostConfig'], 'Mounts': list(order)})
                for order in itertools.permutations(info['Mounts'])]
    need(CRM_CONFIG in variants, 'CRM_CONFIGURATION_DRIFT')
    need(info['HostConfig']['PortBindings'].get('8000/tcp') == [{'HostIp': '127.0.0.1', 'HostPort': '8000'}],
         'CRM_PORT_DRIFT')
    return {'id': CRM_ID, 'image': CRM_IMAGE, 'started_at': CRM_STARTED, 'configuration_sha256': CRM_CONFIG}

def business_fingerprints(path=BUSINESS):
    need(path.is_file() and not path.is_symlink() and path.resolve() == path, 'BUSINESS_PATH_DRIFT')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'BUSINESS_INTEGRITY_FAILED')
        tables = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        need(len(tables) == 83 and not any(t.startswith('private_') for t in tables), 'BUSINESS_SCHEMA_DRIFT')
        need(db.execute('SELECT version_num FROM alembic_version').fetchall() == [('ab6d8e2f0411',)], 'BUSINESS_SCHEMA_HEAD_DRIFT')
        need(db.execute('SELECT role,status FROM employees WHERE id=4').fetchall() == [('super_admin', 'active')], 'OWNER_IDENTITY_DRIFT')
        result = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = db.execute('SELECT * FROM ' + quoted).fetchall()
            encoded = sorted(json.dumps(list(row), ensure_ascii=False, sort_keys=True,
                             default=lambda value: {'hex': value.hex()}, separators=(',', ':')) for row in rows)
            result[table] = {'count': len(rows), 'sha256': sha(('\n'.join(encoded)).encode())}
        schema = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        return {'schema_sha256': digest(schema), 'tables': result}

def read_nginx():
    info = NGINX.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and
         NGINX.resolve() == NGINX and not info.st_mode & 0o022 and info.st_size <= 65536, 'NGINX_PATH_UNTRUSTED')
    fd = os.open(NGINX, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        observed = os.fstat(stream.fileno())
        need((observed.st_dev, observed.st_ino) == (info.st_dev, info.st_ino), 'NGINX_CHANGED_DURING_READ')
        return stream.read(65537)

def atomic_nginx(data, allowed_hashes):
    info = NGINX.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and
         NGINX.resolve() == NGINX and not info.st_mode & 0o022, 'NGINX_PATH_UNTRUSTED')
    need(sha(read_nginx()) in allowed_hashes, 'NGINX_CONCURRENT_CHANGE')
    temporary = NGINX.parent / ('.t24-static-' + uuid4().hex)
    write_new(temporary, data)
    temporary.chmod(stat.S_IMODE(info.st_mode))
    need(sha(read_nginx()) in allowed_hashes and NGINX.stat().st_ino == info.st_ino, 'NGINX_CHANGED_BEFORE_REPLACE')
    os.replace(temporary, NGINX)
    fsync_directory(NGINX.parent)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def request(url, maximum=16 * 1024**2):
    need(url.startswith('https://t24-crm.com/') or url.startswith('http://127.0.0.1:800'), 'HTTP_TARGET_REJECTED')
    opener = urllib.request.build_opener(NoRedirect())
    try:
        response = opener.open(url, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read(maximum + 1)
        need(len(body) <= maximum, 'HTTP_RESPONSE_TOO_LARGE')
        return response.code, {k.lower(): v for k, v in response.headers.items()}, body

def unauthenticated_check(public=False):
    origin = 'https://t24-crm.com' if public else 'http://127.0.0.1:8001'
    for suffix in ('', '/access'):
        code, headers, _ = request(origin + PREFIX + suffix, 65536)
        need(code == 401 and no_store(headers), 'PRIVATE_AUTH_OR_CACHE_DRIFT')

def no_store(headers):
    return 'no-store' in {part.strip().lower() for part in headers.get('cache-control', '').split(',')}

def header_check(headers):
    need(all(headers.get(name.lower()) == value for name, value in HEADERS.items()), 'PUBLIC_SECURITY_HEADERS_DRIFT')

def current_assets(root, manifest):
    # Cached old assets remain readable on disk; HTTP checks follow only this
    # index's reachable JS/CSS graph so retained history cannot cause thousands
    # of serial requests during a live switch.
    index = (root / 'index.html').read_text()
    pending = [name.lstrip('/') for name in re.findall(r'(?:src|href)=["\x27](/assets/[A-Za-z0-9_.-]+\.(?:js|css))["\x27]', index)]
    need(pending and any(name.endswith('.js') for name in pending), 'CURRENT_ASSET_ENTRY_MISSING')
    pattern = re.compile(r'["\x27](?:(?:\./|/assets/|assets/))?([A-Za-z0-9_-]+\.(?:js|css))["\x27]')
    graph = {}
    while pending:
        name = pending.pop()
        if name in graph:
            continue
        need(name in manifest and re.fullmatch(r'assets/[A-Za-z0-9_.-]+\.(?:js|css)', name), 'CURRENT_ASSET_SCOPE_DRIFT')
        path = root / name
        need(path.is_file() and path.resolve() == path and not path.is_symlink() and sha(path.read_bytes()) == manifest[name],
             'CURRENT_ASSET_BYTES_DRIFT')
        graph[name] = manifest[name]
        need(len(graph) <= 256, 'CURRENT_ASSET_GRAPH_LIMIT')
        if name.endswith('.js'):
            pending += ['assets/' + referenced for referenced in pattern.findall(path.read_text())]
    return graph

def public_check(manifest, version, root=PUBLIC, verify_services=True):
    whole_deadline = time.monotonic() + 120
    graph = current_assets(root, manifest)
    deadline = time.monotonic() + 15
    while True:
        try:
            code, headers, body = request('https://t24-crm.com/app-version.json?gmail_upgrade=' + uuid4().hex, 4096)
            matched = code == 200 and json.loads(body) == {'version': version}
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            matched = False
        if matched:
            break
        need(time.monotonic() < deadline, 'PUBLIC_VERSION_PROPAGATION_FAILED')
        time.sleep(1)
    header_check(headers)
    need(no_store(headers), 'PUBLIC_VERSION_CACHE_DRIFT')
    code, headers, body = request('https://t24-crm.com/?gmail_upgrade=' + uuid4().hex)
    need(code == 200 and sha(body) == manifest['index.html'], 'PUBLIC_INDEX_BYTES_DRIFT')
    header_check(headers)
    for name, expected in graph.items():
        need(time.monotonic() < whole_deadline, 'PUBLIC_ASSET_VERIFICATION_DEADLINE')
        relative = PurePosixPath(name)
        need(relative.as_posix() == name and '..' not in relative.parts and not relative.is_absolute(), 'PUBLIC_ASSET_PATH_INVALID')
        code, asset_headers, content = request('https://t24-crm.com/' + name)
        need(code == 200 and sha(content) == expected, 'PUBLIC_ASSET_BYTES_DRIFT')
    if verify_services:
        unauthenticated_check(True)
        need(request('https://t24-crm.com/ready', 4096)[0] == 200, 'PUBLIC_CRM_READY_FAILED')


def run(command, code, timeout=30):
    # A reviewed allowlist excludes all Docker mutation and database commands.
    need(command in (['nginx','-t'],['systemctl','reload','nginx']) or
         command[:6]==['runuser','-u','www-data','--','python3','-c'], 'COMMAND_SCOPE_REJECTED')
    result=subprocess.run(command,capture_output=True,timeout=timeout,check=False)
    need(result.returncode==0,code)
    return result.stdout


def prior_state():
    data=read_protected(PRIOR_STATE)
    need(sha(data)==PRIOR_STATE_SHA,'PRIOR_RECEIPT_HASH_DRIFT')
    value=json.loads(data)
    need(value['phase']=='GMAIL_RELEVANCE_UPGRADE_SERVER_VERIFIED' and value['new_ids']==PRIVATE_IDS and
         value['candidate_image']==PRIVATE_IMAGE and value['env_sha256']==CURRENT_ENV_SHA and
         value['business_tables_verified']==83 and re.fullmatch('[a-f0-9]{64}',value['new_nginx_sha256']), 'PRIOR_RECEIPT_SCOPE_DRIFT')
    return value


def private_guard():
    info=secure(PRIVATE_DB,mode=0o600)
    need((info.st_dev,info.st_ino)==(64515,282885) and not os.path.samefile(PRIVATE_DB,BUSINESS),'PRIVATE_DATABASE_IDENTITY_DRIFT')
    with sqlite3.connect(PRIVATE_DB.as_uri()+'?mode=ro',uri=True,timeout=15) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','PRIVATE_DATABASE_INTEGRITY_FAILED')
        schema=list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        rows=[]
        for identity,owner,source,status,generation,metadata in db.execute('SELECT id,owner_id,source_id,status,generation,metadata_json FROM private_connections ORDER BY id'):
            metadata=json.loads(metadata or '{}')
            rows.append([identity,owner,source,status,generation,metadata.get('account_label'),metadata.get('scope'),metadata.get('connection_mode')])
        need(any(row[1]=='4' and row[2]=='gmail' and row[3]=='connected' and
                 row[6]=='https://www.googleapis.com/auth/gmail.readonly' and row[7]=='oauth' for row in rows),'GMAIL_CONNECTED_BASELINE_REQUIRED')
    return {'device':info.st_dev,'inode':info.st_ino,'schema_sha256':digest(schema),'connection_identity_sha256':digest(rows)}


def runtime_check(previous,healthy=True):
    crm=crm_check(require_healthy=healthy)
    need(sha(read_protected(ENV))==CURRENT_ENV_SHA,'ENVIRONMENT_HASH_DRIFT')
    result={}
    for role,identity in PRIVATE_IDS.items():
        info=inspect('t24-private-'+role); pinned=previous['new_private'][role]
        need(info['Id']==identity and info['Image']==PRIVATE_IMAGE and config_hash(info)==pinned['configuration_sha256'] and
             info['State']['StartedAt']==pinned['started_at'] and info['RestartCount']==pinned['restart_count'], 'PRIVATE_RUNTIME_CONFIGURATION_DRIFT')
        if healthy:
            need(info['State']['Running'] and not info['State'].get('Restarting') and not info['State'].get('Dead'),'PRIVATE_RUNTIME_HEALTH_DRIFT')
            if role=='api': need(info['State'].get('Health',{}).get('Status')=='healthy','PRIVATE_API_HEALTH_DRIFT')
        result[role]={'id':identity,'image':PRIVATE_IMAGE,'configuration_sha256':pinned['configuration_sha256'],'started_at':pinned['started_at']}
    private=private_guard()
    need(all(private[k]==previous['private_database'][k] for k in ('device','inode','schema_sha256')),'PRIVATE_SCHEMA_DRIFT')
    return {'crm':crm,'private':result,'private_database':private}


def nginx_bytes(original,expected_sha):
    need(sha(original)==expected_sha,'NGINX_BASELINE_DRIFT')
    old,new=str(OLD_PUBLIC).encode(),str(PUBLIC).encode()
    need(original.count(old)==1 and new not in original,'EXACT_ROOT_REPLACEMENT_REQUIRED')
    changed=original.replace(old,new,1)
    need(changed.replace(new,old,1)==original and b'127.0.0.1:8000' in original and b'127.0.0.1:8001' in original and
         all(name.encode() in original for name in HEADERS),'PROXIES_OR_HEADERS_DRIFT')
    return changed


def file_map(root):
    result={}
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink(),'STATIC_SYMLINK_FORBIDDEN')
        if path.is_dir(): continue
        relative=path.relative_to(root)
        need(path.is_file() and path.suffix in SUFFIXES and not any(part.startswith('.') for part in relative.parts) and
             (path.suffix!='.html' or relative.as_posix() in {'index.html','offline.html'}),'NON_STATIC_FILE')
        result[relative.as_posix()]=sha(path.read_bytes())
    return result


def extract_static(manifest,archive_bytes=None):
    root=RELEASE/'payload'
    need(not root.exists() and not root.is_symlink(),'NEW_PAYLOAD_DIRECTORY_REQUIRED')
    root.mkdir(mode=0o700)
    entries={};total=0
    # Production uses the exact bytes whose pinned digest was already verified.
    # Local synthetic tests may supply the temporary archive by path.
    with tarfile.open(fileobj=io.BytesIO(archive_bytes),mode='r:gz') if archive_bytes is not None else tarfile.open(RELEASE/'static-payload.tar.gz','r:gz') as archive:
        for member in archive:
            need(member.isfile() and member.name.startswith('payload/'),'REGULAR_STATIC_FILES_ONLY')
            name=member.name.removeprefix('payload/');relative=PurePosixPath(name)
            need(name==relative.as_posix() and not relative.is_absolute() and '..' not in relative.parts and
                 not any(p.startswith('.') for p in relative.parts),'STATIC_PAYLOAD_PATH_INVALID')
            need(name in manifest['payload_files'] and name not in entries and member.size<=16*1024**2,'STATIC_ALLOWLIST_DRIFT')
            total+=member.size;need(total<64*1024**2,'STATIC_PAYLOAD_SIZE_LIMIT')
            blob=archive.extractfile(member).read();need(len(blob)==member.size and sha(blob)==manifest['payload_files'][name],'STATIC_FILE_HASH_DRIFT')
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);write_new(target,blob);entries[name]=sha(blob)
    need(entries==manifest['payload_files'] and file_map(root)==entries,'STATIC_MANIFEST_INCOMPLETE')
    need({'index.html','app-version.json'}<=set(entries) and json.loads((root/'app-version.json').read_bytes())=={'version':VERSION},'STATIC_VERSION_DRIFT')
    return root


def public_ancestors():
    for path in (Path('/var'),Path('/var/www'),PUBLIC.parent,OLD_PUBLIC):
        info=path.lstat()
        need(path.is_dir() and path.resolve()==path and not path.is_symlink() and info.st_uid==0 and
             not info.st_mode&0o022 and info.st_mode&0o005==0o005,'PUBLIC_ANCESTOR_UNTRUSTED')


def create_public_root(path):
    need(not path.exists() and not path.is_symlink(),'FRESH_PUBLIC_ROOT_REQUIRED')
    path.mkdir(mode=0o755);path.chmod(0o755)


def install_public(payload):
    public_ancestors()
    need(not PUBLIC.exists() and not PUBLIC.is_symlink(),'FRESH_PUBLIC_ROOT_REQUIRED')
    old=file_map(OLD_PUBLIC);fresh=file_map(payload);desired=dict(fresh)
    for name,value in old.items():
        if name.startswith('assets/'):
            need(name not in desired or desired[name]==value,'HASHED_ASSET_COLLISION')
            desired.setdefault(name,value)
    create_public_root(PUBLIC)
    for name in sorted(desired):
        source=payload/name if name in fresh else OLD_PUBLIC/name;target=PUBLIC/name
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o755);write_new(target,source.read_bytes());target.chmod(0o644)
    for path in PUBLIC.rglob('*'):
        if path.is_dir(): path.chmod(0o755)
    need(file_map(PUBLIC)==desired,'NEW_PUBLIC_BYTES_DRIFT')
    rows=subprocess.check_output(['ps','-C','nginx','-o','uid=,args='],text=True)
    uids={int(row.split(None,1)[0]) for row in rows.splitlines() if 'nginx: worker process' in row}
    need(len(uids)==1 and 0 not in uids and pwd.getpwuid(next(iter(uids))).pw_name=='www-data','NGINX_WORKER_USER_DRIFT')
    code="import pathlib,hashlib,json;r=pathlib.Path("+repr(str(PUBLIC))+");print(json.dumps({p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file()},sort_keys=True))"
    need(json.loads(run(['runuser','-u','www-data','--','python3','-c',code],'PUBLIC_WORKER_READ_FAILED'))==desired,'PUBLIC_WORKER_BYTES_DRIFT')
    save(RELEASE/'public-manifest.json',desired)
    return desired


def manifest_check(expected):
    data=read_protected(RELEASE/'static-manifest.json',4*1024**2)
    need(sha(data)==expected,'STATIC_MANIFEST_HASH_DRIFT')
    value=json.loads(data)
    need(value['source_sha']==SOURCE and value['frontend_version']==VERSION and value['static_only'] is True and
         value['backend_changes'] is False and value['credentials_included'] is False and
         isinstance(value['payload_files'],dict) and 1<=len(value['payload_files'])<10000,'STATIC_MANIFEST_SCOPE_DRIFT')
    archive=read_protected(RELEASE/'static-payload.tar.gz',64*1024**2)
    need(sha(archive)==value['payload_sha256'],'STATIC_ARCHIVE_HASH_DRIFT')
    return value,archive


def rollback_static(original,changed,previous):
    # An unrelated transient health failure cannot prevent restoring a static
    # root. Identities/configs and concurrent Nginx changes still fail closed.
    runtime_check(previous,healthy=False)
    current=sha(read_nginx());need(current in {sha(original),sha(changed)},'STATIC_ROLLBACK_CONCURRENT_CHANGE')
    if current!=sha(original):
        atomic_nginx(original,{sha(changed)})
        run(['nginx','-t'],'STATIC_ROLLBACK_NGINX_TEST_FAILED');run(['systemctl','reload','nginx'],'STATIC_ROLLBACK_RELOAD_FAILED')
    need(sha(read_nginx())==sha(original),'STATIC_ROLLBACK_HASH_DRIFT')
    public_check(file_map(OLD_PUBLIC),json.loads((OLD_PUBLIC/'app-version.json').read_bytes())['version'],
                 OLD_PUBLIC,verify_services=False)


def main(args):
    need(args.execute and os.geteuid()==0 and socket.gethostname()==HOST,'EXPLICIT_VERIFIED_SERVER_REQUIRED')
    need(re.fullmatch('[a-f0-9]{40}',SOURCE) and re.fullmatch('[a-f0-9]{12}',VERSION) and
         re.fullmatch('[a-f0-9]{64}',args.manifest_sha256),'REVIEWED_HASH_ARGUMENT_REQUIRED')
    os.umask(0o077);secure(RELEASE,True,0o700);secure(CONFIG,True,0o700)
    fd=os.open(CONFIG/'gmail-upgrade.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        secure(CONFIG/'gmail-upgrade.lock',mode=0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        previous=prior_state();baseline=runtime_check(previous);original=read_nginx();changed=nginx_bytes(original,previous['new_nginx_sha256'])
        manifest,archive_bytes=manifest_check(args.manifest_sha256);payload=extract_static(manifest,archive_bytes);public=install_public(payload)
        need(runtime_check(previous)==baseline and sha(read_nginx())==sha(original),'PREPARATION_RUNTIME_DRIFT')
        before=business_fingerprints();attempt=uuid4().hex;receipt=RELEASE/('static-state-'+attempt+'.json')
        state={'phase':'STATIC_PREPARED','source_sha':SOURCE,'frontend_version':VERSION,'manifest_sha256':args.manifest_sha256,
               'original_nginx_sha256':sha(original),'new_nginx_sha256':sha(changed),'private_and_crm_runtime':baseline,
               'business_before_fingerprint_sha256':digest(before),'backend_services_modified':False,'databases_restored':False}
        write_new(RELEASE/('nginx-before-'+attempt+'.conf'),original);save(receipt,state)
        try:
            need(runtime_check(previous)==baseline and sha(read_nginx())==sha(original),'FINAL_STATIC_PREFLIGHT_DRIFT')
            atomic_nginx(changed,{sha(original)});run(['nginx','-t'],'STATIC_NGINX_TEST_FAILED');run(['systemctl','reload','nginx'],'STATIC_NGINX_RELOAD_FAILED')
            state['phase']='STATIC_SWITCHED';save(receipt,state,True)
            public_check(public,VERSION,PUBLIC)
            need(runtime_check(previous)==baseline and sha(read_nginx())==sha(changed) and file_map(PUBLIC)==public,'STATIC_POST_SWITCH_DRIFT')
            after=business_fingerprints();state['business_after_fingerprint_sha256']=digest(after)
            state['changed_business_tables']=sorted(name for name in set(before['tables'])|set(after['tables']) if before['tables'].get(name)!=after['tables'].get(name))
            need(before==after,'BUSINESS_FINGERPRINT_DRIFT_PENDING_REVIEW')
            state['phase']='RESPONSIVE_STATIC_UPGRADE_VERIFIED';state['business_tables_verified']=83;save(receipt,state,True)
            print(json.dumps({'stage':state['phase'],'receipt_basename':receipt.name,'receipt_sha256':sha(receipt.read_bytes()),'frontend_version':VERSION,
                              'business_tables_verified':83,'backend_services_modified':False,'databases_restored':False},sort_keys=True))
        except BaseException as error:
            failure=str(error) if isinstance(error,SwitchError) else type(error).__name__
            need(re.fullmatch('[A-Za-z0-9_]+',failure),'FAILURE_CODE_INVALID');state['failure_code']=failure
            try:
                rollback_static(original,changed,previous);state['phase']='STATIC_ONLY_ROLLBACK_VERIFIED';save(receipt,state,True)
            except BaseException as rollback_error:
                state['phase']='STATIC_ROLLBACK_REQUIRES_REVIEW';state['rollback_failure_code']=str(rollback_error) if isinstance(rollback_error,SwitchError) else type(rollback_error).__name__
                save(receipt,state,True);raise SwitchError('STATIC_ROLLBACK_REQUIRES_REVIEW') from None
            raise SwitchError('STATIC_PATCH_REJECTED_ROLLBACK_VERIFIED') from None
    finally: os.close(fd)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');parser.add_argument('--manifest-sha256',required=True)
    try: main(parser.parse_args())
    except BaseException as error:
        code=str(error) if isinstance(error,SwitchError) and re.fullmatch('[A-Z0-9_]+',str(error)) else 'STATIC_UPGRADE_FAILED'
        print('GMAIL_STATIC_PATCH_ERROR '+code,flush=True);raise SystemExit(1) from None
