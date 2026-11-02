"""Authenticated R2 artifacts, with an exact quiescent at-write data boundary.

Live business updates before stopping the writer are legitimate. Every current
row, table definition and sequence is frozen after stop and preserved exactly
thereafter. No table is ignored and recovery never restores/downgrades data.
"""
import argparse,copy,fcntl,hashlib,json,os,re,resource,socket,stat,time,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
SOURCE='c78b50a11e020674ad53b34fbbfb5b1badd4a9a5'
RELEASE=Path('/opt/t24-crm/releases/media-automation-c78b50a11e02-20261102')
BASE_HELPER='9cc1abc634f927fc0f3b54c1d8d6f8ede2fe5573eb4c730236f756015a97eefe'
PREPARED='29ae8e354c8555a9aca186f5ef0b2368d17bd7f6007f73e57e6195e62558a47d'
MANIFEST='96f1baa987eeea40115fb8408ddb28d1a39b8a1dbbb254098f2da2ae554e44f8'
PAYLOAD='7054749c962d4cf5bd88b1ba040e6efd8ab85cca904675fb00aeb32340554c45'
PREFLIGHT='b130a39759f3638b4428fd974913e1b1cf6b964f757f010ec7b76364baa2d8c0'
PROTOCOL='media-automation-at-write-v1'
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def protected(path,sha,maximum=131072):
    need(path.is_absolute() and path.resolve()==path,'CANONICAL_ROOT_PRIVATE_PATH_REQUIRED')
    for p in path.parents:
        row=p.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
    before=path.lstat();need(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<=maximum,'ROOT600_INPUT_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:opened=os.fstat(f.fileno());body=f.read(maximum+1);after=os.fstat(f.fileno())
    fields=lambda r:(r.st_dev,r.st_ino,r.st_uid,r.st_mode,r.st_nlink,r.st_size,r.st_mtime_ns,r.st_ctime_ns)
    need(fields(before)==fields(opened)==fields(after)==fields(path.lstat()) and len(body)==before.st_size and H(body)==sha,'EXACT_REVIEWED_BYTES_REQUIRED');return body
def load():
    body=protected(RELEASE/'release.py',BASE_HELPER);r=types.ModuleType('_reviewed_r2_at_write_base');r.__file__=str(RELEASE/'release.py');exec(compile(body,r.__file__,'exec'),r.__dict__);need(r.SOURCE_SHA==SOURCE,'EXACT_R2_APPLICATION_REQUIRED');return r
def args_for(phase):
    return types.SimpleNamespace(phase=phase,release=RELEASE,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=Path('/opt/t24-crm/releases/media-automation-preflight-'+PREFLIGHT[:12]+'.json'),preflight_sha256=PREFLIGHT,review_sha256=PREPARED)
def mount_covers(source,database):
    source=Path(source)
    if not source.is_absolute():return False
    source=source.resolve(strict=True);database=database.resolve(strict=True);a,b=source.stat(),database.stat()
    if (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino):return True
    return database==source or source in database.parents
def no_open_database_fds(database,proc_root=Path('/proc')):
    # Compare device/inode, not namespace-specific /proc symlink target text.
    paths=[('database',database),('wal',Path(str(database)+'-wal')),('shm',Path(str(database)+'-shm'))];targets={}
    for kind,p in paths:
        try:row=p.stat();targets[(row.st_dev,row.st_ino)]=kind
        except FileNotFoundError:pass
    started=time.monotonic();checked=0;readers=0
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():continue
        try:entries=list((proc/'fd').iterdir())
        except (FileNotFoundError,ProcessLookupError):continue
        matched=[]
        for entry in entries:
            checked+=1;need(checked<=100000 and time.monotonic()-started<12,'BOUNDED_HOST_FD_CENSUS_REQUIRED')
            try:row=entry.stat()
            except (FileNotFoundError,ProcessLookupError):continue
            kind=targets.get((row.st_dev,row.st_ino))
            if kind is None:continue
            try:
                with (proc/'fdinfo'/entry.name).open() as stream:info=stream.read(4097)
            except (FileNotFoundError,ProcessLookupError):continue
            flags=re.findall(r'^flags:\s+([0-7]+)\s*$',info,re.M);need(len(info)<=4096 and len(flags)==1,'BOUNDED_FD_ACCESS_MODE_REQUIRED');mode=int(flags[0],8)&os.O_ACCMODE;matched.append((kind,mode))
        # A SQLite read-only connection may hold a writable SHM locking handle.
        # It is harmless only alongside its read-only DB handle; DB/WAL write
        # handles remain forbidden. Immutable RO mounts are separately checked.
        has_readonly_db=any(k=='database' and mode==os.O_RDONLY for k,mode in matched)
        for kind,mode in matched:
            need(mode==os.O_RDONLY or kind=='shm' and has_readonly_db,'WRITABLE_DATABASE_OR_WAL_HANDLE_AFTER_STOP')
        if matched:readers+=1
    return {'checked_fds':checked,'writable_database_or_wal_handles':0,'readonly_database_processes':readers}

class Methods:
    def __init__(self,args):
        super().__init__(args);self.r=type(self).base_module;self.original_proof=copy.deepcopy(self.proof);self.baseline=None;self.baseline_sha=None
    def immutable(self,*,migrated=False,updated=False):
        p,c,m=self.original_proof,self.c,self.m
        need(c.safe.safe_private_boundary(m,c.pins)==p['private_boundary'],'PRIVATE_BOUNDARY_CHANGED')
        meta={'ops':c.safe.protected_metadata(c.c.ENV_FILE),'google':c.safe.protected_metadata(c.safe.GBP_ENV),'meta_read':c.safe.protected_metadata(c.ctx.workflow.core.ENV_FILE),'meta_legacy':c.safe.protected_metadata(c.ctx.workflow.core.LEGACY_ENV_FILE)}
        need(meta==p['credential_metadata'] and m.credential_boundary()==p['credential_boundary'],'CREDENTIAL_METADATA_CHANGED')
        need([m.BUSINESS.stat().st_dev,m.BUSINESS.stat().st_ino]==p['database_identity'],'DATABASE_INODE_CHANGED')
        head=self.r.NEW_REVISION if migrated else self.r.OLD_REVISION;need(self.revision()==head,'EXACT_KNOWN_SCHEMA_REVISION_REQUIRED')
        self.r.compare_definitions(p['table_definitions'],self.definitions(),migrated=migrated)
        schema=m.schema_signature(m.BUSINESS,head)
        expected=self.main_prepared['schema_after_sha256'] if migrated else p['schema_sha256'];need(schema==expected,'EXACT_ORIGINAL_OR_REVIEWED_ADDITIVE_SCHEMA_REQUIRED')
        metadata=c.metadata(m.BUSINESS);need(metadata['pragma_sha256']==p['database_metadata']['pragma_sha256'] and metadata['sequence_exists'] is p['database_metadata']['sequence_exists'],'IMMUTABLE_DATABASE_PRAGMAS_CHANGED')
        need(self.r.digest(m.tree(self.old_public))==p['public_inventory_sha256'],'ORIGINAL_STATIC_BYTES_CHANGED');self.nginx(updated);return schema
    def writer_census(self,allowed=()):
        raw=self.m.run(['docker','ps','--no-trunc','-q'],'RUNNING_CONTAINER_CENSUS_FAILED');ids=raw.decode().splitlines();need(len(ids)<=32 and all(re.fullmatch('[a-f0-9]{64}',v) for v in ids),'BOUNDED_CONTAINER_IDS_REQUIRED')
        observed=set()
        for identity in ids:
            info=self.m.inspect(identity)
            for mount in info.get('Mounts',[]):
                if mount.get('RW') is True and mount_covers(mount.get('Source',''),self.m.BUSINESS):observed.add(identity);need(identity in allowed,'UNKNOWN_RUNNING_DATABASE_WRITER')
        need(observed==set(allowed),'EXACT_KNOWN_DATABASE_WRITER_SET_REQUIRED');return {'running_database_writers':len(observed)}
    def current(self):
        self.immutable();old=self.m.inspect('t24-crm');need(old['State']['Running'] is True and self.m.runtime(old)==self.original_proof['crm'] and self.m.inventory(old['Id'])==self.original_inventory,'EXACT_ORIGINAL420_RUNTIME_REQUIRED');self.environment(old);self.writer_census((old['Id'],));return old
    def stable_sample(self,old):
        need(self.m.inspect(old['Id'])['State']['Running'] is False,'OLD_WRITER_MUST_BE_STOPPED');self.writer_census();no_open_database_fds(self.m.BUSINESS);self.immutable()
        value={'rows':self.rows(),'table_definitions':self.definitions(),'database_metadata':self.c.metadata(self.m.BUSINESS),'schema_sha256':self.m.schema_signature(self.m.BUSINESS,self.r.OLD_REVISION),'database_identity':[self.m.BUSINESS.stat().st_dev,self.m.BUSINESS.stat().st_ino]}
        need(len(value['rows'])==162,'EXACT_CURRENT162_TABLES_REQUIRED');self.writer_census();no_open_database_fds(self.m.BUSINESS);return value
    def capture_baseline(self,old,candidate):
        first=self.stable_sample(old);second=self.stable_sample(old);need(first==second,'QUIESCENT_ALL162_SAMPLES_CHANGED')
        baseline={'stage':'MEDIA_AUTOMATION_QUIESCENT_BASELINE','protocol':PROTOCOL,'source_sha':SOURCE,'base_helper_sha256':BASE_HELPER,'prepared_sha256':PREPARED,'preflight_sha256':PREFLIGHT,'original_runtime':self.original_proof['crm'],'candidate_id':candidate['Id'],**second}
        sha=self.record('activation-baseline.json',baseline);self.record('activation-baseline-identity.json',{'protocol':PROTOCOL,'source_sha':SOURCE,'sha256':sha,'prepared_sha256':PREPARED,'original_id':old['Id'],'candidate_id':candidate['Id']});self.baseline,self.baseline_sha=baseline,sha
        changed=[{'table':name,'before_count':self.original_proof['rows'][name]['count'],'at_write_count':second['rows'][name]['count']} for name in sorted(second['rows']) if second['rows'][name]!=self.original_proof['rows'][name]]
        self.record('activation-before-change-summary.json',{'protocol':PROTOCOL,'changed_tables':changed,'schema_changed':False,'rows_ignored':False,'row_content_exported':False,'baseline_sha256':sha});return baseline
    def load_baseline(self,*,required=True):
        if self.baseline is not None:return self.baseline
        path=self.root/'activation-baseline-identity.json'
        if not path.exists():need(not required,'DURABLE_AT_WRITE_BASELINE_REQUIRED');return None
        ident=self.r.strict_json(self.r.protected(path));body=self.r.protected(self.root/'activation-baseline.json',ident['sha256'],1048576);value=self.r.strict_json(body)
        need(ident['protocol']==value['protocol']==PROTOCOL and ident['source_sha']==value['source_sha']==SOURCE and ident['prepared_sha256']==value['prepared_sha256']==PREPARED and value['base_helper_sha256']==BASE_HELPER and value['preflight_sha256']==PREFLIGHT and value['original_runtime']==self.original_proof['crm'] and len(value['rows'])==162 and ident['original_id']==self.original_proof['crm']['id'] and ident['candidate_id']==value['candidate_id'],'EXACT_DURABLE_QUIESCENT_BASELINE_REQUIRED')
        self.baseline,self.baseline_sha=value,ident['sha256'];return value
    def protections(self,*,migrated=False,updated=False,recovery=False):
        schema=self.immutable(migrated=migrated,updated=updated);baseline=self.load_baseline(required=migrated and not recovery)
        if baseline and not recovery:
            self.r.compare_rows(baseline['rows'],self.rows(),migrated=migrated);self.r.compare_definitions(baseline['table_definitions'],self.definitions(),migrated=migrated)
            self.c.retained.sequence_boundary(baseline['database_metadata'],self.c.metadata(self.m.BUSINESS))
        return schema
    def recover_internal(self,r,old):
        m=self.m;a,b=self.identities(r,old)
        if b['State']['Running']:m.run(['docker','stop','--time','30',b['Id']],'AT_WRITE_CANDIDATE_CONTAINMENT_FAILED',60)
        a,b=self.identities(r,old)
        self.settle_migration(m.BUSINESS.parent,r['candidate_image']);head=self.revision();updated=H(m.NGINX.read_bytes())==r['nginx_next_sha256'];self.immutable(migrated=head==self.r.NEW_REVISION,updated=updated)
        self.c.retained.compare(b,old,m);self.environment(a);self.environment(b);self.c.source_boundary(a,self.original_inventory);self.c.source_boundary(b,{**self.original_inventory,**self.r.BACKEND_AFTER})
        self.writer_census((a['Id'],) if a['State']['Running'] else ())
        if not a['State']['Running']:no_open_database_fds(m.BUSINESS)
        if updated:m.replace_nginx(m.NGINX.read_bytes(),self.r.protected(self.root/'nginx-before.conf',self.original_proof['nginx_sha256']))
        m.retained().reload_nginx();a,b=self.identities(r,old)
        if b['Name']=='/t24-crm':m.run(['docker','rename',b['Id'],self.candidate_name],'RETAIN_STOPPED_AT_WRITE_CANDIDATE_FAILED')
        if a['Name']!='/t24-crm':m.run(['docker','rename',a['Id'],'t24-crm'],'RESTORE_ORIGINAL_NAME_FAILED')
        if not a['State']['Running']:
            self.record('original-resume-intent.json',{'protocol':PROTOCOL,'original_id':a['Id'],'image':a['Image'],'config':m.runtime(a)['config'],'candidate_id':b['Id'],'schema_revision':head,'database_restore':False})
            m.run(['docker','start',a['Id']],'AT_WRITE_ORIGINAL_RESUME_FAILED');started=m.inspect(a['Id']);need(started['State']['Running'] is True,'ORIGINAL_START_RESULT_REQUIRED');self.record('original-resume-started.json',{'protocol':PROTOCOL,'runtime':m.runtime(started),'image':started['Image'],'candidate_id':b['Id']})
        m.ready(a['Id']);resumed=m.inspect('t24-crm');need(resumed['Id']==old['Id'] and resumed['State']['Running'] is True and m.runtime(resumed)['config']==self.original_proof['crm']['config'],'EXACT_ORIGINAL_RESUMED_REQUIRED');self.environment(resumed);self.immutable(migrated=head==self.r.NEW_REVISION);self.writer_census((resumed['Id'],))
        result={'stage':'MEDIA_AUTOMATION_AT_WRITE_ORIGINAL_RESUMED','protocol':PROTOCOL,'schema_revision':head,'baseline_was_durable':(self.root/'activation-baseline-identity.json').exists(),'all_current_rows_preserved':True,'database_restored':False,'additive_tables_retained':head==self.r.NEW_REVISION,'provider_requests':False};return {**result,'receipt_sha256':self.record('at-write-recovery.json',result)}
    def activate(self):
        m=self.m;r,old=self.reviewed();self.main_prepared=r;self.current();need(not(self.root/'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name),'FRESH_AT_WRITE_ACTIVATION_REQUIRED');nginx=m.NGINX.read_bytes();new=self.r.next_nginx(nginx,self.old_public,self.public,self.original_proof['nginx_sha256']);need(H(new)==r['nginx_next_sha256'],'EXACT_REVIEWED_NGINX_REQUIRED')
        self.record('nginx-before.conf',nginx);self.record('activation-started.json',{'protocol':PROTOCOL,'source_sha':SOURCE,'prepared_sha256':PREPARED,'original_id':old['Id']});self.record('candidate-create-intent.json',{'protocol':PROTOCOL,'name':self.candidate_name,'image':r['candidate_image'],'original_id':old['Id'],'prepared_sha256':PREPARED})
        status,body=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,m.clone_config(r['candidate_image'],old));need(status==201,'AT_WRITE_CANDIDATE_CREATE_FAILED');identity=json.loads(body)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_ID_REQUIRED');self.record('candidate-created.json',{'source_sha':SOURCE,'candidate_id':identity,'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':PREPARED})
        try:
            _,candidate=self.fresh(r,old);need(candidate['State']['Status']=='created','NEVER_STARTED_AT_WRITE_CANDIDATE_REQUIRED');self.record('stop-intent.json',{'protocol':PROTOCOL,'original_id':old['Id'],'candidate_id':identity,'original_runtime':self.original_proof['crm'],'prepared_sha256':PREPARED});m.run(['docker','stop','--time','30',old['Id']],'AT_WRITE_ORIGINAL_STOP_FAILED',60)
            a,candidate=self.fresh(r,old);need(a['State']['Running'] is False,'STOPPED_AT_WRITE_ORIGINAL_REQUIRED');self.capture_baseline(old,candidate);self.protections();m.backup(m.BUSINESS,self.root/'production-at-write.db');self.protections();self.writer_census();no_open_database_fds(m.BUSINESS);self.run_migration(m.BUSINESS.parent,r['candidate_image']);self.fresh(r,old,migrated=True)
            m.run(['docker','rename',old['Id'],self.old_name],'AT_WRITE_ORIGINAL_RENAME_FAILED');m.run(['docker','rename',identity,'t24-crm'],'AT_WRITE_CANDIDATE_RENAME_FAILED');self.fresh(r,old,migrated=True);m.run(['docker','start',identity],'AT_WRITE_CANDIDATE_START_FAILED');m.ready(identity);self.fresh(r,old,migrated=True,live=True);m.replace_nginx(nginx,new);m.retained().reload_nginx();self.fresh(r,old,migrated=True,updated=True,live=True);privacy=self.public_check(identity);_,candidate=self.fresh(r,old,migrated=True,updated=True,live=True)
            result={'stage':'MEDIA_AUTOMATION_DEPLOYED','protocol':PROTOCOL,'source_sha':SOURCE,'frontend_version':self.r.FRONTEND,'schema_revision':self.r.NEW_REVISION,'table_count':165,'crm':m.runtime(candidate),'prepared_sha256':PREPARED,'preflight_sha256':PREFLIGHT,'schema_after_sha256':r['schema_after_sha256'],'public_root':str(self.public),'public_inventory_sha256':r['public_inventory_sha256'],'nginx_sha256':H(m.NGINX.read_bytes()),'quiescent_baseline_sha256':self.baseline_sha,'original162_rows_schema_preserved':True,'all_current_sequences_preserved':True,'three_new_tables_empty':True,'environment_credentials_private_acl_preserved':True,'google_meta_cutoffs_preserved':True,'automation_worker_enabled':False,'operations_execution_enabled':False,'operations_scheduler_enabled':False,'provider_requests':False,'business_seed_rows':False,'database_restored':False,'privacy':privacy};return {**result,'receipt_sha256':self.record('deployed.json',result)}
        except BaseException:self.recover_internal(r,old);raise
    def recover(self):
        # A previous recovery may have restarted this exact image and config.
        # Authenticate its immutable identity without requiring old StartedAt.
        r=self.r.strict_json(self.r.protected(self.root/'prepared.json',PREPARED));self.r.validate_prepared(r,MANIFEST,PAYLOAD,PREFLIGHT);old=self.m.inspect(self.original_proof['crm']['id']);need(old['Id']==self.original_proof['crm']['id'] and old['Image']==self.original_proof['crm']['image'] and self.m.runtime(old)['config']==self.original_proof['crm']['config'],'AUTHENTICATED_ORIGINAL_RECOVERY_REQUIRED');self.environment(old);self.c.source_boundary(old,self.original_inventory)
        if self.m.runtime(old)!=self.original_proof['crm']:
            intent=self.r.strict_json(self.r.protected(self.root/'original-resume-intent.json'));need(intent['protocol']==PROTOCOL and intent['original_id']==old['Id'] and intent['image']==old['Image'] and intent['config']==self.original_proof['crm']['config'] and intent['database_restore'] is False,'DURABLE_ORIGINAL_RESTART_INTENT_REQUIRED')
            started=self.root/'original-resume-started.json'
            if started.exists():
                proof=self.r.strict_json(self.r.protected(started));need(proof['protocol']==PROTOCOL and proof['runtime']==self.m.runtime(old) and proof['image']==old['Image'],'EXACT_RECORDED_ORIGINAL_RESTART_REQUIRED')
            else:
                need(old['State']['Running'] is True,'CRASH_GAP_RUNNING_ORIGINAL_REQUIRED');self.record('original-resume-started.json',{'protocol':PROTOCOL,'runtime':self.m.runtime(old),'image':old['Image'],'candidate_id':intent['candidate_id']})
        need(self.m.image_id(r['candidate_image'])==r['candidate_image'] and self.m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'RECOVERY_PREPARED_IMAGE_STATIC_CHANGED');self.main_prepared=r;need(not(self.root/'deployed.json').exists(),'SUCCESSFUL_AT_WRITE_RECOVERY_REQUIRES_SEPARATE_REVIEW');return self.recover_internal(r,old)

def make_release(phase):
    r=load();klass=type('ReviewedAtWriteRelease',(Methods,r.Release),{'base_module':r});return klass(args_for(phase))
def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=('activate','recover'),required=True);a=p.parse_args();need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    lock=Path('/opt/t24-crm/releases/.media-workspace-scale.lock');fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_SHARED_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);print(json.dumps(getattr(make_release(a.phase),a.phase)(),sort_keys=True))
    finally:os.close(fd)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        value=str(e);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_AUTOMATION_AT_WRITE_REJECTED';print(json.dumps({'stage':'MEDIA_AUTOMATION_AT_WRITE_REJECTED','code':code,'database_restored':False},sort_keys=True));raise SystemExit(1)
