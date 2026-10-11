#!/usr/bin/env python3
"""Read-only Google Ads release baseline. Never writes files, services or DBs.
Only controlled failure codes, immutable runtime proofs and row hashes are printed.
"""
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess

HOST='iZj6c4cj7edgnhdimts4l7Z'
CRM_ID='ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26'
CRM_IMAGE='sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
CRM_STARTED='2026-10-10T17:19:07.948520307Z'
CRM_CONFIG='2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0'
PRIVATE_IDS={'api':'e85e70c9a9d48124cc35aa7fc683d0fb151468f2beb5a929a052f316e7a90da3','worker':'584ffcb43448651568cfd44a736bdf2ee6bf1e0adbf7bfd4778dcccf331193b4'}
PRIVATE_IMAGE='sha256:42c26eaaa6f6aa847548d4f35abb822a43cd9e9c88629c3c711453d6c1fa0fc9'
CURRENT_ENV_SHA='6ebb9e3e1e947106bc8c25bdba782d631f5fd8c83ab1487120f5b16420470296'
STATIC_STATE=Path('/opt/t24-crm/releases/gmail-responsive-e23fc05-20261011/static-state-fe9c562eaa12434ab432273f9435fdd5.json')
STATIC_STATE_SHA='b68d7f586e8d14d7af279715e4678fc9140ded5128cb7f52e7707df45c9782c5'
PUBLIC=Path('/var/www/t24-crm-public/gmail-responsive-e23fc05-20261011')
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
ENV=Path('/opt/t24-crm/private-workspace/config/runtime.env')
BUSINESS=Path('/opt/t24-crm/app/data/crm_prod.db')
PRIVATE_DB=Path('/opt/t24-crm/private-workspace/data/workspace.db')
TABLES={'private_connections','private_items','private_preferences','private_sync_runs'}
TARGET_KEY='PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID'
TARGET_CUSTOMER='7539806760'


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


def parse_env(data):
    need(data and len(data)<=65536 and data.endswith(b'\n') and b'\r' not in data and b'\x00' not in data,'ENV_FORMAT_INVALID')
    result={}
    for row in data.decode('utf-8').splitlines():
        need('=' in row,'ENV_ROW_INVALID');name,value=row.split('=',1)
        need(re.fullmatch('[A-Z][A-Z0-9_]*',name) and name not in result,'ENV_KEY_INVALID')
        result[name]=value
    return result


def direct_customer_scope(values):
    need(not values.get('GOOGLE_ADS_LOGIN_CUSTOMER_ID','').strip(),'DIRECT_CUSTOMER_MANAGER_ENV_REJECTED')
    for key in (TARGET_KEY,'GOOGLE_ADS_CUSTOMER_ID'):
        value=values.get(key,'').strip()
        if value:
            need(value.replace('-','')==TARGET_CUSTOMER,'DIRECT_CUSTOMER_CONFLICT_REJECTED')
    required={'PRIVATE_WORKSPACE_OWNER_IDS':'4','PRIVATE_WORKSPACE_PUBLIC_URL':'https://t24-crm.com',
              'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:////private-data/workspace.db','DATABASE_URL':'sqlite:///./data/crm_prod.db',
              'DATABASE_SCHEMA_MODE':'verify_only','ENFORCE_EMPLOYEE_STATUS':'true','ENFORCE_EMPLOYEE_SESSIONS':'true'}
    need(all(values.get(key)==value for key,value in required.items()),'PRIVATE_ENVIRONMENT_SCOPE_DRIFT')
    missing=[key for key in ('GOOGLE_WORKSPACE_CLIENT_ID','GOOGLE_WORKSPACE_CLIENT_SECRET') if not values.get(key,'').strip()]
    return {'direct_customer_only':True,'target_key_already_present':TARGET_KEY in values,'target_key_has_value':bool(values.get(TARGET_KEY,'').strip()),
            'missing_configuration_names':missing}


def private_snapshot():
    info=secure(PRIVATE_DB,mode=0o600)
    need((info.st_dev,info.st_ino)==(64515,282885) and not os.path.samefile(PRIVATE_DB,BUSINESS),'PRIVATE_DATABASE_IDENTITY_DRIFT')
    with sqlite3.connect(PRIVATE_DB.as_uri()+'?mode=ro',uri=True,timeout=15) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','PRIVATE_DATABASE_INTEGRITY_FAILED')
        need({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}==TABLES,'PRIVATE_TABLE_SCOPE_DRIFT')
        schema=list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        rows=[];connected=[]
        for identity,owner,source,status,generation,metadata,encrypted in db.execute('SELECT id,owner_id,source_id,status,generation,metadata_json,encrypted_credentials FROM private_connections ORDER BY id'):
            metadata=json.loads(metadata or '{}')
            rows.append([identity,owner,source,status,generation,metadata.get('account_label'),metadata.get('scope'),metadata.get('connection_mode')])
            connected.append({'id':identity,'owner_id':owner,'source_id':source,'status':status,'generation':generation,
                              'account_identity_sha256':digest(metadata.get('account_label')),'scope_sha256':digest(metadata.get('scope')),
                              'connection_mode':metadata.get('connection_mode'),'credentials_present':bool(encrypted)})
        gmail=[r for r in rows if r[1]=='4' and r[2]=='gmail']
        need(len(gmail)==1 and gmail[0][3]=='connected' and gmail[0][6]=='https://www.googleapis.com/auth/gmail.readonly' and
             gmail[0][7]=='oauth' and any(r['source_id']=='gmail' and r['owner_id']=='4' and r['credentials_present'] for r in connected),'CONNECTED_GMAIL_REQUIRED')
        choices={}
        for table,query in (('items','SELECT id,owner_id,source_id,external_id,local_title,local_summary,action_status,snoozed_until,created_at FROM private_items'),
                            ('preferences','SELECT owner_id,preferences_json FROM private_preferences')):
            values=sorted(json.dumps(list(row),sort_keys=True,separators=(',',':')) for row in db.execute(query))
            choices[table]={'count':len(values),'sha256':sha('\n'.join(values).encode())}
    return {'device':info.st_dev,'inode':info.st_ino,'schema_sha256':digest(schema),'connection_identity_sha256':digest(rows),
            'connections':connected,'user_choice_hashes':choices}


def main():
    need(os.geteuid()==0 and socket.gethostname()==HOST,'VERIFIED_SERVER_REQUIRED')
    previous_bytes=read_protected(STATIC_STATE);need(sha(previous_bytes)==STATIC_STATE_SHA,'STATIC_RECEIPT_HASH_DRIFT')
    previous=json.loads(previous_bytes)
    need(previous['phase']=='RESPONSIVE_STATIC_UPGRADE_VERIFIED' and previous['business_tables_verified']==83 and
         previous['backend_services_modified'] is False and previous['databases_restored'] is False,'STATIC_RECEIPT_SCOPE_DRIFT')
    environment=read_protected(ENV);need(sha(environment)==CURRENT_ENV_SHA,'ENVIRONMENT_HASH_DRIFT')
    values=parse_env(environment);scope=direct_customer_scope(values)
    crm=crm_check();private={}
    for role,identity in PRIVATE_IDS.items():
        info=inspect('t24-private-'+role);pinned=previous['private_and_crm_runtime']['private'][role]
        need(info['Id']==identity and info['Image']==PRIVATE_IMAGE and config_hash(info)==pinned['configuration_sha256'] and
             info['State']['StartedAt']==pinned['started_at'] and info['RestartCount']==0 and info['State']['Running'] and
             not info['State'].get('Restarting') and not info['State'].get('Dead'),'PRIVATE_RUNTIME_DRIFT')
        if role=='api':need(info['State'].get('Health',{}).get('Status')=='healthy','PRIVATE_API_HEALTH_DRIFT')
        binds=[r for r in info['Mounts'] if r['Type']=='bind']
        need({(r['Source'],r['Destination'],r['RW']) for r in binds}=={('/opt/t24-crm/app/data','/app/backend/data',False),
              ('/opt/t24-crm/private-workspace/data','/private-data',True)} and len(binds)==2,'PRIVATE_MOUNT_SCOPE_DRIFT')
        private['t24-private-'+role]={'id':identity,'image':PRIVATE_IMAGE,'configuration_sha256':config_hash(info),
                                      'started_at':info['State']['StartedAt'],'restart_count':info['RestartCount']}
    nginx=read_nginx();need(sha(nginx)==previous['new_nginx_sha256'] and nginx.count(str(PUBLIC).encode())==1,'NGINX_STATIC_BASELINE_DRIFT')
    version=PUBLIC/'app-version.json';need(version.is_file() and version.resolve()==version and not version.is_symlink() and
         json.loads(version.read_bytes())=={'version':'5434cc26636a'},'STATIC_VERSION_BASELINE_DRIFT')
    snapshot=private_snapshot();pinned=previous['private_and_crm_runtime']['private_database']
    need(all(snapshot[k]==pinned[k] for k in ('device','inode','schema_sha256')),'PRIVATE_SCHEMA_BASELINE_DRIFT')
    business=business_fingerprints()
    report={'stage':'GOOGLE_ADS_READONLY_BASELINE_VERIFIED','crm':crm,'private':private,'private_database':snapshot,
            'nginx_sha256':sha(nginx),'env_sha256':CURRENT_ENV_SHA,'static_root':str(PUBLIC),'frontend_version':'5434cc26636a',
            'direct_customer_configuration':scope,'business_fingerprints':business,'business_tables_verified':83,
            'static_receipt_sha256':STATIC_STATE_SHA,'mutation_performed':False}
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    try:main()
    except BaseException as error:
        code=str(error) if isinstance(error,SwitchError) and re.fullmatch('[A-Z0-9_]+',str(error)) else 'READONLY_PREFLIGHT_FAILED'
        print('GOOGLE_ADS_PREFLIGHT_ERROR '+code,flush=True);raise SystemExit(1) from None
