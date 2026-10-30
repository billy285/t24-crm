"""Publisher bounds use synthetic SQLite only; no provider/server credentials."""
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('management_publisher', HERE / 'release.py')
r = importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
spec = importlib.util.spec_from_file_location('management_builder', HERE / 'build_payload.py')
b = importlib.util.module_from_spec(spec);spec.loader.exec_module(b)


def snapshot(path, projection=None):
    con = sqlite3.connect(path); result = {}
    try:
        for table, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            columns = list(con.execute('PRAGMA table_info("' + table + '")'))
            names = [row[1] for row in columns]; wanted = projection[table]['columns'] if projection and table in projection else names
            rows = sorted(json.dumps(list(row), ensure_ascii=True) for row in con.execute('SELECT ' + ','.join('"'+name+'"' for name in wanted) + ' FROM "' + table + '"'))
            indexes = {row[1]: [row[2], row[3], row[4], [item[2] for item in con.execute('PRAGMA index_info("' + row[1] + '")')]] for row in con.execute('PRAGMA index_list("' + table + '")')}
            result[table] = {'columns': names, 'schema': {row[1]: list(row[2:]) for row in columns}, 'indexes': indexes, 'count': len(rows), 'rows_sha256': r.H('\n'.join(rows).encode())}
        return result
    finally: con.close()


def objects(path):
    with sqlite3.connect(path) as con:
        return {(row[0], row[1], row[2]): row[3] for row in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}


def create_db(tmp_path, sequence=True):
    path = tmp_path/'synthetic.db'
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('old_google', REPO/'app/backend/alembic/versions/c8d3e5f6a702_google_business.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    engine = sa.create_engine('sqlite:///'+str(path))
    with engine.begin() as con:
        with Operations.context(MigrationContext.configure(con)): old.upgrade()
        con.exec_driver_sql("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)")
        con.exec_driver_sql("INSERT INTO alembic_version VALUES('c8d3e5f6a702')")
        con.exec_driver_sql("CREATE TABLE financial_canary(id INTEGER PRIMARY KEY,amount NUMERIC)")
        con.exec_driver_sql("INSERT INTO financial_canary VALUES(1,198)")
        con.exec_driver_sql("CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY,scopes TEXT)")
        con.exec_driver_sql("INSERT INTO customer_access_grants VALUES(1,'OWNER_INVITATION_UNCHANGED')")
        con.exec_driver_sql("CREATE VIEW original_view AS SELECT id FROM financial_canary")
        con.exec_driver_sql("INSERT INTO google_business_connections(id,owner_id,label,token_encrypted) VALUES(1,1,'Existing','ENCRYPTED_PRIVATE_TOKEN')")
        con.exec_driver_sql("INSERT INTO google_business_oauth_states(id,state_hash,cookie_hash,owner_id,verifier_encrypted,expires_at) VALUES(1,'STATE_HASH','COOKIE_HASH',1,'SEALED_VERIFIER','2026-11-01')")
        con.exec_driver_sql("INSERT INTO google_business_bindings(id,customer_id,customer_name,connection_id,location_name,location_id,title,created_by_id,request_id) VALUES(1,10,'Merchant',1,'accounts/1/locations/2','2','Merchant',1,'11111111-1111-1111-1111-111111111111')")
        con.exec_driver_sql("INSERT INTO google_business_grants(binding_id,employee_id,can_reply,granted_by_id) VALUES(1,2,1,1)")
        con.exec_driver_sql("INSERT INTO google_business_actions(binding_id,customer_id,kind,request_id,fingerprint,actor_id,actor_name,status) VALUES(1,10,'post_publish','22222222-2222-2222-2222-222222222222','HASH',2,'Operator','succeeded')")
        if sequence:
            con.exec_driver_sql("CREATE TABLE old_sequence(id INTEGER PRIMARY KEY AUTOINCREMENT,label TEXT)")
            con.exec_driver_sql("INSERT INTO old_sequence(id,label) VALUES(42,'keep')")
    engine.dispose();return path


def code(path):
    return r.migration_script().replace('/app/backend/'+r.MIGRATION, str(REPO/'app/backend'/r.MIGRATION)).replace('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true', 'sqlite:///file:'+str(path)+'?mode=rw&uri=true')


@pytest.mark.parametrize('sequence', [False, True])
def test_actual_migration_projects_all_original_google_and_financial_values_and_metadata(tmp_path, sequence):
    path=create_db(tmp_path, sequence); before=snapshot(path); original=objects(path)
    with sqlite3.connect(path) as con:
        oldseq = con.execute('SELECT * FROM sqlite_sequence').fetchall() if sequence else []
    exec(compile(code(path),'synthetic-migration','exec'), {})
    after=snapshot(path, before);r.NEW_OBJECTS=set(objects(path))-set(original)
    r.compare_original_rows(before, after);r.additive_objects(original, objects(path))
    assert len(r.NEW_TABLES)==5 and all(after[name]['count']==0 for name in r.NEW_TABLES)
    assert len([key for key in r.NEW_OBJECTS if key[0]=='index'])==6
    with sqlite3.connect(path) as con:
        assert con.execute('SELECT token_encrypted FROM google_business_connections').fetchone()[0]=='ENCRYPTED_PRIVATE_TOKEN'
        assert con.execute('SELECT * FROM sqlite_sequence').fetchall()==oldseq if sequence else con.execute("SELECT count(*) FROM sqlite_master WHERE name='sqlite_sequence'").fetchone()[0]==0


@pytest.mark.parametrize('target', ['financial_canary', 'customer_access_grants', 'google_business_connections', 'google_business_oauth_states', 'google_business_bindings', 'google_business_grants', 'google_business_actions'])
def test_any_original_row_change_fails_even_with_added_columns(tmp_path, target):
    path=create_db(tmp_path);before=snapshot(path);exec(code(path),{});after=snapshot(path,before)
    after[target]['rows_sha256']='changed'
    with pytest.raises(RuntimeError, match='ORIGINAL_PROJECTED_ROWS_CHANGED'):r.compare_original_rows(before,after)


def test_added_columns_cannot_replace_old_columns_or_accept_unreviewed_columns(tmp_path):
    path=create_db(tmp_path);before=snapshot(path);exec(code(path),{});after=snapshot(path,before)
    after['google_business_bindings']['columns'].append('unreviewed')
    with pytest.raises(RuntimeError,match='UNAPPROVED_COLUMN_CHANGE'):r.compare_original_rows(before,after)


def test_mid_migration_failure_rolls_back_ddl_head_and_old_rows(tmp_path):
    path=create_db(tmp_path);before=snapshot(path);old=objects(path)
    script=code(path).replace('with Operations.context(MigrationContext.configure(c)):m.upgrade()', 'with Operations.context(MigrationContext.configure(c)):m.upgrade()\n raise RuntimeError("INJECTED")')
    with pytest.raises(RuntimeError):exec(script,{})
    assert snapshot(path)==before and objects(path)==old


def manifest_context(monkeypatch):
    monkeypatch.setattr(r,'SOURCE_SHA','a'*40);monkeypatch.setattr(r,'SOURCE_FILES',frozenset('app/backend/'+n for n in r.BACKEND_FILES))
    obj=r.Release.__new__(r.Release);before={n:'1'*64 if n in r.EXISTING_BACKEND_FILES else None for n in r.BACKEND_FILES};after={n:'2'*64 for n in r.BACKEND_FILES}
    obj.args=SimpleNamespace(preflight_sha256='3'*64,payload_sha256='4'*64)
    names=['table_'+str(i) for i in range(124)]
    obj.proof={'stage':'MEDIA_OPS_MANAGEMENT_READONLY_PREFLIGHT','host':r.HOST,'source_sha':r.BASE_SOURCE,'frontend_version':r.BASE_FRONTEND,'schema_revision':r.OLD_REVISION,'provider_requests':False,'business_writes':False,'container_or_configuration_changed':False,'credential_content_read':False,'customer_records_exported':False,'private_boundary_verified':True,'backend_inventory_sha256':'5'*64,'backend_changed_before':before,'gbp_feature_enabled':True,'scheduler_disabled':True,'enabled_receipt_sha256':r.BASE_ENABLED_SHA,'rows':{n:{} for n in names},'original_columns':{n:['id'] for n in names},'callback_logging_protection_retained':True,'active_nginx_config_sha256':'6'*64}
    obj.manifest={'source_sha':r.SOURCE_SHA,'frontend_version':'7'*12,'changed_source_files':sorted(r.SOURCE_FILES),'baseline_source_sha':r.BASE_SOURCE,'baseline_frontend_version':r.BASE_FRONTEND,'preflight_sha256':'3'*64,'payload_sha256':'4'*64,'old_schema_revision':r.OLD_REVISION,'schema_revision':r.NEW_REVISION,'additive_tables':sorted(r.NEW_TABLES),'additive_objects':[['table',n,n] for n in r.NEW_TABLES],'production_seed_rows':False,'credentials_included':False,'preserved':copy.deepcopy(r.PRESERVED),'backend_before':before,'backend_after':after,'files':{**{'backend/'+n:v for n,v in after.items()},'static/index.html':'8'*64,'static/app-version.json':'8'*64}}
    obj.m=SimpleNamespace(static_path=lambda x:x in {'index.html','app-version.json'})
    return obj


def test_complete_exact_positive_manifest_control_reaches_all_gates(monkeypatch):
    manifest_context(monkeypatch).validate_manifest()


@pytest.mark.parametrize('change', [lambda o:o.proof.update(scheduler_disabled=False),lambda o:o.proof.update(gbp_feature_enabled=False),lambda o:o.proof.update(enabled_receipt_sha256='f'*64),lambda o:o.proof.update(provider_requests=True),lambda o:o.manifest.update(production_seed_rows=True),lambda o:o.manifest['backend_after'].update({'routers/payments.py':'f'*64}),lambda o:o.manifest['changed_source_files'].append('app/backend/services/customer_permissions.py'),lambda o:o.manifest['additive_objects'].append(['trigger','bad','financial_canary']),lambda o:o.proof['original_columns'].pop('table_1')])
def test_manifest_mutations_reject_after_real_positive_source_pin(monkeypatch,change):
    obj=manifest_context(monkeypatch);obj.validate_manifest();change(obj)
    with pytest.raises(RuntimeError):obj.validate_manifest()


def test_offline_arguments_never_use_production_env_file_secrets_mount_or_enabled_worker(tmp_path):
    obj=r.Release.__new__(r.Release);obj.args=SimpleNamespace(release=tmp_path)
    args=obj.offline_args(tmp_path/'data','sha256:synthetic')
    assert '--network=none' in args and '--env-file' not in args
    assert not any('/run/secrets' in value or '/opt/t24-crm/secrets' in value for value in args)
    env=[args[i+1] for i,value in enumerate(args[:-1]) if value=='-e']
    r.verify_disabled_environment({'Config':{'Env':env},'HostConfig':{'NetworkMode':'none'}})
    assert 'APP_AI_KEY=' in env and 'OPENAI_API_KEY=' in env
    assert 'T24_GBP_CLIENT_SECRET=' in env and 'T24_GBP_TOKEN_KEY=' in env


def test_candidate_runtime_does_not_normalize_env_mounts_network_or_oom_defaults():
    original={'Config':{'Image':'old','Hostname':'old','Labels':{},'Env':['SECRET=unchanged']},'HostConfig':{'OomKillDisable':False},'Mounts':[],'NetworkSettings':{}}
    new=copy.deepcopy(original);new['Config'].update(Image='new',Hostname='new',Labels={'release':'new'})
    r.normalized_configuration(new,original,lambda row:{'config':r.digest(row)})
    new['HostConfig']['OomKillDisable']=None
    with pytest.raises(RuntimeError):r.normalized_configuration(new,original,lambda row:{'config':r.digest(row)})


def test_static_root_switch_cannot_change_callback_or_any_global_nginx_bytes(tmp_path):
    old='/var/www/t24-crm-public/old';new='/var/www/t24-crm-public/new'
    body=b'server { root '+old.encode()+b'; location = /callback { access_log off; add_header Referrer-Policy no-referrer always; } }'
    active=b'full nginx prefix\n'+body
    site=tmp_path/'nginx';site.write_bytes(body)
    obj=r.Release.__new__(r.Release);obj.public=Path(new);obj.proof={'public_root':old,'nginx_sha256':r.H(body),'active_nginx_config_sha256':r.H(active)}
    obj.m=SimpleNamespace(NGINX=site,run=lambda *a:site.read_bytes().replace(b'server',b'full nginx prefix\nserver',1))
    obj.nginx_boundary();site.write_bytes(body.replace(old.encode(),new.encode()));obj.nginx_boundary(updated=True)
    site.write_bytes(site.read_bytes().replace(b'access_log off',b'access_log /var/log/leak'))
    with pytest.raises(RuntimeError):obj.nginx_boundary(updated=True)


def test_real_current_route_registration_probe_is_offline_and_includes_management_ai():
    script="import socket\ndef blocked(*a,**k):raise AssertionError('NO_NETWORK')\nsocket.socket.connect=blocked\n"+r.route_registration_probe()
    env={**os.environ,'APP_ENV':'test','ENVIRONMENT':'test','ENV':'test','IS_LAMBDA':'true','DATABASE_URL':'sqlite+aiosqlite:///:memory:','STRIPE_AUTO_POSTING_ENABLED':'false','STRIPE_HISTORY_DAILY_SCAN_ENABLED':'false','T24_GBP_SCHEDULER_ENABLED':'false','PYTHONPATH':'.:..:tests','PYTHONDONTWRITEBYTECODE':'1'}
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=REPO/'app/backend',env=env,capture_output=True,timeout=60)
    assert result.returncode==0,'ROUTE_PROBE_FAILED'
    assert len(r.GBP_ROUTES)==33 and len(r.MEDIA_ROUTES)==6


@pytest.mark.parametrize('change', [lambda row:row['Config']['Env'].append('T24_GBP_CLIENT_SECRET=LIVE-SECRET'),lambda row:row['Config']['Env'].append('OPENAI_API_KEY=LIVE-SECRET'),lambda row:row['Config']['Env'].append('T24_GBP_SCHEDULER_ENABLED=true'),lambda row:row['HostConfig'].update(NetworkMode='bridge')])
def test_offline_credential_or_worker_or_network_drift_is_rejected(tmp_path,change):
    obj=r.Release.__new__(r.Release);obj.args=SimpleNamespace(release=tmp_path)
    args=obj.offline_args(tmp_path/'data','image');env=[args[i+1] for i,value in enumerate(args[:-1]) if value=='-e']
    row={'Config':{'Env':env},'HostConfig':{'NetworkMode':'none'}}
    r.verify_disabled_environment(row);change(row)
    with pytest.raises(RuntimeError):r.verify_disabled_environment(row)


def test_active_environment_accepts_only_existing_google_names_and_never_enables_new_worker():
    values={'T24_GBP_ENABLED':'true','T24_GBP_API_APPROVED':'true','T24_GBP_CLIENT_ID':'CLIENT','T24_GBP_CLIENT_SECRET':'SECRET','T24_GBP_TOKEN_KEY':'TOKEN','T24_GBP_PUBLIC_URL':'https://t24-crm.com'}
    row={'Config':{'Env':[k+'='+v for k,v in values.items()]}}
    r.verify_gbp_environment_enabled(row)
    for bad in ('T24_GBP_SCHEDULER_ENABLED=true','T24_GBP_SCHEDULER_ACTIVATION_FROM=2026-11-01T00:00:00Z','T24_GBP_UNREVIEWED=value'):
        with pytest.raises(RuntimeError):r.verify_gbp_environment_enabled({'Config':{'Env':row['Config']['Env']+[bad]}})


def test_large_preflight_installers_are_bounded_hash_pinned_parts_without_business_actions():
    spec=importlib.util.spec_from_file_location('management_commands',HERE/'make_commands.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    body=json.dumps({'schema':os.urandom(40000).hex()}).encode();digest=r.H(body)
    outputs=module.receipt_installers('/opt/t24-crm/releases/media-ops-management-preflight-'+digest[:12]+'.json',body,digest)
    assert len(outputs)>2 and 'receipt-install-command.sh' in outputs
    for name,script in outputs.items():
        assert len(script.encode())<11000 and len(__import__('base64').b64encode(script.encode()))<16000
        ast.parse(script.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0])
        assert digest in script and 'EXACT_ROOT_SERVER_REQUIRED' in script
        assert 'sqlite' not in script and 'docker' not in script and 'urllib' not in script


def test_no_unreviewed_source_can_be_packaged_while_source_pin_pending():
    if r.SOURCE_SHA=='0'*40:
        assert r.SOURCE_FILES==frozenset() and not b.FRONTEND
    else:
        before,after=b.inventory(r.BASE_SOURCE),b.inventory(r.SOURCE_SHA)
        changed={name for name in set(before)|set(after) if before.get(name)!=after.get(name)}
        assert changed==r.SOURCE_FILES=={'app/backend/'+n for n in r.BACKEND_FILES}|{'app/frontend/src/'+n for n in b.FRONTEND}|b.TESTS


@pytest.fixture
def publisher_fixture(tmp_path,monkeypatch):
    import base64
    from urllib.parse import parse_qs,urlsplit
    path=create_db(tmp_path);before=snapshot(path);release=tmp_path/'release';release.mkdir()
    oldroot=tmp_path/'old-public';newroot=tmp_path/'new-public';oldroot.mkdir();newroot.mkdir()
    site=tmp_path/'nginx';body=b'server { root '+str(oldroot).encode()+b'; location = /callback { access_log off; } }';site.write_bytes(body)
    env=['T24_GBP_ENABLED=true','T24_GBP_API_APPROVED=true','T24_GBP_CLIENT_ID=synthetic','T24_GBP_CLIENT_SECRET=synthetic','T24_GBP_TOKEN_KEY=synthetic','T24_GBP_PUBLIC_URL=https://t24-crm.com']
    old={'Id':'1'*64,'Image':'sha256:'+'1'*64,'Name':'/t24-crm','Config':{'Env':env,'Image':'old','Hostname':'old','Labels':{}},'HostConfig':{'OomKillDisable':False},'Mounts':[],'NetworkSettings':{},'State':{'Running':True,'StartedAt':'old'},'RestartCount':0}
    runtime=lambda row:{'id':row['Id'],'image':row['Image'],'config':r.digest({key:row[key] for key in ('Config','HostConfig','Mounts','NetworkSettings')}),'started':row['State']['StartedAt'],'restart':row['RestartCount']}
    inventory={'main.py':'a'*64};expected={'main.py':'b'*64};(release/'backend-original-inventory.json').write_text(json.dumps(inventory))
    proof={'crm':runtime(old),'database_identity':[path.stat().st_dev,path.stat().st_ino],'credential_boundary':{'same':'stripe'},'google_credential_metadata':{'same':'google'},'public_root':str(oldroot),'public_inventory_sha256':r.digest({'root':str(oldroot)}),'nginx_sha256':r.H(body),'active_nginx_config_sha256':r.H(b'global\n'+body),'schema_sha256':'old-schema','rows':r.snapshot_evidence(before)}
    receipt={'candidate_image':'sha256:'+'2'*64,'original_inventory_sha256':r.H((release/'backend-original-inventory.json').read_bytes()),'schema_after_sha256':'new-schema','public_inventory_sha256':'new-static'}
    obj=r.Release.__new__(r.Release);obj.source='a'*40;obj.args=SimpleNamespace(release=release);obj.proof=proof;obj.public=newroot;obj.manifest={};obj.pins={}
    containers={old['Id']:copy.deepcopy(old)};mutations=[];reads=[]
    def optional(name):
        return next((copy.deepcopy(row) for row in containers.values() if row['Id']==name or row['Name']=='/'+name),None)
    def inspect(name):
        value=optional(name);assert value is not None;return value
    def run(args,code,*unused):
        if args==['nginx','-T']:return b'global\n'+site.read_bytes()
        if args[:2]==['docker','diff']:reads.append(tuple(args));return b''
        mutations.append(tuple(args))
        if args[:2]==['docker','stop']:containers[args[-1]]['State']['Running']=False
        elif args[:2]==['docker','start']:containers[args[-1]]['State']['Running']=True
        elif args[:2]==['docker','rename']:containers[args[2]]['Name']='/'+args[3]
        else:raise AssertionError(('unexpected mutation',args))
        return b''
    class DockerConnection:
        def __init__(self,*a,**kw):pass
        def request(self,method,url):
            assert method=='HEAD';self.path=parse_qs(urlsplit(url).query)['path'][0]
        def getresponse(self):return self
        status=200
        def getheader(self,name):return base64.b64encode(json.dumps({'name':self.path.rsplit('/',1)[-1],'mode':(1<<31)|0o755,'linkTarget':''}).encode()).decode()
        def close(self):pass
    def read(p,sha=None):
        blob=Path(p).read_bytes()
        if sha:assert r.H(blob)==sha
        return blob
    m=SimpleNamespace(BUSINESS=path,NGINX=site,inspect=inspect,inspect_optional=optional,runtime=runtime,run=run,read=read,
        credential_boundary=lambda:{'same':'stripe'},tree=lambda p:{'root':str(p)},digest=lambda value:'old-static',verify_public=lambda *a:'new-static',
        verify_secret_mount=lambda *a:None,expected_labels=lambda *a:{'release':'new'},inventory=lambda identity:inventory if identity==old['Id'] else expected,
        schema_signature=lambda p,rev:'old-schema' if rev==r.OLD_REVISION else 'new-schema',ready=lambda *a:None,
        retained=lambda:SimpleNamespace(DockerConnection=DockerConnection,sql_snapshot=lambda p,columns:snapshot(p,columns)))
    obj.m=m;obj.private_boundary=lambda:None;obj.safe=SimpleNamespace(GBP_ENV='google.env',protected_metadata=lambda p:{'same':'google'})
    monkeypatch.setattr(r,'PROJECTION',{name:{'columns':row['columns']} for name,row in before.items()})
    return SimpleNamespace(obj=obj,m=m,original=old,receipt=receipt,expected=expected,containers=containers,mutations=mutations,reads=reads,path=path,release=release,site=site,body=body,inspect=inspect)


def test_recovery_positive_boundary_uses_metadata_and_no_mutation(publisher_fixture):
    f=publisher_fixture
    assert f.obj.recovery_boundary(f.receipt,f.original,f.expected)['Id']==f.original['Id']
    assert not f.mutations


@pytest.mark.parametrize('fault',['inode','stripe','google','nginx','static','original_env','unknown_primary','schema'])
def test_recovery_drift_is_denied_before_first_mutation(publisher_fixture,fault):
    f=publisher_fixture
    if fault=='inode':f.obj.proof['database_identity']=[0,0]
    elif fault=='stripe':f.m.credential_boundary=lambda:{'changed':'stripe'}
    elif fault=='google':f.obj.safe.protected_metadata=lambda p:{'changed':'google'}
    elif fault=='nginx':f.site.write_bytes(f.body.replace(b'access_log off',b'access_log leak'))
    elif fault=='static':f.m.tree=lambda x:{'changed':'static'}
    elif fault=='original_env':f.containers[f.original['Id']]['Config']['Env'].append('UNAPPROVED=value')
    elif fault=='unknown_primary':
        f.containers[f.original['Id']]['Name']='/retained';row=copy.deepcopy(f.original);row.update(Id='3'*64);f.containers[row['Id']]=row
    elif fault=='schema':f.m.schema_signature=lambda *a:'changed-schema'
    with pytest.raises(RuntimeError):f.obj.forward(f.receipt,f.original,f.expected,'SYNTHETIC')
    assert not f.mutations


def test_interruption_before_production_baseline_resumes_only_original_old_head(publisher_fixture):
    f=publisher_fixture;f.containers[f.original['Id']]['State']['Running']=False
    result=f.obj.forward(f.receipt,f.original,f.expected,'INTERRUPTED_BEFORE_BASELINE')
    assert result['stage']=='MEDIA_OPS_MANAGEMENT_PRE_MIGRATION_RESUMED'
    assert f.inspect('t24-crm')['Id']==f.original['Id'] and f.inspect('t24-crm')['State']['Running']
    assert f.mutations==[('docker','start',f.original['Id'])]


def test_prebaseline_recovery_never_starts_old_application_at_new_head(publisher_fixture):
    f=publisher_fixture
    with sqlite3.connect(f.path) as con:con.execute('UPDATE alembic_version SET version_num=?',(r.NEW_REVISION,))
    with pytest.raises(RuntimeError):f.obj.forward(f.receipt,f.original,f.expected,'BAD_NEW_HEAD')
    assert not any(item[:2]==('docker','start') for item in f.mutations)


def test_same_image_labels_are_not_a_substitute_for_durable_candidate_id(publisher_fixture):
    f=publisher_fixture;f.containers[f.original['Id']]['Name']='/retained'
    new=copy.deepcopy(f.original);new.update(Id='2'*64,Image=f.receipt['candidate_image']);new['Config']['Labels']={'release':'new'};f.containers[new['Id']]=new
    with pytest.raises(RuntimeError,match='UNKNOWN_FORWARD_CONTAINER'):f.obj.forward(f.receipt,f.original,f.expected,'UNKNOWN_ID')
    assert not f.mutations
