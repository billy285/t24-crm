"""Synthetic-only attacks against the aggregate postpilot proof and maker."""
import copy
import ast
import base64
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import zlib
from datetime import datetime,timezone
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
p=load('onboarding_postpilot_tested',HERE/'postpilot.py')
maker=load('onboarding_postpilot_maker_tested',HERE/'make_postpilot.py')
START='2026-11-02T01:00:00.000000000Z'
CREATED='2026-11-02T01:01:00.000000'
OBSERVED='2026-11-02T01:01:02.000000'

def insert(con,table,row):
    con.execute('INSERT INTO '+p.quote(table)+'('+','.join(p.quote(x) for x in row)+') VALUES('+','.join('?' for x in row)+')',tuple(json.dumps(v) if isinstance(v,(dict,list)) else v for v in row.values()))

@pytest.fixture
def fixture(tmp_path):
    path=tmp_path/'synthetic.db';con=sqlite3.connect(path)
    con.execute('CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)');con.execute("INSERT INTO alembic_version VALUES('g32ed456e792')")
    con.execute('CREATE TABLE google_business_connections(id INTEGER PRIMARY KEY,owner_id INTEGER,label TEXT,token_encrypted TEXT,active BOOLEAN,needs_reconnect BOOLEAN,last_error TEXT,connected_at TEXT)')
    for x in (1,2):insert(con,p.CONNECTIONS,{'id':x,'owner_id':1 if x==1 else 2,'label':'not exported','token_encrypted':'opaque-cipher-'+str(x),'active':1,'needs_reconnect':0,'last_error':None,'connected_at':'2026-10-01T00:00:00+00:00'})
    con.execute('CREATE TABLE employees(id INTEGER PRIMARY KEY,role TEXT,status TEXT)');con.execute("INSERT INTO employees VALUES(1,'super_admin','active')")
    special=['customers','google_business_bindings','financial_canary','customer_access_grants','media_monthly_workflows','media_asset_jobs','monthly_deduction_rates']
    for name in special:
        con.execute('CREATE TABLE '+p.quote(name)+'(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT)')
        count=43 if name=='customers' else 15 if name=='google_business_bindings' else 2 if name=='media_asset_jobs' else 1
        con.executemany('INSERT INTO '+p.quote(name)+' VALUES(?,?)',[(x+1,'original-'+name) for x in range(count)])
    for x in range(158-3-len(special)):
        con.execute('CREATE TABLE old_'+str(x)+'(id INTEGER PRIMARY KEY,value TEXT)');con.execute('INSERT INTO old_'+str(x)+" VALUES(1,'original')")
    con.execute('PRAGMA user_version=19');con.execute('PRAGMA application_id=240024');con.commit();con.close()
    migration=load('onboarding_postpilot_actual_migration',HERE.parents[1]/'app/backend/alembic/versions/g32ed456e792_google_business_onboarding.py')
    engine=sa.create_engine('sqlite:///'+str(path))
    try:
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):migration.upgrade()
    finally:engine.dispose()
    con=sqlite3.connect(path);before,oldraw,oldmeta,_,_=p.snapshot(con);before={k:v for k,v in before.items() if k not in p.NEW};before['alembic_version']['rows_sha256']=p.rows_hash([('f21dc345d681',)])
    catalog={'id':'a'*32,'owner_id':1,'connection_id':1,'customer_id':None,'revision':3,'status':'ready','connection_marker':{'id':1,'owner_id':1,'connected_at':'2026-10-01T00:00:00+00:00'},'locations':[{'location_name':'accounts/123/locations/456','title':'Synthetic Shop','address':'1 Example Road, Example, TX 12345','observed_at':OBSERVED}],'truncated':False,'lease_token':None,'lease_at':CREATED,'observed_at':OBSERVED,'expires_at':'2026-11-02T01:11:02.000000','error_code':None,'message':'sanitized','created_at':CREATED,'updated_at':OBSERVED}
    insert(con,p.CAT,catalog);insert(con,p.REQ,{'id':1,'owner_id':1,'request_id':'12345678-1234-4123-8123-123456789012','kind':'discovery','fingerprint':p.digest({'connection_id':1,'customer_id':None}),'resource_id':catalog['id'],'created_at':CREATED});con.commit();con.close()
    return path,before,oldmeta,oldraw[p.CONNECTIONS]

def audit(fixture,*,allow_refresh=False):
    path,before,oldmeta,oldconnections=fixture;con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    trace=[];con.set_trace_callback(trace.append)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN');current,raw,metadata,_,_=p.snapshot(con)
        result=p.audit(before,current,raw,oldmeta,metadata,started=START,old_connections=oldconnections,allow_refresh=allow_refresh)
        assert all(not row.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','REPLACE')) for row in trace)
        return result
    finally:con.close()

def change(fixture,sql,params=()):
    con=sqlite3.connect(fixture[0]);con.execute(sql,params);con.commit();con.close()

def test_exact_single_discovery_preserves158_and_no_preview_or_provider(fixture):
    result=audit(fixture);assert result['original_tables']==158 and result['current_tables']==162 and result['existing_google_bindings']==15 and result['new_batches']==result['new_items']==0 and not result['connection_refresh_columns_changed']

@pytest.mark.parametrize('sql',[
    "UPDATE financial_canary SET value='edited'", "DELETE FROM financial_canary", "INSERT INTO financial_canary VALUES(2,'extra')",
    "UPDATE customer_access_grants SET value='widened'", "UPDATE media_monthly_workflows SET value='approved'", "UPDATE google_business_bindings SET value='changed'", "UPDATE media_asset_jobs SET value='changed'", "UPDATE customers SET value='changed'",
    "ALTER TABLE customers ADD COLUMN unexpected TEXT", "PRAGMA application_id=7", "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='financial_canary'",
    "INSERT INTO sqlite_sequence VALUES('unexpected',9)", "DELETE FROM sqlite_sequence WHERE name='customers'",
])
def test_every_old_row_shape_finance_acl_private_asset_and_counter_change_rejected(fixture,sql):
    change(fixture,sql)
    with pytest.raises(RuntimeError):audit(fixture)

def test_existing_exact_monthly_counter_exception_forward_only(fixture):
    change(fixture,"UPDATE sqlite_sequence SET seq=seq+7 WHERE name='monthly_deduction_rates'");assert audit(fixture)['existing_monthly_rate_counter_forward_only']
    change(fixture,"UPDATE sqlite_sequence SET seq=0 WHERE name='monthly_deduction_rates'")
    with pytest.raises(RuntimeError,match='PROTECTED_SEQUENCE_COUNTER_CHANGED'):audit(fixture)

def test_selected_connection_refresh_requires_exact_old_column_proof(fixture):
    change(fixture,"UPDATE google_business_connections SET token_encrypted='new-opaque' WHERE id=1")
    with pytest.raises(RuntimeError,match='EXPLICIT_OLD_COLUMN_PROOF'):audit(fixture)
    assert audit(fixture,allow_refresh=True)['connection_refresh_allowed_columns']==['last_error','token_encrypted']
    fixture[3][0]['label']='tampered proof'
    with pytest.raises(RuntimeError,match='OLD_CONNECTION_COLUMNS_NOT_BASELINE_BOUND'):audit(fixture,allow_refresh=True)

@pytest.mark.parametrize('sql',[
    "UPDATE google_business_connections SET label='other' WHERE id=1", "UPDATE google_business_connections SET token_encrypted='new' WHERE id=2",
    "UPDATE google_business_connections SET last_error='error' WHERE id=1", "UPDATE google_business_connections SET needs_reconnect=1 WHERE id=1",
    "UPDATE google_business_connections SET owner_id=2 WHERE id=1", "UPDATE google_business_connections SET connected_at='2026-11-02T01:00:00Z' WHERE id=1",
    "DELETE FROM google_business_connections WHERE id=2", "UPDATE google_business_connections SET active=0 WHERE id=1",
])
def test_connection_exception_never_ignores_other_columns_or_other_connections(fixture,sql):
    change(fixture,sql)
    with pytest.raises(RuntimeError):audit(fixture,allow_refresh=True)

@pytest.mark.parametrize('sql',[
    "UPDATE google_business_onboarding_catalogs SET owner_id=2", "UPDATE google_business_onboarding_catalogs SET customer_id=20",
    "UPDATE google_business_onboarding_catalogs SET revision=2", "UPDATE google_business_onboarding_catalogs SET lease_token='still-running'",
    "UPDATE google_business_onboarding_catalogs SET observed_at='2026-11-02T01:04:00Z'", "UPDATE google_business_onboarding_catalogs SET status='unknown'",
    "UPDATE google_business_onboarding_requests SET owner_id=2", "UPDATE google_business_onboarding_requests SET kind='preview'",
    "UPDATE google_business_onboarding_requests SET resource_id='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'", "UPDATE google_business_onboarding_requests SET fingerprint='incorrect'",
    "UPDATE employees SET role='sales'", "UPDATE employees SET status='disabled'",
    "UPDATE google_business_onboarding_catalogs SET locations='[]'", "UPDATE google_business_onboarding_catalogs SET locations='[{\"location_name\":\"accounts/1/locations/2\",\"title\":\"x\",\"address\":\"x\",\"observed_at\":\"2026-11-02T01:01:02Z\",\"token\":\"x\"}]'",
])
def test_wrong_owner_scope_unknown_lease_receipt_or_unsanitized_catalog_rejected(fixture,sql):
    change(fixture,sql)
    with pytest.raises(RuntimeError):audit(fixture)

def test_actual_migration_shapes_match_frozen_release(fixture):
    con=sqlite3.connect(fixture[0])
    try:_,_,_,_,shapes=p.snapshot(con)
    finally:con.close()
    frozen=json.loads((HERE.parents[1]/'outputs/google-business-onboarding-20261102/schema-freeze.json').read_text())
    assert shapes==frozen['table_shapes']

def test_snapshot_matches_frozen_retained_helpers_on_actual162_sqlite(fixture):
    """Independent historic functions, not a self-consistent new auditor pair."""
    oldpath=HERE.parent/'sales-dossier-20261016/release.py'
    assert p.H(oldpath.read_bytes())=='2e1d59d25010cb2141d6c6e25bcb4eaf6bc6cfdfb1015a60d3f8ac6bca5644fe'
    original=load('postpilot_frozen_original_sqlsnapshot',oldpath)
    deployed_m=load('postpilot_frozen_original_schema',HERE.parent/'stripe-history-daily-scan-20261019/release.py')
    metadata_helper=load('postpilot_frozen_original_metadata',HERE.parent/'media-ops-review-refresh-retry-20261031/preflight.py')
    con=sqlite3.connect('file:'+str(fixture[0])+'?mode=ro',uri=True)
    try:current,_,metadata,schema,_=p.snapshot(con)
    finally:con.close()
    assert current==json.loads(json.dumps(original.sql_snapshot(fixture[0])))
    assert schema==deployed_m.schema_signature(fixture[0],p.HEAD)
    assert metadata==metadata_helper.db_metadata(fixture[0])

@pytest.mark.parametrize('table', [p.CAT,p.REQ,p.BATCH,p.ITEM])
def test_no_second_discovery_receipt_or_preview_items_allowed(fixture,table):
    con=sqlite3.connect(fixture[0])
    try:
        if table in {p.CAT,p.REQ}:
            columns=[x[1] for x in con.execute('PRAGMA table_info('+table+')')];row=dict(zip(columns,con.execute('SELECT * FROM '+table).fetchone()))
            row['id']='b'*32 if table==p.CAT else 2
            if table==p.REQ:row['request_id']='87654321-1234-4123-8123-123456789012'
        elif table==p.BATCH:
            row={'id':'b'*32,'owner_id':1,'catalog_id':'a'*32,'customer_id':None,'kind':'batch','status':'preview','revision':1,'preview_hash':'d'*64,'snapshot':{},'expires_at':OBSERVED,'message':'not allowed','created_at':CREATED,'updated_at':OBSERVED}
        else:
            row={'id':'b'*32,'batch_id':'c'*32,'owner_id':1,'position':0,'customer_id':20,'location_name':'accounts/1/locations/2','request_id':'87654321-1234-4123-8123-123456789012','status':'preview','snapshot':{},'warnings':[],'binding_id':None,'lease_token':None,'lease_at':None,'error_code':None,'message':'not allowed','created_at':CREATED,'updated_at':OBSERVED}
        insert(con,table,row);con.commit()
    finally:con.close()
    with pytest.raises(RuntimeError):audit(fixture)

def test_no_executable_command_without_actual_receipts():
    with pytest.raises(RuntimeError,match='ACTUAL_RECEIPT_BYTES_REQUIRED'):maker.generate(None,None)

def synthetic_receipts():
    r=load('postpilot_synthetic_release',HERE/'release.py');encoded=lambda value:(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    prepared={'stage':'GOOGLE_ONBOARDING_PREPARED','source_sha':r.SOURCE_SHA,'frontend_version':r.FRONTEND,'schema_revision':r.NEW_REVISION,'old_schema_revision':r.OLD_REVISION,'original_table_count':158,'new_table_count':162,'additive_tables':sorted(r.NEW_TABLES),'nginx_csp_policy_occurrences':1,'manifest_sha256':maker.H((HERE/'artifacts/manifest.json').read_bytes()),'payload_sha256':maker.H((HERE/'artifacts/payload.tar.gz').read_bytes()),'preflight_sha256':r.ACTUAL_PREFLIGHT_SHA,'runtime_base_image':r.RUNTIME_BASE_IMAGE,'engine_metadata_sha256':r.ENGINE_METADATA_SHA,'retained_renderer_canary_sha256':r.RENDERER_CANARY_SHA,'retained_renderer_result_sha256':'1'*64,'public_root':'/var/www/t24-crm-public/'+r.SCOPE+'-'+r.SOURCE_SHA[:12]+'-20261102','candidate_image':'sha256:'+'2'*64}
    prepared.update({key:True for key in r.PREPARED_TRUE});prepared.update({key:False for key in r.PREPARED_FALSE})
    prepared.update({key:'3'*64 for key in ('schema_after_sha256','original_runtime_sha256','original_inventory_sha256','candidate_inventory_sha256','public_inventory_sha256','nginx_next_sha256')})
    deployed={'stage':'GOOGLE_ONBOARDING_DEPLOYED','source_sha':r.SOURCE_SHA,'frontend_version':r.FRONTEND,'schema_revision':r.NEW_REVISION,'table_count':162,'original_table_count':158,'additive_tables':sorted(r.NEW_TABLES),'prepared_sha256':maker.H(encoded(prepared)),'preflight_sha256':r.ACTUAL_PREFLIGHT_SHA,'schema_sha256':prepared['schema_after_sha256'],'crm':{'id':'4'*64,'config':'5'*64,'image':prepared['candidate_image'],'restart':0,'started':START}}
    deployed.update({key:True for key in ('all158_original_tables_preserved_except_reviewed_schema_head','four_new_onboarding_tables_empty','existing_full_environment_preserved','private_boundary_preserved','content_security_policy_unchanged')})
    deployed.update({key:False for key in ('operations_execution_enabled','operations_scheduler_enabled','database_restored','provider_requests','credentials_journaled','publications_or_ai_generation_executed')})
    return encoded(prepared),encoded(deployed)

def test_maker_bounded_byte_exact_in_memory_only_no_command_written(tmp_path):
    prepared,deployed=synthetic_receipts();command,pins=maker.generate(prepared,deployed)
    assert len(command.encode())<15000 and pins['command_sha256']==maker.H(command.encode()) and pins['executed'] is False
    python=command.split("<<'POSTPILOT'\n",1)[1].rsplit('\nPOSTPILOT',1)[0];tree=ast.parse(python)
    assigns={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'payload','expected','pins'}}
    decoded=zlib.decompress(base64.b64decode(assigns['payload']));assert decoded==(HERE/'postpilot.py').read_bytes() and maker.H(decoded)==assigns['expected']==pins['checker_sha256']
    assert assigns['pins']['runtime']['id']=='4'*64 and assigns['pins']['allow_connection_refresh'] is False and list(tmp_path.iterdir())==[]

@pytest.mark.parametrize('field,value', [('provider_requests',True),('prepared_sha256','0'*64),('source_sha','0'*40),('crm',{'id':'bad'})])
def test_maker_rejects_changed_runtime_source_public_actions_or_receipt(field,value):
    prepared,deployed=synthetic_receipts();value0=json.loads(deployed);value0[field]=value;deployed=(json.dumps(value0,sort_keys=True,indent=2)+'\n').encode()
    with pytest.raises(RuntimeError):maker.generate(prepared,deployed)

def test_canonical_receipt_hash_duplicate_nonfinite_guards():
    value={'stage':'synthetic'};body=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert maker.canonical(body)==(value,maker.H(body))
    envelope=json.dumps({**value,'receipt_sha256':maker.H(body)}).encode();assert maker.canonical(envelope)==(value,maker.H(body))
    for bad in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1}',json.dumps({**value,'receipt_sha256':'0'*64}).encode()):
        with pytest.raises(RuntimeError):maker.canonical(bad)

def test_protected_reader_requires_exact_hash_and_stable_identity(tmp_path,monkeypatch):
    path=tmp_path/'receipt';path.write_bytes(b'known');path.chmod(0o600)
    monkeypatch.setattr(p,'protected',lambda x,**k:x.lstat())
    assert p.read(path,p.H(b'known'))==b'known'
    with pytest.raises(RuntimeError,match='PROTECTED_RECEIPT_CHANGED'):p.read(path,'0'*64)
    original=p.os.fstat;calls=0
    def changed(fd):
        nonlocal calls
        calls+=1;row=original(fd)
        if calls==2:
            path.write_bytes(b'other')
        return row
    monkeypatch.setattr(p.os,'fstat',changed)
    with pytest.raises(RuntimeError,match='PROTECTED_RECEIPT_CHANGED'):p.read(path)

def test_stopped_copy_connection_hash_binding_and_no_writes(fixture,monkeypatch):
    path,before,_,_=fixture;monkeypatch.setattr(p,'protected',lambda x,**k:x.lstat());rowhash=p.H(path.read_bytes())
    rows=p.copy_connections(path,before[p.CONNECTIONS]);assert len(rows)==2 and p.H(path.read_bytes())==rowhash
    changed=copy.deepcopy(before[p.CONNECTIONS]);changed['rows_sha256']='0'*64
    with pytest.raises(RuntimeError,match='OLD_CONNECTION_COPY_BASELINE_HASH_REQUIRED'):p.copy_connections(path,changed)

def test_old_copy_schema_and_metadata_are_also_pinned(fixture,monkeypatch):
    path,before,oldmeta,_=fixture;monkeypatch.setattr(p,'protected',lambda x,**k:x.lstat())
    con=sqlite3.connect(path)
    try:_,_,_,schema,_=p.snapshot(con)
    finally:con.close()
    def check(value):assert value==oldmeta
    p.copy_connections(path,before[p.CONNECTIONS],schema_sha256=schema,metadata_check=check)
    with pytest.raises(RuntimeError,match='OLD_COPY_REVIEWED_SCHEMA_OBJECTS_REQUIRED'):p.copy_connections(path,before[p.CONNECTIONS],schema_sha256='0'*64)
    change(fixture,'PRAGMA application_id=7')
    with pytest.raises(AssertionError):p.copy_connections(path,before[p.CONNECTIONS],metadata_check=check)

def probe_context(*,probe=None,running=None,inspect_error=False):
    root=Path('/opt/t24-crm/releases/google-business-onboarding-r3-8b429dad8a2f-20261102');image='sha256:'+'e'*64
    config={'Image':image,'Cmd':['uvicorn','main:app'],'Entrypoint':None,'WorkingDir':'/app/backend','User':''}
    good={'Name':'/expected-api-probe','Image':image,'Config':config,'State':{'Running':False,'Status':'exited','ExitCode':0},'HostConfig':{'AutoRemove':True,'ReadonlyRootfs':True,'NetworkMode':'none'},'Mounts':[{'Type':'bind','RW':True,'Destination':'/app/backend/data','Source':str(root/'probe-data')},{'Type':'bind','RW':True,'Destination':'/app/backend/logs','Source':str(root/'probe-logs')}]}
    selected=good if probe=='good' else probe
    def request(method,path):
        assert method=='GET'
        if path=='/containers/json?all=0':return 200,json.dumps([] if running is None else running).encode()
        assert path=='/images/'+image+'/json';return 200,json.dumps({'Id':image,'Config':config}).encode()
    def inspect(name):
        assert name=='expected-api-probe'
        if inspect_error:raise RuntimeError('CONTAINER_INSPECTION_FAILED')
        return selected
    def verify(info):assert info['HostConfig']['NetworkMode']=='none'
    m=SimpleNamespace(inspect_optional=inspect,retained=lambda:SimpleNamespace(docker_request=request))
    ctx=SimpleNamespace(m=m,offline_name='expected-api-probe',offline_args=lambda data,img:['docker','run','--rm','--network=none','--read-only',img],verify_offline_environment=verify)
    return ctx,root,image,good

def test_expected_auto_removed_api_probe_is_allowed_only_with_frozen_rm_and_no_writer():
    ctx,root,image,_=probe_context();assert p.verify_copy_writer_absent(ctx,root,image)=='auto_removed'
    ctx.offline_args=lambda data,img:['docker','run','--network=none','--read-only',img]
    with pytest.raises(RuntimeError,match='EXACT_AUTO_REMOVE_OFFLINE_SOURCE_REQUIRED'):p.verify_copy_writer_absent(ctx,root,image)

def test_unknown_inspection_error_is_never_treated_as_missing():
    ctx,root,image,_=probe_context(inspect_error=True)
    with pytest.raises(RuntimeError,match='CONTAINER_INSPECTION_FAILED'):p.verify_copy_writer_absent(ctx,root,image)

def test_exact_stopped_probe_image_command_mounts_and_isolation_are_checked():
    ctx,root,image,_=probe_context(probe='good');assert p.verify_copy_writer_absent(ctx,root,image)=='exact_stopped'

@pytest.mark.parametrize('field,value', [('Running',True),('Status','created'),('ExitCode',137)])
def test_present_api_probe_must_be_successfully_stopped(field,value):
    _,root,image,good=probe_context();good['State'][field]=value;ctx,_,_,_=probe_context(probe=good)
    with pytest.raises(RuntimeError,match='EXACT_STOPPED_API_PROBE_REQUIRED'):p.verify_copy_writer_absent(ctx,root,image)

@pytest.mark.parametrize('kind', ['name','image','mount','isolation','command'])
def test_wrong_present_probe_is_rejected(kind):
    _,root,image,good=probe_context()
    if kind=='name':good['Name']='/different'
    elif kind=='image':good['Image']='sha256:'+'0'*64
    elif kind=='mount':good['Mounts'][0]['Source']='/other'
    elif kind=='isolation':good['HostConfig']['NetworkMode']='host'
    else:good['Config']['Cmd']=['malicious']
    ctx,_,_,_=probe_context(probe=good)
    with pytest.raises(RuntimeError):p.verify_copy_writer_absent(ctx,root,image)

@pytest.mark.parametrize('source_suffix', ['', '/crm_prod.db'])
def test_any_running_copy_writer_is_rejected_even_after_probe_auto_removal(source_suffix):
    _,root,_,_=probe_context();running=[{'Mounts':[{'Type':'bind','Source':str(root/'probe-data')+source_suffix,'RW':True}]}];ctx,root,image,_=probe_context(running=running)
    with pytest.raises(RuntimeError,match='RUNNING_OLD_COPY_WRITER_REJECTED'):p.verify_copy_writer_absent(ctx,root,image)

def test_unrelated_production_or_readonly_mounts_are_not_false_writers():
    _,root,_,_=probe_context();running=[{'Mounts':[{'Source':'/opt/t24-crm/app/data','RW':True},{'Source':str(root/'probe-data'),'RW':False}]}];ctx,root,image,_=probe_context(running=running)
    assert p.verify_copy_writer_absent(ctx,root,image)=='auto_removed'

def test_real_eight_digit_docker_and_naive_sqlite_timestamp_comparison_only():
    raw='2026-11-01T19:00:56.90391494Z'
    expected=datetime(2026,11,1,19,0,56,903914,tzinfo=timezone.utc)
    assert p.stamp(raw)==expected and raw=='2026-11-01T19:00:56.90391494Z'
    assert p.stamp('2026-11-01 19:00:56.903914')==expected
    assert p.stamp('2026-11-01T19:00:56.903914+00:00')==expected
    assert p.stamp('2026-11-01T14:00:56.903914-05:00')==expected
    assert p.timestamp_canary() is True

def test_timestamp_canary_works_with_python310_strict_fraction_parser(monkeypatch):
    class Strict310Datetime(datetime):
        @classmethod
        def fromisoformat(cls,value):
            assert value.endswith(('+00:00','-05:00')) or len(value.rsplit('.',1)[-1])==6 or '.' not in value
            if '.' in value:assert len(value.split('.',1)[1].split('+',1)[0].split('-',1)[0])==6
            return datetime.fromisoformat(value)
    monkeypatch.setattr(p,'datetime',Strict310Datetime)
    assert p.timestamp_canary() is True

@pytest.mark.parametrize('value', ['2026-11-01T19:00:56.1234567890Z','2026-11-01T19:00:56.Z','2026-11-01T19:00:56abcZ','2026-11-01X19:00:56Z','2026-11-01T19:00:56+0000','2026-11-01T19:00:56+25:00','2026-13-01T19:00:56Z','2026-11-01T19:00:56.123456789e1Z'])
def test_timestamp_unbounded_or_malformed_values_are_rejected(value):
    with pytest.raises((RuntimeError,ValueError)):p.stamp(value)
