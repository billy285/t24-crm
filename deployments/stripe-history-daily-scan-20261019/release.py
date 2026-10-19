#!/usr/bin/env python3
"""One additive daily-scan table and controlled app/public switch; no ledger or credential changes."""
import argparse,ast,copy,fcntl,hashlib,io,json,os,re,socket,sqlite3,stat,subprocess,sys,tarfile,time
from pathlib import Path

SOURCE='285c3377e6d04765116ef553a7692933ad9815b0'
BASELINE='fd1ae7239330a418e6d2df44b0fb7fcb632d2567'
BASELINE_APPLICATION_SOURCE='f055a21a6dfa44539e6acb1bd10405a318305934'
BASELINE_FRONTEND='8ca5d81df65f'
FRONTEND_VERSION='0f8ad5c23245'
BASE_IMAGE='sha256:8c0c86583242e00d5f2d5e0c22fd07b675b6e3370a11498b417e1e7274f81bc7'
OLD_ID='4b06b6bcfdd676d6d01ea9f80187b99e90ab8fd43a6c14c84ae25edefe5243d1'
OLD_CONFIG='ee5314018fa3d4d78710f355cfe1878e62f9ee5028211bd5edea366379ec0e77'
REVISION='e2b6c0f8a345'
HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE='stripe-history-daily-scan'
BACKEND={'alembic/versions/e2b6c0f8a345_stripe_history_daily_scan.py', 'main.py', 'models/stripe_history_daily_scan.py', 'services/stripe_history_daily_scan.py', 'routers/stripe_history_reconciliation.py'}
FRONTEND={'components/StripeHistoryReminders.tsx', 'components/stripe-history-reminders.css', 'components/ServiceFollowThrough.tsx', 'lib/stripe-history-reminders.ts', 'components/StripeHistoryReconciliation.tsx'}
TESTS={'app/frontend/tests/stripe-history-reminders.spec.ts', 'app/frontend/tests/stripe-history-reminders.unit.test.mjs', 'app/backend/tests/test_stripe_history_daily_scan.py'}
LIVE_PREFLIGHT_SHA='bcb69a8c4b69d1f8a3b6ed8fe64b099556b64e817d788334ac5b0a42e175992b'
BASE_BACKEND_SHA='302a8b31ed214a495cad696a5c666efafa6163563c850866be21cbe7cec497d1'
SCHEMA_SHA='2f36b725fc2f1a64467f735d0e29047b3406da22e9e31c893e18d42f7796525b'
STATIC_SHA='e1f21a3e01aac4462938d415e8694eb25168f0fde93d4357c9de8321c1d16e50'
BUSINESS_IDENTITY=(64515,262854)
PUBLIC=Path('/var/www/t24-crm-public/stripe-history-charge-id-compat-f055a21a6dfa-20261018')
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA='f88742e72de782dde4d6661d8279da68d9e0e96f9989f7f3248428294870f057'
BUSINESS=Path('/opt/t24-crm/app/data/crm_prod.db')
RETAINED=Path('/opt/t24-crm/releases/sales-dossier-3aaae9f6b13a-20261016/release.py')
RETAINED_SHA='2e1d59d25010cb2141d6c6e25bcb4eaf6bc6cfdfb1015a60d3f8ac6bca5644fe'
PRESERVED={'original_schema_objects': True, 'original_business_rows_during_migration_and_validation': True, 'company_finance_formulas': True, 'close_conditions': True, 'commission_attribution': True, 'customer_invitation_rules': True, 'private_workspace': True, 'environment': True, 'network': True, 'mounts': True, 'original_static_files': True, 'original_frontend_sources': True, 'nginx_all_nonroot_bytes': True, 'no_provider_writes': True, 'no_automatic_formal_posting': True}
SECRET_HOST=Path('/opt/t24-crm/secrets/stripe-history-readonly.key')
SECRET_TARGET='/run/secrets/t24_crm_stripe_history_readonly'
CREDENTIAL_PROOF=Path('/opt/t24-crm/releases/stripe-history-readonly-credential-proof-20261018.json')
CREDENTIAL_EXPECTED={'credential_content_read': False, 'ctime_ns': 1792289178973788626, 'device': 64515, 'inode': 279537, 'mount': {'read_only': True, 'source': '/opt/t24-crm/secrets/stripe-history-readonly.key', 'target': '/run/secrets/t24_crm_stripe_history_readonly'}, 'mtime_ns': 1792289178973788626, 'provisioning_proof_sha256': 'f9b35302a397cff5c29dad648d608fba24df647d0094b5c01dcdab6e2c7e9253', 'size': 108}

OLD_REVISION='d1a5b9e7f234'
NEW_REVISION=REVISION
NEW_TABLE='stripe_history_scan_states'
MIGRATION='alembic/versions/e2b6c0f8a345_stripe_history_daily_scan.py'
NEW_SCHEMA={'binding_id': ('INTEGER', 1, None, 1), 'scan_for': ('VARCHAR(10)', 0, None, 0), 'completed_for': ('VARCHAR(10)', 0, None, 0), 'target_end': ('DATETIME', 0, None, 0), 'range_start': ('DATETIME', 0, None, 0), 'range_end': ('DATETIME', 0, None, 0), 'cursor': ('VARCHAR(255)', 0, None, 0), 'covered_through': ('DATETIME', 0, None, 0), 'lease_token': ('VARCHAR(64)', 0, None, 0), 'lease_until': ('DATETIME', 0, None, 0), 'retry_at': ('DATETIME', 0, None, 0), 'failure_count': ('INTEGER', 1, None, 0), 'last_error_code': ('VARCHAR(40)', 0, None, 0), 'last_attempt_at': ('DATETIME', 0, None, 0), 'last_completed_at': ('DATETIME', 0, None, 0), 'page_count': ('INTEGER', 1, None, 0), 'invoice_count': ('INTEGER', 1, None, 0), 'discovered_count': ('INTEGER', 1, None, 0)}
NEW_FOREIGN_KEYS=[(0, 0, 'stripe_history_bindings', 'binding_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE')]
FINANCIAL_TABLES=['ad_fund_settlements', 'app_settings', 'business_lines', 'cash_account_balances', 'cash_accounts', 'cash_audit_logs', 'cash_periods', 'cash_restrictions', 'classification_review_decisions', 'commission_agreements', 'commission_entries', 'commission_status_events', 'company_expenses', 'company_strategy_settings', 'customer_access_grants', 'customer_commission_attributions', 'customer_engagements', 'deals', 'engagement_lifecycle_events', 'engagement_source_links', 'expense_categories', 'expenses', 'finance_refunds', 'monthly_exchange_rates', 'monthly_profit_closes', 'payments', 'payroll_audit_logs', 'payroll_items', 'payroll_sheets', 'product_catalog', 'product_plans', 'sales_deal_handoffs', 'sales_deal_plan_policies', 'sales_dossier_grants', 'sales_handoff_checklists', 'sales_partners', 'sales_payment_requests', 'sales_quote_requests', 'sales_receipt_evidence', 'sales_stripe_events', 'sales_stripe_observations', 'subscriptions']

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
def sql_snapshot(path):
 # JSON normalization makes disk receipts and live tuple metadata comparable.
 return json.loads(json.dumps(retained().sql_snapshot(path)))
def backup(source,target):return retained().backup(source,target)
def schema_signature(path,revision=OLD_REVISION):
 con=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:
  con.execute('PRAGMA query_only=ON');con.execute('BEGIN');need(con.execute('SELECT version_num FROM alembic_version').fetchall()==[(revision,)],'SCHEMA_REVISION_DRIFT');need(con.execute('PRAGMA quick_check').fetchall()==[('ok',)],'DATABASE_INTEGRITY_FAILED')
  return digest(con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall())
 finally:con.close()
def schema_boundary(revision=OLD_REVISION,expected=None):
 value=schema_signature(BUSINESS,revision);need(value==(SCHEMA_SHA if revision==OLD_REVISION else expected),'SCHEMA_DRIFT');return value
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

def public_root():return Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE[:12]+'-20261019')
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
def boundary(pins,*,candidate=None,original=None,candidate_image=None,new_public=None,schema_expected=None):
 private_boundary(pins);credential_boundary();identity=BUSINESS.stat();need((identity.st_dev,identity.st_ino)==BUSINESS_IDENTITY,'DATABASE_IDENTITY_DRIFT');schema=schema_boundary(NEW_REVISION if candidate else OLD_REVISION,schema_expected);static=new_static_boundary(new_public) if new_public else static_boundary();crm=inspect('t24-crm');verify_secret_mount(crm)
 if candidate:
  need(crm['Id']==candidate and crm['Image']==candidate_image and crm['State']['Running'],'CANDIDATE_NOT_RUNNING');verify_clone(crm,original);verify_new_schema(BUSINESS,pristine=True)
 else:
  need(crm['Id']==OLD_ID and crm['Image']==BASE_IMAGE and crm['State']['Running'],'BASELINE_CRM_DRIFT');need(runtime(crm)['config']==OLD_CONFIG,'BASELINE_CONFIGURATION_DRIFT');retained().require_safe_original_restart(crm)
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
 need(manifest.get('old_schema_revision')==OLD_REVISION and manifest.get('additive_tables')==[NEW_TABLE] and manifest.get('production_seed_rows') is False,'EXACT_ADDITIVE_MIGRATION_REQUIRED')
 need(manifest['frontend_version']==FRONTEND_VERSION and manifest['baseline_frontend_version']==BASELINE_FRONTEND and manifest['schema_revision']==REVISION,'EXACT_FRONTEND_SCHEMA_REQUIRED')
 need(manifest['payload_sha256']==args.payload_sha256 and manifest['credentials_included'] is False,'PAYLOAD_IDENTITY_DRIFT')
 need(manifest['preserved']==PRESERVED and manifest['backend_only'] is False and manifest['static_transition'] is True,'SCOPE_REJECTED')
 need(manifest['live_preflight_sha256']==LIVE_PREFLIGHT_SHA and manifest['baseline_backend_inventory_sha256']==BASE_BACKEND_SHA,'LIVE_PREFLIGHT_PINS_REQUIRED')
 need(set(manifest['changed_source_files'])=={'app/backend/'+p for p in BACKEND}|{'app/frontend/src/'+p for p in FRONTEND}|TESTS,'EXACT_SOURCE_SCOPE_REQUIRED')
 need(set(manifest['backend_before'])==BACKEND and set(manifest['backend_after'])==BACKEND,'EXACT_BACKEND_SCOPE_REQUIRED')
 need({name[8:] for name in manifest['files'] if name.startswith('backend/')}==BACKEND,'EXACT_BACKEND_PAYLOAD_REQUIRED')
 need(all(name in {'backend/'+path for path in BACKEND} or name.startswith('static/') and static_path(name[7:]) for name in manifest['files']),'EXACT_PAYLOAD_SCOPE_REQUIRED')
 need({'static/index.html','static/app-version.json'}<=set(manifest['files']),'STATIC_ENTRYPOINTS_REQUIRED')
 need(all(re.fullmatch('[a-f0-9]{64}',value) for value in [*manifest['files'].values(),*manifest['backend_after'].values()]) and all(value is None if path in {'models/stripe_history_daily_scan.py','services/stripe_history_daily_scan.py',MIGRATION} else bool(re.fullmatch('[a-f0-9]{64}',value or '')) for path,value in manifest['backend_before'].items()),'FILE_HASH_PINS_REQUIRED')
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
 verify_startup_delay(read(release/'backend/services/stripe_history_daily_scan.py'))
 need(image_id(BASE_IMAGE)==BASE_IMAGE,'BASE_IMAGE_DRIFT')
 tag='t24-crm:stripe-history-daily-scan-base-'+SOURCE[:12]
 existing=image_id(tag);need(existing is None or existing==BASE_IMAGE,'BASE_TAG_DRIFT')
 if existing is None:run(['docker','image','tag',BASE_IMAGE,tag],'BASE_TAG_CREATE_FAILED')
 need(image_id(tag)==BASE_IMAGE,'BASE_TAG_DRIFT')
 dockerfile='FROM '+tag+'\n'+''.join('COPY backend/'+path+' /app/backend/'+path+'\n' for path in sorted(BACKEND))
 write(release/'Dockerfile',dockerfile.encode());write(release/'.dockerignore',dockerignore())
 candidate='t24-crm:stripe-history-daily-scan-'+SOURCE[:12]
 run(['docker','build','--network=none','--pull=false','-t',candidate,str(release)],'CANDIDATE_BUILD_FAILED',300)
 need(image_id(tag)==BASE_IMAGE,'BASE_TAG_DRIFT');image=image_id(candidate)
 need(bool(re.fullmatch('sha256:[a-f0-9]{64}',image or '')),'CANDIDATE_IMAGE_PIN_REQUIRED');return image
def offline_args(release,data,image):
 args=retained().offline_args(release,data,image);need(args[-1]==image,'OFFLINE_IMAGE_POSITION_DRIFT')
 return args[:-1]+['--mount','type=bind,src='+str(SECRET_HOST)+',dst='+SECRET_TARGET+',readonly','-e','STRIPE_HISTORY_DAILY_SCAN_ENABLED=false',image]
def prepare(release,args,manifest,pins):
 old,schema,static=boundary(pins);verify_production_worker_enabled(old);live=checked_live_preflight(args.preflight,args.preflight_sha256);verify_live_rows(live)
 need(set(path.name for path in release.iterdir())=={'release.py','manifest.json','payload.tar.gz'},'FRESH_STAGING_REQUIRED')
 before=inventory(OLD_ID);need(digest(before)==BASE_BACKEND_SHA and {path:before.get(path) for path in BACKEND}==manifest['backend_before'],'DEPLOYED_SOURCE_BASELINE_DRIFT');expected={**before,**manifest['backend_after']}
 extract(release,manifest);write(release/'original-container.json',old);before_sha=write(release/'backend-original-inventory.json',before);after_sha=write(release/'backend-candidate-inventory.json',expected);retained().environment_file(release,old);image=build_image(release,manifest)
 data=release/'probe-data';data.mkdir(mode=0o700);(release/'probe-logs').mkdir(mode=0o700);backup(BUSINESS,data/'crm_prod.db');rows=sql_snapshot(data/'crm_prod.db');need(len(rows)==111 and schema_signature(data/'crm_prod.db')==schema,'OFFLINE_COPY_DRIFT');old_objects=schema_objects(data/'crm_prod.db')
 run(offline_args(release,data,image)+['python','-B','-c',migration_script()],'OFFLINE_ADDITIVE_MIGRATION_FAILED',90);new_schema=schema_signature(data/'crm_prod.db',NEW_REVISION);verify_new_schema(data/'crm_prod.db',True);additive_objects(old_objects,schema_objects(data/'crm_prod.db'));migrated=sql_snapshot(data/'crm_prod.db');compare_original_rows(rows,migrated)
 name='t24-'+SCOPE+'-probe-'+SOURCE[:12];command=offline_args(release,data,image);command[2:2]=['--name',name,'-d'];run(command,'OFFLINE_STARTUP_FAILED')
 try:
  ready(name);info=inspect(name);verify_secret_mount(info,offline=True);need(info['HostConfig']['NetworkMode']=='none' and 'STRIPE_HISTORY_DAILY_SCAN_ENABLED=false' in info['Config']['Env'],'OFFLINE_SCAN_OR_NETWORK_NOT_DISABLED');need(inventory(name)==expected,'OFFLINE_PROTECTED_SOURCE_DRIFT')
 finally:run(['docker','stop','-t','20',name],'OFFLINE_PROBE_STOP_FAILED',45)
 after_rows=sql_snapshot(data/'crm_prod.db');need(after_rows==migrated and schema_signature(data/'crm_prod.db',NEW_REVISION)==new_schema,'OFFLINE_STARTUP_DATABASE_CHANGED');verify_new_schema(data/'crm_prod.db',True)
 row_proof=write(release/'offline-row-proof.json',{'before':rows,'after':after_rows});root,new_static=stage_public(release,manifest);nginx_next=H(next_nginx(NGINX.read_bytes()));old_now,schema_now,static_now=boundary(pins);verify_live_rows(live);need(runtime(old_now)==runtime(old) and schema_now==schema and static_now==static,'BASELINE_CHANGED_DURING_PREPARE')
 result={'stage':'STRIPE_HISTORY_DAILY_SCAN_PREPARED_OFFLINE_VERIFIED','source_sha':SOURCE,'frontend_version':FRONTEND_VERSION,'candidate_image':image,'old_crm':runtime(old),'schema_before_sha256':schema,'schema_after_sha256':new_schema,'old_schema_revision':OLD_REVISION,'schema_revision':NEW_REVISION,'additive_tables':[NEW_TABLE],'old_static_sha256':static,'public_inventory_sha256':new_static,'public_root':str(root),'nginx_next_sha256':nginx_next,'original_inventory_sha256':before_sha,'candidate_inventory_sha256':after_sha,'manifest_sha256':args.manifest_sha256,'payload_sha256':args.payload_sha256,'preflight_sha256':args.preflight_sha256,'credential_boundary':credential_boundary(),'offline_row_proof_sha256':row_proof,'offline_original_business_rows_unchanged':True,'offline_new_scan_table_empty':True,'offline_daily_scan_disabled':True,'offline_network_none':True,'private_runtime_unchanged':True,'backend_only':False,'static_transition':True,'original_table_count':111,'database_migration':True,'database_restored':False}
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
 receipt=json.loads(read(release/'prepared.json',args.review_sha256));need(receipt['stage']=='STRIPE_HISTORY_DAILY_SCAN_PREPARED_OFFLINE_VERIFIED' and receipt['source_sha']==SOURCE,'PREPARED_SOURCE_DRIFT');need(receipt['manifest_sha256']==args.manifest_sha256 and receipt['payload_sha256']==args.payload_sha256 and receipt['preflight_sha256']==args.preflight_sha256,'PREPARED_PIN_DRIFT')
 need(receipt['original_table_count']==111 and receipt['schema_before_sha256']==SCHEMA_SHA and receipt['old_schema_revision']==OLD_REVISION and receipt['schema_revision']==NEW_REVISION and receipt['additive_tables']==[NEW_TABLE] and bool(re.fullmatch('[a-f0-9]{64}',receipt['schema_after_sha256'])),'PREPARED_SCHEMA_SCOPE_DRIFT')
 need(receipt['old_static_sha256']==STATIC_SHA and receipt['nginx_next_sha256']==H(next_nginx(read(release/'nginx-before.conf',NGINX_SHA) if (release/'nginx-before.conf').exists() else NGINX.read_bytes())),'PREPARED_STATIC_DRIFT')
 need(receipt['frontend_version']==FRONTEND_VERSION and receipt['backend_only'] is False and receipt['static_transition'] is True and receipt['database_migration'] is True and receipt['database_restored'] is False,'PREPARED_SCOPE_DRIFT');need(re.fullmatch('sha256:[a-f0-9]{64}',receipt['candidate_image']) and all(receipt[key] is True for key in ('offline_original_business_rows_unchanged','offline_new_scan_table_empty','offline_daily_scan_disabled','offline_network_none','private_runtime_unchanged')),'PREPARED_PROOF_REQUIRED')
 original=json.loads(read(release/'original-container.json'));need(original['Id']==OLD_ID and original['Image']==BASE_IMAGE and runtime(original)==receipt['old_crm'] and runtime(original)['config']==OLD_CONFIG,'SAVED_ORIGINAL_DRIFT');before=json.loads(read(release/'backend-original-inventory.json',receipt['original_inventory_sha256']));after=json.loads(read(release/'backend-candidate-inventory.json',receipt['candidate_inventory_sha256']));need(digest(before)==BASE_BACKEND_SHA and {path:before.get(path) for path in BACKEND}==manifest['backend_before'] and after=={**before,**manifest['backend_after']},'REVIEWED_INVENTORY_DRIFT')
 proof=json.loads(read(release/'offline-row-proof.json',receipt['offline_row_proof_sha256']));compare_original_rows(proof['before'],proof['after']);need(receipt['credential_boundary']==credential_boundary(),'PREPARED_CREDENTIAL_DRIFT');need(verify_public(public_root(),manifest)==receipt['public_inventory_sha256'] and receipt['public_root']==str(public_root()),'REVIEWED_PUBLIC_DRIFT');verify_production_worker_enabled(original);return receipt,original,before,after
def rollback(release,receipt,original,before,pins,reason):
 # Always move forward after schema publication. Never restore the DB or run the old app.
 manifest=json.loads(read(release/'manifest.json',receipt['manifest_sha256']));need(digest(tree(PUBLIC))==STATIC_SHA and verify_public(public_root(),manifest)==receipt['public_inventory_sha256'],'FORWARD_PUBLIC_DRIFT');private_boundary(pins);credential_boundary();active=inspect_optional('t24-crm')
 if active and active['Id']==OLD_ID:
  need(active['Name']=='/t24-crm' and active['Image']==BASE_IMAGE and runtime(active)['config']==OLD_CONFIG,'ORIGINAL_RECOVERY_DRIFT')
  if active['State']['Running']:run(['docker','stop','-t','30',OLD_ID],'ORIGINAL_STOP_FAILED',60)
  stopped=inspect(OLD_ID);need(not stopped['State']['Running'] and stopped['Image']==BASE_IMAGE and runtime(stopped)['config']==OLD_CONFIG,'ORIGINAL_STILL_RUNNING')
 elif active:
  need(owned(active,receipt),'UNKNOWN_FORWARD_CONTAINER')
  if active['State']['Running']:run(['docker','stop','-t','30',active['Id']],'CANDIDATE_STOP_FAILED',60)
 settle_migration(receipt);baseline=release/'production-before-rows.json'
 if not baseline.exists():
  need(not baseline.is_symlink() and active is not None and active['Id']==OLD_ID and current_revision()==OLD_REVISION,'FORWARD_PRE_CODE_BASELINE_UNAVAILABLE');schema_boundary();rows=sql_snapshot(BUSINESS);need(len(rows)==111,'FORWARD_BASELINE_TABLE_COUNT_DRIFT');write(baseline,rows)
 rows=json.loads(read(baseline));need(len(rows)==111,'FORWARD_BASELINE_SCOPE_DRIFT')
 if current_revision()==OLD_REVISION:
  need(schema_boundary()==SCHEMA_SHA and sql_snapshot(BUSINESS)==rows,'FORWARD_ORIGINAL_ROWS_CHANGED');backup_file=release/('business-forward-before-'+str(time.time_ns())+'.db');backup(BUSINESS,backup_file);need(sql_snapshot(backup_file)==rows,'FORWARD_BACKUP_NOT_CONSISTENT');migrate(release,receipt['candidate_image']);settle_migration(receipt)
 need(current_revision()==NEW_REVISION and schema_boundary(NEW_REVISION,receipt['schema_after_sha256'])==receipt['schema_after_sha256'],'FORWARD_SCHEMA_REQUIRED');compare_original_rows(rows,sql_snapshot(BUSINESS));verify_new_schema(BUSINESS,True)
 if active and active['Id']==OLD_ID:run(['docker','rename',OLD_ID,'t24-crm-before-'+SCOPE+'-'+SOURCE[:12]],'RETAIN_ORIGINAL_FAILED');active=None
 candidate=active['Id'] if active else docker_create(receipt['candidate_image'],original);run(['docker','start',candidate],'FORWARD_START_FAILED');ready(candidate);validation_window(candidate);need(inventory(candidate)=={**before,**manifest['backend_after']},'FORWARD_PROTECTED_SOURCE_DRIFT');compare_original_rows(rows,sql_snapshot(BUSINESS))
 original_nginx=read(release/'nginx-before.conf',NGINX_SHA);updated=next_nginx(original_nginx);cleanup_nginx_temp(original_nginx,updated)
 if NGINX.read_bytes()==original_nginx:replace_nginx(original_nginx,updated)
 else:need(NGINX.read_bytes()==updated,'FORWARD_NGINX_DRIFT')
 retained().reload_nginx();boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'],new_public=receipt,schema_expected=receipt['schema_after_sha256']);need(json.loads(run(['curl','-fsS','https://t24-crm.com/app-version.json'],'FORWARD_PUBLIC_VERSION_FAILED')).get('version')==FRONTEND_VERSION,'FORWARD_PUBLIC_VERSION_DRIFT');run(['curl','-fsS','https://t24-crm.com/ready'],'FORWARD_PUBLIC_READY_FAILED');validation_window(candidate);compare_original_rows(rows,sql_snapshot(BUSINESS))
 result={'stage':'STRIPE_HISTORY_DAILY_SCAN_FORWARD_RECOVERED','deployed':False,'source_sha':SOURCE,'crm_id':candidate,'database_restored':False,'database_migration':True,'old_crm_build_started':False,'public_root':str(public_root()),'nginx_only_public_root_changed':True,'all_original_111_business_rows_unchanged':True,'new_scan_table_empty':True,'private_runtime_unchanged':True,'reason':reason};write(release/('forward-recovery-'+str(time.time_ns())+'.json'),result);return result


def activate(release,args,manifest,pins):
 receipt,original,before,after=reviewed_receipt(release,args,manifest);current,schema,static=boundary(pins);verify_live_rows(checked_live_preflight(args.preflight,args.preflight_sha256));need(runtime(current)==receipt['old_crm'] and schema==receipt['schema_before_sha256'] and static==receipt['old_static_sha256'],'DRIFT_AFTER_REHEARSAL');need(inventory(OLD_ID)==before,'LIVE_SOURCE_DRIFT_AFTER_REHEARSAL');need(not (release/'deployed.json').exists(),'ALREADY_DEPLOYED')
 original_nginx=NGINX.read_bytes();updated_nginx=next_nginx(original_nginx);need(H(updated_nginx)==receipt['nginx_next_sha256'],'REVIEWED_NGINX_DRIFT');write(release/'nginx-before.conf',original_nginx);write(release/'activation-started.json',{'source_sha':SOURCE,'review_sha256':args.review_sha256,'candidate_image':receipt['candidate_image'],'old_id':OLD_ID})
 try:
  run(['docker','stop','-t','30',OLD_ID],'CRM_STOP_FAILED',60);stopped=inspect(OLD_ID);need(stopped['Id']==OLD_ID and stopped['Image']==BASE_IMAGE and not stopped['State']['Running'],'CRM_NOT_STOPPED');rows=sql_snapshot(BUSINESS);need(len(rows)==111 and schema_boundary()==schema,'PRE_MIGRATION_DATABASE_DRIFT');before_rows_sha=write(release/'production-before-rows.json',rows);backup(BUSINESS,release/'business-before.db');need(sql_snapshot(release/'business-before.db')==rows,'PRODUCTION_BACKUP_NOT_CONSISTENT')
  migrate(release,receipt['candidate_image']);settle_migration(receipt);need(schema_boundary(NEW_REVISION,receipt['schema_after_sha256'])==receipt['schema_after_sha256'],'PRODUCTION_SCHEMA_DRIFT');additive_objects(schema_objects(release/'business-before.db'),schema_objects(BUSINESS));verify_new_schema(BUSINESS,True);migrated=sql_snapshot(BUSINESS);compare_original_rows(rows,migrated);migration_rows_sha=write(release/'production-after-migration-rows.json',migrated)
  run(['docker','rename',OLD_ID,'t24-crm-before-'+SCOPE+'-'+SOURCE[:12]],'RETAIN_ORIGINAL_FAILED');candidate=docker_create(receipt['candidate_image'],original);run(['docker','start',candidate],'CANDIDATE_START_FAILED');ready(candidate);validation_window(candidate);need(inspect(candidate)['Image']==receipt['candidate_image'] and inventory(candidate)==after,'LIVE_PROTECTED_SOURCE_DRIFT');boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'],schema_expected=receipt['schema_after_sha256']);need(sql_snapshot(BUSINESS)==migrated,'LIVE_STARTUP_DATABASE_CHANGED');startup_sha=write(release/'production-after-startup-rows.json',migrated)
  replace_nginx(original_nginx,updated_nginx);retained().reload_nginx();run(['curl','-fsS','https://t24-crm.com/ready'],'PUBLIC_CRM_NOT_READY');_,new_schema,new_static=boundary(pins,candidate=candidate,original=original,candidate_image=receipt['candidate_image'],new_public=receipt,schema_expected=receipt['schema_after_sha256']);need(new_static==receipt['public_inventory_sha256'],'FINAL_PUBLIC_DRIFT');need(json.loads(run(['curl','-fsS','https://t24-crm.com/app-version.json'],'PUBLIC_VERSION_FAILED')).get('version')==FRONTEND_VERSION,'PUBLIC_VERSION_DRIFT');validation_window(candidate);final_rows=sql_snapshot(BUSINESS);need(final_rows==migrated,'FINAL_FILLED_ROWS_CHANGED');final_sha=write(release/'production-after-rows.json',final_rows)
  result={'stage':'STRIPE_HISTORY_DAILY_SCAN_DEPLOYED_VERIFIED','deployed':True,'source_sha':SOURCE,'frontend_version':FRONTEND_VERSION,'crm':runtime(inspect(candidate)),'retained_original':OLD_ID,'schema_revision':NEW_REVISION,'schema_sha256':new_schema,'additive_tables':[NEW_TABLE],'original_111_business_rows_unchanged':True,'new_scan_table_empty_at_validation':True,'daily_scan_enabled_after_startup_delay':True,'private_runtime_unchanged':True,'credential_boundary':credential_boundary(),'environment_unchanged':True,'network_unchanged':True,'mounts_unchanged':True,'production_before_rows_sha256':before_rows_sha,'production_after_migration_rows_sha256':migration_rows_sha,'startup_after_rows_sha256':startup_sha,'production_after_rows_sha256':final_sha,'old_static_preserved':True,'static_updated_as_reviewed':True,'nginx_only_public_root_changed':True,'public_root':str(public_root()),'public_inventory_sha256':new_static,'nginx_sha256':receipt['nginx_next_sha256'],'database_migration':True,'database_restored':False,'protected_inventory_sha256':receipt['candidate_inventory_sha256']};proof=write(release/'deployed.json',result);print(json.dumps({**result,'receipt_sha256':proof}))
 except BaseException as error:rollback(release,receipt,original,before,pins,safe_error(error));raise
def recover(release,args,manifest,pins):
 receipt,original,before,_=reviewed_receipt(release,args,manifest)
 need(not (release/'deployed.json').exists(),'SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_REVIEW')
 started=json.loads(read(release/'activation-started.json'))
 need(started=={'source_sha':SOURCE,'review_sha256':args.review_sha256,'candidate_image':receipt['candidate_image'],'old_id':OLD_ID},'ACTIVATION_IDENTITY_DRIFT')
 print(json.dumps(rollback(release,receipt,original,before,pins,'INTERRUPTED_ACTIVATION')))
def safe_error(error):return str(error) if re.fullmatch('[A-Z0-9_]+',str(error) or '') else type(error).__name__.upper()
def checked_live_preflight(path,expected):
 need(expected==LIVE_PREFLIGHT_SHA,'EXACT_LIVE_PREFLIGHT_REQUIRED');proof=json.loads(read(path,expected));need(proof['stage']=='STRIPE_HISTORY_DAILY_SCAN_AUTHENTICATED_CURRENT_PREFLIGHT','LIVE_PREFLIGHT_STAGE_DRIFT');need(proof['source_sha']==BASELINE_APPLICATION_SOURCE and proof['crm']['id']==OLD_ID and proof['crm']['image']==BASE_IMAGE and proof['crm']['config']==OLD_CONFIG,'LIVE_PREFLIGHT_RUNTIME_DRIFT');need(proof['schema_revision']==OLD_REVISION and proof['schema_sha256']==SCHEMA_SHA and proof['table_count']==111 and proof['backend_inventory_sha256']==BASE_BACKEND_SHA and proof['backend_file_count']==346,'LIVE_PREFLIGHT_SOURCE_DRIFT');need(proof['frontend_version']==BASELINE_FRONTEND and proof['financial_table_count']==42,'LIVE_PREFLIGHT_FINANCIAL_SCOPE_DRIFT');need(set(proof['current_financial_table_evidence'])==set(FINANCIAL_TABLES) and len(proof['current_history_table_evidence'])==7,'LIVE_PREFLIGHT_TABLE_SCOPE_DRIFT');need(all(proof[key] is True for key in ('private_runtime_schema_unchanged','runtime_environment_network_mounts_unchanged','public_static_and_nginx_unchanged')) and all(proof[key] is False for key in ('provider_requests','business_rows_modified','credential_values_exported')),'READ_ONLY_PREFLIGHT_REQUIRED');return proof
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['prepare','activate','recover'],required=True)
 parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True)
 parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True)
 parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
 need(socket.gethostname()==HOST and os.geteuid()==0,'EXACT_SERVER_ROOT_REQUIRED');os.umask(0o077);sys.dont_write_bytecode=True
 need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases') and args.release.stat().st_uid==0 and stat.S_IMODE(args.release.stat().st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
 lock=os.open('/opt/t24-crm/releases/.stripe-history-daily-scan-boundaries-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
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

def verify_production_worker_enabled(original):
 env=dict(value.split('=',1) for value in original['Config'].get('Env',[]) if '=' in value)
 need((env.get('STRIPE_HISTORY_DAILY_SCAN_ENABLED') or 'true').strip().lower() not in {'0','false','no','off'} and env.get('IS_LAMBDA')!='true','PRODUCTION_DAILY_SCAN_DISABLED')
def verify_startup_delay(body):
 values=[node.value.value for node in ast.parse(body).body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='STARTUP_DELAY_SECONDS' for target in node.targets) and isinstance(node.value,ast.Constant)]
 need(values==[300],'REVIEWED_STARTUP_DELAY_REQUIRED')
def dockerignore():
 dirs={str(parent) for name in BACKEND for parent in Path('backend',name).parents if str(parent)!='.'}
 return ('*\n!Dockerfile\n'+''.join('!'+name+'\n' for name in sorted(dirs,key=lambda name:(name.count('/'),name)))+''.join('!backend/'+name+'\n' for name in sorted(BACKEND))).encode()
def schema_objects(path):
 c=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:return {(r[0],r[1],r[2]):r[3] for r in c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
 finally:c.close()
def additive_objects(before,after):
 need(all(after.get(key)==value for key,value in before.items()),'ORIGINAL_SCHEMA_OBJECT_CHANGED');need(set(after)-set(before)=={('table',NEW_TABLE,NEW_TABLE)},'UNAPPROVED_SCHEMA_OBJECT_ADDED')
def verify_new_schema(path,pristine=True):
 c=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:
  need(retained().table_schema(c,NEW_TABLE)==NEW_SCHEMA,'NEW_TABLE_SCHEMA_DRIFT');need(retained().table_indexes(c,NEW_TABLE)=={},'NEW_TABLE_INDEX_DRIFT');need(c.execute('PRAGMA foreign_key_list('+retained().quote(NEW_TABLE)+')').fetchall()==NEW_FOREIGN_KEYS,'NEW_TABLE_FOREIGN_KEY_DRIFT')
  if pristine:need(c.execute('SELECT count(*) FROM '+retained().quote(NEW_TABLE)).fetchone()[0]==0,'NEW_TABLE_NOT_EMPTY')
 finally:c.close()
def compare_original_rows(before,after):
 need(len(before)==111 and set(after)==set(before)|{NEW_TABLE},'EXACT_ADDITIVE_TABLE_SET_REQUIRED')
 for table,row in before.items():
  current=after[table];need(all(current[key]==row[key] for key in ('columns','schema','indexes')),'ORIGINAL_TABLE_SCHEMA_CHANGED')
  if table=='alembic_version':need(current['count']==1 and current['rows_sha256']==H(json.dumps([NEW_REVISION]).encode()),'EXACT_NEW_REVISION_REQUIRED')
  else:need(current==row,'ORIGINAL_FILLED_ROWS_CHANGED_'+table.upper())
 need(after[NEW_TABLE]['count']==0,'NEW_TABLE_NOT_EMPTY')
def migration_script():
 return ("import importlib.util,sqlalchemy as sa\nfrom alembic.migration import MigrationContext\nfrom alembic.operations import Operations\nspec=importlib.util.spec_from_file_location('fixed_daily_scan_migration',%r);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\nassert m.revision==%r and m.down_revision==%r\ne=sa.create_engine('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true')\nwith e.connect() as c:\n c.exec_driver_sql('BEGIN IMMEDIATE')\n assert c.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[(%r,)]\n with Operations.context(MigrationContext.configure(c)):m.upgrade()\n r=c.exec_driver_sql(\"UPDATE alembic_version SET version_num='''NEW''' WHERE version_num='''OLD'''\")\n assert r.rowcount==1\n c.commit()\nprint('EXACT_ADDITIVE_DAILY_SCAN_MIGRATION_OK')\n" % (str(Path('/app/backend')/MIGRATION),NEW_REVISION,OLD_REVISION,OLD_REVISION)).replace("'''NEW'''","'"+NEW_REVISION+"'").replace("'''OLD'''","'"+OLD_REVISION+"'")
def current_revision():
 c=sqlite3.connect(f'file:{BUSINESS}?mode=ro',uri=True)
 try:
  rows=c.execute('SELECT version_num FROM alembic_version').fetchall();need(len(rows)==1 and rows[0][0] in (OLD_REVISION,NEW_REVISION),'UNKNOWN_SCHEMA_HEAD');return rows[0][0]
 finally:c.close()
def migration_name():return 't24-'+SCOPE+'-migrate-'+SOURCE[:12]
def settle_migration(receipt):
 info=inspect_optional(migration_name())
 if info:
  labels=info.get('Config',{}).get('Labels') or {};need(info['Image']==receipt['candidate_image'] and labels.get('t24.release.scope')==SCOPE and labels.get('t24.release.source')==SOURCE,'UNKNOWN_MIGRATION_CONTAINER')
  if info['State']['Running']:run(['docker','stop','-t','30',info['Id']],'MIGRATION_STOP_FAILED',60)
  final=inspect_optional(info['Id']);need(final is None or not final['State']['Running'],'MIGRATION_STILL_RUNNING')
  if final:run(['docker','rm',info['Id']],'MIGRATION_REMOVE_FAILED')
def migrate(release,image):
 command=offline_args(release,BUSINESS.parent,image);command[2:2]=['--name',migration_name(),'--label','t24.release.scope='+SCOPE,'--label','t24.release.source='+SOURCE]
 run(command+['python','-B','-c',migration_script()],'PRODUCTION_ADDITIVE_MIGRATION_FAILED',90)
def verify_live_rows(proof):
 rows=sql_snapshot(BUSINESS)
 for scope in ('current_financial_table_evidence','current_history_table_evidence'):
  for table,expected in proof[scope].items():need(all(rows[table][key]==value for key,value in expected.items()),'LIVE_PREFLIGHT_ROWS_DRIFT_'+table.upper())
 return rows
def validation_window(candidate):
 from datetime import datetime,timezone
 started=inspect(candidate)['State']['StartedAt'];seconds=(datetime.now(timezone.utc)-datetime.fromisoformat(started.replace('Z','+00:00'))).total_seconds();need(0<=seconds<180,'INITIAL_VALIDATION_WINDOW_EXPIRED')

if __name__=='__main__':
 try:main()
 except BaseException as error:
  print(json.dumps({'stage':'STRIPE_HISTORY_DAILY_SCAN_RELEASE_REJECTED','code':safe_error(error)}));sys.exit(1)
