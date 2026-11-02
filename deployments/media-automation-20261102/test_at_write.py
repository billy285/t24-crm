import copy,hashlib,importlib.util,json,os,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
a=load('_test_at_write','at_write_release.py');r=load('_test_at_write_base','release.py')
def rows():
    return {name:{'count':1,'rows_sha256':r.H(json.dumps([r.OLD_REVISION]).encode()) if name=='alembic_version' else 'a'*64,'shape_sha256':'b'*64} for name in ['alembic_version']+['table_'+str(i) for i in range(161)]}
def metadata():return {'pragma_sha256':'c'*64,'sequence_exists':True,'sequence_sha256':r.digest([('table_0',1)]),'sequence_values':{'table_0':1}}
class BoundaryTests(unittest.TestCase):
    def state(self):
        old=rows();current=copy.deepcopy(old);current['table_0'].update(count=3,rows_sha256='d'*64);defs=[['table',n,n,'CREATE TABLE '+n+' (id INTEGER)'] for n in old];state={'rows':current,'table_definitions':defs,'database_metadata':metadata(),'schema_sha256':'e'*64,'database_identity':[1,2]};records={}
        def record(name,value):records[name]=copy.deepcopy(value);return r.H(r.encoded(value))
        obj=types.SimpleNamespace(r=r,original_proof={'rows':old,'crm':{'id':'old'}},stable_sample=lambda old:copy.deepcopy(state),record=record,baseline=None,baseline_sha=None)
        baseline=a.Methods.capture_baseline(obj,{'Id':'old'},{'Id':'new'})
        fake=types.SimpleNamespace(immutable=lambda **kw:'schema',load_baseline=lambda **kw:baseline,rows=lambda:copy.deepcopy(state['rows']),definitions=lambda:copy.deepcopy(state['table_definitions']),c=types.SimpleNamespace(metadata=lambda path:copy.deepcopy(state['database_metadata']),retained=types.SimpleNamespace(sequence_boundary=lambda x,y:r.need(x==y,'EXACT_ALL_SEQUENCES_REQUIRED'))),m=types.SimpleNamespace(BUSINESS=Path('/synthetic/db')),r=r)
        return obj,fake,state,records
    def test_legitimate_pre_stop_updates_become_exact_baseline(self):
        obj,fake,state,records=self.state();self.assertEqual(obj.baseline['rows']['table_0']['count'],3);self.assertEqual(records['activation-before-change-summary.json']['changed_tables'],[{'table':'table_0','before_count':1,'at_write_count':3}]);a.Methods.protections(fake)
    def test_every_one_of162_tables_rejects_post_stop_change(self):
        obj,fake,state,_=self.state()
        for name in state['rows']:
            original=state['rows'][name]['rows_sha256'];state['rows'][name]['rows_sha256']='f'*64
            with self.subTest(table=name),self.assertRaises(RuntimeError):a.Methods.protections(fake)
            state['rows'][name]['rows_sha256']=original
    def test_any_sequence_change_rejected_after_stop(self):
        _,fake,state,_=self.state();state['database_metadata']['sequence_values']['table_0']=2
        with self.assertRaisesRegex(RuntimeError,'EXACT_ALL_SEQUENCES_REQUIRED'):a.Methods.protections(fake)
    def test_two_quiescent_samples_must_be_identical(self):
        obj,_,state,_=self.state();counter=iter([state,{**state,'schema_sha256':'f'*64}]);obj.stable_sample=lambda old:copy.deepcopy(next(counter))
        with self.assertRaisesRegex(RuntimeError,'QUIESCENT_ALL162_SAMPLES_CHANGED'):a.Methods.capture_baseline(obj,{'Id':'old'},{'Id':'new'})
    def test_record_failure_before_identity_does_not_authorize_migration(self):
        obj,_,_,records=self.state();records.clear()
        def record(name,value):
            if name=='activation-baseline-identity.json':raise OSError('synthetic full disk')
            records[name]=value;return r.H(r.encoded(value))
        obj.record=record;obj.baseline=None
        with self.assertRaises(OSError):a.Methods.capture_baseline(obj,{'Id':'old'},{'Id':'new'})
        self.assertIsNone(obj.baseline);self.assertNotIn('activation-baseline-identity.json',records)
    def test_original_schema_changes_always_rejected(self):
        _,fake,state,_=self.state();state['table_definitions'].append(['index','injected','table_0','CREATE INDEX injected ON table_0(id)'])
        with self.assertRaises(RuntimeError):a.Methods.protections(fake)
    def test_no_old_rows_are_consulted_before_baseline_exists(self):
        fake=types.SimpleNamespace(immutable=lambda **kw:'immutable-verified',load_baseline=lambda **kw:None)
        self.assertEqual(a.Methods.protections(fake),'immutable-verified')

class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.p=Path(self.temp.name);self.db=self.p/'data'/'crm.db';self.db.parent.mkdir();self.db.write_bytes(b'synthetic');self.proc=self.p/'proc';self.proc.mkdir()
    def tearDown(self):self.temp.cleanup()
    def fd(self,pid,index,path,mode):
        proc=self.proc/str(pid);(proc/'fd').mkdir(parents=True,exist_ok=True);(proc/'fdinfo').mkdir(exist_ok=True);(proc/'fd'/str(index)).symlink_to(path);(proc/'fdinfo'/str(index)).write_text('flags:\t'+format(mode,'o')+'\n')
    def test_readonly_private_database_reader_is_allowed(self):self.fd(1,3,self.db,os.O_RDONLY);self.assertEqual(a.no_open_database_fds(self.db,self.proc)['readonly_database_processes'],1)
    def test_readonly_sqlite_connection_shm_lock_handle_is_allowed(self):
        shm=Path(str(self.db)+'-shm');shm.write_bytes(b'shm');self.fd(1,3,self.db,os.O_RDONLY);self.fd(1,4,shm,os.O_RDWR);a.no_open_database_fds(self.db,self.proc)
    def test_writable_database_handle_rejected(self):
        self.fd(1,3,self.db,os.O_RDWR)
        with self.assertRaisesRegex(RuntimeError,'WRITABLE_DATABASE_OR_WAL_HANDLE_AFTER_STOP'):a.no_open_database_fds(self.db,self.proc)
    def test_writable_wal_rejected_even_with_readonly_db(self):
        wal=Path(str(self.db)+'-wal');wal.write_bytes(b'wal');self.fd(1,3,self.db,os.O_RDONLY);self.fd(1,4,wal,os.O_RDWR)
        with self.assertRaises(RuntimeError):a.no_open_database_fds(self.db,self.proc)
    def test_shm_only_unknown_writable_handle_rejected(self):
        shm=Path(str(self.db)+'-shm');shm.write_bytes(b'shm');self.fd(1,4,shm,os.O_RDWR)
        with self.assertRaises(RuntimeError):a.no_open_database_fds(self.db,self.proc)
    def test_symlink_mount_alias_is_detected(self):
        alias=self.p/'alias';alias.symlink_to(self.db.parent,target_is_directory=True);self.assertTrue(a.mount_covers(str(alias),self.db))
    def test_direct_file_hardlink_is_detected(self):
        alias=self.p/'hardlink';os.link(self.db,alias);self.assertTrue(a.mount_covers(str(alias),self.db))
    def test_missing_absolute_mount_source_fails_closed(self):
        with self.assertRaises(FileNotFoundError):a.mount_covers(str(self.p/'missing'),self.db)
    def test_unknown_running_mount_writer_rejected(self):
        obj=types.SimpleNamespace(m=types.SimpleNamespace(BUSINESS=self.db,run=lambda *x:('a'*64+'\n').encode(),inspect=lambda identity:{'Mounts':[{'RW':True,'Source':str(self.db.parent)}]}))
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_RUNNING_DATABASE_WRITER'):a.Methods.writer_census(obj)
    def test_readonly_mount_does_not_count_as_writer(self):
        obj=types.SimpleNamespace(m=types.SimpleNamespace(BUSINESS=self.db,run=lambda *x:('a'*64+'\n').encode(),inspect=lambda identity:{'Mounts':[{'RW':False,'Source':str(self.db.parent)}]}));self.assertEqual(a.Methods.writer_census(obj)['running_database_writers'],0)

class RecoveryTests(unittest.TestCase):
    def fake(self,unknown=False,running=False,candidate_running=False):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name);old={'Id':'old','Image':'old-image','Name':'/t24-crm','State':{'Running':running,'StartedAt':'new-start' if running else 'old-start'}};candidate={'Id':'new','Image':'candidate','Name':'/candidate','State':{'Running':candidate_running}};events=[];crm={'id':'old','image':'old-image','config':'fixed','started':'old-start'}
        def runtime(info):return {'id':info['Id'],'image':info['Image'],'config':'fixed','started':info['State']['StartedAt']}
        def run(argv,*rest):
            events.append(argv)
            if argv[:2]==['docker','start']:old['State'].update(Running=True,StartedAt='new-start')
            if argv[:2]==['docker','stop']:candidate['State']['Running']=False
        m=types.SimpleNamespace(BUSINESS=root/'crm.db',NGINX=root/'nginx',runtime=runtime,run=run,retained=lambda:types.SimpleNamespace(reload_nginx=lambda:None),inspect=lambda identity:old,ready=lambda identity:None);m.NGINX.write_bytes(b'old')
        def census(allowed=()):
            events.append(('census',allowed))
            if unknown:raise RuntimeError('UNKNOWN_RUNNING_DATABASE_WRITER')
        o=types.SimpleNamespace(m=m,root=root,identities=lambda r,orig:(old,candidate),settle_migration=lambda *x:None,revision=lambda:'g32ed456e792',immutable=lambda **x:None,c=types.SimpleNamespace(retained=types.SimpleNamespace(compare=lambda *x:None),source_boundary=lambda *x:None),environment=lambda *x:None,original_inventory={},r=types.SimpleNamespace(NEW_REVISION='h43fe567f803',BACKEND_AFTER={}),writer_census=census,original_proof={'crm':crm},record=lambda name,v:events.append(('record',name)) or 'f'*64,old_name='before',candidate_name='candidate')
        return o,old,events
    def test_missing_baseline_recovery_resumes_known_old(self):
        o,old,events=self.fake()
        with patch.object(a,'no_open_database_fds',return_value={}):a.Methods.recover_internal(o,{'candidate_image':'candidate','nginx_next_sha256':a.H(b'new')},old)
        self.assertTrue(old['State']['Running']);self.assertLess(events.index(('record','original-resume-intent.json')),events.index(['docker','start','old']));self.assertIn(('record','original-resume-started.json'),events)
    def test_running_candidate_is_contained_before_old_resume(self):
        o,old,events=self.fake(candidate_running=True)
        with patch.object(a,'no_open_database_fds',return_value={}):a.Methods.recover_internal(o,{'candidate_image':'candidate','nginx_next_sha256':a.H(b'new')},old)
        self.assertLess(events.index(['docker','stop','--time','30','new']),events.index(['docker','start','old']))
    def test_unknown_writer_prevents_old_resume(self):
        o,old,events=self.fake(unknown=True)
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_RUNNING_DATABASE_WRITER'):a.Methods.recover_internal(o,{'candidate_image':'candidate','nginx_next_sha256':a.H(b'new')},old)
        self.assertFalse(old['State']['Running']);self.assertFalse(any(e==['docker','start','old'] for e in events))
    def test_already_resumed_old_does_not_restart_again(self):
        o,old,events=self.fake(running=True);a.Methods.recover_internal(o,{'candidate_image':'candidate','nginx_next_sha256':a.H(b'new')},old);self.assertFalse(any(e==['docker','start','old'] for e in events))
if __name__=='__main__':unittest.main()
