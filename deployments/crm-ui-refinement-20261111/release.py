"""No-migration CRM UI runtime and static release.

Manifest: source_sha, frontend_version, backend_before{frozen relative paths: sha or null},
files{backend/<relative> or static/<dist-relative>: sha}, payload_sha256.
No credentials are persisted; neither activation nor recovery writes the DB.
"""
import argparse, copy, fcntl, hashlib, itertools, json, os, re, socket, subprocess, time, types, urllib.parse
from pathlib import Path

HOST='iZj6c4cj7edgnhdimts4l7Z'
LEGACY_ROOT=Path('/opt/t24-crm/releases/ringcentral-team-18240e28774a-20261109')
LEGACY_SHA='922e0ed7d3fbde5d2985a5ea2a02b90b9622262f1969c8146535665133589f85'
LEGACY_SOURCE='18240e28774a1ce6043d06d1f7f913af2e9a369e'
PRIOR_ROOT=Path('/opt/t24-crm/releases/beautyos-sales-knowledge-f89031f4818e-20261110')
BASE_SOURCE='f89031f4818ec2114594b73a9c3d750ee88014fd'
BASE_STATIC_SOURCE=BASE_SOURCE
BASE_ID='4a81be38b526008b93dd26ab2f753dbfaa60bd4b94031c4477d0378d0d1e543a'
BASE_IMAGE='sha256:5ec19f11c845cd386bbe699ee3d4b76234b6bc5be742fe01184602acec86252f'
BASE_STARTED='2026-11-10T13:05:45.18541659Z'
SCHEMA='j65bc789b025'
BASE_FRONTEND_VERSION='a8cce266e74e'
BASE_CONFIG_SHA='aece28d499fd74e6c4abfd4c39fdc2f36fc3a070ef3f30932517ee25608cc6d6'
BASE_PUBLIC_ROOT='/var/www/t24-crm-public/beautyos-sales-knowledge-f89031f4818e-20261110'
BASE_SCHEMA_SHA='ca15d3cb51c5cb99a68865c6a0c0d5aadd32ee1c5a5cfbc70dee7bfbbf4baa6a'
BASE_DATABASE_IDENTITY=[64515, 262854]
BASE_INVENTORY_SHA='444d8d6591718bc3ecfb7a6f568be0835616db2e7801449a7b665054bf3665ae'
BASE_INVENTORY_COUNT=443
BASE_PRIVATE_RUNTIMES={'t24-private-api': {'config': '04160cf058e2e8b47b719e731a813af4bdb12144850680b50ed2ec00dd5491e2', 'id': 'f8644b043b7f9d8e57190a8e7f411291ccb0814871428891e00e77cb74974d6b', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'started': '2026-10-11T23:58:43.773320701Z'}, 't24-private-worker': {'config': '7dba014c965ef1c4618a0a33546a5089edb27095a3c06ce05ab06d01a8ceb061', 'id': '7f7930d5ea468765c404a163ecb0cb4d2935b793ad4435efc8ca8aa782772cab', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'started': '2026-10-11T23:58:58.055948866Z'}}
BASE_BACKEND_BEFORE={'models/employees.py': '04c049ccf54e8b3dc431b780acec0ed0db1038c400a83ab532e5212eb2568699', 'routers/employees.py': 'f06e723df1e26ea0a8a39a58aa6028609df04f838186fc6ddea124cc86a182db', 'routers/finance_entry_drafts.py': '56830b23579e8b43faf90476a8bfe3e1d94c8a7177bc3b7a38b3228d639b2f6f', 'services/finance_entry_drafts.py': '6339009f168d97023b7e68ce3432d4e921df4e165dad8f71cae9481b7aff0486'}
RUNTIME_PATHS=set(BASE_BACKEND_BEFORE) # FROZEN_RUNTIME_PATHS
H=lambda body:hashlib.sha256(body).hexdigest()

def need(ok,code):
 if not ok:raise RuntimeError(code)

def load_helper():
 path=LEGACY_ROOT/'release.py'
 need(path.resolve()==path and path.is_file() and path.stat().st_uid==0 and not path.stat().st_mode&0o022,'ROOT_PROTECTED_LEGACY_HELPER_REQUIRED')
 body=path.read_bytes();need(H(body)==LEGACY_SHA,'LEGACY_HELPER_HASH_MISMATCH')
 m=types.ModuleType('multichannel_timezone_legacy');m.__file__=str(path);exec(compile(body,str(path),'exec'),m.__dict__)
 need(m.SOURCE==LEGACY_SOURCE and m.NEW==SCHEMA,'EXPECTED_COMMON_RUNTIME_HELPER_REQUIRED')
 return m

def equivalent_private_runtime(m,info,expected):
 # Docker may return the same Mounts array in a different order. Nothing else
 # is normalized: recover the exact frozen configuration hash by permuting
 # complete mount dictionaries, never by deleting security/configuration fields.
 actual=m.runtime(info)
 need(info['State']['Running'] is True,'PRIVATE_SERVICE_NOT_RUNNING')
 need(all(actual[key]==expected[key] for key in ('id','image','started')),'PRIVATE_RUNTIME_IDENTITY_DRIFT')
 mounts=info['Mounts'];need(len(mounts)==2,'PRIVATE_MOUNT_COUNT_DRIFT')
 parts={'Config':info['Config'],'HostConfig':info['HostConfig'],'Mounts':mounts,'networks':m.networks(info)}
 for order in itertools.permutations(range(len(mounts))):
  candidate={**parts,'Mounts':[mounts[index] for index in order]}
  if m.digest(candidate)==expected['config']:
   return {**actual,'config':expected['config']},{'observed_config_sha256':actual['config'],'baseline_config_sha256':expected['config'],'mount_order':list(order),'exact_configuration_equivalence':True}
 raise RuntimeError('PRIVATE_RUNTIME_CONFIGURATION_DRIFT')

def install_private_order_guard(m,root,source):
 original=m.private_runtimes
 def private_runtimes():
  path=root/'baseline.json'
  baseline_raw=path.read_bytes() if path.exists() else None
  expected=json.loads(baseline_raw)['private_runtimes'] if baseline_raw else BASE_PRIVATE_RUNTIMES
  actual={};proof={}
  for name in ('t24-private-api','t24-private-worker'):
   info=m.optional(name)
   if info is None:continue
   need(name in expected,'UNEXPECTED_PRIVATE_SERVICE')
   actual[name],proof[name]=equivalent_private_runtime(m,info,expected[name])
  need(set(actual)==set(expected),'PRIVATE_SERVICE_SET_DRIFT')
  if baseline_raw is None:return actual
  receipt=root/'private-runtime-mount-order-equivalence.json'
  if receipt.exists():
   saved=m.read(receipt)
   need(saved['source_sha']==source and saved['baseline_sha256']==H(baseline_raw) and saved['expected_private_runtimes']==expected and saved['raw_baseline_preserved'] is True,'PRIVATE_ORDER_EQUIVALENCE_RECEIPT_DRIFT')
  else:
   m.write(receipt,{'source_sha':source,'baseline_sha256':H(baseline_raw),'expected_private_runtimes':expected,'first_observed_equivalence':proof,'method':'exact_frozen_hash_by_complete_mount_array_permutation','raw_baseline_preserved':True})
  return actual
 m.private_runtimes=private_runtimes

def install_crm_mount_order_guard(m,root,source):
 original=m.runtime
 def runtime(info):
  candidate_path=root/'candidate.json'
  candidate_id=m.read(candidate_path)['id'] if candidate_path.exists() else None
  if info['Id'] not in (BASE_ID,candidate_id):return original(info)
  need(len(info['Mounts'])==3,'CRM_MOUNT_COUNT_DRIFT')
  normalized={**info,'Mounts':sorted(info['Mounts'],key=m.canonical)}
  value=original(normalized)
  if info['Id']==BASE_ID:
   # Canonicalize complete mount dictionaries against the frozen hash.
   # Preserve actual ID/image/StartedAt, so existing call-site guards still
   # reject identity/restart drift and allow the retained stopped original.
   need(value['config']==BASE_CONFIG_SHA,'CRM_CONFIGURATION_DRIFT')
   baseline_path=root/'baseline.json'
   if baseline_path.exists():
    baseline_raw=baseline_path.read_bytes();baseline=json.loads(baseline_raw)
    need(baseline['runtime']['id']==BASE_ID and baseline['runtime']['config']==BASE_CONFIG_SHA,'CRM_FROZEN_BASELINE_MISMATCH')
    receipt=root/'crm-runtime-mount-order-equivalence.json'
    if receipt.exists():
     saved=m.read(receipt);need(saved['source_sha']==source and saved['baseline_sha256']==H(baseline_raw) and saved['baseline_config_sha256']==BASE_CONFIG_SHA and saved['raw_baseline_preserved'] is True,'CRM_ORDER_EQUIVALENCE_RECEIPT_DRIFT')
    else:
     m.write(receipt,{'source_sha':source,'baseline_sha256':H(baseline_raw),'baseline_config_sha256':BASE_CONFIG_SHA,'observed_config_sha256':original(info)['config'],'canonical_config_sha256':value['config'],'method':'complete_three_mount_dictionary_sort_equals_frozen_hash','raw_baseline_preserved':True})
  return value
 m.runtime=runtime

def make_release(m,args):
 # Rebind only the isolated imported module's scope variables. The retained
 # helper and prior deployment state on disk are never modified.
 raw=(args.release/'manifest.json').read_bytes();need(H(raw)==args.manifest_sha256,'MANIFEST_HASH_MISMATCH')
 manifest=json.loads(raw);source=manifest['source_sha']
 need(bool(re.fullmatch('[a-f0-9]{40}',source)) and source not in (BASE_SOURCE,BASE_STATIC_SOURCE),'NEW_SOURCE_IDENTITY_REQUIRED')
 m.SOURCE=source;m.OLD=SCHEMA;m.NEW=SCHEMA;m.RUNTIME_PATHS=set(RUNTIME_PATHS)
 m.ERROR_LOG=args.release/'diagnostics-private.log'
 install_crm_mount_order_guard(m,args.release,source)
 install_private_order_guard(m,args.release,source)

 class Release(m.Release):
  def __init__(self):
   self.root=args.release;self.args=args;self.manifest=manifest;self.source=source
   need(self.root==Path('/opt/t24-crm/releases/crm-ui-refinement-'+source[:12]+'-20261111'),'EXACT_CRM_UI_RELEASE_NAMESPACE_REQUIRED')
   need(self.root.resolve()==self.root and self.root.is_dir() and self.root.stat().st_uid==0 and not self.root.stat().st_mode&0o077,'ROOT_PRIVATE_RELEASE_REQUIRED')
   need(set(manifest['backend_before'])==RUNTIME_PATHS,'EXACT_CRM_UI_BACKEND_SCOPE_REQUIRED')
   need(all(v.startswith('static/') or v.startswith('backend/') and v[8:] in RUNTIME_PATHS for v in manifest['files']),'EXACT_PAYLOAD_SCOPE_REQUIRED')
   need({'backend/'+p for p in RUNTIME_PATHS}|{'static/index.html','static/app-version.json'}<=set(manifest['files']),'COMPLETE_CRM_UI_PAYLOAD_REQUIRED')
   need(manifest.get('template_only') is not True,'REVIEWED_MANIFEST_REQUIRED')
   need(bool(re.fullmatch('[a-f0-9]{64}',manifest.get('payload_sha256',''))) and all(bool(re.fullmatch('[a-f0-9]{64}',value)) for value in manifest['files'].values()),'PINNED_PAYLOAD_HASHES_REQUIRED')
   need(manifest.get('baseline_source_sha')==BASE_SOURCE,'EXACT_BASELINE_SOURCE_REQUIRED')
   need(manifest.get('database_migration') is False and manifest.get('database_writes_by_release') is False,'NO_DATABASE_CHANGES_REQUIRED')
   need(bool(re.fullmatch('[a-f0-9]{12}',manifest['frontend_version'])) and manifest['frontend_version']!=BASE_FRONTEND_VERSION,'NEW_REVIEWED_FRONTEND_VERSION_REQUIRED')
   need(manifest['backend_before']==BASE_BACKEND_BEFORE,'PINNED_BACKEND_BASELINE_REQUIRED')
   self.public=Path('/var/www/t24-crm-public/crm-ui-refinement-'+source[:12]+'-20261111')
  def capture(self):
   receipt=m.read(PRIOR_ROOT/'deployed.json');old=m.inspect('t24-crm')
   need(receipt['stage']=='DEPLOYED' and receipt['source_sha']==BASE_SOURCE and receipt['schema_revision']==SCHEMA and receipt['frontend_version']==BASE_FRONTEND_VERSION and receipt['schema_unchanged'] is True and receipt['database_migration'] is False and receipt['database_writes_by_release'] is False,'PREVIOUS_DEPLOYED_RECEIPT_REQUIRED')
   expected={'id':BASE_ID,'image':BASE_IMAGE,'config':BASE_CONFIG_SHA,'started':BASE_STARTED}
   need(receipt['runtime']==expected and m.runtime(old)==expected and old['Id']==BASE_ID and old['Image']==BASE_IMAGE,'EXACT_LIVE_UI_BASE_REQUIRED')
   need(receipt['public_root']==BASE_PUBLIC_ROOT and str(m.public_root())==BASE_PUBLIC_ROOT and m.read(m.public_root()/'app-version.json')=={'version':BASE_FRONTEND_VERSION},'EXACT_PRIOR_PUBLIC_ROOT_REQUIRED')
   need([m.DB.stat().st_dev,m.DB.stat().st_ino]==BASE_DATABASE_IDENTITY,'DATABASE_FILE_IDENTITY_CHANGED')
   need(m.revision(m.DB)==SCHEMA and m.digest(m.schema(m.DB))==BASE_SCHEMA_SHA,'FROZEN_SCHEMA_DRIFT')
   inventory=m.inventory(old['Id'])
   need(len(inventory)==BASE_INVENTORY_COUNT and m.digest(inventory)==BASE_INVENTORY_SHA,'FROZEN_FULL_BACKEND_DRIFT')
   need(m.private_runtimes()==BASE_PRIVATE_RUNTIMES,'PRIVATE_SERVICES_CHANGED')
   return super().capture()
  def build(self,old):
   base='t24-crm:crm-ui-refinement-base-'+source[:12];tag='t24-crm:crm-ui-refinement-'+source[:12]
   existing=subprocess.run(['docker','image','inspect',base],capture_output=True)
   if existing.returncode==0:need(json.loads(existing.stdout)[0]['Id']==old['Image'],'BASE_TAG_COLLISION')
   else:m.run(['docker','image','tag',old['Image'],base],'BASE_TAG_FAILED')
   body='FROM '+base+'\n'+''.join('COPY backend/'+p+' /app/backend/'+p+'\n' for p in sorted(RUNTIME_PATHS))
   m.write(self.root/'Dockerfile',body.encode())
   m.run(['docker','build','--network=none','--pull=false','-t',tag,str(self.root)],'CANDIDATE_BUILD_FAILED',300)
   return json.loads(m.run(['docker','image','inspect',tag],'CANDIDATE_IMAGE_INSPECTION_FAILED'))[0]['Id']
  def create_candidate(self,old,image):
   config=copy.deepcopy(old['Config']);config['Image']=image;config['Hostname']=''
   config['Labels']={**(config.get('Labels') or {}),'t24.release.scope':'crm-ui-refinement','t24.release.source':source}
   config['HostConfig']=copy.deepcopy(old['HostConfig']);config['HostConfig']['AutoRemove']=False
   config['NetworkingConfig']={'EndpointsConfig':m.networks(old)}
   conn=m.DockerConnection('localhost',timeout=45)
   try:
    conn.request('POST','/containers/create?name=t24-crm',json.dumps(config),{'Content-Type':'application/json'});response=conn.getresponse();blob=response.read();need(response.status==201,'CANDIDATE_CREATE_FAILED');return json.loads(blob)['Id']
   finally:conn.close()
  def prepare(self):
   old=self.boundary();need(not(self.root/'prepared.json').exists(),'ALREADY_PREPARED')
   self.extract();m.write(self.root/'.dockerignore',b'*\n!backend/\n!backend/**\n!Dockerfile\n')
   image=self.build(old);need(self.image_inventory(image)==self.expected(),'CANDIDATE_WOULD_DROP_EXISTING_CODE')
   data=self.root/'probe-data';data.mkdir(mode=0o700);(self.root/'probe-logs').mkdir(mode=0o700)
   m.backup(m.DB,data/'crm_prod.db');before=m.snapshot(data/'crm_prod.db');shape=m.schema(data/'crm_prod.db')
   need(m.revision(data/'crm_prod.db')==SCHEMA,'OFFLINE_CURRENT_SCHEMA_REQUIRED')
   self.probe(data,image,'candidate')
   need(m.snapshot(data/'crm_prod.db')==before and m.schema(data/'crm_prod.db')==shape,'OFFLINE_DATA_OR_SCHEMA_CHANGED')
   self.stage_public();self.boundary()
   value={'stage':'PREPARED','source_sha':source,'manifest_sha256':args.manifest_sha256,'candidate_image':image,'original_image':old['Image'],'public_root':str(self.public),'schema_revision':SCHEMA,'offline_candidate_ready':True,'offline_ui_readmodels_verified_readonly':True,'offline_rows_and_schema_unchanged':True,'private_mount_order_equivalence_verified':True,'crm_mount_order_equivalence_verified':True,'database_migration':False}
   m.write(self.root/'prepared.json',value);return {**value,'prepared_sha256':H((self.root/'prepared.json').read_bytes())}
  def probe(self,data,image,label):
   super().probe(data,image,label)
   script="""import asyncio
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from routers.employees import query_employeess,EmployeesListResponse
from routers.finance_entry_drafts import list_drafts
async def verify():
 engine=create_async_engine('sqlite+aiosqlite:///file:/app/backend/data/crm_prod.db?mode=ro&uri=true')
 Session=async_sessionmaker(engine,expire_on_commit=False)
 try:
  async with Session() as db:
   actor=SimpleNamespace(id=1,name='Offline read-only acceptance',role='super_admin')
   employees=await query_employeess(query=None,sort='id',skip=0,limit=20,fields=None,_admin=actor,db=db)
   EmployeesListResponse.model_validate(employees)
   assert isinstance(employees['items'],list) and isinstance(employees['total'],int)
   for kind in (None,'manual_receipt','customer_expense','company_expense'):
    response=await list_drafts(status=None,q=None,kind=kind,start=None,end=None,skip=0,limit=2,user=actor,db=db)
    assert isinstance(response['items'],list) and isinstance(response['total'],int)
    assert response['skip']==0 and response['limit']==2 and len(response['items'])<=2
 finally:await engine.dispose()
asyncio.run(verify())
print('CRM_UI_READMODELS_VERIFIED_READONLY')
"""
   result=m.run(m.offline_args(self.root,data,image)+['python','-B','-c',script],'OFFLINE_UI_READMODEL_PROBE_FAILED',120)
   need(result.strip().endswith(b'CRM_UI_READMODELS_VERIFIED_READONLY'),'UI_READMODEL_RECEIPT_REQUIRED')
  def prepared(self):
   p=m.read(self.root/'prepared.json')
   pin=args.prepared_sha256
   if args.phase in ('activate','recover'):
    need(bool(pin and re.fullmatch('[a-f0-9]{64}',pin)) and H((self.root/'prepared.json').read_bytes())==pin,'REVIEWED_PREPARED_HASH_REQUIRED')
   elif args.phase=='status' and (self.root/'activation-started.json').exists():
    need(H((self.root/'prepared.json').read_bytes())==m.read(self.root/'activation-started.json')['prepared_sha256'],'ACTIVATED_PREPARED_HASH_CHANGED')
   need(p['stage']=='PREPARED' and p['source_sha']==source and p['manifest_sha256']==args.manifest_sha256 and p['schema_revision']==SCHEMA,'EXACT_PREPARED_SCOPE_REQUIRED')
   need(p['original_image']==BASE_IMAGE and bool(re.fullmatch('sha256:[a-f0-9]{64}',p['candidate_image'])) and p['public_root']==str(self.public),'EXACT_PREPARED_CANDIDATE_REQUIRED')
   need(p['offline_candidate_ready'] is True and p['offline_ui_readmodels_verified_readonly'] is True and p['offline_rows_and_schema_unchanged'] is True and p['database_migration'] is False,'NO_MIGRATION_REHEARSAL_REQUIRED')
   return p
  def expected_nginx(self):
   old=(self.root/'nginx-before.conf').read_bytes();oldroot=os.fsencode(self.baseline()['public_root']);need(old.count(oldroot)==1,'EXACT_NGINX_ROOT_REPLACEMENT_REQUIRED');return old.replace(oldroot,os.fsencode(self.public),1)
  def public_retry(self):
   # Nginx reload may return before the new worker begins accepting requests.
   # Retry only observation; never repeat activation or alter config on retries.
   last=None
   for attempt in range(8):
    try:
     super().public_check()
     url='https://t24-crm.com/app-version.json?crm-ui-refinement-check='+str(time.time_ns())
     value=json.loads(m.run(['curl','-q','--silent','--show-error','--fail','--http1.1','--max-time','5','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','-H','Cache-Control: no-cache',url],'FRESH_VERSION_READ_FAILED',8))
     need(value=={'version':manifest['frontend_version']},'FRESH_FRONTEND_VERSION_MISMATCH');return
    except RuntimeError as error:
     last=error
     if attempt<7:time.sleep(1)
   raise last
  def candidate_boundary(self):
   p=self.prepared();b=self.baseline();record=m.read(self.root/'candidate.json');old=m.inspect(b['runtime']['id']);live=m.inspect('t24-crm')
   need(not old['State']['Running'] and m.runtime(old)==b['runtime'],'EXACT_STOPPED_ORIGINAL_REQUIRED')
   need(old['Name']=='/'+record['retained'],'EXACT_RETAINED_ORIGINAL_REQUIRED')
   need(live['Id']==record['id'] and live['Image']==p['candidate_image'] and live['State']['Running'],'EXACT_LIVE_CANDIDATE_REQUIRED')
   labels=live['Config'].get('Labels') or {};need(labels.get('t24.release.scope')=='crm-ui-refinement' and labels.get('t24.release.source')==source,'CANDIDATE_LABELS_CHANGED')
   m.configuration_equal(live,old);need(m.inventory(live['Id'])==self.expected(),'LIVE_FULL_BACKEND_INVENTORY_CHANGED')
   need(m.revision(m.DB)==SCHEMA and m.schema(m.DB)==b['schema'],'UNCHANGED_SCHEMA_REQUIRED')
   need([m.DB.stat().st_dev,m.DB.stat().st_ino]==b['database_identity'],'DATABASE_FILE_IDENTITY_CHANGED')
   self.static_check();need(m.NGINX.read_bytes()==self.expected_nginx() and m.public_root()==self.public,'EXACT_NEW_STATIC_ROOT_REQUIRED')
   need(m.private_runtimes()==b['private_runtimes'],'PRIVATE_SERVICES_CHANGED')
   m.ready(live['Id']);return live
  def finish(self):
   live=self.candidate_boundary();self.public_retry()
   need(m.runtime(m.inspect('t24-crm'))==m.runtime(live),'CANDIDATE_CHANGED_DURING_CHECKS')
   result={'stage':'DEPLOYED','source_sha':source,'frontend_version':manifest['frontend_version'],'schema_revision':SCHEMA,'runtime':m.runtime(live),'public_root':str(self.public),'retained_original':m.read(self.root/'candidate.json')['retained'],'database_migration':False,'database_writes_by_release':False,'schema_unchanged':True,'environment_preserved':True,'authentication_and_unrelated_code_preserved':True,'private_services_preserved':True,'private_mount_order_equivalence_verified':True,'crm_mount_order_equivalence_verified':True}
   if (self.root/'deployed.json').exists():
    need(m.read(self.root/'deployed.json')==result,'EXISTING_DEPLOYED_RECEIPT_MISMATCH');return result
   m.write(self.root/'deployed.json',result);return result
  def activate(self):
   p=self.prepared();old=self.boundary();self.static_check()
   need(not(self.root/'activation-started.json').exists(),'ACTIVATION_ALREADY_STARTED_REVIEW_REQUIRED')
   m.write(self.root/'activation-started.json',{'original_id':old['Id'],'prepared_sha256':H((self.root/'prepared.json').read_bytes()),'database_migration':False})
   m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60)
   need(not m.inspect(old['Id'])['State']['Running'],'ORIGINAL_STILL_RUNNING')
   need(m.revision(m.DB)==SCHEMA and m.schema(m.DB)==self.baseline()['schema'],'SCHEMA_CHANGED_BEFORE_CANDIDATE')
   retained='t24-crm-before-crm-ui-refinement-'+source[:12];m.run(['docker','rename',old['Id'],retained],'RETAIN_ORIGINAL_FAILED')
   candidate=self.create_candidate(old,p['candidate_image']);m.write(self.root/'candidate.json',{'id':candidate,'retained':retained})
   m.run(['docker','start',candidate],'CANDIDATE_START_FAILED');m.ready(candidate)
   m.configuration_equal(m.inspect(candidate),old);need(m.inventory(candidate)==self.expected(),'LIVE_BACKEND_DRIFT')
   self.swap_nginx(self.expected_nginx());return self.finish()
  def status(self):
   if (self.root/'candidate.json').exists():return self.finish()
   return {'stage':'NOT_DEPLOYED','activation_started':(self.root/'activation-started.json').exists(),'runtime':m.runtime(m.inspect('t24-crm')),'schema_revision':m.revision(m.DB)}
  def recover(self):
   p=self.prepared();b=self.baseline();need((self.root/'activation-started.json').exists(),'ACTIVATION_REQUIRED')
   need(m.read(self.root/'activation-started.json')=={'original_id':b['runtime']['id'],'prepared_sha256':args.prepared_sha256,'database_migration':False},'ACTIVATION_SCOPE_DRIFT')
   original=m.inspect(b['runtime']['id']);need(original['Id']==BASE_ID and original['Image']==BASE_IMAGE and m.runtime(original)['config']==b['runtime']['config'],'ORIGINAL_CONFIG_CHANGED')
   need(m.revision(m.DB)==SCHEMA and m.schema(m.DB)==b['schema'],'CURRENT_UNCHANGED_SCHEMA_REQUIRED')
   need([m.DB.stat().st_dev,m.DB.stat().st_ino]==b['database_identity'],'DATABASE_FILE_IDENTITY_CHANGED')
   need(m.private_runtimes()==b['private_runtimes'],'PRIVATE_SERVICES_CHANGED')
   need(m.NGINX.read_bytes() in ((self.root/'nginx-before.conf').read_bytes(),self.expected_nginx()),'UNKNOWN_NGINX_NOT_REPLACED')
   current=m.optional('t24-crm')
   if current and current['Id']!=original['Id']:
    record=m.read(self.root/'candidate.json');need(current['Id']==record['id'] and current['Image']==p['candidate_image'],'UNKNOWN_CURRENT_CONTAINER')
    if current['State']['Running']:m.run(['docker','stop','--time','30',current['Id']],'CANDIDATE_STOP_FAILED',60)
    m.run(['docker','rename',current['Id'],'t24-crm-ui-refinement-failed-'+current['Id'][:12]],'RETAIN_FAILED_CANDIDATE')
   original=m.inspect(original['Id'])
   if original['Name']!='/t24-crm':m.run(['docker','rename',original['Id'],'t24-crm'],'ORIGINAL_NAME_RESTORE_FAILED')
   if not original['State']['Running']:m.run(['docker','start',original['Id']],'ORIGINAL_RESTART_FAILED')
   m.ready(original['Id']);need(m.inventory(original['Id'])==b['backend_inventory'],'ORIGINAL_BACKEND_CHANGED')
   self.swap_nginx((self.root/'nginx-before.conf').read_bytes())
   need(m.private_runtimes()==b['private_runtimes'],'PRIVATE_SERVICES_CHANGED')
   return {'stage':'RECOVERED','schema_revision':SCHEMA,'database_restored':False,'database_migrated':False,'runtime':m.runtime(m.inspect('t24-crm'))}
 return Release()

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('capture','prepare','activate','status','recover'),required=True);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--prepared-sha256');args=parser.parse_args()
 need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');os.umask(0o077)
 fd=os.open('/opt/t24-crm/releases/.crm-ui-refinement-release.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);m=load_helper();release=make_release(m,args);print(json.dumps(getattr(release,args.phase)(),sort_keys=True))
 except BaseException as error:
  reason=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
  print(json.dumps({'stage':'FAILED','phase':args.phase,'reason':reason}));raise SystemExit(1)
 finally:os.close(fd)
if __name__=='__main__':main()
