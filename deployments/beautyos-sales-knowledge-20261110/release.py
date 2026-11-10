"""No-migration BeautyOS knowledge runtime and static release.

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
PRIOR_ROOT=Path('/opt/t24-crm/releases/merchant-pool-filter-state-dcccb1227b91-20261110')
BASE_SOURCE='9878ca0654b82e7cd9150e7b8628c04aa3cc5eae'
BASE_STATIC_SOURCE='dcccb1227b917cdc29d96c5a1c96f5f8e5ca8031'
BASE_ID='f94582e507c00846088667307f356ec52a130578916a77a0218928ecf438ea12'
BASE_IMAGE='sha256:5679c46f3a78f852c1bf9544e4d1ab8c75acaa0e45df0fb529655644166a5518'
BASE_STARTED='2026-11-10T11:09:36.65962259Z'
SCHEMA='j65bc789b025'
BASE_FRONTEND_VERSION='a298ad75553b'
BASE_CONFIG_SHA='2358f89373d634572a826f62e4f8a1831c925789e982a6b2858e8d026985141b'
RUNTIME_PATHS={'routers/sales_knowledge.py','services/beautyos_knowledge_pack.py','services/sales_knowledge_profiles.py'} # FROZEN_RUNTIME_PATHS
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
  if not path.exists():return original()
  baseline_raw=path.read_bytes();expected=json.loads(baseline_raw)['private_runtimes'];actual={};proof={}
  for name in ('t24-private-api','t24-private-worker'):
   info=m.optional(name)
   if info is None:continue
   need(name in expected,'UNEXPECTED_PRIVATE_SERVICE')
   actual[name],proof[name]=equivalent_private_runtime(m,info,expected[name])
  need(set(actual)==set(expected),'PRIVATE_SERVICE_SET_DRIFT')
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
   need(self.root==Path('/opt/t24-crm/releases/beautyos-sales-knowledge-'+source[:12]+'-20261110'),'EXACT_KNOWLEDGE_RELEASE_NAMESPACE_REQUIRED')
   need(self.root.resolve()==self.root and self.root.is_dir() and self.root.stat().st_uid==0 and not self.root.stat().st_mode&0o077,'ROOT_PRIVATE_RELEASE_REQUIRED')
   need(set(manifest['backend_before'])==RUNTIME_PATHS,'EXACT_KNOWLEDGE_BACKEND_SCOPE_REQUIRED')
   need(all(v.startswith('static/') or v.startswith('backend/') and v[8:] in RUNTIME_PATHS for v in manifest['files']),'EXACT_PAYLOAD_SCOPE_REQUIRED')
   need({'backend/'+p for p in RUNTIME_PATHS}|{'static/index.html','static/app-version.json'}<=set(manifest['files']),'COMPLETE_KNOWLEDGE_PAYLOAD_REQUIRED')
   need(manifest.get('baseline_source_sha')==BASE_SOURCE,'EXACT_BASELINE_SOURCE_REQUIRED')
   need(manifest.get('database_migration') is False and manifest.get('database_writes_by_release') is False,'NO_DATABASE_CHANGES_REQUIRED')
   need(bool(re.fullmatch('[a-f0-9]{12}',manifest['frontend_version'])) and manifest['frontend_version']!=BASE_FRONTEND_VERSION,'NEW_REVIEWED_FRONTEND_VERSION_REQUIRED')
   need(all(value is None or bool(re.fullmatch('[a-f0-9]{64}',value)) for value in manifest['backend_before'].values()),'PINNED_BACKEND_BASELINE_REQUIRED')
   self.public=Path('/var/www/t24-crm-public/beautyos-sales-knowledge-'+source[:12]+'-20261110')
  def capture(self):
   receipt=m.read(PRIOR_ROOT/'deployed.json');old=m.inspect('t24-crm')
   need(receipt['stage']=='STATIC_DEPLOYED' and receipt['source_sha']==BASE_STATIC_SOURCE and receipt['backend_source_sha']==BASE_SOURCE and receipt['frontend_version']==BASE_FRONTEND_VERSION and receipt['schema_unchanged'] is True,'PREVIOUS_DEPLOYED_RECEIPT_REQUIRED')
   expected={'id':BASE_ID,'image':BASE_IMAGE,'config':BASE_CONFIG_SHA,'started':BASE_STARTED}
   need(receipt['runtime']==expected and m.runtime(old)==expected and old['Id']==BASE_ID and old['Image']==BASE_IMAGE,'EXACT_LIVE_TIMEZONE_BASE_REQUIRED')
   need(str(m.public_root())==receipt['public_root'] and m.read(m.public_root()/'app-version.json')=={'version':BASE_FRONTEND_VERSION},'EXACT_PRIOR_PUBLIC_ROOT_REQUIRED')
   return super().capture()
  def build(self,old):
   base='t24-crm:beautyos-sales-knowledge-base-'+source[:12];tag='t24-crm:beautyos-sales-knowledge-'+source[:12]
   existing=subprocess.run(['docker','image','inspect',base],capture_output=True)
   if existing.returncode==0:need(json.loads(existing.stdout)[0]['Id']==old['Image'],'BASE_TAG_COLLISION')
   else:m.run(['docker','image','tag',old['Image'],base],'BASE_TAG_FAILED')
   body='FROM '+base+'\n'+''.join('COPY backend/'+p+' /app/backend/'+p+'\n' for p in sorted(RUNTIME_PATHS))
   m.write(self.root/'Dockerfile',body.encode())
   m.run(['docker','build','--network=none','--pull=false','-t',tag,str(self.root)],'CANDIDATE_BUILD_FAILED',300)
   return json.loads(m.run(['docker','image','inspect',tag],'CANDIDATE_IMAGE_INSPECTION_FAILED'))[0]['Id']
  def create_candidate(self,old,image):
   config=copy.deepcopy(old['Config']);config['Image']=image;config['Hostname']=''
   config['Labels']={**(config.get('Labels') or {}),'t24.release.scope':'beautyos-sales-knowledge','t24.release.source':source}
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
   value={'stage':'PREPARED','source_sha':source,'manifest_sha256':args.manifest_sha256,'candidate_image':image,'original_image':old['Image'],'public_root':str(self.public),'schema_revision':SCHEMA,'offline_candidate_ready':True,'offline_knowledge_readmodels_verified_readonly':True,'offline_rows_and_schema_unchanged':True,'private_mount_order_equivalence_verified':True,'crm_mount_order_equivalence_verified':True,'database_migration':False}
   m.write(self.root/'prepared.json',value);return {**value,'prepared_sha256':H((self.root/'prepared.json').read_bytes())}
  def probe(self,data,image,label):
   super().probe(data,image,label)
   script="""import asyncio
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from routers.sales_knowledge import list_articles
from services.beautyos_knowledge_pack import BEAUTYOS_KNOWLEDGE_PACK,canonical_pack_hash
assert len(BEAUTYOS_KNOWLEDGE_PACK)==60
assert sum(bool(x.get('high_frequency')) for x in BEAUTYOS_KNOWLEDGE_PACK)==20
assert len({x['key'] for x in BEAUTYOS_KNOWLEDGE_PACK})==60
assert len(canonical_pack_hash())==64
assert all(x['product_scope']=='beautyos' and x['phone_answer'].strip() and x['standard_answer'].strip() and x['internal_notes'].strip() for x in BEAUTYOS_KNOWLEDGE_PACK)
assert all(x['availability'] in ('ready','requires_setup','pending_confirmation') for x in BEAUTYOS_KNOWLEDGE_PACK)
async def verify():
 engine=create_async_engine('sqlite+aiosqlite:///file:/app/backend/data/crm_prod.db?mode=ro&uri=true')
 Session=async_sessionmaker(engine,expire_on_commit=False)
 try:
  async with Session() as db:
   actor=SimpleNamespace(id=0,name='Offline read-only acceptance',role='super_admin')
   for scope in (None,'beautyos','general','managed_service'):
    response=await list_articles(query='',category=None,include_all=False,product_scope=scope,include_general=False,high_frequency=None,store_type=None,current_user=actor,db=db)
    assert isinstance(response['items'],list) and isinstance(response['categories'],list)
    if scope:assert all(item['product_scope']==scope for item in response['items'])
 finally:await engine.dispose()
asyncio.run(verify())
print('KNOWLEDGE_READMODELS_VERIFIED_READONLY')
"""
   result=m.run(m.offline_args(self.root,data,image)+['python','-B','-c',script],'OFFLINE_KNOWLEDGE_READMODEL_PROBE_FAILED',120)
   need(result.strip().endswith(b'KNOWLEDGE_READMODELS_VERIFIED_READONLY'),'KNOWLEDGE_READMODEL_RECEIPT_REQUIRED')
  def prepared(self):
   p=m.read(self.root/'prepared.json')
   pin=args.prepared_sha256
   if args.phase in ('activate','recover'):
    need(bool(pin and re.fullmatch('[a-f0-9]{64}',pin)) and H((self.root/'prepared.json').read_bytes())==pin,'REVIEWED_PREPARED_HASH_REQUIRED')
   elif args.phase=='status' and (self.root/'activation-started.json').exists():
    need(H((self.root/'prepared.json').read_bytes())==m.read(self.root/'activation-started.json')['prepared_sha256'],'ACTIVATED_PREPARED_HASH_CHANGED')
   need(p['stage']=='PREPARED' and p['source_sha']==source and p['manifest_sha256']==args.manifest_sha256 and p['schema_revision']==SCHEMA,'EXACT_PREPARED_SCOPE_REQUIRED')
   need(p['original_image']==BASE_IMAGE and bool(re.fullmatch('sha256:[a-f0-9]{64}',p['candidate_image'])) and p['public_root']==str(self.public),'EXACT_PREPARED_CANDIDATE_REQUIRED')
   need(p['offline_candidate_ready'] is True and p['offline_knowledge_readmodels_verified_readonly'] is True and p['offline_rows_and_schema_unchanged'] is True and p['database_migration'] is False,'NO_MIGRATION_REHEARSAL_REQUIRED')
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
     url='https://t24-crm.com/app-version.json?beautyos-sales-knowledge-check='+str(time.time_ns())
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
   labels=live['Config'].get('Labels') or {};need(labels.get('t24.release.scope')=='beautyos-sales-knowledge' and labels.get('t24.release.source')==source,'CANDIDATE_LABELS_CHANGED')
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
   retained='t24-crm-before-beautyos-sales-knowledge-'+source[:12];m.run(['docker','rename',old['Id'],retained],'RETAIN_ORIGINAL_FAILED')
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
    m.run(['docker','rename',current['Id'],'t24-beautyos-sales-knowledge-failed-'+current['Id'][:12]],'RETAIN_FAILED_CANDIDATE')
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
 fd=os.open('/opt/t24-crm/releases/.beautyos-sales-knowledge-release.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);m=load_helper();release=make_release(m,args);print(json.dumps(getattr(release,args.phase)(),sort_keys=True))
 except BaseException as error:
  reason=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
  print(json.dumps({'stage':'FAILED','phase':args.phase,'reason':reason}));raise SystemExit(1)
 finally:os.close(fd)
if __name__=='__main__':main()
