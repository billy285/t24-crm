"""Static-only release guards. No production access, network or subprocesses."""
import copy,io,json,sqlite3,stat,subprocess,sys,tarfile,types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

def load(path,name):
 module=types.ModuleType(name);module.__file__=str(path)
 exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__);return module

r=load(Path(__file__).with_name('release.py'),'customer_close_release_test')
c=load(Path(__file__).with_name('make_commands.py'),'customer_close_commands_test')

@pytest.fixture(autouse=True)
def no_real_actions(monkeypatch):
 def forbid(*args,**kwargs):raise AssertionError('No real process or network permitted')
 monkeypatch.setattr(subprocess,'run',forbid);monkeypatch.setattr(subprocess,'check_output',forbid)
 monkeypatch.setattr(r,'retained',Mock(side_effect=AssertionError('No server helper reads permitted')))

def manifest():
 return {'source_sha':r.SOURCE,'baseline_source_sha':r.BASELINE,'frontend_version':r.FRONTEND_VERSION,
  'baseline_frontend_version':r.BASELINE_FRONTEND,'payload_sha256':'payload','static_only':True,
  'preserved':copy.deepcopy(r.PRESERVED),**dict.fromkeys(r.FALSE_FLAGS,False),
  'changed_source_files':['app/frontend/src/pages/Customers.tsx','app/frontend/tests/customers-dialog-close.spec.ts'],
  'files':{'static/index.html':'1'*64,'static/app-version.json':'2'*64}}

def args():return SimpleNamespace(manifest_sha256='manifest',payload_sha256='payload',preflight_sha256='preflight',review_sha256='review')
def stub_read(monkeypatch):
 def read(path,expected=None):
  body=Path(path).read_bytes();r.need(expected is None or r.H(body)==expected,'FILE_HASH_DRIFT');return body
 monkeypatch.setattr(r,'read',read)

def test_pinned_current_backend_is_immutable():
 assert r.SOURCE=='b2655953a2d909ba3fd79dd37e7dddbe4dfc54bd' and r.FRONTEND_VERSION=='3361045efa5f'
 assert r.CRM_ID=='2dd800e1616754eb86c968ba9f514d2d57e0ab3576d14157f43f88fd82dbf7b3'
 assert r.CRM_IMAGE=='sha256:f3551e83890493f75982ba772db7aacfc6a85e49ddaf22acd447dcc7ec4bab7d'
 assert r.SCHEMA_REVISION=='f7d1c5a9b027' and r.PRESERVED['private_workspace'] is True

@pytest.mark.parametrize('path',['index.html','app-version.json','sw.js','assets/Customers-a12.js','assets/style-b23.css'])
def test_local_static_path_never_requires_server_helper(path):assert r.static_path(path)

@pytest.mark.parametrize('path',['backend/main.py','private/.env','assets/.env','../index.html','/index.html','assets/../index.html','assets\\evil.js','index.html/','assets/key.pem','data/crm_prod.db'])
def test_static_whitelist_rejects_every_nonpublic_path(path):assert not r.static_path(path)

def test_manifest_accepts_exact_static_boundary(monkeypatch,tmp_path):
 selected=manifest();monkeypatch.setattr(r,'read',lambda path,*a:json.dumps(selected).encode() if path.name=='manifest.json' else b'payload')
 assert r.checked_manifest(tmp_path,args())==selected

@pytest.mark.parametrize('field,value',[('source_sha','0'*40),('baseline_source_sha','0'*40),('frontend_version','0'*12),
 ('baseline_frontend_version','0'*12),('payload_sha256','wrong'),('static_only',False),('preserved',{'backend':True}),
 ('files',{}),('files',{'backend/main.py':'1'*64}),('files',{'static/../crm_prod.db':'1'*64}),
 ('files',{'static/index.html':'broken'}),('changed_source_files',['app/frontend/src/pages/Finance.tsx'])])
def test_manifest_rejects_changed_identity_or_wider_scope(monkeypatch,tmp_path,field,value):
 selected=manifest();selected[field]=value
 monkeypatch.setattr(r,'read',lambda path,*a:json.dumps(selected).encode() if path.name=='manifest.json' else b'payload')
 with pytest.raises(RuntimeError):r.checked_manifest(tmp_path,args())

@pytest.mark.parametrize('field',r.FALSE_FLAGS)
def test_manifest_explicitly_rejects_backend_db_service_env_or_credentials(monkeypatch,tmp_path,field):
 selected=manifest();selected[field]=True;monkeypatch.setattr(r,'read',lambda path,*a:json.dumps(selected).encode() if path.name=='manifest.json' else b'payload')
 with pytest.raises(RuntimeError,match='UNCHANGED_BOUNDARY_REQUIRED'):r.checked_manifest(tmp_path,args())

@pytest.mark.parametrize('source,version',[('PENDING_SOURCE',r.FRONTEND_VERSION),(r.SOURCE,'PENDING_FRONTEND'),('0'*39,r.FRONTEND_VERSION)])
def test_unfrozen_helper_is_never_runnable(monkeypatch,tmp_path,source,version):
 monkeypatch.setattr(r,'SOURCE',source);monkeypatch.setattr(r,'FRONTEND_VERSION',version)
 with pytest.raises(RuntimeError,match='FROZEN_SOURCE_VERSION_REQUIRED'):r.checked_manifest(tmp_path,args())

def make_tar(entries):
 output=io.BytesIO()
 with tarfile.open(fileobj=output,mode='w:gz') as archive:
  for name,body,kind in entries:
   member=tarfile.TarInfo(name);member.size=len(body);member.type=kind
   if kind==tarfile.SYMTYPE:member.linkname='/outside'
   archive.addfile(member,io.BytesIO(body))
 return output.getvalue()

@pytest.mark.parametrize('entries,files,code',[
 ([('static/index.html',b'good',tarfile.SYMTYPE)],{'static/index.html':r.H(b'good')},'PAYLOAD_MEMBER_REJECTED'),
 ([('static/index.html',b'good',tarfile.REGTYPE)]*2,{'static/index.html':r.H(b'good')},'PAYLOAD_MEMBER_REJECTED'),
 ([('static/index.html',b'bad',tarfile.REGTYPE)],{'static/index.html':r.H(b'good')},'PAYLOAD_HASH_DRIFT'),
 ([('static/index.html',b'good',tarfile.REGTYPE)],{'static/index.html':r.H(b'good'),'static/app-version.json':'1'*64},'PAYLOAD_INCOMPLETE'),
 ([('../escape',b'good',tarfile.REGTYPE)],{'static/index.html':r.H(b'good')},'PAYLOAD_MEMBER_REJECTED')])
def test_tar_rejects_links_duplicates_drift_and_missing_files(monkeypatch,tmp_path,entries,files,code):
 stub_read(monkeypatch);(tmp_path/'payload.tar.gz').write_bytes(make_tar(entries))
 with pytest.raises(RuntimeError,match=code):r.extract(tmp_path,{'files':files})
 assert not (tmp_path.parent/'escape').exists()

def setup_public(monkeypatch,tmp_path):
 stub_read(monkeypatch);release=tmp_path/'release';release.mkdir()
 old=tmp_path/'old';old.mkdir();(old/'assets').mkdir();(old/'assets/previous.js').write_bytes(b'oldchunk')
 (old/'app-version.json').write_text(json.dumps({'version':r.BASELINE_FRONTEND}));(old/'index.html').write_bytes(b'oldindex')
 nginx=tmp_path/'nginx.conf';nginx.write_bytes(('server { root '+str(old)+'; }').encode())
 root=tmp_path/'new';monkeypatch.setattr(r,'OLD_PUBLIC',old);monkeypatch.setattr(r,'NGINX',nginx)
 monkeypatch.setattr(r,'NGINX_SHA',r.H(nginx.read_bytes()));monkeypatch.setattr(r,'OLD_STATIC_SHA',r.digest(r.tree_inventory(old)))
 monkeypatch.setattr(r,'public_root',lambda:root)
 runtime={'id':r.CRM_ID,'config':r.CRM_CONFIG,'started':'unchanged','restart_count':0}
 monkeypatch.setattr(r,'protected_boundary',Mock(return_value=runtime));monkeypatch.setattr(r,'public_check',Mock())
 payload={'static/index.html':b'newindex','static/app-version.json':json.dumps({'version':r.FRONTEND_VERSION}).encode(),'static/assets/new.js':b'newchunk'}
 selected=manifest();selected['files']={name:r.H(body) for name,body in payload.items()}
 (release/'release.py').write_bytes(b'helper');(release/'manifest.json').write_text(json.dumps(selected))
 (release/'payload.tar.gz').write_bytes(make_tar([(name,body,tarfile.REGTYPE) for name,body in payload.items()]))
 return release,selected,runtime,old,nginx,root

def test_prepare_stages_static_and_retains_old_chunks_without_activating(monkeypatch,tmp_path,capsys):
 release,selected,runtime,old,nginx,root=setup_public(monkeypatch,tmp_path);before=nginx.read_bytes();r.prepare(release,args(),selected,{})
 receipt=json.loads((release/'prepared.json').read_bytes())
 assert receipt['crm']==runtime and receipt['services_restarted'] is False and receipt['database_modified'] is False
 assert nginx.read_bytes()==before and (root/'assets/previous.js').read_bytes()==b'oldchunk'
 assert (root/'assets/new.js').stat().st_mode&0o777==0o644 and root.stat().st_mode&0o777==0o755
 assert r.tree_inventory(old)['assets/previous.js']==r.H(b'oldchunk')
 assert json.loads(capsys.readouterr().out)['stage']=='CUSTOMER_DIALOG_STATIC_PREPARED'

def test_prepare_rejects_old_asset_collision(monkeypatch,tmp_path):
 release,selected,_,old,_,_=setup_public(monkeypatch,tmp_path)
 (old/'assets/new.js').write_bytes(b'unexpected-old');monkeypatch.setattr(r,'OLD_STATIC_SHA',r.digest(r.tree_inventory(old)))
 with pytest.raises(RuntimeError,match='STATIC_ASSET_COLLISION'):r.prepare(release,args(),selected,{})

@pytest.mark.parametrize('target',['nginx','old_static','runtime'])
def test_prepare_or_activate_stops_on_live_drift(monkeypatch,tmp_path,target):
 release,selected,runtime,old,nginx,root=setup_public(monkeypatch,tmp_path)
 if target=='nginx':nginx.write_bytes(b'thirdparty')
 elif target=='old_static':(old/'index.html').write_bytes(b'thirdparty')
 else:monkeypatch.setattr(r,'protected_boundary',Mock(side_effect=RuntimeError('CRM_IDENTITY_DRIFT')))
 with pytest.raises(RuntimeError):r.prepare(release,args(),selected,{})
 assert not root.exists()

def test_schema_signature_reads_only_and_detects_all_schema_objects(monkeypatch,tmp_path):
 db=tmp_path/'business.db';monkeypatch.setattr(r,'BUSINESS',db)
 with sqlite3.connect(db) as connection:
  connection.executescript("CREATE TABLE alembic_version(version_num TEXT);INSERT INTO alembic_version VALUES('f7d1c5a9b027');CREATE TABLE entries(amount INTEGER);INSERT INTO entries VALUES(123);")
 before=db.read_bytes();first=r.schema_signature();assert db.read_bytes()==before
 with sqlite3.connect(db) as connection:connection.execute('CREATE INDEX amount_index ON entries(amount)')
 assert r.schema_signature()!=first
 with sqlite3.connect(db) as connection:
  assert connection.execute('SELECT * FROM entries').fetchall()==[(123,)]
  connection.execute("UPDATE alembic_version SET version_num='wrong'")
 with pytest.raises(RuntimeError,match='SCHEMA_REVISION_DRIFT'):r.schema_signature()

@pytest.mark.parametrize('drift',['id','image','running','config','schema','private'])
def test_protected_boundary_rejects_any_backend_schema_private_drift(monkeypatch,drift):
 info={'Id':r.CRM_ID,'Image':r.CRM_IMAGE,'State':{'Running':True}}
 runtime={'config':r.CRM_CONFIG};helper=SimpleNamespace(private_boundary=Mock(),runtime=lambda _:runtime,verify_sales_schema=Mock())
 if drift=='id':info['Id']='unknown'
 elif drift=='image':info['Image']='sha256:'+'0'*64
 elif drift=='running':info['State']['Running']=False
 elif drift=='config':runtime['config']='unknown'
 elif drift=='private':helper.private_boundary.side_effect=RuntimeError('PRIVATE_DRIFT')
 monkeypatch.setattr(r,'retained',lambda:helper);monkeypatch.setattr(r,'inspect',lambda _:info)
 monkeypatch.setattr(r,'schema_signature',lambda:'wrong' if drift=='schema' else r.SCHEMA_SHA)
 with pytest.raises(RuntimeError):r.protected_boundary({})

def test_swap_nginx_restores_exact_original_if_reload_fails(monkeypatch,tmp_path):
 path=tmp_path/'nginx';path.write_bytes(b'original');monkeypatch.setattr(r,'NGINX',path)
 reload=Mock(side_effect=[RuntimeError('NGINX_TEST_FAILED'),None]);monkeypatch.setattr(r,'reload_nginx',reload)
 with pytest.raises(RuntimeError,match='NGINX_TEST_FAILED'):r.swap_nginx(b'original',b'next')
 assert path.read_bytes()==b'original' and reload.call_count==2

def pretend_root(monkeypatch,path):
 original=Path.lstat
 def lstat(self,*args,**kwargs):
  found=original(self,*args,**kwargs)
  if self==path:return SimpleNamespace(st_uid=0,st_mode=found.st_mode,st_nlink=found.st_nlink,st_dev=found.st_dev,st_ino=found.st_ino,st_size=found.st_size,st_mtime_ns=found.st_mtime_ns)
  return found
 monkeypatch.setattr(Path,'lstat',lstat)

@pytest.mark.parametrize('body',[b'',b'ori',b'original',b'ne',b'next'])
def test_known_interrupted_atomic_write_can_be_cleaned(monkeypatch,tmp_path,body):
 nginx=tmp_path/'nginx';nginx.write_bytes(b'original');monkeypatch.setattr(r,'NGINX',nginx)
 temp=tmp_path/'.t24-customer-dialog-next';temp.write_bytes(body);temp.chmod(0o600);pretend_root(monkeypatch,temp)
 r.cleanup_nginx_temp(b'original',b'next');assert not temp.exists()

@pytest.mark.parametrize('kind',['unknown','symlink','writable','nginx_changed'])
def test_recovery_never_unlinks_unrecognized_temp_or_overwrites_thirdparty(monkeypatch,tmp_path,kind):
 nginx=tmp_path/'nginx';nginx.write_bytes(b'thirdparty' if kind=='nginx_changed' else b'original');monkeypatch.setattr(r,'NGINX',nginx)
 temp=tmp_path/'.t24-customer-dialog-next'
 if kind=='symlink':temp.symlink_to(nginx)
 else:temp.write_bytes(b'unknown' if kind=='unknown' else b'ori');temp.chmod(0o666 if kind=='writable' else 0o600)
 pretend_root(monkeypatch,temp)
 with pytest.raises(RuntimeError):r.cleanup_nginx_temp(b'original',b'next')
 assert temp.exists() or temp.is_symlink()

def prepared(monkeypatch,tmp_path,capsys):
 release,selected,runtime,old,nginx,root=setup_public(monkeypatch,tmp_path);r.prepare(release,args(),selected,{})
 capsys.readouterr();a=args();a.review_sha256=r.H((release/'prepared.json').read_bytes());return release,selected,runtime,old,nginx,root,a

def test_activation_only_changes_nginx_and_checks_unchanged_running_backend(monkeypatch,tmp_path,capsys):
 release,selected,runtime,old,nginx,root,a=prepared(monkeypatch,tmp_path,capsys);reload=Mock();monkeypatch.setattr(r,'reload_nginx',reload)
 r.activate(release,a,selected,{})
 assert ('root '+str(root)+';').encode() in nginx.read_bytes() and reload.call_count==1
 receipt=json.loads((release/'deployed.json').read_bytes());assert receipt['crm']==runtime and receipt['backend_unchanged']
 assert receipt['database_modified'] is False and receipt['services_restarted'] is False
 assert (old/'index.html').read_bytes()==b'oldindex'

@pytest.mark.parametrize('target',['new_public','runtime','receipt'])
def test_activation_refuses_unreviewed_mutations_before_nginx_change(monkeypatch,tmp_path,capsys,target):
 release,selected,runtime,old,nginx,root,a=prepared(monkeypatch,tmp_path,capsys);before=nginx.read_bytes()
 if target=='new_public':(root/'assets/new.js').write_bytes(b'unreviewed')
 elif target=='runtime':monkeypatch.setattr(r,'protected_boundary',lambda _:{**runtime,'started':'restarted'})
 else:(release/'prepared.json').write_bytes(b'{}')
 with pytest.raises(RuntimeError):r.activate(release,a,selected,{})
 assert nginx.read_bytes()==before and not (release/'activation-started.json').exists()

def test_failed_public_check_rolls_back_only_nginx(monkeypatch,tmp_path,capsys):
 release,selected,runtime,old,nginx,root,a=prepared(monkeypatch,tmp_path,capsys);before=nginx.read_bytes()
 monkeypatch.setattr(r,'reload_nginx',Mock());monkeypatch.setattr(r,'public_check',Mock(side_effect=RuntimeError('PUBLIC_CHECK_FAILED')))
 with pytest.raises(RuntimeError,match='PUBLIC_CHECK_FAILED'):r.activate(release,a,selected,{})
 assert nginx.read_bytes()==before and root.exists() and (root/'assets/new.js').read_bytes()==b'newchunk'
 result=json.loads(next(release.glob('rollback-*.json')).read_bytes());assert result['stage']=='CUSTOMER_DIALOG_ROLLED_BACK' and result['database_modified'] is False

def test_successful_release_cannot_be_automatically_recovered(monkeypatch,tmp_path,capsys):
 release,selected,_,_,_,_,a=prepared(monkeypatch,tmp_path,capsys);(release/'deployed.json').write_text('{}')
 with pytest.raises(RuntimeError,match='SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_REVIEW'):r.recover(release,a,selected,{})

def test_rollback_refuses_thirdparty_nginx_without_touching_it(monkeypatch,tmp_path,capsys):
 release,selected,runtime,old,nginx,root,a=prepared(monkeypatch,tmp_path,capsys);original,updated=r.nginx_pair(release);nginx.write_bytes(b'thirdparty')
 reload=Mock();monkeypatch.setattr(r,'reload_nginx',reload)
 with pytest.raises(RuntimeError,match='ROLLBACK_INCOMPLETE'):r.rollback(release,{'crm':runtime},{},original,updated,'test')
 assert nginx.read_bytes()==b'thirdparty';reload.assert_not_called()

def test_commands_are_generated_from_immutable_carrier_and_compile_without_execution(monkeypatch,tmp_path,capsys):
 package=tmp_path/c.DIRECTORY;(package/'artifacts').mkdir(parents=True);selected=manifest()
 (package/'release.py').write_bytes(b'helper');(package/'artifacts/manifest.json').write_text(json.dumps(selected));(package/'artifacts/payload.tar.gz').write_bytes(b'payload')
 monkeypatch.chdir(tmp_path);out=tmp_path/'commands';monkeypatch.setattr(sys,'argv',['make','--carrier','a'*40,'--preflight','/opt/t24-crm/releases/preflight.json','--preflight-sha256','b'*64,'--out',str(out)])
 c.main();script=(out/'prepare-command.sh').read_text();code=script.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0];compile(code,'generated','exec')
 assert 'raw.githubusercontent.com' in script and '/'+c.DIRECTORY+'/' in script and "'--phase','prepare'" in script
 assert not (out/'activate-command.sh').exists() and 'backend_after' not in script and "manifest['static_only'] is True" in script

def test_release_program_has_no_backend_mutation_or_service_restart_primitives():
 source=Path(r.__file__).read_text()
 for forbidden in ('docker_request(',"['docker','stop'","['docker','start'","['docker','restart'",'CREATE TABLE','ALTER TABLE','shutil.copy2','backup_to','restore_database','os.environ['):assert forbidden not in source
 assert "['systemctl','reload','nginx']" in source and "mode=ro" in source
