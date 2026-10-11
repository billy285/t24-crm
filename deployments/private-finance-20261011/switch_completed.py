#!/usr/bin/env python3
"""Explicit, phased private-only release. Never restores a database or changes CRM.

schema freezes the old private writers and validates an additive in-place schema.
activate starts only the new private API after the separately verified Stripe seed.
finish requires the first persisted Stripe sync, then starts the private worker.
rollback explicitly restores retained old services; new encrypted Stripe credentials
and schema remain, but the old implementation does not provide new Stripe features.
All inspection, environment values and provider metadata remain in process memory.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4

import candidate_prepare as candidate
import credential_transfer as transfer
import live_preflight as live
import private_schema_guard as guard
import seed_private_stripe as seed

MINIMUM_TESTS = 807
ROLE_LABEL = 't24.private_finance.release.attempt'
DISABLED = {
    'PRIVATE_WORKSPACE_PLAID_ENABLED': 'false', 'PRIVATE_MAIL_TRANSLATION_ENABLED': 'false',
    'PRIVATE_MAIL_BRIEF_ENABLED': 'false', 'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT': 'false',
    'PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED': 'false', 'PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT': 'false',
}
API_PROGRAM = ['services.private_workspace_app:app', '--host', '0.0.0.0', '--port', '8001', '--no-access-log']
WORKER_PROGRAM = ['-m', 'services.private_workspace_worker']
INIT_CODE = """import asyncio,json,os
os.environ.update(CONFIG)
from services.private_workspace import private_session_factory,close_private_workspace_storage
async def operation():
 await private_session_factory()
 await close_private_workspace_storage()
asyncio.run(operation())
print(json.dumps({'stage':'PRIVATE_INITIALIZER_EXITED'}))
""".replace('CONFIG', repr({**DISABLED, 'APP_ENV':'production', 'ENVIRONMENT':'production',
    'DATABASE_URL':'sqlite+aiosqlite:////app/backend/data/crm_prod.db', 'DATABASE_SCHEMA_MODE':'verify_only',
    'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:////private-data/workspace.db',
    'PRIVATE_WORKSPACE_OWNER_IDS':'4', 'PYTHONDONTWRITEBYTECODE':'1'}))


class SwitchError(RuntimeError): pass

class SafeParser(argparse.ArgumentParser):
    def error(self, message): raise SwitchError('ARGUMENTS_REJECTED')

def need(condition, code):
    if not condition: raise SwitchError(code)

def sha(blob): return hashlib.sha256(blob).hexdigest()

def fixed_json(path, expected): return seed.fixed_json(path, expected)

def save(path, value, *, replace=False):
    transfer.protected_directory(path.parent)
    blob = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    if not replace:
        transfer.write_exclusive(path, blob)
    else:
        old = transfer.read_protected(path, 4*1024**2)
        info = path.lstat(); temporary = path.parent / ('.' + path.name + '-' + uuid4().hex)
        transfer.write_exclusive(temporary, blob)
        need(path.lstat().st_ino == info.st_ino and transfer.read_protected(path, 4*1024**2) == old,
             'RECEIPT_CONCURRENT_CHANGE')
        os.replace(temporary, path); transfer.fsync_directory(path.parent)
    return sha(blob)

def root_guard():
    need(os.geteuid() == 0 and socket.gethostname() == live.HOST, 'EXPLICIT_VERIFIED_ROOT_SERVER_REQUIRED')
    transfer.protected_directory(transfer.CONFIG)

@contextmanager
def release_lock():
    root_guard()
    path = transfer.CONFIG / 'private-finance-release.lock'
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor); on_disk = path.lstat()
        need(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and
             stat.S_IMODE(info.st_mode) == 0o600 and (info.st_dev,info.st_ino) == (on_disk.st_dev,on_disk.st_ino),
             'PROTECTED_SHARED_RELEASE_LOCK_REQUIRED')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)

def docker(arguments, *, timeout=30):
    try:
        result = subprocess.run(['docker', *arguments], capture_output=True, timeout=timeout, check=False)
    except Exception:
        raise SwitchError('DOCKER_OUTCOME_REQUIRES_OPERATOR_REVIEW') from None
    need(result.returncode == 0, 'DOCKER_OPERATION_REJECTED')
    return result.stdout

def inspect(identity, *, optional=False):
    try:
        result = subprocess.run(['docker','inspect',identity], capture_output=True, timeout=30, check=False)
    except Exception:
        raise SwitchError('INSPECTION_REQUIRES_OPERATOR_REVIEW') from None
    if optional and result.returncode != 0: return None
    need(result.returncode == 0, 'CONTAINER_INSPECTION_FAILED')
    rows = json.loads(result.stdout)
    need(isinstance(rows,list) and len(rows) == 1, 'SINGLE_CONTAINER_REQUIRED')
    return rows[0]

def environment(info):
    values = {}
    for row in info['Config']['Env']:
        need(isinstance(row,str) and '=' in row, 'CONTAINER_ENVIRONMENT_REJECTED')
        name,value = row.split('=',1)
        need(name not in values, 'DUPLICATE_CONTAINER_ENVIRONMENT')
        values[name] = value
    return values

def runtime_guard(baseline):
    need(live.crm_snapshot() == baseline['crm'], 'CRM_RUNTIME_CHANGED')
    need(sha(transfer.read_protected(transfer.ENV)) == live.ENV_SHA == baseline['environment_sha256'],
         'ORIGINAL_RUNTIME_ENVIRONMENT_CHANGED')
    need(sha(live.safe_file(live.NGINX, maximum=65536)) == baseline['nginx_sha256'] and
         json.loads(live.safe_file(live.PUBLIC/'app-version.json', maximum=4096)) == {'version':baseline['frontend_version']},
         'STATIC_CHANGED_DURING_PRIVATE_RELEASE')
    values = live.parse_env(transfer.read_protected(transfer.ENV))
    need(environment(inspect(live.CRM_ID)).get('JWT_SECRET_KEY') == values['JWT_SECRET_KEY'], 'SHARED_IDENTITY_KEY_DRIFT')
    return values

def checked_candidate(args):
    path = args.candidate; release = path.parent
    transfer.protected_directory(release)
    need(release.parent == Path('/opt/t24-crm/releases') and re.fullmatch(
         'private-finance-' + args.source_sha[:12] + '-20261011-candidate(?:-[a-z0-9]{1,16})?',release.name)
         and path.name == 'candidate.json', 'EXACT_REVIEWED_CANDIDATE_PATH_REQUIRED')
    receipt = seed.checked_candidate(fixed_json(path,args.candidate_sha256),source_sha=args.source_sha,release=release)
    need(receipt['candidate_regressions']['minimum'] >= MINIMUM_TESTS and receipt['candidate_regressions']['tests'] >= MINIMUM_TESTS,
         'COMPLETE_SERVER_807_REGRESSIONS_REQUIRED')
    images = json.loads(docker(['image','inspect',receipt['image_id']]))
    base = json.loads(docker(['image','inspect',live.PRIVATE_IMAGE]))
    need(len(images) == len(base) == 1 and images[0]['Id'] == receipt['image_id'] and
         images[0]['Config'].get('Labels',{}).get('t24.private.source.sha') == args.source_sha,
         'CANDIDATE_IMAGE_OR_SOURCE_DRIFT')
    candidate.verify_candidate_base(base[0],images[0])
    return receipt

def old_check(role, baseline, *, running=None):
    need(role in {'api','worker'}, 'OLD_ROLE_REJECTED')
    info = inspect(live.PRIVATE_IDS[role]); previous = baseline['private'][role]
    need(info['Id'] == previous['id'] == live.PRIVATE_IDS[role] and info['Image'] == live.PRIVATE_IMAGE and
         live.config_hash(info) == previous['configuration_sha256'], 'RETAINED_OLD_PRIVATE_CONFIGURATION_DRIFT')
    need(not info['State'].get('Dead') and not info['State'].get('Restarting'), 'OLD_PRIVATE_STATE_REJECTED')
    if running is not None: need(info['State']['Running'] is running, 'OLD_PRIVATE_RUNNING_STATE_DRIFT')
    if running is True:
        need(info['State']['StartedAt'] == previous['started_at'] and
             ('restart_count' not in previous or info.get('RestartCount')==previous['restart_count']),
             'OLD_PRIVATE_START_TIME_DRIFT')
    return info

def no_writers(allowed=()):
    allowed = set(allowed)
    need(not (allowed & {live.CRM_ID,*live.PRIVATE_IDS.values()}), 'OLD_OR_BUSINESS_WRITER_CANNOT_BE_ALLOWED')
    ids = docker(['ps','--quiet','--no-trunc']).decode().splitlines()
    need(all(re.fullmatch('[a-f0-9]{64}',identity) for identity in ids), 'RUNNING_CONTAINER_INVENTORY_REJECTED')
    for identity in ids:
        info = inspect(identity)
        for mount in info.get('Mounts',[]):
            if mount.get('Type') == 'bind' and mount.get('RW') and mount.get('Source'):
                source = Path(mount['Source']).resolve()
                root = live.PRIVATE_DB.parent
                if source == root or source in root.parents or root in source.parents:
                    need(identity in allowed, 'UNEXPECTED_PRIVATE_DATABASE_WRITER')
    for identity in live.PRIVATE_IDS.values():
        need(not inspect(identity)['State']['Running'], 'OLD_PRIVATE_WRITER_MUST_BE_STOPPED')

def checked_business(current, before):
    need(current['business'] == before['business'] and len(current['business']['tables']) == 83,
         'ALL_CUSTOMER_TABLE_FINGERPRINTS_MUST_BE_UNCHANGED')

def backup_private(path, before):
    transfer.write_exclusive(path,b'')
    need(not os.path.samefile(path,live.PRIVATE_DB) and not os.path.samefile(path,live.BUSINESS), 'DISTINCT_BACKUP_REQUIRED')
    with sqlite3.connect(live.PRIVATE_DB.as_uri()+'?mode=ro',uri=True,timeout=15) as source, sqlite3.connect(path,timeout=15) as target:
        source.backup(target)
    path.chmod(0o600)
    descriptor = os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    transfer.fsync_directory(path.parent)
    value = guard.database_snapshot(path,private=True)
    need(set(value['tables']) == guard.BASE_TABLES and all(value[key] == before['private'][key]
         for key in ('tables','schema_objects','schema_sha256','data_sha256')), 'EXACT_ORIGINAL_PRIVATE_BACKUP_REQUIRED')
    return sha(transfer.read_protected(path,512*1024**2))

def initializer_command(name, image, attempt):
    need(re.fullmatch('t24-private-finance-initialize-[a-f0-9]{32}',name) and re.fullmatch('[a-f0-9]{32}',attempt),
         'EXCLUSIVE_INITIALIZER_NAME_REQUIRED')
    return ['create','--name',name,'--network','none','--restart','no','--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--log-driver','none','--pids-limit','64','--memory','256m','--cpus','1',
        '--tmpfs','/tmp:rw,nosuid,noexec,size=64m','--workdir','/app/backend','--env','PYTHONDONTWRITEBYTECODE=1',
        '--mount','type=bind,src='+str(live.BUSINESS.parent)+',dst=/app/backend/data,readonly',
        '--mount','type=bind,src='+str(live.PRIVATE_DB.parent)+',dst=/private-data',
        '--label',ROLE_LABEL+'='+attempt,'--label','t24.private.role=initializer','--entrypoint','python',image,'-c',INIT_CODE]

def initializer_check(info, image, attempt):
    host,config = info['HostConfig'],info['Config']
    need(info['Image'] == image and config.get('Labels',{}).get(ROLE_LABEL) == attempt and
         config.get('Labels',{}).get('t24.private.role') == 'initializer', 'INITIALIZER_IDENTITY_REJECTED')
    need(host.get('NetworkMode') == 'none' and host.get('ReadonlyRootfs') is True and host.get('CapDrop') == ['ALL'] and
         host.get('SecurityOpt') in (['no-new-privileges'],['no-new-privileges:true']) and
         host.get('RestartPolicy',{}).get('Name') == 'no' and host.get('LogConfig',{}).get('Type') == 'none' and
         host.get('Tmpfs') == {'/tmp':'rw,nosuid,noexec,size=64m'} and not host.get('PortBindings') and
         host.get('PidsLimit') == 64 and host.get('Memory') == 256*1024**2 and host.get('NanoCpus') == 10**9,
         'INITIALIZER_ISOLATION_REJECTED')
    checked_mounts(info)
    need(config.get('Entrypoint') == ['python'] and config.get('Cmd') == ['-c',INIT_CODE] and
         config.get('WorkingDir') == '/app/backend' and set(environment(info)) <= transfer.SAFE_IMAGE_ENV_NAMES,
         'INITIALIZER_FIXED_PROGRAM_AND_NO_PRODUCTION_ENV_REQUIRED')
    return info

def checked_mounts(info):
    host = info['HostConfig']
    need(not host.get('Privileged') and not host.get('CapAdd') and not host.get('Devices') and
         not host.get('DeviceRequests') and not host.get('Binds') and host.get('PidMode','') == '' and
         host.get('UTSMode','') == '' and host.get('IpcMode') == 'private', 'PRIVATE_ISOLATION_REJECTED')
    mounts = info.get('Mounts',[]); binds = [m for m in mounts if m.get('Type') == 'bind']
    need(len(binds) == 2 and {(m['Source'],m['Destination'],m['RW']) for m in binds} == {
         (str(live.BUSINESS.parent),'/app/backend/data',False),(str(live.PRIVATE_DB.parent),'/private-data',True)} and
         len(mounts) <= 3 and all(m.get('Type') == 'bind' or m.get('Type') == 'tmpfs' and
         m.get('Destination') == '/tmp' and m.get('RW') for m in mounts), 'ONLY_PRIVATE_DATABASE_WRITABLE_MOUNT_REQUIRED')

def run_initializer(image, attempt, progress, progress_path):
    name = 't24-private-finance-initialize-'+attempt
    need(inspect(name,optional=True) is None, 'INITIALIZER_NAME_COLLISION')
    progress['initializer_name'] = name; save(progress_path,progress,replace=True)
    identity = docker(initializer_command(name,image,attempt)).decode().strip()
    need(re.fullmatch('[a-f0-9]{64}',identity), 'INITIALIZER_ID_REQUIRED')
    initializer_check(inspect(identity),image,attempt)
    progress['initializer_id'] = identity; save(progress_path,progress,replace=True)
    no_writers()
    result = docker(['start','--attach',identity],timeout=90)
    info = initializer_check(inspect(identity),image,attempt)
    need(not info['State']['Running'] and info['State'].get('ExitCode') == 0 and
         json.loads(result) == {'stage':'PRIVATE_INITIALIZER_EXITED'}, 'INITIALIZER_SAFE_SUCCESS_REQUIRED')
    docker(['rm',identity])
    progress['initializer_completed'] = True; save(progress_path,progress,replace=True)

def schema(args):
    receipt = checked_candidate(args)
    baseline = fixed_json(args.baseline,args.baseline_sha256)
    need(receipt['baseline_sha256'] == args.baseline_sha256, 'CANDIDATE_BASELINE_BINDING_REQUIRED')
    live.compare_baseline(live.preflight(),baseline)
    root = args.output_dir
    need(root == args.candidate.parent/'completed-release' and not root.exists() and not root.is_symlink(),
         'NEW_EXCLUSIVE_COMPLETED_RELEASE_DIRECTORY_REQUIRED')
    root.mkdir(mode=0o700); transfer.protected_directory(root)
    attempt = uuid4().hex
    progress = {'format_version':1,'phase':'PRIVATE_SCHEMA_FREEZE_PREPARED','source_sha':args.source_sha,
        'candidate':str(args.candidate),'candidate_sha256':args.candidate_sha256,'candidate_image':receipt['image_id'],
        'baseline':str(args.baseline),'baseline_sha256':args.baseline_sha256,'attempt':attempt,'old_ids':live.PRIVATE_IDS,
        'stopped_roles':[],'bank_enabled':False,'ai_enabled':False,'databases_restored':False,'public_assets_published':False,'deployed':False}
    journal = root/'schema-progress.json'; save(journal,progress)
    for role in ('worker','api'):
        old_check(role,baseline,running=True)
        progress['stop_intent'] = role; save(journal,progress,replace=True)
        docker(['stop','--time','30',live.PRIVATE_IDS[role]],timeout=45)
        old_check(role,baseline,running=False)
        progress['stopped_roles'].append(role); save(journal,progress,replace=True)
    no_writers(); runtime_guard(baseline)
    before = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    need(set(before['private']['tables']) == guard.BASE_TABLES, 'ORIGINAL_FOUR_PRIVATE_TABLES_REQUIRED')
    need((before['private']['identity']['device'],before['private']['identity']['inode']) == live.PRIVATE_DEVICE_INODE,
         'ORIGINAL_PRIVATE_DATABASE_INODE_REQUIRED')
    before_sha = save(root/'schema-before.json',before)
    progress['schema_before_sha256'] = before_sha; save(journal,progress,replace=True)
    backup_sha = backup_private(root/'original-private.db',before)
    progress.update(schema_before_sha256=before_sha,backup_sha256=backup_sha)
    save(journal,progress,replace=True)
    manifest = {'format_version':1,'stage':'FROZEN_PRIVATE_ADDITIVE_SCHEMA_MANIFEST','source_sha':args.source_sha,
        'baseline_tables':sorted(guard.BASE_TABLES),'target_tables':sorted(candidate.TARGET_TABLES),
        'target_schema_objects':receipt['synthetic_schema']['schema_objects'],'business_table_count':83,
        'business_schema_sha256':before['business']['schema_sha256']}
    guard.checked_manifest(manifest,source_sha=args.source_sha)
    manifest_sha = save(root/'schema-manifest.json',manifest)
    no_writers(); runtime_guard(baseline)
    need(guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS) == before, 'FROZEN_ORIGINAL_DATABASE_DRIFT')
    run_initializer(receipt['image_id'],attempt,progress,journal)
    no_writers(); runtime_guard(baseline)
    after = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    validation = guard.compare_snapshots(before,after,manifest,source_sha=args.source_sha,mode='in_place')
    seed.checked_backup(root/'original-private.db',backup_sha,before)
    after_sha = save(root/'schema-after.json',after)
    validation_sha = save(root/'schema-validation.json',validation)
    value = {**progress,'phase':'PRIVATE_COMPLETED_SCHEMA_VERIFIED_WRITERS_STOPPED',
        'schema_before':str(root/'schema-before.json'),'schema_before_sha256':before_sha,
        'schema_after':str(root/'schema-after.json'),'schema_after_sha256':after_sha,
        'schema_manifest':str(root/'schema-manifest.json'),'schema_manifest_sha256':manifest_sha,
        'schema_validation':str(root/'schema-validation.json'),'schema_validation_sha256':validation_sha,
        'backup':str(root/'original-private.db'),'backup_sha256':backup_sha,'runtime_env_sha256':live.ENV_SHA,
        'customer_tables_verified':83,'original_rows_columns_indexes_preserved':True,'same_private_inode':True,
        'new_tables_empty':True,'worker_started':False,'services_switched':False}
    saved = save(root/'schema-state.json',value)
    print(json.dumps({'phase':value['phase'],'schema_state_sha256':saved,'files':{key:value[key] for key in
        ('schema_before','schema_before_sha256','schema_after','schema_after_sha256','schema_manifest','schema_manifest_sha256',
         'schema_validation','schema_validation_sha256','backup','backup_sha256')},'deployed':False},sort_keys=True))

def checked_schema_state(args, receipt):
    state = fixed_json(args.schema_state,args.schema_state_sha256)
    root = args.candidate.parent/'completed-release'
    if state.get('resume_lineage') is not None:
        return checked_resume_schema_state(args,receipt,state)
    need(args.schema_state == root/'schema-state.json' and state.get('phase') == 'PRIVATE_COMPLETED_SCHEMA_VERIFIED_WRITERS_STOPPED' and
         state.get('candidate_sha256') == args.candidate_sha256 and state.get('source_sha') == args.source_sha and
         state.get('candidate_image') == receipt['image_id'] and state.get('old_ids') == live.PRIVATE_IDS and
         state.get('bank_enabled') is False and state.get('ai_enabled') is False,
         'EXACT_COMPLETED_SCHEMA_STATE_REQUIRED')
    files = {}
    for key,filename in (('schema_before','schema-before.json'),('schema_after','schema-after.json'),
                         ('schema_manifest','schema-manifest.json'),('schema_validation','schema-validation.json')):
        need(state.get(key) == str(root/filename), 'SCHEMA_RECEIPT_PATH_DRIFT')
        files[key] = fixed_json(Path(state[key]),state[key+'_sha256'])
    before,after,manifest,validation = (files[key] for key in ('schema_before','schema_after','schema_manifest','schema_validation'))
    need(guard.compare_snapshots(before,after,manifest,source_sha=args.source_sha,mode='in_place') == validation and
         manifest['target_schema_objects'] == receipt['synthetic_schema']['schema_objects'], 'ACTUAL_SCHEMA_ACCEPTANCE_DRIFT')
    need(state.get('backup') == str(root/'original-private.db'), 'BACKUP_PATH_DRIFT')
    seed.checked_backup(Path(state['backup']),state['backup_sha256'],before)
    baseline = fixed_json(Path(state['baseline']),state['baseline_sha256'])
    need(receipt['baseline_sha256'] == state['baseline_sha256'], 'SCHEMA_BASELINE_BINDING_DRIFT')
    return state,before,after,baseline

def checked_resume_schema_state(args,receipt,state):
    import resume_preflight as resumed
    root=args.candidate.parent/'completed-release'
    need(args.schema_state==root/'schema-state.json' and
         state.get('phase')=='PRIVATE_COMPLETED_RESUME_VERIFIED_WRITERS_STOPPED' and
         state.get('source_sha')==args.source_sha and state.get('candidate_sha256')==args.candidate_sha256 and
         state.get('candidate_image')==receipt['image_id'] and state.get('old_ids')==live.PRIVATE_IDS and
         state.get('resume_lineage')==receipt.get('resume_lineage') and
         state.get('bank_enabled') is False and state.get('ai_enabled') is False and
         state.get('initializer_rerun') is False and state.get('database_migration_performed') is False and
         re.fullmatch('[a-f0-9]{32}',state.get('attempt','')),
         'EXACT_REVIEWED_RESUME_SCHEMA_STATE_REQUIRED')
    original,before,original_after,old_baseline,baseline=resumed.checked_lineage(receipt)
    for key in ('schema_before','schema_manifest','schema_validation','backup'):
        need(state.get(key)==original.get(key) and state.get(key+'_sha256')==original.get(key+'_sha256'),
             'ORIGINAL_MIGRATION_PROOF_MUST_REMAIN_IMMUTABLE')
    need(state.get('schema_after')==str(root/'schema-after.json') and
         state.get('original_schema_after')==original.get('schema_after') and
         state.get('original_schema_after_sha256')==original.get('schema_after_sha256') and
         state.get('baseline')==receipt['resume_lineage']['new_baseline'] and
         state.get('baseline_sha256')==receipt['baseline_sha256'] and
         receipt['synthetic_schema']['schema_objects']==original_after['private']['schema_objects'],
         'NEW_CANDIDATE_AND_ORIGINAL_SCHEMA_LINEAGE_REQUIRED')
    after=fixed_json(root/'schema-after.json',state['schema_after_sha256'])
    # This is historical proof. Current connections may now include the
    # approved Stripe seed; the live absent-Stripe guard belongs before seed.
    schema_and_business_unchanged(after,original_after)
    need(set(after['private']['tables'])==candidate.TARGET_TABLES and
         all(after['private']['tables'][name]['rows']==0 for name in candidate.TARGET_TABLES-guard.BASE_TABLES) and
         state.get('stripe_connection_absent') is True,'HISTORICAL_FROZEN_RESUME_SCHEMA_REQUIRED')
    need(state.get('frozen_seed_before_sha256')==guard.digest(after) and
         isinstance(state.get('resume_stable_before'),dict) and
         {'items','preferences','connections','other_connections','other_connection_rows_sha256','other_item_rows_sha256'}<=
         state['resume_stable_before'].keys(),
         'EXACT_FROZEN_RESUME_STATE_REQUIRED')
    # The self hash is injected on reading; it is never fabricated in a file.
    return {**state,'accepted_schema_state_sha256':args.schema_state_sha256},before,after,baseline

def resume_schema(args):
    import resume_preflight as resumed
    receipt=checked_candidate(args)
    original,before,original_after,old_baseline,baseline=resumed.checked_lineage(receipt)
    need(args.baseline==Path(receipt['resume_lineage']['new_baseline']) and
         args.baseline_sha256==receipt['baseline_sha256'],'EXACT_NEW_RESUME_BASELINE_REQUIRED')
    runtime_guard(baseline)
    for role in ('api','worker'): old_check(role,baseline,running=True)
    current=guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    resumed.checked_frozen_snapshot(baseline,current)
    root=args.output_dir
    need(root==args.candidate.parent/'completed-release' and not root.exists() and not root.is_symlink(),
         'NEW_EXCLUSIVE_COMPLETED_RELEASE_DIRECTORY_REQUIRED')
    root.mkdir(mode=0o700);transfer.protected_directory(root)
    progress={'format_version':1,'phase':'PRIVATE_RESUME_FREEZE_PREPARED','source_sha':args.source_sha,
        'candidate':str(args.candidate),'candidate_sha256':args.candidate_sha256,'candidate_image':receipt['image_id'],
        'baseline':str(args.baseline),'baseline_sha256':args.baseline_sha256,'attempt':uuid4().hex,
        'old_ids':live.PRIVATE_IDS,'stopped_roles':[],'bank_enabled':False,'ai_enabled':False,
        'databases_restored':False,'public_assets_published':False,'deployed':False,
        'resume_lineage':receipt['resume_lineage'],'initializer_rerun':False,'database_migration_performed':False,
        'original_schema_after':original['schema_after'],'original_schema_after_sha256':original['schema_after_sha256']}
    for key in ('schema_before','schema_manifest','schema_validation','backup'):
        progress[key]=original[key];progress[key+'_sha256']=original[key+'_sha256']
    journal=root/'schema-progress.json';save(journal,progress)
    for role in ('worker','api'):
        old_check(role,baseline,running=True)
        progress['stop_intent']=role;save(journal,progress,replace=True)
        docker(['stop','--time','30',live.PRIVATE_IDS[role]],timeout=45)
        old_check(role,baseline,running=False)
        progress['stopped_roles'].append(role);save(journal,progress,replace=True)
    no_writers();runtime_guard(baseline)
    frozen=guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    resumed.checked_frozen_snapshot(baseline,frozen)
    after_sha=save(root/'schema-after.json',frozen)
    value={**progress,'phase':'PRIVATE_COMPLETED_RESUME_VERIFIED_WRITERS_STOPPED',
        'schema_after':str(root/'schema-after.json'),'schema_after_sha256':after_sha,
        'frozen_seed_before_sha256':guard.digest(frozen),'resume_stable_before':stable_records(live.PRIVATE_DB),
        'runtime_env_sha256':live.ENV_SHA,'customer_tables_verified':83,'same_private_inode':True,
        'new_tables_empty':True,'stripe_connection_absent':True,'worker_started':False,'services_switched':False}
    saved=save(root/'schema-state.json',value)
    print(json.dumps({'phase':value['phase'],'schema_state_sha256':saved,'initializer_rerun':False,
        'database_migration_performed':False,'original_claim_preserved':True,'deployed':False},sort_keys=True))

def role_configuration(blob, role):
    need(role in {'api','worker'} and sha(blob) == live.ENV_SHA, 'EXACT_ORIGINAL_ROLE_ENVIRONMENT_REQUIRED')
    values = dict(live.parse_env(blob))
    need(not any(name.startswith(('STRIPE_','OPENAI_','RINGCENTRAL_','OSS_','PRIVATE_WORKSPACE_PLAID_'))
         or name in {'PRIVATE_WORKSPACE_STRIPE_KEY','PRIVATE_MAIL_BRIEF_OPENAI_API_KEY'} for name in values),
         'NO_NEW_CUSTOMER_BANK_OR_AI_SECRETS_ALLOWED')
    need(len(values.get('JWT_SECRET_KEY','')) >= 32 and len(values.get('PRIVATE_WORKSPACE_ENCRYPTION_KEY','')) >= 32,
         'ORIGINAL_PRIVATE_IDENTITY_AND_ENCRYPTION_REQUIRED')
    values.update(DISABLED)
    values.update(PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID=transfer.ACCOUNT,PRIVATE_WORKSPACE_STRIPE_MODE='live',
        PYTHONDONTWRITEBYTECODE='1',PRIVATE_WORKSPACE_PROCESS_ROLE=role,
        PRIVATE_MAIL_BRIEF_MONTHLY_BUDGET_MICRO_USD='5000000')
    # The dedicated credential is only in the existing encrypted private DB.
    need('PRIVATE_WORKSPACE_STRIPE_KEY' not in values, 'PERSISTED_RUNTIME_STRIPE_KEY_REJECTED')
    return values

def profile_bytes(values): return ('\n'.join(name+'='+value for name,value in sorted(values.items()))+'\n').encode()

def create_command(name,role,image,attempt,source,profile):
    need(role in {'api','worker'} and re.fullmatch('t24-private-finance-stage-(?:api|worker)-[a-f0-9]{32}',name) and
         re.fullmatch('[a-f0-9]{32}',attempt) and re.fullmatch('[a-f0-9]{40}',source), 'EXACT_RELEASE_ROLE_REQUIRED')
    result = ['create','--name',name,'--restart','unless-stopped','--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--log-opt','max-size=5m','--log-opt','max-file=3',
        '--env-file',str(profile),'--tmpfs','/tmp:rw,nosuid,noexec,size=128m',
        '--mount','type=bind,src='+str(live.BUSINESS.parent)+',dst=/app/backend/data,readonly',
        '--mount','type=bind,src='+str(live.PRIVATE_DB.parent)+',dst=/private-data',
        '--label','t24.private.source.sha='+source,'--label','t24.private.role='+role,'--label',ROLE_LABEL+'='+attempt]
    if role == 'api':
        result += ['--publish','127.0.0.1:8001:8001','--health-cmd','curl -fsS http://127.0.0.1:8001/ready || exit 1',
            '--health-interval','15s','--health-timeout','5s','--health-start-period','15s','--health-retries','3',
            '--entrypoint','uvicorn',image,*API_PROGRAM]
    else:
        result += ['--no-healthcheck','--entrypoint','python',image,*WORKER_PROGRAM]
    return result

def staged_check(identity,role,image,attempt,source,values,*,running=None,require_stable=True):
    info = inspect(identity); host,config = info['HostConfig'],info['Config']
    need(info['Id'] == identity and identity not in {live.CRM_ID,*live.PRIVATE_IDS.values()} and info['Image'] == image,
         'NEW_PRIVATE_IDENTITY_DRIFT')
    labels = config.get('Labels',{})
    need(labels.get(ROLE_LABEL) == attempt and labels.get('t24.private.source.sha') == source and
         labels.get('t24.private.role') == role, 'NEW_PRIVATE_SOURCE_ROLE_ATTEMPT_DRIFT')
    checked_mounts(info)
    need(host.get('ReadonlyRootfs') is True and host.get('CapDrop') == ['ALL'] and
         host.get('SecurityOpt') in (['no-new-privileges'],['no-new-privileges:true']) and
         host.get('RestartPolicy',{}).get('Name') == 'unless-stopped' and
         host.get('LogConfig',{}).get('Config') == {'max-size':'5m','max-file':'3'} and
         host.get('Tmpfs') == {'/tmp':'rw,nosuid,noexec,size=128m'} and host.get('NetworkMode') in {'default','bridge'},
         'NEW_PRIVATE_PROTECTION_DRIFT')
    configured = environment(info)
    need(all(configured.get(key) == value for key,value in values.items()) and
         set(configured) <= set(values) | transfer.SAFE_IMAGE_ENV_NAMES,
         'EXACT_ROLE_ENVIRONMENT_REQUIRED')
    need(all(configured.get(key) == 'false' for key in DISABLED) and not configured.get('PRIVATE_WORKSPACE_STRIPE_KEY') and
         not any(key.startswith(('STRIPE_','OPENAI_','RINGCENTRAL_','OSS_')) for key in configured),
         'BANK_AI_AND_CUSTOMER_FINANCE_BOUNDARY_DRIFT')
    if role == 'api':
        health = config.get('Healthcheck',{})
        need(config.get('Entrypoint') == ['uvicorn'] and config.get('Cmd') == API_PROGRAM and
             host.get('PortBindings') == {'8001/tcp':[{'HostIp':'127.0.0.1','HostPort':'8001'}]} and
             health.get('Test') == ['CMD-SHELL','curl -fsS http://127.0.0.1:8001/ready || exit 1'] and
             health.get('Interval') == 15_000_000_000 and health.get('Timeout') == 5_000_000_000 and
             health.get('StartPeriod') == 15_000_000_000 and health.get('Retries') == 3,
             'NEW_API_LAUNCH_DRIFT')
    else:
        need(config.get('Entrypoint') == ['python'] and config.get('Cmd') == WORKER_PROGRAM and
             not host.get('PortBindings') and config.get('Healthcheck',{}).get('Test') == ['NONE'],
             'NEW_WORKER_LAUNCH_DRIFT')
    if running is not None: need(info['State']['Running'] is running, 'NEW_PRIVATE_RUNNING_STATE_DRIFT')
    if require_stable:
        need(not info['State'].get('Dead') and not info['State'].get('Restarting') and info['RestartCount'] == 0,
             'NEW_PRIVATE_UNSTABLE_RUNTIME')
    return {'id':identity,'image':image,'configuration_sha256':live.config_hash(info),
        'started_at':info['State']['StartedAt'],'restart_count':info['RestartCount'],'source_sha':source,
        'launch_mount_port_verified':True}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def local_request(path):
    need(path in {'/ready','/api/v1/private-workspace','/api/v1/private-workspace/access'}, 'FIXED_LOCAL_API_ONLY')
    opener = urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))
    try: response = opener.open('http://127.0.0.1:8001'+path,timeout=5)
    except urllib.error.HTTPError as error: response = error
    with response:
        body = response.read(65537)
        need(len(body) <= 65536, 'BOUNDED_LOCAL_API_RESPONSE_REQUIRED')
        return response.code,{key.lower():value for key,value in response.headers.items()},body

def wait_api(identity):
    deadline = time.monotonic()+55
    while time.monotonic() < deadline:
        info = inspect(identity)
        need(info['Id'] == identity and info['State']['Running'] and info['RestartCount'] == 0 and
             not info['State'].get('Restarting'), 'NEW_API_RUNTIME_FAILED')
        try:
            code,_,body = local_request('/ready')
            if info['State'].get('Health',{}).get('Status') == 'healthy' and code == 200 and json.loads(body) == {'ready':True}:
                break
        except (OSError,urllib.error.URLError,json.JSONDecodeError): pass
        time.sleep(1)
    else: raise SwitchError('NEW_PRIVATE_API_NOT_READY')
    for path in ('/api/v1/private-workspace','/api/v1/private-workspace/access'):
        code,headers,_ = local_request(path)
        need(code == 401 and 'no-store' in {piece.strip().lower() for piece in headers.get('cache-control','').split(',')},
             'PRIVATE_AUTHENTICATION_OR_CACHE_BOUNDARY_FAILED')

def stable_records(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=15) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        items = {row[0]:guard.digest(list(row)) for row in db.execute('SELECT id,owner_id,source_id,external_id,local_title,local_summary,action_status,snoozed_until,created_at FROM private_items')}
        prefs = {row[0]:guard.digest(list(row)) for row in db.execute('SELECT owner_id,preferences_json FROM private_preferences')}
        connections = {row[0]:guard.digest(list(row)) for row in db.execute('SELECT id,owner_id,source_id,generation,created_at FROM private_connections')}
        other_rows = db.execute("SELECT * FROM private_connections WHERE source_id <> 'stripe' ORDER BY id").fetchall()
        columns = [row[1] for row in db.execute('PRAGMA table_info(private_connections)')]
        other_identity = {}
        for row in other_rows:
            value = dict(zip(columns,row)); metadata = json.loads(value.get('metadata_json') or '{}')
            selected = {key:metadata.get(key) for key in ('account_label','scope','connection_mode','ads_customer_id','read_only_adapter')}
            other_identity[value['id']] = guard.digest([value['owner_id'],value['source_id'],value['status'],value['generation'],
                bool(value.get('encrypted_credentials')),selected])
        other_items = db.execute("SELECT * FROM private_items WHERE source_id <> 'stripe' ORDER BY id").fetchall()
    return {'items':items,'preferences':prefs,'connections':connections,'other_connections':other_identity,
        'other_connection_rows_sha256':guard.digest(other_rows),'other_item_rows_sha256':guard.digest(other_items)}

def preserved(before,after,*,allow_provider_changes=True):
    need(before['preferences'] == after['preferences'] and before['connections'] == after['connections'] and
         all(after['items'].get(key) == value for key,value in before['items'].items()),
         'PRIVATE_NOTES_ACTIONS_IDENTITIES_OR_PREFERENCES_CHANGED')
    if 'other_connections' in before:
        need(before['other_connections'] == after.get('other_connections'), 'NON_STRIPE_CONNECTION_IDENTITY_OR_SCOPE_CHANGED')
        if not allow_provider_changes:
            need(all(before[key] == after.get(key) for key in ('other_connection_rows_sha256','other_item_rows_sha256')),
                 'NON_STRIPE_ROWS_CHANGED_BEFORE_WORKER_START')

def disabled_data(current):
    need(all(current['private']['tables'][name]['rows'] == 0 for name in candidate.TARGET_TABLES-guard.BASE_TABLES),
         'BANK_OR_AI_TABLES_MUST_REMAIN_EMPTY')
    with sqlite3.connect(live.PRIVATE_DB.as_uri()+'?mode=ro',uri=True,timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        need(db.execute("SELECT 1 FROM private_connections WHERE source_id='bofa_bank' AND (status='connected' OR encrypted_credentials IS NOT NULL) LIMIT 1").fetchone() is None,
             'BANK_CONNECTION_MUST_REMAIN_DISABLED')

def checked_seed(value,args,state,current):
    checked_seed_scope(value,args,state)
    need(value.get('after_snapshot_sha256') == guard.digest(current), 'EXACT_PERSISTED_STRIPE_SEED_SNAPSHOT_REQUIRED')
    seed_state = seed.connection_state(live.PRIVATE_DB); row = seed_state['row']
    need(row and row.get('status') == 'connected' and row.get('encrypted_credentials') and not row.get('sync_lease_until') and
         not row.get('error') and row.get('generation') == value.get('generation'), 'PERSISTED_CONNECTED_STRIPE_REQUIRED')
    metadata = json.loads(row.get('metadata_json') or '{}')
    need(metadata.get('stripe_account_id') == transfer.ACCOUNT and metadata.get('mode') == 'live' and
         metadata.get('read_only_adapter') is True, 'STRIPE_LIVE_ACCOUNT_BOUNDARY_DRIFT')

def checked_seed_scope(value,args,state):
    need(value.get('stage') == 'PRIVATE_STRIPE_SEED_VERIFIED_NOT_DEPLOYED' and value.get('format_version') == 1 and
         value.get('candidate_sha256') == args.candidate_sha256 and value.get('source_sha') == args.source_sha and
         value.get('image_id') == state['candidate_image'] and value.get('schema_acceptance_sha256') == state['schema_validation_sha256'] and
         value.get('backup_sha256') == state['backup_sha256'] and value.get('six_get_probes_verified') is True and
         value.get('encrypted_db_credential_verified') is True and value.get('runtime_env_changed') is False and
         value.get('customer_data_changed') is False and value.get('other_private_connections_changed') is False and
         value.get('private_rows_changed_only_stripe_connection') is True and value.get('deployed') is False and
         re.fullmatch('[a-f0-9]{64}',value.get('after_snapshot_sha256','')) and
         re.fullmatch('[a-f0-9]{64}',value.get('before_snapshot_sha256','')), 'EXACT_PERSISTED_STRIPE_SEED_ACCEPTANCE_REQUIRED')
    if state.get('resume_lineage') is not None:
        import resume_seed_private_stripe as resumed
        resumed.checked_seed_lineage(value,args,state)
        need(value['before_snapshot_sha256']==state['frozen_seed_before_sha256'],
             'RESUME_SEED_MUST_START_AT_EXACT_FROZEN_SNAPSHOT')

def schema_and_business_unchanged(current,after):
    checked_business(current,after)
    need(current['private']['identity'] == after['private']['identity'] and
         current['private']['schema_objects'] == after['private']['schema_objects'], 'MIGRATED_DATABASE_INODE_OR_SCHEMA_CHANGED')

def create_role(role,progress,values,profile,journal):
    name = 't24-private-finance-stage-'+role+'-'+progress['attempt']
    need(inspect(name,optional=True) is None, 'NEW_ROLE_NAME_COLLISION')
    progress.setdefault('stage_names',{})[role] = name; save(journal,progress,replace=True)
    identity = docker(create_command(name,role,progress['candidate_image'],progress['attempt'],progress['source_sha'],profile)).decode().strip()
    need(re.fullmatch('[a-f0-9]{64}',identity), 'NEW_ROLE_CONTAINER_ID_REQUIRED')
    staged_check(identity,role,progress['candidate_image'],progress['attempt'],progress['source_sha'],values,running=False)
    progress.setdefault('new_ids',{})[role] = identity; save(journal,progress,replace=True)
    return identity

def launch_role(role,progress,baseline,values,journal):
    identity = progress['new_ids'][role]; old = old_check(role,baseline,running=False)
    name = 't24-private-'+role
    need(old['Name'] == '/'+name, 'ORIGINAL_ROLE_NAME_REQUIRED_BEFORE_RENAME')
    retained = name+'-retained-'+progress['attempt']
    need(inspect(retained,optional=True) is None, 'RETAINED_OLD_ROLE_NAME_COLLISION')
    progress.setdefault('rename_intent',{})[role] = retained; save(journal,progress,replace=True)
    docker(['rename',live.PRIVATE_IDS[role],retained])
    need(inspect(name,optional=True) is None, 'ROLE_NAME_COLLISION_AFTER_OLD_RENAME')
    docker(['rename',identity,name]); save(journal,progress,replace=True)
    staged_check(identity,role,progress['candidate_image'],progress['attempt'],progress['source_sha'],values,running=False)
    docker(['start',identity]); save(journal,progress,replace=True)

def activate(args):
    receipt = checked_candidate(args)
    state,before,after,baseline = checked_schema_state(args,receipt)
    root = args.candidate.parent/'completed-release'
    need(args.stripe_seed == args.candidate.parent/'stripe-seed-receipt.json', 'EXACT_SEED_RECEIPT_PATH_REQUIRED')
    stripe = fixed_json(args.stripe_seed,args.stripe_seed_sha256)
    no_writers(); values = runtime_guard(baseline)
    current = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    schema_and_business_unchanged(current,after); disabled_data(current)
    checked_seed(stripe,args,state,current)
    progress = {**state,'phase':'PRIVATE_COMPLETED_API_ACTIVATION_PREPARED','schema_state':str(args.schema_state),
        'schema_state_sha256':args.schema_state_sha256,'stripe_seed':str(args.stripe_seed),'stripe_seed_sha256':args.stripe_seed_sha256,
        'new_ids':{},'stage_names':{},'new_private':{},'role_environment_sha256':{},'api_started':False,'worker_started':False,
        'new_stripe_seed_verified':True,'stable_before':stable_records(live.PRIVATE_DB),'seeded_snapshot_sha256':guard.digest(current)}
    journal = root/'activate-progress.json'; save(journal,progress)
    for role in ('api','worker'):
        role_values = role_configuration(transfer.read_protected(transfer.ENV),role)
        profile = root/(role+'-runtime.env')
        progress['role_environment_sha256'][role] = sha(profile_bytes(role_values))
        transfer.write_exclusive(profile,profile_bytes(role_values)); save(journal,progress,replace=True)
        create_role(role,progress,role_values,profile,journal)
    no_writers(); runtime_guard(baseline)
    need(guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS) == current, 'PRIVATE_ROWS_CHANGED_BEFORE_API_START')
    api_values = role_configuration(transfer.read_protected(transfer.ENV),'api')
    launch_role('api',progress,baseline,api_values,journal)
    progress['api_started'] = True; save(journal,progress,replace=True)
    wait_api(progress['new_ids']['api'])
    progress['new_private']['api'] = staged_check(progress['new_ids']['api'],'api',receipt['image_id'],state['attempt'],args.source_sha,api_values,running=True)
    no_writers([progress['new_ids']['api']]); runtime_guard(baseline)
    final = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    need(final == current, 'API_START_CHANGED_PRIVATE_ROWS_OR_CUSTOMER_DATA')
    value = {**progress,'phase':'PRIVATE_COMPLETED_RELEASE_API_READY','private_database':final['private'],
        'business':final['business'],'customer_tables_verified':83,'local_auth_cache_verified':True,
        'api_started':True,'worker_started':False,'services_switched':True,'deployed':False}
    saved = save(root/'api-state.json',value)
    print(json.dumps({'phase':value['phase'],'api_state_sha256':saved,'api_id':progress['new_ids']['api'],
        'worker_started':False,'public_assets_published':False,'deployed':False},sort_keys=True))

def checked_first_sync(current):
    row = seed.connection_state(live.PRIVATE_DB)['row']
    need(row and row.get('status') == 'connected' and row.get('encrypted_credentials') and row.get('last_sync') and
         not row.get('sync_lease_until') and not row.get('error'), 'FIRST_REAL_STRIPE_SYNC_REQUIRED')
    metadata = json.loads(row.get('metadata_json') or '{}'); snap = metadata.get('stripe_snapshot',{})
    need(metadata.get('stripe_account_id') == transfer.ACCOUNT and metadata.get('mode') == 'live' and
         metadata.get('read_only_adapter') is True and metadata.get('payouts_are_income') is False and
         metadata.get('aggregated_totals') is False and metadata.get('coverage') == 'bounded_recent_records' and
         snap.get('account_id') == transfer.ACCOUNT and snap.get('mode') == 'live' and snap.get('id') and snap.get('observed_at'),
         'REAL_STRIPE_SNAPSHOT_IDENTITY_AND_COVERAGE_REQUIRED')
    with sqlite3.connect(live.PRIVATE_DB.as_uri()+'?mode=ro',uri=True,timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute("SELECT status,completed_at FROM private_sync_runs WHERE owner_id='4' AND source_id='stripe' ORDER BY started_at DESC LIMIT 1").fetchall()
    need(len(rows) == 1 and rows[0][0] == 'succeeded' and rows[0][1], 'PERSISTED_FIRST_STRIPE_SYNC_SUCCESS_REQUIRED')
    return {'first_real_stripe_sync_verified':True,'mode':'live','account_id':transfer.ACCOUNT,
        'coverage':'bounded_recent_records','aggregated_totals':False,'payouts_are_income':False,
        'snapshot_sha256':guard.digest(snap)}

def checked_api_state(args,receipt):
    root = args.candidate.parent/'completed-release'
    state = fixed_json(args.api_state,args.api_state_sha256)
    need(args.api_state == root/'api-state.json' and state.get('phase') == 'PRIVATE_COMPLETED_RELEASE_API_READY' and
         state.get('candidate_sha256') == args.candidate_sha256 and state.get('source_sha') == args.source_sha and
         state.get('candidate_image') == receipt['image_id'] and state.get('old_ids') == live.PRIVATE_IDS and
         state.get('api_started') is True and state.get('worker_started') is False and state.get('bank_enabled') is False and
         state.get('ai_enabled') is False and re.fullmatch('[a-f0-9]{32}',state.get('attempt','')),
         'EXACT_ACCEPTED_API_STATE_REQUIRED')
    schema_args = argparse.Namespace(**vars(args),schema_state=Path(state['schema_state']),schema_state_sha256=state['schema_state_sha256'])
    schema_state,before,after,baseline = checked_schema_state(schema_args,receipt)
    need(state['new_ids'].keys() == {'api','worker'} and state['seeded_snapshot_sha256'] and
         fixed_json(Path(state['stripe_seed']),state['stripe_seed_sha256']).get('after_snapshot_sha256') == state['seeded_snapshot_sha256'],
         'API_AND_PERSISTED_SEED_BINDING_REQUIRED')
    return state,after,baseline

def finish(args):
    receipt = checked_candidate(args)
    state,after,baseline = checked_api_state(args,receipt)
    root = args.candidate.parent/'completed-release'
    values = runtime_guard(baseline)
    profiles = {role:role_configuration(transfer.read_protected(transfer.ENV),role) for role in ('api','worker')}
    for role in profiles:
        need(sha(transfer.read_protected(root/(role+'-runtime.env'))) == state['role_environment_sha256'][role] == sha(profile_bytes(profiles[role])),
             'PROTECTED_ROLE_ENVIRONMENT_CHANGED')
    proof = staged_check(state['new_ids']['api'],'api',receipt['image_id'],state['attempt'],args.source_sha,profiles['api'],running=True)
    need(proof == state['new_private']['api'], 'API_CHANGED_SINCE_ACCEPTANCE')
    wait_api(state['new_ids']['api'])
    staged_check(state['new_ids']['worker'],'worker',receipt['image_id'],state['attempt'],args.source_sha,profiles['worker'],running=False)
    no_writers([state['new_ids']['api']])
    current = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    schema_and_business_unchanged(current,after); disabled_data(current)
    preserved(state['stable_before'],stable_records(live.PRIVATE_DB),allow_provider_changes=False)
    sync_proof = checked_first_sync(current)
    progress = {**state,'phase':'PRIVATE_COMPLETED_WORKER_ACTIVATION_PREPARED','first_stripe_sync':sync_proof}
    journal = root/'finish-progress.json'; save(journal,progress)
    launch_role('worker',progress,baseline,profiles['worker'],journal)
    progress['worker_started'] = True; save(journal,progress,replace=True)
    time.sleep(3)
    progress['new_private']['worker'] = staged_check(state['new_ids']['worker'],'worker',receipt['image_id'],state['attempt'],args.source_sha,profiles['worker'],running=True)
    progress['new_private']['api'] = staged_check(state['new_ids']['api'],'api',receipt['image_id'],state['attempt'],args.source_sha,profiles['api'],running=True)
    no_writers(progress['new_ids'].values()); runtime_guard(baseline)
    final = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    schema_and_business_unchanged(final,after); disabled_data(final)
    preserved(state['stable_before'],stable_records(live.PRIVATE_DB))
    checked_first_sync(final)
    value = {**progress,'phase':'PRIVATE_COMPLETED_RELEASE_SERVER_VERIFIED','private_database':final['private'],
        'business':final['business'],'env_sha256':live.ENV_SHA,'crm':baseline['crm'],'business_tables_verified':83,
        'customer_tables_verified':83,'customer_finance_unchanged':True,'bank_enabled':False,'ai_enabled':False,
        'original_runtime_env_unchanged':True,'api_started':True,'worker_started':True,'services_switched':True,
        'deployed':True,'public_assets_published':False,'rollback_stripe_availability':False,
        'rollback_preserves_new_stripe_credentials':True,'databases_restored':False}
    saved = save(root/'switch-state.json',value)
    print(json.dumps({'phase':value['phase'],'switch_state_sha256':saved,'new_ids':value['new_ids'],
        'bank_enabled':False,'ai_enabled':False,'public_assets_published':False,'deployed':True},sort_keys=True))

def rollback_schema_preserved(before,current,receipt,*,allow_private_sync=False):
    checked_business(current,before)
    old,new = before['private'],current['private']
    need(old['identity'] == new['identity'] and guard.BASE_TABLES <= set(new['tables']) <= candidate.TARGET_TABLES,
         'ROLLBACK_DATABASE_IDENTITY_OR_INVENTORY_DRIFT')
    target = receipt['synthetic_schema']['schema_objects']
    need(all(target.get(name) == value for name,value in new['schema_objects'].items()), 'ROLLBACK_UNKNOWN_PRIVATE_DDL')
    # Stripe seed/sync may update only private source data; local notes and
    # stable identities are checked separately if activation was reached.
    need(all(old['tables'][name]['columns_sha256'] == new['tables'][name]['columns_sha256'] for name in guard.BASE_TABLES),
         'ROLLBACK_ORIGINAL_PRIVATE_COLUMNS_CHANGED')
    for name,value in old['schema_objects'].items():
        need(new['schema_objects'].get(name) == value, 'ROLLBACK_ORIGINAL_PRIVATE_DDL_CHANGED')
    if not allow_private_sync:
        need(all(old['tables'][name] == new['tables'][name] for name in guard.BASE_TABLES),
             'ROLLBACK_ORIGINAL_PRIVATE_ROWS_CHANGED_BEFORE_CONNECTORS')

def rollback(args):
    receipt = checked_candidate(args)
    root = args.candidate.parent/'completed-release'
    need(args.state.parent == root and args.state.name in {'schema-progress.json','schema-state.json','activate-progress.json',
         'api-state.json','finish-progress.json','switch-state.json'}, 'EXACT_RELEASE_ROLLBACK_STATE_REQUIRED')
    state = fixed_json(args.state,args.state_sha256)
    need(state.get('source_sha') == args.source_sha and state.get('candidate_sha256') == args.candidate_sha256 and
         state.get('candidate_image') == receipt['image_id'] and state.get('old_ids') == live.PRIVATE_IDS and
         re.fullmatch('[a-f0-9]{32}',state.get('attempt','')), 'ROLLBACK_EXACT_ATTEMPT_REQUIRED')
    if state.get('resume_lineage') is not None:
        import resume_preflight as resumed
        need(state['resume_lineage']==receipt.get('resume_lineage'),'ROLLBACK_EXACT_RESUME_LINEAGE_REQUIRED')
        resumed.checked_lineage(receipt)
        if state.get('phase')=='PRIVATE_COMPLETED_RESUME_VERIFIED_WRITERS_STOPPED':
            bound_args=argparse.Namespace(**vars(args),schema_state=args.state,schema_state_sha256=args.state_sha256)
            state,_,_,_=checked_schema_state(bound_args,receipt)
        elif state.get('schema_state'):
            bound_args=argparse.Namespace(**vars(args),schema_state=Path(state['schema_state']),
                schema_state_sha256=state['schema_state_sha256'])
            accepted,_,_,_=checked_schema_state(bound_args,receipt)
            need(state.get('accepted_schema_state_sha256')==accepted['accepted_schema_state_sha256'],
                 'ROLLBACK_RESUME_SCHEMA_SELF_HASH_BINDING_REQUIRED')
        else:
            need(state.get('phase')=='PRIVATE_RESUME_FREEZE_PREPARED' and not state.get('stripe_seed') and
                 not getattr(args,'stripe_seed',None),'ROLLBACK_RESUME_PROGRESS_CANNOT_CLAIM_SEED')
    baseline = fixed_json(Path(state['baseline']),state['baseline_sha256']); runtime_guard(baseline)
    values = {role:role_configuration(transfer.read_protected(transfer.ENV),role) for role in ('api','worker')}
    # Resolve a command timeout only through this attempt's exact name and labels.
    owned = dict(state.get('new_ids',{}))
    worker_may_have_run = bool(state.get('worker_started'))
    for role,name in state.get('stage_names',{}).items():
        if role not in owned:
            discovered = inspect(name,optional=True)
            if discovered:
                staged_check(discovered['Id'],role,receipt['image_id'],state['attempt'],args.source_sha,values[role],require_stable=False)
                owned[role] = discovered['Id']
    for role in ('worker','api'):
        if role in owned:
            staged_check(owned[role],role,receipt['image_id'],state['attempt'],args.source_sha,values[role],require_stable=False)
            owned_info = inspect(owned[role])
            if role == 'worker' and not owned_info['State'].get('StartedAt','0001-01-01').startswith('0001-'):
                worker_may_have_run = True
            if owned_info['State']['Running']:
                docker(['stop','--time','30',owned[role]],timeout=45)
            info = inspect(owned[role]); staged_check(owned[role],role,receipt['image_id'],state['attempt'],args.source_sha,values[role],running=False,require_stable=False)
            if info['Name'] == '/t24-private-'+role:
                retained = 't24-private-'+role+'-failed-'+state['attempt']
                need(inspect(retained,optional=True) is None, 'ROLLBACK_FAILED_ROLE_NAME_COLLISION')
                docker(['rename',owned[role],retained])
    helper_name = state.get('initializer_name')
    if helper_name:
        helper = inspect(helper_name,optional=True)
        if helper:
            initializer_check(helper,receipt['image_id'],state['attempt'])
            if helper['State']['Running']: docker(['stop','--time','30',helper['Id']],timeout=45)
    # A schema-stage failure may occur after stopping only one old role.
    # Freeze the remaining exact old writer before checking the database.
    for role in ('worker','api'):
        old = old_check(role,baseline)
        if old['State']['Running']:
            docker(['stop','--time','30',live.PRIVATE_IDS[role]],timeout=45)
    no_writers()
    current = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    before_path = root/'schema-before.json'
    seed_path = Path(state['stripe_seed']) if state.get('stripe_seed') else getattr(args,'stripe_seed',None)
    seed_hash = state.get('stripe_seed_sha256') or getattr(args,'stripe_seed_sha256',None)
    need(bool(seed_path) == bool(seed_hash), 'EXPLICIT_ROLLBACK_SEED_FILE_AND_HASH_REQUIRED_TOGETHER')
    approved_seed = None
    if seed_path:
        need(seed_path == args.candidate.parent/'stripe-seed-receipt.json', 'EXACT_ROLLBACK_SEED_RECEIPT_PATH_REQUIRED')
        approved_seed = fixed_json(seed_path,seed_hash)
        seed_state = state
        need(state.get('schema_validation_sha256') and state.get('schema_after_sha256'),
             'ROLLBACK_POST_SEED_ACCEPTED_SCHEMA_STATE_REQUIRED')
        checked_seed_scope(approved_seed,args,seed_state)
        migrated = fixed_json(Path(seed_state.get('schema_after',str(root/'schema-after.json'))),seed_state['schema_after_sha256'])
        need(approved_seed['before_snapshot_sha256'] == guard.digest(migrated), 'ROLLBACK_SEED_ORIGINAL_SNAPSHOT_DRIFT')
        if not state.get('stable_before'):
            checked_seed(approved_seed,args,seed_state,current)
    if state.get('resume_lineage') is not None:
        import resume_preflight as resumed
        original,before,original_after,old_baseline,resume_baseline=resumed.checked_lineage(receipt)
        need(state.get('resume_lineage')==receipt.get('resume_lineage') and resume_baseline==baseline,
             'ROLLBACK_RESUME_LINEAGE_MUST_REMAIN_BOUND')
        rollback_schema_preserved(before,current,receipt,allow_private_sync=True)
        if not approved_seed:
            resumed.checked_frozen_snapshot(baseline,current)
            if state.get('schema_after'):
                need(current==fixed_json(Path(state['schema_after']),state['schema_after_sha256']),
                     'ROLLBACK_RESUME_PRIVATE_ROWS_CHANGED_BEFORE_SEED')
    elif before_path.exists():
        before = fixed_json(before_path,state['schema_before_sha256'])
        rollback_schema_preserved(before,current,receipt,allow_private_sync=bool(approved_seed))
    else:
        need((current['private']['identity']['device'],current['private']['identity']['inode']) == live.PRIVATE_DEVICE_INODE and
             set(current['private']['tables']) == guard.BASE_TABLES and not approved_seed,
             'ROLLBACK_ORIGINAL_INODE_AND_FOUR_TABLES_REQUIRED')
        previous,_ = live.prior_receipts(); business,private = live.database_snapshots(previous)
        need(business == baseline['business'] and private == baseline['private_database'],
             'ROLLBACK_EARLY_BASELINE_DATABASE_DRIFT')
    if state.get('stable_before'):
        need(approved_seed is not None, 'ROLLBACK_POST_ACTIVATION_SEED_PROOF_REQUIRED')
        preserved(state['stable_before'],stable_records(live.PRIVATE_DB),allow_provider_changes=worker_may_have_run)
    for role in ('api','worker'):
        old = old_check(role,baseline,running=False)
        name = 't24-private-'+role
        need(old['Name'] in {'/'+name,'/'+name+'-retained-'+state['attempt']}, 'ROLLBACK_OLD_ROLE_NAME_DRIFT')
        if old['Name'] != '/'+name:
            need(inspect(name,optional=True) is None, 'ROLLBACK_ORIGINAL_NAME_COLLISION')
            docker(['rename',live.PRIVATE_IDS[role],name])
        docker(['start',live.PRIVATE_IDS[role]])
        if role == 'api': wait_api(live.PRIVATE_IDS[role])
    runtime_guard(baseline)
    final = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
    checked_business(final,current)
    need(final['private']['identity'] == current['private']['identity'] and
         final['private']['schema_objects'] == current['private']['schema_objects'], 'ROLLBACK_CHANGED_PRIVATE_FILE_OR_SCHEMA')
    value = {'format_version':1,'phase':'PRIVATE_COMPLETED_RELEASE_ROLLED_BACK_OLD_SERVICES',
        'source_sha':args.source_sha,'attempt':state['attempt'],'old_ids':live.PRIVATE_IDS,
        'bank_enabled':False,'ai_enabled':False,'databases_restored':False,'private_database_replaced':False,
        'new_stripe_credentials_retained':True,'new_stripe_features_available':False,
        'customer_tables_verified':83,'public_assets_published':False,'deployed':False}
    saved = save(root/('rollback-'+uuid4().hex+'.json'),value)
    print(json.dumps({'phase':value['phase'],'rollback_receipt_sha256':saved,'databases_restored':False,
        'new_stripe_features_available':False,'deployed':False},sort_keys=True))

def cli(argv=None):
    parser = SafeParser(description=__doc__)
    sub = parser.add_subparsers(dest='phase',required=True)
    for name in ('schema','resume-schema','activate','finish','rollback'):
        item = sub.add_parser(name)
        item.add_argument('--execute',action='store_true')
        item.add_argument('--source-sha',required=True)
        item.add_argument('--candidate',type=Path,required=True)
        item.add_argument('--candidate-sha256',required=True)
        if name in {'schema','resume-schema'}:
            item.add_argument('--baseline',type=Path,required=True)
            item.add_argument('--baseline-sha256',required=True)
            item.add_argument('--output-dir',type=Path,required=True)
        elif name == 'activate':
            for field in ('schema-state','stripe-seed'):
                item.add_argument('--'+field,type=Path,required=True); item.add_argument('--'+field+'-sha256',required=True)
        elif name == 'finish':
            item.add_argument('--api-state',type=Path,required=True); item.add_argument('--api-state-sha256',required=True)
        else:
            item.add_argument('--state',type=Path,required=True); item.add_argument('--state-sha256',required=True)
            item.add_argument('--stripe-seed',type=Path); item.add_argument('--stripe-seed-sha256')
    try:
        args = parser.parse_args(argv)
        need(args.execute and re.fullmatch('[a-f0-9]{40}',args.source_sha), 'EXPLICIT_EXECUTION_AND_REVIEWED_SOURCE_REQUIRED')
        os.umask(0o077)
        with release_lock():
            {'schema':schema,'resume-schema':resume_schema,'activate':activate,'finish':finish,'rollback':rollback}[args.phase](args)
    except BaseException as error:
        allowed = (SwitchError,seed.SeedError,transfer.TransferError,candidate.PrepareError,live.PreflightError,guard.GuardError)
        code = str(error) if isinstance(error,allowed) and re.fullmatch('[A-Z0-9_]{1,100}',str(error)) else 'PRIVATE_RELEASE_REQUIRES_OPERATOR_REVIEW'
        print(json.dumps({'phase':'PRIVATE_COMPLETED_RELEASE_REJECTED','code':code,
            'automatic_database_restore':False,'automatic_service_rollback':False,
            'production_changes_may_have_occurred':True,'operator_review_required':True,'deployed':False},sort_keys=True))
        return 1
    return 0

if __name__ == '__main__': raise SystemExit(cli())
