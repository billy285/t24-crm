"""Synthetic baseline and embedded-capture checks; never touch a live service."""
import ast,base64,copy,hashlib,importlib.util,json,sqlite3,zlib
from pathlib import Path
from types import SimpleNamespace
import pytest
HERE=Path(__file__).resolve().parent

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
p=load('_meta_month_pf',HERE/'preflight.py');maker=load('_meta_month_capture',HERE/'make_capture.py')

def seed(path):
 con=sqlite3.connect(path)
 for name,count in [('customers',43),('google_business_bindings',15),('google_business_onboarding_catalogs',2),('google_business_onboarding_requests',2),('google_business_onboarding_batches',0),('google_business_onboarding_items',0)]:
  con.execute('CREATE TABLE '+name+'(id INTEGER)');con.executemany('INSERT INTO '+name+' VALUES(?)',[(n,) for n in range(count)])
 con.commit();con.close()

def test_markers_only_read_existing_named_tables(tmp_path,monkeypatch):
 path=tmp_path/'synthetic.db';seed(path);before=path.read_bytes();original=p.sqlite3.connect;trace=[]
 def connect(*args,**kwargs):
  assert '?mode=ro' in args[0];con=original(*args,**kwargs);con.set_trace_callback(trace.append);return con
 monkeypatch.setattr(p.sqlite3,'connect',connect);result=p.markers(path)
 assert result['customers']==43 and result['google_business_bindings']==15
 assert path.read_bytes()==before and all(not statement.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','ALTER','DROP','CREATE','REPLACE')) for statement in trace)

def fixture(tmp_path,monkeypatch):
 path=tmp_path/'synthetic.db';seed(path)
 inventory={f'fixture/{n}.py':'a'*64 for n in range(419)}
 rows={f'table{n}':{'count':n,'rows_sha256':'b'*64,'shape_sha256':'c'*64} for n in range(162)}
 m=SimpleNamespace(inspect=lambda name:{'State':{'Running':True}},runtime=lambda x:p.RUNTIME,verify_secret_mount=lambda x:None,verify_production_worker_enabled=lambda x:None,retained=lambda:SimpleNamespace(require_safe_original_restart=lambda x:None),inventory=lambda x:inventory,schema_signature=lambda *a:p.SCHEMA,verify_public=lambda *a:'d'*64,BUSINESS=path,NGINX=SimpleNamespace(read_bytes=lambda:b'fixed nginx'))
 retained=SimpleNamespace(evidence=lambda x:x,live_sequence_boundary=lambda *a:None)
 proof={k:{'metadata_only':True} for k in ('credential_boundary','credential_metadata','private_boundary')};proof['database_identity']=[path.stat().st_dev,path.stat().st_ino]
 flow=SimpleNamespace(m=m,environment=lambda x:('e'*64,'f'*64),ctx=SimpleNamespace(workflow=SimpleNamespace(pf=SimpleNamespace(google_environment=lambda x:None))),retained=retained,protections=lambda **kw:None,public=Path(p.PUBLIC),nginx=lambda **kw:'f'*64,rows=lambda:rows,metadata=lambda path:{'same':True},proof=proof,manifest={})
 monkeypatch.setattr(p,'dependencies',lambda:(None,flow,inventory));monkeypatch.setattr(p,'NGINX',p.H(b'fixed nginx'))
 return flow,inventory,rows

def test_sample_keeps_exact419_sources_all162_rows_and_disabled_execution(tmp_path,monkeypatch):
 flow,inventory,rows=fixture(tmp_path,monkeypatch);value=p.sample()
 assert value['backend_inventory']==inventory and value['rows']==rows and value['backend_file_count']==419
 assert value['source_sha']==p.SOURCE and value['frontend_version']==p.FRONTEND and value['schema_revision']==p.HEAD
 for field in ('ops_execution_enabled','ops_scheduler_enabled','business_writes','provider_requests','credential_file_content_read','private_content_read','runtime_changed','schema_changed','permissions_changed'):assert value[field] is False

@pytest.mark.parametrize('attack',['runtime','inventory','static_root','nginx','preservation'])
def test_changed_live_boundaries_reject_capture(tmp_path,monkeypatch,attack):
 flow,inventory,rows=fixture(tmp_path,monkeypatch)
 if attack=='runtime':flow.m.runtime=lambda x:{**p.RUNTIME,'restart':1}
 elif attack=='inventory':flow.m.inventory=lambda x:{**inventory,'unreviewed.py':'d'*64}
 elif attack=='static_root':flow.public=Path('/other')
 elif attack=='nginx':flow.m.NGINX.read_bytes=lambda:b'changed'
 else:flow.protections=lambda **kw:p.need(False,'PROTECTION_DRIFT')
 with pytest.raises(RuntimeError):p.sample()

def test_two_samples_allow_only_retained_forward_metadata_not_rows_or_environment():
 retained=SimpleNamespace(live_sequence_boundary=lambda *a:None)
 first={'rows':{'finance':'same','private':'same'},'environment':'same','database_metadata':{'counter':1}}
 second=copy.deepcopy(first);second['database_metadata']['counter']=2;p.stable(first,second,retained)
 for field in ('rows','environment'):
  changed=copy.deepcopy(second);changed[field]='changed'
  with pytest.raises(RuntimeError):p.stable(first,changed,retained)

def test_capture_outputs_bounded_summary_and_new_root600_aggregate_only(tmp_path,monkeypatch):
 flow,inventory,rows=fixture(tmp_path,monkeypatch);value=p.sample();out=tmp_path/'proofs';out.mkdir()
 monkeypatch.setattr(p,'ROOT',out);monkeypatch.setattr(p,'sample',lambda:copy.deepcopy(value));summary=p.capture();files=list(out.iterdir())
 assert len(files)==1 and files[0].stat().st_mode&0o777==0o600
 assert p.H(files[0].read_bytes())==summary['sha256'] and summary['stage']=='MEDIA_META_MONTHLY_PREFLIGHT_CAPTURED'
 assert summary['two_stable_samples_verified'] is True and 'rows' not in summary and 'backend_inventory' not in summary
 assert json.loads(files[0].read_bytes())['rows']==rows

def test_capture_wrapper_pins_exact_reviewed_bytes_without_network_or_exec_now():
 command,pins=maker.generate();source=command.split("<<'CAPTURE'\n",1)[1].rsplit('\nCAPTURE',1)[0];tree=ast.parse(source)
 values={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'payload','expected'}}
 assert zlib.decompress(base64.b64decode(values['payload']))==(HERE/'preflight.py').read_bytes()
 assert values['expected']==pins['preflight_sha256'] and len(command.encode())<14000
 assert pins['executed'] is False and pins['provider_requests'] is False and pins['database_writes'] is False

def test_pinned_completed_parent_receipts_sources_and_runtime_match_local_evidence():
 parent=HERE.parent/'media-operator-queue-20261102'
 for name,expected in [('release.py',p.HELPER),('prepared.json',p.PREPARED),('deployed.json',p.DEPLOYED),('artifacts/manifest.json',p.MANIFEST),('artifacts/payload.tar.gz',p.PAYLOAD)]:assert p.H((parent/name).read_bytes())==expected
 deployed=json.loads((parent/'deployed.json').read_bytes());assert deployed['source_sha']==p.SOURCE and deployed['frontend_version']==p.FRONTEND and deployed['crm']==p.RUNTIME
 assert deployed['schema_revision']==p.HEAD and deployed['table_count']==162 and deployed['privacy']['content_security_policy_sha256']==p.CSP
 assert deployed['preflight_sha256']==p.PREFLIGHT
