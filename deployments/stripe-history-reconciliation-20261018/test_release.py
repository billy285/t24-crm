"""Local release guards only. No Docker, production DB, or network operations."""
import copy,hashlib,importlib.util,json,sqlite3,types
from pathlib import Path
from types import SimpleNamespace
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

DIRECTORY=Path(__file__).resolve().parent
REPO=DIRECTORY.parents[1]
def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
release=module(DIRECTORY/'release.py','handoff_release_test')

@pytest.fixture
def retained(monkeypatch):
 path=DIRECTORY.parent/'sales-dossier-20261016/release.py';body=path.read_bytes()
 assert release.H(body)==release.RETAINED_SHA
 old=module(path,'handoff_retained_test');release.configure(old)
 actual_read=release.read
 def read(path,expected=None):
  if path==release.RETAINED:
   assert expected==release.RETAINED_SHA
   return body
  return actual_read(path,expected)
 monkeypatch.setattr(release,'read',read);monkeypatch.setattr(release,'_D',old);return old

@pytest.fixture
def database(tmp_path):
 path=tmp_path/'crm.db';con=sqlite3.connect(path)
 con.executescript("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL); INSERT INTO alembic_version VALUES ('c0f4a8d6e123'); CREATE TABLE subscriptions(id INTEGER PRIMARY KEY); INSERT INTO subscriptions VALUES (1); CREATE TABLE customers(id INTEGER PRIMARY KEY); INSERT INTO customers VALUES (1); CREATE TABLE payments(id INTEGER PRIMARY KEY); INSERT INTO payments VALUES (1); CREATE TABLE old_business(id INTEGER PRIMARY KEY, amount FLOAT, note TEXT); INSERT INTO old_business VALUES (1,420.5,'keep'); CREATE INDEX old_amount ON old_business(amount); CREATE TRIGGER old_guard BEFORE UPDATE ON old_business BEGIN SELECT 1; END; CREATE VIEW old_view AS SELECT id FROM old_business;")
 con.close();return path

def upgrade(path):
 migration=module(REPO/'app/backend'/release.MIGRATION,'handoff_exact_migration_test')
 assert migration.revision==release.NEW_REVISION and migration.down_revision==release.OLD_REVISION
 engine=sa.create_engine('sqlite:///'+str(path))
 with engine.connect() as con:
  con.exec_driver_sql('BEGIN IMMEDIATE')
  with Operations.context(MigrationContext.configure(con)):migration.upgrade()
  con.exec_driver_sql("UPDATE alembic_version SET version_num='d1a5b9e7f234'");con.commit()
 engine.dispose()

def test_preflight_pins_match_exact_verified_proof():
 path=REPO/'outputs/stripe-history-reconciliation-20261018/preflight.json'
 if release.LIVE_PREFLIGHT_SHA=='UNFROZEN':pytest.skip('fresh authenticated preflight not yet frozen')
 body=path.read_bytes();p=json.loads(body)
 assert release.H(body)==release.LIVE_PREFLIGHT_SHA
 assert p['crm']['id']==release.OLD_ID and p['crm']['image']==release.BASE_IMAGE and p['crm']['config']==release.OLD_CONFIG
 assert p['schema_revision']==release.OLD_REVISION and p['schema_sha256']==release.OLD_SCHEMA_SHA
 assert p['backend_inventory_sha256']==release.BASE_BACKEND_SHA and p['public_inventory_sha256']==release.OLD_STATIC_SHA
 assert tuple(p['business_identity'][k] for k in ('device','inode'))==release.BUSINESS_IDENTITY
 assert p['readonly'] is True and p['database_modified'] is False and p['services_modified'] is False

def test_exact_additive_migration_preserves_rows_indexes_triggers_views(retained,database):
 before=retained.sql_snapshot(database);objects=release.schema_objects(database);upgrade(database)
 retained.original_rows_unchanged(before,retained.sql_snapshot(database,before));retained.verify_sales_schema(database,True)
 release.additive_objects(objects,release.schema_objects(database))
 assert len(retained.sql_snapshot(database))==len(before)+len(release.NEW_SCHEMA)
 assert release.schema_signature(database,release.NEW_REVISION)

def test_reject_old_row_change(retained,database):
 before=retained.sql_snapshot(database);upgrade(database)
 with sqlite3.connect(database) as con:con.execute('UPDATE old_business SET amount=0')
 with pytest.raises(RuntimeError,match='BUSINESS_ROWS_CHANGED_OLD_BUSINESS'):retained.original_rows_unchanged(before,retained.sql_snapshot(database,before))

@pytest.mark.parametrize('sql',["DROP TRIGGER old_guard","DROP VIEW old_view","CREATE TABLE unapproved(id INTEGER)"])
def test_reject_old_schema_or_unapproved_object(database,sql):
 before=release.schema_objects(database);upgrade(database)
 with sqlite3.connect(database) as con:con.execute(sql)
 with pytest.raises(RuntimeError,match='SCHEMA_OBJECT'):release.additive_objects(before,release.schema_objects(database))

def test_reject_seeded_new_history_policy_table(retained,database):
 before=retained.sql_snapshot(database);upgrade(database)
 fields=release.NEW_SCHEMA['stripe_history_policy'];values={p:(1 if definition[0] in ('INTEGER','FLOAT') else '{}') for p,definition in fields.items() if definition[1] and p!='id'}
 with sqlite3.connect(database) as con:con.execute('INSERT INTO stripe_history_policy('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',list(values.values()))
 with pytest.raises(RuntimeError,match='NEW_SALES_TABLE_NOT_EMPTY'):retained.original_rows_unchanged(before,retained.sql_snapshot(database,before))

def test_reject_new_table_column_drift(retained,database):
 upgrade(database)
 with sqlite3.connect(database) as con:con.execute('ALTER TABLE stripe_history_policy ADD COLUMN secret TEXT')
 with pytest.raises(RuntimeError,match='SALES_TABLE_SCHEMA_DRIFT'):retained.verify_sales_schema(database)

def test_payment_tables_have_only_the_reviewed_restrict_foreign_keys(retained,database):
 upgrade(database);retained.verify_sales_schema(database,True)
 with sqlite3.connect(database) as con:
  for table,expected in release.NEW_FOREIGN_KEYS.items():
   assert con.execute('PRAGMA foreign_key_list('+table+')').fetchall()==expected
 assert release.NEW_FOREIGN_KEYS['stripe_history_postings'][0][6]=='RESTRICT'

def test_foreign_key_drift_rejected(retained,database,monkeypatch):
 upgrade(database);changed=copy.deepcopy(release.NEW_FOREIGN_KEYS);changed['stripe_history_postings'][0]=(*changed['stripe_history_postings'][0][:6],'CASCADE','NONE')
 monkeypatch.setattr(release,'NEW_FOREIGN_KEYS',changed)
 with pytest.raises(RuntimeError,match='SALES_FOREIGN_KEY_DRIFT'):retained.verify_sales_schema(database)

def test_all_seven_new_tables_required_at_new_head_and_absent_at_old_head(retained,database,monkeypatch):
 monkeypatch.setattr(retained,'BUSINESS',database)
 assert retained.committed_revision()==release.OLD_REVISION
 upgrade(database);assert retained.committed_revision()==release.NEW_REVISION
 with sqlite3.connect(database) as con:con.execute('DROP TABLE stripe_history_audits')
 with pytest.raises(RuntimeError,match='AUDIT_MIGRATION_REVISION_MISMATCH'):retained.committed_revision()

def test_reject_wrong_revision(database):
 with pytest.raises(RuntimeError,match='SCHEMA_REVISION_DRIFT'):release.schema_signature(database,release.NEW_REVISION)

def original_runtime():
 return {'Id':'old'*21+'a','Image':release.BASE_IMAGE,'RestartCount':0,'State':{'StartedAt':'stable','Running':True},
  'Config':{'Image':release.BASE_IMAGE,'Hostname':'oldhost','Labels':{'old':'label'},'Env':['A=one','B=two'],'Cmd':['python','main.py']},
  'HostConfig':{'AutoRemove':False,'NetworkMode':'production','RestartPolicy':{'Name':'unless-stopped'}},
  'Mounts':[{'Type':'bind','Source':'/data','Destination':'/app/backend/data','RW':True},{'Type':'bind','Source':'/logs','Destination':'/app/backend/logs','RW':True}],
  'NetworkSettings':{'Networks':{'production':{'Aliases':['t24-crm','old'*21+'a'],'NetworkID':'ephemeral'}}}}

def candidate_runtime(original):
 candidate=copy.deepcopy(original);candidate['Config'].update(Image='sha256:'+'a'*64,Hostname='',Labels=release.clone_config('image',original)['Labels'])
 candidate['HostConfig']['Binds']=release.clone_config('image',original)['HostConfig']['Binds']
 candidate['Mounts'].append({'Type':'bind','Source':str(release.SECRET_HOST),'Destination':release.SECRET_TARGET,'Mode':'ro','RW':False,'Propagation':'rprivate'})
 return candidate

def test_clone_preserves_original_configuration_with_exact_readonly_addition(retained,monkeypatch):
 original=original_runtime();candidate=candidate_runtime(original);candidate['Config'].update(Image='sha256:'+'a'*64,Hostname='',Labels=release.clone_config('image',original)['Labels'])
 release.verify_clone(candidate,original)
 candidate['Mounts'].reverse();release.verify_clone(candidate,original)
 assert original['Config']['Env']==['A=one','B=two']

@pytest.mark.parametrize('field',['env_order','cmd_order','mount_property','network_alias_order','host'])
def test_clone_rejects_real_runtime_changes(retained,field):
 original=original_runtime();candidate=candidate_runtime(original);candidate['Config'].update(Image='newimage',Hostname='',Labels=release.clone_config('newimage',original)['Labels'])
 if field=='env_order':candidate['Config']['Env'].reverse()
 if field=='cmd_order':candidate['Config']['Cmd'].reverse()
 if field=='mount_property':candidate['Mounts'][0]['RW']=False
 if field=='network_alias_order':candidate['NetworkSettings']['Networks']['production']['Aliases'].insert(0,'newalias')
 if field=='host':candidate['HostConfig']['NetworkMode']='none'
 with pytest.raises(RuntimeError,match='CONFIGURATION_DRIFT'):release.verify_clone(candidate,original)

def test_migration_only_exact_file_head_atomic_and_no_catalog_seed():
 script=release.migration_script();compile(script,'migration','exec')
 assert release.MIGRATION in script and 'BEGIN IMMEDIATE' in script and 'm.upgrade()' in script
 assert 'result.rowcount==1' in script and 'product_plans' not in script and 'INSERT' not in script
 assert 'alembic upgrade' not in script and release.NEW_REVISION in script and release.OLD_REVISION in script

def test_docker_build_context_excludes_env_database_static_and_other_backend():
 text=release.dockerignore().decode();assert text.startswith('*\n!Dockerfile\n')
 assert '!backend/services\n' in text and '!backend/'+release.MIGRATION+'\n' in text
 assert '**' not in text and 'crm.env' not in text and 'probe-data' not in text and '!static' not in text

@pytest.mark.parametrize('name',['../x','assets/../../x','/assets/a.js','.env','assets/.env','backend/main.py','assets/a.py','assets/secret.json','assets\\x.js'])
def test_reject_static_escape_or_secret(name):assert not release.static_path(name)

@pytest.mark.parametrize('name',['index.html','app-version.json','assets/chunk-123.js','assets/styles-123.css','workbox-abc.js'])
def test_accept_only_public_static(name):assert release.static_path(name)

def test_old_build_forbidden_after_migration_before_any_docker_action(retained,monkeypatch):
 calls=[];monkeypatch.setattr(release,'run',lambda *a,**k:calls.append(a))
 with pytest.raises(RuntimeError,match='OLD_BUILD_FORBIDDEN_AFTER_MIGRATION'):release.restore_crm({}, {}, {},release.NEW_REVISION)
 assert calls==[]

def test_retained_recovery_dispatches_forward_from_actual_committed_head(retained,monkeypatch):
 monkeypatch.setattr(retained,'settle_migration',lambda *a:None);monkeypatch.setattr(retained,'committed_revision',lambda:release.NEW_REVISION)
 calls=[];monkeypatch.setattr(retained,'forward_recover',lambda *a:calls.append(a) or {'database_restored':False})
 result=retained.rollback('release','receipt','manifest','pins','old','next','interrupted')
 assert calls and result['database_restored'] is False

def test_retained_primitives_bound_only_to_new_scope(retained):
 assert retained.BACKEND==release.BACKEND and retained.NEW_TABLES=={table:set(columns) for table,columns in release.NEW_SCHEMA.items()}
 assert retained.ADDITIONS=={} and retained.ADDED_SCHEMA=={} and retained.OLD_REVISION==release.OLD_REVISION
 assert retained.forward_recover is release.forward_recover and retained.current_boundary is release.current_boundary
 assert retained.production_migration_args is release.production_migration_args and retained.restore_crm is release.restore_crm

def test_service_scope_never_targets_private_containers():
 source=(DIRECTORY/'release.py').read_text()
 assert "['docker','stop','-t','30','t24-crm']" in source
 assert 'docker-compose' not in source and 'compose up' not in source and 'restore(' not in source
 assert 'shutil.copyfile' not in source and 't24-private-api' not in source and 't24-private-worker' not in source

def test_unfrozen_source_rejected_before_any_payload_read(monkeypatch,tmp_path):
 monkeypatch.setattr(release,'SOURCE','UNFROZEN');calls=[];monkeypatch.setattr(release,'read',lambda *a:calls.append(a))
 with pytest.raises(RuntimeError,match='FROZEN_SOURCE_VERSION_REQUIRED'):release.checked_manifest(tmp_path,SimpleNamespace())
 assert calls==[]

def test_immutable_command_generation_does_not_generate_activation_without_receipt(tmp_path,monkeypatch):
 generator=module(DIRECTORY/'make_commands.py','handoff_command_test');directory=tmp_path/'package';(directory/'artifacts').mkdir(parents=True)
 source='a'*40;version='b'*12
 proof=tmp_path/'preflight.json';proof.write_bytes(b'{"synthetic_only":true}\n');proof_sha=generator.H(proof.read_bytes())
 manifest={'source_sha':source,'frontend_version':version,'credentials_included':False,'production_seed_rows':False,'preserved':{'private':True}}
 (directory/'release.py').write_bytes(b'pass\n');(directory/'artifacts/manifest.json').write_text(json.dumps(manifest));(directory/'artifacts/payload.tar.gz').write_bytes(b'payload')
 monkeypatch.setattr(generator,'DIRECTORY',str(directory));out=tmp_path/'commands';monkeypatch.setattr(generator.sys if hasattr(generator,'sys') else __import__('sys'),'argv',['generate','--carrier','c'*40,'--out',str(out),'--preflight','/opt/t24-crm/releases/stripe-history-reconciliation-preflight-20261018.json','--preflight-sha256',proof_sha,'--preflight-receipt',str(proof)])
 generator.main();assert not (out/'activate-command.sh').exists() and not (out/'recover-command.sh').exists()
 body=(out/'prepare-command.sh').read_text();compile(body.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0],'generated_prepare','exec')
 assert '--phase' in body and "'prepare'" in body and 'NoRedirect' in body and 'FRESH_RELEASE_REQUIRED' in body
 receipt={'stage':'STRIPE_HISTORY_RECONCILIATION_PREPARED','source_sha':source,'version':version,
  'manifest_sha256':generator.H((directory/'artifacts/manifest.json').read_bytes()),'payload_sha256':generator.H(b'payload'),
  'preflight_sha256':proof_sha}
 receipt_path=tmp_path/'receipt.json';receipt_path.write_text(json.dumps(receipt))
 monkeypatch.setattr(__import__('sys'),'argv',['generate','--carrier','c'*40,'--out',str(out),'--preflight','/opt/t24-crm/releases/stripe-history-reconciliation-preflight-20261018.json','--preflight-sha256',proof_sha,'--preflight-receipt',str(proof),'--prepared-receipt',str(receipt_path)])
 generator.main()
 for phase in ('activate','recover'):
  body=(out/(phase+'-command.sh')).read_text();compile(body.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0],'generated_'+phase,'exec')
  assert generator.H(receipt_path.read_bytes()) in body and 'HELPER_HASH_DRIFT' in body

def test_payload_source_scope_rejects_extra_customer_finance_or_private_change(monkeypatch):
 builder=module(DIRECTORY/'build_payload.py','handoff_builder_test');allowed={'app/backend/'+p for p in release.BACKEND}|{'app/frontend/src/'+p for p in release.FRONTEND}|builder.TESTS
 baseline={p:'old' for p in allowed};source={p:'new' for p in allowed};assert builder.scope(baseline,source)==allowed
 for extra in ('app/backend/services/finance.py','app/backend/routers/customer_access.py','app/frontend/src/pages/PrivateWorkspace.tsx'):
  with pytest.raises(RuntimeError,match='EXACT_SOURCE_SCOPE_REQUIRED'):builder.scope(baseline,{**source,extra:'changed'})

def manifest_fixture(monkeypatch):
 monkeypatch.setattr(release,'SOURCE','a'*40);monkeypatch.setattr(release,'FRONTEND_VERSION','b'*12);monkeypatch.setattr(release,'FINANCE_BODY_SHA','9'*64)
 monkeypatch.setattr(release,'LIVE_PREFLIGHT_SHA','1'*64);monkeypatch.setattr(release,'BASE_BACKEND_SHA','2'*64)
 monkeypatch.setattr(release,'FRONTEND',{'pages/SalesLeads.tsx'});monkeypatch.setattr(release,'TESTS',{'app/backend/tests/test_stripe_history_reconciliation.py'})
 return {'source_sha':release.SOURCE,'baseline_source_sha':release.BASELINE,'frontend_version':release.FRONTEND_VERSION,
  'baseline_frontend_version':release.BASELINE_FRONTEND,'live_preflight_sha256':release.LIVE_PREFLIGHT_SHA,
  'baseline_backend_inventory_sha256':release.BASE_BACKEND_SHA,'payload_sha256':'c'*64,'credentials_included':False,
  'preserved':copy.deepcopy(release.PRESERVED),'old_schema_revision':release.OLD_REVISION,'new_schema_revision':release.NEW_REVISION,
  'additive_tables':sorted(release.NEW_SCHEMA),'production_seed_rows':False,'configuration_extension':copy.deepcopy(release.CONFIG_EXTENSION),'finance_legacy_body_sha256':release.FINANCE_BODY_SHA,'provider_capabilities_sha256':release.PROVIDER_CAPABILITY_SHA,'provisioning_proof_sha256':release.PROVISIONING_PROOF_SHA,
  'backend_before':{p:None for p in release.BACKEND},'backend_after':{p:'d'*64 for p in release.BACKEND},
  'files':{**{'backend/'+p:'d'*64 for p in release.BACKEND},'static/index.html':'e'*64,'static/app-version.json':'f'*64},
  'changed_source_files':sorted({'app/backend/'+p for p in release.BACKEND}|{'app/frontend/src/'+p for p in release.FRONTEND}|release.TESTS)}

@pytest.mark.parametrize('change',['extra_backend','extra_source','private_scope','credentials','seed_prices','wrong_head','extra_table','backend_hash','static_secret','mount_write','mount_path','finance_body'])
def test_manifest_rejects_scope_drift_before_extraction(monkeypatch,tmp_path,change):
 m=manifest_fixture(monkeypatch)
 if change=='extra_backend':m['backend_after']['routers/finance.py']='d'*64
 if change=='extra_source':m['changed_source_files'].append('app/frontend/src/pages/PrivateWorkspace.tsx')
 if change=='private_scope':m['preserved']['private_workspace']=False
 if change=='credentials':m['credentials_included']=True
 if change=='seed_prices':m['production_seed_rows']=True
 if change=='wrong_head':m['new_schema_revision']='unreviewed'
 if change=='extra_table':m['additive_tables'].append('payments')
 if change=='backend_hash':m['files']['backend/main.py']='e'*64
 if change=='mount_write':m['configuration_extension']['read_only_secret_mount']['read_only']=False
 if change=='mount_path':m['configuration_extension']['read_only_secret_mount']['source']='/app/data/key'
 if change=='finance_body':m['finance_legacy_body_sha256']='0'*64
 if change=='static_secret':m['files']['static/.env']='e'*64
 monkeypatch.setattr(release,'read',lambda path,expected=None:json.dumps(m).encode() if path.name=='manifest.json' else b'payload')
 with pytest.raises(RuntimeError):release.checked_manifest(tmp_path,SimpleNamespace(manifest_sha256='0'*64,payload_sha256='c'*64))

def test_manifest_exact_scope_accepted(monkeypatch,tmp_path):
 m=manifest_fixture(monkeypatch);monkeypatch.setattr(release,'read',lambda path,expected=None:json.dumps(m).encode() if path.name=='manifest.json' else b'payload')
 assert release.checked_manifest(tmp_path,SimpleNamespace(manifest_sha256='0'*64,payload_sha256='c'*64))==m


def test_fresh_live_preflight_loader_rejects_old_private_receipt_and_scope_drift(monkeypatch):
 proof=json.loads((REPO/'outputs/stripe-history-reconciliation-20261018/preflight.json').read_bytes())
 monkeypatch.setattr(release,'read',lambda *args:json.dumps(proof).encode())
 assert release.checked_live_preflight(Path('/safe.json'),release.LIVE_PREFLIGHT_SHA)==proof
 with pytest.raises(RuntimeError,match='EXACT_LIVE_PREFLIGHT_REQUIRED'):
  release.checked_live_preflight(Path('/safe.json'),'0'*64)
 for key,value in [('stage','PRIVATE_OLD_PROOF'),('business_table_count',99),('database_modified',True),('private_boundary_verified',False),('public_root','/wrong')]:
  changed={**proof,key:value};monkeypatch.setattr(release,'read',lambda *args,changed=changed:json.dumps(changed).encode())
  with pytest.raises(RuntimeError):release.checked_live_preflight(Path('/safe.json'),release.LIVE_PREFLIGHT_SHA)


def test_receipt_installer_only_protected_exact_file_no_database_or_provider_commands():
 generator=module(DIRECTORY/'make_commands.py','followthrough_receipt_generator_test')
 body=b'{"synthetic_only":true}\n';script=generator.receipt_installer('/opt/t24-crm/releases/stripe-history-reconciliation-preflight-20261018.json',body,generator.H(body))
 embedded=script.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0];compile(embedded,'receipt_installer','exec')
 for required in ('os.O_EXCL','os.O_NOFOLLOW','0o600','info.st_nlink==1','PROTECTED_PARENT_REQUIRED','EXISTING_PROOF_HASH_DRIFT','socket.gethostname()'):
  assert required in script
 for forbidden in ('sqlite3','docker','urllib','crm_prod.db','sales-stripe-webhook-secret'):
  assert forbidden not in script

@pytest.mark.parametrize('drift',['missing','writable','wrong_source','wrong_target','duplicate','propagation','mode','extra_property','extra_bind','lost_original_bind','new_environment','new_mount'])
def test_secret_mount_extension_rejects_every_unapproved_change(retained,drift):
 original=original_runtime();original['HostConfig']['Binds']=['/data:/app/backend/data:rw','/logs:/app/backend/logs:rw']
 candidate=candidate_runtime(original);secret=candidate['Mounts'][-1]
 if drift=='missing':candidate['Mounts'].pop()
 if drift=='writable':secret['RW']=True
 if drift=='wrong_source':secret['Source']='/tmp/key'
 if drift=='wrong_target':secret['Destination']='/run/secrets/wrong'
 if drift=='duplicate':candidate['Mounts'].append(copy.deepcopy(secret))
 if drift=='propagation':secret['Propagation']='rshared'
 if drift=='mode':secret['Mode']='rw'
 if drift=='extra_property':secret['Surprise']='yes'
 if drift=='extra_bind':candidate['HostConfig']['Binds'].append('/foreign:/foreign:ro')
 if drift=='lost_original_bind':candidate['HostConfig']['Binds'].pop(0)
 if drift=='new_environment':candidate['Config']['Env'].append('STRIPE_KEY=synthetic')
 if drift=='new_mount':candidate['Mounts'].append({'Type':'bind','Source':'/foreign','Destination':'/foreign','RW':False})
 with pytest.raises(RuntimeError):release.verify_clone(candidate,original)

@pytest.mark.parametrize('original_binds',[None,[],['/data:/app/backend/data:rw']])
def test_exact_mount_extension_preserves_original_binds_absence_and_order(retained,original_binds):
 original=original_runtime();original['HostConfig']['Binds']=original_binds
 candidate=candidate_runtime(original);release.verify_clone(candidate,original)
 assert candidate['HostConfig']['Binds']==[*(original_binds or []),release.secret_bind()]
 assert original['HostConfig']['Binds']==original_binds

def test_preexisting_secret_mount_rejected_instead_of_silent_reuse(retained):
 original=original_runtime();original['Mounts'].append({'Source':str(release.SECRET_HOST),'Destination':release.SECRET_TARGET})
 with pytest.raises(RuntimeError,match='ORIGINAL_CREDENTIAL_MOUNT_PRESENT'):release.clone_config('new',original)

def test_offline_candidate_has_real_secret_readonly_and_network_disabled(retained,tmp_path):
 args=release.offline_args(tmp_path,tmp_path/'copy','fixed-image')
 assert args[-1]=='fixed-image' and '--network=none' in args and '--read-only' in args
 assert 'AUTOMATION_SCAN_ENABLED=false' in args
 assert args[-3:-1]==['--mount','type=bind,src='+str(release.SECRET_HOST)+',dst='+release.SECRET_TARGET+',readonly']
 assert str(release.SECRET_HOST) not in release.dockerignore().decode()
 assert all('stripe-history-readonly' not in name for name in release.BACKEND)

def credential_fixture(monkeypatch):
 import stat
 info=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_nlink=1,st_size=80,st_dev=1,st_ino=2,st_mtime_ns=3,st_ctime_ns=4)
 directory=SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=0)
 class Protected:
  def __init__(self,name,isdir=False):self.name=name;self.isdir=isdir
  @property
  def parents(self):return [Protected('/protected',True),Protected('/',True)]
  def resolve(self):return self
  def lstat(self):return directory if self.isdir else info
  def __str__(self):return self.name
  def read_bytes(self):raise AssertionError('credential bytes must never be read by release tooling')
 path=Protected('/protected/stripe-history-readonly.key');monkeypatch.setattr(release,'SECRET_HOST',path);monkeypatch.setattr(release,'CREDENTIAL_PROOF',Protected('/protected/proof.json'))
 monkeypatch.setattr(release,'CONFIG_EXTENSION',{'read_only_secret_mount':{'source':str(path),'target':release.SECRET_TARGET,'read_only':True},'environment_changed':False,'network_changed':False,'existing_mounts_preserved':True})
 proof={'stage':'STRIPE_HISTORY_RESTRICTED_CREDENTIAL_PROVISIONED','destination':str(path),'container_destination':release.SECRET_TARGET,'expected_mount_read_only':True,'credential_profile':'restricted_live','root_owner':True,'mode':'0600','existing_file_overwritten':False,'provider_credential_value_exported':False,'provider_credential_hash_exported':False,'ephemeral_transport_removed':True,'provider_requests':False,'expected_stripe_account':'acct_1QxFjbIdE9Gt7xxR','api_account_verified':False}
 monkeypatch.setattr(release,'read',lambda p,*a:json.dumps(proof,sort_keys=True).encode() if p==release.CREDENTIAL_PROOF else (_ for _ in ()).throw(AssertionError('only safe proof may be read')))
 return info,directory,proof

def test_credential_boundary_uses_only_stat_and_safe_proof_never_value_or_hash(monkeypatch):
 info,directory,proof=credential_fixture(monkeypatch);value=release.credential_boundary()
 assert value['credential_content_read'] is False and 'credential_sha256' not in value
 assert value['inode']==info.st_ino and release.credential_boundary(value)==value
 info.st_ino+=1
 with pytest.raises(RuntimeError,match='CREDENTIAL_BOUNDARY_DRIFT'):release.credential_boundary(value)

@pytest.mark.parametrize('drift',['mode','owner','hardlink','empty','oversize','parent_mode','parent_owner','account','target','overwritten','exported','unexpected'])
def test_credential_stat_or_safe_proof_drift_fails_before_mount(monkeypatch,drift):
 info,directory,proof=credential_fixture(monkeypatch)
 if drift=='mode':info.st_mode|=0o004
 if drift=='owner':info.st_uid=1000
 if drift=='hardlink':info.st_nlink=2
 if drift=='empty':info.st_size=0
 if drift=='oversize':info.st_size=4097
 if drift=='parent_mode':directory.st_mode|=0o002
 if drift=='parent_owner':directory.st_uid=1000
 if drift=='account':proof['expected_stripe_account']='acct_wrong'
 if drift=='target':proof['container_destination']='/data/key'
 if drift=='overwritten':proof['existing_file_overwritten']=True
 if drift=='exported':proof['provider_credential_hash_exported']=True
 if drift=='unexpected':proof['secret']='synthetic-must-not-be-retained'
 with pytest.raises(RuntimeError):release.credential_boundary()

def test_finance_body_guard_ignores_only_function_rename_but_rejects_calculation_edit():
 builder=module(DIRECTORY/'build_payload.py','history_finance_body_guard_test')
 before=b'export default function Finance(){ const result=amount-fee; return result; }'
 renamed=b'import X from "./X"; export default function Finance(){return <X/>;} function FinanceWorkspace(){ const result=amount-fee; return result; }'
 changed=renamed.replace(b'amount-fee',b'amount+fee')
 assert builder.finance_body(before,'Finance')==builder.finance_body(renamed,'FinanceWorkspace')
 assert builder.finance_body(before,'Finance')!=builder.finance_body(changed,'FinanceWorkspace')


def test_frozen_finance_legacy_body_hash_matches_baseline_and_current_wrapper():
 builder=module(DIRECTORY/'build_payload.py','history_actual_finance_body_guard_test')
 before=builder.finance_body(builder.git('show',release.BASELINE+':app/frontend/src/pages/Finance.tsx'),'Finance')
 current=builder.finance_body((REPO/'app/frontend/src/pages/Finance.tsx').read_bytes(),release.FINANCE_LEGACY_NAME)
 assert before==current and release.H(before)==release.FINANCE_BODY_SHA
 builder.finance_source_unchanged(builder.git('show',release.BASELINE+':app/frontend/src/pages/Finance.tsx'),(REPO/'app/frontend/src/pages/Finance.tsx').read_bytes())


def test_whole_original_finance_file_protected_including_helpers_outside_body():
 builder=module(DIRECTORY/'build_payload.py','history_whole_finance_guard_test')
 before=builder.git('show',release.BASELINE+':app/frontend/src/pages/Finance.tsx')
 after=(REPO/'app/frontend/src/pages/Finance.tsx').read_bytes()
 assert b'const defaultIncomeTypeLabels' in after
 with pytest.raises(RuntimeError,match='ORIGINAL_FINANCE_SOURCE_CHANGED'):
  builder.finance_source_unchanged(before,after.replace(b'const defaultIncomeTypeLabels',b'const changedIncomeTypeLabels',1))
