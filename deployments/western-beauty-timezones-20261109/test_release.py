import copy,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

LOCAL_HELPER=Path('/Users/billyli/Documents/Codex/2026-10-07/sites-plugin-sites-openai-curated-remote-3/work/t24-crm/work/release-ui/deployments/ringcentral-team-20261109/release.py')
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
adapter=module('timezone_release',Path(__file__).with_name('release.py'))

class PrivateRoot:
 """Local fixture implementing the already-validated root-private directory."""
 def __init__(self,path,source):self.path=path;self.source=source
 def __truediv__(self,part):return self.path/part
 def __eq__(self,other):return other is self or other==Path('/opt/t24-crm/releases/western-beauty-timezones-'+self.source[:12]+'-20261109')
 def resolve(self):return self
 def is_dir(self):return True
 def stat(self):return SimpleNamespace(st_uid=0,st_mode=0o700)

class AdapterTests(unittest.TestCase):
 def fixture(self,extra=False):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);folder=Path(tmp.name);source='a'*40;root=PrivateRoot(folder,source)
  files={'backend/'+p:'b'*64 for p in adapter.RUNTIME_PATHS};files.update({'static/index.html':'c'*64,'static/app-version.json':'d'*64})
  if extra:files['backend/routers/finance.py']='e'*64
  manifest={'source_sha':source,'frontend_version':'123456789abc','backend_before':{p:'f'*64 for p in adapter.RUNTIME_PATHS},'files':files,'payload_sha256':'0'*64}
  body=json.dumps(manifest).encode();(folder/'manifest.json').write_bytes(body)
  legacy=module('legacy_'+str(id(folder)),LOCAL_HELPER)
  self.assertEqual(hashlib.sha256(LOCAL_HELPER.read_bytes()).hexdigest(),adapter.LEGACY_SHA)
  release=adapter.make_release(legacy,SimpleNamespace(release=root,manifest_sha256=hashlib.sha256(body).hexdigest()))
  return release,legacy,folder
 def test_three_file_scope_and_existing_schema(self):
  obj,m,folder=self.fixture();self.assertEqual(len(m.RUNTIME_PATHS),3);self.assertEqual(m.OLD,m.NEW);self.assertEqual(m.NEW,'j65bc789b025');self.assertIn('services/sales_timezones.py',m.RUNTIME_PATHS)
 def test_unrelated_backend_file_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'EXACT_PAYLOAD_SCOPE_REQUIRED'):self.fixture(extra=True)
 def test_version_retry_observes_without_repeating_activation(self):
  obj,m,folder=self.fixture();default=[];fresh=[]
  def public_check(self):
   default.append(True)
   if len(default)<3:raise RuntimeError('PUBLIC_FRONTEND_VERSION_MISMATCH')
  def run(*unused,**kw):fresh.append(True);return b'{"version":"123456789abc"}'
  with patch.object(m.Release,'public_check',public_check),patch.object(m,'run',run),patch.object(adapter.time,'sleep',lambda seconds:None):obj.public_retry()
  self.assertEqual(len(default),3);self.assertEqual(len(fresh),1)
 def test_version_retry_is_bounded(self):
  obj,m,folder=self.fixture();calls=[]
  def failure(self):calls.append(True);raise RuntimeError('PUBLIC_FRONTEND_VERSION_MISMATCH')
  with patch.object(m.Release,'public_check',failure),patch.object(adapter.time,'sleep',lambda seconds:None):
   with self.assertRaisesRegex(RuntimeError,'PUBLIC_FRONTEND_VERSION_MISMATCH'):obj.public_retry()
  self.assertEqual(len(calls),8)

class PrivateOrderTests(unittest.TestCase):
 def fixture(self):
  m=module('private_order_'+str(id(self)),LOCAL_HELPER)
  info={'Id':'synthetic-api-id','Image':'synthetic-image','Config':{'Env':['SYNTHETIC=value']},'HostConfig':{'ReadonlyRootfs':True},'Mounts':[{'Type':'bind','Source':'/synthetic/data','Destination':'/data','RW':True},{'Type':'bind','Source':'/synthetic/key','Destination':'/key','RW':False}],'NetworkSettings':{'Networks':{'synthetic':{'Aliases':['api']}}},'State':{'Running':True,'StartedAt':'2026-11-01T00:00:00Z'}}
  return m,info,m.runtime(info)
 def test_only_mount_order_is_accepted_with_exact_frozen_hash(self):
  m,info,expected=self.fixture();info['Mounts'].reverse();result,proof=adapter.equivalent_private_runtime(m,info,expected)
  self.assertEqual(result,expected);self.assertTrue(proof['exact_configuration_equivalence']);self.assertEqual(proof['mount_order'],[1,0])
 def test_identity_start_and_running_changes_rejected(self):
  for target in ('id','image','started','running'):
   with self.subTest(target=target):
    m,info,expected=self.fixture()
    if target=='id':info['Id']='different-id'
    elif target=='image':info['Image']='different-image'
    elif target=='started':info['State']['StartedAt']='later-start'
    else:info['State']['Running']=False
    with self.assertRaisesRegex(RuntimeError,'PRIVATE_'):adapter.equivalent_private_runtime(m,info,expected)
 def test_real_configuration_mount_or_network_changes_rejected(self):
  for target in ('env','host','network','source','destination','rw','add','remove'):
   with self.subTest(target=target):
    m,info,expected=self.fixture();info['Mounts'].reverse()
    if target=='env':info['Config']['Env']=['SYNTHETIC=changed']
    elif target=='host':info['HostConfig']['ReadonlyRootfs']=False
    elif target=='network':info['NetworkSettings']['Networks']['synthetic']['Aliases']=['changed']
    elif target=='source':info['Mounts'][0]['Source']='/different/source'
    elif target=='destination':info['Mounts'][0]['Destination']='/different/destination'
    elif target=='rw':info['Mounts'][0]['RW']=True
    elif target=='add':info['Mounts'].append({'Source':'extra','Destination':'extra'})
    else:info['Mounts'].pop()
    with self.assertRaisesRegex(RuntimeError,'PRIVATE_'):adapter.equivalent_private_runtime(m,info,expected)
 def test_wrapper_preserves_baseline_and_records_bounded_equivalence(self):
  m,info,expected=self.fixture();info['Mounts'].reverse()
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw);baseline=json.dumps({'private_runtimes':{'t24-private-api':expected}}).encode();(root/'baseline.json').write_bytes(baseline)
   m.private_runtimes=lambda:{'legacy':'raw'};m.optional=lambda name:info if name=='t24-private-api' else None
   adapter.install_private_order_guard(m,root,'a'*40);self.assertEqual(m.private_runtimes(),{'t24-private-api':expected});self.assertEqual((root/'baseline.json').read_bytes(),baseline)
   proof=json.loads((root/'private-runtime-mount-order-equivalence.json').read_bytes());self.assertTrue(proof['raw_baseline_preserved']);self.assertEqual(proof['expected_private_runtimes'],{'t24-private-api':expected})
   self.assertEqual(m.private_runtimes(),{'t24-private-api':expected})
 def test_wrapper_before_capture_leaves_original_observation_unchanged(self):
  m,info,expected=self.fixture()
  with tempfile.TemporaryDirectory() as raw:
   m.private_runtimes=lambda:{'legacy':'raw'};adapter.install_private_order_guard(m,Path(raw),'a'*40);self.assertEqual(m.private_runtimes(),{'legacy':'raw'})

class CrmOrderTests(unittest.TestCase):
 def fixture(self):
  m=module('crm_order_'+str(id(self)),LOCAL_HELPER)
  info={'Id':adapter.BASE_ID,'Image':'synthetic-image','Config':{'Env':['SYNTHETIC=value']},'HostConfig':{'ReadonlyRootfs':False},'Mounts':[{'Type':'bind','Source':'/synthetic/data','Destination':'/data','RW':True},{'Type':'bind','Source':'/synthetic/key','Destination':'/key','RW':False},{'Type':'bind','Source':'/synthetic/logs','Destination':'/logs','RW':True}],'NetworkSettings':{'Networks':{'synthetic':{'Aliases':['crm']}}},'State':{'Running':True,'StartedAt':'2026-11-01T00:00:00Z'}}
  expected=m.runtime({**info,'Mounts':sorted(info['Mounts'],key=m.canonical)})
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name);(root/'baseline.json').write_text(json.dumps({'runtime':expected}));return m,info,expected,root
 def test_main_three_mounts_sort_matches_frozen_hash_and_preserves_baseline(self):
  m,info,expected,root=self.fixture();before=(root/'baseline.json').read_bytes();info['Mounts'].reverse()
  with patch.object(adapter,'BASE_CONFIG_SHA',expected['config']):adapter.install_crm_mount_order_guard(m,root,'a'*40);self.assertEqual(m.runtime(info),expected)
  self.assertEqual((root/'baseline.json').read_bytes(),before);self.assertTrue(json.loads((root/'crm-runtime-mount-order-equivalence.json').read_bytes())['raw_baseline_preserved'])
 def test_actual_start_image_and_unknown_id_remain_visible_to_caller(self):
  for target in ('started','image','id'):
   with self.subTest(target=target):
    m,info,expected,root=self.fixture();raw_runtime=m.runtime
    if target=='started':info['State']['StartedAt']='new-start'
    elif target=='image':info['Image']='new-image'
    else:info['Id']='unknown-id'
    with patch.object(adapter,'BASE_CONFIG_SHA',expected['config']):adapter.install_crm_mount_order_guard(m,root,'a'*40);actual=m.runtime(info)
    self.assertNotEqual(actual,expected)
    if target=='id':self.assertEqual(actual,raw_runtime(info))
 def test_stopped_original_is_valid_but_real_configuration_drift_fails(self):
  m,info,expected,root=self.fixture();info['State']['Running']=False
  with patch.object(adapter,'BASE_CONFIG_SHA',expected['config']):
   adapter.install_crm_mount_order_guard(m,root,'a'*40);self.assertEqual(m.runtime(info),expected)
   info['Config']['Env']=['SYNTHETIC=changed']
   with self.assertRaisesRegex(RuntimeError,'CRM_CONFIGURATION_DRIFT'):m.runtime(info)
 def test_candidate_runtime_is_deterministic_across_later_status_receipt(self):
  m,info,expected,root=self.fixture();info['Id']='candidate-id';(root/'candidate.json').write_text(json.dumps({'id':'candidate-id'}))
  adapter.install_crm_mount_order_guard(m,root,'a'*40);first=m.runtime(info);(root/'deployed.json').write_text(json.dumps({'runtime':first}))
  second_module=module('fresh_crm_status',LOCAL_HELPER);info['Mounts'].reverse();adapter.install_crm_mount_order_guard(second_module,root,'a'*40);later=second_module.runtime(info)
  self.assertEqual(later,json.loads((root/'deployed.json').read_bytes())['runtime'])
  info['HostConfig']['ReadonlyRootfs']=True;self.assertNotEqual(second_module.runtime(info),first)
 def test_private_unknown_runtime_is_not_sorted(self):
  m,info,expected,root=self.fixture();info['Id']='private-api-id';info['Mounts'].reverse();raw=m.runtime(info);adapter.install_crm_mount_order_guard(m,root,'a'*40);self.assertEqual(m.runtime(info),raw)

if __name__=='__main__':unittest.main()
