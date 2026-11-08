"""Scoped RingCentral backend+static release; never print credentials or business rows.

Input manifest keys: source_sha, frontend_version, backend_before (relative paths ->
sha256 or null), files (backend/... and static/... -> sha256), payload_sha256.
Phases: capture, prepare, activate, status, recover. All state lives root-private.
"""
import argparse, copy, fcntl, hashlib, http.client, io, json, os, re, shutil, socket, sqlite3, stat, subprocess, tarfile, time, urllib.parse
from pathlib import Path

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = '18240e28774a1ce6043d06d1f7f913af2e9a369e'
OLD = 'i54af678a914'
NEW = 'j65bc789b025'
DB = Path('/opt/t24-crm/app/data/crm_prod.db')
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
RUNTIME_PATHS = {
 'models/ringcentral_call_records.py', 'models/ringcentral_connections.py',
 'routers/ringcentral.py', 'routers/sales_leads.py',
 'services/ringcentral_sync.py', 'services/ringcentral_team.py',
 'alembic/versions/j65bc789b025_ringcentral_provider_identity.py',
}
BACKBONE = RUNTIME_PATHS - {'routers/ringcentral.py', 'routers/sales_leads.py'}
ERROR_LOG = None
H = lambda value: hashlib.sha256(value).hexdigest()

def need(value, code):
 if not value: raise RuntimeError(code)

def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
def digest(value): return H(canonical(value))
def write(path, value):
 body = value if isinstance(value, bytes) else canonical(value) + b'\n'
 fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
 with os.fdopen(fd,'wb') as f: f.write(body);f.flush();os.fsync(f.fileno())
 return H(body)
def read(path):
 need(path.is_file() and not path.is_symlink(), 'REGULAR_STATE_FILE_REQUIRED')
 return json.loads(path.read_bytes())
def run(args, code, timeout=180):
 p=subprocess.run(args, capture_output=True, timeout=timeout)
 if p.returncode != 0:
  if ERROR_LOG is not None:
   with ERROR_LOG.open('ab') as log: log.write(('\n'+code+'\n').encode()+p.stdout+b'\n'+p.stderr)
  raise RuntimeError(code)
 return p.stdout

def inspect(name): return json.loads(run(['docker','inspect',name],'CONTAINER_INSPECT_FAILED'))[0]
def optional(name):
 p=subprocess.run(['docker','inspect',name],capture_output=True)
 return json.loads(p.stdout)[0] if p.returncode==0 else None

def networks(info):
 result={}
 for name,v in info.get('NetworkSettings',{}).get('Networks',{}).items():
  result[name]={k:copy.deepcopy(v[k]) for k in ('Aliases','Links','DriverOpts','GwPriority') if v.get(k) is not None}
  if 'Aliases' in result[name]:result[name]['Aliases']=[a for a in result[name]['Aliases'] if a not in (info['Id'],info['Id'][:12])]
 return result

def runtime(info): return dict(id=info['Id'],image=info['Image'],config=digest({'Config':info['Config'],'HostConfig':info['HostConfig'],'Mounts':info['Mounts'],'networks':networks(info)}),started=info['State']['StartedAt'])

def private_runtimes():
 result={}
 for name in ('t24-private-api','t24-private-worker'):
  v=optional(name)
  if v:result[name]=runtime(v)
 return result

INVENTORY_SCRIPT = """import pathlib,hashlib,json
r=pathlib.Path('/app/backend');excluded={'data','logs','__pycache__','.git','.pytest_cache','.venv','node_modules','work'}
print(json.dumps({str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file() and not p.is_symlink() and not any(x in excluded or x.startswith('.') for x in p.relative_to(r).parts) and p.suffix not in {'.pyc','.db','.log','.pem','.key'}}))
"""
def inventory(name):return json.loads(run(['docker','exec',name,'python','-B','-c',INVENTORY_SCRIPT],'SOURCE_INVENTORY_FAILED'))

def revision(path):
 c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
 try:
  rows=c.execute('select version_num from alembic_version').fetchall();need(len(rows)==1,'SINGLE_SCHEMA_HEAD_REQUIRED');return rows[0][0]
 finally:c.close()

def snapshot(path, project_binding_fence=False):
 c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
 try:
  c.execute('BEGIN')
  need(c.execute('PRAGMA quick_check').fetchall()==[('ok',)],'SQLITE_INTEGRITY_FAILED')
  result={}
  for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
   if name=='alembic_version':continue
   q='"'+name.replace('"','""')+'"'
   cols=[v[1] for v in c.execute('PRAGMA table_info('+q+')')]
   if project_binding_fence and name=='ringcentral_connections':cols=[col for col in cols if col!='binding_started_at']
   select=','.join(chr(34)+col.replace(chr(34),chr(34)*2)+chr(34) for col in cols)
   rows=sorted(json.dumps(list(v),ensure_ascii=True,default=lambda b:bytes(b).hex(),separators=(',',':')) for v in c.execute('SELECT '+select+' FROM '+q))
   result[name]={'columns':cols,'count':len(rows),'rows_sha256':H('\n'.join(rows).encode())}
  return result
 finally:c.close()

def schema(path):
 c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
 try:return [list(v) for v in c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()]
 finally:c.close()

def validate_schema(before,after):
 # Only the two RingCentral tables' indexes/possible constraint representation
 # may change. Every unrelated table, index, trigger and view must stay exact.
 allowed_tables={'ringcentral_connections','ringcentral_call_records'}
 allowed_indexes={'uq_ringcentral_connection_provider_identity','uq_ringcentral_call_provider_identity','ix_ringcentral_call_records_ringcentral_call_id'}
 permitted=lambda v:v[0]=='table' and v[2] in allowed_tables or v[0]=='index' and v[1] in allowed_indexes
 a=[v for v in before if not permitted(v)]
 b=[v for v in after if not permitted(v)]
 need(a==b,'UNRELATED_SCHEMA_CHANGED')
 rows={v[1]:v for v in after if v[0]=='index'}
 for name in ('uq_ringcentral_connection_provider_identity','uq_ringcentral_call_provider_identity','ix_ringcentral_call_records_ringcentral_call_id'):
  need(name in rows,'EXPECTED_PROVIDER_INDEX_MISSING')
 need('UNIQUE' not in (rows['ix_ringcentral_call_records_ringcentral_call_id'][3] or '').upper(),'OLD_GLOBAL_CALL_ID_UNIQUENESS_REMAINED')
 binding_sql=rows['uq_ringcentral_connection_provider_identity'][3] or ''
 need('UNIQUE INDEX' in binding_sql.upper() and re.search(r'WHERE\s+is_active\s*=\s*1\s*$',binding_sql,re.I),'ACTIVE_ONLY_BINDING_UNIQUENESS_REQUIRED')
 table_sql=next((v[3] or '' for v in after if v[0]=='table' and v[1]=='ringcentral_connections'),'')
 need(re.search(r'\bbinding_started_at\b',table_sql),'BINDING_FENCE_COLUMN_REQUIRED')

def validate_binding_fence(path):
 c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
 try:
  fields={v[1]:v for v in c.execute('PRAGMA table_info(ringcentral_connections)')}
  field=fields.get('binding_started_at')
  need(field is not None and str(field[2]).upper()=='DATETIME' and field[3]==0 and field[4] is None,'EXACT_NULLABLE_BINDING_FENCE_REQUIRED')
  need(c.execute('SELECT count(*) FROM ringcentral_connections WHERE binding_started_at IS NOT NULL').fetchone()[0]==0,'HISTORICAL_BINDING_FENCE_MUST_REMAIN_NULL')
 finally:c.close()

def backup(source,target):
 need(not target.exists(),'FRESH_DB_BACKUP_REQUIRED')
 a=sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True);b=sqlite3.connect(target)
 try:a.backup(b)
 finally:a.close();b.close()
 target.chmod(0o600)

def public_root():
 body=NGINX.read_text();matches=re.findall(r'^\s*root\s+(/var/www/t24-crm-public/[^;\s]+);',body,re.M)
 need(len(matches)==1,'EXACT_STATIC_ROOT_REQUIRED');return Path(matches[0])

def ready(name, timeout=65):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  p=subprocess.run(['docker','exec',name,'curl','-fsS','http://127.0.0.1:8000/ready'],capture_output=True)
  if p.returncode==0:return
  info=inspect(name)
  if not info['State']['Running']:
   save_container_logs(name);raise RuntimeError('CANDIDATE_EXITED')
  time.sleep(1)
 save_container_logs(name);raise RuntimeError('CANDIDATE_READINESS_TIMEOUT')

def save_container_logs(name):
 if ERROR_LOG is not None:
  result=subprocess.run(['docker','logs','--tail','120',name],capture_output=True)
  with ERROR_LOG.open('ab') as log:log.write(b'\nCONTAINER_DIAGNOSTICS\n'+result.stdout+b'\n'+result.stderr)

class DockerConnection(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect('/var/run/docker.sock')
def create(name,image,original):
 config=copy.deepcopy(original['Config']);config['Image']=image;config['Hostname']=''
 config['Labels']={**(config.get('Labels') or {}),'t24.release.scope':'ringcentral-team','t24.release.source':SOURCE}
 config['HostConfig']=copy.deepcopy(original['HostConfig']);config['HostConfig']['AutoRemove']=False
 config['NetworkingConfig']={'EndpointsConfig':networks(original)}
 conn=DockerConnection('localhost',timeout=45)
 try:
  conn.request('POST','/containers/create?name='+urllib.parse.quote(name),json.dumps(config),{'Content-Type':'application/json'})
  r=conn.getresponse();blob=r.read();need(r.status==201,'CANDIDATE_CONTAINER_CREATE_FAILED');return json.loads(blob)['Id']
 finally:conn.close()

def configuration_equal(current,old):
 config=copy.deepcopy(current['Config']);prior=copy.deepcopy(old['Config'])
 for key in ('Hostname','Image','Labels'):config.pop(key,None);prior.pop(key,None)
 need(config==prior,'CONTAINER_CONFIG_CHANGED')
 host=copy.deepcopy(current['HostConfig']);original=copy.deepcopy(old['HostConfig'])
 for k in ('ContainerIDFile',):host.pop(k,None);original.pop(k,None)
 # Explicitly false is equivalent to an absent AutoRemove.
 host['AutoRemove']=bool(host.get('AutoRemove'));original['AutoRemove']=bool(original.get('AutoRemove'))
 need(host==original,'HOST_SECURITY_MOUNTS_ENV_CHANGED')
 need(current['Config']['Env']==old['Config']['Env'],'ENVIRONMENT_CHANGED')
 need(networks(current)==networks(old),'NETWORK_ALIASES_CHANGED')

MIGRATE="""import importlib.util,sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
p='alembic/versions/j65bc789b025_ringcentral_provider_identity.py'
s=importlib.util.spec_from_file_location('ringcentral_identity',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
e=sa.create_engine('sqlite:////app/backend/data/crm_prod.db')
with e.connect() as c:
 c.exec_driver_sql('BEGIN IMMEDIATE')
 assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()=='i54af678a914'
 with Operations.context(MigrationContext.configure(c)):m.upgrade()
 c.exec_driver_sql(\"UPDATE alembic_version SET version_num='j65bc789b025' WHERE version_num='i54af678a914'\")
 c.commit()
print('RINGCENTRAL_MIGRATED')
"""
def offline_args(root,data,image):
 env={'APP_ENV':'test','ENVIRONMENT':'test','ENV':'test','DATABASE_SCHEMA_MODE':'verify_only',
 'JWT_SECRET_KEY':'offline-only-synthetic-jwt-012345678901234567890123456789',
 'MASK_KEY':'offline-only-synthetic-mask-012345678901234567890123456789',
 'DATABASE_URL':'sqlite:///./data/crm_prod.db','AUTOMATION_SCAN_ENABLED':'false',
 'STRIPE_HISTORY_DAILY_SCAN_ENABLED':'false','STRIPE_AUTO_POSTING_ENABLED':'false',
 'T24_GBP_SCHEDULER_ENABLED':'false','T24_GBP_ENABLED':'false','T24_GBP_API_APPROVED':'false',
 'T24_META_OPS_SCHEDULER_ENABLED':'false','T24_META_EXECUTION_ENABLED':'false',
 'T24_MEDIA_MONTHLY_AUTOPREP_ENABLED':'false','T24_MEDIA_ASSET_WORKER_ENABLED':'false',
 'T24_GBP_ONBOARDING_WORKER_ENABLED':'false','APP_AI_KEY':'','OPENAI_API_KEY':'',
 'ENABLE_MOCK_DATA':'false','MGX_LOAD_INIT_DATA':'false'}
 return ['docker','run','--rm','--network=none','--read-only','--tmpfs','/tmp:rw,nosuid,noexec',
 '--mount','type=bind,src='+str(data)+',dst=/app/backend/data',
 '--mount','type=bind,src='+str(root/'probe-logs')+',dst=/app/backend/logs',
 *[x for k,v in env.items() for x in ('-e',k+'='+v)],image]

class Release:
 def __init__(self,args):
  global ERROR_LOG
  self.root=args.release;self.args=args
  need(self.root==Path('/opt/t24-crm/releases/ringcentral-team-'+SOURCE[:12]+'-20261109'),'EXACT_RELEASE_NAMESPACE_REQUIRED')
  need(self.root.is_dir() and self.root.resolve()==self.root and self.root.stat().st_uid==0 and not self.root.stat().st_mode&0o077,'PRIVATE_RELEASE_DIRECTORY_REQUIRED')
  ERROR_LOG=self.root/'diagnostics-private.log'
  self.manifest=read(self.root/'manifest.json');m=self.manifest
  need(H((self.root/'manifest.json').read_bytes())==args.manifest_sha256,'MANIFEST_HASH_MISMATCH')
  need(m['source_sha']==SOURCE and set(m['backend_before'])==RUNTIME_PATHS,'EXACT_SOURCE_SCOPE_REQUIRED')
  need(all(n.startswith('static/') or n.startswith('backend/') and n[8:] in RUNTIME_PATHS for n in m['files']),'PAYLOAD_SCOPE_REJECTED')
  need({'static/index.html','static/app-version.json'}<=set(m['files']),'STATIC_ENTRYPOINTS_REQUIRED')
  self.public=Path('/var/www/t24-crm-public/ringcentral-team-'+SOURCE[:12]+'-20261109')
 def capture(self):
  need(not (self.root/'baseline.json').exists(),'BASELINE_ALREADY_EXISTS')
  old=inspect('t24-crm');need(old['State']['Running'],'RUNNING_ORIGINAL_REQUIRED')
  need(any(v.get('Source')==str(DB.parent) and v.get('Destination')=='/app/backend/data' and v.get('RW') for v in old['Mounts']),'EXPECTED_DATABASE_MOUNT_REQUIRED')
  need(not any(v.get('Destination') in ('/app','/app/backend') for v in old['Mounts']),'SOURCE_BIND_MOUNT_NOT_SUPPORTED')
  overlay=run(['docker','diff',old['Id']],'WRITABLE_LAYER_DIFF_FAILED').decode().splitlines()
  # Do not silently lose durable state hidden in the writable container layer.
  # Parent directory metadata, bytecode and temporary runtime files are benign;
  # every other live-only file requires explicit review before a new image.
  mount_metadata=set()
  for mount in old['Mounts']:
   target=Path(mount['Destination']);mount_metadata.add(str(target));mount_metadata.update(str(parent) for parent in target.parents)
  forbidden=[]
  for line in overlay:
   need(len(line)>2 and line[0] in 'ACD' and line[1]==' ','DOCKER_DIFF_FORMAT_REJECTED')
   name=line[2:]
   benign=(name in mount_metadata or name in {'/app','/app/backend','/tmp','/run','/var','/var/tmp','/root','/root/.cache'}
    or name.startswith(('/tmp/','/var/tmp/','/root/.cache/','/app/backend/logs/','/app/backend/data/'))
    or '/__pycache__' in name or name.endswith('.pyc'))
   if not benign:forbidden.append(name)
  write(self.root/'writable-layer-paths-private.json',overlay)
  need(not forbidden,'UNREVIEWED_WRITABLE_LAYER_STATE')
  inv=inventory(old['Id'])
  need(all(inv.get(p)==h for p,h in self.manifest['backend_before'].items()),'CHANGED_SOURCE_BASELINE_DRIFT')
  need(revision(DB)==OLD,'OLD_SCHEMA_REQUIRED')
  root=public_root();need(root.is_dir(),'OLD_PUBLIC_ROOT_MISSING')
  raw=NGINX.read_bytes();ngpath=NGINX.resolve()
  baseline={'runtime':runtime(old),'backend_inventory':inv,'database_identity':[DB.stat().st_dev,DB.stat().st_ino],'schema':schema(DB),'nginx_path':str(ngpath),'nginx_sha256':H(raw),'public_root':str(root),'private_runtimes':private_runtimes()}
  write(self.root/'nginx-before.conf',raw);write(self.root/'baseline.json',baseline)
  return {'stage':'CAPTURED','runtime':baseline['runtime'],'backend_files':len(inv),'schema_revision':OLD,'schema_objects':len(baseline['schema']),'public_root':str(root),'baseline_sha256':digest(baseline),'private_services_preserved':True}
 def baseline(self):return read(self.root/'baseline.json')
 def boundary(self):
  b=self.baseline();v=inspect('t24-crm');need(v['State']['Running'] and runtime(v)==b['runtime'],'LIVE_RUNTIME_DRIFT')
  need(inventory(v['Id'])==b['backend_inventory'],'LIVE_BACKEND_DRIFT')
  need([DB.stat().st_dev,DB.stat().st_ino]==b['database_identity'] and revision(DB)==OLD and schema(DB)==b['schema'],'LIVE_SCHEMA_DRIFT')
  need(H(NGINX.read_bytes())==b['nginx_sha256'] and str(public_root())==b['public_root'],'LIVE_NGINX_DRIFT')
  need(private_runtimes()==b['private_runtimes'],'PRIVATE_SERVICES_DRIFT')
  return v
 def extract(self):
  m=self.manifest;payload=(self.root/'payload.tar.gz').read_bytes();need(H(payload)==m['payload_sha256'],'PAYLOAD_HASH_MISMATCH');seen=set()
  with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as ar:
   for v in ar:
    need(v.isfile() and v.name in m['files'] and v.name not in seen and 0<v.size<20*1024**2,'PAYLOAD_MEMBER_REJECTED')
    p=Path(v.name);need(not p.is_absolute() and '..' not in p.parts and str(p)==v.name,'CANONICAL_PAYLOAD_PATH_REQUIRED')
    seen.add(v.name);body=ar.extractfile(v).read(v.size+1);need(len(body)==v.size and H(body)==m['files'][v.name],'PAYLOAD_MEMBER_HASH_MISMATCH')
    dst=self.root/p;dst.parent.mkdir(mode=0o700,parents=True,exist_ok=True);write(dst,body)
  need(seen==set(m['files']),'PAYLOAD_INCOMPLETE')
 def build(self,old,rollback=False):
  name='t24-crm:ringcentral-team-'+SOURCE[:12]+('-fallback' if rollback else '')
  base='t24-crm:ringcentral-team-base-'+SOURCE[:12]
  existing=subprocess.run(['docker','image','inspect',base],capture_output=True)
  if existing.returncode==0:need(json.loads(existing.stdout)[0]['Id']==old['Image'],'BASE_TAG_COLLISION')
  else:run(['docker','image','tag',old['Image'],base],'BASE_TAG_FAILED')
  files=BACKBONE if rollback else RUNTIME_PATHS
  body='FROM '+base+'\n'+''.join('COPY backend/'+p+' /app/backend/'+p+'\n' for p in sorted(files))
  dockerfile=self.root/('Dockerfile.fallback' if rollback else 'Dockerfile')
  write(dockerfile,body.encode())
  run(['docker','build','--network=none','--pull=false','-f',str(dockerfile),'-t',name,str(self.root)],'IMAGE_BUILD_FAILED',300)
  return json.loads(run(['docker','image','inspect',name],'IMAGE_INSPECT_FAILED'))[0]['Id']
 def expected(self,rollback=False):
  expected=dict(self.baseline()['backend_inventory'])
  for p in (BACKBONE if rollback else RUNTIME_PATHS):expected[p]=self.manifest['files']['backend/'+p]
  return expected
 def image_inventory(self,image):return json.loads(run(['docker','run','--rm','--network=none','--entrypoint','python',image,'-B','-c',INVENTORY_SCRIPT],'IMAGE_INVENTORY_FAILED'))
 def migrate(self,data,image,phase):
  name='t24-ringcentral-migration-'+SOURCE[:12]+'-'+phase
  need(optional(name) is None,'MIGRATION_ALREADY_ATTEMPTED_REVIEW_REQUIRED')
  cmd=offline_args(self.root,data,image);cmd[1]='create';cmd.remove('--rm');cmd[2:2]=['--name',name]
  ident=run(cmd+['python','-B','-c',MIGRATE],'MIGRATION_CREATE_FAILED').decode().strip();write(self.root/('migration-'+phase+'.json'),{'id':ident,'image':image})
  run(['docker','start',ident],'MIGRATION_START_FAILED');run(['docker','wait',ident],'MIGRATION_WAIT_FAILED',120)
  v=inspect(ident);need(not v['State']['Running'] and v['State']['ExitCode']==0,'MIGRATION_FAILED')
 def probe(self,data,image,label):
  before=snapshot(data/'crm_prod.db');before_schema=schema(data/'crm_prod.db')
  verify="import asyncio\nfrom services.database import verify_database_schema\nfrom core.database import db_manager\nasync def verify():\n await db_manager.init_db()\n await verify_database_schema()\n await db_manager.close_db()\nasyncio.run(verify())\nprint('SCHEMA_VERIFIED_NO_WRITES')"
  run(offline_args(self.root,data,image)+['python','-B','-c',verify],'OFFLINE_EXPLICIT_SCHEMA_VERIFY_FAILED')
  need(snapshot(data/'crm_prod.db')==before and schema(data/'crm_prod.db')==before_schema,'EXPLICIT_SCHEMA_VERIFY_MUTATED_DATABASE')
  name='t24-ringcentral-probe-'+SOURCE[:12]+'-'+label
  need(optional(name) is None,'PROBE_ALREADY_EXISTS')
  cmd=offline_args(self.root,data,image);cmd.remove('--rm');cmd[2:2]=['--name',name,'-d']
  ident=run(cmd,'OFFLINE_STARTUP_FAILED').decode().strip()
  try:ready(ident)
  finally:run(['docker','stop','--time','20',ident],'OFFLINE_STOP_FAILED',45)
  need(snapshot(data/'crm_prod.db')==before and schema(data/'crm_prod.db')==before_schema,'OFFLINE_STARTUP_MUTATED_DATA_OR_SCHEMA')
 def stage_public(self):
  need(not self.public.exists(),'FRESH_PUBLIC_ROOT_REQUIRED');self.public.mkdir(mode=0o755);self.public.chmod(0o755)
  for f in (self.root/'static').rglob('*'):
   if f.is_file():
    dst=self.public/f.relative_to(self.root/'static');dst.parent.mkdir(mode=0o755,parents=True,exist_ok=True);shutil.copyfile(f,dst);dst.chmod(0o644)
  old=Path(self.baseline()['public_root'])/'assets'
  if old.is_dir():
   for f in old.rglob('*'):
    if f.is_file():
     need(not f.is_symlink(),'SYMLINK_STATIC_ASSET_REJECTED');dst=self.public/'assets'/f.relative_to(old);dst.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
     if dst.exists():need(H(dst.read_bytes())==H(f.read_bytes()),'HASHED_ASSET_COLLISION')
     else:shutil.copyfile(f,dst);dst.chmod(0o644)
  for d in self.public.rglob('*'):
   if d.is_dir():d.chmod(0o755)
  self.static_check()
 def static_check(self):
  for n,h in self.manifest['files'].items():
   if n.startswith('static/'):need(H((self.public/n[7:]).read_bytes())==h,'STAGED_STATIC_DRIFT')
  need(read(self.public/'app-version.json')=={'version':self.manifest['frontend_version']},'STATIC_VERSION_DRIFT')
 def prepare(self):
  old=self.boundary();need(not(self.root/'prepared.json').exists(),'ALREADY_PREPARED')
  self.extract();write(self.root/'.dockerignore',b'*\n!backend/\n!backend/**\n!Dockerfile\n!Dockerfile.fallback\n')
  candidate=self.build(old);fallback=self.build(old,True)
  need(self.image_inventory(candidate)==self.expected(),'CANDIDATE_BACKEND_INVENTORY_DRIFT')
  need(self.image_inventory(fallback)==self.expected(True),'FALLBACK_BACKEND_INVENTORY_DRIFT')
  data=self.root/'probe-data';data.mkdir(mode=0o700);(self.root/'probe-logs').mkdir(mode=0o700)
  backup(DB,data/'crm_prod.db');before=snapshot(data/'crm_prod.db');before_schema=schema(data/'crm_prod.db')
  self.migrate(data,candidate,'offline');need(revision(data/'crm_prod.db')==NEW,'OFFLINE_HEAD_MISMATCH')
  need(snapshot(data/'crm_prod.db',project_binding_fence=True)==before,'OFFLINE_MIGRATION_CHANGED_ROWS');after_schema=schema(data/'crm_prod.db');validate_schema(before_schema,after_schema);validate_binding_fence(data/'crm_prod.db')
  self.probe(data,candidate,'candidate');self.probe(data,fallback,'fallback')
  self.stage_public();self.boundary()
  v={'stage':'PREPARED','source_sha':SOURCE,'manifest_sha256':self.args.manifest_sha256,'candidate_image':candidate,'fallback_image':fallback,'schema_after':after_schema,'public_root':str(self.public),'offline_row_preservation':True,'offline_candidate_ready':True,'offline_fallback_ready':True}
  write(self.root/'prepared.json',v);return {k:v[k] for k in v if k!='schema_after'}
 def swap_nginx(self,body):
  path=Path(self.baseline()['nginx_path']);tmp=path.with_name(path.name+'.ringcentral-next')
  fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
  with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path);run(['nginx','-t'],'NGINX_TEST_FAILED');run(['systemctl','reload','nginx'],'NGINX_RELOAD_FAILED')
 def public_check(self):
  body=run(['curl','-q','--silent','--show-error','--fail','--max-time','10','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','https://t24-crm.com/app-version.json'],'PUBLIC_VERSION_FAILED',15)
  need(json.loads(body)=={'version':self.manifest['frontend_version']},'PUBLIC_FRONTEND_VERSION_MISMATCH')
  run(['curl','-q','--silent','--show-error','--fail','--max-time','10','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','https://t24-crm.com/ready'],'PUBLIC_READY_FAILED',15)
 def activate(self):
  p=read(self.root/'prepared.json');old=self.boundary();self.static_check()
  need(p['manifest_sha256']==self.args.manifest_sha256 and p['source_sha']==SOURCE,'PREPARED_SCOPE_MISMATCH')
  need(not(self.root/'activation-started.json').exists(),'ACTIVATION_ALREADY_STARTED_REVIEW_REQUIRED')
  before_nginx=(self.root/'nginx-before.conf').read_bytes();oldroot=os.fsencode(self.baseline()['public_root']);need(before_nginx.count(oldroot)==1,'EXACT_NGINX_REPLACEMENT_REQUIRED');new_nginx=before_nginx.replace(oldroot,os.fsencode(self.public),1)
  write(self.root/'activation-started.json',{'old_id':old['Id'],'prepared_sha256':H((self.root/'prepared.json').read_bytes())})
  run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60)
  need(not inspect(old['Id'])['State']['Running'],'ORIGINAL_STILL_RUNNING')
  backup(DB,self.root/'production-before.db');before=snapshot(DB);before_schema=schema(DB);write(self.root/'production-row-evidence-before.json',before)
  need(before_schema==self.baseline()['schema'] and revision(DB)==OLD,'PRODUCTION_SCHEMA_CHANGED')
  # No app can write until migration has exited and row-preservation is proven.
  self.migrate(DB.parent,p['candidate_image'],'production');need(revision(DB)==NEW,'PRODUCTION_HEAD_MISMATCH');need(snapshot(DB,project_binding_fence=True)==before,'PRODUCTION_MIGRATION_CHANGED_ROWS');need(schema(DB)==p['schema_after'],'PRODUCTION_SCHEMA_DIFFERS_FROM_REHEARSAL');validate_binding_fence(DB)
  write(self.root/'production-migrated.json',{'schema_revision':NEW,'original_rows_preserved':True,'row_evidence_sha256':digest(before)})
  retained='t24-crm-before-ringcentral-'+SOURCE[:12];run(['docker','rename',old['Id'],retained],'RETAIN_ORIGINAL_FAILED')
  candidate=create('t24-crm',p['candidate_image'],old);write(self.root/'candidate.json',{'id':candidate,'retained':retained});run(['docker','start',candidate],'CANDIDATE_START_FAILED')
  ready(candidate);v=inspect(candidate);configuration_equal(v,old);need(inventory(candidate)==self.expected(),'LIVE_CODE_DRIFT')
  self.swap_nginx(new_nginx);self.public_check();need(private_runtimes()==self.baseline()['private_runtimes'],'PRIVATE_SERVICES_CHANGED')
  result={'stage':'DEPLOYED','source_sha':SOURCE,'frontend_version':self.manifest['frontend_version'],'schema_revision':NEW,'runtime':runtime(v),'public_root':str(self.public),'retained_original':retained,'original_rows_preserved_during_migration':True,'environment_preserved':True,'private_services_preserved':True}
  write(self.root/'deployed.json',result);return result
 def status(self):
  if (self.root/'deployed.json').exists():
   v=read(self.root/'deployed.json');need(runtime(inspect('t24-crm'))==v['runtime'],'DEPLOYED_RUNTIME_DRIFT');self.public_check();return v
  return {'stage':'NOT_DEPLOYED','activation_started':(self.root/'activation-started.json').exists(),'revision':revision(DB),'crm':runtime(inspect('t24-crm'))}
 def recover(self):
  # Recovery is forward-compatible: preserve migrated DB and every post-start
  # write. Never restore or downgrade a live database as a convenience rollback.
  need((self.root/'activation-started.json').exists(),'ACTIVATION_REQUIRED')
  p=read(self.root/'prepared.json');old=inspect(self.baseline()['runtime']['id'])
  need(runtime(old)['config']==self.baseline()['runtime']['config'],'ORIGINAL_RETAINED_CONFIG_DRIFT')
  migration=self.root/'migration-production.json'
  if migration.exists():
   mi=read(migration);mv=inspect(mi['id'])
   if mv['State']['Running']:run(['docker','wait',mi['id']],'MIGRATION_NOT_SETTLED',120)
   need(not inspect(mi['id'])['State']['Running'],'MIGRATION_STILL_RUNNING')
  rev=revision(DB);need(rev in (OLD,NEW),'UNKNOWN_SCHEMA_REFUSE_RECOVERY')
  current=optional('t24-crm')
  if current and current['Id']!=old['Id']:
   need(current['Image'] in (p['candidate_image'],p['fallback_image']),'UNKNOWN_RUNNING_CONTAINER')
   if current['State']['Running']:run(['docker','stop','--time','30',current['Id']],'CANDIDATE_STOP_FAILED',60)
   run(['docker','rename',current['Id'],'t24-ringcentral-failed-'+current['Id'][:12]],'FAILED_CANDIDATE_RETAIN_FAILED')
  if rev==OLD:
   original=inspect(old['Id'])
   if original['Name']!='/t24-crm':run(['docker','rename',old['Id'],'t24-crm'],'RESTORE_ORIGINAL_NAME_FAILED')
   run(['docker','start',old['Id']],'ORIGINAL_RESTART_FAILED');ready(old['Id'])
  else:
   if current and current['Id']==old['Id']:
    if current['State']['Running']:run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60)
    run(['docker','rename',old['Id'],'t24-crm-before-ringcentral-'+SOURCE[:12]],'RETAIN_ORIGINAL_FAILED')
   fallback=create('t24-crm',p['fallback_image'],old);write(self.root/('fallback-'+fallback[:12]+'.json'),{'id':fallback});run(['docker','start',fallback],'FALLBACK_START_FAILED');ready(fallback);configuration_equal(inspect(fallback),old);need(inventory(fallback)==self.expected(True),'FALLBACK_CODE_DRIFT')
  self.swap_nginx((self.root/'nginx-before.conf').read_bytes())
  return {'stage':'RECOVERED','schema_revision':rev,'database_restored':False,'database_downgraded':False,'forward_compatible_fallback':rev==NEW,'runtime':runtime(inspect('t24-crm'))}

def main():
 p=argparse.ArgumentParser();p.add_argument('--phase',choices=('capture','prepare','activate','status','recover'),required=True);p.add_argument('--release',type=Path,required=True);p.add_argument('--manifest-sha256',required=True);args=p.parse_args()
 need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');os.umask(0o077)
 fd=os.open('/opt/t24-crm/releases/.ringcentral-team-release.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);r=Release(args);result=getattr(r,args.phase)();print(json.dumps(result,sort_keys=True))
 except BaseException as exc:
  # Leave explicit state for review. No automatic DB restoration after any
  # possible writer start. recover phase is an explicit inspected action.
  code=str(exc) if type(exc) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(exc)) else type(exc).__name__.upper()
  print(json.dumps({'stage':'FAILED','phase':args.phase,'reason':code}));raise SystemExit(1)
 finally:os.close(fd)
if __name__=='__main__':main()
