#!/usr/bin/env python3
"""One-service forward patch; no migrations, database restoration or static/private writes."""
import argparse,copy,fcntl,hashlib,io,json,os,re,socket,sqlite3,stat,subprocess,sys,tarfile,time
from pathlib import Path

SOURCE='aa3461c2eed92269ebdf7b55ce182ec04619b04b'
BASELINE='ccf55231bcf1fda629cbb2cfaba64f1739e31396'
BASELINE_APPLICATION_SOURCE='7afebc98140e00dfb5fed47be7215ef6db1e7b41'
FRONTEND_VERSION='d1dffbe546bf'
BASE_IMAGE='sha256:4c88cc34bb5e73558e781dab2d28f97c6bdd55f360a20771249fc7ea6cc47dee'
OLD_ID='a3bf001387ec4bac8ec650c584c8f51e478c38335977ed9c01bfabd950e3dd3d'
OLD_CONFIG='1ac40aa280d1a76ab780b87841110118094631af2b2475ee22028b1da7aa4537'
REVISION='c0f4a8d6e123'
HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE='service-followthrough-current-period'
BACKEND={'services/service_follow_through.py'}
TESTS={'app/backend/tests/test_service_follow_through.py'}
LIVE_PREFLIGHT_SHA='e237c5abcc101537c6c115efb7529bdd66c40d7c36df225629a361257d92f72c'
BASE_BACKEND_SHA='ff9e56f3c2fd3766a7fab76a893e92819d3098fa86089124ff9a99430a1fa4ea'
SCHEMA_SHA='543ab530306c54054fbbe648783021281eba9980ba2cd57fa5e95e7544716e03'
STATIC_SHA='f998b49c51fe54760b64fc5275b25318d537e57f077ed434cd45045f31b4efe1'
BUSINESS_IDENTITY=(64515,262854)
PUBLIC=Path('/var/www/t24-crm-public/service-followthrough-7afebc98140e-20261018')
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA='3436be119a39e3fbd69f3d9356aed3727ee2914bfe876446b120cb46a258c374'
BUSINESS=Path('/opt/t24-crm/app/data/crm_prod.db')
RETAINED=Path('/opt/t24-crm/releases/sales-dossier-3aaae9f6b13a-20261016/release.py')
RETAINED_SHA='2e1d59d25010cb2141d6c6e25bcb4eaf6bc6cfdfb1015a60d3f8ac6bca5644fe'
PRESERVED={'schema':True,'business_rows':True,'company_finance_formulas':True,'close_conditions':True,
 'commission_attribution':True,'customer_invitation_rules':True,'private_workspace':True,
 'environment':True,'static':True,'nginx':True}
DOCKERIGNORE=('*\n!Dockerfile\n!backend\n!backend/services\n'+''.join('!backend/'+path+'\n' for path in sorted(BACKEND))).encode()
H=lambda body:hashlib.sha256(body).hexdigest()
_RETAINED=None

def need(ok,code):
 if not ok:raise RuntimeError(code)
def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def read(path,expected=None):
 path=Path(path);s=path.lstat()
 need(path.resolve()==path and stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and not s.st_mode&0o077,'PROTECTED_FILE_REQUIRED')
 body=path.read_bytes();need(expected is None or H(body)==expected,'FILE_HASH_DRIFT');return body
def write(path,value):
 body=value if isinstance(value,bytes) else (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
 return H(body)
def run(args,code,timeout=180):
 result=subprocess.run(args,capture_output=True,timeout=timeout)
 need(result.returncode==0,code);return result.stdout
def retained():
 global _RETAINED
 body=read(RETAINED,RETAINED_SHA)
 if _RETAINED is None:
  import types
  module=types.ModuleType('_sales_account_retained');module.__file__=str(RETAINED)
  exec(compile(body,str(RETAINED),'exec'),module.__dict__);_RETAINED=module
 return _RETAINED
def inspect(name):return json.loads(run(['docker','inspect',name],'CONTAINER_INSPECTION_FAILED'))[0]
def inspect_optional(name):return retained().inspect_optional(name)
def runtime(info):return retained().runtime(info)
def private_boundary(pins):return retained().private_boundary(pins)
def ready(name):return retained().ready(name)
def sql_snapshot(path):return retained().sql_snapshot(path)
def backup(source,target):return retained().backup(source,target)
def schema_signature(path):
 con=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:
  con.execute('BEGIN')
  need(con.execute('SELECT version_num FROM alembic_version').fetchall()==[(REVISION,)],'SCHEMA_REVISION_DRIFT')
  need(con.execute('PRAGMA quick_check').fetchall()==[('ok',)],'DATABASE_INTEGRITY_FAILED')
  objects=con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
  return digest(objects)
 finally:con.close()
def schema_boundary():
 signature=schema_signature(BUSINESS);need(signature==SCHEMA_SHA,'SCHEMA_DRIFT');return signature
def static_boundary():
 need(H(NGINX.read_bytes())==NGINX_SHA,'NGINX_DRIFT')
 need(NGINX.read_bytes().count(('root '+str(PUBLIC)+';').encode())==1,'STATIC_ROOT_DRIFT')
 need(json.loads((PUBLIC/'app-version.json').read_bytes())['version']==FRONTEND_VERSION,'FRONTEND_DRIFT')
 files={}
 for path in PUBLIC.rglob('*'):
  need(not path.is_symlink(),'STATIC_LINK_REJECTED')
  if path.is_file():files[str(path.relative_to(PUBLIC))]=H(path.read_bytes())
 need(bool(files),'STATIC_FILES_REQUIRED');need(digest(files)==STATIC_SHA,'STATIC_INVENTORY_DRIFT');return digest(files)
def boundary(pins,*,candidate=None,original=None,candidate_image=None):
 private_boundary(pins);identity=BUSINESS.stat();need((identity.st_dev,identity.st_ino)==BUSINESS_IDENTITY,'DATABASE_IDENTITY_DRIFT');schema=schema_boundary();static=static_boundary();crm=inspect('t24-crm')
 if candidate:
  need(crm['Id']==candidate and crm['Image']==candidate_image and crm['State']['Running'],'CANDIDATE_NOT_RUNNING')
  verify_clone(crm,original)
 else:
  need(crm['Id']==OLD_ID and crm['Image']==BASE_IMAGE and crm['State']['Running'],'BASELINE_CRM_DRIFT')
  need(runtime(crm)['config']==OLD_CONFIG,'BASELINE_CONFIGURATION_DRIFT')
  retained().require_safe_original_restart(crm)
 return crm,schema,static
def inventory(name):
 script="""import hashlib,json,os,pathlib
root=pathlib.Path('/app/backend');result={}
for folder,dirs,files in os.walk(root,followlinks=False):
 dirs[:]=[d for d in dirs if d not in {'data','logs','__pycache__','.git','.pytest_cache','.venv','node_modules'}]
 for child in dirs+files:
  if pathlib.Path(folder,child).is_symlink():raise RuntimeError('source symlink')
 for child in files:
  if child.endswith(('.pyc','.pyo')):continue
  p=pathlib.Path(folder,child)
  if p.is_file():result[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps(result,sort_keys=True))"""
 return json.loads(run(['docker','exec',name,'python','-c',script],'BACKEND_INVENTORY_FAILED'))
def checked_manifest(release,args):
 need(bool(re.fullmatch('[a-f0-9]{40}',SOURCE)) and bool(re.fullmatch('[a-f0-9]{64}',LIVE_PREFLIGHT_SHA)),'FROZEN_SOURCE_REQUIRED')
 manifest=json.loads(read(release/'manifest.json',args.manifest_sha256));read(release/'payload.tar.gz',args.payload_sha256)
 need(manifest['source_sha']==SOURCE and manifest['baseline_source_sha']==BASELINE and manifest['baseline_application_source']==BASELINE_APPLICATION_SOURCE,'SOURCE_PINS_REQUIRED')
 need(manifest['frontend_version']==FRONTEND_VERSION and manifest['schema_revision']==REVISION,'UNCHANGED_FRONTEND_SCHEMA_REQUIRED')
 need(manifest['payload_sha256']==args.payload_sha256 and manifest['credentials_included'] is False,'PAYLOAD_IDENTITY_DRIFT')
 need(manifest['preserved']==PRESERVED and manifest['backend_only'] is True,'SCOPE_REJECTED')
 need(manifest['live_preflight_sha256']==LIVE_PREFLIGHT_SHA and manifest['baseline_backend_inventory_sha256']==BASE_BACKEND_SHA,'LIVE_PREFLIGHT_PINS_REQUIRED')
 need(set(manifest['changed_source_files'])=={'app/backend/'+p for p in BACKEND}|TESTS,'EXACT_SOURCE_SCOPE_REQUIRED')
 need(set(manifest['backend_before'])==BACKEND and set(manifest['backend_after'])==BACKEND,'EXACT_BACKEND_SCOPE_REQUIRED')
 need(set(manifest['files'])=={'backend/'+path for path in BACKEND},'EXACT_BACKEND_PAYLOAD_REQUIRED')
 need(all(re.fullmatch('[a-f0-9]{64}',value) for value in [*manifest['files'].values(),*manifest['backend_before'].values(),*manifest['backend_after'].values()]),'FILE_HASH_PINS_REQUIRED')
 need(all(manifest['files']['backend/'+path]==manifest['backend_after'][path] for path in BACKEND),'BACKEND_HASH_IDENTITY_DRIFT')
 return manifest
def extract(release,manifest):
 seen=set()
 with tarfile.open(fileobj=io.BytesIO(read(release/'payload.tar.gz')),mode='r:gz') as archive:
  for item in archive:
   need(item.isfile() and item.name in manifest['files'] and item.name not in seen and 0<=item.size<2*1024**2,'PAYLOAD_MEMBER_REJECTED')
   body=archive.extractfile(item).read();need(H(body)==manifest['files'][item.name],'PAYLOAD_HASH_DRIFT')
   target=release/item.name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
   need(target.parent.resolve()==target.parent,'STAGING_LINK_REJECTED');write(target,body);seen.add(item.name)
 need(seen==set(manifest['files']),'PAYLOAD_INCOMPLETE')
def image_id(reference):return retained().local_image_id(reference)
def build_image(release,manifest):
 need(image_id(BASE_IMAGE)==BASE_IMAGE,'BASE_IMAGE_DRIFT')
 tag='t24-crm:service-current-period-base-'+SOURCE[:12]
 existing=image_id(tag);need(existing is None or existing==BASE_IMAGE,'BASE_TAG_DRIFT')
 if existing is None:run(['docker','image','tag',BASE_IMAGE,tag],'BASE_TAG_CREATE_FAILED')
 need(image_id(tag)==BASE_IMAGE,'BASE_TAG_DRIFT')
 dockerfile='FROM '+tag+'\n'+''.join('COPY backend/'+path+' /app/backend/'+path+'\n' for path in sorted(BACKEND))
 write(release/'Dockerfile',dockerfile.encode());write(release/'.dockerignore',DOCKERIGNORE)
 candidate='t24-crm:service-current-period-'+SOURCE[:12]
 run(['docker','build','--network=none','--pull=false','-t',candidate,str(release)],'CANDIDATE_BUILD_FAILED',300)
 need(image_id(tag)==BASE_IMAGE,'BASE_TAG_DRIFT');image=image_id(candidate)
 need(bool(re.fullmatch('sha256:[a-f0-9]{64}',image or '')),'CANDIDATE_IMAGE_PIN_REQUIRED');return image
def offline_args(release,data,image):return retained().offline_args(release,data,image)
def prepare(release,args,manifest,pins):
 old,schema,static=boundary(pins)
 need(set(path.name for path in release.iterdir())=={'release.py','manifest.json','payload.tar.gz'},'FRESH_STAGING_REQUIRED')
 before=inventory(OLD_ID);need(digest(before)==BASE_BACKEND_SHA and {path:before.get(path) for path in BACKEND}==manifest['backend_before'],'DEPLOYED_SOURCE_BASELINE_DRIFT')
 expected={**before,**manifest['backend_after']}
 extract(release,manifest);write(release/'original-container.json',old)
 before_sha=write(release/'backend-original-inventory.json',before);after_sha=write(release/'backend-candidate-inventory.json',expected)
 retained().environment_file(release,old)
 image=build_image(release,manifest)
 data=release/'probe-data';data.mkdir(mode=0o700);(release/'probe-logs').mkdir(mode=0o700)
 backup(BUSINESS,data/'crm_prod.db');rows=sql_snapshot(data/'crm_prod.db');need(len(rows)==104,'EXACT_TABLE_COUNT_REQUIRED');need(schema_signature(data/'crm_prod.db')==schema,'OFFLINE_SCHEMA_COPY_DRIFT')
 name='t24-service-current-period-probe-'+SOURCE[:12];command=offline_args(release,data,image);command[2:2]=['--name',name,'-d']
 run(command,'OFFLINE_STARTUP_FAILED')
 try:
  ready(name);need(inventory(name)==expected,'OFFLINE_PROTECTED_SOURCE_DRIFT')
 finally:run(['docker','stop','-t','20',name],'OFFLINE_PROBE_STOP_FAILED',45)
 need(sql_snapshot(data/'crm_prod.db')==rows and schema_signature(data/'crm_prod.db')==schema,'OFFLINE_DATABASE_CHANGED')
 old_now,schema_now,static_now=boundary(pins)
 need(runtime(old_now)==runtime(old) and schema_now==schema and static_now==static,'BASELINE_CHANGED_DURING_PREPARE')
 result={'stage':'SERVICE_CURRENT_PERIOD_PREPARED_OFFLINE_VERIFIED','source_sha':SOURCE,'frontend_version':FRONTEND_VERSION,
  'candidate_image':image,'old_crm':runtime(old),'schema_sha256':schema,'static_sha256':static,
  'original_inventory_sha256':before_sha,'candidate_inventory_sha256':after_sha,
  'manifest_sha256':args.manifest_sha256,'payload_sha256':args.payload_sha256,'preflight_sha256':args.preflight_sha256,
  'offline_business_rows_unchanged':True,'offline_schema_unchanged':True,'private_runtime_unchanged':True,
  'backend_only':True,'original_table_count':104,'database_migration':False,'database_restored':False}
 proof=write(release/'prepared.json',result);print(json.dumps({**result,'receipt_sha256':proof}))
def expected_labels(original):return {**(original['Config'].get('Labels') or {}),'t24.release.scope':SCOPE,'t24.release.source':SOURCE}
def clone_config(image,original):
 config=copy.deepcopy(original['Config']);config.update(Image=image,Hostname='',Labels=expected_labels(original))
 config['HostConfig']=copy.deepcopy(original['HostConfig']);config['HostConfig']['AutoRemove']=False
 networks=retained().clone_networks(original)
 need(networks or original['HostConfig']['NetworkMode'] in ('host','none'),'ORIGINAL_NETWORKS_REQUIRED')
 config['NetworkingConfig']={'EndpointsConfig':networks};return config
def verify_clone(candidate,original):
 need(candidate['Config'].get('Labels')==expected_labels(original),'CANDIDATE_LABEL_DRIFT')
 normalized=copy.deepcopy(candidate)
 for key in ('Image','Hostname','Labels'):normalized['Config'][key]=copy.deepcopy(original['Config'].get(key))
 need(runtime(normalized)['config']==runtime(original)['config'],'CANDIDATE_CONFIGURATION_DRIFT')
def docker_create(image,original):
 status,body=retained().docker_request('POST','/containers/create?name=t24-crm',clone_config(image,original))
 need(status==201,'CONTAINER_CREATE_FAILED');return json.loads(body)['Id']
def owned(info,receipt):
 labels=info.get('Config',{}).get('Labels') or {}
 return info['Image']==receipt['candidate_image'] and labels.get('t24.release.scope')==SCOPE and labels.get('t24.release.source')==SOURCE
def reviewed_receipt(release,args,manifest):
 receipt=json.loads(read(release/'prepared.json',args.review_sha256))
 need(receipt['stage']=='SERVICE_CURRENT_PERIOD_PREPARED_OFFLINE_VERIFIED' and receipt['source_sha']==SOURCE,'PREPARED_SOURCE_DRIFT')
 need(receipt['manifest_sha256']==args.manifest_sha256 and receipt['payload_sha256']==args.payload_sha256 and receipt['preflight_sha256']==args.preflight_sha256,'PREPARED_PIN_DRIFT')
 need(receipt['original_table_count']==104,'PREPARED_TABLE_COUNT_DRIFT')
 need(receipt['schema_sha256']==SCHEMA_SHA and receipt['static_sha256']==STATIC_SHA,'PREPARED_BOUNDARY_DRIFT')
 need(receipt['frontend_version']==FRONTEND_VERSION and receipt['backend_only'] is True and receipt['database_migration'] is False and receipt['database_restored'] is False,'PREPARED_SCOPE_DRIFT')
 need(re.fullmatch('sha256:[a-f0-9]{64}',receipt['candidate_image']) and receipt['offline_business_rows_unchanged'] is True and receipt['offline_schema_unchanged'] is True and receipt['private_runtime_unchanged'] is True,'PREPARED_PROOF_REQUIRED')
 original=json.loads(read(release/'original-container.json'))
 need(original['Id']==OLD_ID and original['Image']==BASE_IMAGE and runtime(original)==receipt['old_crm'] and runtime(original)['config']==OLD_CONFIG,'SAVED_ORIGINAL_DRIFT')
 before=json.loads(read(release/'backend-original-inventory.json',receipt['original_inventory_sha256']))
 after=json.loads(read(release/'backend-candidate-inventory.json',receipt['candidate_inventory_sha256']))
 need(digest(before)==BASE_BACKEND_SHA and {path:before.get(path) for path in BACKEND}==manifest['backend_before'] and after=={**before,**manifest['backend_after']},'REVIEWED_INVENTORY_DRIFT')
 return receipt,original,before,after
def rollback(release,receipt,original,before,pins,reason):
 # A forward-only code recovery. Never start the old container or restore data.
 need(schema_boundary()==receipt['schema_sha256'] and static_boundary()==receipt['static_sha256'],'FORWARD_BOUNDARY_DRIFT')
 private_boundary(pins);active=inspect_optional('t24-crm')
 if active and active['Id']==OLD_ID:
  need(active['Image']==BASE_IMAGE and runtime(active)['config']==OLD_CONFIG,'ORIGINAL_RECOVERY_DRIFT')
  if active['State']['Running']:run(['docker','stop','-t','30',OLD_ID],'ORIGINAL_STOP_FAILED',60)
  need(not inspect(OLD_ID)['State']['Running'],'ORIGINAL_STILL_RUNNING')
  run(['docker','rename',OLD_ID,'t24-crm-before-'+SCOPE+'-'+SOURCE[:12]],'RETAIN_ORIGINAL_FAILED');active=None
 if active:
  need(owned(active,receipt),'UNKNOWN_FORWARD_CONTAINER');candidate=active['Id']
 else:candidate=docker_create(receipt['candidate_image'],original)
 run(['docker','start',candidate],'FORWARD_START_FAILED');ready(candidate)
 after={**before,**json.loads(read(release/'manifest.json',receipt['manifest_sha256']))['backend_after']}
 need(inventory(candidate)==after,'FORWARD_PROTECTED_SOURCE_DRIFT')
 _,schema,static=boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'])
 need(schema==receipt['schema_sha256'] and static==receipt['static_sha256'],'FORWARD_BOUNDARY_DRIFT')
 result={'stage':'SERVICE_CURRENT_PERIOD_FORWARD_RECOVERED','deployed':False,'source_sha':SOURCE,'crm_id':candidate,
  'database_restored':False,'database_migration':False,'old_crm_build_started':False,'static_modified':False,'nginx_modified':False,'private_runtime_unchanged':True,'reason':reason}
 write(release/('forward-recovery-'+str(time.time_ns())+'.json'),result);return result
def activate(release,args,manifest,pins):
 receipt,original,before,after=reviewed_receipt(release,args,manifest)
 current,schema,static=boundary(pins)
 need(runtime(current)==receipt['old_crm'] and schema==receipt['schema_sha256'] and static==receipt['static_sha256'],'DRIFT_AFTER_REHEARSAL')
 need(inventory(OLD_ID)==before,'LIVE_SOURCE_DRIFT_AFTER_REHEARSAL')
 need(not (release/'deployed.json').exists(),'ALREADY_DEPLOYED')
 write(release/'activation-started.json',{'source_sha':SOURCE,'review_sha256':args.review_sha256,'candidate_image':receipt['candidate_image'],'old_id':OLD_ID})
 try:
  run(['docker','stop','-t','30',OLD_ID],'CRM_STOP_FAILED',60)
  stopped=inspect(OLD_ID);need(stopped['Id']==OLD_ID and stopped['Image']==BASE_IMAGE and not stopped['State']['Running'],'CRM_NOT_STOPPED')
  backup(BUSINESS,release/'business-before.db');rows=sql_snapshot(BUSINESS);need(len(rows)==104,'EXACT_TABLE_COUNT_REQUIRED')
  need(schema_boundary()==schema,'SCHEMA_CHANGED_BEFORE_SWAP')
  run(['docker','rename',OLD_ID,'t24-crm-before-service-current-period-'+SOURCE[:12]],'RETAIN_ORIGINAL_FAILED')
  candidate=docker_create(receipt['candidate_image'],original);run(['docker','start',candidate],'CANDIDATE_START_FAILED');ready(candidate)
  need(inspect(candidate)['Image']==receipt['candidate_image'] and inventory(candidate)==after,'LIVE_PROTECTED_SOURCE_DRIFT')
  _,new_schema,new_static=boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'])
  need(new_schema==schema and new_static==static and sql_snapshot(BUSINESS)==rows,'LIVE_DATABASE_OR_STATIC_CHANGED')
  run(['curl','-fsS','https://t24-crm.com/ready'],'PUBLIC_CRM_NOT_READY')
  _,new_schema,new_static=boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'])
  need(new_schema==schema and new_static==static,'FINAL_BOUNDARY_DRIFT')
  result={'stage':'SERVICE_CURRENT_PERIOD_DEPLOYED_VERIFIED','deployed':True,'source_sha':SOURCE,
   'frontend_version':FRONTEND_VERSION,'crm':runtime(inspect(candidate)),'retained_original':OLD_ID,
   'schema_revision':REVISION,'schema_unchanged':True,'business_rows_unchanged_during_swap':True,
   'private_runtime_unchanged':True,'environment_unchanged':True,'static_unchanged':True,'nginx_unchanged':True,
   'database_migration':False,'database_restored':False,'protected_inventory_sha256':receipt['candidate_inventory_sha256']}
  proof=write(release/'deployed.json',result);print(json.dumps({**result,'receipt_sha256':proof}))
 except BaseException as error:
  rollback(release,receipt,original,before,pins,safe_error(error));raise
def recover(release,args,manifest,pins):
 receipt,original,before,_=reviewed_receipt(release,args,manifest)
 need(not (release/'deployed.json').exists(),'SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_REVIEW')
 started=json.loads(read(release/'activation-started.json'))
 need(started=={'source_sha':SOURCE,'review_sha256':args.review_sha256,'candidate_image':receipt['candidate_image'],'old_id':OLD_ID},'ACTIVATION_IDENTITY_DRIFT')
 print(json.dumps(rollback(release,receipt,original,before,pins,'INTERRUPTED_ACTIVATION')))
def safe_error(error):return str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
def checked_live_preflight(path,expected):
 need(expected==LIVE_PREFLIGHT_SHA,'EXACT_LIVE_PREFLIGHT_REQUIRED');p=json.loads(read(path,expected))
 need(p['stage']=='SERVICE_CURRENT_PERIOD_READ_ONLY_PREFLIGHT' and p['baseline_carrier']==BASELINE,'LIVE_PREFLIGHT_STAGE_DRIFT')
 need(p['crm']['id']==OLD_ID and p['crm']['image']==BASE_IMAGE and p['crm']['config']==OLD_CONFIG,'LIVE_PREFLIGHT_RUNTIME_DRIFT')
 need(p['schema_revision']==REVISION and p['schema_sha256']==SCHEMA_SHA and p['business_table_count']==104,'LIVE_PREFLIGHT_SCHEMA_DRIFT')
 need(p['backend_inventory_sha256']==BASE_BACKEND_SHA and p['frontend_version']==FRONTEND_VERSION and p['public_inventory_sha256']==STATIC_SHA and p['nginx_sha256']==NGINX_SHA,'LIVE_PREFLIGHT_SOURCE_DRIFT')
 need(p['public_root']==str(PUBLIC) and tuple(p['business_identity'][k] for k in ('device','inode'))==BUSINESS_IDENTITY,'LIVE_PREFLIGHT_PATH_DRIFT')
 need(p['readonly'] is True and p['private_boundary_verified'] is True and all(p[k] is False for k in ('database_modified','services_modified','files_written','provider_requests')),'READ_ONLY_PREFLIGHT_REQUIRED');return p
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['prepare','activate','recover'],required=True)
 parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True)
 parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True)
 parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
 need(socket.gethostname()==HOST and os.geteuid()==0,'EXACT_SERVER_ROOT_REQUIRED');os.umask(0o077);sys.dont_write_bytecode=True
 need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases') and args.release.stat().st_uid==0 and stat.S_IMODE(args.release.stat().st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
 lock=os.open('/opt/t24-crm/releases/.service-current-period-boundaries-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=checked_manifest(args.release,args);checked_live_preflight(args.preflight,args.preflight_sha256)
 pins=json.loads(read(Path('/opt/t24-crm/releases/commission-service-month-preflight-20261013.json'),'af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161'))
 if args.phase=='prepare':prepare(args.release,args,manifest,pins)
 else:
  need(bool(args.review_sha256),'INDEPENDENT_PREPARE_REVIEW_REQUIRED')
  (activate if args.phase=='activate' else recover)(args.release,args,manifest,pins)
if __name__=='__main__':
 try:main()
 except BaseException as error:
  print(json.dumps({'stage':'SERVICE_CURRENT_PERIOD_RELEASE_REJECTED','code':safe_error(error)}));sys.exit(1)
