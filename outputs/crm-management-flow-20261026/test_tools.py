"""Focused guard checks; only local temporary fixtures, never a server."""
import ast,copy,hashlib,importlib.util,json,os,sqlite3,subprocess,sys
from pathlib import Path
from unittest.mock import patch
try:
 import pytest
except ImportError:
 from contextlib import contextmanager
 class _LocalChecks:
  @staticmethod
  @contextmanager
  def raises(expected,match=None):
   try:yield
   except expected as error:
    if match is not None and not __import__('re').search(match,str(error)):raise AssertionError('Expected error pattern: '+match)
   else:raise AssertionError('Expected exception was not raised')
 pytest=_LocalChecks()
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
def module(name):
 spec=importlib.util.spec_from_file_location('crm_ui_test_'+name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
b=module('baseline');builder=module('build_package')
def nested(name,values):
 tree=ast.parse((ROOT/'static_release.py').read_text());node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
 ns={'os':os,'Path':Path,'need':b.need,'re':__import__('re'),**values};exec(compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(node)],type_ignores=[])),'guard','exec'),ns);return ns[name]
def test_before_source_matches_actual_version():
 assert builder.source_version('69666997496e57189e6e2f32f33467a584fe37c5')=='2908954fe44e'
def test_schema_reads_ddl_not_financial_rows(tmp_path):
 db=tmp_path/'fixture.db';c=sqlite3.connect(db);c.execute('CREATE TABLE secret_ledger(id INTEGER, amount REAL)');c.execute('INSERT INTO secret_ledger VALUES(1,99)');c.commit();c.close()
 with patch.object(b,'protected',lambda p:Path(p).stat()):
  before=b.schema(db);c=sqlite3.connect(db);c.execute('UPDATE secret_ledger SET amount=199');c.commit();c.close();assert b.schema(db)==before
  c=sqlite3.connect(db);c.execute('ALTER TABLE secret_ledger ADD COLUMN status TEXT');c.commit();c.close();assert b.schema(db)['schema_sha256']!=before['schema_sha256']
def test_runtime_hashes_configuration_without_exporting_secrets():
 v={'Id':'a'*64,'Image':'sha256:'+'b'*64,'State':{'Running':True,'StartedAt':'now'},'RestartCount':0,'Config':{'Env':['API_KEY=DO_NOT_EXPORT'],'Labels':{'t24.release.source':'x','OTHER_SECRET':'DO_NOT_EXPORT'}},'HostConfig':{},'Mounts':[],'NetworkSettings':{'Networks':{}}}
 with patch.object(b,'run',return_value=json.dumps([v]).encode()):first=b.runtime('t24-crm')
 assert 'DO_NOT_EXPORT' not in json.dumps(first)
 v['Config']['Env']=['API_KEY=CHANGED']
 with patch.object(b,'run',return_value=json.dumps([v]).encode()):assert b.runtime('t24-crm')['config_sha256']!=first['config_sha256']
def test_capture_rejects_concurrent_runtime_change():
 with patch.object(b.os,'geteuid',return_value=0),patch.object(b.socket,'gethostname',return_value=b.HOST),patch.object(b,'backend_boundary',side_effect=[{'id':'old'},{'id':'new'}]),patch.object(b,'static_boundary',return_value={'root':'same'}):
  with pytest.raises(RuntimeError,match='BOUNDARY_CHANGED'):b.capture()
def test_only_one_nginx_root_and_exact_before_hash():
 original=b'server {\n root /var/www/t24-crm-public/old;\n location /api { proxy_pass http://127.0.0.1; }\n}\n';old=Path('/var/www/t24-crm-public/old');new=Path('/var/www/t24-crm-public/new')
 fn=nested('nginx_next',{'H':b.H,'baseline':{'nginx_sha256':b.H(original)},'old':old,'public':new})
 assert fn(original).replace(str(new).encode(),str(old).encode())==original
 with pytest.raises(RuntimeError):fn(original+b'\nroot /other;')
 twice=original+b'\nroot /other;';fn=nested('nginx_next',{'H':b.H,'baseline':{'nginx_sha256':b.H(twice)},'old':old,'public':new})
 with pytest.raises(RuntimeError,match='EXACT_NGINX_ROOT'):fn(twice)
def test_cas_will_not_overwrite_unknown_nginx(tmp_path):
 path=tmp_path/'nginx';path.write_bytes(b'original');fn=nested('replace',{'m':{'NGINX':path},'read':lambda p:p.read_bytes()})
 with pytest.raises(RuntimeError,match='NGINX_CONCURRENT'):fn(b'wrong',b'new')
 assert path.read_bytes()==b'original';fn(b'original',b'new');assert path.read_bytes()==b'new'
def test_recover_always_reloads_original_on_disk(tmp_path):
 path=tmp_path/'nginx';path.write_bytes(b'original');calls=[]
 values={'m':{'NGINX':path},'read':lambda p:p.read_bytes(),'replace':lambda a,b:calls.append('replace'),'reload':lambda:calls.append('reload'),'old_static':lambda:calls.append('old_static'),'public_version':lambda:{'version':'old'},'baseline':{'frontend_version':'old'}}
 nested('rollback',values)(b'original',b'new');assert calls==['reload','old_static']
 values['public_version']=lambda:{'version':'new'}
 with pytest.raises(RuntimeError,match='RECOVERED_PUBLIC_VERSION'):nested('rollback',values)(b'original',b'new')
def test_scope_and_no_application_or_database_write_paths():
 assert builder.BEFORE=='69666997496e57189e6e2f32f33467a584fe37c5'
 text=(ROOT/'static_release.py').read_text();tree=ast.parse(text)
 assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) and any(a.name.startswith(('app.','services.','models.')) for a in getattr(n,'names',[])) for n in ast.walk(tree))
 assert all(x not in text for x in ('docker_create','docker_stop','alembic','INSERT INTO','UPDATE payments','DELETE FROM','STRIPE_AUTO_POSTING_ENABLED','payments\'','pilot'))
def test_explicit_ui_allowlist_rejects_private_auth_and_backend(tmp_path):
 path=tmp_path/'allowlist.json';valid=['app/frontend/src/pages/Customers.tsx','app/frontend/src/components/ui/crm-form-dialog.css'];path.write_text(json.dumps(valid));assert builder.read_allowlist(path)==sorted(valid)
 for names in ([],valid+[valid[0]],['app/frontend/src/pages/PrivateWorkspace.tsx'],['app/frontend/src/lib/customer-permissions.ts'],['app/backend/routers/sales_leads.py'],['app/frontend/src/components/auth-helper.ts'],['app/frontend/src/components/../../tokenStore.ts'],[None],[{}]):
  path.write_text(json.dumps(names))
  with pytest.raises(RuntimeError,match='EXACT_SAFE_UI_ALLOWLIST'):builder.read_allowlist(path)
def test_ui_scope_guard_allows_view_only_changes_but_not_mutations_or_gates():
 before="function Finance(){const canCreatePayment=isAdmin; const handleSavePayment=async()=>{if(!canCreatePayment)return;await api('/payments','POST',{amount:198});}; return <button>Old</button>}"
 command=['/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',str(ROOT/'verify_ui_scope.cjs')]
 def check(after):return subprocess.run(command,input=json.dumps({'files':{'app/frontend/src/pages/Fixture.tsx':{'before':before,'after':after}}}).encode(),capture_output=True)
 assert json.loads(check(before.replace('Old','New')).stdout)['unchanged'] is True
 assert check(before.replace('amount:198','amount:199')).returncode!=0
 assert check(before.replace('canCreatePayment=isAdmin','canCreatePayment=true')).returncode!=0
 assert check(before.replace("return <button>","api('/extra','POST',{});return <button>")).returncode!=0
def test_ui_scope_guard_rejects_object_method_mutation_arguments():
 before='function Finance(){return <button>View</button>}'
 command=['/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',str(ROOT/'verify_ui_scope.cjs')]
 def check(after):return subprocess.run(command,input=json.dumps({'files':{'app/frontend/src/pages/Fixture.tsx':{'before':before,'after':after}}}).encode(),capture_output=True)
 assert json.loads(check(before.replace('View','Other view')).stdout)['unchanged'] is True
 for method in ('POST','PUT','PATCH','DELETE','post'):
  for key in ('method',"'method'"):
   changed=before.replace('return <button>',"invokeWithAuth({"+key+":'"+method+"',url:'/payments',data:{amount:198}});return <button>")
   assert check(changed).returncode!=0
def test_ui_projection_preserves_conditions_controls_and_calculations():
 command=['/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',str(ROOT/'verify_ui_scope.cjs')]
 before='function Finance(){const total=paid-fee; return <section>{isOwner && <button disabled={!canSave} onClick={()=>save(total)}>Save</button>}</section>}'
 def check(after):return subprocess.run(command,input=json.dumps({'files':{'app/frontend/src/pages/Fixture.tsx':{'before':before,'after':after}}}).encode(),capture_output=True)
 assert check(before.replace('<section>','<CrmFormDialogBody>').replace('</section>','</CrmFormDialogBody>')).returncode==0
 assert check(before.replace('paid-fee','paid+fee')).returncode!=0
 assert check(before.replace('isOwner &&','true &&')).returncode!=0
 assert check(before.replace('disabled={!canSave}','disabled={false}')).returncode!=0
 assert check(before.replace('save(total)','save(100)')).returncode!=0

def test_ui_guard_rejects_added_unguarded_action_even_when_original_remains():
 before='function Finance(){return <section>{isOwner && <button onClick={confirm}>Confirm</button>}</section>}'
 after=before.replace('</section>','<button onClick={confirm}>Bypass</button></section>')
 command=['/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',str(ROOT/'verify_ui_scope.cjs')]
 result=subprocess.run(command,input=json.dumps({'files':{'app/frontend/src/pages/Fixture.tsx':{'before':before,'after':after}}}).encode(),capture_output=True)
 assert result.returncode!=0

def guard_check(before, after, file='app/frontend/src/pages/Fixture.tsx'):
 command=['/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',str(ROOT/'verify_ui_scope.cjs')]
 return subprocess.run(command,input=json.dumps({'files':{file:{'before':before,'after':after}}}).encode(),capture_output=True)

def test_guard_freezes_create_update_and_remove_calls_and_parent_handlers():
 for name in ('create','update','remove'):
  before="function save(){return client.entities.customers."+name+"({id:1,amount:198})} function UI(){return <button>View</button>}"
  assert guard_check(before,before.replace('amount:198','amount:199')).returncode!=0
  assert guard_check(before,before.replace('return client','if(false)return;return client')).returncode!=0
  assert guard_check(before,before.replace('View','New label')).returncode==0

def test_guard_rejects_unregistered_reads_inline_finance_formula_and_new_logic():
 before='function UI(){return <section>{paid-fee}</section>}'
 for after in (before.replace('paid-fee','paid+fee'),before+";const bypass=true;",before+";fetch('/unapproved-data')"):
  assert guard_check(before,after).returncode!=0

def test_guard_rejects_moving_existing_action_outside_its_permission_condition():
 before='function UI(){return <>{canEdit && <button onClick={save}>Save</button>}</>}'
 after='function UI(){return <>{canEdit && <span />}<button onClick={save}>Save</button></>}'
 assert guard_check(before,after).returncode!=0

def test_guard_rejects_private_auth_routes_and_ordinary_dialog_changes():
 before='function App(){return <Route path="/private-workspace" element={<PrivateWorkspace />} />}'
 assert guard_check(before,before.replace('PrivateWorkspace','Customers'), 'app/frontend/src/App.tsx').returncode!=0
 before='const DialogContent=React.forwardRef((props,ref)=><div ref={ref} {...props}/>);'
 assert guard_check(before,before.replace('ref={ref}','ref={ref} role="none"'),'app/frontend/src/components/ui/dialog.tsx').returncode!=0

def test_current_frozen_sources_match_explicit_registered_deltas():
 registry=json.loads((ROOT/'approved-deltas.json').read_text());files={}
 for name in registry['files']:
  old=subprocess.run(['git','show',builder.BEFORE+':'+name],capture_output=True)
  files[name]={'before':old.stdout.decode() if old.returncode==0 else '', 'after':Path(name).read_text()}
 command=['/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',str(ROOT/'verify_ui_scope.cjs')]
 result=subprocess.run(command,input=json.dumps({'files':files}).encode(),capture_output=True)
 assert result.returncode==0,result.stderr.decode()
 value=json.loads(result.stdout);assert value['registered_read_and_ui_changes_only'] is True and value['unknown_semantic_drift'] is False
 assert value['original_api_requests_unchanged'] is True and value['authorization_gates_unchanged'] is True

def test_registry_rejects_one_unknown_change_inside_approved_read_function():
 name='app/frontend/src/pages/ManagementDecisions.tsx'
 old=subprocess.check_output(['git','show',builder.BEFORE+':'+name]).decode()
 current=Path(name).read_text()
 assert guard_check(old,current.replace("const request = ++readSequence.current;","const request = ++readSequence.current; const unreviewed=1;",1),name).returncode!=0

def test_exact_extra_build_paths_do_not_open_general_lib_or_config():
 for name in ('app/frontend/src/App.tsx','app/frontend/vite.config.ts'):
  assert builder.ui_source(name)
 for name in ('app/frontend/src/lib/crm-prefetch.ts','app/frontend/package.json','app/frontend/src/pages/auth-bypass.ts','app/backend/x.py'):
  assert not builder.ui_source(name)

def test_fresh_baseline_hash_and_expected_old_version_are_pinned():
 assert builder.BASELINE_SHA256==hashlib.sha256((ROOT/'baseline.json').read_bytes()).hexdigest()
 assert json.loads((ROOT/'baseline.json').read_text())['frontend_version']=='2908954fe44e'
 assert "manifest['baseline_source_sha']=='"+builder.BEFORE+"'" in (ROOT/'static_release.py').read_text()


if __name__=='__main__':
 import inspect,tempfile
 passed=[];failed=[]
 for name,check in sorted(list(globals().items())):
  if not name.startswith('test_') or not callable(check):continue
  try:
   if 'tmp_path' in inspect.signature(check).parameters:
    with tempfile.TemporaryDirectory(prefix='t24-crm-management-flow-test-') as directory:check(Path(directory))
   else:check()
   passed.append(name)
  except BaseException as error:failed.append({'test':name,'error':type(error).__name__,'detail':str(error)})
 result={'passed':len(passed),'failed':len(failed),'checks':passed,'failures':failed,'synthetic_only':True,'server_commands_executed':False}
 print(json.dumps(result,sort_keys=True,indent=2));raise SystemExit(1 if failed else 0)
