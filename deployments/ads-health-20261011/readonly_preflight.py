#!/usr/bin/env python3
"""Read-only Ads health release baseline. No database/service/file mutation."""
import hashlib,itertools,json,os,re,socket,sqlite3,stat,subprocess
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
CRM_ID='ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26'
CRM_IMAGE='sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
CRM_STARTED='2026-10-10T17:19:07.948520307Z'
CRM_CONFIG='2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0'
PRIVATE_IDS={'api':'627de60395d238990245c8a3958255508896ecd31aa0218b5c63283e8500a443','worker':'a1ae1e9b72c48439495da120e51d1148fc145f2d2592c5301404e8c8a4b353b1'}
PRIVATE_IMAGE='sha256:ce90e93f5420d940fce431cd23cdc8f9e95a6d18d41167fe46a4ebf2738862a8'
CURRENT_ENV_SHA='180f945729234df79c45f5148663f8407c75be55aa8d4e79107305c03c00f82d'
PREVIOUS_RELEASE=Path('/opt/t24-crm/releases/google-ads-d6fce13-20261011')
SWITCH_RECEIPT=PREVIOUS_RELEASE/'switch-state-e90cdec99d994c1fad9c75479dd8e7e9.json'
SWITCH_RECEIPT_SHA='ccd6300640fdaafa0ab7665aee19832c9986a48bbc4082060601ea496b40ec86'
ORIGINAL_BASELINE=PREVIOUS_RELEASE/'readonly-baseline.json'
ORIGINAL_BASELINE_SHA='8437aa76648ee4b3c8ca69bb0ad55b613dfeb219b50e5b52a8af5fc72d971288'
PUBLIC=Path('/var/www/t24-crm-public/google-ads-d6fce13-20261011')
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


def private_snapshot(original, path=PRIVATE_DB):
    info=secure(path,mode=0o600)
    need((info.st_dev,info.st_ino)==(64515,282885) and not os.path.samefile(path,BUSINESS),'PRIVATE_DATABASE_IDENTITY_DRIFT')
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=15) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','PRIVATE_DATABASE_INTEGRITY_FAILED')
        need({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}==TABLES,'PRIVATE_TABLE_SCOPE_DRIFT')
        schema=list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        need(digest(schema)==original['private_database']['schema_sha256'],'PRIVATE_SCHEMA_DRIFT')
        connections=[]
        # The presence expression returns a boolean; ciphertext is never selected.
        query="SELECT id,owner_id,source_id,status,generation,json_extract(metadata_json,'$.account_label'),json_extract(metadata_json,'$.scope'),json_extract(metadata_json,'$.connection_mode'),json_extract(metadata_json,'$.ads_customer_id'),json_extract(metadata_json,'$.read_only_adapter'), encrypted_credentials IS NOT NULL AND length(encrypted_credentials)>0 FROM private_connections ORDER BY id"
        for identity,owner,source,status,generation,label,scope,mode,customer,readonly,encrypted in db.execute(query):
            connections.append({'id':identity,'owner_id':owner,'source_id':source,'status':status,'generation':generation,
                                'account_identity_sha256':digest(label),'scope_sha256':digest(scope),'connection_mode':mode,
                                'credentials_present':bool(encrypted),'ads_target_matches':customer==TARGET_CUSTOMER if source=='google_ads' else None,
                                'readonly_adapter':bool(readonly)})
            if source=='gmail':
                previous=[r for r in original['private_database']['connections'] if r['source_id']=='gmail' and r['owner_id']=='4']
                need(len(previous)==1,'ORIGINAL_GMAIL_MISSING');previous=previous[0]
                need(identity==previous['id'] and owner=='4' and status=='connected' and generation==previous['generation'] and
                     digest(label)==previous['account_identity_sha256'] and digest(scope)==previous['scope_sha256'] and mode=='oauth' and encrypted,
                     'GMAIL_CONNECTION_IDENTITY_DRIFT')
            if source=='google_ads':
                need(owner=='4' and status=='connected' and mode=='oauth' and encrypted and readonly==1 and customer==TARGET_CUSTOMER and
                     'https://www.googleapis.com/auth/adwords' in (scope or '').split(),'ADS_CONNECTION_IDENTITY_DRIFT')
        need(sum(c['source_id']=='gmail' for c in connections)==1 and sum(c['source_id']=='google_ads' for c in connections)==1,'REQUIRED_CONNECTIONS_MISSING')
        choices={}
        for table,query in (('items','SELECT id,owner_id,source_id,external_id,local_title,local_summary,action_status,snoozed_until,created_at FROM private_items'),
                            ('preferences','SELECT owner_id,preferences_json FROM private_preferences')):
            values=sorted(json.dumps(list(row),sort_keys=True,separators=(',',':')) for row in db.execute(query))
            choices[table]={'count':len(values),'sha256':sha('\n'.join(values).encode())}
        count,valid=db.execute("SELECT count(*),sum(CASE WHEN owner_id='4' AND kind='campaign' AND external_id LIKE ? AND json_extract(evidence,'$.customer_id')=? AND json_extract(evidence,'$.period')='LAST_30_DAYS' AND json_extract(evidence,'$.accounting_effect')='none' THEN 1 ELSE 0 END) FROM private_items WHERE source_id='google_ads'",(TARGET_CUSTOMER+':%:last_30_days',TARGET_CUSTOMER)).fetchone()
        need(count>0 and valid==count,'ADS_ITEM_SCOPE_DRIFT')
    return {'device':info.st_dev,'inode':info.st_ino,'schema_sha256':digest(schema),'connections':connections,
            'connection_identity_sha256':digest(connections),'user_choice_hashes':choices,
            'ads_items_count':count,'ads_items_owner_target_and_no_accounting_effect_verified':True}


def main():
    need(os.geteuid()==0 and socket.gethostname()==HOST,'VERIFIED_SERVER_REQUIRED')
    blob=read_protected(SWITCH_RECEIPT,2*1024**2);need(sha(blob)==SWITCH_RECEIPT_SHA,'PREVIOUS_SWITCH_RECEIPT_HASH_DRIFT');previous=json.loads(blob)
    need(previous['phase']=='GOOGLE_ADS_UPGRADE_SERVER_VERIFIED' and previous['business_tables_verified']==83 and previous['crm_runtime_modified'] is False and
         previous['databases_restored'] is False and previous['new_ids']==PRIVATE_IDS and previous['candidate_image']==PRIVATE_IMAGE,'PREVIOUS_SWITCH_RECEIPT_SCOPE_DRIFT')
    blob=read_protected(ORIGINAL_BASELINE,2*1024**2);need(sha(blob)==ORIGINAL_BASELINE_SHA,'ORIGINAL_BASELINE_HASH_DRIFT');original=json.loads(blob)
    need(original['stage']=='GOOGLE_ADS_READONLY_BASELINE_VERIFIED' and original['mutation_performed'] is False,'ORIGINAL_BASELINE_REQUIRED')
    environment=read_protected(ENV);need(sha(environment)==CURRENT_ENV_SHA,'ENVIRONMENT_HASH_DRIFT')
    values=parse_env(environment);scope=direct_customer_scope(values);need(values.get(TARGET_KEY)==TARGET_CUSTOMER and not scope['missing_configuration_names'],'TARGET_ENVIRONMENT_DRIFT')
    crm=crm_check();private={}
    for role,identity in PRIVATE_IDS.items():
        info=inspect('t24-private-'+role);pinned=previous['new_private'][role]
        need(info['Id']==identity and info['Image']==PRIVATE_IMAGE and config_hash(info)==pinned['configuration_sha256'] and
             info['State']['StartedAt']==pinned['started_at'] and info['RestartCount']==0 and info['State']['Running'] and
             not info['State'].get('Restarting') and not info['State'].get('Dead'),'PRIVATE_RUNTIME_DRIFT')
        if role=='api':need(info['State'].get('Health',{}).get('Status')=='healthy','PRIVATE_API_HEALTH_DRIFT')
        binds=[r for r in info['Mounts'] if r['Type']=='bind']
        need({(r['Source'],r['Destination'],r['RW']) for r in binds}=={('/opt/t24-crm/app/data','/app/backend/data',False),
              ('/opt/t24-crm/private-workspace/data','/private-data',True)} and len(binds)==2,'PRIVATE_MOUNT_SCOPE_DRIFT')
        private['t24-private-'+role]={'id':identity,'image':PRIVATE_IMAGE,'configuration_sha256':pinned['configuration_sha256'],
                                      'started_at':pinned['started_at'],'restart_count':0}
    nginx=read_nginx();need(sha(nginx)==previous['new_nginx_sha256'] and nginx.count(str(PUBLIC).encode())==1,'NGINX_STATIC_DRIFT')
    version=PUBLIC/'app-version.json';need(version.is_file() and version.resolve()==version and not version.is_symlink() and
         json.loads(version.read_bytes())=={'version':'e260d507da1d'},'STATIC_VERSION_DRIFT')
    snapshot=private_snapshot(original)
    business=business_fingerprints();need(business==original['business_fingerprints'],'CRM_BUSINESS_BASELINE_DRIFT')
    report={'stage':'ADS_HEALTH_READONLY_BASELINE_VERIFIED','crm':crm,'private':private,'private_database':snapshot,
            'business_fingerprints':business,'business_tables_verified':83,'original_business_fingerprints_match':True,
            'env_sha256':CURRENT_ENV_SHA,'nginx_sha256':sha(nginx),'static_root':str(PUBLIC),'frontend_version':'e260d507da1d',
            'previous_switch_receipt_sha256':SWITCH_RECEIPT_SHA,'mutation_performed':False}
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    try:main()
    except BaseException as error:
        code=str(error) if isinstance(error,SwitchError) and re.fullmatch('[A-Z0-9_]+',str(error)) else 'ADS_HEALTH_READONLY_BASELINE_FAILED'
        print('ADS_HEALTH_PREFLIGHT_ERROR '+code,flush=True);raise SystemExit(1) from None
