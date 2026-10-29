"""Publisher safety checks on synthetic SQLite/FastAPI only; no production/provider use."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
spec = importlib.util.spec_from_file_location('media_operations_publisher', ROOT / 'release.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
spec = importlib.util.spec_from_file_location('media_operations_builder', ROOT / 'build_payload.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


def snapshot(path):
    con=sqlite3.connect(path); out={}
    try:
        for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            q='"'+table+'"'; schema=list(con.execute('PRAGMA table_info('+q+')'))
            rows=sorted(json.dumps(list(x), ensure_ascii=True, default=lambda value:bytes(value).hex()) for x in con.execute('SELECT * FROM '+q))
            out[table]={'columns':[x[1] for x in schema], 'schema':schema, 'indexes':list(con.execute('PRAGMA index_list('+q+')')), 'count':len(rows), 'rows_sha256':r.H('\n'.join(rows).encode())}
    finally: con.close()
    return out


def objects(path):
    con=sqlite3.connect(path)
    try:return {(x[0],x[1],x[2]):x[3] for x in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    finally:con.close()


def migration_code(path):
    migration=REPO/'app/backend'/r.MIGRATION
    return r.migration_script().replace('/app/backend/'+r.MIGRATION,str(migration)).replace('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true','sqlite:///file:'+str(path)+'?mode=rw&uri=true')


def fixture_db(tmp_path):
    path=tmp_path/'synthetic.db'; con=sqlite3.connect(path)
    con.executescript("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);INSERT INTO alembic_version VALUES('a8d4e2c6f901');CREATE TABLE payments(id INTEGER PRIMARY KEY,amount NUMERIC);INSERT INTO payments VALUES(7,99);CREATE TABLE employees(id INTEGER PRIMARY KEY,role TEXT);INSERT INTO employees VALUES(1,'super_admin');CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY,grant_value TEXT);INSERT INTO customer_access_grants VALUES(1,'unchanged');CREATE VIEW old_view AS SELECT id FROM payments;CREATE TABLE app_settings(config_key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT);")
    con.execute('INSERT INTO app_settings VALUES (?,?,?)',('role_permissions',json.dumps({'finance':{'dataScope':'self'},'ops':{'pages':['/customers']}}),'unchanged'))
    con.commit();con.close(); return path


def migrated(tmp_path):
    path=fixture_db(tmp_path); before,old_objects=snapshot(path),objects(path)
    exec(compile(migration_code(path),'synthetic-additive-migration','exec'),{})
    r.NEW_OBJECTS=set(objects(path))-set(old_objects)
    return path,before,old_objects


def test_actual_upgrade_exactly_two_empty_tables_five_indexes_all_old_rows_preserved(tmp_path):
    path,before,old_objects=migrated(tmp_path)
    r.compare_original_rows(before,snapshot(path)); r.additive_objects(old_objects,objects(path))
    assert len([x for x in r.NEW_OBJECTS if x[0]=='table'])==2
    assert len([x for x in r.NEW_OBJECTS if x[0]=='index'])==5
    assert {x[2] for x in r.NEW_OBJECTS}==r.NEW_TABLES
    assert snapshot(path)['app_settings']==before['app_settings']
    assert b.migration_objects()==[list(x) for x in sorted(r.NEW_OBJECTS)]


@pytest.mark.parametrize('mutation',[
    lambda x:x['payments'].update(rows_sha256='changed'), lambda x:x['employees'].update(count=2),
    lambda x:x['customer_access_grants'].update(rows_sha256='changed'),lambda x:x['payments'].update(columns=['bad']),
    lambda x:x['media_operation_tasks'].update(count=1),lambda x:x['media_operation_events'].update(count=1),
    lambda x:x.update(unknown={}),lambda x:x.pop('payments'),lambda x:x['alembic_version'].update(rows_sha256='bad'),
    lambda x:x['app_settings'].update(rows_sha256='changed'),lambda x:x['app_settings'].update(count=0),
])
def test_any_old_financial_account_grant_appsetting_row_or_seed_change_blocks(tmp_path,mutation):
    path,before,_=migrated(tmp_path);after=snapshot(path);mutation(after)
    with pytest.raises(RuntimeError):r.compare_original_rows(before,after)


@pytest.mark.parametrize('key',[('view','old_view','old_view'),('index','bad','payments'),('trigger','bad','payments')])
def test_old_schema_view_index_trigger_changes_block(tmp_path,key):
    path,_,before=migrated(tmp_path);after=objects(path);after[key]='bad'
    with pytest.raises(RuntimeError):r.additive_objects(before,after)


def test_migration_mid_ddl_failure_rolls_back_schema_head_and_all_rows(tmp_path):
    path=fixture_db(tmp_path);before,old_objects=snapshot(path),objects(path)
    code=migration_code(path).replace('with Operations.context(MigrationContext.configure(c)):m.upgrade()', 'with Operations.context(MigrationContext.configure(c)):m.upgrade()\n raise RuntimeError("SYNTHETIC_DDL_FAILURE")')
    with pytest.raises(RuntimeError):exec(compile(code,'synthetic-fault-migration','exec'),{})
    assert snapshot(path)==before and objects(path)==old_objects


def test_migration_downgrade_refuses_historical_deletion():
    spec=importlib.util.spec_from_file_location('offline_downgrade',REPO/'app/backend'/r.MIGRATION);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    with pytest.raises(RuntimeError,match='forward migration'):m.downgrade()


def context():
    obj=r.Release.__new__(r.Release);before={n:'a'*64 if n in r.EXISTING_BACKEND_FILES else None for n in r.BACKEND_FILES};after={n:'b'*64 for n in r.BACKEND_FILES}
    obj.args=SimpleNamespace(preflight_sha256='c'*64,payload_sha256='d'*64)
    obj.proof={'stage':'MEDIA_OPERATIONS_READONLY_PREFLIGHT','host':r.HOST,'source_sha':r.BASE_SOURCE,'frontend_version':r.BASE_FRONTEND,'schema_revision':r.OLD_REVISION,'provider_requests':False,'business_writes':False,'container_or_configuration_changed':False,'credential_content_read':False,'customer_records_exported':False,'private_boundary_verified':True,'backend_inventory_sha256':'e'*64,'backend_changed_before':copy.deepcopy(before)}
    obj.manifest={'source_sha':r.SOURCE_SHA,'frontend_version':'2'*12,'baseline_source_sha':r.BASE_SOURCE,'baseline_frontend_version':r.BASE_FRONTEND,'preflight_sha256':'c'*64,'payload_sha256':'d'*64,'old_schema_revision':r.OLD_REVISION,'schema_revision':r.NEW_REVISION,'additive_tables':sorted(r.NEW_TABLES),'additive_objects':[['table',n,n] for n in sorted(r.NEW_TABLES)],'production_seed_rows':False,'credentials_included':False,'preserved':copy.deepcopy(r.PRESERVED),'backend_before':before,'backend_after':after,'changed_source_files':sorted(r.SOURCE_FILES),'files':{**{'backend/'+n:v for n,v in after.items()},'static/index.html':'f'*64,'static/app-version.json':'f'*64}}
    obj.m=SimpleNamespace(static_path=lambda n:n in {'index.html','app-version.json'});return obj


def test_exact_backend_additive_manifest_passes():context().validate_manifest()


@pytest.mark.parametrize('change',[
    lambda o:o.manifest['changed_source_files'].append('app/backend/routers/payments.py'),
    lambda o:o.manifest.update(source_sha='1'*40),
    lambda o:o.manifest['backend_after'].update({'routers/payments.py':'b'*64}),
    lambda o:o.manifest['files'].update({'backend/routers/payments.py':'b'*64}),
    lambda o:o.manifest['files'].update({'static/../key':'b'*64}),
    lambda o:o.manifest.update(production_seed_rows=True),lambda o:o.manifest.update(credentials_included=True),
    lambda o:o.manifest.update(finance_role_configuration={'dataScope':'self'}),
    lambda o:o.manifest['additive_objects'].append(['trigger','bad','payments']),
    lambda o:o.manifest['additive_objects'].append(['index','bad','payments']),
    lambda o:o.proof.update(provider_requests=True),lambda o:o.proof.update(business_writes=True),
    lambda o:o.manifest['preserved'].update(app_settings_and_all_roles_unchanged=False),
])
def test_unapproved_source_ddl_role_or_side_effect_manifest_blocks(change):
    obj=context();change(obj)
    with pytest.raises(RuntimeError):obj.validate_manifest()


@pytest.mark.parametrize('change',[{'HostConfig':{'NetworkMode':'bridge'}},{'Config':{'Env':['STRIPE_AUTO_POSTING_ENABLED=true']}},{'Config':{'Env':[]}}])
def test_offline_requires_network_none_and_both_workers_disabled(change):
    good={'HostConfig':{'NetworkMode':'none'},'Config':{'Env':['STRIPE_AUTO_POSTING_ENABLED=false','STRIPE_HISTORY_DAILY_SCAN_ENABLED=false']}}
    r.verify_disabled_environment(good)
    with pytest.raises(RuntimeError):r.verify_disabled_environment({**good,**change})


def test_runtime_normalization_cannot_change_environment_mounts_or_network():
    original={'Config':{'Image':'old','Hostname':'old','Labels':{},'Env':['same']},'HostConfig':{'Mounts':['same']},'NetworkSettings':{'same':1}};new=copy.deepcopy(original);new['Config'].update(Image='new',Hostname='new',Labels={'scope':'new'});runtime=lambda v:{'config':r.digest(v)}
    r.normalized_configuration(new,original,runtime)
    for field in ['Config','HostConfig','NetworkSettings']:
        bad=copy.deepcopy(new);bad[field]['UNAPPROVED']='changed'
        with pytest.raises(RuntimeError):r.normalized_configuration(bad,original,runtime)


@pytest.mark.parametrize('fault',[None,'missing','duplicate','unknown','method','module'])
def test_route_gate_works_with_nested_lazy_routers_and_rejects_any_scope_change(monkeypatch,fault):
    from fastapi import FastAPI,APIRouter
    import types
    app=FastAPI();inner=APIRouter();routes=sorted(r.MEDIA_ROUTES)
    if fault=='missing':routes.pop()
    if fault=='duplicate':routes.append(routes[0])
    if fault=='unknown':routes.append(('/api/v1/media-operations/unreviewed','POST'))
    if fault=='method':routes[0]=(routes[0][0],'PATCH')
    for number,(path,method) in enumerate(routes):
        def endpoint():return None
        endpoint.__name__='synthetic_'+str(number);endpoint.__module__='routers.unapproved' if fault=='module' else 'routers.media_operations';inner.add_api_route(path,endpoint,methods=[method])
    outer=APIRouter();outer.include_router(inner);app.include_router(outer)
    fake=types.ModuleType('main');fake.app=app;monkeypatch.setitem(sys.modules,'main',fake)
    if fault:
        with pytest.raises(AssertionError):exec(r.route_registration_probe(),{})
    else:exec(r.route_registration_probe(),{})
    assert len(r.MEDIA_ROUTES)==6


def test_actual_main_route_probe_does_not_connect_database_or_network():
    code="""import socket,sqlalchemy as sa
from sqlalchemy.engine import Engine
def forbidden(*args,**kwargs):raise AssertionError('NO_DATABASE_OR_NETWORK_IN_PROBE')
sa.event.listen(Engine,'do_connect',forbidden)
socket.socket.connect=forbidden
"""+r.route_registration_probe()
    env={**os.environ,'APP_ENV':'test','ENVIRONMENT':'test','ENV':'test','IS_LAMBDA':'true','DATABASE_URL':'sqlite+aiosqlite:///:memory:','PRIVATE_DATABASE_URL':'sqlite+aiosqlite:///:memory:','JWT_SECRET_KEY':'synthetic-media-release-route-gate-test','ENFORCE_EMPLOYEE_STATUS':'false','ENFORCE_EMPLOYEE_SESSIONS':'false','STRIPE_HISTORY_DAILY_SCAN_ENABLED':'false','STRIPE_AUTO_POSTING_ENABLED':'false','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':'.:..:tests'}
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=REPO/'app/backend',env=env,capture_output=True,timeout=60)
    assert result.returncode==0,'ACTUAL_MAIN_PROBE_FAILED_'+str(result.returncode)
    assert b'EXACT_MEDIA_ROUTES_REGISTERED' in result.stdout


def test_exact_source_scope_is_only_current_nineteen_files_and_no_protected_module():
    before,after=b.inventory(r.BASE_SOURCE),b.inventory('d70c28dae860598229c7d81299d8a65db016f764')
    changed={n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)}
    exact={'app/backend/'+n for n in r.BACKEND_FILES}|{'app/frontend/src/'+n for n in b.FRONTEND}|b.TESTS
    assert changed==exact and len(changed)==19 and len(r.BACKEND_FILES)==5 and len(b.FRONTEND)==13 and len(b.TESTS)==1
    for name in ['routers/payments.py','services/payments.py','services/role_permissions.py','services/customer_permissions.py','routers/customer_access.py','routers/commissions.py','dependencies/auth.py','main.py','services/schema_readiness.py']:
        full='app/backend/'+name
        if full in before:assert after[full]==before[full]
    assert all('/private' not in n.lower() and '/finance' not in n.lower() for n in changed)


def test_readonly_preflight_has_no_mutation_and_no_redundant_inventory_output():
    text=(ROOT/'preflight.py').read_text()
    assert '"backend_inventory": inventory' not in text and '"backend_inventory_sha256": m.digest(inventory)' in text
    assert all(x not in text for x in ['m.write(','m.backup(','BEGIN IMMEDIATE','docker", "stop','docker", "start'])
    assert 'sys.dont_write_bytecode = True' in text


def test_release_has_atomic_additive_ddl_backup_forward_and_frozen_settings():
    text=(ROOT/'release.py').read_text()
    assert 'BEGIN IMMEDIATE' in r.migration_script()
    assert 'UPDATE app_settings' not in text and 'FINANCE_ROLE' not in text and 'role_projection' not in text
    assert 'def prepare(self)' in text and 'def activate(self)' in text and 'def forward(self,' in text
    assert 'm.backup(m.BUSINESS' in text and 'old_application_started_after_migration": False' in text and 'database_restored": False' in text
    assert 'offline_media_routes_registered' in text and 'new_media_tables_empty' in text
    assert 'actual_frontend_source == expected_frontend_source' in (ROOT/'build_payload.py').read_text()
    assert 'changed == backend_expected | frontend_expected | TESTS' in (ROOT/'build_payload.py').read_text()
    for path in ROOT.glob('*.py'):ast.parse(path.read_bytes(),feature_version=(3,10))


def command_context(tmp_path,monkeypatch,*,prepared=False,carrier_drift=False):
    spec=importlib.util.spec_from_file_location('media_commands',ROOT/'make_commands.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    local=tmp_path/'tools';(local/'artifacts').mkdir(parents=True)
    proof={'stage':'MEDIA_OPERATIONS_READONLY_PREFLIGHT'};proof_body=(json.dumps(proof)+'\n').encode();proof_path=tmp_path/'proof.json';proof_path.write_bytes(proof_body)
    manifest={'source_sha':r.SOURCE_SHA,'frontend_version':'2'*12,'preflight_sha256':r.H(proof_body),'production_seed_rows':False,'credentials_included':False}
    members={'release.py':b'synthetic reviewed release body','artifacts/manifest.json':(json.dumps(manifest)+'\n').encode(),'artifacts/payload.tar.gz':b'synthetic-payload'}
    for name,body in members.items():(local/name).write_bytes(body)
    carrier='3'*40
    def git(args):
        if args[:2]==['git','rev-parse']:return b'changed' if carrier_drift and args[-1].startswith(carrier) else b'same-tree'
        for name,body in members.items():
            if args==['git','show',carrier+':'+module.DIRECTORY+'/'+name]:return body
        raise AssertionError('UNKNOWN_LOCAL_GIT_READ')
    monkeypatch.setattr(module,'ROOT',local);monkeypatch.setattr(module.subprocess,'check_output',git)
    out=tmp_path/'commands';argv=['make_commands.py','--carrier',carrier,'--out',str(out),'--preflight-receipt',str(proof_path)]
    if prepared:
        receipt={'stage':'MEDIA_OPERATIONS_PREPARED_OFFLINE_VERIFIED','source_sha':r.SOURCE_SHA,'frontend_version':manifest['frontend_version'],'preflight_sha256':manifest['preflight_sha256'],'manifest_sha256':r.H(members['artifacts/manifest.json']),'payload_sha256':r.H(members['artifacts/payload.tar.gz'])}
        path=tmp_path/'prepared.json';path.write_text(json.dumps(receipt)+'\n');argv+=['--prepared-receipt',str(path)]
    monkeypatch.setattr(sys,'argv',argv)
    return module,out


def test_command_generation_without_prepared_cannot_create_activate(tmp_path,monkeypatch):
    module,out=command_context(tmp_path,monkeypatch);module.main()
    assert {p.name for p in out.iterdir()}=={'package-pins.json','prepare-command.sh','receipt-install-command.sh'}
    text=(out/'prepare-command.sh').read_text()
    assert 'NoRedirect' in text and 'deployments/media-operations-20261030/' in text
    assert 'FRESH_RELEASE_REQUIRED' in text and 'CARRIER_MEMBER_HASH_DRIFT' in text and 'PROTECTED_PARENT_REQUIRED' in text
    assert '20261026' not in text and 'finance-entry-clerk' not in text
    assert "'--phase','prepare'" in text


def test_command_generation_rejects_different_carrier_application_tree(tmp_path,monkeypatch):
    module,_=command_context(tmp_path,monkeypatch,carrier_drift=True)
    with pytest.raises(RuntimeError,match='CARRIER_APPLICATION_TREE_DRIFT'):module.main()


def test_activate_recover_commands_bind_exact_prepared_helper_and_source(tmp_path,monkeypatch):
    module,out=command_context(tmp_path,monkeypatch,prepared=True);module.main()
    pins=json.loads((out/'package-pins.json').read_text())
    for phase in ['activate','recover']:
        text=(out/(phase+'-command.sh')).read_text()
        assert pins['prepared_sha256'] in text and pins['files']['release.py'][1] in text
        assert pins['release'] in text and 'HELPER_HASH_DRIFT' in text and '--review-sha256' in text
        assert 'media-operations-' in text and '20261030' in text


def test_generated_readonly_command_embeds_exact_current_preflight():
    import base64,zlib
    text=(ROOT/'preflight-command.sh').read_text();tree=ast.parse(text.split("<<'MEDIA_OPERATIONS_READONLY'\n",1)[1].rsplit('\nMEDIA_OPERATIONS_READONLY',1)[0])
    encoded=next(node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str) and len(node.value)>1000)
    body=zlib.decompress(base64.b64decode(encoded));assert body==(ROOT/'preflight.py').read_bytes()
    assert r.H(body) in text and "namespace['main']()" in text
    assert 'finance-entry' not in text and 'MEDIA_OPERATIONS_READONLY' in text


def test_all_seven_actual_business_zones_available_without_network_or_database():
    assert len(r.BUSINESS_ZONES)==7 and len(set(r.BUSINESS_ZONES))==7
    exec(r.timezone_probe(),{})
    text=(ROOT/'release.py').read_text()
    assert 'offline_media_timezones_available' in text and 'OFFLINE_MEDIA_TIMEZONES_UNAVAILABLE' in text
