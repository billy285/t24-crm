#!/usr/bin/env python3
"""Four additive payment evidence tables and a scoped CRM/static overlay. Never restore data.

Uses the exact reviewed dossier helper for SQLite proofs, private isolation,
Docker cloning, migration settlement, and old-head/forward recovery selection.
The lifecycle below remains specific to this one release.
"""
import argparse,copy,fcntl,hashlib,io,json,os,re,socket,sqlite3,stat,subprocess,sys,tarfile,time,types
from pathlib import Path

SOURCE='78d2bd9934bef296f655356e52efa3ff42e6c885'
FRONTEND_VERSION='44abdb48cad7'
BASELINE='6f524c66db4e94481ba199e0415daa63cef66f7b'
BASELINE_FRONTEND='7d96bb6aa0ca'
HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE='sales-payment-handoff'
BASE_IMAGE='sha256:6ce05502b49d1b9c9c4a6d6773096bb43dec4dd01d8d206ace16000cfe8cf0d5'
OLD_ID='7572863698a82219a4437ffca2b5d458cb0e87586e0d8ba5b20310ab76a3d5a3'
OLD_CONFIG='15395c8cf2f7c2602535a9b6ed4ddbb5ec3c538082609d038d788fe7ef56dec5'
OLD_PUBLIC=Path('/var/www/t24-crm-public/sales-unified-handoff-52cb50a1e76c-20261016')
OLD_STATIC_SHA='2a6c26e2427973ae44f52438e1233c0e076a0ff328f828c0641c8612a890a727'
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA='9bd4dc96098f240636819babac5a05f0e8b648d0e5b584371e20311c9964d473'
BUSINESS=Path('/opt/t24-crm/app/data/crm_prod.db')
BUSINESS_IDENTITY=(64515,262854)
OLD_REVISION='a8d2e6b4c901'
NEW_REVISION='b9e3f7c5d012'
OLD_SCHEMA_SHA='4d2908d3a3ce622eed05bf0901ebc35aadaf856ef0765de298512ca0a94db534'
BASE_BACKEND_SHA='d5486484ca02313eb73c3b21bb621defb74658cbdbd9f2001a2638fef03c6df8'
LIVE_PREFLIGHT_SHA='bcf1be0aa40588b137adeeb461abe5bf3ad57f49df69986cf6d608f1bc86b24a'
MIGRATION='alembic/versions/b9e3f7c5d012_sales_deal_payment_observations.py'
BACKEND={MIGRATION,'main.py','models/sales_deal_payments.py','routers/sales_deal_payments.py',
 'services/sales_deal_payments.py','services/sales_payment_catalog.py','services/sales_deal_handoffs.py','routers/sales_deal_handoffs.py'}
FRONTEND={'components/CustomerSalesHandoff.tsx','components/SalesDealHandoffDialog.tsx',
 'components/SalesDealHandoffQueue.tsx','components/SalesDealPaymentEvidence.tsx','components/SalesDealPaymentLink.tsx',
 'components/sales-deal-handoff.css','lib/sales-deal-handoff.ts'}
TESTS={'app/backend/tests/test_sales_deal_payments.py','app/frontend/tests/sales-deal-handoff.spec.ts',
 'app/frontend/tests/sales-deal-handoff-api.spec.ts'}
PRESERVED={'company_finance_formulas':True,'close_conditions':True,'commission_attribution':True,
 'customer_invitation_rules':True,'private_workspace':True,'existing_business_rows':True,
 'existing_catalog_rows':True,'environment':True}
RETAINED=Path('/opt/t24-crm/releases/sales-dossier-3aaae9f6b13a-20261016/release.py')
RETAINED_SHA='2e1d59d25010cb2141d6c6e25bcb4eaf6bc6cfdfb1015a60d3f8ac6bca5644fe'
AUDIT=Path('/opt/t24-crm/releases/sales-account-boundaries-033d971bf086-20261016/release.py')
AUDIT_SHA='9f5b94cd321eca115771859d8ee8ca158bb0c01b2a41554472df7509fc1c1a9a'
NEW_SCHEMA={'sales_payment_requests': {'created_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                            'created_by_id': ('INTEGER', 1, None, 0),
                            'handoff_id': ('INTEGER', 1, None, 0),
                            'id': ('INTEGER', 1, None, 1),
                            'link_snapshot': ('JSON', 1, None, 0),
                            'reference': ('VARCHAR(80)', 1, None, 0)},
 'sales_receipt_evidence': {'created_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                            'currency': ('VARCHAR(3)', 1, None, 0),
                            'fee_minor': ('INTEGER', 1, None, 0),
                            'gross_minor': ('INTEGER', 1, None, 0),
                            'handoff_id': ('INTEGER', 1, None, 0),
                            'id': ('INTEGER', 1, None, 1),
                            'net_minor': ('INTEGER', 1, None, 0),
                            'observation_id': ('INTEGER', 0, None, 0),
                            'payment_date': ('VARCHAR(10)', 1, None, 0),
                            'service_minor': ('INTEGER', 1, None, 0),
                            'tax_minor': ('INTEGER', 1, None, 0),
                            'transaction_reference_digest': ('VARCHAR(64)', 1, None, 0),
                            'verified_by_id': ('INTEGER', 1, None, 0),
                            'verified_by_name': ('VARCHAR(255)', 0, None, 0)},
 'sales_stripe_events': {'event_id': ('VARCHAR(255)', 1, None, 1),
                         'event_type': ('VARCHAR(80)', 1, None, 0),
                         'observation_id': ('INTEGER', 1, None, 0),
                         'payload_digest': ('VARCHAR(64)', 1, None, 0),
                         'received_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                         'stripe_created_at': ('DATETIME', 1, None, 0)},
 'sales_stripe_observations': {'checkout_completed_at': ('DATETIME', 0, None, 0),
                               'currency': ('VARCHAR(3)', 0, None, 0),
                               'gross_minor': ('INTEGER', 0, None, 0),
                               'id': ('INTEGER', 1, None, 1),
                               'invoice_id': ('VARCHAR(255)', 0, None, 0),
                               'latest_event_at': ('DATETIME', 1, None, 0),
                               'match_issues': ('JSON', 1, None, 0),
                               'paid_at': ('DATETIME', 0, None, 0),
                               'payer_business_name': ('VARCHAR(255)', 0, None, 0),
                               'payer_email': ('VARCHAR(320)', 0, None, 0),
                               'payer_name': ('VARCHAR(255)', 0, None, 0),
                               'payment_intent_id': ('VARCHAR(255)', 0, None, 0),
                               'received_at': ('DATETIME', 1, 'CURRENT_TIMESTAMP', 0),
                               'request_id': ('INTEGER', 1, None, 0),
                               'service_minor': ('INTEGER', 0, None, 0),
                               'session_id': ('VARCHAR(255)', 1, None, 0),
                               'status': ('VARCHAR(32)', 1, None, 0),
                               'stripe_created_at': ('DATETIME', 0, None, 0),
                               'subscription_id': ('VARCHAR(255)', 0, None, 0),
                               'tax_minor': ('INTEGER', 0, None, 0)}}
NEW_INDEXES={'sales_payment_requests': {'sqlite_autoindex_sales_payment_requests_1': (1, 'u', 0, ('handoff_id',)),
                            'sqlite_autoindex_sales_payment_requests_2': (1, 'u', 0, ('reference',))},
 'sales_receipt_evidence': {'sqlite_autoindex_sales_receipt_evidence_1': (1, 'u', 0, ('handoff_id',)),
                            'sqlite_autoindex_sales_receipt_evidence_2': (1, 'u', 0, ('observation_id',)),
                            'sqlite_autoindex_sales_receipt_evidence_3': (1,
                                                                          'u',
                                                                          0,
                                                                          ('transaction_reference_digest',))},
 'sales_stripe_events': {'sqlite_autoindex_sales_stripe_events_1': (1, 'pk', 0, ('event_id',))},
 'sales_stripe_observations': {'ix_sales_stripe_observations_invoice_id': (0, 'c', 0, ('invoice_id',)),
                               'ix_sales_stripe_observations_payment_intent_id': (0,
                                                                                  'c',
                                                                                  0,
                                                                                  ('payment_intent_id',)),
                               'ix_sales_stripe_observations_request_id': (0, 'c', 0, ('request_id',)),
                               'ix_sales_stripe_observations_subscription_id': (0,
                                                                                'c',
                                                                                0,
                                                                                ('subscription_id',)),
                               'sqlite_autoindex_sales_stripe_observations_1': (1, 'u', 0, ('session_id',))}}
NEW_FOREIGN_KEYS={'sales_payment_requests': [(0,
                             0,
                             'sales_deal_handoffs',
                             'handoff_id',
                             'id',
                             'NO ACTION',
                             'RESTRICT',
                             'NONE')],
 'sales_receipt_evidence': [(0,
                             0,
                             'sales_stripe_observations',
                             'observation_id',
                             'id',
                             'NO ACTION',
                             'RESTRICT',
                             'NONE'),
                            (1,
                             0,
                             'sales_deal_handoffs',
                             'handoff_id',
                             'id',
                             'NO ACTION',
                             'RESTRICT',
                             'NONE')],
 'sales_stripe_events': [(0,
                          0,
                          'sales_stripe_observations',
                          'observation_id',
                          'id',
                          'NO ACTION',
                          'RESTRICT',
                          'NONE')],
 'sales_stripe_observations': [(0,
                                0,
                                'sales_payment_requests',
                                'request_id',
                                'id',
                                'NO ACTION',
                                'RESTRICT',
                                'NONE')]}
H=lambda body:hashlib.sha256(body).hexdigest()
_D=None
_A=None

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
 result=subprocess.run(args,capture_output=True,timeout=timeout);need(result.returncode==0,code);return result.stdout
def load(path,expected,name):
 module=types.ModuleType(name);module.__file__=str(path)
 exec(compile(read(path,expected),str(path),'exec'),module.__dict__);return module
def configure(module):
 # Only this in-memory copy changes; the reviewed on-disk helper stays immutable.
 for key in ('SOURCE','BASELINE','BASELINE_FRONTEND','FRONTEND_VERSION','HOST','BASE_IMAGE','OLD_ID','OLD_PUBLIC','NGINX','NGINX_SHA','BUSINESS','MIGRATION','BACKEND','OLD_REVISION','NEW_REVISION','NEW_SCHEMA','NEW_INDEXES','PRESERVED'):
  setattr(module,key,globals()[key])
 module.ADDITIONS={};module.ADDED_SCHEMA={};module.NEW_TABLES={t:set(cols) for t,cols in NEW_SCHEMA.items()}
 module.current_boundary=current_boundary;module.prepared_receipt=reviewed_receipt
 module.verify_sales_schema=verify_new_schema
 module.migration_name=migration_name;module.production_migration_args=production_migration_args
 module.owned_release_container=owned;module.forward_recover=forward_recover;module.restore_crm=restore_crm
 module.replace_nginx=replace_nginx;module.cleanup_nginx_temp=cleanup_nginx_temp
 return module
def retained():
 global _D
 read(RETAINED,RETAINED_SHA)
 if _D is None:_D=configure(load(RETAINED,RETAINED_SHA,'_unified_handoff_retained'))
 return _D
def inventory(name):
 global _A
 read(AUDIT,AUDIT_SHA)
 if _A is None:_A=load(AUDIT,AUDIT_SHA,'_unified_handoff_inventory')
 return _A.inventory(name)
def public_root():return Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE[:12]+'-20261016')
def schema_signature(path,revision):
 con=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:
  con.execute('BEGIN');need(con.execute('SELECT version_num FROM alembic_version').fetchall()==[(revision,)],'SCHEMA_REVISION_DRIFT')
  need(con.execute('PRAGMA quick_check').fetchall()==[('ok',)],'DATABASE_INTEGRITY_FAILED')
  return digest(con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall())
 finally:con.close()
def schema_objects(path):
 con=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:return {(r[0],r[1],r[2]):r[3] for r in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
 finally:con.close()
def additive_objects(before,after):
 need(all(after.get(key)==sql for key,sql in before.items()),'ORIGINAL_SCHEMA_OBJECT_CHANGED')
 allowed={('table',table,table) for table in NEW_SCHEMA}|{('index',name,table) for table,indexes in NEW_INDEXES.items() for name in indexes if not name.startswith('sqlite_')}
 need(set(after)-set(before)==allowed,'UNAPPROVED_SCHEMA_OBJECT_ADDED')
def verify_new_schema(path,pristine=False):
 d=retained();con=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
 try:
  con.execute('BEGIN')
  for table,expected in NEW_SCHEMA.items():
   need(d.table_schema(con,table)==expected,'SALES_TABLE_SCHEMA_DRIFT')
   need(d.table_indexes(con,table)==NEW_INDEXES[table],'SALES_INDEX_SCHEMA_DRIFT')
   need(con.execute('PRAGMA foreign_key_list('+d.quote(table)+')').fetchall()==NEW_FOREIGN_KEYS[table],'SALES_FOREIGN_KEY_DRIFT')
   if pristine:need(con.execute('SELECT count(*) FROM '+d.quote(table)).fetchone()[0]==0,'NEW_SALES_TABLE_NOT_EMPTY')
 finally:con.close()
def current_boundary(pins,after_crm=None):
 d=retained();tools=d.private_boundary(pins);crm=d.inspect('t24-crm');identity=BUSINESS.stat()
 need((identity.st_dev,identity.st_ino)==BUSINESS_IDENTITY,'BUSINESS_DATABASE_IDENTITY_DRIFT')
 if after_crm:
  need(crm['Id']==after_crm and crm['State']['Running'],'CANDIDATE_NOT_RUNNING');d.verify_sales_schema(BUSINESS)
  schema_signature(BUSINESS,NEW_REVISION)
 else:
  need(crm['Id']==OLD_ID and crm['Image']==BASE_IMAGE and crm['State']['Running'],'ORIGINAL_CRM_DRIFT')
  need(d.runtime(crm)['config']==OLD_CONFIG,'ORIGINAL_CRM_CONFIGURATION_DRIFT');d.require_safe_original_restart(crm)
  need(schema_signature(BUSINESS,OLD_REVISION)==OLD_SCHEMA_SHA,'ORIGINAL_SCHEMA_DRIFT')
 return tools
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
def old_static():
 need(H(NGINX.read_bytes())==NGINX_SHA and NGINX.read_bytes().count(('root '+str(OLD_PUBLIC)+';').encode())==1,'NGINX_BASELINE_DRIFT')
 need(digest(tree(OLD_PUBLIC))==OLD_STATIC_SHA,'STATIC_BASELINE_DRIFT')
 need(json.loads((OLD_PUBLIC/'app-version.json').read_bytes())['version']==BASELINE_FRONTEND,'FRONTEND_BASELINE_DRIFT')
def verify_public(root,manifest):
 need(root==public_root(),'EXACT_PUBLIC_ROOT_REQUIRED')
 files=tree(root)
 need(all(files.get(n[7:])==h for n,h in manifest['files'].items() if n.startswith('static/')),'PUBLIC_FILE_DRIFT')
 need(json.loads((root/'app-version.json').read_bytes())['version']==FRONTEND_VERSION,'PUBLIC_VERSION_DRIFT');return digest(files)
def stage_public(release,manifest):
 d=retained();root=public_root();need(not root.exists() and not root.is_symlink(),'FRESH_STATIC_ROOT_REQUIRED');d.public_directory(root,root)
 for name in manifest['files']:
  if name.startswith('static/'):
   target=root/name[7:];d.public_directory(target.parent,root)
   with target.open('xb') as stream:stream.write(read(release/name))
   target.chmod(0o644)
 for name,value in tree(OLD_PUBLIC).items():
  if name.startswith('assets/'):
   target=root/name;d.public_directory(target.parent,root)
   if target.exists():need(H(target.read_bytes())==value,'STATIC_ASSET_COLLISION')
   else:
    with target.open('xb') as stream:stream.write((OLD_PUBLIC/name).read_bytes())
    target.chmod(0o644)
 return root,verify_public(root,manifest)
def checked_manifest(release,args):
 need(bool(NEW_SCHEMA) and 'UNFROZEN' not in FRONTEND and 'UNFROZEN' not in TESTS and bool(re.fullmatch('[a-f0-9]{64}',LIVE_PREFLIGHT_SHA)) and bool(re.fullmatch('[a-f0-9]{64}',BASE_BACKEND_SHA)) and bool(re.fullmatch('[a-f0-9]{40}',SOURCE)) and bool(re.fullmatch('[a-f0-9]{12}',FRONTEND_VERSION)),'FROZEN_SOURCE_VERSION_REQUIRED')
 m=json.loads(read(release/'manifest.json',args.manifest_sha256));read(release/'payload.tar.gz',args.payload_sha256)
 need(m['source_sha']==SOURCE and m['baseline_source_sha']==BASELINE and m['frontend_version']==FRONTEND_VERSION and m['baseline_frontend_version']==BASELINE_FRONTEND,'SOURCE_PINS_REQUIRED')
 need(m['live_preflight_sha256']==LIVE_PREFLIGHT_SHA and m['baseline_backend_inventory_sha256']==BASE_BACKEND_SHA,'LIVE_PREFLIGHT_PINS_REQUIRED')
 need(m['payload_sha256']==args.payload_sha256 and m['credentials_included'] is False and m['preserved']==PRESERVED,'MANIFEST_SCOPE_REJECTED')
 need(m['old_schema_revision']==OLD_REVISION and m['new_schema_revision']==NEW_REVISION and m['additive_tables']==sorted(NEW_SCHEMA) and m['production_seed_rows'] is False,'ADDITIVE_SCHEMA_SCOPE_REQUIRED')
 need(set(m['backend_before'])==BACKEND and set(m['backend_after'])==BACKEND,'EXACT_BACKEND_SCOPE_REQUIRED')
 need(set(m['changed_source_files'])=={'app/backend/'+p for p in BACKEND}|{'app/frontend/src/'+p for p in FRONTEND}|TESTS,'EXACT_SOURCE_SCOPE_REQUIRED')
 need({n[8:] for n in m['files'] if n.startswith('backend/')}==BACKEND,'EXACT_BACKEND_PAYLOAD_REQUIRED')
 need(all(n in {'backend/'+b for b in BACKEND} or (n.startswith('static/') and static_path(n[7:])) for n in m['files']),'PAYLOAD_SCOPE_REJECTED')
 need({'static/index.html','static/app-version.json'}<=set(m['files']),'STATIC_ENTRYPOINTS_REQUIRED')
 need(all(re.fullmatch('[a-f0-9]{64}',h or '') for h in [*m['files'].values(),*m['backend_after'].values()]),'FILE_HASH_PINS_REQUIRED')
 need(all(m['files']['backend/'+b]==m['backend_after'][b] for b in BACKEND),'BACKEND_HASH_IDENTITY_DRIFT');return m
def dockerignore():
 dirs={str(p) for name in BACKEND for p in Path('backend',name).parents if str(p)!='.'}
 return ('*\n!Dockerfile\n'+''.join('!'+p+'\n' for p in sorted(dirs,key=lambda x:(x.count('/'),x)))+''.join('!backend/'+p+'\n' for p in sorted(BACKEND))).encode()
def build_image(release):
 d=retained();need(d.local_image_id(BASE_IMAGE)==BASE_IMAGE,'BASE_IMAGE_DRIFT')
 tag='t24-crm:'+SCOPE+'-base-'+SOURCE[:12];existing=d.local_image_id(tag)
 need(existing is None or existing==BASE_IMAGE,'BASE_TAG_DRIFT')
 if existing is None:run(['docker','image','tag',BASE_IMAGE,tag],'BASE_TAG_CREATE_FAILED')
 write(release/'Dockerfile',('FROM '+tag+'\n'+''.join('COPY backend/'+p+' /app/backend/'+p+'\n' for p in sorted(BACKEND))).encode());write(release/'.dockerignore',dockerignore())
 target='t24-crm:'+SCOPE+'-'+SOURCE[:12]
 run(['docker','build','--network=none','--pull=false','-t',target,str(release)],'CANDIDATE_BUILD_FAILED',300)
 need(d.local_image_id(tag)==BASE_IMAGE,'BASE_TAG_DRIFT');image=d.local_image_id(target)
 need(bool(re.fullmatch('sha256:[a-f0-9]{64}',image or '')),'CANDIDATE_IMAGE_PIN_REQUIRED');return image
def migration_script():
 return """import importlib.util,sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
spec=importlib.util.spec_from_file_location('fixed_handoff_migration',%r);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.revision==%r and m.down_revision==%r
e=sa.create_engine('sqlite:////app/backend/data/crm_prod.db')
with e.connect() as c:
 c.exec_driver_sql('BEGIN IMMEDIATE')
 assert c.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[(%r,)]
 with Operations.context(MigrationContext.configure(c)):m.upgrade()
 result=c.exec_driver_sql("UPDATE alembic_version SET version_num='%s' WHERE version_num='%s'")
 assert result.rowcount==1
 c.commit()
print('EXACT_ADDITIVE_HANDOFF_MIGRATION_OK')
""" % (MIGRATION,NEW_REVISION,OLD_REVISION,OLD_REVISION,NEW_REVISION,OLD_REVISION)
def migration_name(m):return 't24-'+SCOPE+'-migrate-'+SOURCE[:12]
def production_migration_args(release,image,m):
 cmd=retained().offline_args(release,BUSINESS.parent,image)
 cmd[2:2]=['--name',migration_name(m),'--label','t24.release.scope='+SCOPE,'--label','t24.release.source='+SOURCE]
 return cmd+['python','-c',migration_script()]
def clone_config(image,original):
 d=retained();config=copy.deepcopy(original['Config']);config.update(Image=image,Hostname='',Labels={**(config.get('Labels') or {}),'t24.release.scope':SCOPE,'t24.release.source':SOURCE})
 config['HostConfig']=copy.deepcopy(original['HostConfig']);config['HostConfig']['AutoRemove']=False
 networks=d.clone_networks(original);need(networks or original['HostConfig']['NetworkMode'] in ('host','none'),'ORIGINAL_NETWORKS_REQUIRED')
 config['NetworkingConfig']={'EndpointsConfig':networks};return config
def verify_clone(candidate,original):
 expected=clone_config(candidate['Image'],original)['Labels'];need(candidate['Config'].get('Labels')==expected,'CANDIDATE_LABEL_DRIFT')
 normalized=copy.deepcopy(candidate)
 for key in ('Image','Hostname','Labels'):normalized['Config'][key]=copy.deepcopy(original['Config'].get(key))
 need(retained().runtime(normalized)['config']==retained().runtime(original)['config'],'CANDIDATE_CONFIGURATION_DRIFT')
def create(image,original):
 status,body=retained().docker_request('POST','/containers/create?name=t24-crm',clone_config(image,original));need(status==201,'CONTAINER_CREATE_FAILED');return json.loads(body)['Id']
def owned(info,receipt,m):
 labels=info.get('Config',{}).get('Labels') or {}
 return info['Image']==receipt['candidate_image'] and labels.get('t24.release.scope')==SCOPE and labels.get('t24.release.source')==SOURCE
def prepare(release,args,m,pins):
 d=retained();current_boundary(pins);old_static();old=d.inspect('t24-crm')
 need({p.name for p in release.iterdir()}=={'release.py','manifest.json','payload.tar.gz'},'FRESH_RELEASE_REQUIRED')
 before=inventory(OLD_ID);need(digest(before)==BASE_BACKEND_SHA and {p:before.get(p) for p in BACKEND}==m['backend_before'],'DEPLOYED_SOURCE_BASELINE_DRIFT')
 expected={**before,**m['backend_after']};d.extract(release,m);write(release/'original-container.json',old);d.environment_file(release,old)
 before_sha=write(release/'backend-original-inventory.json',before);after_sha=write(release/'backend-candidate-inventory.json',expected)
 image=build_image(release);data=release/'probe-data';data.mkdir(mode=0o700);(release/'probe-logs').mkdir(mode=0o700)
 d.backup(BUSINESS,data/'crm_prod.db');rows=d.sql_snapshot(data/'crm_prod.db');objects=schema_objects(data/'crm_prod.db')
 need(schema_signature(data/'crm_prod.db',OLD_REVISION)==OLD_SCHEMA_SHA,'OFFLINE_COPY_SCHEMA_DRIFT')
 run(d.offline_args(release,data,image)+['python','-c',migration_script()],'OFFLINE_MIGRATION_FAILED')
 additive_objects(objects,schema_objects(data/'crm_prod.db'))
 d.original_rows_unchanged(rows,d.sql_snapshot(data/'crm_prod.db',rows));d.verify_sales_schema(data/'crm_prod.db',True)
 new_schema=schema_signature(data/'crm_prod.db',NEW_REVISION)
 name='t24-'+SCOPE+'-probe-'+SOURCE[:12];cmd=d.offline_args(release,data,image);cmd[2:2]=['--name',name,'-d'];run(cmd,'OFFLINE_STARTUP_FAILED')
 try:d.ready(name);need(inventory(name)==expected,'OFFLINE_PROTECTED_SOURCE_DRIFT')
 finally:run(['docker','stop','-t','20',name],'OFFLINE_PROBE_STOP_FAILED',45)
 d.original_rows_unchanged(rows,d.sql_snapshot(data/'crm_prod.db',rows));d.verify_sales_schema(data/'crm_prod.db',True)
 need(schema_signature(data/'crm_prod.db',NEW_REVISION)==new_schema,'OFFLINE_STARTUP_SCHEMA_CHANGED')
 proof_sha=write(release/'offline-row-proof.json',{'before':rows,'after':d.sql_snapshot(data/'crm_prod.db',rows)})
 root,static_sha=stage_public(release,m);current_boundary(pins);old_static()
 need(d.runtime(d.inspect('t24-crm'))==d.runtime(old) and inventory(OLD_ID)==before,'BASELINE_CHANGED_DURING_PREPARE')
 result={'stage':'SALES_PAYMENT_HANDOFF_PREPARED','source_sha':SOURCE,'version':FRONTEND_VERSION,'candidate_image':image,'rollback_image':image,'old_crm':d.runtime(old),
  'public_root':str(root),'public_inventory_sha256':static_sha,'schema_before_sha256':OLD_SCHEMA_SHA,'schema_after_sha256':new_schema,
  'original_inventory_sha256':before_sha,'candidate_inventory_sha256':after_sha,'offline_row_proof_sha256':proof_sha,
  'manifest_sha256':args.manifest_sha256,'payload_sha256':args.payload_sha256,'preflight_sha256':args.preflight_sha256,
  'live_preflight_sha256':LIVE_PREFLIGHT_SHA,'migration':NEW_REVISION,'additive_tables':sorted(NEW_SCHEMA),'original_table_count':len(rows),
  'offline_original_rows_unchanged':True,'new_tables_empty':True,'private_runtime_unchanged':True,'catalog_seeded':False,'database_restored':False}
 proof=write(release/'prepared.json',result);print(json.dumps({**result,'receipt_sha256':proof}))
def reviewed_receipt(release,args,m):
 receipt=json.loads(read(release/'prepared.json',args.review_sha256))
 need(receipt['stage']=='SALES_PAYMENT_HANDOFF_PREPARED' and receipt['source_sha']==SOURCE and receipt['version']==FRONTEND_VERSION,'PREPARED_SOURCE_DRIFT')
 need(receipt['manifest_sha256']==args.manifest_sha256 and receipt['payload_sha256']==args.payload_sha256 and receipt['preflight_sha256']==args.preflight_sha256 and receipt['live_preflight_sha256']==LIVE_PREFLIGHT_SHA,'PREPARED_PIN_DRIFT')
 need(receipt['public_root']==str(public_root()) and receipt['schema_before_sha256']==OLD_SCHEMA_SHA and receipt['migration']==NEW_REVISION and receipt['additive_tables']==sorted(NEW_SCHEMA),'PREPARED_SCOPE_DRIFT')
 need(receipt['candidate_image']==receipt['rollback_image'] and bool(re.fullmatch('sha256:[a-f0-9]{64}',receipt['candidate_image'])),'PREPARED_IMAGE_PIN_REQUIRED')
 need(all(receipt[x] is True for x in ('offline_original_rows_unchanged','new_tables_empty','private_runtime_unchanged')) and receipt['catalog_seeded'] is False and receipt['database_restored'] is False,'PREPARED_PROOF_REQUIRED')
 original=json.loads(read(release/'original-container.json'));need(retained().runtime(original)==receipt['old_crm'] and original['Id']==OLD_ID and original['Image']==BASE_IMAGE and receipt['old_crm']['config']==OLD_CONFIG,'SAVED_CONFIGURATION_DRIFT')
 before=json.loads(read(release/'backend-original-inventory.json',receipt['original_inventory_sha256']));after=json.loads(read(release/'backend-candidate-inventory.json',receipt['candidate_inventory_sha256']))
 need(digest(before)==BASE_BACKEND_SHA and {p:before.get(p) for p in BACKEND}==m['backend_before'] and after=={**before,**m['backend_after']},'REVIEWED_SOURCE_INVENTORY_DRIFT')
 read(release/'offline-row-proof.json',receipt['offline_row_proof_sha256']);return receipt
def expected_inventory(release,receipt):return json.loads(read(release/'backend-candidate-inventory.json',receipt['candidate_inventory_sha256']))
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
def restore_crm(receipt,m,original,revision):
 d=retained();need(revision==OLD_REVISION,'OLD_BUILD_FORBIDDEN_AFTER_MIGRATION');active=d.inspect_optional('t24-crm')
 if active and active['Id']!=OLD_ID:
  need(owned(active,receipt,m),'UNKNOWN_ACTIVE_CRM');run(['docker','stop','-t','20',active['Id']],'FAILED_CANDIDATE_STOP_FAILED',45)
  run(['docker','rename',active['Id'],'t24-crm-failed-'+SCOPE+'-'+SOURCE[:12]+'-'+active['Id'][:12]],'FAILED_CANDIDATE_RETAIN_FAILED')
 original_now=d.inspect(OLD_ID);need(original_now['Image']==BASE_IMAGE and d.runtime(original_now)['config']==receipt['old_crm']['config'],'ORIGINAL_RETAINED_CONFIGURATION_DRIFT')
 if original_now['Name']!='/t24-crm':run(['docker','rename',OLD_ID,'t24-crm'],'ORIGINAL_RENAME_FAILED')
 run(['docker','start',OLD_ID],'ORIGINAL_START_FAILED');d.ready(OLD_ID)
 need(digest(inventory(OLD_ID))==BASE_BACKEND_SHA,'RECOVERED_ORIGINAL_SOURCE_DRIFT');old_static();return OLD_ID
def forward_recover(release,receipt,m,pins,original_nginx,next_nginx,reason):
 d=retained();d.settle_migration(receipt,m);need(d.committed_revision()==NEW_REVISION,'FORWARD_SCHEMA_REQUIRED');d.private_boundary(pins)
 need(schema_signature(BUSINESS,NEW_REVISION)==receipt['schema_after_sha256'],'FORWARD_SCHEMA_DRIFT')
 original=d.recovery_original(release,receipt);need(verify_public(public_root(),m)==receipt['public_inventory_sha256'],'FORWARD_STATIC_DRIFT')
 active=d.inspect_optional('t24-crm')
 if active and active['Id']==OLD_ID:
  if active['State']['Running']:run(['docker','stop','-t','30',OLD_ID],'LEGACY_STOP_FAILED',60)
  run(['docker','rename',OLD_ID,'t24-crm-before-'+SCOPE+'-'+SOURCE[:12]],'RETAIN_ORIGINAL_FAILED');active=None
 if active:need(owned(active,receipt,m),'UNKNOWN_FORWARD_CRM');candidate=active['Id']
 else:candidate=create(receipt['candidate_image'],original)
 run(['docker','start',candidate],'FORWARD_START_FAILED');d.ready(candidate);info=d.inspect(candidate)
 need(owned(info,receipt,m),'FORWARD_IMAGE_IDENTITY_DRIFT');verify_clone(info,original)
 need(inventory(candidate)==expected_inventory(release,receipt),'FORWARD_SOURCE_DRIFT');cleanup_nginx_temp(original_nginx,next_nginx)
 if NGINX.read_bytes()==original_nginx:d.swap_nginx(original_nginx,next_nginx)
 else:need(NGINX.read_bytes()==next_nginx,'FORWARD_NGINX_DRIFT');d.reload_nginx()
 current_boundary(pins,candidate);need(schema_signature(BUSINESS,NEW_REVISION)==receipt['schema_after_sha256'],'FORWARD_SCHEMA_DRIFT')
 result={'stage':'SALES_PAYMENT_HANDOFF_FORWARD_RECOVERED','deployed':False,'database_restored':False,'old_crm_build_started':False,'private_runtime_unchanged':True,'crm_id':candidate,'reason_type':reason}
 write(release/('forward-recovery-'+str(time.time_ns())+'.json'),result);return result
def activate(release,args,m,pins):
 d=retained();receipt=reviewed_receipt(release,args,m);current_boundary(pins);old_static()
 original=json.loads(read(release/'original-container.json'));need(d.runtime(d.inspect('t24-crm'))==receipt['old_crm'],'CRM_DRIFT_AFTER_PREPARE')
 need(inventory(OLD_ID)==json.loads(read(release/'backend-original-inventory.json',receipt['original_inventory_sha256'])),'BACKEND_DRIFT_AFTER_PREPARE')
 need(verify_public(public_root(),m)==receipt['public_inventory_sha256'],'PUBLIC_DRIFT_AFTER_PREPARE')
 original_nginx=NGINX.read_bytes();next_nginx=original_nginx.replace(('root '+str(OLD_PUBLIC)+';').encode(),('root '+str(public_root())+';').encode());write(release/'nginx-before.conf',original_nginx)
 retained_name='t24-crm-before-'+SCOPE+'-'+SOURCE[:12]
 write(release/'activation-started.json',{'stage':'ACTIVATING','prepared_sha256':args.review_sha256,'source_sha':SOURCE,'old_id':OLD_ID,'old_image':BASE_IMAGE,'candidate_image':receipt['candidate_image'],'rollback_image':receipt['rollback_image'],'retained_name':retained_name})
 try:
  run(['docker','stop','-t','30','t24-crm'],'CRM_STOP_FAILED',60);stopped=d.inspect(OLD_ID)
  need(not stopped['State']['Running'] and stopped['Image']==BASE_IMAGE and d.runtime(stopped)['config']==OLD_CONFIG,'CRM_NOT_STOPPED_AS_REVIEWED')
  d.backup(BUSINESS,release/'business-before.db');before=d.sql_snapshot(release/'business-before.db');need(schema_signature(release/'business-before.db',OLD_REVISION)==OLD_SCHEMA_SHA,'PRODUCTION_COPY_SCHEMA_DRIFT')
  before_sha=write(release/'production-before-rows.json',before);auth=d.authorization_snapshot(BUSINESS)
  objects=schema_objects(BUSINESS)
  run(production_migration_args(release,receipt['candidate_image'],m),'PRODUCTION_ADDITIVE_MIGRATION_FAILED');d.settle_migration(receipt,m)
  need(d.committed_revision()==NEW_REVISION and schema_signature(BUSINESS,NEW_REVISION)==receipt['schema_after_sha256'],'PRODUCTION_MIGRATION_SCHEMA_DRIFT')
  after=d.sql_snapshot(BUSINESS,before);d.original_rows_unchanged(before,after);d.verify_sales_schema(BUSINESS,True)
  additive_objects(objects,schema_objects(BUSINESS))
  need(d.authorization_snapshot(BUSINESS)==auth,'MIGRATION_CHANGED_AUTHORIZATION');after_sha=write(release/'production-after-rows.json',after)
  run(['docker','rename','t24-crm',retained_name],'RETAIN_ORIGINAL_FAILED');candidate=create(receipt['candidate_image'],original)
  run(['docker','start',candidate],'CANDIDATE_START_FAILED');d.ready(candidate);info=d.inspect(candidate)
  need(owned(info,receipt,m),'LIVE_IMAGE_IDENTITY_DRIFT');verify_clone(info,original)
  need(inventory(candidate)==expected_inventory(release,receipt),'LIVE_PROTECTED_SOURCE_DRIFT');current_boundary(pins,candidate)
  d.swap_nginx(original_nginx,next_nginx);_,_,base,_,_=d.tools();base.public_check(base.file_map(public_root()),FRONTEND_VERSION,public_root(),verify_services=False)
  run(['curl','-fsS','https://t24-crm.com/ready'],'PUBLIC_READY_FAILED');current_boundary(pins,candidate)
  need(schema_signature(BUSINESS,NEW_REVISION)==receipt['schema_after_sha256'],'LIVE_SCHEMA_DRIFT')
  need(verify_public(public_root(),m)==receipt['public_inventory_sha256'] and H(NGINX.read_bytes())==H(next_nginx),'LIVE_STATIC_DRIFT')
  result={'stage':'SALES_PAYMENT_HANDOFF_DEPLOYED','deployed':True,'source_sha':SOURCE,'frontend_version':FRONTEND_VERSION,'crm':d.runtime(d.inspect(candidate)),
   'public_root':str(public_root()),'nginx_sha256':H(next_nginx),'public_inventory_sha256':receipt['public_inventory_sha256'],
   'migration':NEW_REVISION,'schema_sha256':receipt['schema_after_sha256'],'original_rows_unchanged_during_migration':True,
   'production_before_rows_sha256':before_sha,'production_after_rows_sha256':after_sha,'private_runtime_unchanged':True,
   'environment_unchanged':True,'catalog_seeded':False,'database_restored':False,'retained_original':retained_name}
  proof=write(release/'deployed.json',result);print(json.dumps({**result,'receipt_sha256':proof}))
 except BaseException as error:
  recovery=d.rollback(release,receipt,m,pins,original_nginx,next_nginx,d.safe_error(error));print(json.dumps({'recovery':recovery}));raise
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['prepare','activate','recover'],required=True);parser.add_argument('--release',type=Path,required=True)
 for name in ('manifest-sha256','payload-sha256','preflight-sha256'):parser.add_argument('--'+name,required=True)
 parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
 need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_SERVER_ROOT_REQUIRED');os.umask(0o077);sys.dont_write_bytecode=True
 need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases') and args.release.stat().st_uid==0 and stat.S_IMODE(args.release.stat().st_mode)==0o700,'PROTECTED_RELEASE_REQUIRED')
 lock=os.open('/opt/t24-crm/releases/.sales-payment-handoff-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 m=checked_manifest(args.release,args);pins=json.loads(read(args.preflight,args.preflight_sha256))
 if args.phase=='prepare':prepare(args.release,args,m,pins)
 else:
  need(bool(args.review_sha256),'INDEPENDENT_PREPARE_REVIEW_REQUIRED');(activate if args.phase=='activate' else retained().recover)(args.release,args,m,pins)
if __name__=='__main__':
 try:main()
 except BaseException as error:
  code=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(error)) else type(error).__name__.upper()
  print(json.dumps({'stage':'SALES_PAYMENT_HANDOFF_RELEASE_REJECTED','code':code}));sys.exit(1)
