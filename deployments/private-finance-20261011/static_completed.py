#!/usr/bin/env python3
"""Publish the accepted completed private release static bundle. No container, credential or database mutation.

Pinned completed-release proof controls current runtime. Raw mail/token/config values
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

SOURCE = None
VERSION = None
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
CRM_ID = 'ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26'
CRM_IMAGE = 'sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
CRM_STARTED = '2026-10-10T17:19:07.948520307Z'
CRM_CONFIG = '2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0'
RELEASE = None
PUBLIC = None
OLD_PUBLIC = Path('/var/www/t24-crm-public/ads-health-responsive-30d9748-20261011')
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
    import credential_transfer as transfer
    return transfer.read_protected(path,maximum)

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
            code, headers, body = request('https://t24-crm.com/app-version.json?ads_health_static=' + uuid4().hex, 4096)
            matched = code == 200 and json.loads(body) == {'version': version}
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            matched = False
        if matched:
            break
        need(time.monotonic() < deadline, 'PUBLIC_VERSION_PROPAGATION_FAILED')
        time.sleep(1)
    header_check(headers)
    need(no_store(headers), 'PUBLIC_VERSION_CACHE_DRIFT')
    code, headers, body = request('https://t24-crm.com/?ads_health_static=' + uuid4().hex)
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



def fixed_json(path, expected, maximum=4*1024**2):
    need(re.fullmatch('[a-f0-9]{64}', expected or ''), 'REVIEWED_HASH_REQUIRED')
    blob=read_protected(path,maximum)
    need(sha(blob)==expected,'FIXED_RECEIPT_HASH_DRIFT')
    value=json.loads(blob);need(isinstance(value,dict),'OBJECT_RECEIPT_REQUIRED')
    return value


def checked_state(state,candidate):
    need(state.get('phase')=='PRIVATE_COMPLETED_RELEASE_SERVER_VERIFIED' and
         state.get('source_sha')==candidate['source_sha'] and state.get('candidate_image')==candidate['image_id'] and
         state.get('deployed') is True and state.get('public_assets_published') is False and
         state.get('bank_enabled') is False and state.get('ai_enabled') is False and
         state.get('business_tables_verified')==83,'ACCEPTED_COMPLETED_SERVER_RELEASE_REQUIRED')
    need(set(state.get('new_ids',{}))=={'api','worker'} and set(state.get('new_private',{}))=={'api','worker'},
         'BOTH_PRIVATE_ROLES_REQUIRED')
    return state


def private_snapshot(candidate):
    import private_schema_guard as guard
    import candidate_prepare as preparation
    snap=guard.database_snapshot(PRIVATE_DB,private=True)
    need(set(snap['tables'])==preparation.TARGET_TABLES and
         snap['schema_objects']==candidate['synthetic_schema']['schema_objects'],'TEN_TABLE_PRIVATE_SCHEMA_DRIFT')
    need((PRIVATE_DB.stat().st_dev,PRIVATE_DB.stat().st_ino)==(64515,282885),'PRIVATE_FILE_IDENTITY_DRIFT')
    return {'identity':snap['identity'],'schema_sha256':snap['schema_sha256']}


def runtime_snapshot(state,candidate,healthy=True):
    import live_preflight as live
    result={'crm':crm_check(require_healthy=healthy),'private':{}}
    need(sha(read_protected(live.ENV))==live.ENV_SHA,'ORIGINAL_ENVIRONMENT_DRIFT')
    for role in ('api','worker'):
        info=inspect('t24-private-'+role);pinned=state['new_private'][role]
        need(info['Id']==state['new_ids'][role] and info['Image']==candidate['image_id'] and
             config_hash(info)==pinned['configuration_sha256'] and
             info['State']['StartedAt']==pinned['started_at'] and info['RestartCount']==pinned['restart_count'],
             'ACCEPTED_PRIVATE_RUNTIME_DRIFT')
        need(info['Config'].get('Labels',{}).get('t24.private.source.sha')==candidate['source_sha'] and
             info['Config'].get('Labels',{}).get('t24.private.role')==role,'PRIVATE_SOURCE_ROLE_DRIFT')
        if healthy:
            need(info['State']['Running'] and not info['State'].get('Restarting') and not info['State'].get('Dead'),
                 'PRIVATE_HEALTH_DRIFT')
            if role=='api':need(info['State'].get('Health',{}).get('Status')=='healthy','PRIVATE_API_NOT_READY')
        result['private'][role]={'id':info['Id'],'image':info['Image'],'configuration_sha256':config_hash(info),
            'started_at':info['State']['StartedAt'],'restart_count':info['RestartCount']}
    result['private_database']=private_snapshot(candidate)
    return result


def candidate_payload(path,candidate,manifest_path):
    manifest=fixed_json(manifest_path,candidate['payload_manifest_sha256'])
    need(manifest.get('source_sha')==candidate['source_sha'] and manifest.get('frontend_version')==candidate['frontend_version'] and
         manifest.get('credentials_included') is False,'CANDIDATE_PAYLOAD_SCOPE_DRIFT')
    desired={name.removeprefix('frontend/dist/'):value for name,value in manifest['payload_files'].items()
             if name.startswith('frontend/dist/')}
    payload=path/'payload'/'frontend'/'dist'
    need(desired and file_map(payload)==desired and
         json.loads((payload/'app-version.json').read_bytes())=={'version':candidate['frontend_version']},
         'COMPLETE_FROZEN_FRONTEND_BYTES_REQUIRED')
    return payload


def changed_nginx(original,expected_sha):
    need(sha(original)==expected_sha,'NGINX_BASELINE_DRIFT')
    old,new=str(OLD_PUBLIC).encode(),str(PUBLIC).encode()
    need(original.count(old)==1 and new not in original,'EXACT_STATIC_ROOT_REPLACEMENT_REQUIRED')
    changed=original.replace(old,new,1)
    need(changed.replace(new,old,1)==original and b'127.0.0.1:8000' in original and b'127.0.0.1:8001' in original and
         all(name.encode() in original for name in HEADERS),'PROXIES_SECURITY_HEADERS_PRESERVED_REQUIRED')
    return changed


def rollback_static(original,changed,state,candidate):
    runtime_snapshot(state,candidate,healthy=False)
    current=sha(read_nginx());need(current in {sha(original),sha(changed)},'STATIC_ROLLBACK_CONCURRENT_CHANGE')
    if current!=sha(original):
        atomic_nginx(original,{sha(changed)})
        run(['nginx','-t'],'ROLLBACK_NGINX_TEST_FAILED');run(['systemctl','reload','nginx'],'ROLLBACK_RELOAD_FAILED')
    need(sha(read_nginx())==sha(original),'STATIC_ROLLBACK_HASH_DRIFT')
    public_check(file_map(OLD_PUBLIC),'54da68143ed2',OLD_PUBLIC,verify_services=False)


def main(args):
    global SOURCE,VERSION,RELEASE,PUBLIC
    import seed_private_stripe as seed
    import live_preflight as live
    need(args.execute and os.geteuid()==0 and socket.gethostname()==HOST,'EXPLICIT_VERIFIED_ROOT_SERVER_REQUIRED')
    SOURCE=args.source_sha
    need(re.fullmatch('[a-f0-9]{40}',SOURCE or ''),'COMPLETE_SOURCE_SHA_REQUIRED')
    candidate=fixed_json(args.candidate,args.candidate_sha256)
    seed.checked_candidate(candidate,source_sha=SOURCE,release=args.candidate.parent)
    state=checked_state(fixed_json(args.switch_state,args.switch_state_sha256),candidate)
    VERSION=candidate['frontend_version'];need(re.fullmatch('[a-f0-9]{12}',VERSION),'FROZEN_FRONTEND_VERSION_REQUIRED')
    RELEASE=args.switch_state.parent/'static-release'
    need(RELEASE.parent.resolve()==RELEASE.parent and not RELEASE.exists() and not RELEASE.is_symlink(),
         'FRESH_STATIC_RELEASE_REQUIRED')
    os.umask(0o077);RELEASE.mkdir(mode=0o700);secure(RELEASE,True,0o700);secure(CONFIG,True,0o700)
    PUBLIC=Path('/var/www/t24-crm-public')/('private-completed-'+SOURCE[:12]+'-20261011')
    lock=CONFIG/'private-finance-release.lock'
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        secure(lock,mode=0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        baseline=runtime_snapshot(state,candidate)
        original=read_nginx();previous=fixed_json(live.STATIC_RECEIPT,live.STATIC_RECEIPT_SHA)
        changed=changed_nginx(original,previous['new_nginx_sha256'])
        payload=candidate_payload(args.candidate.parent,candidate,args.manifest);public=install_public(payload)
        need(runtime_snapshot(state,candidate)==baseline and sha(read_nginx())==sha(original),'PREPUBLISH_RUNTIME_DRIFT')
        before=business_fingerprints();receipt=RELEASE/'static-state.json'
        report={'phase':'COMPLETED_STATIC_PREPARED','source_sha':SOURCE,'frontend_version':VERSION,
            'candidate_sha256':args.candidate_sha256,'switch_state_sha256':args.switch_state_sha256,
            'original_nginx_sha256':sha(original),'new_nginx_sha256':sha(changed),'public_root':str(PUBLIC),
            'private_and_crm_runtime':baseline,'business_before_fingerprint_sha256':digest(before),
            'backend_services_modified':False,'databases_restored':False,'bank_enabled':False,'ai_enabled':False,'deployed':False}
        write_new(RELEASE/'nginx-before.conf',original);save(receipt,report)
        try:
            need(runtime_snapshot(state,candidate)==baseline and sha(read_nginx())==sha(original),'FINAL_STATIC_PREFLIGHT_DRIFT')
            atomic_nginx(changed,{sha(original)});run(['nginx','-t'],'STATIC_NGINX_TEST_FAILED');run(['systemctl','reload','nginx'],'STATIC_RELOAD_FAILED')
            report['phase']='COMPLETED_STATIC_SWITCHED';save(receipt,report,True)
            public_check(public,VERSION,PUBLIC)
            need(runtime_snapshot(state,candidate)==baseline and sha(read_nginx())==sha(changed) and file_map(PUBLIC)==public,
                 'STATIC_POSTPUBLISH_DRIFT')
            after=business_fingerprints();need(before==after,'BUSINESS_FINGERPRINT_DRIFT_PENDING_REVIEW')
            report.update(phase='PRIVATE_COMPLETED_PUBLIC_RELEASE_VERIFIED',business_tables_verified=83,
                business_after_fingerprint_sha256=digest(after),deployed=True)
            save(receipt,report,True)
            print(json.dumps({'stage':report['phase'],'receipt_path':str(receipt),'receipt_sha256':sha(receipt.read_bytes()),
                'frontend_version':VERSION,'business_tables_verified':83,'bank_enabled':False,'ai_enabled':False,'deployed':True},sort_keys=True))
        except BaseException:
            report['deployed']=False
            try:
                rollback_static(original,changed,state,candidate)
                report['phase']='COMPLETED_STATIC_ROLLBACK_VERIFIED';save(receipt,report,True)
            except BaseException:
                report['phase']='STATIC_ROLLBACK_REQUIRES_REVIEW';save(receipt,report,True)
                raise SwitchError('STATIC_ROLLBACK_REQUIRES_REVIEW') from None
            raise SwitchError('STATIC_RELEASE_REJECTED_ROLLBACK_VERIFIED') from None
    finally:os.close(fd)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute',action='store_true');parser.add_argument('--source-sha',required=True)
    parser.add_argument('--candidate',type=Path,required=True);parser.add_argument('--candidate-sha256',required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--switch-state',type=Path,required=True);parser.add_argument('--switch-state-sha256',required=True)
    try:main(parser.parse_args())
    except BaseException as error:
        code=str(error) if isinstance(error,SwitchError) and re.fullmatch('[A-Z0-9_]+',str(error)) else 'STATIC_RELEASE_FAILED'
        print('PRIVATE_COMPLETED_STATIC_ERROR '+code);raise SystemExit(1) from None
