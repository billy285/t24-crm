#!/usr/bin/env python3
"""Scoped CRM overlay release. Private services untouched; financial rows never restored.

Prepare builds from the exact deployed image with explicitly approved files, validates an
additive migration and candidate startup on offline DB copies.
Activate requires a reviewed receipt, stops only CRM, migrates atomically, swaps
one CRM container and one static root. After migration, recovery uses the reviewed
new image because the previous application requires its exact older schema head.
"""
import argparse,copy,fcntl,hashlib,http.client,importlib.util,io,json,os,re,socket,sqlite3,stat,subprocess,sys,tarfile,time,urllib.parse,urllib.request
from pathlib import Path
SOURCE='3aaae9f6b13a349c57d0a9d026019757ba837fd6'
BASELINE='c1b3c4cde5558923d7ec81dc3c95cf319dadf5a2'
BASELINE_FRONTEND='ebdd4929c921'
FRONTEND_VERSION='f38ebb7b07a9'
HOST='iZj6c4cj7edgnhdimts4l7Z'
BASE_IMAGE='sha256:c538ec8a7ae0f1f715c2cd6c9b221e8614f3040039217ade4fc5d8f650acce27'
OLD_ID='06716fe2398628a3f19103ca8b6c3d60ae58f63621d395b0bed8de0231c31915'
OLD_PUBLIC=Path('/var/www/t24-crm-public/sales-note-templates-retry-f96eaa209f2d-20261014')
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA='0c1f7e23681db67aee4942fb5c8e6fe1fa95caaea428b3ee2994bcfcb4f20421'
BUSINESS=Path('/opt/t24-crm/app/data/crm_prod.db')
MIGRATION='alembic/versions/f7d1c5a9b027_sales_unified_dossiers.py'
BACKEND={'main.py', 'alembic/versions/f7d1c5a9b027_sales_unified_dossiers.py',
 'models/sales_contact_protection.py',
 'models/sales_dossiers.py',
 'routers/merchant_pool.py',
 'routers/sales_dossiers.py',
 'routers/sales_leads.py',
 'schemas/sales_dossiers.py',
 'services/sales_contact_protection.py',
 'services/sales_dossiers.py',
 'services/sales_enrichment.py',
 'services/sales_lead_cycle.py'}
OLD_REVISION='e6c0b4f8a916'
NEW_REVISION='f7d1c5a9b027'
DOCKERIGNORE=b'*\n!Dockerfile\n!Dockerfile.rollback\n!backend\n!backend/**\n'
_TOOLS_CACHE=None
PERSONAL=Path('/opt/t24-crm/releases/personal-finance-1a9232dcc04a-20261012-retry2/release.py')
PERSONAL_SHA='a3d63f63a6c2b0483469c27a488f7c115848e63a603ad3f5fbdc92c16b382d16'
ADDITIONS={}
NEW_SCHEMA={'sales_contact_protection_audits': {'action': ('VARCHAR(32)', 1, None, 0),
                                     'actor_id': ('INTEGER', 0, None, 0),
                                     'actor_name': ('VARCHAR(255)', 0, None, 0),
                                     'created_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                                     'id': ('INTEGER', 1, None, 1),
                                     'lead_id': ('INTEGER', 0, None, 0),
                                     'phone_key': ('VARCHAR(64)', 1, None, 0),
                                     'reason': ('TEXT', 1, None, 0)},
 'sales_dossier_grant_audits': {'access': ('VARCHAR(16)', 1, None, 0),
                                'action': ('VARCHAR(16)', 1, None, 0),
                                'actor_id': ('INTEGER', 1, None, 0),
                                'actor_name': ('VARCHAR(255)', 0, None, 0),
                                'created_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                                'employee_id': ('INTEGER', 1, None, 0),
                                'id': ('INTEGER', 1, None, 1),
                                'lead_id': ('INTEGER', 1, None, 0),
                                'revision': ('INTEGER', 1, None, 0)},
 'sales_dossier_grants': {'access': ('VARCHAR(16)', 1, None, 0),
                          'employee_id': ('INTEGER', 1, None, 0),
                          'id': ('INTEGER', 1, None, 1),
                          'invited_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                          'invited_by_id': ('INTEGER', 1, None, 0),
                          'invited_by_name': ('VARCHAR(255)', 0, None, 0),
                          'lead_id': ('INTEGER', 1, None, 0),
                          'revision': ('INTEGER', 1, None, 0),
                          'revoked_at': ('DATETIME', 0, None, 0),
                          'revoked_by_id': ('INTEGER', 0, None, 0),
                          'revoked_by_name': ('VARCHAR(255)', 0, None, 0),
                          'status': ('VARCHAR(16)', 1, None, 0)},
 'sales_dossier_handoffs': {'ack_note': ('TEXT', 0, None, 0),
                            'acknowledged_at': ('DATETIME', 0, None, 0),
                            'acknowledged_by_id': ('INTEGER', 0, None, 0),
                            'acknowledged_by_name': ('VARCHAR(255)', 0, None, 0),
                            'created_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                            'created_by_id': ('INTEGER', 1, None, 0),
                            'created_by_name': ('VARCHAR(255)', 0, None, 0),
                            'from_sales_id': ('INTEGER', 0, None, 0),
                            'from_sales_name': ('VARCHAR(255)', 0, None, 0),
                            'id': ('INTEGER', 1, None, 1),
                            'lead_id': ('INTEGER', 1, None, 0),
                            'note': ('TEXT', 1, None, 0),
                            'reason': ('TEXT', 0, None, 0),
                            'status': ('VARCHAR(16)', 1, None, 0),
                            'summary': ('JSON', 1, None, 0),
                            'to_sales_id': ('INTEGER', 1, None, 0),
                            'to_sales_name': ('VARCHAR(255)', 0, None, 0)},
 'sales_dossier_summaries': {'lead_id': ('INTEGER', 1, None, 1),
                             'payload': ('JSON', 1, None, 0),
                             'revision': ('INTEGER', 1, None, 0),
                             'updated_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                             'updated_by_id': ('INTEGER', 1, None, 0),
                             'updated_by_name': ('VARCHAR(255)', 0, None, 0)},
 'sales_dossier_summary_audits': {'actor_id': ('INTEGER', 1, None, 0),
                                  'actor_name': ('VARCHAR(255)', 0, None, 0),
                                  'after': ('JSON', 1, None, 0),
                                  'before': ('JSON', 1, None, 0),
                                  'created_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                                  'id': ('INTEGER', 1, None, 1),
                                  'lead_id': ('INTEGER', 1, None, 0),
                                  'revision': ('INTEGER', 1, None, 0)},
 'sales_phone_suppressions': {'actor_id': ('INTEGER', 0, None, 0),
                              'actor_name': ('VARCHAR(255)', 0, None, 0),
                              'blocked': ('BOOLEAN', 1, None, 0),
                              'phone_key': ('VARCHAR(64)', 1, None, 1),
                              'reason': ('TEXT', 1, None, 0),
                              'source_lead_id': ('INTEGER', 0, None, 0),
                              'updated_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0)}}
NEW_TABLES={table:set(columns) for table,columns in NEW_SCHEMA.items()}
ADDED_SCHEMA={}
NEW_INDEXES={'sales_contact_protection_audits': {'ix_sales_contact_protection_audits_lead_id': (0, 'c', 0, ('lead_id',)),
                                     'ix_sales_contact_protection_audits_phone_key': (0,
                                                                                      'c',
                                                                                      0,
                                                                                      ('phone_key',))},
 'sales_dossier_grant_audits': {'ix_sales_dossier_grant_audits_lead_id': (0, 'c', 0, ('lead_id',))},
 'sales_dossier_grants': {'ix_sales_dossier_grants_employee_id': (0, 'c', 0, ('employee_id',)),
                          'ix_sales_dossier_grants_lead_id': (0, 'c', 0, ('lead_id',)),
                          'sqlite_autoindex_sales_dossier_grants_1': (1, 'u', 0, ('lead_id', 'employee_id'))},
 'sales_dossier_handoffs': {'ix_sales_dossier_handoffs_lead_id': (0, 'c', 0, ('lead_id',))},
 'sales_dossier_summaries': {},
 'sales_dossier_summary_audits': {'ix_sales_dossier_summary_audits_lead_id': (0, 'c', 0, ('lead_id',)),
                                  'sqlite_autoindex_sales_dossier_summary_audits_1': (1,
                                                                                      'u',
                                                                                      0,
                                                                                      ('lead_id',
                                                                                       'revision'))},
 'sales_phone_suppressions': {'sqlite_autoindex_sales_phone_suppressions_1': (1, 'pk', 0, ('phone_key',))}}
PRESERVED={'company_finance_formulas':True,'close_conditions':True,'private_workspace':True,'customer_invitation_rules':True,'commission_attribution':True}
H=lambda b:hashlib.sha256(b).hexdigest()
def static_path(name):
 p=Path(name)
 if not p.parts or p.is_absolute() or str(p)!=name or '\\' in name or any(part.startswith('.') for part in p.parts):return False
 if len(p.parts)==1:return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or p.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch('workbox-[a-zA-Z0-9_-]+\\.js',name))
 return p.parts[0]=='assets' and p.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}
def need(ok,code):
 if not ok:raise RuntimeError(code)
def digest(obj):return H(json.dumps(obj,sort_keys=True,separators=(',',':')).encode())
def read(path,expected=None):
 path=Path(path);s=path.lstat();need(path.resolve()==path and stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and not s.st_mode&0o077,'PROTECTED_FILE_REQUIRED')
 b=path.read_bytes();need(not expected or H(b)==expected,'FILE_HASH_DRIFT');return b
def write(path,body):
 b=body if isinstance(body,bytes) else (json.dumps(body,sort_keys=True,indent=2)+'\n').encode()
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
 return H(b)
def run(args,code,timeout=180):
 p=subprocess.run(args,capture_output=True,timeout=timeout)
 need(p.returncode==0,code);return p.stdout

def inspect(name):return json.loads(run(['docker','inspect',name],'CONTAINER_INSPECTION_FAILED'))[0]
def clone_networks(info):
 # Docker-assigned endpoint IDs, DNS names and IP addresses must not be reused.
 # Preserve every attached network and user-configured alias/driver option.
 result={}
 for name,endpoint in info.get('NetworkSettings',{}).get('Networks',{}).items():
  result[name]={k:copy.deepcopy(endpoint[k]) for k in ('Aliases','Links','DriverOpts','GwPriority') if endpoint.get(k) is not None}
  if 'Aliases' in result[name]:result[name]['Aliases']=[alias for alias in result[name]['Aliases'] if alias not in {info['Id'],info['Id'][:12]}]
 return result
def runtime(info):
 mounts=info['Mounts'];need(isinstance(mounts,list) and all(isinstance(row,dict) for row in mounts),'COMPLETE_MOUNT_RECORDS_REQUIRED')
 mounts=sorted(mounts,key=lambda row:json.dumps(row,sort_keys=True,separators=(',',':')))
 return {'id':info['Id'],'image':info['Image'],'started':info['State']['StartedAt'],'restart':info['RestartCount'],'config':digest({'Config':info['Config'],'HostConfig':info['HostConfig'],'Mounts':mounts,'networks':clone_networks(info)})}
def tools():
 global _TOOLS_CACHE
 # Retained helpers reject loading their module identities twice. Cache only
 # after the full hash-verified initialization succeeds, while still checking
 # the entry helper's bytes on every boundary. Runtime/DB checks live outside
 # this loader and are deliberately never cached.
 b=read(PERSONAL,PERSONAL_SHA)
 if _TOOLS_CACHE is not None:return _TOOLS_CACHE
 spec=importlib.util.spec_from_loader('_sales_dossier_personal',loader=None);r=importlib.util.module_from_spec(spec);r.__file__=str(PERSONAL);exec(compile(b,str(PERSONAL),'exec'),r.__dict__)
 u=r.load_legacy('upgrade.py');base,nav,prep,switch=u.retained_tools(r.LEGACY)
 _TOOLS_CACHE=(r,u,base,prep,switch);return _TOOLS_CACHE

def quote(name):return '"'+name.replace('"','""')+'"'
def table_schema(con,table):
 return {row[1]:(row[2],row[3],row[4],row[5]) for row in con.execute('PRAGMA table_info('+quote(table)+')')}
def table_indexes(con,table):
 return {row[1]:(row[2],row[3],row[4],tuple(item[2] for item in con.execute('PRAGMA index_info('+quote(row[1])+')'))) for row in con.execute('PRAGMA index_list('+quote(table)+')')}
def sql_snapshot(path,columns=None):
 con=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:
  con.execute('BEGIN');tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
  result={}
  for table in tables:
   schema=table_schema(con,table);cols=list(schema)
   want=columns[table]['columns'] if columns and table in columns else cols
   need(set(want)<=set(cols),'COLUMN_REMOVED')
   query='SELECT '+','.join(quote(c) for c in want)+' FROM '+quote(table)
   rows=sorted(json.dumps(list(r),ensure_ascii=True,default=lambda x:bytes(x).hex()) for r in con.execute(query))
   result[table]={'columns':cols,'schema':schema,'indexes':table_indexes(con,table),'count':len(rows),'rows_sha256':H('\n'.join(rows).encode())}
  return result
 finally:con.close()
def verify_sales_schema(path,pristine=False):
 con=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:
  con.execute('BEGIN')
  for table,expected in NEW_SCHEMA.items():
   need(table_schema(con,table)==expected,'SALES_TABLE_SCHEMA_DRIFT')
   need(table_indexes(con,table)==NEW_INDEXES[table],'SALES_INDEX_SCHEMA_DRIFT')
   need(not con.execute('PRAGMA foreign_key_list('+quote(table)+')').fetchall(),'SALES_FOREIGN_KEY_DRIFT')
   if pristine:need(con.execute('SELECT count(*) FROM '+quote(table)).fetchone()[0]==0,'NEW_SALES_TABLE_NOT_EMPTY')
  for table,expected in ADDED_SCHEMA.items():
   schema=table_schema(con,table)
   need(all(schema.get(column)==definition for column,definition in expected.items()),'SALES_COLUMN_SCHEMA_DRIFT')
   indexes=table_indexes(con,table)
   need(all(indexes.get(name)==definition for name,definition in NEW_INDEXES.get(table,{}).items()),'SALES_INDEX_SCHEMA_DRIFT')
   if pristine:
    need(con.execute('SELECT count(*) FROM '+quote(table)+' WHERE '+' OR '.join(quote(column)+' IS NOT NULL' for column in expected)).fetchone()[0]==0,'EXISTING_SALES_ROW_INITIALIZED')
 finally:con.close()

def original_rows_unchanged(before,after):
 need(set(after)==set(before)|set(NEW_TABLES),'BUSINESS_TABLE_SET_CHANGED')
 for t,row in before.items():
  need(set(after[t]['columns'])==set(row['columns'])|ADDITIONS.get(t,set()),'UNAPPROVED_SCHEMA_CHANGE')
  need(all(after[t]['schema'].get(c)==definition for c,definition in row['schema'].items()),'ORIGINAL_COLUMN_SCHEMA_CHANGED')
  need(after[t]['indexes']=={**row['indexes'],**NEW_INDEXES.get(t,{})},'ORIGINAL_INDEX_SCHEMA_CHANGED')
  if t!='alembic_version':need((row['count'],row['rows_sha256'])==(after[t]['count'],after[t]['rows_sha256']),'BUSINESS_ROWS_CHANGED_'+t.upper())
 for t,columns in NEW_TABLES.items():
  need(set(after[t]['columns'])==columns and after[t]['count']==0,'NEW_SALES_TABLE_NOT_EMPTY_OR_SCHEMA_DRIFT')
def backup(source,target):
 need(not target.exists(),'NEW_DB_SNAPSHOT_REQUIRED');a=sqlite3.connect(f'file:{source}?mode=ro',uri=True);b=sqlite3.connect(target)
 try:a.backup(b)
 finally:a.close();b.close()
 os.chmod(target,0o600)

def private_boundary(pins):
 r,u,base,prep,switch=tools()
 need(H(read(base.ENV))==pins['environment_sha256'],'PRIVATE_ENV_CHANGED')
 for role in ('api','worker'):
  row=pins['roles'][role];info=inspect('t24-private-'+role)
  proof=u.own_role(base,switch,row['id'],role,row['image'],row['attempt'],row['source'],switch.environment(info),True)
  need(proof==row['runtime'],'PRIVATE_RUNTIME_CHANGED')
 snap=prep.release_snapshot(base.PRIVATE_DB,base.BUSINESS)
 need(snap['private']['identity']==pins['databases']['private']['identity'] and snap['private']['schema_objects']==pins['databases']['private']['schema_objects'],'PRIVATE_SCHEMA_CHANGED')
 return r,u,base,prep,switch
def require_safe_original_restart(info):
 # The retained prior container must stay stopped across a Docker/host restart
 # after the sales schema commits; its old exact-head startup check would fail.
 policy=info.get('HostConfig',{}).get('RestartPolicy',{})
 need(isinstance(policy,dict) and policy.get('Name','') in ('','no','unless-stopped'),'UNSAFE_LEGACY_RESTART_POLICY')
def current_boundary(pins,after_crm=None):
 r,u,base,prep,switch=private_boundary(pins)
 crm=inspect('t24-crm')
 if after_crm:need(crm['Id']==after_crm and crm['State']['Running'],'CRM_CANDIDATE_NOT_RUNNING')
 else:
  need(crm['Id']==OLD_ID and crm['Image']==BASE_IMAGE and crm['State']['Running'],'ORIGINAL_CRM_DRIFT');require_safe_original_restart(crm)
 return r,u,base,prep,switch

def inventory_in_container(name,paths):
 script="import hashlib,json,pathlib;paths="+repr(sorted(paths))+";print(json.dumps({p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() if pathlib.Path(p).is_file() else None for p in paths}))"
 return json.loads(run(['docker','exec',name,'python','-c',script],'BACKEND_INVENTORY_FAILED'))

def checked_manifest(release,a):
 need(bool(re.fullmatch('[a-f0-9]{40}',SOURCE)) and bool(re.fullmatch('[a-f0-9]{12}',FRONTEND_VERSION)),'FROZEN_SOURCE_VERSION_REQUIRED')
 m=json.loads(read(release/'manifest.json',a.manifest_sha256));read(release/'payload.tar.gz',a.payload_sha256)
 need(m['payload_sha256']==a.payload_sha256 and m['credentials_included'] is False and all(m['preserved'].values()),'MANIFEST_SCOPE_REJECTED')
 need(m['baseline_source_sha']==BASELINE and m['source_sha']==SOURCE and m['baseline_frontend_version']==BASELINE_FRONTEND and m['frontend_version']==FRONTEND_VERSION,'SOURCE_PINS_REQUIRED')
 need(m['preserved']==PRESERVED,'PRESERVED_BOUNDARY_REQUIRED')
 need(set(m['backend_after'])==BACKEND and set(m['backend_before'])==BACKEND,'EXACT_BACKEND_SCOPE_REQUIRED')
 need({n[8:] for n in m['files'] if n.startswith('backend/')}==BACKEND,'EXACT_BACKEND_PAYLOAD_REQUIRED')
 need(all((n.startswith('static/') and static_path(n[7:])) or n in {'backend/'+b for b in BACKEND} for n in m['files']),'PAYLOAD_SCOPE_REJECTED')
 return m

def extract(release,m):
 seen=set()
 with tarfile.open(fileobj=io.BytesIO(read(release/'payload.tar.gz')),mode='r:gz') as ar:
  for item in ar:
   n=item.name;p=Path(n)
   need(item.isfile() and not p.is_absolute() and '..' not in p.parts and str(p)==n and not any(x.startswith('.') for x in p.parts) and n in m['files'] and n not in seen and item.size<16*1024**2,'PAYLOAD_MEMBER_REJECTED')
   b=ar.extractfile(item).read();need(H(b)==m['files'][n],'PAYLOAD_HASH_DRIFT');target=release/p;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);write(target,b);seen.add(n)
 need(seen==set(m['files']),'PAYLOAD_INCOMPLETE')

def environment_file(release,info):
 lines=info['Config']['Env'];need(all('\n' not in v and '\r' not in v and '=' in v for v in lines),'ENV_FORMAT_REJECTED');write(release/'crm.env',('\n'.join(lines)+'\n').encode())

def local_image_id(reference):
 status,blob=docker_request('GET','/images/'+urllib.parse.quote(reference,safe=':')+'/json')
 if status==404:return None
 need(status==200,'LOCAL_IMAGE_INSPECTION_FAILED');return json.loads(blob)['Id']
def checked_base_tag(release,m):
 need(local_image_id(BASE_IMAGE)==BASE_IMAGE,'BASE_IMAGE_ID_DRIFT')
 # BuildKit interprets bare sha256:<config-id> as repository:tag. Alias the
 # exact local image instead; never retag a pre-existing different image.
 tag='t24-crm:sales-dossier-base-'+m['source_sha'][:12]+'-'+H(str(release).encode())[:12]
 existing=local_image_id(tag)
 need(existing is None or existing==BASE_IMAGE,'BASE_TAG_ID_DRIFT')
 if existing is None:run(['docker','image','tag',BASE_IMAGE,tag],'BASE_TAG_CREATE_FAILED')
 need(local_image_id(tag)==BASE_IMAGE,'BASE_TAG_ID_DRIFT');return tag
def build_images(release,m):
 base_tag=checked_base_tag(release,m)
 dockerfile='FROM '+base_tag+'\nCOPY backend/ /app/backend/\n'
 write(release/'Dockerfile',dockerfile.encode());tag='t24-crm:sales-dossier-'+m['source_sha'][:12]
 need(local_image_id(base_tag)==BASE_IMAGE,'BASE_TAG_ID_DRIFT')
 run(['docker','build','--network=none','--pull=false','-t',tag,str(release)],'CANDIDATE_BUILD_FAILED',300)
 need(local_image_id(base_tag)==BASE_IMAGE,'BASE_TAG_ID_DRIFT')
 image=json.loads(run(['docker','image','inspect',tag],'CANDIDATE_IMAGE_INSPECTION_FAILED'))[0]['Id']
 # Recovery uses this same reviewed build after migration; legacy code is forbidden.
 return image,image


MIGRATE="""import importlib.util,sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
p='alembic/versions/f7d1c5a9b027_sales_unified_dossiers.py'
spec=importlib.util.spec_from_file_location('sales_dossier_migration',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
e=sa.create_engine('sqlite:////app/backend/data/crm_prod.db')
with e.connect() as c:
 c.exec_driver_sql('BEGIN IMMEDIATE')
 assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()=='e6c0b4f8a916'
 with Operations.context(MigrationContext.configure(c)):m.upgrade()
 c.exec_driver_sql("UPDATE alembic_version SET version_num='f7d1c5a9b027' WHERE version_num='e6c0b4f8a916'")
 c.commit()
print('ADDITIVE_MIGRATION_OK')
"""

def offline_args(release,data,image):
 return ['docker','run','--rm','--network=none','--read-only','--tmpfs','/tmp:rw,nosuid,noexec','--env-file',str(release/'crm.env'),'-e','DATABASE_URL=sqlite:///./data/crm_prod.db','-e','AUTOMATION_SCAN_ENABLED=false','--mount','type=bind,src='+str(data)+',dst=/app/backend/data','--mount','type=bind,src='+str(release/'probe-logs')+',dst=/app/backend/logs',image]

def ready(name,seconds=50):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  p=subprocess.run(['docker','exec',name,'curl','-fsS','http://127.0.0.1:8000/ready'],capture_output=True)
  if p.returncode==0:return
  time.sleep(1)
 raise RuntimeError('CANDIDATE_READINESS_TIMEOUT')

def public_directory(path,root):
 # The publisher uses umask 077 for credentials and DB snapshots. mkdir's
 # requested mode cannot override that mask, so explicitly open only the
 # immutable public tree for nginx traversal, including intermediate folders.
 need(path==root or root in path.parents,'PUBLIC_DIRECTORY_SCOPE_REJECTED')
 path.mkdir(parents=True,exist_ok=True,mode=0o755)
 for directory in (path,*path.parents):
  directory.chmod(0o755)
  if directory==root:break

def prepare(release,a,m,pins):
 current_boundary(pins);crm=inspect('t24-crm');require_safe_original_restart(crm)
 need(H(NGINX.read_bytes())==NGINX_SHA,'NGINX_BASELINE_DRIFT');need(not (release/'prepared.json').exists(),'PREPARATION_EXISTS')
 actual=inventory_in_container('t24-crm',BACKEND);need(actual==m['backend_before'],'DEPLOYED_BACKEND_DIFFERS_FROM_BASELINE')
 extract(release,m);write(release/'original-container.json',crm);environment_file(release,crm)
 # Build context contains credentials, so explicitly exclude everything except the approved code files.
 write(release/'.dockerignore',DOCKERIGNORE)
 image,rollback=build_images(release,m)
 data=release/'probe-data';data.mkdir(mode=0o700);(release/'probe-logs').mkdir(mode=0o700)
 backup(BUSINESS,data/'crm_prod.db');before=sql_snapshot(data/'crm_prod.db')
 run(offline_args(release,data,image)+['python','-c',MIGRATE],'OFFLINE_MIGRATION_FAILED');after=sql_snapshot(data/'crm_prod.db',before);original_rows_unchanged(before,after);verify_sales_schema(data/'crm_prod.db',pristine=True)
 for label,im in [('candidate',image)]:
  name='t24-sales-dossier-probe-'+label+'-'+m['source_sha'][:12];cmd=offline_args(release,data,im);cmd[2:2]=['--name',name,'-d']
  run(cmd,'OFFLINE_STARTUP_FAILED')
  try:
   ready(name);expected=m['backend_after'] if label=='candidate' else {**m['backend_before'],MIGRATION:m['backend_after'][MIGRATION]}
   need(inventory_in_container(name,BACKEND)==expected,'OFFLINE_CODE_IDENTITY_DRIFT')
  finally:run(['docker','stop','-t','20',name],'OFFLINE_PROBE_STOP_FAILED')
  original_rows_unchanged(before,sql_snapshot(data/'crm_prod.db',before))
 need(H(NGINX.read_bytes())==NGINX_SHA,'NGINX_CHANGED_DURING_PREPARATION');current_boundary(pins)
 public=Path('/var/www/t24-crm-public/sales-dossier-'+m['source_sha'][:12]+'-20261016');need(not public.exists(),'FRESH_STATIC_ROOT_REQUIRED');public_directory(public,public)
 for src in (release/'static').rglob('*'):
  if src.is_file():
   dst=public/src.relative_to(release/'static');public_directory(dst.parent,public);dst.write_bytes(src.read_bytes());dst.chmod(0o644)
 # Keep existing hashed chunks for tabs opened before deployment.
 for src in (OLD_PUBLIC/'assets').rglob('*'):
  if src.is_file():
   dst=public/'assets'/src.relative_to(OLD_PUBLIC/'assets');public_directory(dst.parent,public)
   if dst.exists():need(H(dst.read_bytes())==H(src.read_bytes()),'STATIC_ASSET_COLLISION')
   else:dst.write_bytes(src.read_bytes());dst.chmod(0o644)
 result={'stage':'SALES_DOSSIER_PREPARED_OFFLINE_VERIFIED','source_sha':m['source_sha'],'version':m['frontend_version'],'candidate_image':image,'rollback_image':rollback,'old_crm':runtime(crm),'public_root':str(public),'business_rows_unchanged_in_rehearsal':True,'private_runtime_unchanged':True,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,'preflight_sha256':a.preflight_sha256}
 result_sha=write(release/'prepared.json',result);print(json.dumps({**result,'receipt_sha256':result_sha}))

class DockerConnection(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect('/var/run/docker.sock')
def docker_request(method,path,body=None):
 conn=DockerConnection('localhost',timeout=45)
 try:
  conn.request(method,path,None if body is None else json.dumps(body),{'Content-Type':'application/json'})
  response=conn.getresponse();return response.status,response.read()
 finally:conn.close()
def inspect_optional(name):
 need(bool(re.fullmatch('[a-zA-Z0-9_.-]+',name)),'INVALID_CONTAINER_IDENTITY')
 status,blob=docker_request('GET','/containers/'+name+'/json')
 if status==404:return None
 need(status==200,'CONTAINER_INSPECTION_FAILED');return json.loads(blob)
def clone_config(image,original,source):
 config=copy.deepcopy(original['Config']);config['Image']=image;config['Hostname']=''
 config['Labels']={**(config.get('Labels') or {}),'t24.release.scope':'sales-dossier','t24.release.source':source}
 config['HostConfig']=copy.deepcopy(original['HostConfig']);config['HostConfig']['AutoRemove']=False
 networks=clone_networks(original)
 need(bool(networks) or original['HostConfig']['NetworkMode'] in ('host','none'),'ORIGINAL_NETWORKS_REQUIRED')
 config['NetworkingConfig']={'EndpointsConfig':networks};return config
def docker_create(name,image,original,source):
 status,blob=docker_request('POST','/containers/create?name='+name,clone_config(image,original,source))
 need(status==201,'CONTAINER_CREATE_FAILED');return json.loads(blob)['Id']
def cleanup_nginx_temp(original,updated):
 # An interrupted fsync/rename may leave an empty, partial or complete file.
 # Remove only a protected regular file containing a prefix of our two exact
 # approved configurations. Unknown content, links and writable files fail shut.
 temp=NGINX.parent/'.t24-sales-dossier-next'
 if not temp.exists() and not temp.is_symlink():return
 need(NGINX.read_bytes() in (original,updated),'NGINX_RECOVERY_DRIFT')
 before=temp.lstat()
 need(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and not before.st_mode&0o022,'UNKNOWN_NGINX_RECOVERY_TEMP')
 fd=os.open(temp,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  opened=os.fstat(f.fileno())
  need((opened.st_dev,opened.st_ino)==(before.st_dev,before.st_ino),'NGINX_RECOVERY_TEMP_CHANGED')
  content=f.read(max(len(original),len(updated))+1)
 need(any(value.startswith(content) for value in (original,updated)),'UNKNOWN_NGINX_RECOVERY_TEMP')
 after=temp.lstat()
 need((after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)==(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns),'NGINX_RECOVERY_TEMP_CHANGED')
 temp.unlink()
def replace_nginx(original,updated):
 need(NGINX.read_bytes()==original,'NGINX_CONCURRENT_CHANGE');temp=NGINX.parent/'.t24-sales-dossier-next'
 # Exclusive creation also rejects stale files or symbolic links after interruption.
 fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
 with os.fdopen(fd,'wb') as f:f.write(updated);f.flush();os.fsync(f.fileno())
 temp.chmod(0o644);os.replace(temp,NGINX)
def reload_nginx():
 run(['nginx','-t'],'NGINX_TEST_FAILED');run(['systemctl','reload','nginx'],'NGINX_RELOAD_FAILED')
def swap_nginx(original,updated):
 replace_nginx(original,updated)
 try:reload_nginx()
 except BaseException:
  # A failed nginx test/reload must not leave the candidate configuration on disk.
  try:replace_nginx(updated,original);reload_nginx()
  except BaseException as err:raise RuntimeError('NGINX_SWAP_AND_RESTORE_FAILED') from err
  raise
def safe_error(err):
 return str(err) if type(err) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(err)) else type(err).__name__.upper()
def migration_name(m):return 't24-sales-dossier-migrate-'+m['source_sha'][:12]
def production_migration_args(release,image,m):
 cmd=offline_args(release,BUSINESS.parent,image)
 cmd[2:2]=['--name',migration_name(m),'--label','t24.release.scope=sales-dossier','--label','t24.release.source='+m['source_sha']]
 return cmd+['python','-c',MIGRATE]
def owned_release_container(info,receipt,m):
 labels=info.get('Config',{}).get('Labels') or {}
 return info['Image'] in (receipt['candidate_image'],receipt['rollback_image']) and labels.get('t24.release.scope')=='sales-dossier' and labels.get('t24.release.source')==m['source_sha']
def settle_migration(receipt,m):
 # Killing a timed-out Docker CLI does not kill its container. Stop the exact
 # migration before reading the committed revision or starting either server.
 name=migration_name(m);info=inspect_optional(name)
 if info is None:return
 need(owned_release_container(info,receipt,m) and info['Image']==receipt['candidate_image'],'UNKNOWN_MIGRATION_CONTAINER')
 if info['State']['Running']:
  try:run(['docker','stop','-t','30',name],'MIGRATION_STOP_FAILED',45)
  except BaseException:
   current=inspect_optional(name)
   need(current is None or not current['State']['Running'],'MIGRATION_STILL_RUNNING')
 current=inspect_optional(name);need(current is None or not current['State']['Running'],'MIGRATION_STILL_RUNNING')
 if current is not None:
  try:run(['docker','rm',name],'MIGRATION_REMOVE_FAILED')
  except BaseException:need(inspect_optional(name) is None,'MIGRATION_REMOVE_FAILED')
def committed_revision():
 con=sqlite3.connect(f'file:{BUSINESS}?mode=ro',uri=True)
 try:
  con.execute('BEGIN');rows=con.execute('SELECT version_num FROM alembic_version').fetchall()
  need(len(rows)==1 and rows[0][0] in (OLD_REVISION,NEW_REVISION),'UNKNOWN_DATABASE_REVISION')
  revision=rows[0][0]
  for table,added in ADDITIONS.items():
   cols={row[1] for row in con.execute('PRAGMA table_info("'+table+'")')}
   need('id' in cols,'SALES_DOSSIER_BASE_TABLE_MISSING')
   need(added<=cols if revision==NEW_REVISION else not added&cols,'MIGRATION_REVISION_SCHEMA_MISMATCH')
  tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  for table,expected in NEW_TABLES.items():
   need(table in tables if revision==NEW_REVISION else table not in tables,'AUDIT_MIGRATION_REVISION_MISMATCH')
   if revision==NEW_REVISION:
    need({row[1] for row in con.execute('PRAGMA table_info("'+table+'")')}==expected,'AUDIT_SCHEMA_MISMATCH')
  if revision==NEW_REVISION:verify_sales_schema(BUSINESS)
  return revision
 finally:con.close()

def authorization_snapshot(path):
 # Preserve customer invitation state and private-data authorization verbatim.
 # Sales profile/audit tables are deliberately outside this security snapshot.
 con=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:
  con.execute('BEGIN');tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  wanted={'customer_access_grants':{'id':None,'customer_id':None,'employee_id':None,'access_level':None,'scopes':'{}','finance_access':'none','can_export':0,'can_delete':0,'can_reassign':0,'invitation_source':None,'invitation_status':None,'invited_at':None,'invited_by_id':None,'invited_by_name':None},'customers':{'id':None,'private_notes':None},'customer_materials':{'id':None,'visibility':'team'},'employees':{'id':None,'role':None,'status':None}}
  result={}
  for table,fields in wanted.items():
   need(table in tables,'AUTHORIZATION_BASE_TABLE_MISSING')
   columns={row[1] for row in con.execute('PRAGMA table_info("'+table+'")')}
   actual=[name for name in fields if name in columns]
   rows=[]
   for values in con.execute('SELECT '+','.join('"'+name+'"' for name in actual)+' FROM "'+table+'"'):
    row=dict(fields);row.update(dict(zip(actual,values)))
    if table=='customer_access_grants':
     row['scopes']=json.loads(row['scopes'] or '{}')
     for name in ('can_export','can_delete','can_reassign'):row[name]=int(bool(row[name]))
     row['finance_access']=row['finance_access'] or 'none'
    if table=='customer_materials':row['visibility']=row['visibility'] or 'team'
    rows.append(json.dumps(row,sort_keys=True,separators=(',',':')))
   result[table]=H('\n'.join(sorted(rows)).encode())
  config=con.execute("SELECT value_json FROM app_settings WHERE config_key='role_permissions'").fetchall() if 'app_settings' in tables else []
  result['role_permissions']=digest(config)
  return result
 finally:con.close()

def guard_old_authorization_code(release,receipt,m):
 settle_migration(receipt,m)
 need(committed_revision()==OLD_REVISION,'SCHEMA_HEAD_REQUIRES_FORWARD_RECOVERY')

def prepared_receipt(release,a,m):
 receipt=json.loads(read(release/'prepared.json',a.review_sha256))
 need(receipt['stage']=='SALES_DOSSIER_PREPARED_OFFLINE_VERIFIED' and receipt['manifest_sha256']==a.manifest_sha256 and receipt['payload_sha256']==a.payload_sha256 and receipt['preflight_sha256']==a.preflight_sha256,'PREPARED_IDENTITY_DRIFT')
 need(all(re.fullmatch('sha256:[a-f0-9]{64}',receipt[key]) for key in ('candidate_image','rollback_image')),'PREPARED_IMAGE_PINS_REQUIRED')
 need(receipt['source_sha']==m['source_sha'] and receipt['version']==m['frontend_version'],'PREPARED_SOURCE_DRIFT')
 return receipt
def recovery_original(release,receipt):
 original=json.loads(read(release/'original-container.json'));existing=inspect(OLD_ID)
 need(original['Id']==OLD_ID and original['Image']==BASE_IMAGE and runtime(original)==receipt['old_crm'],'ORIGINAL_SAVED_CONFIGURATION_DRIFT')
 # StartedAt changes if a previous recovery started the original server; its
 # immutable identity, configuration and network attachment must still match.
 need(existing['Id']==OLD_ID and existing['Image']==BASE_IMAGE and runtime(existing)['config']==receipt['old_crm']['config'],'ORIGINAL_RETAINED_CONFIGURATION_DRIFT')
 return original
def restore_crm(receipt,m,original,revision):
 need(revision==OLD_REVISION,'OLD_CRM_BUILD_FORBIDDEN_AFTER_SALES_MIGRATION')
 active=inspect_optional('t24-crm')
 if active and active['Id']!=OLD_ID:
  need(owned_release_container(active,receipt,m),'UNKNOWN_ACTIVE_CRM_CONTAINER')
  run(['docker','stop','-t','20',active['Id']],'FAILED_CANDIDATE_STOP_FAILED',45)
  run(['docker','rename',active['Id'],'t24-crm-failed-sales-dossier-'+m['source_sha'][:12]+'-'+active['Id'][:12]],'FAILED_CANDIDATE_RETAIN_FAILED')
 existing=inspect(OLD_ID)
 if existing['Name']!='/t24-crm':run(['docker','rename',OLD_ID,'t24-crm'],'ORIGINAL_RENAME_FAILED')
 run(['docker','start',OLD_ID],'ROLLBACK_START_FAILED');ready(OLD_ID);return OLD_ID

def forward_recover(release,receipt,m,pins,orig_nginx,next_nginx,reason):
 # Recover service availability with the reviewed sales build. Never restore
 # a DB snapshot or start the previous image against the new schema head.
 settle_migration(receipt,m)
 need(committed_revision()==NEW_REVISION,'SALES_DOSSIER_MIGRATION_REQUIRED')
 private_boundary(pins)
 original=recovery_original(release,receipt)
 public=Path(receipt['public_root'])
 for name,value in m['files'].items():
  if name.startswith('static/'):need(H((public/name[7:]).read_bytes())==value,'FORWARD_STATIC_FILE_DRIFT')
 active=inspect_optional('t24-crm')
 if active and active['Id']==OLD_ID:
  if active['State']['Running']:run(['docker','stop','-t','30',OLD_ID],'LEGACY_STOP_FAILED',60)
  run(['docker','rename',OLD_ID,'t24-crm-before-sales-dossier-'+m['source_sha'][:12]],'RETAIN_ORIGINAL_FAILED');active=None
 if active:
  need(owned_release_container(active,receipt,m) and active['Image']==receipt['candidate_image'],'UNKNOWN_FORWARD_CRM_CONTAINER')
  candidate=active['Id']
 else:candidate=docker_create('t24-crm',receipt['candidate_image'],original,m['source_sha'])
 run(['docker','start',candidate],'FORWARD_START_FAILED');ready(candidate)
 need(inventory_in_container(candidate,BACKEND)==m['backend_after'],'FORWARD_CODE_IDENTITY_DRIFT')
 cleanup_nginx_temp(orig_nginx,next_nginx)
 current=NGINX.read_bytes()
 if current==orig_nginx:swap_nginx(orig_nginx,next_nginx)
 else:need(current==next_nginx,'FORWARD_NGINX_DRIFT');reload_nginx()
 current_boundary(pins,candidate)
 result={'stage':'SALES_DOSSIER_FORWARD_RECOVERED','deployed':False,'database_restored':False,'old_crm_build_started':False,'private_runtime_unchanged':True,'crm_id':candidate,'reason_type':reason}
 write(release/('forward-recovery-'+str(time.time_ns())+'.json'),result)
 return result

def rollback(release,receipt,m,pins,orig_nginx,next_nginx,reason):
 settle_migration(receipt,m)
 if committed_revision()==NEW_REVISION:return forward_recover(release,receipt,m,pins,orig_nginx,next_nginx,reason)
 try:guard_old_authorization_code(release,receipt,m)
 except BaseException as err:
  result={'stage':'ROLLBACK_BLOCKED_AUTHORIZATION','database_restored':False,'old_crm_build_started':False,'reason_type':safe_error(err)}
  target=release/('rollback-blocked-'+str(time.time_ns())+'.json');write(target,result)
  raise RuntimeError('ROLLBACK_AUTHORIZATION_GUARD_REJECTED') from err
 # Recovery operations are independent. A backend failure must not prevent
 # restoring nginx, and a stale nginx file must not prevent restoring the API.
 errors=[];revision=None;restored=None;private_ok=False
 try:
  cleanup_nginx_temp(orig_nginx,next_nginx)
  current=NGINX.read_bytes()
  if current==next_nginx:swap_nginx(next_nginx,orig_nginx)
  else:need(current==orig_nginx,'ROLLBACK_NGINX_DRIFT');reload_nginx()
 except BaseException as err:errors.append('NGINX_'+safe_error(err))
 try:
  original=recovery_original(release,receipt);settle_migration(receipt,m);revision=committed_revision()
  restored=restore_crm(receipt,m,original,revision)
 except BaseException as err:errors.append('CRM_'+safe_error(err))
 try:private_boundary(pins);private_ok=True
 except BaseException as err:errors.append('PRIVATE_'+safe_error(err))
 result={'stage':'ROLLBACK_INCOMPLETE' if errors else 'ROLLED_BACK','schema_retained':None if revision is None else revision==NEW_REVISION,'database_restored':False,'restored_crm_id':restored,'private_runtime_unchanged':private_ok,'reason_type':reason,'failures':errors}
 target=release/'rollback.json'
 if target.exists():target=release/('rollback-recovery-'+str(time.time_ns())+'.json')
 write(target,result)
 need(not errors,'ROLLBACK_INCOMPLETE');return result
def recover(release,a,m,pins):
 receipt=prepared_receipt(release,a,m);private_boundary(pins)
 need(not (release/'deployed.json').exists(),'SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_ROLLBACK_REVIEW')
 started=json.loads(read(release/'activation-started.json'))
 need(started['prepared_sha256']==a.review_sha256 and started['source_sha']==m['source_sha'] and started['old_id']==OLD_ID and started['candidate_image']==receipt['candidate_image'] and started['rollback_image']==receipt['rollback_image'],'ACTIVATION_IDENTITY_DRIFT')
 orig=read(release/'nginx-before.conf');need(H(orig)==NGINX_SHA,'RECOVERY_NGINX_BASELINE_DRIFT')
 oldroot=('root '+str(OLD_PUBLIC)+';').encode();need(orig.count(oldroot)==1,'EXACT_STATIC_ROOT_REQUIRED')
 updated=orig.replace(oldroot,('root '+receipt['public_root']+';').encode())
 print(json.dumps(rollback(release,receipt,m,pins,orig,updated,'INTERRUPTED_ACTIVATION')))

def activate(release,a,m,pins):
 receipt=prepared_receipt(release,a,m)
 r,u,base,prep,switch=current_boundary(pins);need(H(NGINX.read_bytes())==NGINX_SHA,'NGINX_BASELINE_DRIFT')
 old=inspect('t24-crm');require_safe_original_restart(old);need(runtime(old)==receipt['old_crm'],'CRM_DRIFT_AFTER_REHEARSAL');original=json.loads(read(release/'original-container.json'));need(runtime(original)==runtime(old),'ORIGINAL_CONTAINER_DRIFT')
 public=Path(receipt['public_root']);need(json.loads((public/'app-version.json').read_bytes())['version']==m['frontend_version'],'STATIC_VERSION_DRIFT')
 for n,h in m['files'].items():
  if n.startswith('static/'):need(H((public/n[7:]).read_bytes())==h,'STATIC_FILE_DRIFT')
 orig_nginx=NGINX.read_bytes();oldroot=('root '+str(OLD_PUBLIC)+';').encode();need(orig_nginx.count(oldroot)==1,'EXACT_STATIC_ROOT_REQUIRED');next_nginx=orig_nginx.replace(oldroot,('root '+str(public)+';').encode())
 write(release/'nginx-before.conf',orig_nginx)
 retained='t24-crm-before-sales-dossier-'+m['source_sha'][:12];candidate=None
 write(release/'activation-started.json',{'stage':'ACTIVATING','prepared_sha256':a.review_sha256,'source_sha':m['source_sha'],'old_id':OLD_ID,'old_image':BASE_IMAGE,'candidate_image':receipt['candidate_image'],'rollback_image':receipt['rollback_image'],'retained_name':retained})
 try:
  run(['docker','stop','-t','30','t24-crm'],'CRM_STOP_FAILED',60)
  stopped=inspect(OLD_ID);need(stopped['Id']==OLD_ID and stopped['Image']==BASE_IMAGE and not stopped['State']['Running'],'CRM_NOT_STOPPED')
  backup(BUSINESS,release/'business-before.db');before=sql_snapshot(BUSINESS)
  write(release/'authorization-guard.json',authorization_snapshot(BUSINESS))
  # The only production DB writer in this phase is the additive migration.
  cmd=production_migration_args(release,receipt['candidate_image'],m)
  run(cmd,'PRODUCTION_ADDITIVE_MIGRATION_FAILED');need(committed_revision()==NEW_REVISION,'PRODUCTION_MIGRATION_NOT_COMMITTED')
  original_rows_unchanged(before,sql_snapshot(BUSINESS,before));verify_sales_schema(BUSINESS,pristine=True)
  need(json.loads(read(release/'authorization-guard.json'))==authorization_snapshot(BUSINESS),'MIGRATION_CHANGED_AUTHORIZATION')
  run(['docker','rename','t24-crm',retained],'RETAIN_ORIGINAL_FAILED');candidate=docker_create('t24-crm',receipt['candidate_image'],original,m['source_sha']);run(['docker','start',candidate],'CANDIDATE_START_FAILED');ready(candidate)
  need(inventory_in_container(candidate,BACKEND)==m['backend_after'],'LIVE_CODE_IDENTITY_DRIFT')
  current_boundary(pins,candidate);swap_nginx(orig_nginx,next_nginx)
  base.public_check(base.file_map(public),m['frontend_version'],public,verify_services=False)
  run(['curl','-fsS','https://t24-crm.com/ready'],'PUBLIC_CRM_NOT_READY')
  current_boundary(pins,candidate)
  result={'stage':'SALES_DOSSIER_DEPLOYED_VERIFIED','deployed':True,'source_sha':m['source_sha'],'frontend_version':m['frontend_version'],'crm':runtime(inspect(candidate)),'retained_original':retained,'rollback_image':receipt['rollback_image'],'private_runtime_unchanged':True,'financial_rows_unchanged_during_migration':True,'migration':NEW_REVISION,'public_root':str(public),'new_nginx_sha256':H(next_nginx)}
  proof=write(release/'deployed.json',result);print(json.dumps({**result,'receipt_sha256':proof}))
 except BaseException as err:
  # Never restore the DB, including when a migration committed but its CLI
  # response was lost. Recovery inspects the real schema, never a local boolean.
  rollback(release,receipt,m,pins,orig_nginx,next_nginx,type(err).__name__)
  raise

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['prepare','activate','recover'],required=True);ap.add_argument('--release',type=Path,required=True);ap.add_argument('--manifest-sha256',required=True);ap.add_argument('--payload-sha256',required=True);ap.add_argument('--preflight',type=Path,required=True);ap.add_argument('--preflight-sha256',required=True);ap.add_argument('--review-sha256');a=ap.parse_args()
 need(socket.gethostname()==HOST and os.geteuid()==0,'EXACT_SERVER_ROOT_REQUIRED');os.umask(0o077);sys.dont_write_bytecode=True
 need(a.release.resolve()==a.release and a.release.parent==Path('/opt/t24-crm/releases') and a.release.stat().st_uid==0 and stat.S_IMODE(a.release.stat().st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
 lock=os.open('/opt/t24-crm/releases/.sales-dossier-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 m=checked_manifest(a.release,a);pins=json.loads(read(a.preflight,a.preflight_sha256))
 if a.phase=='prepare':prepare(a.release,a,m,pins)
 else:
  need(bool(a.review_sha256),'INDEPENDENT_PREPARE_RECEIPT_REQUIRED')
  (activate if a.phase=='activate' else recover)(a.release,a,m,pins)
if __name__=='__main__':
 try:main()
 except BaseException as e:
  code=str(e) if type(e) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(e)) else type(e).__name__.upper()
  print(json.dumps({'stage':'SALES_DOSSIER_RELEASE_REJECTED','code':code}));sys.exit(1)
