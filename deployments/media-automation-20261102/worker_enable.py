"""Separately reviewed runtime-only opt-in, after the additive release succeeds.

Requires zero policies/occurrences/requests before enabling. Only one new Docker
environment entry is added; protected credential/environment files are untouched.
No policy is created and no content generation/publication is requested here.
"""
import argparse,copy,fcntl,hashlib,json,os,re,resource,socket,stat,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
KEY='T24_MEDIA_MONTHLY_AUTOPREP_ENABLED'
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
    need(fields(before)==fields(opened)==fields(after)==fields(path.lstat()) and len(body)==before.st_size and H(body)==sha,'EXACT_STABLE_REVIEWED_BYTES_REQUIRED');return body
def project(info):
    rows=info['Config']['Env'];need(isinstance(rows,list) and [v for v in rows if v.split('=',1)[0]==KEY]==[KEY+'=true'],'EXACT_SINGLE_NEW_DRAFT_WORKER_FLAG_REQUIRED');value=copy.deepcopy(info);value['Config']['Env']=[v for v in rows if v.split('=',1)[0]!=KEY];return value
def candidate_config(m,image,current):
    need(not any(v.split('=',1)[0]==KEY for v in current['Config']['Env']),'NEW_WORKER_FLAG_MUST_BE_ABSENT_BEFORE_ENABLE')
    config=m.clone_config(image,current);need(config['Env']==current['Config']['Env'],'ORIGINAL_ORDERED_ENVIRONMENT_REQUIRED');config['Env']=[*config['Env'],KEY+'=true'];return config
def bind_quiescent_baseline(release,r,deployed):
    need(deployed.get('protocol')=='media-automation-at-write-v1','REVIEWED_AT_WRITE_DEPLOYMENT_REQUIRED')
    sha=deployed.get('quiescent_baseline_sha256');need(re.fullmatch('[a-f0-9]{64}',sha or ''),'MAIN_QUIESCENT_BASELINE_HASH_REQUIRED');value=r.strict_json(r.protected(release.root/'activation-baseline.json',sha,1048576));p=release.proof
    need(value['stage']=='MEDIA_AUTOMATION_QUIESCENT_BASELINE' and value['protocol']==deployed['protocol'] and value['source_sha']==r.SOURCE_SHA and value['prepared_sha256']==deployed['prepared_sha256'] and value['preflight_sha256']==r.PREFLIGHT_SHA and value['original_runtime']==p['crm'] and value['candidate_id']==deployed['crm']['id'] and value['database_identity']==p['database_identity'] and value['schema_sha256']==p['schema_sha256'] and set(value['rows'])==set(p['rows']) and len(value['rows'])==162,'EXACT_MAIN_QUIESCENT_BASELINE_REQUIRED')
    r.compare_definitions(p['table_definitions'],value['table_definitions']);need(all(value['rows'][n]['shape_sha256']==p['rows'][n]['shape_sha256'] for n in p['rows']),'ORIGINAL162_TABLE_SHAPES_REQUIRED')
    release.proof={**p,'rows':value['rows'],'table_definitions':value['table_definitions'],'database_metadata':value['database_metadata']}
    def strict_boundary(self,path=None,*,migrated=False,rows=True,empty=True):
        path=path or self.m.BUSINESS;head=r.NEW_REVISION if migrated else r.OLD_REVISION;need(self.revision(path)==head,'EXACT_DATABASE_REVISION_REQUIRED');r.compare_rows(self.proof['rows'],self.rows(path),migrated=migrated,rows=rows,empty=empty);r.compare_definitions(self.proof['table_definitions'],self.definitions(path),migrated=migrated)
        current=self.c.metadata(path)
        if rows:self.c.retained.sequence_boundary(self.proof['database_metadata'],current)
        else:need(current['pragma_sha256']==self.proof['database_metadata']['pragma_sha256'] and current['sequence_exists'] is self.proof['database_metadata']['sequence_exists'],'RECOVERY_IMMUTABLE_PRAGMAS_CHANGED')
        return self.m.schema_signature(path,head)
    release.db_boundary=types.MethodType(strict_boundary,release);return sha

class Enable:
    def __init__(self,a):
        self.a=a;body=protected(a.release/'release.py',a.main_release_sha256);r=types.ModuleType('_reviewed_additive_automation_release');r.__file__=str(a.release/'release.py');exec(compile(body,r.__file__,'exec'),r.__dict__)
        mainargs=types.SimpleNamespace(phase='recover',release=a.release,manifest_sha256=a.manifest_sha256,payload_sha256=a.payload_sha256,preflight=a.preflight,preflight_sha256=a.preflight_sha256,review_sha256=a.main_prepared_sha256)
        self.r=r;self.release=r.Release(mainargs);self.m=self.release.m;self.main_prepared,self.main_original=self.release.reviewed();self.deployed=r.strict_json(r.protected(a.release/'deployed.json',a.main_deployed_sha256))
        v=self.deployed;need(v['stage']=='MEDIA_AUTOMATION_DEPLOYED' and v['source_sha']==r.SOURCE_SHA and v['schema_revision']==r.NEW_REVISION and v['prepared_sha256']==a.main_prepared_sha256 and v['automation_worker_enabled'] is False and v['original162_rows_schema_preserved'] is True and v['three_new_tables_empty'] is True,'EXACT_COMPLETED_DEFAULT_OFF_RELEASE_REQUIRED')
        self.baseline_sha=bind_quiescent_baseline(self.release,r,v)
        self.old_name='t24-crm-before-autoprep-'+r.SOURCE_SHA[:12];self.candidate_name='t24-crm-autoprep-candidate-'+r.SOURCE_SHA[:12];self.inventory={**self.release.original_inventory,**r.BACKEND_AFTER}
    def record(self,name,value):return self.release.record(name,value)
    def current(self):
        info=self.m.inspect('t24-crm');need(info['State']['Running'] is True and self.m.runtime(info)==self.deployed['crm'] and info['Image']==self.main_prepared['candidate_image'],'EXACT_DEPLOYED_DEFAULT_OFF_RUNTIME_REQUIRED');self.release.environment(info);self.release.protections(migrated=True,updated=True);need(self.m.inventory(info['Id'])==self.inventory,'EXACT_ADDITIVE_SOURCE_REQUIRED');return info
    def prepare(self):
        current=self.current();need(not(self.a.release/'worker-prepared.json').exists(),'FRESH_WORKER_PREPARATION_REQUIRED')
        result={'stage':'MEDIA_AUTOMATION_WORKER_PREPARED','source_sha':self.r.SOURCE_SHA,'main_release_sha256':self.a.main_release_sha256,'main_prepared_sha256':self.a.main_prepared_sha256,'main_deployed_sha256':self.a.main_deployed_sha256,'quiescent_baseline_sha256':self.baseline_sha,'runtime':self.m.runtime(current),'new_runtime_entry':KEY+'=true','three_tables_empty':True,'existing_flags_environment_order_and_files_preserved':True,'policies_created':False,'provider_requests':False,'publications_requested':False,'database_written':False};return {**result,'receipt_sha256':self.record('worker-prepared.json',result)}
    def reviewed(self):
        p=self.r.strict_json(self.r.protected(self.a.release/'worker-prepared.json',self.a.review_sha256));need(p['stage']=='MEDIA_AUTOMATION_WORKER_PREPARED' and p['source_sha']==self.r.SOURCE_SHA and p['main_release_sha256']==self.a.main_release_sha256 and p['main_prepared_sha256']==self.a.main_prepared_sha256 and p['main_deployed_sha256']==self.a.main_deployed_sha256 and p['runtime']==self.deployed['crm'] and p['new_runtime_entry']==KEY+'=true','EXACT_REVIEWED_WORKER_PREPARATION_REQUIRED');need(all(p[k] is False for k in ('policies_created','provider_requests','publications_requested','database_written')) and p['three_tables_empty'] is True and p['existing_flags_environment_order_and_files_preserved'] is True,'ZERO_POLICY_RUNTIME_ONLY_ENABLE_REQUIRED');return p
    def identities(self):
        state=self.r.strict_json(self.r.protected(self.a.release/'worker-candidate.json'));need(state=={'source_sha':self.r.SOURCE_SHA,'old_id':self.deployed['crm']['id'],'candidate_id':state['candidate_id'],'candidate_image':self.main_prepared['candidate_image'],'review_sha256':self.a.review_sha256} and re.fullmatch('[a-f0-9]{64}',state['candidate_id']),'EXACT_WORKER_CANDIDATE_RECORD_REQUIRED')
        old=self.m.inspect(state['old_id']);new=self.m.inspect(state['candidate_id']);need(old['Name'] in {'/t24-crm','/'+self.old_name} and new['Name'] in {'/t24-crm','/'+self.candidate_name} and old['Image']==new['Image']==state['candidate_image'],'ONLY_KNOWN_SAME_IMAGE_CANDIDATES_ALLOWED');primary=self.m.inspect_optional('t24-crm');need(not primary or primary['Id'] in {old['Id'],new['Id']},'UNKNOWN_PRIMARY_NOT_CHANGED');return old,new
    def boundary(self,*,live=False,recovery=False):
        self.release.protections(migrated=True,updated=True,recovery=recovery);old,new=self.identities();self.release.environment(old);self.release.environment(project(new));self.release.c.retained.compare(project(new),old,self.m);self.release.c.source_boundary(old,self.inventory);self.release.c.source_boundary(new,self.inventory)
        need(new['RestartCount']==0,'NEW_WORKER_CANDIDATE_RESTARTED');need(live and new['State']['Running'] is True and old['State']['Running'] is False and self.m.inspect('t24-crm')['Id']==new['Id'] or not live and new['State']['Running'] is False,'SINGLE_KNOWN_WORKER_WRITER_REQUIRED')
        if live:self.release.c.helper.validation_window(new)
        return old,new
    def activate(self):
        self.reviewed();old=self.current();need(not(self.a.release/'worker-candidate.json').exists() and not self.m.inspect_optional(self.old_name) and not self.m.inspect_optional(self.candidate_name),'FRESH_WORKER_SWITCH_REQUIRED')
        status,body=self.m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,candidate_config(self.m,old['Image'],old));need(status==201,'WORKER_CANDIDATE_CREATE_FAILED');identity=json.loads(body)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_ID_REQUIRED');self.record('worker-candidate.json',{'source_sha':self.r.SOURCE_SHA,'old_id':old['Id'],'candidate_id':identity,'candidate_image':old['Image'],'review_sha256':self.a.review_sha256})
        try:
            _,new=self.boundary();need(new['State']['Status']=='created','NEVER_STARTED_WORKER_CANDIDATE_REQUIRED');self.m.run(['docker','stop','--time','30',old['Id']],'WORKER_ORIGINAL_STOP_FAILED',60);original,_=self.boundary();need(original['State']['Running'] is False,'STOPPED_DEFAULT_OFF_RUNTIME_REQUIRED');self.m.run(['docker','rename',old['Id'],self.old_name],'WORKER_ORIGINAL_RENAME_FAILED');self.m.run(['docker','rename',identity,'t24-crm'],'WORKER_CANDIDATE_RENAME_FAILED');self.boundary();self.m.run(['docker','start',identity],'WORKER_CANDIDATE_START_FAILED');self.m.ready(identity);_,new=self.boundary(live=True)
            code="from services.media_monthly_automation import enabled;assert enabled() is True;print('EXACT_DRAFT_WORKER_ENABLED_ZERO_POLICIES')";need(b'EXACT_DRAFT_WORKER_ENABLED_ZERO_POLICIES' in self.m.run(['docker','exec',identity,'python','-B','-c',code],'WORKER_RUNTIME_FLAG_PROBE_FAILED'),'EXACT_RUNTIME_WORKER_FLAG_REQUIRED');self.boundary(live=True)
            result={'stage':'MEDIA_AUTOMATION_WORKER_ENABLED','source_sha':self.r.SOURCE_SHA,'crm':self.m.runtime(new),'main_deployed_sha256':self.a.main_deployed_sha256,'worker_prepared_sha256':self.a.review_sha256,'only_new_runtime_flag_added':True,'three_tables_empty':True,'existing_environment_files_flags_credentials_static_acl_preserved':True,'policies_created':False,'ai_calls_requested':False,'publications_requested':False,'database_written':False};return {**result,'receipt_sha256':self.record('worker-enabled.json',result)}
        except BaseException:self.recover_internal();raise
    def recover_internal(self):
        old,new=self.identities()
        if new['State']['Running']:self.m.run(['docker','stop','--time','30',new['Id']],'WORKER_RECOVERY_CONTAINMENT_FAILED',60)
        self.boundary(recovery=True);old,new=self.identities()
        if new['Name']=='/t24-crm':self.m.run(['docker','rename',new['Id'],self.candidate_name],'WORKER_STOPPED_CANDIDATE_RETAIN_FAILED')
        if old['Name']!='/t24-crm':self.m.run(['docker','rename',old['Id'],'t24-crm'],'WORKER_ORIGINAL_NAME_RESTORE_FAILED')
        if not old['State']['Running']:self.m.run(['docker','start',old['Id']],'WORKER_DEFAULT_OFF_RESUME_FAILED')
        self.m.ready(old['Id']);resumed=self.m.inspect('t24-crm');need(resumed['Id']==old['Id'] and resumed['State']['Running'] is True and self.m.runtime(resumed)['config']==self.deployed['crm']['config'],'EXACT_DEFAULT_OFF_RUNTIME_RESUMED_REQUIRED');self.release.environment(resumed);self.release.protections(migrated=True,updated=True,recovery=True)
        result={'stage':'MEDIA_AUTOMATION_WORKER_DEFAULT_OFF_RESUMED','crm':self.m.runtime(resumed),'all_current_rows_and_additive_tables_preserved':True,'database_restored':False,'policies_deleted':False,'publications_requested':False};return {**result,'receipt_sha256':self.record('worker-recovered.json',result)}
    def recover(self):
        self.reviewed();need(not(self.a.release/'worker-enabled.json').exists(),'SUCCESSFUL_WORKER_SWITCH_RECOVERY_REQUIRES_SEPARATE_REVIEW');return self.recover_internal()
def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=('prepare','prepare_activate','activate','recover'),required=True);p.add_argument('--release',type=Path,required=True)
    for key in ('main-release-sha256','main-prepared-sha256','main-deployed-sha256','manifest-sha256','payload-sha256','preflight-sha256'):p.add_argument('--'+key,required=True)
    p.add_argument('--preflight',type=Path,required=True);p.add_argument('--review-sha256');a=p.parse_args();need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    need(all(re.fullmatch('[a-f0-9]{64}',getattr(a,k.replace('-','_')) or '') for k in ('main-release-sha256','main-prepared-sha256','main-deployed-sha256','manifest-sha256','payload-sha256','preflight-sha256')) and (a.phase in {'prepare','prepare_activate'} or re.fullmatch('[a-f0-9]{64}',a.review_sha256 or '')),'EXACT_REVIEWED_PHASE_HASHES_REQUIRED')
    lock=Path('/opt/t24-crm/releases/.media-workspace-scale.lock')
    for path in lock.parents:
        row=path.lstat();need(path.resolve()==path and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_LOCK_PARENT_REQUIRED')
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_SHARED_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.phase=='prepare_activate':
            first=Enable(a).prepare();canonical={k:v for k,v in first.items() if k!='receipt_sha256'};sha=H((json.dumps(canonical,sort_keys=True,indent=2)+'\n').encode());need(first['receipt_sha256']==sha and first['three_tables_empty'] is True and first['existing_flags_environment_order_and_files_preserved'] is True and first['new_runtime_entry']==KEY+'=true' and all(first[k] is False for k in ('policies_created','provider_requests','publications_requested','database_written')),'EXACT_ZERO_POLICY_PREPARATION_REQUIRED')
            protected(a.release/'worker-prepared.json',sha,1048576);a.review_sha256=sha;a.phase='activate';second=Enable(a).activate();print(json.dumps({'stage':'MEDIA_AUTOMATION_WORKER_PREPARED_AND_ENABLED','prepared':first,'enabled':second,'single_reviewed_zero_policy_invocation':True},sort_keys=True))
        else:print(json.dumps(getattr(Enable(a),a.phase)(),sort_keys=True))
    finally:os.close(fd)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        v=str(e);code=v if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',v) else 'MEDIA_AUTOMATION_WORKER_ENABLE_REJECTED';print(json.dumps({'stage':'MEDIA_AUTOMATION_WORKER_ENABLE_REJECTED','code':code,'database_restored':False},sort_keys=True));raise SystemExit(1)
