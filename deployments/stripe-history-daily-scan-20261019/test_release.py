"""Focused release guards; all external commands and production files forbidden."""
import copy,json,sqlite3,subprocess,types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

def load(path,name):
 m=types.ModuleType(name);m.__file__=str(path);exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__);return m
r=load(Path(__file__).with_name('release.py'),'daily_release')
old=load(Path(__file__).parents[1]/'sales-dossier-20261016/release.py','old_release')

@pytest.fixture(autouse=True)
def no_external(monkeypatch):
 def forbidden(*a,**k):raise AssertionError('EXTERNAL_ACTION_FORBIDDEN')
 monkeypatch.setattr(r,'run',forbidden);monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'check_output',forbidden);monkeypatch.setattr(r,'retained',lambda:old)
 monkeypatch.setattr(r,'LIVE_PREFLIGHT_SHA','3'*64);monkeypatch.setattr(r,'BASE_BACKEND_SHA','4'*64)

def manifest():
 new={'models/stripe_history_daily_scan.py','services/stripe_history_daily_scan.py',r.MIGRATION}
 return {'source_sha':r.SOURCE,'baseline_source_sha':r.BASELINE,'baseline_application_source':r.BASELINE_APPLICATION_SOURCE,'frontend_version':r.FRONTEND_VERSION,'baseline_frontend_version':r.BASELINE_FRONTEND,'schema_revision':r.NEW_REVISION,'old_schema_revision':r.OLD_REVISION,'additive_tables':[r.NEW_TABLE],'production_seed_rows':False,'payload_sha256':'payload','credentials_included':False,'preserved':r.PRESERVED,'backend_only':False,'static_transition':True,'live_preflight_sha256':r.LIVE_PREFLIGHT_SHA,'baseline_backend_inventory_sha256':r.BASE_BACKEND_SHA,'changed_source_files':sorted({'app/backend/'+p for p in r.BACKEND}|{'app/frontend/src/'+p for p in r.FRONTEND}|r.TESTS),'backend_before':{p:None if p in new else '1'*64 for p in r.BACKEND},'backend_after':dict.fromkeys(r.BACKEND,'2'*64),'files':{**{'backend/'+p:'2'*64 for p in r.BACKEND},'static/index.html':'2'*64,'static/app-version.json':'2'*64}}

def args():return SimpleNamespace(manifest_sha256='manifest',payload_sha256='payload')
def manifest_read(monkeypatch,value):monkeypatch.setattr(r,'read',lambda path,*a:json.dumps(value).encode() if path.name=='manifest.json' else b'payload')

def test_exact_additive_allowlist_accepts_three_new_files(monkeypatch,tmp_path):
 value=manifest();manifest_read(monkeypatch,value);assert r.checked_manifest(tmp_path,args())==value

@pytest.mark.parametrize('field,value',[('source_sha','0'*40),('baseline_source_sha','0'*40),('baseline_application_source','0'*40),('frontend_version','bad'),('baseline_frontend_version','bad'),('schema_revision','bad'),('old_schema_revision','bad'),('additive_tables',['payments']),('production_seed_rows',True),('credentials_included',True),('preserved',{}),('backend_only',True),('static_transition',False),('backend_after',{}),('backend_before',{}),('changed_source_files',[]),('files',{}),('live_preflight_sha256','0'*64),('baseline_backend_inventory_sha256','0'*64)])
def test_manifest_rejects_any_scope_or_pin_drift(monkeypatch,tmp_path,field,value):
 m=manifest();m[field]=value;manifest_read(monkeypatch,m)
 with pytest.raises(RuntimeError):r.checked_manifest(tmp_path,args())

@pytest.mark.parametrize('path,value',[('main.py',None),('models/stripe_history_daily_scan.py','1'*64),('services/stripe_history_daily_scan.py','1'*64)])
def test_only_exact_new_files_can_have_null_before_hash(monkeypatch,tmp_path,path,value):
 m=manifest();m['backend_before'][path]=value;manifest_read(monkeypatch,m)
 with pytest.raises(RuntimeError,match='FILE_HASH_PINS_REQUIRED'):r.checked_manifest(tmp_path,args())

def snapshots():
 before={f'table_{i}':{'columns':['id'],'schema':{'id':['INTEGER',1,None,1]},'indexes':{},'count':1,'rows_sha256':'a'*64} for i in range(110)}
 before['alembic_version']={'columns':['version_num'],'schema':{'version_num':['VARCHAR(32)',1,None,1]},'indexes':{},'count':1,'rows_sha256':r.H(json.dumps([r.OLD_REVISION]).encode())}
 after=copy.deepcopy(before);after['alembic_version']['rows_sha256']=r.H(json.dumps([r.NEW_REVISION]).encode());after[r.NEW_TABLE]={'columns':list(r.NEW_SCHEMA),'schema':{},'indexes':{},'count':0,'rows_sha256':r.H(b'')};return before,after

def test_only_version_metadata_and_empty_new_table_can_change():
 before,after=snapshots();r.compare_original_rows(before,after)

@pytest.mark.parametrize('mutation',[lambda a:a['table_0'].update(count=2),lambda a:a['table_0'].update(rows_sha256='b'*64),lambda a:a['table_0'].update(columns=['secret']),lambda a:a['table_0'].update(indexes={'new':1}),lambda a:a.pop('table_0'),lambda a:a.update(other={}),lambda a:a[r.NEW_TABLE].update(count=1),lambda a:a['alembic_version'].update(rows_sha256='wrong')])
def test_old_rows_schema_and_seed_writes_fail_closed(mutation):
 before,after=snapshots();mutation(after)
 with pytest.raises(RuntimeError):r.compare_original_rows(before,after)

def test_schema_delta_can_only_add_single_table():
 old_objects={('table','payments','payments'):'old'};new={**old_objects,('table',r.NEW_TABLE,r.NEW_TABLE):'new'};r.additive_objects(old_objects,new)
 with pytest.raises(RuntimeError):r.additive_objects(old_objects,{**new,('index','extra','payments'):'extra'})
 with pytest.raises(RuntimeError):r.additive_objects(old_objects,{**new,('table','payments','payments'):'changed'})

@pytest.mark.parametrize('fail',[False,True])
def test_actual_migration_is_atomic_additive_and_has_no_seed(monkeypatch,tmp_path,fail):
 import sqlalchemy as sa
 path=tmp_path/'copy.db';c=sqlite3.connect(path);c.execute('CREATE TABLE alembic_version(version_num TEXT NOT NULL)');c.execute('INSERT INTO alembic_version VALUES (?)',(r.OLD_REVISION,));c.execute('CREATE TABLE stripe_history_bindings(id INTEGER PRIMARY KEY)');c.execute('INSERT INTO stripe_history_bindings VALUES(18)');c.commit();c.close();engine=sa.create_engine('sqlite:///'+str(path));migration=Path('app/backend')/r.MIGRATION
 if fail:
  target=tmp_path/'failing.py';target.write_text(migration.read_text()+'\n_original_upgrade=upgrade\ndef upgrade():\n _original_upgrade()\n raise RuntimeError("CONTROLLED_AFTER_DDL_FAILURE")\n');migration=target
 monkeypatch.setattr(r,'MIGRATION',str(migration.resolve()));monkeypatch.setattr(sa,'create_engine',lambda url:engine)
 if fail:
  with pytest.raises(RuntimeError,match='CONTROLLED_AFTER_DDL_FAILURE'):exec(compile(r.migration_script(),'isolated-migration','exec'),{})
 else:exec(compile(r.migration_script(),'isolated-migration','exec'),{})
 c=sqlite3.connect(path);assert c.execute('SELECT id FROM stripe_history_bindings').fetchall()==[(18,)];assert c.execute('SELECT version_num FROM alembic_version').fetchall()==[(r.OLD_REVISION if fail else r.NEW_REVISION,)]
 assert bool(c.execute('SELECT count(*) FROM sqlite_master WHERE name=?',(r.NEW_TABLE,)).fetchone()[0]) is (not fail);c.close()
 if not fail:r.verify_new_schema(path,True)


def test_offline_worker_disabled_with_unchanged_production_clone(monkeypatch,tmp_path):
 image='image';monkeypatch.setattr(old,'offline_args',lambda *a:['docker','run','--network','none','--read-only',image]);values=r.offline_args(tmp_path,tmp_path,image);assert values[-1]==image and values[-3:-1]==['-e','STRIPE_HISTORY_DAILY_SCAN_ENABLED=false'];assert '--read-only' in values and 'none' in values
 r.verify_production_worker_enabled({'Config':{'Env':['EXISTING_SETTING=unchanged']}})
 for override in ('STRIPE_HISTORY_DAILY_SCAN_ENABLED=false','IS_LAMBDA=true'):
  with pytest.raises(RuntimeError,match='PRODUCTION_DAILY_SCAN_DISABLED'):r.verify_production_worker_enabled({'Config':{'Env':[override]}})

def preflight():
 return {'stage':'STRIPE_HISTORY_DAILY_SCAN_AUTHENTICATED_CURRENT_PREFLIGHT','source_sha':r.BASELINE_APPLICATION_SOURCE,'frontend_version':r.BASELINE_FRONTEND,'crm':{'id':r.OLD_ID,'image':r.BASE_IMAGE,'config':r.OLD_CONFIG},'schema_revision':r.OLD_REVISION,'schema_sha256':r.SCHEMA_SHA,'table_count':111,'backend_inventory_sha256':r.BASE_BACKEND_SHA,'backend_file_count':346,'financial_table_count':42,'current_financial_table_evidence':{t:{'count':191 if t=='payments' else 133,'rows_sha256':'z'*64,'columns':['id']} for t in r.FINANCIAL_TABLES},'current_history_table_evidence':{f'history_{i}':{'count':1,'rows_sha256':'x'*64,'columns':['id']} for i in range(7)},'private_runtime_schema_unchanged':True,'runtime_environment_network_mounts_unchanged':True,'public_static_and_nginx_unchanged':True,'provider_requests':False,'business_rows_modified':False,'credential_values_exported':False}

def test_current_manual_payment_and_posting_baseline_not_hardcoded(monkeypatch,tmp_path):
 p=preflight();monkeypatch.setattr(r,'read',lambda *a:json.dumps(p).encode());assert r.checked_live_preflight(tmp_path,r.LIVE_PREFLIGHT_SHA)==p
 rows={**p['current_financial_table_evidence'],**p['current_history_table_evidence']};monkeypatch.setattr(r,'sql_snapshot',lambda path:rows);assert r.verify_live_rows(p)==rows
 rows['payments']={**rows['payments'],'count':192}
 with pytest.raises(RuntimeError,match='LIVE_PREFLIGHT_ROWS_DRIFT_PAYMENTS'):r.verify_live_rows(p)

def test_retained_helper_cached_but_hash_checked_every_time(monkeypatch):
 actual=load(Path(__file__).with_name('release.py'),'cache_check');reads=[];monkeypatch.setattr(actual,'read',lambda path,expected:reads.append((path,expected)) or b'example=1');first=actual.retained();assert actual.retained() is first and len(reads)==2
 def fail(*a):raise RuntimeError('FILE_HASH_DRIFT')
 monkeypatch.setattr(actual,'read',fail)
 with pytest.raises(RuntimeError,match='FILE_HASH_DRIFT'):actual.retained()

def test_guard_subclass_error_code_is_not_masked():
 class StaticError(RuntimeError):pass
 assert r.safe_error(StaticError('RETAINED_TOOL_MODULE_ALREADY_LOADED'))=='RETAINED_TOOL_MODULE_ALREADY_LOADED';assert r.safe_error(StaticError('value with spaces'))=='STATICERROR'

def test_validation_deadline_precedes_worker_startup(monkeypatch):
 from datetime import datetime,timezone,timedelta
 monkeypatch.setattr(r,'inspect',lambda name:{'State':{'StartedAt':(datetime.now(timezone.utc)-timedelta(seconds=20)).isoformat()}});r.validation_window('candidate')
 monkeypatch.setattr(r,'inspect',lambda name:{'State':{'StartedAt':(datetime.now(timezone.utc)-timedelta(seconds=181)).isoformat()}})
 with pytest.raises(RuntimeError,match='INITIAL_VALIDATION_WINDOW_EXPIRED'):r.validation_window('candidate')

def test_no_prod_env_or_secret_fallback_in_migration_or_offline():
 code=r.migration_script();assert 'BEGIN IMMEDIATE' in code and 'm.upgrade()' in code and 'create_all' not in code and 'downgrade' not in code and r.NEW_REVISION in code and r.OLD_REVISION in code
 assert r.SECRET_TARGET=='/run/secrets/t24_crm_stripe_history_readonly';assert r.NEW_TABLE not in r.PRESERVED

@pytest.mark.parametrize('state',['absent','candidate','old_after_migration'])
def test_recovery_cannot_invent_missing_baseline_after_candidate_or_migration(monkeypatch,tmp_path,state):
 receipt={'manifest_sha256':'manifest','public_inventory_sha256':'public','candidate_image':'candidate'};old_files={'index.html':'a'*64};monkeypatch.setattr(r,'STATIC_SHA',r.digest(old_files));monkeypatch.setattr(r,'tree',lambda path:old_files);monkeypatch.setattr(r,'verify_public',lambda *a:'public');monkeypatch.setattr(r,'private_boundary',lambda *a:None);monkeypatch.setattr(r,'credential_boundary',lambda:None);monkeypatch.setattr(r,'read',lambda path,*a:json.dumps(manifest()).encode());monkeypatch.setattr(r,'settle_migration',lambda *a:None)
 active=None if state=='absent' else {'Id':r.OLD_ID if state=='old_after_migration' else 'candidate','Name':'/t24-crm','Image':r.BASE_IMAGE,'State':{'Running':False}}
 monkeypatch.setattr(r,'inspect_optional',lambda *a:active);monkeypatch.setattr(r,'owned',lambda *a:True);monkeypatch.setattr(r,'inspect',lambda *a:active);monkeypatch.setattr(r,'runtime',lambda *a:{'config':r.OLD_CONFIG});monkeypatch.setattr(r,'current_revision',lambda:r.NEW_REVISION);create=Mock();migrate=Mock();monkeypatch.setattr(r,'docker_create',create);monkeypatch.setattr(r,'migrate',migrate)
 with pytest.raises(RuntimeError,match='FORWARD_PRE_CODE_BASELINE_UNAVAILABLE'):r.rollback(tmp_path,receipt,{}, {},{},'CONTROLLED_FAILURE')
 create.assert_not_called();migrate.assert_not_called();assert not (tmp_path/'production-before-rows.json').exists()


def test_recovery_with_known_baseline_rejects_old_row_drift_before_candidate_action(monkeypatch,tmp_path):
 before,after=snapshots();after['table_0']['rows_sha256']='changed';(tmp_path/'production-before-rows.json').write_text(json.dumps(before));receipt={'manifest_sha256':'manifest','public_inventory_sha256':'public','candidate_image':'candidate','schema_after_sha256':'new_schema'};old_files={'index.html':'a'*64};monkeypatch.setattr(r,'STATIC_SHA',r.digest(old_files));monkeypatch.setattr(r,'tree',lambda path:old_files);monkeypatch.setattr(r,'verify_public',lambda *a:'public');monkeypatch.setattr(r,'private_boundary',lambda *a:None);monkeypatch.setattr(r,'credential_boundary',lambda:None);monkeypatch.setattr(r,'read',lambda path,*a:path.read_bytes() if path.name=='production-before-rows.json' else json.dumps(manifest()).encode());monkeypatch.setattr(r,'settle_migration',lambda *a:None);monkeypatch.setattr(r,'inspect_optional',lambda *a:None);monkeypatch.setattr(r,'current_revision',lambda:r.NEW_REVISION);monkeypatch.setattr(r,'schema_boundary',lambda *a:'new_schema');monkeypatch.setattr(r,'sql_snapshot',lambda *a:after);create=Mock();monkeypatch.setattr(r,'docker_create',create)
 with pytest.raises(RuntimeError,match='ORIGINAL_FILLED_ROWS_CHANGED'):r.rollback(tmp_path,receipt,{}, {},{},'CONTROLLED_FAILURE')
 create.assert_not_called()

@pytest.mark.parametrize('value',[0,5,179,299,301])
def test_candidate_rejects_any_unreviewed_initial_worker_delay(value):
 with pytest.raises(RuntimeError,match='REVIEWED_STARTUP_DELAY_REQUIRED'):r.verify_startup_delay(('STARTUP_DELAY_SECONDS='+str(value)).encode())

def test_exact_worker_delay_is_reviewed_and_not_runtime_env_mutation():
 r.verify_startup_delay(b'STARTUP_DELAY_SECONDS=300')
