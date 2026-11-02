"""Aggregate-only read-only production verification after live write frontier.

No provider, authenticated browser request, SQL write or automatic recovery.
Business-row deltas are reported, never mistaken for a failed additive migration.
"""
import argparse,hashlib,json,os,re,resource,socket,sqlite3,types
from datetime import datetime,timezone
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
SOURCE='54e027aad00e81a4ebb747ada1299e7a10e1ec52'
ROOT=Path('/opt/t24-crm/releases/media-unified-settings-54e027aad00e-20261102')
HELPER='b9d954130b99802bf444fe1ce99b73ba869c21ca95d1387ebb6d124d06ea109e'
PREPARED='c96bb2707cfd7c1c83a0bc01e7e17671a5997b20f09d27b44bbb42801ab91482'
MANIFEST='0292d5bf251f16b03bfb0692942715c0cd304f998fe644211b95e780433341e3'
PAYLOAD='64537d65fbdf9b8f249d004f6639e9d2d7b5c28ac14bf43f256cee3cdf442439'
BASELINE='0dd43fefcf43ee7c925cbf825b3d88fb125abe1168f3adde9478ba603205dc83'
MEDIA_TABLES=('media_monthly_runs','media_monthly_items','media_monthly_workflows','media_monthly_workflow_requests','media_operation_tasks','media_operation_events','media_operation_publication_specs','google_business_schedules','google_business_actions','meta_operations_schedules','meta_operations_drafts','meta_operations_actions')
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def protected(path,sha,maximum=131072):
    need(path.resolve()==path and path.is_absolute(),'CANONICAL_ROOT_PRIVATE_FILE_REQUIRED')
    for parent in path.parents:
        row=parent.lstat();need(parent.resolve()==parent and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_ROOT_PARENT_REQUIRED')
    import stat
    before=path.lstat();need(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<=maximum,'EXACT_ROOT600_FILE_REQUIRED');fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:opened=os.fstat(f.fileno());body=f.read(maximum+1);after=os.fstat(f.fileno())
    identity=lambda r:(r.st_dev,r.st_ino,r.st_uid,r.st_mode,r.st_nlink,r.st_size,r.st_mtime_ns,r.st_ctime_ns)
    need(identity(before)==identity(opened)==identity(after)==identity(path.lstat()) and len(body)==before.st_size and H(body)==sha,'EXACT_FROZEN_POSTFLIGHT_INPUT_REQUIRED');return body
def heartbeat(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN');rows=con.execute('SELECT enabled,platform,last_checked_at FROM media_monthly_automation_policies ORDER BY id').fetchall();now=datetime.now(timezone.utc);active=[row for row in rows if row[0]];recent=0;missing=0;ages=[];platforms={}
        for _,platform,checked in active:
            platforms[platform]=platforms.get(platform,0)+1
            if checked is None:missing+=1;continue
            at=datetime.fromisoformat(str(checked).replace('Z','+00:00'))
            if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
            age=(now-at).total_seconds();ages.append(round(age,1));recent+=int(0<=age<=180)
        occurrences=con.execute('SELECT count(*) FROM media_monthly_automation_occurrences').fetchone()[0]
        return {'total_policy_count':len(rows),'enabled_policy_count':len(active),'enabled_platform_counts':platforms,'enabled_policies_seen_within_180_seconds':recent,'enabled_policies_missing_last_checked':missing,'enabled_policy_min_age_seconds':min(ages) if ages else None,'enabled_policy_max_age_seconds':max(ages) if ages else None,'occurrence_count':occurrences,'sampled_at_utc':now.isoformat()}
    finally:con.close()
def compare_media(before,after):
    need(all(name in before and name in after for name in MEDIA_TABLES),'EXPECTED_OLD_MEDIA_TABLES_REQUIRED')
    return {name:{'before_count':before[name]['count'],'current_count':after[name]['count'],'rows_hash_match':before[name]['rows_sha256']==after[name]['rows_sha256'],'shape_hash_match':before[name]['shape_sha256']==after[name]['shape_sha256']} for name in MEDIA_TABLES}
def main():
    p=argparse.ArgumentParser();p.add_argument('--deployed-sha256',required=True);a=p.parse_args();need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');need(re.fullmatch('[a-f0-9]{64}',a.deployed_sha256 or ''),'EXACT_DEPLOYED_RECEIPT_HASH_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    body=protected(ROOT/'release.py',HELPER);module=types.ModuleType('_unified_postflight_single_load');module.__file__=str(ROOT/'release.py');exec(compile(body,module.__file__,'exec'),module.__dict__)
    args=types.SimpleNamespace(phase='recover',release=ROOT,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,preflight=ROOT.parent/('media-unified-settings-baseline-'+BASELINE[:12]+'.json'),preflight_sha256=BASELINE,review_sha256=PREPARED)
    release=module.Release(args);prepared,old=release.reviewed(recovery=True);deployed=module.strict_json(module.protected(ROOT/'deployed.json',a.deployed_sha256,1048576))
    need(deployed['stage']=='MEDIA_UNIFIED_SETTINGS_DEPLOYED' and deployed['source_sha']==SOURCE and deployed['schema_revision']=='i54af678a914' and deployed['table_count']==169 and deployed['prepared_sha256']==PREPARED and deployed['post_start_live_business_rows_frozen'] is False and deployed['all165_rows_sequences_preserved_before_start'] is True,'EXACT_SUCCESSFUL_DATA_FRONTIER_RECEIPT_REQUIRED')
    baseline=module.strict_json(module.protected(ROOT/'activation-baseline.json',deployed['quiescent165_baseline_sha256'],1048576));preserved=module.strict_json(module.protected(ROOT/'prestart-preservation.json',deployed['prestart_preservation_sha256'],1048576));need(len(baseline['rows'])==165 and baseline['source_sha']==SOURCE and baseline['prepared_sha256']==PREPARED and preserved['baseline_sha256']==deployed['quiescent165_baseline_sha256'] and preserved['all165_rows_sequences_exact'] is True and preserved['four_new_tables_empty'] is True and preserved['candidate_not_started'] is True,'EXACT_QUIESCENT_TO_PRESTART_DATA_PRESERVATION_REQUIRED')
    m=release.m;original,candidate=release.identities(prepared,old);need(candidate['Id']==deployed['crm']['id'] and m.runtime(candidate)==deployed['crm'] and candidate['State']['Running'] is True and original['State']['Running'] is False and m.inspect('t24-crm')['Id']==candidate['Id'],'EXACT_DEPLOYED_LIVE_RUNTIME_REQUIRED');release.environment(candidate);release.base.c.retained.compare(candidate,old,m);expected={**release.inventory,**module.BACKEND_AFTER};need(m.inventory(candidate['Id'])==expected,'EXACT_DEPLOYED_FULL_SOURCE_REQUIRED');release.immutable(migrated=True,updated=True);release.writer_census((candidate['Id'],));release.public_check()
    current=release.rows();need(len(current)==169 and all(current[name]['count']==0 for name in module.NEW_TABLES),'EXACT169_SCHEMA_FOUR_EMPTY_TABLES_REQUIRED');comparisons=compare_media(baseline['rows'],current);needs_review=[name for name,row in comparisons.items() if not row['rows_hash_match'] or not row['shape_hash_match']];changed=[name for name,row in baseline['rows'].items() if name!='alembic_version' and row!=current[name]]
    result={'stage':'MEDIA_UNIFIED_SETTINGS_READONLY_POSTFLIGHT','deployed_sha256':a.deployed_sha256,'source_sha':SOURCE,'frontend_version':deployed['frontend_version'],'schema_revision':'i54af678a914','schema_sha256':deployed['schema_sha256'],'table_count':169,'current_runtime':m.runtime(candidate),'runtime_backend_file_count':len(expected),'all169_table_definitions_verified':True,'four_new_settings_tables_empty':True,'all_old_worker_flags_environment_credentials_private_static_csp_preserved':True,'monthly_auto_prep_enabled':True,'quiescent165_baseline_sha256':deployed['quiescent165_baseline_sha256'],'prestart_preservation_sha256':deployed['prestart_preservation_sha256'],'all165_rows_sequences_preserved_before_candidate_start':True,'post_start_live_rows_frozen':False,'selected_media_comparison':comparisons,'selected_media_tables_requiring_review':needs_review,'old_post_start_changed_table_names':changed[:24],'old_post_start_changed_tables_truncated':len(changed)>24,'existing_active_worker':heartbeat(m.BUSINESS),'business_writes':False,'schema_writes':False,'provider_requests':False,'authenticated_browser_requests':False,'runtime_mutations':False,'automatic_recovery_requested':False}
    need(len(json.dumps(result).encode())<18000,'BOUNDED_AGGREGATE_POSTFLIGHT_REQUIRED');print(json.dumps(result,sort_keys=True))
if __name__=='__main__':
    try:main()
    except BaseException as e:
        v=str(e);code=v if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',v) else 'MEDIA_UNIFIED_SETTINGS_POSTFLIGHT_REJECTED';print(json.dumps({'stage':'MEDIA_UNIFIED_SETTINGS_POSTFLIGHT_REJECTED','code':code,'business_writes':False},sort_keys=True));raise SystemExit(1)
