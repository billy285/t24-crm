"""Read-only failed-prepare diagnosis plus a new private current baseline.

Only names/counts/booleans and aggregate fingerprints leave this process.
No business row, production container, schema or existing file is changed.
"""
import hashlib,json,os,re,resource,socket,stat,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
ROOT=Path('/opt/t24-crm/releases')
FAILED=ROOT/'media-automation-c78b50a11e02-20261102'
OLD_PROOF='ecc7ae9cf9dfbdff68306b928b9b3a8f0ad98c90e5785611a061730f78a8beda'
FILES={'release.py':('9c7a0fb049625e9550ff38a405c0f69389555a988c01191e87e7af38a61279ec',42813),'preflight.py':('57deb06c6c9ebd11336cf9408887f36754ba2246d294faa5cbe38896a56f99ce',9665),'manifest.json':('65fdf21e9d88273ee558354428346882a1b869fa4df857184e95430a7edadcd3',151908),'payload.tar.gz':('76eec467ac5c43d54b27dfdd9fbaa99bf1bd5728816d0e0481f8cf6e016010fc',2310293)}
NAMES=('t24-crm-before-media-automation-53d66ebb6c69','t24-crm-candidate-media-automation-53d66ebb6c69','t24-media-automation-probe-53d66ebb6c69','t24-media-automation-migration-53d66ebb6c69-offline','t24-media-automation-migration-53d66ebb6c69-production','t24-crm-before-autoprep-53d66ebb6c69','t24-crm-autoprep-candidate-53d66ebb6c69')
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def protected(path,sha,size):
    need(path.is_absolute() and path.resolve()==path,'CANONICAL_ROOT_PRIVATE_PATH_REQUIRED')
    for p in path.parents:
        x=p.lstat();need(stat.S_ISDIR(x.st_mode) and x.st_uid==0 and not x.st_mode&0o022,'PROTECTED_ROOT_PARENT_REQUIRED')
    before=path.lstat();need(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and before.st_size==size,'EXACT_ROOT600_MEMBER_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:opened=os.fstat(f.fileno());body=f.read(size+1);after=os.fstat(f.fileno())
    fields=lambda r:(r.st_dev,r.st_ino,r.st_uid,r.st_mode,r.st_nlink,r.st_size,r.st_mtime_ns,r.st_ctime_ns)
    need(fields(before)==fields(opened)==fields(after)==fields(path.lstat()) and len(body)==size and H(body)==sha,'EXACT_IMMUTABLE_MEMBER_BYTES_REQUIRED');return body
def main():
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    sha='9cc1abc634f927fc0f3b54c1d8d6f8ede2fe5573eb4c730236f756015a97eefe';body=protected(FAILED/'release.py',sha,42813)
    mod=types.ModuleType('_reviewed_r2_release_readonly');mod.__file__=str(FAILED/'release.py');exec(compile(body,mod.__file__,'exec'),mod.__dict__)
    from types import SimpleNamespace
    args=SimpleNamespace(phase='recover',release=FAILED,manifest_sha256='96f1baa987eeea40115fb8408ddb28d1a39b8a1dbbb254098f2da2ae554e44f8',payload_sha256='7054749c962d4cf5bd88b1ba040e6efd8ab85cca904675fb00aeb32340554c45',preflight=ROOT/'media-automation-preflight-b130a39759f3.json',preflight_sha256='b130a39759f3638b4428fd974913e1b1cf6b964f757f010ec7b76364baa2d8c0',review_sha256='29ae8e354c8555a9aca186f5ef0b2368d17bd7f6007f73e57e6195e62558a47d')
    pf=types.ModuleType('_r2_readonly_before_mutable_adapter');pf.__file__=str(FAILED/'preflight.py');exec(compile(mod.protected(FAILED/'preflight.py',mod.PREFLIGHT_CODE_SHA),pf.__file__,'exec'),pf.__dict__);current=pf.sample()
    r=mod.Release(args);prepared,old=r.reviewed();m=r.m
    absent=['activation-started.json','candidate-created.json','migration-production-container.json','deployed.json','recovery.json','activation-baseline.json']
    need(all(not (FAILED/name).exists() for name in absent),'R2_ACTIVATION_RECORD_EXISTS_REQUIRES_REVIEW')
    names=[r.old_name,r.candidate_name,r.offline_name,'t24-media-automation-migration-c78b50a11e02-production','t24-crm-before-autoprep-c78b50a11e02','t24-crm-autoprep-candidate-c78b50a11e02']
    need(all(m.inspect_optional(name) is None for name in names),'UNEXPECTED_R2_CANDIDATE_OR_LIVE_MIGRATION')
    saved=mod.strict_json(mod.protected(FAILED/'migration-offline-container.json'));info=m.inspect(saved['id']);need(saved['phase']=='offline' and saved['source_sha']==mod.SOURCE_SHA and saved['image']==prepared['candidate_image']==info['Image'] and info['State']['Running'] is False and info['State']['ExitCode']==0,'ONLY_SUCCESSFUL_EXITED_OFFLINE_MIGRATION_ALLOWED')
    changed=[{'table':name,'before_count':r.proof['rows'][name]['count'],'current_count':current['rows'][name]['count'],'rows_changed':r.proof['rows'][name]['rows_sha256']!=current['rows'][name]['rows_sha256'],'shape_changed':r.proof['rows'][name]['shape_sha256']!=current['rows'][name]['shape_sha256']} for name in sorted(r.proof['rows']) if r.proof['rows'][name]!=current['rows'].get(name)]
    result={'stage':'MEDIA_AUTOMATION_R2_PREACTIVATION_READONLY_STATE','source_sha':mod.SOURCE_SHA,'runtime':current['crm'],'backend_file_count':420,'schema_revision':current['schema_revision'],'table_count':len(current['rows']),'nginx_sha256':current['nginx_sha256'],'public_root':current['public_root'],'schema162_unchanged':current['table_definitions']==r.proof['table_definitions'],'no_activation_records':True,'no_candidate_or_live_migration':True,'offline_migration_exited_successfully':True,'prepared_sha256':args.review_sha256,'candidate_image':prepared['candidate_image'],'changed_table_count':len(changed),'changed_tables':changed[:24],'changed_tables_truncated':len(changed)>24,'business_rows_written':False,'runtime_changed':False,'existing_files_changed':False,'provider_requests':False}
    need(len(json.dumps(result).encode())<12000,'BOUNDED_READONLY_R2_RESULT_REQUIRED');print(json.dumps(result,sort_keys=True))
if __name__=='__main__':
    try:main()
    except BaseException as e:
        value=str(e);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_AUTOMATION_R2_STATE_REJECTED';print(json.dumps({'stage':'MEDIA_AUTOMATION_R2_STATE_REJECTED','code':code,'business_rows_written':False},sort_keys=True));raise SystemExit(1)
