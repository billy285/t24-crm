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
 con.executescript("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL); INSERT INTO alembic_version VALUES ('f7d1c5a9b027'); CREATE TABLE old_business(id INTEGER PRIMARY KEY, amount FLOAT, note TEXT); INSERT INTO old_business VALUES (1,420.5,'keep'); CREATE INDEX old_amount ON old_business(amount); CREATE TRIGGER old_guard BEFORE UPDATE ON old_business BEGIN SELECT 1; END; CREATE VIEW old_view AS SELECT id FROM old_business;")
 con.close();return path

def upgrade(path):
 migration=module(REPO/'app/backend'/release.MIGRATION,'handoff_exact_migration_test')
 assert migration.revision==release.NEW_REVISION and migration.down_revision==release.OLD_REVISION
 engine=sa.create_engine('sqlite:///'+str(path))
 with engine.connect() as con:
  con.exec_driver_sql('BEGIN IMMEDIATE')
  with Operations.context(MigrationContext.configure(con)):migration.upgrade()
  con.exec_driver_sql("UPDATE alembic_version SET version_num='a8d2e6b4c901'");con.commit()
 engine.dispose()

def test_preflight_pins_match_exact_verified_proof():
 path=REPO/'outputs/sales-unified-handoff-20261016/preflight.json';body=path.read_bytes();p=json.loads(body)
 assert release.H(body)==release.LIVE_PREFLIGHT_SHA
 assert p['crm']['id']==release.OLD_ID and p['crm']['image']==release.BASE_IMAGE and p['crm']['config']==release.OLD_CONFIG
 assert p['schema_revision']==release.OLD_REVISION and p['schema_sha256']==release.OLD_SCHEMA_SHA
 assert p['backend_inventory_sha256']==release.BASE_BACKEND_SHA and p['public_inventory_sha256']==release.OLD_STATIC_SHA
 assert tuple(p['business_identity'][k] for k in ('device','inode'))==release.BUSINESS_IDENTITY
 assert p['catalog']['counts']['plans']==0

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

def test_reject_seeded_new_handoff_table(retained,database):
 before=retained.sql_snapshot(database);upgrade(database)
 fields=release.NEW_SCHEMA['sales_deal_handoffs'];values={p:(1 if definition[0] in ('INTEGER','FLOAT') else '{}') for p,definition in fields.items() if definition[1] and p!='id'}
 with sqlite3.connect(database) as con:con.execute('INSERT INTO sales_deal_handoffs('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',list(values.values()))
 with pytest.raises(RuntimeError,match='NEW_SALES_TABLE_NOT_EMPTY'):retained.original_rows_unchanged(before,retained.sql_snapshot(database,before))

def test_reject_new_table_column_drift(retained,database):
 upgrade(database)
 with sqlite3.connect(database) as con:con.execute('ALTER TABLE sales_deal_handoffs ADD COLUMN secret TEXT')
 with pytest.raises(RuntimeError,match='SALES_TABLE_SCHEMA_DRIFT'):retained.verify_sales_schema(database)

def test_policy_table_is_empty_and_restricts_only_exact_existing_plan_key(retained,database):
 before=retained.sql_snapshot(database);upgrade(database);retained.verify_sales_schema(database,True)
 with sqlite3.connect(database) as con:
  assert con.execute('PRAGMA foreign_key_list(sales_deal_plan_policies)').fetchall()==[(0,0,'product_plans','plan_id','id','NO ACTION','RESTRICT','NONE')]
  con.execute("INSERT INTO sales_deal_plan_policies(plan_id,collection_policy,revision,updated_by_id) VALUES (1,'manual',1,1)")
 with pytest.raises(RuntimeError,match='NEW_SALES_TABLE_NOT_EMPTY'):retained.original_rows_unchanged(before,retained.sql_snapshot(database,before))

def test_policy_foreign_key_drift_rejected(retained,database,monkeypatch):
 upgrade(database);changed=copy.deepcopy(release.NEW_FOREIGN_KEYS);changed['sales_deal_plan_policies'][0]=(0,0,'product_plans','plan_id','id','NO ACTION','CASCADE','NONE')
 monkeypatch.setattr(release,'NEW_FOREIGN_KEYS',changed)
 with pytest.raises(RuntimeError,match='SALES_FOREIGN_KEY_DRIFT'):retained.verify_sales_schema(database)

def test_both_new_tables_required_at_new_head_and_absent_at_old_head(retained,database,monkeypatch):
 monkeypatch.setattr(retained,'BUSINESS',database)
 assert retained.committed_revision()==release.OLD_REVISION
 upgrade(database);assert retained.committed_revision()==release.NEW_REVISION
 with sqlite3.connect(database) as con:con.execute('DROP TABLE sales_deal_plan_policies')
 with pytest.raises(RuntimeError,match='AUDIT_MIGRATION_REVISION_MISMATCH'):retained.committed_revision()

def test_reject_wrong_revision(database):
 with pytest.raises(RuntimeError,match='SCHEMA_REVISION_DRIFT'):release.schema_signature(database,release.NEW_REVISION)

def original_runtime():
 return {'Id':'old'*21+'a','Image':release.BASE_IMAGE,'RestartCount':0,'State':{'StartedAt':'stable','Running':True},
  'Config':{'Image':release.BASE_IMAGE,'Hostname':'oldhost','Labels':{'old':'label'},'Env':['A=one','B=two'],'Cmd':['python','main.py']},
  'HostConfig':{'AutoRemove':False,'NetworkMode':'production','RestartPolicy':{'Name':'unless-stopped'}},
  'Mounts':[{'Type':'bind','Source':'/data','Destination':'/app/backend/data','RW':True},{'Type':'bind','Source':'/logs','Destination':'/app/backend/logs','RW':True}],
  'NetworkSettings':{'Networks':{'production':{'Aliases':['t24-crm','old'*21+'a'],'NetworkID':'ephemeral'}}}}

def test_clone_preserves_configuration_environment_networks_and_mounts(retained,monkeypatch):
 original=original_runtime();candidate=copy.deepcopy(original);candidate['Config'].update(Image='sha256:'+'a'*64,Hostname='',Labels=release.clone_config('image',original)['Labels'])
 release.verify_clone(candidate,original)
 candidate['Mounts'].reverse();release.verify_clone(candidate,original)
 assert original['Config']['Env']==['A=one','B=two']

@pytest.mark.parametrize('field',['env_order','cmd_order','mount_property','network_alias_order','host'])
def test_clone_rejects_real_runtime_changes(retained,field):
 original=original_runtime();candidate=copy.deepcopy(original);candidate['Config'].update(Image='newimage',Hostname='',Labels=release.clone_config('newimage',original)['Labels'])
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
 manifest={'source_sha':source,'frontend_version':version,'credentials_included':False,'production_seed_rows':False,'preserved':{'private':True}}
 (directory/'release.py').write_bytes(b'pass\n');(directory/'artifacts/manifest.json').write_text(json.dumps(manifest));(directory/'artifacts/payload.tar.gz').write_bytes(b'payload')
 monkeypatch.setattr(generator,'DIRECTORY',str(directory));out=tmp_path/'commands';monkeypatch.setattr(generator.sys if hasattr(generator,'sys') else __import__('sys'),'argv',['generate','--carrier','c'*40,'--out',str(out)])
 generator.main();assert not (out/'activate-command.sh').exists() and not (out/'recover-command.sh').exists()
 body=(out/'prepare-command.sh').read_text();compile(body.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0],'generated_prepare','exec')
 assert '--phase' in body and "'prepare'" in body and 'NoRedirect' in body and 'FRESH_RELEASE_REQUIRED' in body
 receipt={'stage':'SALES_UNIFIED_HANDOFF_PREPARED','source_sha':source,'version':version,
  'manifest_sha256':generator.H((directory/'artifacts/manifest.json').read_bytes()),'payload_sha256':generator.H(b'payload'),
  'preflight_sha256':'af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161'}
 receipt_path=tmp_path/'receipt.json';receipt_path.write_text(json.dumps(receipt))
 monkeypatch.setattr(__import__('sys'),'argv',['generate','--carrier','c'*40,'--out',str(out),'--prepared-receipt',str(receipt_path)])
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
 monkeypatch.setattr(release,'SOURCE','a'*40);monkeypatch.setattr(release,'FRONTEND_VERSION','b'*12)
 return {'source_sha':release.SOURCE,'baseline_source_sha':release.BASELINE,'frontend_version':release.FRONTEND_VERSION,
  'baseline_frontend_version':release.BASELINE_FRONTEND,'live_preflight_sha256':release.LIVE_PREFLIGHT_SHA,
  'baseline_backend_inventory_sha256':release.BASE_BACKEND_SHA,'payload_sha256':'c'*64,'credentials_included':False,
  'preserved':copy.deepcopy(release.PRESERVED),'old_schema_revision':release.OLD_REVISION,'new_schema_revision':release.NEW_REVISION,
  'additive_tables':sorted(release.NEW_SCHEMA),'production_seed_rows':False,
  'backend_before':{p:None for p in release.BACKEND},'backend_after':{p:'d'*64 for p in release.BACKEND},
  'files':{**{'backend/'+p:'d'*64 for p in release.BACKEND},'static/index.html':'e'*64,'static/app-version.json':'f'*64},
  'changed_source_files':sorted({'app/backend/'+p for p in release.BACKEND}|{'app/frontend/src/'+p for p in release.FRONTEND}|release.TESTS)}

@pytest.mark.parametrize('change',['extra_backend','extra_source','private_scope','credentials','seed_prices','wrong_head','extra_table','backend_hash','static_secret'])
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
 if change=='static_secret':m['files']['static/.env']='e'*64
 monkeypatch.setattr(release,'read',lambda path,expected=None:json.dumps(m).encode() if path.name=='manifest.json' else b'payload')
 with pytest.raises(RuntimeError):release.checked_manifest(tmp_path,SimpleNamespace(manifest_sha256='0'*64,payload_sha256='c'*64))

def test_manifest_exact_scope_accepted(monkeypatch,tmp_path):
 m=manifest_fixture(monkeypatch);monkeypatch.setattr(release,'read',lambda path,expected=None:json.dumps(m).encode() if path.name=='manifest.json' else b'payload')
 assert release.checked_manifest(tmp_path,SimpleNamespace(manifest_sha256='0'*64,payload_sha256='c'*64))==m
