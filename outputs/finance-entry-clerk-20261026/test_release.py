"""Actual additive migration and publisher boundary tests; synthetic SQLite only."""
import copy,hashlib,importlib.util,json,sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('finance_entry_publisher',ROOT/'release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
def snapshot(path):
 con=sqlite3.connect(path);out={}
 try:
  for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
   q='"'+table+'"';schema=list(con.execute('PRAGMA table_info('+q+')'));rows=sorted(json.dumps(list(x),ensure_ascii=True,default=lambda b:bytes(b).hex()) for x in con.execute('SELECT * FROM '+q))
   out[table]={'columns':[x[1] for x in schema],'schema':schema,'indexes':list(con.execute('PRAGMA index_list('+q+')')),'count':len(rows),'rows_sha256':r.H('\n'.join(rows).encode())}
 finally:con.close()
 if 'app_settings' in out:out['app_settings']['finance_role_projection']=r.role_projection(path)
 return out
def objects(path):
 con=sqlite3.connect(path)
 try:return {(x[0],x[1],x[2]):x[3] for x in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
 finally:con.close()
def migrated(tmp_path,role_row=True):
 path=tmp_path/'synthetic.db';con=sqlite3.connect(path)
 con.executescript("CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);INSERT INTO alembic_version VALUES('f3c7d1a9b456');CREATE TABLE payments(id INTEGER PRIMARY KEY,amount NUMERIC);INSERT INTO payments VALUES(7,99);CREATE TABLE employees(id INTEGER PRIMARY KEY,role TEXT);INSERT INTO employees VALUES(1,'super_admin');CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY,grant_value TEXT);INSERT INTO customer_access_grants VALUES(1,'unaltered');CREATE VIEW original_view AS SELECT id FROM payments;CREATE TABLE app_settings(config_key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT);")
 con.execute('INSERT INTO app_settings VALUES (?,?,?)',('company_info',json.dumps({'name':'Preserved'}),'old'))
 if role_row:con.execute('INSERT INTO app_settings VALUES (?,?,?)',('role_permissions',json.dumps({'finance':{'pages':['/finance'],'dataScope':'all'},'sales':{'pages':['/sales']}}),'old'))
 con.commit();con.close();before,old_objects=snapshot(path),objects(path)
 migration=(ROOT.parents[1]/'app/backend'/r.MIGRATION).resolve()
 code=r.migration_script().replace('/app/backend/'+r.MIGRATION,str(migration)).replace('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true','sqlite:///file:'+str(path)+'?mode=rw&uri=true')
 exec(compile(code,'synthetic-migration','exec'),{})
 after_objects=objects(path);r.NEW_OBJECTS=set(after_objects)-set(old_objects)
 assert {x for x in r.NEW_OBJECTS if x[0]=='table'}=={('table',n,n) for n in r.NEW_TABLES}
 return path,before,old_objects
@pytest.mark.parametrize('role_row',[True,False])
def test_actual_migration_only_three_empty_tables_and_exact_finance_role(tmp_path,role_row):
 path,b,o=migrated(tmp_path,role_row);r.compare_original_rows(b,snapshot(path));r.additive_objects(o,objects(path))
 projection=r.role_projection(path);assert projection['row_present']==role_row
 assert projection['finance']==r.FINANCE_ROLE if role_row else projection['finance'] is None
 con=sqlite3.connect(path);assert con.execute('SELECT * FROM payments').fetchall()==[(7,99)];assert con.execute('SELECT * FROM employees').fetchall()==[(1,'super_admin')];con.close()
@pytest.mark.parametrize('mutation',[lambda x:x['payments'].update(rows_sha256='changed'),lambda x:x['employees'].update(count=2),lambda x:x['customer_access_grants'].update(rows_sha256='changed'),lambda x:x['payments'].update(columns=['bad']),lambda x:x['finance_entry_drafts'].update(count=1),lambda x:x['finance_entry_attachments'].update(count=1),lambda x:x.update(unknown={}),lambda x:x.pop('payments'),lambda x:x['alembic_version'].update(rows_sha256='bad'),lambda x:x['app_settings']['finance_role_projection'].update(other_settings_sha256='bad'),lambda x:x['app_settings']['finance_role_projection'].update(finance={'dataScope':'all'})])
def test_any_old_financial_row_account_permission_or_unapproved_seed_blocks(tmp_path,mutation):
 path,b,_=migrated(tmp_path);a=snapshot(path);mutation(a)
 with pytest.raises(RuntimeError):r.compare_original_rows(b,a)
def test_old_schema_view_index_and_trigger_rejected(tmp_path):
 path,_,b=migrated(tmp_path);a=objects(path)
 for key in [('view','original_view','original_view'),('index','bad','payments'),('trigger','bad','payments')]:
  wrong=copy.deepcopy(a);wrong[key]='bad'
  with pytest.raises(RuntimeError):r.additive_objects(b,wrong)
def test_real_roles_config_guard_detects_other_role_and_setting_changes(tmp_path):
 path,b,_=migrated(tmp_path);con=sqlite3.connect(path);roles=json.loads(con.execute("SELECT value_json FROM app_settings WHERE config_key='role_permissions'").fetchone()[0]);roles['sales']['pages']=[];con.execute("UPDATE app_settings SET value_json=? WHERE config_key='role_permissions'",(json.dumps(roles),));con.commit();con.close()
 with pytest.raises(RuntimeError):r.compare_original_rows(b,snapshot(path))
def test_candidate_offline_cannot_have_network_or_workers():
 good={'HostConfig':{'NetworkMode':'none'},'Config':{'Env':['STRIPE_AUTO_POSTING_ENABLED=false','STRIPE_HISTORY_DAILY_SCAN_ENABLED=false']}};r.verify_disabled_environment(good)
 for changed in [{'HostConfig':{'NetworkMode':'bridge'}},{'Config':{'Env':['STRIPE_AUTO_POSTING_ENABLED=true']}},{'Config':{'Env':[]}}]:
  with pytest.raises(RuntimeError):r.verify_disabled_environment({**good,**changed})
def test_configuration_normalization_does_not_allow_env_mount_or_network_change():
 original={'Config':{'Image':'old','Hostname':'old','Labels':{},'Env':['unchanged']},'HostConfig':{'Mounts':['same']},'NetworkSettings':{'same':1}};new=copy.deepcopy(original);new['Config'].update(Image='new',Hostname='new',Labels={'scope':'new'})
 runtime=lambda v:{'config':r.digest(v)};r.normalized_configuration(new,original,runtime)
 for key in ['Env']:
  bad=copy.deepcopy(new);bad['Config'][key]=['different']
  with pytest.raises(RuntimeError):r.normalized_configuration(bad,original,runtime)
def context():
 obj=r.Release.__new__(r.Release);before={n:'a'*64 if n in r.EXISTING_BACKEND_FILES else None for n in r.BACKEND_FILES};after={n:before[n] if n in r.UNCHANGED_BACKEND_FILES else 'b'*64 for n in r.BACKEND_FILES}
 obj.args=SimpleNamespace(preflight_sha256='c'*64,payload_sha256='d'*64);obj.proof={'stage':'FINANCE_ENTRY_CLERK_READONLY_PREFLIGHT','host':r.HOST,'source_sha':r.BASE_SOURCE,'frontend_version':r.BASE_FRONTEND,'schema_revision':r.OLD_REVISION,'provider_requests':False,'business_writes':False,'container_or_configuration_changed':False,'credential_content_read':False,'customer_records_exported':False,'private_boundary_verified':True,'backend_inventory_sha256':'e'*64,'backend_changed_before':copy.deepcopy(before)}
 obj.manifest={'source_sha':'1'*40,'frontend_version':'2'*12,'baseline_source_sha':r.BASE_SOURCE,'baseline_frontend_version':r.BASE_FRONTEND,'preflight_sha256':'c'*64,'payload_sha256':'d'*64,'old_schema_revision':r.OLD_REVISION,'schema_revision':r.NEW_REVISION,'additive_tables':sorted(r.NEW_TABLES),'additive_objects':[['table',n,n] for n in sorted(r.NEW_TABLES)],'finance_role_configuration':copy.deepcopy(r.FINANCE_ROLE),'production_seed_rows':False,'credentials_included':False,'preserved':copy.deepcopy(r.PRESERVED),'backend_before':before,'backend_after':after,'files':{**{'backend/'+n:v for n,v in after.items()},'static/index.html':'f'*64,'static/app-version.json':'f'*64}}
 obj.m=SimpleNamespace(static_path=lambda n:n in {'index.html','app-version.json'});return obj
def test_exact_backend_ddl_manifest_passes():context().validate_manifest()
@pytest.mark.parametrize('change',[lambda o:o.manifest['backend_after'].update({'routers/payments.py':'b'*64}),lambda o:o.manifest['files'].update({'backend/routers/payments.py':'b'*64}),lambda o:o.manifest['files'].update({'static/../key':'b'*64}),lambda o:o.manifest.update(production_seed_rows=True),lambda o:o.manifest.update(credentials_included=True),lambda o:o.manifest['finance_role_configuration'].update(dataScope='all'),lambda o:o.manifest['additive_objects'].append(['trigger','bad','payments']),lambda o:o.manifest['additive_objects'].append(['index','bad','payments']),lambda o:o.proof.update(provider_requests=True),lambda o:o.proof.update(business_writes=True)])
def test_unknown_source_or_ddl_or_widened_role_manifest_blocks(change):
 obj=context();change(obj)
 with pytest.raises(RuntimeError):obj.validate_manifest()
def test_real_publisher_has_backend_ddl_phases_not_static_only():
 text=(ROOT/'release.py').read_text();assert 'def prepare(self)' in text and 'def activate(self)' in text and 'def forward(self,' in text
 assert 'm.backup(m.BUSINESS' in text and 'database_restored": False' in text and 'old_application_started_after_migration": False' in text
 assert 'STRIPE_AUTO_POSTING_ENABLED=false' in text and 'BEGIN IMMEDIATE' in r.migration_script()

def test_unchanged_model_and_router_discovery_sources_are_byte_pinned():
 obj=context();obj.manifest['backend_after']['main.py']='1'*64;obj.manifest['files']['backend/main.py']='1'*64
 with pytest.raises(RuntimeError,match='UNCHANGED_DISCOVERY_SOURCE_REQUIRED'):obj.validate_manifest()
def test_readonly_preflight_omits_inventory_details_but_retains_exact_digest_and_overlay_pins():
 text=(ROOT/'preflight.py').read_text()
 assert '"backend_inventory": inventory' not in text
 assert '"backend_inventory_sha256": m.digest(inventory)' in text
 assert '"backend_file_count": len(inventory)' in text
 assert '"backend_changed_before"' in text
 assert all(x not in text for x in ['m.write(', 'm.backup(', 'docker", "stop', 'docker", "start', 'BEGIN IMMEDIATE'])
 assert 'sys.dont_write_bytecode = True' in text
def test_builder_requires_changes_without_forcing_unchanged_discovery_files():
 spec=importlib.util.spec_from_file_location('finance_entry_builder',ROOT/'build_payload.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
 assert 'app/backend/tests/test_config_and_audit_permissions.py' in b.TESTS
 assert 'app/backend/tests/test_customer_permission_boundaries.py' in b.TESTS
 assert 'app/frontend/tests/customer-access-workflow.test.mjs' in b.TESTS
 text=(ROOT/'build_payload.py').read_text()
 assert '(backend_expected - unchanged_backend) <= changed' in text and 'not changed & unchanged_backend' in text

@pytest.mark.parametrize('fault', ['after_additive_ddl','invalid_roles_json'])
def test_additive_migration_failure_rolls_back_schema_head_and_config(tmp_path,fault):
 path=tmp_path/'migration-fault.db';con=sqlite3.connect(path)
 con.executescript("CREATE TABLE alembic_version(version_num TEXT);INSERT INTO alembic_version VALUES('f3c7d1a9b456');CREATE TABLE app_settings(config_key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT);")
 con.execute('INSERT INTO app_settings VALUES (?,?,?)',('role_permissions','invalid' if fault=='invalid_roles_json' else json.dumps({'finance':{'dataScope':'all'},'sales':{'dataScope':'self'}}),'before'));con.commit();con.close()
 def raw_state():
  c=sqlite3.connect(path)
  try:return list(c.iterdump())
  finally:c.close()
 before,old_objects=raw_state(),objects(path)
 migration=(ROOT.parents[1]/'app/backend'/r.MIGRATION).resolve()
 code=r.migration_script().replace('/app/backend/'+r.MIGRATION,str(migration)).replace('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true','sqlite:///file:'+str(path)+'?mode=rw&uri=true')
 if fault=='after_additive_ddl':code=code.replace('with Operations.context(MigrationContext.configure(c)):m.upgrade()','with Operations.context(MigrationContext.configure(c)):m.upgrade()\n raise RuntimeError("SYNTHETIC_DDL_FAULT")')
 with pytest.raises(Exception):exec(compile(code,'synthetic-failure-migration','exec'),{})
 assert raw_state()==before and objects(path)==old_objects

def test_frontend_artifact_source_cannot_include_uncommitted_helpers():
 text=(ROOT/'build_payload.py').read_text()
 assert 'actual_frontend_source == expected_frontend_source' in text
 assert 'UNCOMMITTED_FRONTEND_SOURCE_REJECTED' in text

@pytest.mark.parametrize('fault',[None,'missing_route','duplicate_route','unknown_route','wrong_method'])
def test_actual_image_probe_requires_all_thirteen_new_registered_route_methods(monkeypatch,fault):
 import sys,types
 routes=[SimpleNamespace(path=path,methods={method}) for path,method in sorted(r.DRAFT_ROUTES)]
 if fault=='missing_route':routes.pop()
 if fault=='duplicate_route':routes.append(routes[0])
 if fault=='unknown_route':routes.append(SimpleNamespace(path='/api/v1/finance-entry-drafts/unreviewed',methods={'POST'}))
 if fault=='wrong_method':routes[0]=SimpleNamespace(path=routes[0].path,methods={'PATCH'})
 fake=types.ModuleType('main');fake.app=SimpleNamespace(routes=routes);monkeypatch.setitem(sys.modules,'main',fake)
 assert len(r.DRAFT_ROUTES)==13
 if fault:
  with pytest.raises(AssertionError,match='EXACT_DRAFT_ROUTES_NOT_REGISTERED'):exec(r.route_registration_probe(),{})
 else:exec(r.route_registration_probe(),{})
 assert 'offline_draft_routes_registered' in (ROOT/'release.py').read_text()
