#!/usr/bin/env python3
"""Exact service/component forward patch with controlled public-root switch; no DB migration."""
import argparse,copy,fcntl,hashlib,io,json,os,re,socket,sqlite3,stat,subprocess,sys,tarfile,time
from pathlib import Path

SOURCE='f055a21a6dfa44539e6acb1bd10405a318305934'
BASELINE='defa952ea874015eeb3447d155be13eb95f9d704'
BASELINE_APPLICATION_SOURCE='56d213bd34617df28590a4aaccdef2f92a88f2ea'
BASELINE_FRONTEND='02a54427d549'
FRONTEND_VERSION='8ca5d81df65f'
BASE_IMAGE='sha256:1e5de79d903e93cc045c31c296a56f6d614812ece305e6c211860ff81856ccf3'
OLD_ID='a74eff0a6419748ee9600435c435182baa49575b37d2f669fb5db21661787702'
OLD_CONFIG='efc5e747bb89c1501ee3fbe66449edb42e44f4fe5018caa9e504a79275a82236'
REVISION='d1a5b9e7f234'
HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE='stripe-history-charge-id-compat'
BACKEND={'services/stripe_history_reconciliation.py'}
FRONTEND={'components/StripeHistoryReconciliation.tsx'}
TESTS={'app/backend/tests/test_stripe_history_reconciliation.py','app/frontend/tests/stripe-history-reconciliation.spec.ts'}
LIVE_PREFLIGHT_SHA='31ed436b1390ef4c32f23c6811aaee6010a3668c7e4ca5d32ad317a7a07ded17'
BASE_BACKEND_SHA='b60e1544a0fd8c7f612368da73cc5f87d540d1105808ef668dadbee885f5d58c'
SCHEMA_SHA='2f36b725fc2f1a64467f735d0e29047b3406da22e9e31c893e18d42f7796525b'
STATIC_SHA='d8bb48dd9e89024a10eb4ecf54d2ae77a4a6d7d2d59fbde8ada53db3d497cc28'
BUSINESS_IDENTITY=(64515,262854)
PUBLIC=Path('/var/www/t24-crm-public/stripe-history-reconciliation-1d229e35ae32-20261018')
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA='6490cccf932df1d28326ccf6493f803e66453a6f07acf635fab34e8698102aac'
BUSINESS=Path('/opt/t24-crm/app/data/crm_prod.db')
RETAINED=Path('/opt/t24-crm/releases/sales-dossier-3aaae9f6b13a-20261016/release.py')
RETAINED_SHA='2e1d59d25010cb2141d6c6e25bcb4eaf6bc6cfdfb1015a60d3f8ac6bca5644fe'
PRESERVED={'schema':True,'business_rows':True,'company_finance_formulas':True,'close_conditions':True,
 'commission_attribution':True,'customer_invitation_rules':True,'private_workspace':True,
 'environment':True,'network':True,'mounts':True,'original_static_files':True,'original_frontend_sources':True,'nginx_all_nonroot_bytes':True}
SECRET_HOST=Path('/opt/t24-crm/secrets/stripe-history-readonly.key')
SECRET_TARGET='/run/secrets/t24_crm_stripe_history_readonly'
CREDENTIAL_PROOF=Path('/opt/t24-crm/releases/stripe-history-readonly-credential-proof-20261018.json')
CREDENTIAL_EXPECTED={'credential_content_read': False, 'ctime_ns': 1792289178973788626, 'device': 64515, 'inode': 279537, 'mount': {'read_only': True, 'source': '/opt/t24-crm/secrets/stripe-history-readonly.key', 'target': '/run/secrets/t24_crm_stripe_history_readonly'}, 'mtime_ns': 1792289178973788626, 'provisioning_proof_sha256': 'f9b35302a397cff5c29dad648d608fba24df647d0094b5c01dcdab6e2c7e9253', 'size': 108}

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
def static_path(name):
 p=Path(name)
 if not p.parts or p.is_absolute() or str(p)!=name or '\\' in name or any(x.startswith('.') for x in p.parts):return False
 if len(p.parts)==1:return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or p.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch('workbox-[a-zA-Z0-9_-]+\\.js',name))
 return p.parts[0]=='assets' and p.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}

def tree(root):
 result={}
 for p in root.rglob('*'):
  need(not p.is_symlink(),'STATIC_LINK_REJECTED')
  if p.is_file():
   name=str(p.relative_to(root));need(static_path(name),'STATIC_PATH_REJECTED');result[name]=H(p.read_bytes())
 need(bool(result),'STATIC_FILES_REQUIRED');return result

def public_root():return Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE[:12]+'-20261018')
def static_boundary():
 body=NGINX.read_bytes();need(H(body)==NGINX_SHA,'NGINX_DRIFT');need(body.count(('root '+str(PUBLIC)+';').encode())==1,'STATIC_ROOT_DRIFT')
 need(json.loads((PUBLIC/'app-version.json').read_bytes())['version']==BASELINE_FRONTEND,'FRONTEND_BASELINE_DRIFT')
 value=digest(tree(PUBLIC));need(value==STATIC_SHA,'STATIC_INVENTORY_DRIFT');return value
def public_files(manifest):
 expected={name[7:]:value for name,value in manifest['files'].items() if name.startswith('static/')}
 for name,value in tree(PUBLIC).items():
  if name.startswith('assets/'):
   need(name not in expected or expected[name]==value,'STATIC_ASSET_COLLISION');expected[name]=value
 return expected
def verify_public(root,manifest):
 need(root==public_root() and root.resolve()==root,'EXACT_PUBLIC_ROOT_REQUIRED');files=tree(root)
 need(files==public_files(manifest),'EXACT_PUBLIC_FILE_DRIFT');need(json.loads((root/'app-version.json').read_bytes())['version']==FRONTEND_VERSION,'PUBLIC_VERSION_DRIFT');return digest(files)
def stage_public(release,manifest):
 root=public_root();need(not root.exists() and not root.is_symlink(),'FRESH_STATIC_ROOT_REQUIRED');retained().public_directory(root,root)
 for name,value in public_files(manifest).items():
  target=root/name;retained().public_directory(target.parent,root)
  body=read(release/'static'/name) if 'static/'+name in manifest['files'] else (PUBLIC/name).read_bytes()
  need(H(body)==value,'STATIC_STAGE_HASH_DRIFT')
  with target.open('xb') as stream:stream.write(body)
  target.chmod(0o644)
 return root,verify_public(root,manifest)
def next_nginx(original):
 old=('root '+str(PUBLIC)+';').encode();new=('root '+str(public_root())+';').encode()
 need(H(original)==NGINX_SHA and original.count(old)==1 and new not in original,'NGINX_EXACT_BASELINE_REQUIRED');updated=original.replace(old,new)
 need(updated!=original and updated.count(new)==1 and updated.replace(new,old)==original,'NGINX_NONROOT_BYTES_CHANGED');return updated
def new_static_boundary(receipt):
 need(receipt['public_root']==str(public_root()),'CANDIDATE_PUBLIC_ROOT_DRIFT');need(digest(tree(PUBLIC))==STATIC_SHA,'OLD_STATIC_CHANGED')
 value=digest(tree(public_root()));need(value==receipt['public_inventory_sha256'],'CANDIDATE_STATIC_DRIFT');body=NGINX.read_bytes()
 need(H(body)==receipt['nginx_next_sha256'] and body.count(('root '+str(public_root())+';').encode())==1,'CANDIDATE_NGINX_DRIFT')
 need(json.loads((public_root()/'app-version.json').read_bytes())['version']==FRONTEND_VERSION,'PUBLIC_VERSION_DRIFT');return value

def credential_boundary():
 for parent in (*SECRET_HOST.parents,*CREDENTIAL_PROOF.parents):
  info=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'CREDENTIAL_PARENT_NOT_PROTECTED')
 info=SECRET_HOST.lstat();need(SECRET_HOST.resolve()==SECRET_HOST and stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600,'CREDENTIAL_FILE_NOT_PROTECTED')
 read(CREDENTIAL_PROOF,CREDENTIAL_EXPECTED['provisioning_proof_sha256'])
 current={'device':info.st_dev,'inode':info.st_ino,'size':info.st_size,'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns}
 need(all(current[key]==CREDENTIAL_EXPECTED[key] for key in current),'CREDENTIAL_METADATA_DRIFT');return CREDENTIAL_EXPECTED
def verify_secret_mount(info,offline=False):
 rows=[row for row in info['Mounts'] if row.get('Destination')==SECRET_TARGET or row.get('Source')==str(SECRET_HOST)]
 need(len(rows)==1,'EXACT_EXISTING_SECRET_MOUNT_REQUIRED');row=rows[0]
 need(row.get('Type')=='bind' and row.get('Source')==str(SECRET_HOST) and row.get('Destination')==SECRET_TARGET and row.get('RW') is False and row.get('Propagation')=='rprivate','EXISTING_SECRET_MOUNT_DRIFT')
 need(row.get('Mode') in ('','ro') if offline else row.get('Mode')=='ro','EXISTING_SECRET_MOUNT_MODE_DRIFT')
def boundary(pins,*,candidate=None,original=None,candidate_image=None,new_public=None):
 private_boundary(pins);credential_boundary();identity=BUSINESS.stat();need((identity.st_dev,identity.st_ino)==BUSINESS_IDENTITY,'DATABASE_IDENTITY_DRIFT');schema=schema_boundary();static=new_static_boundary(new_public) if new_public else static_boundary();crm=inspect('t24-crm');verify_secret_mount(crm)
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
 need(bool(re.fullmatch('[a-f0-9]{40}',SOURCE)) and bool(re.fullmatch('[a-f0-9]{64}',LIVE_PREFLIGHT_SHA)) and bool(re.fullmatch('[a-f0-9]{12}',FRONTEND_VERSION)),'FROZEN_SOURCE_REQUIRED')
 manifest=json.loads(read(release/'manifest.json',args.manifest_sha256));read(release/'payload.tar.gz',args.payload_sha256)
 need(manifest['source_sha']==SOURCE and manifest['baseline_source_sha']==BASELINE and manifest['baseline_application_source']==BASELINE_APPLICATION_SOURCE,'SOURCE_PINS_REQUIRED')
 need(manifest['frontend_version']==FRONTEND_VERSION and manifest['baseline_frontend_version']==BASELINE_FRONTEND and manifest['schema_revision']==REVISION,'EXACT_FRONTEND_SCHEMA_REQUIRED')
 need(manifest['payload_sha256']==args.payload_sha256 and manifest['credentials_included'] is False,'PAYLOAD_IDENTITY_DRIFT')
 need(manifest['preserved']==PRESERVED and manifest['backend_only'] is False and manifest['static_transition'] is True,'SCOPE_REJECTED')
 need(manifest['live_preflight_sha256']==LIVE_PREFLIGHT_SHA and manifest['baseline_backend_inventory_sha256']==BASE_BACKEND_SHA,'LIVE_PREFLIGHT_PINS_REQUIRED')
 need(set(manifest['changed_source_files'])=={'app/backend/'+p for p in BACKEND}|{'app/frontend/src/'+p for p in FRONTEND}|TESTS,'EXACT_SOURCE_SCOPE_REQUIRED')
 need(set(manifest['backend_before'])==BACKEND and set(manifest['backend_after'])==BACKEND,'EXACT_BACKEND_SCOPE_REQUIRED')
 need({name[8:] for name in manifest['files'] if name.startswith('backend/')}==BACKEND,'EXACT_BACKEND_PAYLOAD_REQUIRED')
 need(all(name in {'backend/'+path for path in BACKEND} or name.startswith('static/') and static_path(name[7:]) for name in manifest['files']),'EXACT_PAYLOAD_SCOPE_REQUIRED')
 need({'static/index.html','static/app-version.json'}<=set(manifest['files']),'STATIC_ENTRYPOINTS_REQUIRED')
 need(all(re.fullmatch('[a-f0-9]{64}',value) for value in [*manifest['files'].values(),*manifest['backend_before'].values(),*manifest['backend_after'].values()]),'FILE_HASH_PINS_REQUIRED')
 need(all(manifest['files']['backend/'+path]==manifest['backend_after'][path] for path in BACKEND),'BACKEND_HASH_IDENTITY_DRIFT')
 return manifest
def extract(release,manifest):
 seen=set()
 with tarfile.open(fileobj=io.BytesIO(read(release/'payload.tar.gz')),mode='r:gz') as archive:
  for item in archive:
   need(item.isfile() and item.name in manifest['files'] and item.name not in seen and 0<=item.size<16*1024**2,'PAYLOAD_MEMBER_REJECTED')
   body=archive.extractfile(item).read();need(H(body)==manifest['files'][item.name],'PAYLOAD_HASH_DRIFT')
   target=release/item.name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
   need(target.parent.resolve()==target.parent,'STAGING_LINK_REJECTED');write(target,body);seen.add(item.name)
 need(seen==set(manifest['files']),'PAYLOAD_INCOMPLETE')
def image_id(reference):return retained().local_image_id(reference)
def build_image(release,manifest):
 need(image_id(BASE_IMAGE)==BASE_IMAGE,'BASE_IMAGE_DRIFT')
 tag='t24-crm:stripe-history-charge-id-compat-base-'+SOURCE[:12]
 existing=image_id(tag);need(existing is None or existing==BASE_IMAGE,'BASE_TAG_DRIFT')
 if existing is None:run(['docker','image','tag',BASE_IMAGE,tag],'BASE_TAG_CREATE_FAILED')
 need(image_id(tag)==BASE_IMAGE,'BASE_TAG_DRIFT')
 dockerfile='FROM '+tag+'\n'+''.join('COPY backend/'+path+' /app/backend/'+path+'\n' for path in sorted(BACKEND))
 write(release/'Dockerfile',dockerfile.encode());write(release/'.dockerignore',DOCKERIGNORE)
 candidate='t24-crm:stripe-history-charge-id-compat-'+SOURCE[:12]
 run(['docker','build','--network=none','--pull=false','-t',candidate,str(release)],'CANDIDATE_BUILD_FAILED',300)
 need(image_id(tag)==BASE_IMAGE,'BASE_TAG_DRIFT');image=image_id(candidate)
 need(bool(re.fullmatch('sha256:[a-f0-9]{64}',image or '')),'CANDIDATE_IMAGE_PIN_REQUIRED');return image
def offline_args(release,data,image):
 args=retained().offline_args(release,data,image);need(args[-1]==image,'OFFLINE_IMAGE_POSITION_DRIFT')
 return args[:-1]+['--mount','type=bind,src='+str(SECRET_HOST)+',dst='+SECRET_TARGET+',readonly',image]
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
 backup(BUSINESS,data/'crm_prod.db');rows=sql_snapshot(data/'crm_prod.db');need(len(rows)==111,'EXACT_TABLE_COUNT_REQUIRED');need(schema_signature(data/'crm_prod.db')==schema,'OFFLINE_SCHEMA_COPY_DRIFT')
 name='t24-stripe-history-charge-id-compat-probe-'+SOURCE[:12];command=offline_args(release,data,image);command[2:2]=['--name',name,'-d']
 run(command,'OFFLINE_STARTUP_FAILED')
 try:
  ready(name);verify_secret_mount(inspect(name),offline=True);need(inventory(name)==expected,'OFFLINE_PROTECTED_SOURCE_DRIFT')
 finally:run(['docker','stop','-t','20',name],'OFFLINE_PROBE_STOP_FAILED',45)
 after_rows=sql_snapshot(data/'crm_prod.db');need(after_rows==rows and schema_signature(data/'crm_prod.db')==schema,'OFFLINE_DATABASE_CHANGED')
 row_proof=write(release/'offline-row-proof.json',{'before':rows,'after':after_rows})
 root,new_static=stage_public(release,manifest);nginx_next=H(next_nginx(NGINX.read_bytes()))
 old_now,schema_now,static_now=boundary(pins)
 need(runtime(old_now)==runtime(old) and schema_now==schema and static_now==static,'BASELINE_CHANGED_DURING_PREPARE')
 result={'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_PREPARED_OFFLINE_VERIFIED','source_sha':SOURCE,'frontend_version':FRONTEND_VERSION,
  'candidate_image':image,'old_crm':runtime(old),'schema_sha256':schema,'old_static_sha256':static,'public_inventory_sha256':new_static,'public_root':str(root),'nginx_next_sha256':nginx_next,
  'original_inventory_sha256':before_sha,'candidate_inventory_sha256':after_sha,
  'manifest_sha256':args.manifest_sha256,'payload_sha256':args.payload_sha256,'preflight_sha256':args.preflight_sha256,
  'credential_boundary':credential_boundary(),'offline_row_proof_sha256':row_proof,'offline_business_rows_unchanged':True,'offline_schema_unchanged':True,'private_runtime_unchanged':True,
  'backend_only':False,'static_transition':True,'original_table_count':111,'database_migration':False,'database_restored':False}
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
 need(receipt['stage']=='STRIPE_HISTORY_CHARGE_ID_COMPAT_PREPARED_OFFLINE_VERIFIED' and receipt['source_sha']==SOURCE,'PREPARED_SOURCE_DRIFT')
 need(receipt['manifest_sha256']==args.manifest_sha256 and receipt['payload_sha256']==args.payload_sha256 and receipt['preflight_sha256']==args.preflight_sha256,'PREPARED_PIN_DRIFT')
 need(receipt['original_table_count']==111,'PREPARED_TABLE_COUNT_DRIFT')
 need(receipt['schema_sha256']==SCHEMA_SHA and receipt['old_static_sha256']==STATIC_SHA and receipt['nginx_next_sha256']==H(next_nginx(read(release/'nginx-before.conf',NGINX_SHA) if (release/'nginx-before.conf').exists() else NGINX.read_bytes())),'PREPARED_BOUNDARY_DRIFT')
 need(receipt['frontend_version']==FRONTEND_VERSION and receipt['backend_only'] is False and receipt['static_transition'] is True and receipt['database_migration'] is False and receipt['database_restored'] is False,'PREPARED_SCOPE_DRIFT')
 need(re.fullmatch('sha256:[a-f0-9]{64}',receipt['candidate_image']) and receipt['offline_business_rows_unchanged'] is True and receipt['offline_schema_unchanged'] is True and receipt['private_runtime_unchanged'] is True,'PREPARED_PROOF_REQUIRED')
 original=json.loads(read(release/'original-container.json'))
 need(original['Id']==OLD_ID and original['Image']==BASE_IMAGE and runtime(original)==receipt['old_crm'] and runtime(original)['config']==OLD_CONFIG,'SAVED_ORIGINAL_DRIFT')
 before=json.loads(read(release/'backend-original-inventory.json',receipt['original_inventory_sha256']))
 after=json.loads(read(release/'backend-candidate-inventory.json',receipt['candidate_inventory_sha256']))
 need(digest(before)==BASE_BACKEND_SHA and {path:before.get(path) for path in BACKEND}==manifest['backend_before'] and after=={**before,**manifest['backend_after']},'REVIEWED_INVENTORY_DRIFT')
 read(release/'offline-row-proof.json',receipt['offline_row_proof_sha256']);need(receipt['credential_boundary']==credential_boundary(),'PREPARED_CREDENTIAL_METADATA_DRIFT')
 need(verify_public(public_root(),manifest)==receipt['public_inventory_sha256'] and receipt['public_root']==str(public_root()),'REVIEWED_PUBLIC_DRIFT')
 return receipt,original,before,after
def rollback(release,receipt,original,before,pins,reason):
 # Forward-only recovery: establish a stopped pre-code baseline before any new candidate action.
 need(schema_boundary()==receipt['schema_sha256'] and digest(tree(PUBLIC))==STATIC_SHA,'FORWARD_BOUNDARY_DRIFT')
 manifest=json.loads(read(release/'manifest.json',receipt['manifest_sha256']));need(verify_public(public_root(),manifest)==receipt['public_inventory_sha256'],'FORWARD_PUBLIC_DRIFT')
 private_boundary(pins);credential_boundary();active=inspect_optional('t24-crm')
 if active and active['Id']==OLD_ID:
  need(active['Name']=='/t24-crm' and active['Image']==BASE_IMAGE and runtime(active)['config']==OLD_CONFIG,'ORIGINAL_RECOVERY_DRIFT')
  if active['State']['Running']:run(['docker','stop','-t','30',OLD_ID],'ORIGINAL_STOP_FAILED',60)
  stopped=inspect(OLD_ID);need(stopped['Id']==OLD_ID and stopped['Image']==BASE_IMAGE and not stopped['State']['Running'] and runtime(stopped)['config']==OLD_CONFIG,'ORIGINAL_STILL_RUNNING')
 elif active:need(owned(active,receipt),'UNKNOWN_FORWARD_CONTAINER')
 baseline=release/'production-before-rows.json'
 if not baseline.exists():
  need(not baseline.is_symlink() and active is not None and active['Id']==OLD_ID,'FORWARD_PRE_CODE_BASELINE_UNAVAILABLE')
  rows=sql_snapshot(BUSINESS);need(len(rows)==111 and schema_boundary()==receipt['schema_sha256'],'FORWARD_PRE_CODE_BASELINE_INVALID');write(baseline,rows)
 rows=json.loads(read(baseline));need(len(rows)==111 and sql_snapshot(BUSINESS)==rows,'FORWARD_FILLED_ROWS_CHANGED')
 recovery_backup=release/('business-forward-before-'+str(time.time_ns())+'.db');backup(BUSINESS,recovery_backup)
 need(schema_signature(recovery_backup)==receipt['schema_sha256'] and sql_snapshot(recovery_backup)==rows,'FORWARD_BACKUP_NOT_CONSISTENT')
 if active and active['Id']==OLD_ID:
  run(['docker','rename',OLD_ID,'t24-crm-before-'+SCOPE+'-'+SOURCE[:12]],'RETAIN_ORIGINAL_FAILED');active=None
 if active:candidate=active['Id']
 else:candidate=docker_create(receipt['candidate_image'],original)
 run(['docker','start',candidate],'FORWARD_START_FAILED');ready(candidate)
 need(inventory(candidate)=={**before,**manifest['backend_after']},'FORWARD_PROTECTED_SOURCE_DRIFT')
 need(sql_snapshot(BUSINESS)==rows,'FORWARD_FILLED_ROWS_CHANGED')
 original_nginx=read(release/'nginx-before.conf',NGINX_SHA);updated=next_nginx(original_nginx);cleanup_nginx_temp(original_nginx,updated)
 if NGINX.read_bytes()==original_nginx:replace_nginx(original_nginx,updated)
 else:need(NGINX.read_bytes()==updated,'FORWARD_NGINX_DRIFT')
 retained().reload_nginx();boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'],new_public=receipt)
 need(json.loads(run(['curl','-fsS','https://t24-crm.com/app-version.json'],'FORWARD_PUBLIC_VERSION_FAILED')).get('version')==FRONTEND_VERSION,'FORWARD_PUBLIC_VERSION_DRIFT')
 run(['curl','-fsS','https://t24-crm.com/ready'],'FORWARD_PUBLIC_READY_FAILED');need(sql_snapshot(BUSINESS)==rows,'FORWARD_FINAL_FILLED_ROWS_CHANGED')
 result={'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_FORWARD_RECOVERED','deployed':False,'source_sha':SOURCE,'crm_id':candidate,'database_restored':False,'database_migration':False,'old_crm_build_started':False,'public_root':str(public_root()),'nginx_only_public_root_changed':True,'all_111_rows_unchanged':True,'private_runtime_unchanged':True,'reason':reason}
 write(release/('forward-recovery-'+str(time.time_ns())+'.json'),result);return result


def activate(release,args,manifest,pins):
 receipt,original,before,after=reviewed_receipt(release,args,manifest)
 current,schema,static=boundary(pins)
 need(runtime(current)==receipt['old_crm'] and schema==receipt['schema_sha256'] and static==receipt['old_static_sha256'],'DRIFT_AFTER_REHEARSAL')
 need(inventory(OLD_ID)==before,'LIVE_SOURCE_DRIFT_AFTER_REHEARSAL')
 need(not (release/'deployed.json').exists(),'ALREADY_DEPLOYED')
 original_nginx=NGINX.read_bytes();updated_nginx=next_nginx(original_nginx);need(H(updated_nginx)==receipt['nginx_next_sha256'],'REVIEWED_NGINX_DRIFT');write(release/'nginx-before.conf',original_nginx)
 write(release/'activation-started.json',{'source_sha':SOURCE,'review_sha256':args.review_sha256,'candidate_image':receipt['candidate_image'],'old_id':OLD_ID})
 try:
  run(['docker','stop','-t','30',OLD_ID],'CRM_STOP_FAILED',60)
  stopped=inspect(OLD_ID);need(stopped['Id']==OLD_ID and stopped['Image']==BASE_IMAGE and not stopped['State']['Running'],'CRM_NOT_STOPPED')
  rows=sql_snapshot(BUSINESS);need(len(rows)==111,'EXACT_TABLE_COUNT_REQUIRED');before_rows_sha=write(release/'production-before-rows.json',rows)
  backup(BUSINESS,release/'business-before.db');need(sql_snapshot(release/'business-before.db')==rows,'PRODUCTION_BACKUP_NOT_CONSISTENT')
  need(schema_boundary()==schema,'SCHEMA_CHANGED_BEFORE_SWAP')
  run(['docker','rename',OLD_ID,'t24-crm-before-stripe-history-charge-id-compat-'+SOURCE[:12]],'RETAIN_ORIGINAL_FAILED')
  candidate=docker_create(receipt['candidate_image'],original);run(['docker','start',candidate],'CANDIDATE_START_FAILED');ready(candidate)
  need(inspect(candidate)['Image']==receipt['candidate_image'] and inventory(candidate)==after,'LIVE_PROTECTED_SOURCE_DRIFT')
  _,new_schema,new_static=boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'])
  after_rows=sql_snapshot(BUSINESS);need(new_schema==schema and new_static==static and after_rows==rows,'LIVE_DATABASE_OR_STATIC_CHANGED');after_rows_sha=write(release/'production-after-startup-rows.json',after_rows)
  replace_nginx(original_nginx,updated_nginx);retained().reload_nginx()
  run(['curl','-fsS','https://t24-crm.com/ready'],'PUBLIC_CRM_NOT_READY')
  _,new_schema,new_static=boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'],new_public=receipt)
  need(new_schema==schema and new_static==receipt['public_inventory_sha256'],'FINAL_BOUNDARY_DRIFT')
  need(json.loads(run(['curl','-fsS','https://t24-crm.com/app-version.json'],'PUBLIC_VERSION_FAILED')).get('version')==FRONTEND_VERSION,'PUBLIC_VERSION_DRIFT')
  final_rows=sql_snapshot(BUSINESS);need(final_rows==rows,'FINAL_FILLED_ROWS_CHANGED');final_after_sha=write(release/'production-after-rows.json',final_rows)
  result={'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_DEPLOYED_VERIFIED','deployed':True,'source_sha':SOURCE,
   'frontend_version':FRONTEND_VERSION,'crm':runtime(inspect(candidate)),'retained_original':OLD_ID,
   'schema_revision':REVISION,'schema_unchanged':True,'business_rows_unchanged_during_swap':True,
   'private_runtime_unchanged':True,'credential_boundary':credential_boundary(),'environment_unchanged':True,'network_unchanged':True,'mounts_unchanged':True,'production_before_rows_sha256':before_rows_sha,'production_after_rows_sha256':final_after_sha,'startup_after_rows_sha256':after_rows_sha,'old_static_preserved':True,'static_updated_as_reviewed':True,'nginx_only_public_root_changed':True,'public_root':str(public_root()),'public_inventory_sha256':new_static,'nginx_sha256':receipt['nginx_next_sha256'],'schema_sha256':new_schema,
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
 need(p['stage']=='STRIPE_HISTORY_CHARGE_ID_COMPAT_READ_ONLY_PREFLIGHT' and p['baseline_carrier']==BASELINE,'LIVE_PREFLIGHT_STAGE_DRIFT')
 need(p['crm']['id']==OLD_ID and p['crm']['image']==BASE_IMAGE and p['crm']['config']==OLD_CONFIG,'LIVE_PREFLIGHT_RUNTIME_DRIFT')
 need(p['schema_revision']==REVISION and p['schema_sha256']==SCHEMA_SHA and p['business_table_count']==111,'LIVE_PREFLIGHT_SCHEMA_DRIFT')
 need(p['backend_inventory_sha256']==BASE_BACKEND_SHA and p['frontend_version']==BASELINE_FRONTEND and p['public_inventory_sha256']==STATIC_SHA and p['nginx_sha256']==NGINX_SHA,'LIVE_PREFLIGHT_SOURCE_DRIFT')
 need(p['public_root']==str(PUBLIC) and tuple(p['business_identity'][k] for k in ('device','inode'))==BUSINESS_IDENTITY,'LIVE_PREFLIGHT_PATH_DRIFT')
 need(p['readonly'] is True and p['private_boundary_verified'] is True and all(p[k] is False for k in ('database_modified','services_modified','files_written','provider_requests')),'READ_ONLY_PREFLIGHT_REQUIRED');return p
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['prepare','activate','recover'],required=True)
 parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True)
 parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True)
 parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
 need(socket.gethostname()==HOST and os.geteuid()==0,'EXACT_SERVER_ROOT_REQUIRED');os.umask(0o077);sys.dont_write_bytecode=True
 need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases') and args.release.stat().st_uid==0 and stat.S_IMODE(args.release.stat().st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
 lock=os.open('/opt/t24-crm/releases/.stripe-history-charge-id-compat-boundaries-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=checked_manifest(args.release,args);checked_live_preflight(args.preflight,args.preflight_sha256)
 pins=json.loads(read(Path('/opt/t24-crm/releases/commission-service-month-preflight-20261013.json'),'af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161'))
 if args.phase=='prepare':prepare(args.release,args,manifest,pins)
 else:
  need(bool(args.review_sha256),'INDEPENDENT_PREPARE_REVIEW_REQUIRED')
  (activate if args.phase=='activate' else recover)(args.release,args,manifest,pins)

def replace_nginx(original,updated):
 need(NGINX.read_bytes()==original,'NGINX_CONCURRENT_CHANGE');temp=NGINX.parent/('.t24-'+SCOPE+'-next')
 fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
 with os.fdopen(fd,'wb') as stream:stream.write(updated);stream.flush();os.fsync(stream.fileno())
 temp.chmod(0o644);os.replace(temp,NGINX)

def cleanup_nginx_temp(original,updated):
 temp=NGINX.parent/('.t24-'+SCOPE+'-next')
 if not temp.exists() and not temp.is_symlink():return
 need(NGINX.read_bytes() in (original,updated),'NGINX_RECOVERY_DRIFT');info=temp.lstat()
 need(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and not info.st_mode&0o022,'UNKNOWN_NGINX_TEMP')
 fd=os.open(temp,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  opened=os.fstat(stream.fileno());need((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'NGINX_TEMP_CHANGED');body=stream.read(max(len(original),len(updated))+1)
 need(any(value.startswith(body) for value in (original,updated)),'UNKNOWN_NGINX_TEMP');after=temp.lstat()
 need((after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)==(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns),'NGINX_TEMP_CHANGED');temp.unlink()

if __name__=='__main__':
 try:main()
 except BaseException as error:
  print(json.dumps({'stage':'STRIPE_HISTORY_CHARGE_ID_COMPAT_RELEASE_REJECTED','code':safe_error(error)}));sys.exit(1)
