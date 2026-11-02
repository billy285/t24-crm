"""Read-only failed-prepare diagnosis plus a new private current baseline.

Only names/counts/booleans and aggregate fingerprints leave this process.
No business row, production container, schema or existing file is changed.
"""
import hashlib,json,os,re,resource,socket,stat,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
ROOT=Path('/opt/t24-crm/releases')
FAILED=ROOT/'media-automation-53d66ebb6c69-20261102'
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
    row=FAILED.lstat();need(FAILED.resolve()==FAILED and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and stat.S_IMODE(row.st_mode)==0o700,'ROOT_PRIVATE_FAILED_STAGING_REQUIRED')
    need({p.name for p in FAILED.iterdir()}==set(FILES),'FAILED_STAGING_NOT_ARTIFACT_ONLY_REQUIRES_REVIEW')
    bodies={name:protected(FAILED/name,*pins) for name,pins in FILES.items()}
    pf=types.ModuleType('_failed_prepare_readonly_current');pf.__file__=str(FAILED/'preflight.py');exec(compile(bodies['preflight.py'],pf.__file__,'exec'),pf.__dict__)
    _,static,inventory=pf.dependencies();m=static.m
    need(all(m.inspect_optional(n) is None for n in NAMES),'UNEXPECTED_CANDIDATE_OR_MIGRATION_CONTAINER_REQUIRES_REVIEW')
    old=json.loads(pf.read(ROOT/('media-automation-preflight-'+OLD_PROOF[:12]+'.json'),OLD_PROOF,1048576))
    need(old['stage']=='MEDIA_AUTOMATION_READONLY_PREFLIGHT' and len(old['rows'])==162 and old['backend_inventory']==inventory,'EXACT_FAILED_ATTEMPT_BASELINE_REQUIRED')
    fresh=pf.capture();current=json.loads(pf.read(Path(fresh['path']),fresh['sha256'],1048576))
    need(current['crm']==old['crm'] and current['backend_inventory']==old['backend_inventory'] and current['schema_sha256']==old['schema_sha256'] and current['table_definitions']==old['table_definitions'],'RUNTIME_SOURCE_OR_SCHEMA_CHANGED_REQUIRES_REVIEW')
    changed=[{'table':name,'before_count':old['rows'][name]['count'],'current_count':current['rows'][name]['count'],'rows_changed':old['rows'][name]['rows_sha256']!=current['rows'][name]['rows_sha256'],'shape_changed':old['rows'][name]['shape_sha256']!=current['rows'][name]['shape_sha256']} for name in sorted(old['rows']) if old['rows'][name]!=current['rows'].get(name)]
    need({p.name for p in FAILED.iterdir()}==set(FILES) and all(m.inspect_optional(n) is None for n in NAMES),'FAILED_PREPARE_STATE_CHANGED_DURING_DIAGNOSIS')
    for name,pins in FILES.items():protected(FAILED/name,*pins)
    result={'stage':'MEDIA_AUTOMATION_FAILED_PREPARE_READONLY_DIAGNOSIS','old_preflight_sha256':OLD_PROOF,'new_preflight':fresh,'changed_table_count':len(changed),'unchanged_table_count':162-len(changed),'changed_tables':changed[:24],'changed_tables_truncated':len(changed)>24,'failed_staging':str(FAILED),'failed_staging_exact_four_artifacts_verified':True,'no_activation_or_migration_record':True,'all_seven_candidate_migration_names_absent':True,'runtime420_and_original162_schema_unchanged':True,'schema_revision':'g32ed456e792','new_application_worker_not_deployed':True,'business_rows_written':False,'production_schema_changed':False,'runtime_changed':False,'existing_files_changed':False,'provider_requests':False}
    need(len(json.dumps(result).encode())<18000,'BOUNDED_NO_ROW_CONTENT_DIAGNOSIS_REQUIRED');print(json.dumps(result,sort_keys=True))
if __name__=='__main__':
    try:main()
    except BaseException as e:
        value=str(e);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_AUTOMATION_READONLY_DIAGNOSIS_REJECTED';print(json.dumps({'stage':'MEDIA_AUTOMATION_READONLY_DIAGNOSIS_REJECTED','code':code,'business_rows_written':False},sort_keys=True));raise SystemExit(1)
