"""Fixed deployed review-refresh baseline; business/private/credentials never written."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import sqlite3
import stat
import sys
import types

H=lambda value:hashlib.sha256(value).hexdigest()
HOST='iZj6c4cj7edgnhdimts4l7Z'
BASE_SOURCE='6b47aefa201fb5e4963e4cfa522b7a5776e5a2c4'
BASE_FRONTEND='b06112728ac2'
REVISION='d9e4f6a7b803'
OLD=Path('/opt/t24-crm/releases/media-ops-management-6b47aefa201f-20261031')
DEPLOYED_SHA='17858808bd0ac0f825e8a51931bdf49cde6253f431a0ab7e8280b301fe3b9f37'
ORIGINAL_ID='fc368b511c945fc9fd28b4ccd889fddc2d50d5b7d068a2afd789e6e262e98441'
IMAGE='sha256:925f4b723f13e89ee5217955d9f5208336b5bd063af2e1878fc06b036a50a2bf'
BASE_HELPER_SHA='ebe95b02fb337bd4d2c0cb10fed9e1f29ef7c71aececff2e94c40a7443acd27c'
SAFE_SHA='12a65720a072901bbeb55cdc91ca69a3430c06da178d8d6d0b80d46e8787d95b'
LEGACY=Path('/opt/t24-crm/releases/stripe-history-daily-scan-285c3377e6d0-20261019/release.py')
LEGACY_SHA='bd5f1af9c67b6e268d7d1b4d91ae4b122895480b10bb6ef777b79770ca2392c0'
OLD_PROOF_SHA='92cf8b589defaffcc3a38837c46057fba82a7b82766ca12176bc5c323e9eb4f9'
BACKEND_FILES={'services/google_business.py','routers/google_business.py'}


def need(ok,code):
    if not ok:raise RuntimeError(code)


def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


def guard():
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);sys.dont_write_bytecode=True


def read(path,sha=None):
    row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_TOOL_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:body=stream.read(1048577)
    need(len(body)<=1048576 and (sha is None or H(body)==sha),'PINNED_TOOL_HASH_REQUIRED');return body


def load(path,sha,name):
    module=types.ModuleType(name);module.__file__=str(path);exec(compile(read(path,sha),str(path),'exec'),module.__dict__);return module


def dependencies():
    return (load(LEGACY,LEGACY_SHA,'_refresh_legacy'),load(OLD/'release.py',BASE_HELPER_SHA,'_refresh_base'),load(OLD/'preflight.py',SAFE_SHA,'_refresh_safe'))


def db_metadata(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        pragma=[con.execute('PRAGMA '+name).fetchone()[0] for name in ('user_version','application_id')]
        present=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone() is not None
        sequence=con.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall() if present else []
        return {'pragma_sha256':digest(pragma),'sequence_exists':present,'sequence_sha256':digest(sequence)}
    finally:con.close()


def row_evidence(m):return {name:{'count':row['count'],'rows_sha256':row['rows_sha256'],'shape_sha256':digest({k:row[k] for k in ('columns','schema','indexes')})} for name,row in m.sql_snapshot(m.BUSINESS).items()}


def baseline(m,base,safe):
    receipt=json.loads(read(OLD/'deployed.json',DEPLOYED_SHA))
    need(receipt['stage']=='MEDIA_OPS_MANAGEMENT_DEPLOYED_VERIFIED' and receipt['source_sha']==BASE_SOURCE and receipt['frontend_version']==BASE_FRONTEND and receipt['schema_revision']==REVISION and receipt['scheduler_disabled'] is True,'EXACT_DEPLOYED_BASELINE_REQUIRED')
    need(receipt['crm']['id']==ORIGINAL_ID and receipt['crm']['image']==IMAGE,'EXACT_DEPLOYED_ID_IMAGE_REQUIRED')
    oldproof=json.loads(read(Path('/opt/t24-crm/releases/media-ops-management-preflight-'+OLD_PROOF_SHA[:12]+'.json'),OLD_PROOF_SHA))
    pins=json.loads(m.read(base.PRIVATE_PINS,base.PRIVATE_PINS_SHA));crm=m.inspect('t24-crm')
    need(crm['State']['Running'] is True and m.runtime(crm)==receipt['crm'],'DEPLOYED_RUNTIME_DRIFT')
    base.verify_gbp_environment_enabled(crm);m.verify_secret_mount(crm);m.verify_production_worker_enabled(crm);m.retained().require_safe_original_restart(crm)
    inventory=m.inventory(crm['Id']);need(H((json.dumps(inventory,sort_keys=True,indent=2)+'\n').encode())==receipt['candidate_inventory_sha256'],'DEPLOYED_SOURCE_DRIFT')
    need(m.schema_signature(m.BUSINESS,REVISION)==receipt['schema_sha256'],'DEPLOYED_SCHEMA_DRIFT')
    static=Path(receipt['public_root']);need(m.digest(m.tree(static))==receipt['public_inventory_sha256'] and json.loads((static/'app-version.json').read_bytes())['version']==BASE_FRONTEND,'DEPLOYED_STATIC_DRIFT')
    body=m.NGINX.read_bytes();active=m.run(['nginx','-T'],'ACTIVE_NGINX_REQUIRED');new=os.fsencode(receipt['public_root']);old=os.fsencode(oldproof['public_root'])
    need(H(body)==receipt['nginx_sha256'] and active.count(new)==1 and H(active.replace(new,old,1))==oldproof['active_nginx_config_sha256'],'EXACT_CALLBACK_PROTECTED_NGINX_REQUIRED')
    private=safe.safe_private_boundary(m,pins);identity=m.BUSINESS.stat();rows=row_evidence(m)
    need(len(rows)==129 and set(BACKEND_FILES)<=set(inventory),'EXACT_CURRENT_TABLES_AND_SOURCE_REQUIRED')
    return {'stage':'MEDIA_OPS_REVIEW_REFRESH_READONLY_PREFLIGHT','host':HOST,'source_sha':BASE_SOURCE,'frontend_version':BASE_FRONTEND,'schema_revision':REVISION,'schema_sha256':receipt['schema_sha256'],'deployed_sha256':DEPLOYED_SHA,'crm':m.runtime(crm),'database_identity':[identity.st_dev,identity.st_ino],'database_metadata':db_metadata(m.BUSINESS),'rows':rows,'backend_inventory_sha256':digest(inventory),'backend_file_count':len(inventory),'backend_changed_before':{n:inventory[n] for n in sorted(BACKEND_FILES)},'public_root':str(static),'public_inventory_sha256':receipt['public_inventory_sha256'],'nginx_sha256':H(body),'active_nginx_config_sha256':H(active),'credential_boundary':m.credential_boundary(),'google_credential_metadata':safe.protected_metadata(safe.GBP_ENV),'private_boundary':private,'environment_sha256':digest(sorted(crm['Config']['Env'])),'scheduler_disabled':True,'gbp_feature_enabled':True,'callback_logging_protection_retained':True,'provider_requests':False,'business_writes':False,'private_content_read':False,'credential_content_read':False,'container_or_configuration_changed':False}


def collect():
    guard();m,base,safe=dependencies();proof=baseline(m,base,safe)
    need(proof==baseline(m,base,safe),'PREFLIGHT_CHANGED_DURING_READ');return proof


def capture():
    proof=collect();body=(json.dumps(proof,sort_keys=True,indent=2)+'\n').encode();sha=H(body)
    path=Path('/opt/t24-crm/releases/media-ops-review-refresh-preflight-'+sha[:12]+'.json')
    if path.exists():need(read(path,sha)==body,'EXISTING_PREFLIGHT_DRIFT')
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'stage':'MEDIA_OPS_REVIEW_REFRESH_PREFLIGHT_CAPTURED','sha256':sha,'bytes':len(body),'path':str(path),'source_sha':proof['source_sha'],'frontend_version':proof['frontend_version'],'schema_revision':proof['schema_revision'],'schema_sha256':proof['schema_sha256'],'deployed_sha256':proof['deployed_sha256'],'crm':proof['crm'],'backend_changed_before':proof['backend_changed_before'],'backend_inventory_sha256':proof['backend_inventory_sha256'],'rows_sha256':digest(proof['rows']),'table_count':len(proof['rows']),'environment_sha256':proof['environment_sha256'],'nginx_sha256':proof['nginx_sha256'],'active_nginx_config_sha256':proof['active_nginx_config_sha256'],'scheduler_disabled':True,'gbp_feature_enabled':True,'callback_logging_protection_retained':True,'private_boundary_verified':True,'executed_business_writes':False,'credential_content_read':False,'private_content_read':False},sort_keys=True))


if __name__=='__main__':
    try:capture()
    except BaseException as error:
        code=str(error) if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',str(error)) else 'PREFLIGHT_REJECTED'
        print(json.dumps({'stage':'MEDIA_OPS_REVIEW_REFRESH_PREFLIGHT_REJECTED','code':code}));sys.exit(1)
