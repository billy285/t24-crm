"""New release scope plus reused exact configuration-preservation regressions."""
import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
adapter=load('knowledge_release',Path(__file__).with_name('release.py'))
legacy_path=ROOT/'deployments/ringcentral-team-20261109/release.py'
previous=load('previous_release_tests',ROOT/'deployments/beauty-5000-import-geography-20261110/test_release.py')
previous.adapter=adapter
PrivateOrderTests=previous.PrivateOrderTests
CrmOrderTests=previous.CrmOrderTests

class PrivateRoot:
    def __init__(self,path,source):self.path=path;self.source=source
    def __truediv__(self,name):return self.path/name
    def __eq__(self,other):return other is self or other==Path('/opt/t24-crm/releases/beautyos-sales-knowledge-'+self.source[:12]+'-20261110')
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
        return adapter.make_release(legacy,SimpleNamespace(release=PrivateRoot(folder,source),manifest_sha256=hashlib.sha256(body).hexdigest(),phase="prepare",prepared_sha256=None)),legacy
    def test_changed_static_and_new_backend_supported_without_migration(self):
        r,m=self.fixture();self.assertEqual(m.OLD,m.NEW);self.assertEqual(m.NEW,'j65bc789b025');self.assertEqual(m.RUNTIME_PATHS,adapter.RUNTIME_PATHS)
    def test_knowledge_probe_follows_startup_and_reads_only_offline_database(self):
        r,m=self.fixture();events=[]
        original=m.Release.probe
        m.Release.probe=lambda *args:events.append('legacy')
        m.offline_args=lambda root,data,image: ['offline-container',str(data),image]
        def run(args,code,timeout):
            events.append('knowledge')
            self.assertEqual(args[:3],['offline-container','offline-data','candidate-image'])
            self.assertEqual(code,'OFFLINE_KNOWLEDGE_READMODEL_PROBE_FAILED')
            script=args[-1];compile(script,'knowledge_probe','exec')
            self.assertIn('mode=ro&uri=true',script)
            self.assertIn('await list_articles(',script)
            self.assertIn('==60',script);self.assertIn('==20',script)
            self.assertIn('canonical_pack_hash()',script)
            for forbidden in ('install_beautyos_pack','db.commit','db.add','INSERT','UPDATE','DELETE'):
                self.assertNotIn(forbidden,script)
            return b'KNOWLEDGE_READMODELS_VERIFIED_READONLY\n'
        m.run=run
        try:r.probe('offline-data','candidate-image','candidate')
        finally:m.Release.probe=original
        self.assertEqual(events,['legacy','knowledge'])
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



class LifecycleTests(unittest.TestCase):
    fixture=ScopeTests.fixture
    def test_prepare_probes_copy_and_rejects_rows_or_schema_mutation_before_publish(self):
        for drift in (None,'rows','schema'):
            with self.subTest(drift=drift):
                r,m=self.fixture();events=[];snapshots=[];schemas=[]
                old={'Image':adapter.BASE_IMAGE};r.boundary=lambda:old
                r.extract=lambda:events.append('extract');r.build=lambda old:'sha256:'+'f'*64
                r.expected=lambda:{'existing.py':'untouched'};r.image_inventory=lambda image:r.expected()
                def backup(source,target):
                    self.assertEqual(source,m.DB);self.assertEqual(target,r.root/'probe-data/crm_prod.db');events.append('backup-copy')
                def snapshot(path):
                    self.assertEqual(path,r.root/'probe-data/crm_prod.db');snapshots.append(True)
                    return {'rows':1 if drift=='rows' and len(snapshots)>1 else 0}
                def schema(path):
                    self.assertEqual(path,r.root/'probe-data/crm_prod.db');schemas.append(True)
                    return {'shape':1 if drift=='schema' and len(schemas)>1 else 0}
                m.backup=backup;m.snapshot=snapshot;m.schema=schema;m.revision=lambda path:adapter.SCHEMA
                r.probe=lambda *a:events.append('readonly-probe');r.stage_public=lambda:events.append('publish-static')
                if drift:
                    with self.assertRaisesRegex(RuntimeError,'OFFLINE_DATA_OR_SCHEMA_CHANGED'):r.prepare()
                    self.assertNotIn('publish-static',events);self.assertFalse((r.root/'prepared.json').exists())
                else:
                    result=r.prepare();self.assertEqual(events,['extract','backup-copy','readonly-probe','publish-static'])
                    self.assertTrue(result['offline_rows_and_schema_unchanged']);self.assertFalse(result['database_migration'])
                    self.assertEqual(result['prepared_sha256'],adapter.H((r.root/'prepared.json').read_bytes()))
                    self.assertLess(len(json.dumps(result)),2000)
    def prepared_fixture(self,phase='activate'):
        r,m=self.fixture();r.args.phase=phase
        p={'stage':'PREPARED','source_sha':r.source,'manifest_sha256':r.args.manifest_sha256,
           'schema_revision':adapter.SCHEMA,'original_image':adapter.BASE_IMAGE,
           'candidate_image':'sha256:'+'f'*64,'public_root':str(r.public),
           'offline_candidate_ready':True,'offline_knowledge_readmodels_verified_readonly':True,
           'offline_rows_and_schema_unchanged':True,'database_migration':False}
        m.write(r.root/'prepared.json',p)
        r.args.prepared_sha256=adapter.H((r.root/'prepared.json').read_bytes())
        return r,m,p
    def test_reviewed_prepared_required_for_activate_and_recover(self):
        for phase in ('activate','recover'):
            for pin in (None,'0'*64,'invalid'):
                with self.subTest(phase=phase,pin=pin):
                    r,m,p=self.prepared_fixture(phase);r.args.prepared_sha256=pin
                    with self.assertRaisesRegex(RuntimeError,'REVIEWED_PREPARED_HASH_REQUIRED'):r.prepared()
    def test_prepared_exact_bytes_pin_rejects_even_whitespace_changes(self):
        r,m,p=self.prepared_fixture();path=r.root/'prepared.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(RuntimeError,'REVIEWED_PREPARED_HASH_REQUIRED'):r.prepared()
    def test_valid_prepared_and_candidate_scope(self):
        r,m,p=self.prepared_fixture();self.assertEqual(r.prepared(),p)
        for field,bad in [('original_image','sha256:'+'e'*64),('candidate_image','invalid'),('public_root','/wrong'),('offline_rows_and_schema_unchanged',False)]:
            with self.subTest(field=field):
                r,m,p=self.prepared_fixture();p[field]=bad;(r.root/'prepared.json').write_text(json.dumps(p))
                r.args.prepared_sha256=adapter.H((r.root/'prepared.json').read_bytes())
                with self.assertRaisesRegex(RuntimeError,'EXACT_PREPARED_CANDIDATE_REQUIRED|NO_MIGRATION_REHEARSAL_REQUIRED'):r.prepared()
    def test_capture_accepts_only_frozen_static_release_and_runtime(self):
        r,m=self.fixture()
        expected={'id':adapter.BASE_ID,'image':adapter.BASE_IMAGE,'config':adapter.BASE_CONFIG_SHA,'started':adapter.BASE_STARTED}
        public=Path('/var/www/t24-crm-public/merchant-pool-filter-state-dcccb1227b91-20261110')
        receipt={'stage':'STATIC_DEPLOYED','source_sha':adapter.BASE_STATIC_SOURCE,'backend_source_sha':adapter.BASE_SOURCE,'frontend_version':adapter.BASE_FRONTEND_VERSION,'schema_unchanged':True,'runtime':dict(expected),'public_root':str(public)}
        m.read=lambda path: {'version':adapter.BASE_FRONTEND_VERSION} if path.name=='app-version.json' else receipt
        m.inspect=lambda name:{'Id':adapter.BASE_ID,'Image':adapter.BASE_IMAGE};m.runtime=lambda info:expected;m.public_root=lambda:public
        original=m.Release.capture;m.Release.capture=lambda self:{'stage':'CAPTURED'}
        try:
            self.assertEqual(r.capture(),{'stage':'CAPTURED'})
            receipt['backend_source_sha']='b'*40
            with self.assertRaisesRegex(RuntimeError,'PREVIOUS_DEPLOYED_RECEIPT_REQUIRED'):r.capture()
            receipt['backend_source_sha']=adapter.BASE_SOURCE;expected['started']='drift'
            with self.assertRaisesRegex(RuntimeError,'EXACT_LIVE_TIMEZONE_BASE_REQUIRED'):r.capture()
        finally:m.Release.capture=original
    def test_recover_marker_drift_rejects_before_any_server_operation(self):
        r,m,p=self.prepared_fixture('recover')
        m.write(r.root/'baseline.json',{'runtime':{'id':adapter.BASE_ID}})
        m.write(r.root/'activation-started.json',{'original_id':adapter.BASE_ID,'prepared_sha256':'0'*64,'database_migration':False})
        m.inspect=lambda *a: self.fail('marker must be checked before inspect/mutations')
        with self.assertRaisesRegex(RuntimeError,'ACTIVATION_SCOPE_DRIFT'):r.recover()
    def test_no_migrate_or_business_database_restore_in_overrides(self):
        import ast
        tree=ast.parse(Path(adapter.__file__).read_text())
        methods={n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        for name in ('prepare','activate','recover','probe'):
            calls=[n for n in ast.walk(methods[name]) if isinstance(n,ast.Call)]
            for call in calls:
                if isinstance(call.func,ast.Attribute):self.assertNotIn(call.func.attr,('migrate','restore'))
        recovery=ast.get_source_segment(Path(adapter.__file__).read_text(),methods['recover'])
        self.assertNotIn('backup(',recovery);self.assertNotIn('snapshot(',recovery)
        self.assertIn('DATABASE_FILE_IDENTITY_CHANGED',recovery)
        self.assertIn('UNKNOWN_NGINX_NOT_REPLACED',recovery)
    def test_full_backend_preserved_by_incremental_expected_inventory(self):
        r,m=self.fixture();m.write(r.root/'baseline.json',{'backend_inventory':{'unrelated.py':'keep','routers/sales_knowledge.py':'old'}})
        expected=r.expected();self.assertEqual(expected['unrelated.py'],'keep')
        for path in adapter.RUNTIME_PATHS:self.assertEqual(expected[path],r.manifest['files']['backend/'+path])

if __name__=='__main__':unittest.main()
