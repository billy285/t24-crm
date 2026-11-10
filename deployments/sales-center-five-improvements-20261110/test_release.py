"""New release scope plus reused exact configuration-preservation regressions."""
import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
adapter=load('quality_release',Path(__file__).with_name('release.py'))
legacy_path=ROOT/'deployments/ringcentral-team-20261109/release.py'
previous=load('previous_release_tests',ROOT/'deployments/beauty-5000-import-geography-20261110/test_release.py')
previous.adapter=adapter
PrivateOrderTests=previous.PrivateOrderTests
CrmOrderTests=previous.CrmOrderTests

class PrivateRoot:
    def __init__(self,path,source):self.path=path;self.source=source
    def __truediv__(self,name):return self.path/name
    def __eq__(self,other):return other is self or other==Path('/opt/t24-crm/releases/sales-center-five-improvements-'+self.source[:12]+'-20261110')
    def resolve(self):return self
    def is_dir(self):return True
    def stat(self):return SimpleNamespace(st_uid=0,st_mode=0o700)

class ScopeTests(unittest.TestCase):
    def fixture(self,mutate=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);folder=Path(tmp.name);source='a'*40
        files={'backend/'+p:'b'*64 for p in adapter.RUNTIME_PATHS};files.update({'static/index.html':'c'*64,'static/app-version.json':'d'*64})
        manifest={'source_sha':source,'baseline_source_sha':adapter.BASE_SOURCE,'frontend_version':'123456789abc','backend_before':{p:None for p in adapter.RUNTIME_PATHS},'files':files,'database_migration':False,'database_writes_by_release':False,'payload_sha256':'0'*64}
        if mutate:mutate(manifest)
        body=json.dumps(manifest).encode();(folder/'manifest.json').write_bytes(body)
        legacy=load('isolated_legacy_'+str(id(self)),legacy_path)
        return adapter.make_release(legacy,SimpleNamespace(release=PrivateRoot(folder,source),manifest_sha256=hashlib.sha256(body).hexdigest())),legacy
    def test_changed_static_and_new_backend_supported_without_migration(self):
        r,m=self.fixture();self.assertEqual(m.OLD,m.NEW);self.assertEqual(m.NEW,'j65bc789b025');self.assertEqual(m.RUNTIME_PATHS,adapter.RUNTIME_PATHS)
    def test_quality_queries_follow_legacy_probe_on_readonly_offline_data(self):
        r,m=self.fixture();events=[]
        original=m.Release.probe
        m.Release.probe=lambda *args:events.append('legacy')
        m.offline_args=lambda root,data,image: ['offline-container',str(data),image]
        def run(args,code,timeout):
            events.append('quality')
            self.assertEqual(args[:3],['offline-container','offline-data','candidate-image'])
            self.assertEqual(code,'OFFLINE_QUALITY_READMODEL_PROBE_FAILED')
            script=args[-1];compile(script,'quality_probe','exec')
            self.assertIn('mode=ro&uri=true',script)
            self.assertIn('sqlite_version_info >= (3,35,0)',script)
            self.assertIn('MerchantPool',script);self.assertIn('SalesLeads',script)
            self.assertIn('group_by(quality)',script)
            return b'QUALITY_READMODELS_VERIFIED_READONLY\n'
        m.run=run
        try:r.probe('offline-data','candidate-image','candidate')
        finally:m.Release.probe=original
        self.assertEqual(events,['legacy','quality'])
    def test_unrelated_backend_member_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'EXACT_PAYLOAD_SCOPE_REQUIRED'):self.fixture(lambda m:m['files'].__setitem__('backend/routers/finance.py','f'*64))
    def test_wrong_prior_source_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'EXACT_BASELINE_SOURCE_REQUIRED'):self.fixture(lambda m:m.__setitem__('baseline_source_sha','f'*40))
    def test_database_write_or_migration_rejected(self):
        for key in ('database_migration','database_writes_by_release'):
            with self.subTest(key=key),self.assertRaisesRegex(RuntimeError,'NO_DATABASE_CHANGES_REQUIRED'):self.fixture(lambda m:m.__setitem__(key,True))
    def test_stale_or_invalid_frontend_version_rejected(self):
        for version in (adapter.BASE_FRONTEND_VERSION,'unknown','a'*64):
            with self.subTest(version=version),self.assertRaisesRegex(RuntimeError,'NEW_REVIEWED_FRONTEND_VERSION_REQUIRED'):self.fixture(lambda m:m.__setitem__('frontend_version',version))
    def test_unpinned_backend_baseline_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'PINNED_BACKEND_BASELINE_REQUIRED'):self.fixture(lambda m:m['backend_before'].__setitem__(next(iter(adapter.RUNTIME_PATHS)),'not-hash'))

if __name__=='__main__':unittest.main()
