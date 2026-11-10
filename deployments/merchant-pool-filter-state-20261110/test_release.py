"""Local-only static guards and recovery flow. No server command is executed."""
import copy, hashlib, importlib.util, json, stat, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('static_filter',HERE/'release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
H=lambda b:hashlib.sha256(b).hexdigest()
SOURCE='a'*40
PUBLIC='/var/www/t24-crm-public/merchant-pool-filter-state-'+SOURCE[:12]+'-20261110'

def manifest():
 return dict(source_sha=SOURCE,baseline_source_sha=r.BASE_SOURCE,baseline_frontend_version=r.BASE_FRONTEND,frontend_version='b'*12,
  static_only=True,**{k:False for k in r.FALSE_FLAGS},backend_before={'routers/merchant_pool.py':'c'*64},
  expected_private={'t24-private-api':{},'t24-private-worker':{}},files={'static/index.html':'d'*64,'static/app-version.json':'e'*64},payload_sha256='f'*64)

class File:
 def __init__(self,body=b'',exists=True):self.body=body;self.present=exists;self.uid=0;self.mode=stat.S_IFREG|0o600;self.links=1;self.symlink=False
 def lstat(self):return SimpleNamespace(st_uid=self.uid,st_mode=self.mode,st_nlink=self.links)
 def resolve(self):return object() if self.symlink else self
 def read_bytes(self):return self.body
 def exists(self):return self.present

class Root:
 def __init__(self):self.files={}
 def __truediv__(self,key):return self.files.setdefault(key,File(exists=False))
 def __eq__(self,other):return other is self or other==Path('/opt/t24-crm/releases/merchant-pool-filter-state-'+SOURCE[:12]+'-20261110')
 def resolve(self):return self
 def is_dir(self):return True
 def stat(self):return SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o700)

class Tests(unittest.TestCase):
 def test_static_manifest_and_safe_paths(self):
  self.assertIs(r.validate_manifest(manifest())['static_only'],True)
  for name in ['index.html','app-version.json','assets/chunk-a.js','assets/font.woff2','t2-marketing-logo.png']:
   self.assertTrue(r.static_path(name),name)
  for name in ['../x','assets/../secret.js','assets//x.js','/assets/x.js','.env','assets/.x.js','leads.csv','assets/leads.json','assets/db.sqlite','assets/code.js.map']:
   self.assertFalse(r.static_path(name),name)
 def test_backend_member_raw_data_and_all_mutation_flags_rejected(self):
  for name in ['backend/services/anything.py','static/assets/contacts.csv','static/.env']:
   value=manifest();value['files'][name]='f'*64
   with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'ONLY_STATIC_PAYLOAD_ALLOWED'):r.validate_manifest(value)
  for flag in r.FALSE_FLAGS:
   value=manifest();value[flag]=True
   with self.subTest(flag=flag),self.assertRaisesRegex(RuntimeError,'STATIC_ONLY_REQUIRED'):r.validate_manifest(value)
 def test_old_version_wrong_source_or_private_set_rejected(self):
  for key,value,code in [('frontend_version',r.BASE_FRONTEND,'NEW_FRONTEND_REQUIRED'),('baseline_source_sha','f'*40,'EXACT_BASELINE_REQUIRED'),('expected_private',{},'EXACT_PRIVATE_BASELINE_REQUIRED')]:
   v=manifest();v[key]=value
   with self.subTest(key=key),self.assertRaisesRegex(RuntimeError,code):r.validate_manifest(v)
 def test_protected_state_hash_owner_mode_links_and_symlink(self):
  file=File(b'correct');self.assertEqual(r.protected(file,H(b'correct')),b'correct')
  with self.assertRaisesRegex(RuntimeError,'STATE_HASH_MISMATCH'):r.protected(file,'0'*64)
  for attr,value in [('uid',501),('mode',stat.S_IFREG|0o644),('links',2),('symlink',True)]:
   bad=File(b'correct');setattr(bad,attr,value)
   with self.subTest(attr=attr),self.assertRaisesRegex(RuntimeError,'ROOT_PRIVATE_FILE_REQUIRED'):r.protected(bad)
 def fixture(self):
  root=Root();body=json.dumps(manifest()).encode();(root/'manifest.json').body=body;(root/'manifest.json').present=True
  old=('server { root '+str(r.OLD_PUBLIC)+'; }').encode();(root/'nginx-before.conf').body=old;(root/'nginx-before.conf').present=True
  class Base:
   def baseline(self):return {}
  writes=[]
  def write(path,value):
   self.assertFalse(path.exists());path.body=json.dumps(value,sort_keys=True).encode();path.present=True;writes.append(value);return H(path.body)
  m=SimpleNamespace(Release=Base,read=lambda p:json.loads(p.read_bytes()),write=write,NGINX=File(old),digest=lambda v:H(json.dumps(v,sort_keys=True,separators=(',',':')).encode()))
  args=SimpleNamespace(release=root,manifest_sha256=H(body),prepared_sha256=None)
  release=r.make_release(m,args);assets={'index.html':'frozen'}
  prepared=dict(stage='STATIC_PREPARED',source_sha=SOURCE,frontend_version='b'*12,manifest_sha256=H(body),runtime=r.BASE_RUNTIME,
   static_only=True,database_writes=False,container_restarts=False,public_inventory=assets,next_nginx_sha256=H(release.nginx_pair()[1]))
  (root/'prepared.json').body=json.dumps(prepared).encode();(root/'prepared.json').present=True;args.prepared_sha256=H((root/'prepared.json').body)
  observed=[]
  def boundary(updated=False):
   self.assertEqual(m.NGINX.body,release.nginx_pair()[1 if updated else 0]);observed.append(('boundary',updated));return r.BASE_RUNTIME
  def swap(expected,body):
   self.assertEqual(m.NGINX.body,expected);observed.append(('swap',));m.NGINX.body=body
  release.boundary=boundary;release.swap=swap;release.static_check=lambda:None;release.public_check_version=lambda v:observed.append(('public',v))
  return release,m,args,root,assets,observed
 def test_prepare_review_hash_required_and_assets_drift_rejected(self):
  release,m,args,root,assets,events=self.fixture()
  with patch.object(r,'inventory',return_value=assets):
   args.prepared_sha256=None
   with self.assertRaisesRegex(RuntimeError,'REVIEWED_PREPARED_SHA_REQUIRED'):release.reviewed()
   args.prepared_sha256='0'*64
   with self.assertRaisesRegex(RuntimeError,'STATE_HASH_MISMATCH'):release.reviewed()
   args.prepared_sha256=H((root/'prepared.json').body)
  with patch.object(r,'inventory',return_value={'index.html':'changed'}):
   with self.assertRaisesRegex(RuntimeError,'PREPARED_ASSET_OR_NGINX_DRIFT'):release.reviewed()
 def test_prepare_keeps_large_inventory_private_but_prints_only_bounded_summary(self):
  release,m,args,root,assets,events=self.fixture();(root/'prepared.json').present=False
  release.extract=lambda:None;release.stage_public=lambda:None
  large={f'assets/retained-{i:04d}.js':'a'*64 for i in range(700)}
  with patch.object(r,'inventory',return_value=large):summary=release.prepare()
  self.assertNotIn('public_inventory',summary);self.assertEqual(summary['static_files'],700)
  self.assertEqual(summary['public_inventory_sha256'],m.digest(large));self.assertLess(len(json.dumps(summary)),2000)
  self.assertEqual(m.read(root/'prepared.json')['public_inventory'],large)
  self.assertGreater(len((root/'prepared.json').body),60000);self.assertEqual(summary['prepared_sha256'],H((root/'prepared.json').body))
 def test_single_root_change_and_successful_static_activation_no_service_calls(self):
  release,m,args,root,assets,events=self.fixture()
  with patch.object(r,'inventory',return_value=assets):
   value=release.activate();self.assertEqual(value['stage'],'STATIC_DEPLOYED');self.assertEqual(value['runtime'],r.BASE_RUNTIME)
   self.assertFalse(value['database_writes']);self.assertFalse(value['container_restarts']);self.assertTrue(value['nginx_reload_only'])
   with self.assertRaisesRegex(RuntimeError,'ACTIVATION_ALREADY_STARTED'):release.activate()
  old,new=release.nginx_pair();self.assertEqual(new.replace(PUBLIC.encode(),str(r.OLD_PUBLIC).encode()),old)
 def test_activation_failure_restores_only_old_nginx_bytes(self):
  release,m,args,root,assets,events=self.fixture()
  release.finish=lambda:(_ for _ in ()).throw(RuntimeError('SYNTHETIC_PUBLIC_FAILURE'))
  with patch.object(r,'inventory',return_value=assets):
   with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_PUBLIC_FAILURE'):release.activate()
  self.assertEqual(m.NGINX.body,release.nginx_pair()[0]);self.assertEqual(sum(e[0]=='swap' for e in events),2)
  self.assertEqual(m.read(root/'recovered.json')['stage'],'STATIC_RECOVERED')
 def test_unknown_nginx_is_never_recovered(self):
  release,m,args,root,assets,events=self.fixture();(root/'activation-started.json').body=json.dumps({'prepared_sha256':args.prepared_sha256,'source_sha':SOURCE}).encode()
  m.NGINX.body=b'unrelated current nginx'
  with patch.object(r,'inventory',return_value=assets):
   with self.assertRaisesRegex(RuntimeError,'UNKNOWN_NGINX_NOT_REPLACED'):release.recover()
  self.assertFalse(any(e[0]=='swap' for e in events))
 def test_current_runtime_and_backend_hashes_match_saved_deployment(self):
  repo=HERE.parents[1];work=Path('/Users/billyli/Documents/Codex/2026-11-08/t/work/sales-center-five-improvements-20261110')
  self.assertEqual(json.loads((work/'deployed.json').read_text())['runtime'],r.BASE_RUNTIME)
  previous=json.loads((repo/'deployments/sales-center-five-improvements-20261110/manifest.json').read_text())
  for name,sha in previous['files'].items():
   if name.startswith('backend/'):
    self.assertEqual(H(subprocess.check_output(['git','show',r.BASE_SOURCE+':app/'+name],cwd=repo)),sha,name)
 def test_helper_has_no_backend_container_or_database_mutation_entrypoints(self):
  source=(HERE/'release.py').read_text()
  for forbidden in ["['docker','build'","['docker','stop'","['docker','start'","['docker','rename'",'self.build(','.migrate(','.backup(','.snapshot(']:self.assertNotIn(forbidden,source)
 def tools(self,infos):
  canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':')).encode()
  def runtime(info):
   return dict(id=info['Id'],image=info['Image'],started=info['State']['StartedAt'],config=H(canonical({k:info[k] for k in ('Config','HostConfig','Mounts')})))
  m=SimpleNamespace(runtime=runtime,canonical=canonical,optional=lambda name:infos.get(name),private_runtimes=lambda:{})
  return m,runtime
 def info(self,id,mounts=3):
  return {'Id':id,'Image':'image','State':{'Running':True,'StartedAt':'started'},'Config':{'Env':['SYNTHETIC=1']},'HostConfig':{'ReadonlyRootfs':False},'Mounts':[{'Source':'/synthetic/'+str(i),'Destination':'/target/'+str(i),'RW':True} for i in range(mounts)]}
 def test_crm_complete_mount_sort_does_not_hide_configuration_or_restart_drift(self):
  info=self.info(r.BASE_RUNTIME['id']);m,original=self.tools({});expected=original({**info,'Mounts':sorted(info['Mounts'],key=m.canonical)})
  with patch.dict(r.BASE_RUNTIME,expected):
   r.install_observation_guards(m,Root());info['Mounts'].reverse();self.assertEqual(m.runtime(info),expected)
   info['State']['StartedAt']='changed';self.assertNotEqual(m.runtime(info),expected)
   info['Config']['Env']=['SYNTHETIC=changed']
   with self.assertRaisesRegex(RuntimeError,'CRM_CONFIGURATION_DRIFT'):m.runtime(info)
 def test_private_mount_permutation_only_and_stopped_or_configuration_changes_rejected(self):
  infos={name:self.info(name,2) for name in ('t24-private-api','t24-private-worker')};m,original=self.tools(infos)
  m.STATIC_EXPECTED_PRIVATE={name:original(info) for name,info in infos.items()};r.install_observation_guards(m,Root())
  for info in infos.values():info['Mounts'].reverse()
  self.assertEqual(m.private_runtimes(),m.STATIC_EXPECTED_PRIVATE)
  infos['t24-private-api']['State']['Running']=False
  with self.assertRaisesRegex(RuntimeError,'PRIVATE_SERVICE_IDENTITY_DRIFT'):m.private_runtimes()
  infos['t24-private-api']['State']['Running']=True;infos['t24-private-api']['HostConfig']['ReadonlyRootfs']=True
  with self.assertRaisesRegex(RuntimeError,'PRIVATE_CONFIGURATION_DRIFT'):m.private_runtimes()

if __name__=='__main__':unittest.main()
