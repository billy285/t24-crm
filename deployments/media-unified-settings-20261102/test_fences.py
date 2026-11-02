import hashlib,importlib.util,json,os,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
r=load('_unified_fence_release',HERE/'release.py')
controller_path=HERE.parent/'media-automation-20261102/at_write_release.py'
assert hashlib.sha256(controller_path.read_bytes()).hexdigest()=='8727edc4ae5ef1a99ef1276f7f337412ec1de67526d3eeb5a5baf9664853cd78'
census=load('_exact_published_fences',controller_path)
class FenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.p=Path(self.temp.name);self.db=self.p/'data'/'db';self.db.parent.mkdir();self.db.write_bytes(b'synthetic');self.proc=self.p/'proc';self.proc.mkdir()
    def tearDown(self):self.temp.cleanup()
    def fd(self,pid,n,path,mode):
        p=self.proc/str(pid);(p/'fd').mkdir(parents=True,exist_ok=True);(p/'fdinfo').mkdir(exist_ok=True);(p/'fd'/str(n)).symlink_to(path);(p/'fdinfo'/str(n)).write_text('flags:\t'+format(mode,'o')+'\n')
    def test_exact_deployed_census_is_reused_not_unreleased_patch(self):
        self.assertEqual(hashlib.sha256(controller_path.read_bytes()).hexdigest(),'8727edc4ae5ef1a99ef1276f7f337412ec1de67526d3eeb5a5baf9664853cd78')
    def test_legitimate_readonly_private_reader_and_shm_lock_allowed(self):
        shm=Path(str(self.db)+'-shm');shm.write_bytes(b'lock');self.fd(1,3,self.db,os.O_RDONLY);self.fd(1,4,shm,os.O_RDWR);census.no_open_database_fds(self.db,self.proc)
    def test_unknown_writable_database_or_wal_handle_rejected(self):
        wal=Path(str(self.db)+'-wal');wal.write_bytes(b'wal');self.fd(1,3,self.db,os.O_RDONLY);self.fd(1,4,wal,os.O_RDWR)
        with self.assertRaises(RuntimeError):census.no_open_database_fds(self.db,self.proc)
    def test_unknown_running_database_writer_mount_rejected(self):
        alias=self.p/'alias';alias.symlink_to(self.db.parent,target_is_directory=True);m=types.SimpleNamespace(BUSINESS=self.db,run=lambda *x:('a'*64+'\n').encode(),inspect=lambda identity:{'Mounts':[{'RW':True,'Source':str(alias)}]});obj=types.SimpleNamespace(m=m,census=census)
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_RUNNING_DATABASE_WRITER'):r.Release.writer_census(obj)
    def test_readonly_container_mount_does_not_count_as_writer(self):
        m=types.SimpleNamespace(BUSINESS=self.db,run=lambda *x:('a'*64+'\n').encode(),inspect=lambda identity:{'Mounts':[{'RW':False,'Source':str(self.db.parent)}]});obj=types.SimpleNamespace(m=m,census=census);self.assertEqual(r.Release.writer_census(obj)['running_database_writers'],0)
    def test_missing_bind_source_fails_closed(self):
        with self.assertRaises(FileNotFoundError):census.mount_covers(str(self.p/'missing'),self.db)

class RecoveryTests(unittest.TestCase):
    def fake(self,*,unknown=False,old_running=False,new_running=False,head=r.OLD_REVISION):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name);old={'Id':'old','Image':'old-image','Name':'/t24-crm','State':{'Running':old_running,'StartedAt':'new-start' if old_running else 'original-start'}};new={'Id':'new','Image':'new-image','Name':'/candidate','State':{'Running':new_running}};events=[]
        def runtime(info):return {'id':info['Id'],'image':info['Image'],'config':'all-old-flags-including-autoprep-true','started':info['State']['StartedAt']}
        def run(argv,*rest):
            events.append(argv)
            if argv[:2]==['docker','stop']:new['State']['Running']=False
            if argv[:2]==['docker','start']:old['State'].update(Running=True,StartedAt='new-start')
        def writers(allowed=()):
            events.append(('writers',allowed))
            if unknown:raise RuntimeError('UNKNOWN_RUNNING_DATABASE_WRITER')
        m=types.SimpleNamespace(BUSINESS=root/'db',NGINX=root/'nginx',run=run,runtime=runtime,inspect=lambda identity:old,retained=lambda:types.SimpleNamespace(reload_nginx=lambda:None),ready=lambda identity:None);m.NGINX.write_bytes(b'old')
        def record(name,value):events.append(('record',name));return 'f'*64
        def immutable(**kwargs):events.append(('immutable',kwargs));self.assertTrue(kwargs['recovery'])
        obj=types.SimpleNamespace(m=m,root=root,identities=lambda rec,o:(old,new),settle_migration=lambda *x:events.append(('settled',True)),migration_revision=lambda:head,immutable=immutable,base=types.SimpleNamespace(c=types.SimpleNamespace(retained=types.SimpleNamespace(compare=lambda *x:None),source_boundary=lambda *x:None)),environment=lambda info:events.append(('flags-preserved',info['Id'])),inventory={},writer_census=writers,census=types.SimpleNamespace(no_open_database_fds=lambda path:events.append(('no-writable-fds',True))),proof={'crm':runtime(old)},candidate_name='candidate',old_name='before',record_once=record)
        return obj,old,new,events
    def test_failure_after_stop_before_baseline_still_resumes_old(self):
        obj,old,new,events=self.fake();result=r.Release.recover_internal(obj,{'candidate_image':'new-image','nginx_next_sha256':r.H(b'new')},old);self.assertTrue(old['State']['Running']);self.assertFalse(result['database_restored']);self.assertIn(('record','original-resume-intent.json'),events)
    def test_running_candidate_contained_before_original_resumes(self):
        obj,old,new,events=self.fake(new_running=True);r.Release.recover_internal(obj,{'candidate_image':'new-image','nginx_next_sha256':r.H(b'new')},old);self.assertLess(events.index(['docker','stop','--time','30','new']),events.index(['docker','start','old']))
    def test_unknown_other_writer_prevents_original_restart(self):
        obj,old,new,events=self.fake(unknown=True)
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_RUNNING_DATABASE_WRITER'):r.Release.recover_internal(obj,{'candidate_image':'new-image','nginx_next_sha256':r.H(b'new')},old)
        self.assertFalse(old['State']['Running']);self.assertNotIn(['docker','start','old'],events)
    def test_failed_post_start_release_keeps_additive_schema_and_current_rows(self):
        obj,old,new,events=self.fake(new_running=True,head=r.NEW_REVISION);result=r.Release.recover_internal(obj,{'candidate_image':'new-image','nginx_next_sha256':r.H(b'new')},old);self.assertTrue(result['additive_tables_retained']);self.assertTrue(result['all_current_business_rows_preserved']);self.assertFalse(result['database_restored']);self.assertFalse(any(isinstance(e,list) and any('drop' in str(x).lower() for x in e) for e in events))
    def test_already_resumed_original_not_restarted_again(self):
        obj,old,new,events=self.fake(old_running=True);r.Release.recover_internal(obj,{'candidate_image':'new-image','nginx_next_sha256':r.H(b'new')},old);self.assertNotIn(['docker','start','old'],events)
if __name__=='__main__':unittest.main()
