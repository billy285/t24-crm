"""Only synthetic DB/receipt tests; never connect to production or providers."""
import ast
import base64
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import zlib
import pytest

HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
p=load('mobile_readonly_capture',HERE/'preflight.py');maker=load('mobile_readonly_capture_maker',HERE/'make_capture.py')

def seed(path):
    con=sqlite3.connect(path)
    definitions={'customers':'id INTEGER','google_business_bindings':'id INTEGER,active INTEGER','google_business_onboarding_catalogs':'id TEXT,owner_id INTEGER,connection_id INTEGER,status TEXT,revision INTEGER,lease_token TEXT,error_code TEXT,customer_id INTEGER','google_business_onboarding_requests':'resource_id TEXT,owner_id INTEGER,kind TEXT','google_business_onboarding_batches':'id TEXT','google_business_onboarding_items':'id TEXT','google_business_connections':'id INTEGER,owner_id INTEGER,active INTEGER,needs_reconnect INTEGER','employees':'id INTEGER,role TEXT,status TEXT'}
    for name,columns in definitions.items():con.execute('CREATE TABLE '+name+'('+columns+')')
    con.executemany('INSERT INTO customers VALUES(?)',[(x,) for x in range(43)]);con.executemany('INSERT INTO google_business_bindings VALUES(?,1)',[(x,) for x in range(15)])
    con.execute("INSERT INTO google_business_onboarding_catalogs VALUES('a',1,1,'ready',3,NULL,NULL,NULL)");con.execute("INSERT INTO google_business_onboarding_requests VALUES('a',1,'discovery')");con.execute('INSERT INTO google_business_connections VALUES(1,1,1,0)');con.execute("INSERT INTO employees VALUES(1,'super_admin','active')");con.commit();con.close()

def test_exact_pilot_markers_only_readonly_queries(tmp_path,monkeypatch):
    path=tmp_path/'synthetic.db';seed(path);body=path.read_bytes();connect=p.sqlite3.connect;traces=[]
    def observed(*a,**kw):
        assert '?mode=ro' in a[0];db=connect(*a,**kw);db.set_trace_callback(traces.append);return db
    monkeypatch.setattr(p.sqlite3,'connect',observed)
    result=p.markers(path);assert result['customers']==43 and result['google_business_bindings']==15 and result['single_owner_discovery_verified'] is True and path.read_bytes()==body
    assert all(not x.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','DROP','ALTER','REPLACE')) for x in traces)

@pytest.mark.parametrize('sql',[
    "INSERT INTO google_business_onboarding_batches VALUES('new')", "INSERT INTO google_business_onboarding_items VALUES('new')",
    "INSERT INTO google_business_onboarding_requests VALUES('b',1,'discovery')", "UPDATE google_business_onboarding_catalogs SET status='processing'", "UPDATE google_business_onboarding_catalogs SET customer_id=20", "UPDATE google_business_onboarding_catalogs SET owner_id=2", "UPDATE google_business_onboarding_catalogs SET lease_token='live'", "UPDATE google_business_onboarding_requests SET kind='preview'", "UPDATE employees SET role='sales'", "UPDATE google_business_connections SET needs_reconnect=1", "UPDATE google_business_bindings SET active=0 WHERE id=1", "DELETE FROM customers WHERE id=1"
])
def test_marker_conflicts_scope_staff_or_incomplete_discovery_rejected(tmp_path,sql):
    path=tmp_path/'synthetic.db';seed(path);con=sqlite3.connect(path);con.execute(sql);con.commit();con.close()
    with pytest.raises(RuntimeError):p.markers(path)

class Retained:
    def live_sequence_boundary(self,old,new):
        assert old['pragma']==new['pragma'] and set(old['seq'])==set(new['seq'])
        assert all(new['seq'][key]>=value if key=='monthly_deduction_rates' else new['seq'][key]==value for key,value in old['seq'].items())

def test_two_stable_samples_exact_except_existing_one_counter_forward():
    first={'rows':{'finance':'unchanged','private':'unchanged'},'runtime':'pinned','database_metadata':{'pragma':'same','seq':{'finance':10,'monthly_deduction_rates':3}}}
    second=copy.deepcopy(first);second['database_metadata']['seq']['monthly_deduction_rates']=4;p.stable(first,second,Retained())
    for key in ('rows','runtime'):
        bad=copy.deepcopy(second);bad[key]='changed'
        with pytest.raises(RuntimeError):p.stable(first,bad,Retained())
    bad=copy.deepcopy(second);bad['database_metadata']['seq']['finance']=11
    with pytest.raises(AssertionError):p.stable(first,bad,Retained())
    bad=copy.deepcopy(second);bad['database_metadata']['seq']['monthly_deduction_rates']=2
    with pytest.raises(AssertionError):p.stable(first,bad,Retained())

def test_exact_r3_constants_match_actual_canonical_receipts():
    old=HERE.parents[1]/'outputs/google-business-onboarding-20261102';deployed_body=(old/'deployed.json').read_bytes();prepared_body=(old/'prepared.json').read_bytes();deployed=json.loads(deployed_body)
    assert p.H(deployed_body)==p.DEPLOYED and p.H(prepared_body)==p.PREPARED
    assert deployed['crm']==p.RUNTIME and deployed['source_sha']==p.SOURCE and deployed['frontend_version']==p.FRONTEND and deployed['schema_sha256']==p.SCHEMA and deployed['schema_revision']==p.HEAD
    assert p.H((HERE.parent/'google-business-onboarding-20261102/release.py').read_bytes())==p.HELPER
    assert deployed['privacy']['content_security_policy_sha256']==p.CSP

def test_maker_exact_bounded_embedded_source_and_no_execution(tmp_path):
    command,pins=maker.generate();assert len(command.encode())<14000 and pins['executed'] is False and pins['database_writes'] is False
    source=command.split("<<'CAPTURE'\n",1)[1].rsplit('\nCAPTURE',1)[0];tree=ast.parse(source)
    values={x.targets[0].id:ast.literal_eval(x.value) for x in tree.body if isinstance(x,ast.Assign) and isinstance(x.targets[0],ast.Name) and x.targets[0].id in {'payload','expected'}}
    assert zlib.decompress(base64.b64decode(values['payload']))==(HERE/'preflight.py').read_bytes() and values['expected']==pins['preflight_sha256']
    assert list(tmp_path.iterdir())==[]

def test_capture_only_new_root_private_aggregate_not_database(tmp_path,monkeypatch):
    sample={'source_sha':p.SOURCE,'frontend_version':p.FRONTEND,'schema_revision':p.HEAD,'deployed_receipt_sha256':p.DEPLOYED,'prepared_receipt_sha256':p.PREPARED,'crm':p.RUNTIME,'environment_sha256':'e'*64,'ops_environment_sha256':'a'*64,'schema_sha256':p.SCHEMA,'database_identity':[1,2],'business_markers':{'google_business_bindings':15},'backend_inventory_sha256':'b'*64,'backend_file_count':419,'public_root':p.PUBLIC,'public_inventory_sha256':'d'*64,'nginx_sha256':p.NGINX,'active_nginx_sha256':'c'*64,'content_security_policy_sha256':p.CSP,'all162_current_tables_preserved':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','ops_execution_enabled':False,'ops_scheduler_enabled':False,'existing_asset_worker_enabled':True,'onboarding_worker_default_enabled':True,'rows':{'t':{'count':1,'rows_sha256':'f'*64,'shape_sha256':'g'*64}},'database_metadata':{'pragma':'same','seq':{'finance':1,'monthly_deduction_rates':2}},'backend_inventory':{'a':'b'},'credential_metadata':{'metadata_only':True},'private_boundary':{'metadata_only':True}}
    monkeypatch.setattr(p,'ROOT',tmp_path);monkeypatch.setattr(p,'sample',lambda:copy.deepcopy(sample));monkeypatch.setattr(p,'dependencies',lambda:(None,SimpleNamespace(retained=Retained()),None))
    result=p.capture();files=list(tmp_path.iterdir());assert len(files)==1 and files[0].stat().st_mode&0o777==0o600 and p.H(files[0].read_bytes())==result['sha256'] and len(json.dumps(result).encode())<10000
    full=json.loads(files[0].read_bytes());assert full['rows']==sample['rows'] and full['backend_inventory']==sample['backend_inventory'] and full['credential_metadata']==sample['credential_metadata']
    assert result['business_writes'] is False and result['provider_requests'] is False and 'rows' not in result and 'backend_inventory' not in result
