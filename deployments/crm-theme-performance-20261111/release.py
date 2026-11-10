"""No-migration CRM UI runtime and static release.

Manifest: source_sha, frontend_version, backend_before{frozen relative paths: sha or null},
files{backend/<relative> or static/<dist-relative>: sha}, payload_sha256.
No credentials are persisted; neither activation nor recovery writes the DB.
"""
import argparse, copy, fcntl, hashlib, itertools, json, os, re, socket, subprocess, time, types, urllib.parse, zlib
from pathlib import Path

HOST='iZj6c4cj7edgnhdimts4l7Z'
LEGACY_ROOT=Path('/opt/t24-crm/releases/ringcentral-team-18240e28774a-20261109')
LEGACY_SHA='922e0ed7d3fbde5d2985a5ea2a02b90b9622262f1969c8146535665133589f85'
LEGACY_SOURCE='18240e28774a1ce6043d06d1f7f913af2e9a369e'
PRIOR_ROOT=Path('/opt/t24-crm/releases/crm-ui-refinement-34917180e0d8-20261111')
PRIOR_STATIC_ROOT=Path('/opt/t24-crm/releases/crm-themes-00f851323f98-20261111')
BASE_GIT='7db737e0e692dd0325050897feaf6f66e8143770'
BASE_BACKEND_SOURCE='34917180e0d811d720e6bbba44355dfb69b6adee'
BASE_RUNTIME_FRONTEND_VERSION='80ed5befe7f2'
BASE_SOURCE='7db737e0e692dd0325050897feaf6f66e8143770'
BASE_STATIC_SOURCE='00f851323f98c50e484205e380cd4feb78938b1b'
BASE_ID='320d1b6356f47b583726af75dac9f0fc367c4567cf01b034a6fb4cc6de3a6ea8'
BASE_IMAGE='sha256:894a9c5619a3d6f9203714745ce38bde3ca68a14754ea1745f0b10e15b25d943'
BASE_STARTED='2026-11-10T16:40:13.147502643Z'
SCHEMA='j65bc789b025'
BASE_FRONTEND_VERSION='21a50c5ef5c5'
BASE_CONFIG_SHA='feb0f6f7911c81bcfd47001fefde79d2b083b92f794ee6dd253180e047e7321c'
BASE_PUBLIC_ROOT='/var/www/t24-crm-public/crm-themes-00f851323f98-20261111'
BASE_SCHEMA_SHA='ca15d3cb51c5cb99a68865c6a0c0d5aadd32ee1c5a5cfbc70dee7bfbbf4baa6a'
BASE_DATABASE_IDENTITY=[64515, 262854]
BASE_INVENTORY_SHA='12a5fca6e20c56b08e3759cc0573138d6d2483def69ce6b6dda1a1f987bbdfef'
BASE_INVENTORY_COUNT=443
BASE_PRIVATE_RUNTIMES={'t24-private-api': {'config': '04160cf058e2e8b47b719e731a813af4bdb12144850680b50ed2ec00dd5491e2', 'id': 'f8644b043b7f9d8e57190a8e7f411291ccb0814871428891e00e77cb74974d6b', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'started': '2026-10-11T23:58:43.773320701Z'}, 't24-private-worker': {'config': '7dba014c965ef1c4618a0a33546a5089edb27095a3c06ce05ab06d01a8ceb061', 'id': '7f7930d5ea468765c404a163ecb0cb4d2935b793ad4435efc8ca8aa782772cab', 'image': 'sha256:a82266de5af9ff84a957854f8dc7971415718278f0cf7342d037dde74dd518c5', 'started': '2026-10-11T23:58:58.055948866Z'}}
BASE_BACKEND_BEFORE={'routers/sales_leads.py': '18f5a24a63087409af94c899bcbc4c82baf23bdcbca9745d81f9f7937bac14f6', 'services/sales_contact_protection.py': 'b7da07ee5de0ae3d078c680c5ddd96d995fad7e49e91d06d5d66ab5e7400f922'}
RUNTIME_PATHS=set(BASE_BACKEND_BEFORE) # FROZEN_RUNTIME_PATHS
PREFLIGHT_CODE_SHA='72385676fc2c91ecd68749a79acab89895b58e0dcce9045978e3f41cdc9a4028'
ROOT_REVIEWED_ASSET_COMPRESSION_PATCH=('gzip on;', 'gzip_types text/css application/javascript text/javascript;', 'gzip_vary on;', 'gzip_proxied any;', 'gzip_comp_level 5;', 'gzip_min_length 1024;')
BASE_ASSET_LOCATION_LINES=('location ^~ /assets/ {', 'try_files $uri =404;', 'add_header Cache-Control "public, max-age=31536000, immutable";', 'add_header X-Frame-Options "SAMEORIGIN" always;', 'add_header Content-Security-Policy "default-src \'self\'; script-src \'self\'; style-src \'self\' \'unsafe-inline\'; img-src \'self\' data: https:; media-src \'self\' blob:; font-src \'self\' data:; connect-src \'self\' https: wss:; frame-ancestors \'self\'; base-uri \'self\'; form-action \'self\'" always;', 'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;', 'add_header Referrer-Policy "strict-origin-when-cross-origin" always;', 'add_header Permissions-Policy "camera=(), geolocation=(), microphone=(self)" always;', 'add_header X-Content-Type-Options "nosniff" always;', '}')
NGINX_MAIN=Path('/etc/nginx/nginx.conf')
NGINX_SITES=Path('/etc/nginx/sites-enabled')
BASE_CSP_SHA='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
H=lambda body:hashlib.sha256(body).hexdigest()

def need(ok,code):
 if not ok:raise RuntimeError(code)

def reviewed_asset_compression(body):
 matches=list(re.finditer(rb'(?m)^([ \t]*)location[ \t]+\^~[ \t]+/assets/[ \t]*\{[ \t]*\r?\n',body))
 need(len(matches)==1,'EXACT_SINGLE_ASSET_LOCATION_REQUIRED')
 header=matches[0];end=re.search(rb'(?m)^[ \t]*\}[ \t]*(?:\r?\n|$)',body[header.end():])
 need(end is not None,'CLOSED_ASSET_LOCATION_REQUIRED')
 block=body[header.start():header.end()+end.end()]
 need(not re.search(rb'(?m)^\s*gzip(?:_[a-z_]+)?\s',block),'EXISTING_ASSET_GZIP_REJECTED')
 need(tuple(line.strip().decode('utf-8') for line in block.splitlines() if line.strip())==BASE_ASSET_LOCATION_LINES,'EXACT_REVIEWED_ASSET_BLOCK_REQUIRED')
 newline=b'\r\n' if header.group().endswith(b'\r\n') else b'\n'
 insertion=b''.join(header.group(1)+b'    '+line.encode()+newline for line in ROOT_REVIEWED_ASSET_COMPRESSION_PATCH)
 return body[:header.end()]+insertion+body[header.end():]

def verified_gzip(body,expected_sha,expected_size):
 need(0<len(body)<=expected_size+65536 and 0<expected_size<20*1024**2,'BOUNDED_GZIP_ASSET_REQUIRED')
 decoder=zlib.decompressobj(31)
 try:decoded=decoder.decompress(body,expected_size+1)
 except zlib.error:raise RuntimeError('VALID_GZIP_ASSET_REQUIRED')
 need(decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data and len(decoded)==expected_size and H(decoded)==expected_sha,'EXACT_DECOMPRESSED_STATIC_HASH_REQUIRED')
 return {'identity_bytes':expected_size,'gzip_bytes':len(body),'sha256':expected_sha,'content_encoding':'gzip','decoded_payload_verified':True}

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
 need(bool(re.fullmatch('[a-f0-9]{40}',source)) and source not in (BASE_SOURCE,BASE_BACKEND_SOURCE,BASE_STATIC_SOURCE),'NEW_SOURCE_IDENTITY_REQUIRED')
 m.SOURCE=source;m.OLD=SCHEMA;m.NEW=SCHEMA;m.RUNTIME_PATHS=set(RUNTIME_PATHS)
 m.ERROR_LOG=args.release/'diagnostics-private.log'
 install_crm_mount_order_guard(m,args.release,source)
 install_private_order_guard(m,args.release,source)

 class Release(m.Release):
  def __init__(self):
   self.root=args.release;self.args=args;self.manifest=manifest;self.source=source
   need(self.root==Path('/opt/t24-crm/releases/crm-theme-performance-'+source[:12]+'-20261111'),'EXACT_CRM_THEME_PERFORMANCE_RELEASE_NAMESPACE_REQUIRED')
   need(self.root.resolve()==self.root and self.root.is_dir() and self.root.stat().st_uid==0 and not self.root.stat().st_mode&0o077,'ROOT_PRIVATE_RELEASE_REQUIRED')
   need(set(manifest['backend_before'])==RUNTIME_PATHS,'EXACT_CRM_THEME_PERFORMANCE_BACKEND_SCOPE_REQUIRED')
   need(all(v.startswith('static/') or v.startswith('backend/') and v[8:] in RUNTIME_PATHS for v in manifest['files']),'EXACT_PAYLOAD_SCOPE_REQUIRED')
   need({'backend/'+p for p in RUNTIME_PATHS}|{'static/index.html','static/app-version.json'}<=set(manifest['files']),'COMPLETE_CRM_THEME_PERFORMANCE_PAYLOAD_REQUIRED')
   need(manifest.get('template_only') is not True,'REVIEWED_MANIFEST_REQUIRED')
   need(bool(re.fullmatch('[a-f0-9]{64}',manifest.get('payload_sha256',''))) and all(bool(re.fullmatch('[a-f0-9]{64}',value)) for value in manifest['files'].values()),'PINNED_PAYLOAD_HASHES_REQUIRED')
   need(manifest.get('baseline_source_sha')==BASE_GIT and manifest.get('baseline_git_commit')==BASE_GIT,'EXACT_BASELINE_SOURCE_REQUIRED')
   need(manifest.get('baseline_backend_source_sha')==BASE_BACKEND_SOURCE and manifest.get('baseline_static_source_sha')==BASE_STATIC_SOURCE,'SEPARATE_RUNTIME_STATIC_BASELINES_REQUIRED')
   need(manifest.get('database_migration') is False and manifest.get('database_writes_by_release') is False,'NO_DATABASE_CHANGES_REQUIRED')
   need(bool(re.fullmatch('[a-f0-9]{12}',manifest['frontend_version'])) and manifest['frontend_version']!=BASE_FRONTEND_VERSION,'NEW_REVIEWED_FRONTEND_VERSION_REQUIRED')
   need(manifest['backend_before']==BASE_BACKEND_BEFORE,'PINNED_BACKEND_BASELINE_REQUIRED')
   self.public=Path('/var/www/t24-crm-public/crm-theme-performance-'+source[:12]+'-20261111')
  def current_preflight(self):
   path=self.root/'preflight.py'
   need(path.resolve()==path and path.is_file() and path.stat().st_uid==0 and not path.stat().st_mode&0o077,'ROOT_PRIVATE_PREFLIGHT_REQUIRED')
   body=path.read_bytes();need(H(body)==PREFLIGHT_CODE_SHA,'FROZEN_PREFLIGHT_CODE_REQUIRED')
   pf=types.ModuleType('reviewed_current_boundary');pf.__file__=str(path);exec(compile(body,str(path),'exec'),pf.__dict__)
   value=pf.capture()
   need(all(value.get(key)==expected for key,expected in pf.FROZEN_BOUNDARY.items()),'FROZEN_BOUNDARY_CHANGED')
   return value
  def capture(self):
   self.current_preflight()
   receipt=m.read(PRIOR_ROOT/'deployed.json');static_receipt=m.read(PRIOR_STATIC_ROOT/'deployed.json');old=m.inspect('t24-crm')
   need(receipt['stage']=='DEPLOYED' and receipt['source_sha']==BASE_BACKEND_SOURCE and receipt['schema_revision']==SCHEMA and receipt['frontend_version']==BASE_RUNTIME_FRONTEND_VERSION and receipt['schema_unchanged'] is True and receipt['database_migration'] is False and receipt['database_writes_by_release'] is False,'PREVIOUS_RUNTIME_DEPLOYED_RECEIPT_REQUIRED')
   need(static_receipt['stage']=='CRM_THEMES_STATIC_DEPLOYED' and static_receipt['source_sha']==BASE_STATIC_SOURCE and static_receipt['frontend_version']==BASE_FRONTEND_VERSION and static_receipt['static_only'] is True and static_receipt['runtime_restarts'] is False and static_receipt['database_writes'] is False,'PREVIOUS_STATIC_DEPLOYED_RECEIPT_REQUIRED')
   expected={'id':BASE_ID,'image':BASE_IMAGE,'config':BASE_CONFIG_SHA,'started':BASE_STARTED}
   need(receipt['runtime']==expected and m.runtime(old)==expected and old['Id']==BASE_ID and old['Image']==BASE_IMAGE,'EXACT_LIVE_RUNTIME_BASE_REQUIRED')
   need(static_receipt['public_root']==BASE_PUBLIC_ROOT and str(m.public_root())==BASE_PUBLIC_ROOT and m.read(m.public_root()/'app-version.json')=={'version':BASE_FRONTEND_VERSION},'EXACT_PRIOR_PUBLIC_ROOT_REQUIRED')
   need([m.DB.stat().st_dev,m.DB.stat().st_ino]==BASE_DATABASE_IDENTITY,'DATABASE_FILE_IDENTITY_CHANGED')
   need(m.revision(m.DB)==SCHEMA and m.digest(m.schema(m.DB))==BASE_SCHEMA_SHA,'FROZEN_SCHEMA_DRIFT')
   inventory=m.inventory(old['Id'])
   need(len(inventory)==BASE_INVENTORY_COUNT and m.digest(inventory)==BASE_INVENTORY_SHA,'FROZEN_FULL_BACKEND_DRIFT')
   need(m.private_runtimes()==BASE_PRIVATE_RUNTIMES,'PRIVATE_SERVICES_CHANGED')
   return super().capture()
  def boundary(self):
   self.current_preflight()
   return super().boundary()
  def build(self,old):
   base='t24-crm:crm-theme-performance-base-'+source[:12];tag='t24-crm:crm-theme-performance-'+source[:12]
   existing=subprocess.run(['docker','image','inspect',base],capture_output=True)
   if existing.returncode==0:need(json.loads(existing.stdout)[0]['Id']==old['Image'],'BASE_TAG_COLLISION')
   else:m.run(['docker','image','tag',old['Image'],base],'BASE_TAG_FAILED')
   body='FROM '+base+'\n'+''.join('COPY backend/'+p+' /app/backend/'+p+'\n' for p in sorted(RUNTIME_PATHS))
   m.write(self.root/'Dockerfile',body.encode())
   m.run(['docker','build','--network=none','--pull=false','-t',tag,str(self.root)],'CANDIDATE_BUILD_FAILED',300)
   return json.loads(m.run(['docker','image','inspect',tag],'CANDIDATE_IMAGE_INSPECTION_FAILED'))[0]['Id']
  def create_candidate(self,old,image):
   config=copy.deepcopy(old['Config']);config['Image']=image;config['Hostname']=''
   config['Labels']={**(config.get('Labels') or {}),'t24.release.scope':'crm-theme-performance','t24.release.source':source}
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
   self.stage_public();self.test_nginx_candidate();self.boundary()
   value={'stage':'PREPARED','source_sha':source,'manifest_sha256':args.manifest_sha256,'candidate_image':image,'original_image':old['Image'],'public_root':str(self.public),'schema_revision':SCHEMA,'nginx_candidate_verified':True,'offline_candidate_ready':True,'offline_ui_readmodels_verified_readonly':True,'offline_rows_and_schema_unchanged':True,'private_mount_order_equivalence_verified':True,'crm_mount_order_equivalence_verified':True,'database_migration':False}
   m.write(self.root/'prepared.json',value);return {**value,'prepared_sha256':H((self.root/'prepared.json').read_bytes())}
  def probe(self,data,image,label):
   super().probe(data,image,label)
   script="""import asyncio
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from routers.sales_leads import list_sales_leads,SalesLeadListResponse,list_sales_assignees,get_daily_call_workbench
from services.sales_contact_protection import contact_protection_summaries,contact_protection_summary
async def verify():
 engine=create_async_engine('sqlite+aiosqlite:///file:/app/backend/data/crm_prod.db?mode=ro&uri=true')
 Session=async_sessionmaker(engine,expire_on_commit=False,autoflush=False)
 try:
  async with Session() as db:
   actor=SimpleNamespace(id=1,name='Offline read-only acceptance',role='super_admin')
   response=await list_sales_leads(search=None,lead_status=None,contact_rule=None,due_range=None,skip=0,limit=2,current_user=actor,db=db)
   SalesLeadListResponse.model_validate(response)
   assert isinstance(response['items'],list) and isinstance(response['total'],int)
   summaries=await contact_protection_summaries(db,response['items'])
   for lead in response['items']:
    assert summaries[lead.id]==await contact_protection_summary(db,lead)
   sales=await list_sales_assignees(current_user=actor,db=db)
   if sales:
    queue=await get_daily_call_workbench(sales_employee_id=sales[0].id,target_date=None,current_user=actor,db=db)
    assert isinstance(queue['items'],list) and queue['salesperson']['id']==sales[0].id
 finally:await engine.dispose()
asyncio.run(verify())
print('CRM_THEME_PERFORMANCE_READMODELS_VERIFIED_READONLY')
"""
   result=m.run(m.offline_args(self.root,data,image)+['python','-B','-c',script],'OFFLINE_SALES_READMODEL_PROBE_FAILED',120)
   need(result.strip().endswith(b'CRM_THEME_PERFORMANCE_READMODELS_VERIFIED_READONLY'),'SALES_READMODEL_RECEIPT_REQUIRED')

  def prepared(self):
   p=m.read(self.root/'prepared.json')
   pin=args.prepared_sha256
   if args.phase in ('activate','recover'):
    need(bool(pin and re.fullmatch('[a-f0-9]{64}',pin)) and H((self.root/'prepared.json').read_bytes())==pin,'REVIEWED_PREPARED_HASH_REQUIRED')
   elif args.phase=='status' and (self.root/'activation-started.json').exists():
    need(H((self.root/'prepared.json').read_bytes())==m.read(self.root/'activation-started.json')['prepared_sha256'],'ACTIVATED_PREPARED_HASH_CHANGED')
   need(p['stage']=='PREPARED' and p['source_sha']==source and p['manifest_sha256']==args.manifest_sha256 and p['schema_revision']==SCHEMA,'EXACT_PREPARED_SCOPE_REQUIRED')
   need(p['original_image']==BASE_IMAGE and bool(re.fullmatch('sha256:[a-f0-9]{64}',p['candidate_image'])) and p['public_root']==str(self.public),'EXACT_PREPARED_CANDIDATE_REQUIRED')
   need(p.get('nginx_candidate_verified') is True and p['offline_candidate_ready'] is True and p['offline_ui_readmodels_verified_readonly'] is True and p['offline_rows_and_schema_unchanged'] is True and p['database_migration'] is False,'NO_MIGRATION_REHEARSAL_REQUIRED')
   return p
  def expected_nginx(self):
   old=(self.root/'nginx-before.conf').read_bytes();oldroot=os.fsencode(self.baseline()['public_root']);need(old.count(oldroot)==1,'EXACT_NGINX_ROOT_REPLACEMENT_REQUIRED')
   updated=old.replace(oldroot,os.fsencode(self.public),1)
   return reviewed_asset_compression(updated)
  def test_nginx_candidate(self):
   # Test a complete candidate main config with only the site include redirected.
   # The live main/site files and running Nginx workers are never edited here.
   folder=self.root/'nginx-precheck-sites';folder.mkdir(mode=0o700)
   current=m.NGINX.resolve();found=0
   for path in sorted(NGINX_SITES.iterdir()):
    need(path.is_file() and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*',path.name),'REGULAR_NGINX_SITE_REQUIRED')
    target=folder/path.name
    if path.resolve()==current:
     found+=1;m.write(target,self.expected_nginx())
    else:target.symlink_to(path.resolve())
   need(found==1,'EXACT_ACTIVE_SITE_FOR_PRECHECK_REQUIRED')
   body=NGINX_MAIN.read_bytes();pattern=rb'(?m)^([ \t]*)include[ \t]+/etc/nginx/sites-enabled/\*;[ \t]*$'
   matches=list(re.finditer(pattern,body));need(len(matches)==1,'EXACT_MAIN_SITES_INCLUDE_REQUIRED')
   match=matches[0];candidate=body[:match.start()]+match.group(1)+b'include '+os.fsencode(folder)+b'/*;'+body[match.end():]
   path=self.root/'nginx-precheck-main.conf';m.write(path,candidate)
   m.run(['nginx','-t','-c',str(path)],'CANDIDATE_NGINX_TEST_FAILED',30)
  def public_gzip_check(self):
   candidates=[(name[7:],self.public/name[7:]) for name in manifest['files'] if name.startswith('static/assets/') and name.endswith(('.js','.css'))]
   chosen=[]
   for suffix in ('.js','.css'):
    eligible=[item for item in candidates if item[0].endswith(suffix) and item[1].stat().st_size>=1024]
    need(bool(eligible),'CURRENT_JS_AND_CSS_COMPRESSION_PROBES_REQUIRED')
    chosen.append(max(eligible,key=lambda item:item[1].stat().st_size))
   proof=[]
   for relative,path in chosen:
    expected=manifest['files']['static/'+relative];size=path.stat().st_size
    headers=self.root/('gzip-probe-'+path.suffix[1:]+'.headers')
    url='https://t24-crm.com/'+urllib.parse.quote(relative,safe='/._-')+'?crm-theme-performance-gzip='+str(time.time_ns())
    body=m.run(['curl','-q','--silent','--show-error','--fail','--http1.1','--max-time','8','--max-filesize',str(20*1024**2),'--max-redirs','0','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','-H','Accept-Encoding: gzip','-H','Cache-Control: no-cache','-D',str(headers),url],'PUBLIC_GZIP_ASSET_READ_FAILED',12)
    raw=headers.read_bytes();need(len(raw)<16384,'BOUNDED_GZIP_HEADERS_REQUIRED')
    rows=raw.decode('iso-8859-1').splitlines();need(rows and re.fullmatch(r'HTTP/1[.]1 200(?: .*)?',rows[0]),'PUBLIC_GZIP_200_REQUIRED')
    values={}
    for row in rows[1:]:
     if ':' in row:
      key,value=row.split(':',1);values.setdefault(key.lower(),[]).append(value.strip())
    need(values.get('content-encoding')==['gzip'],'PUBLIC_ASSET_GZIP_REQUIRED')
    need(any('accept-encoding' in value.lower() for value in values.get('vary',[])),'ACCEPT_ENCODING_VARY_REQUIRED')
    need(values.get('cache-control')==['public, max-age=31536000, immutable'],'IMMUTABLE_ASSET_CACHE_PRESERVED_REQUIRED')
    csp=values.get('content-security-policy',[]);need(len(csp)==1 and H(csp[0].encode())==BASE_CSP_SHA,'PUBLIC_ASSET_CSP_PRESERVED_REQUIRED')
    proof.append({'path':relative,**verified_gzip(body,expected,size)})
   return proof
  def public_retry(self):
   # Nginx reload may return before the new worker begins accepting requests.
   # Retry only observation; never repeat activation or alter config on retries.
   last=None
   for attempt in range(8):
    try:
     super().public_check()
     url='https://t24-crm.com/app-version.json?crm-theme-performance-check='+str(time.time_ns())
     value=json.loads(m.run(['curl','-q','--silent','--show-error','--fail','--http1.1','--max-time','5','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','-H','Cache-Control: no-cache',url],'FRESH_VERSION_READ_FAILED',8))
     need(value=={'version':manifest['frontend_version']},'FRESH_FRONTEND_VERSION_MISMATCH');return self.public_gzip_check()
    except RuntimeError as error:
     last=error
     if attempt<7:time.sleep(1)
   raise last
  def candidate_boundary(self):
   p=self.prepared();b=self.baseline();record=m.read(self.root/'candidate.json');old=m.inspect(b['runtime']['id']);live=m.inspect('t24-crm')
   need(not old['State']['Running'] and m.runtime(old)==b['runtime'],'EXACT_STOPPED_ORIGINAL_REQUIRED')
   need(old['Name']=='/'+record['retained'],'EXACT_RETAINED_ORIGINAL_REQUIRED')
   need(live['Id']==record['id'] and live['Image']==p['candidate_image'] and live['State']['Running'],'EXACT_LIVE_CANDIDATE_REQUIRED')
   labels=live['Config'].get('Labels') or {};need(labels.get('t24.release.scope')=='crm-theme-performance' and labels.get('t24.release.source')==source,'CANDIDATE_LABELS_CHANGED')
   m.configuration_equal(live,old);need(m.inventory(live['Id'])==self.expected(),'LIVE_FULL_BACKEND_INVENTORY_CHANGED')
   need(m.revision(m.DB)==SCHEMA and m.schema(m.DB)==b['schema'],'UNCHANGED_SCHEMA_REQUIRED')
   need([m.DB.stat().st_dev,m.DB.stat().st_ino]==b['database_identity'],'DATABASE_FILE_IDENTITY_CHANGED')
   self.static_check();need(m.NGINX.read_bytes()==self.expected_nginx() and m.public_root()==self.public,'EXACT_NEW_STATIC_ROOT_REQUIRED')
   need(m.private_runtimes()==b['private_runtimes'],'PRIVATE_SERVICES_CHANGED')
   m.ready(live['Id']);return live
  def finish(self):
   live=self.candidate_boundary();gzip_proof=self.public_retry()
   need(m.runtime(m.inspect('t24-crm'))==m.runtime(live),'CANDIDATE_CHANGED_DURING_CHECKS')
   result={'stage':'DEPLOYED','source_sha':source,'frontend_version':manifest['frontend_version'],'schema_revision':SCHEMA,'runtime':m.runtime(live),'public_root':str(self.public),'retained_original':m.read(self.root/'candidate.json')['retained'],'gzip_verified_public_assets':gzip_proof,'asset_compression_scope':'public_assets_only','database_migration':False,'database_writes_by_release':False,'schema_unchanged':True,'environment_preserved':True,'authentication_and_unrelated_code_preserved':True,'private_services_preserved':True,'private_mount_order_equivalence_verified':True,'crm_mount_order_equivalence_verified':True}
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
   retained='t24-crm-before-crm-theme-performance-'+source[:12];m.run(['docker','rename',old['Id'],retained],'RETAIN_ORIGINAL_FAILED')
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
    m.run(['docker','rename',current['Id'],'t24-crm-theme-performance-failed-'+current['Id'][:12]],'RETAIN_FAILED_CANDIDATE')
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
 fd=os.open('/opt/t24-crm/releases/.crm-theme-performance-release.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);m=load_helper();release=make_release(m,args);print(json.dumps(getattr(release,args.phase)(),sort_keys=True))
 except BaseException as error:
  reason=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
  print(json.dumps({'stage':'FAILED','phase':args.phase,'reason':reason}));raise SystemExit(1)
 finally:os.close(fd)
if __name__=='__main__':main()
