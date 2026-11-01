"""Synthetic read-only capture tests. No server, credentials or providers."""
import ast,base64,copy,importlib.util,json,sqlite3,zlib
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
p=load('scale_readonly_capture',HERE/'preflight.py');maker=load('scale_readonly_maker',HERE/'make_capture.py')

def seed(path):
    con=sqlite3.connect(path)
    for name in ('customers','google_business_onboarding_catalogs','google_business_onboarding_requests','google_business_onboarding_batches','google_business_onboarding_items'):con.execute('CREATE TABLE '+name+'(id INTEGER)')
    con.execute('CREATE TABLE google_business_bindings(id INTEGER,active INTEGER)')
    con.executemany('INSERT INTO customers VALUES(?)',[(n,) for n in range(43)])
    con.executemany('INSERT INTO google_business_bindings VALUES(?,1)',[(n,) for n in range(15)])
    for name in ('google_business_onboarding_catalogs','google_business_onboarding_requests'):con.executemany('INSERT INTO '+name+' VALUES(?)',[(1,),(2,)])
    con.commit();con.close()

def test_legitimate_second_explicit_discovery_is_captured_not_forced_back_to_one(tmp_path,monkeypatch):
    path=tmp_path/'synthetic.db';seed(path);body=path.read_bytes();original=p.sqlite3.connect;trace=[]
    def observed(*a,**kw):
        assert '?mode=ro' in a[0];con=original(*a,**kw);con.set_trace_callback(trace.append);return con
    monkeypatch.setattr(p.sqlite3,'connect',observed);value=p.markers(path)
    assert value=={'customers':43,'google_business_bindings':15,'google_business_onboarding_catalogs':2,'google_business_onboarding_requests':2,'google_business_onboarding_batches':0,'google_business_onboarding_items':0,'active_google_bindings':15}
    assert path.read_bytes()==body and all(not x.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','ALTER','DROP','CREATE','REPLACE')) for x in trace)

def fixture(tmp_path,monkeypatch):
    path=tmp_path/'synthetic.db';seed(path)
    inventory={f'synthetic/{n}.py':'a'*64 for n in range(417)};inventory.update({name:'b'*64 for name in p.BACKEND_FILES})
    rows={f'table_{n}':{'count':n,'rows_sha256':'a'*64,'shape_sha256':'b'*64} for n in range(162)}
    creds={name:{'metadata_only':True} for name in ('ops','google','meta_read','meta_legacy')};private={'metadata_only':True};identity=[path.stat().st_dev,path.stat().st_ino]
    m=SimpleNamespace(inspect=lambda name:{'State':{'Running':True}},runtime=lambda x:p.RUNTIME,verify_secret_mount=lambda x:None,verify_production_worker_enabled=lambda x:None,retained=lambda:SimpleNamespace(require_safe_original_restart=lambda x:None),inventory=lambda x:inventory,schema_signature=lambda *a:p.SCHEMA,credential_boundary=lambda:{'metadata_only':True},verify_public=lambda *a:'d'*64,BUSINESS=path,NGINX=SimpleNamespace(read_bytes=lambda:b'fixed nginx'),run=lambda *a:b'fixed active nginx')
    old=SimpleNamespace(core=SimpleNamespace(ENV_FILE='read',LEGACY_ENV_FILE='legacy'),pf=SimpleNamespace(google_environment=lambda x:None))
    safe=SimpleNamespace(safe_private_boundary=lambda *a:private,protected_metadata=lambda x:{'metadata_only':True},GBP_ENV='google')
    flow=SimpleNamespace(m=m,environment=lambda x:('e'*64,'f'*64),ctx=SimpleNamespace(workflow=old),c=SimpleNamespace(ENV_FILE='ops'),safe=safe,pins={},rows=lambda:rows,retained=SimpleNamespace(evidence=lambda x:x,live_sequence_boundary=lambda a,b:None),metadata=lambda path:{'same':True})
    wrapper=SimpleNamespace(proof={'private_boundary':private,'credential_metadata':creds,'credential_boundary':{'metadata_only':True},'database_identity':identity},nginx=lambda updated:None,manifest={})
    monkeypatch.setattr(p,'dependencies',lambda:(None,flow,inventory));monkeypatch.setattr(p,'_CACHE',(None,flow,inventory,wrapper,{'public_inventory_sha256':'d'*64}))
    return flow,inventory,rows,wrapper

def test_sample_preserves_every_current_row_and_419_file_inventory(tmp_path,monkeypatch):
    flow,inventory,rows,wrapper=fixture(tmp_path,monkeypatch);value=p.sample()
    assert value['rows']==rows and len(value['rows'])==162 and value['backend_inventory']==inventory and value['backend_file_count']==419
    assert value['backend_changed_before']=={name:inventory[name] for name in p.BACKEND_FILES}
    assert value['source_sha']==p.SOURCE and value['static_source_sha']==p.STATIC_SOURCE and value['frontend_version']==p.FRONTEND
    assert value['business_markers']['google_business_onboarding_catalogs']==2 and value['business_writes'] is False and value['provider_requests'] is False
    assert value['credential_file_content_read'] is False and value['private_content_read'] is False

@pytest.mark.parametrize('key',['runtime','source','schema','private','credentials','static','database'])
def test_current_boundary_drift_prevents_capture(tmp_path,monkeypatch,key):
    flow,inventory,rows,wrapper=fixture(tmp_path,monkeypatch)
    if key=='runtime':flow.m.runtime=lambda x:{**p.RUNTIME,'restart':1}
    if key=='source':flow.m.inventory=lambda x:{**inventory,'unexpected.py':'d'*64}
    if key=='schema':flow.m.schema_signature=lambda *a:'d'*64
    if key=='private':flow.safe.safe_private_boundary=lambda *a:{'changed':True}
    if key=='credentials':flow.m.credential_boundary=lambda:{'changed':True}
    if key=='static':flow.m.verify_public=lambda *a:'f'*64
    if key=='database':wrapper.proof['database_identity']=[0,0]
    with pytest.raises(RuntimeError):p.sample()

def test_two_stable_samples_require_all162_rows_and_protections_exact():
    retained=SimpleNamespace(live_sequence_boundary=lambda a,b:None)
    first={'rows':{'financial':'same','private':'same'},'inventory':'same','database_metadata':{'sequence':1}}
    second=copy.deepcopy(first);second['database_metadata']['sequence']=2;p.stable(first,second,retained)
    for key in ('rows','inventory'):
        bad=copy.deepcopy(second);bad[key]='changed'
        with pytest.raises(RuntimeError,match='CURRENT162_BOUNDARIES_CHANGED_DURING_CAPTURE'):p.stable(first,bad,retained)

def test_capture_writes_only_new_root_private_aggregate(tmp_path,monkeypatch):
    flow,inventory,rows,wrapper=fixture(tmp_path,monkeypatch);proof=p.sample();out=tmp_path/'proofs';out.mkdir();monkeypatch.setattr(p,'ROOT',out)
    monkeypatch.setattr(p,'sample',lambda:copy.deepcopy(proof));value=p.capture();files=list(out.iterdir())
    assert len(files)==1 and files[0].stat().st_mode&0o777==0o600 and p.H(files[0].read_bytes())==value['sha256']
    assert value['table_count']==162 and 'rows' not in value and 'backend_inventory' not in value and value['two_stable_samples_verified'] is True
    full=json.loads(files[0].read_bytes());assert full['rows']==rows and full['backend_inventory']==inventory

def test_wrapper_embeds_exact_reviewed_source_without_execution_or_transmission():
    command,pins=maker.generate();source=command.split("<<'CAPTURE'\n",1)[1].rsplit('\nCAPTURE',1)[0];tree=ast.parse(source)
    values={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'payload','expected'}}
    assert zlib.decompress(base64.b64decode(values['payload']))==(HERE/'preflight.py').read_bytes() and values['expected']==pins['preflight_sha256']
    assert len(command.encode())<14000 and pins['executed'] is False and pins['provider_requests'] is False and pins['database_writes'] is False

def test_actual_deployed_receipts_and_helper_pins_match_latest_static_and_backend():
    root=HERE.parents[1];mobile=root/'deployments/google-business-onboarding-mobile-20261102';out=root/'outputs/google-business-onboarding-mobile-20261102'
    assert p.H((mobile/'release.py').read_bytes())==p.HELPER and p.H((out/'deployed.json').read_bytes())==p.DEPLOYED and p.H((out/'prepared.json').read_bytes())==p.PREPARED
    deployed=json.loads((out/'deployed.json').read_bytes());assert deployed['runtime']==p.RUNTIME and deployed['source_sha']==p.STATIC_SOURCE and deployed['backend_source_sha']==p.SOURCE and deployed['frontend_version']==p.FRONTEND
    assert deployed['public_root']==str(p.PUBLIC) and deployed['boundary']['schema_sha256']==p.SCHEMA
