#!/usr/bin/env python3
"""Resume only the two existing private containers and the reviewed static switch.

Preserve all original artifacts and private data. Never rebuild, recreate a
container, insert another probe, restore a business database, or run migrations.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4
import urllib.request
import urllib.error

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = '1a4c9523cad250d32a8c1274c2f72c8c6cb6df8b'
RELEASE = Path('/opt/t24-crm/releases/private-workspace-1a4c952-20261011-retry2')
CANDIDATE_SHA = 'be453830af6a53308ecc7dacb006abbc7af23c10d5ca8442f4ba620e17f13bcc'
IMAGE = 'sha256:30978e4d00cf102c188e13e986eb5bd90716e7994c5c6c361f724fded4512c08'
DEPLOY_SHA = 'a4118f3b4134f6e07d98683b44951e14da4006c96dc9bd3186dc062094051336'
PREPARE_SHA = '8de2ecaec7aad3b56fa966a3d3509ebe522c46345f227c79584ebcaabfb73641'
ORIGINAL_CRM_HASH = '2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0'
NAMES = ('t24-private-api', 't24-private-worker')
STATE_SHA = '89c67316b1c9f527613cd2f314abfe265ed55ad9b68bc5c2916b7d2561d1ae24'


def need(value, code):
    if not value:
        raise RuntimeError(code)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_frozen(filename, expected, name):
    path = RELEASE/filename
    need(path.is_file() and not path.is_symlink() and path.resolve() == path and
         path.stat().st_uid == 0 and not path.stat().st_mode & 0o077, 'FROZEN_HELPER_UNTRUSTED')
    need(sha(path) == expected, 'FROZEN_HELPER_DRIFT')
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(url):
    # HTTPMessage.get is case insensitive; preserve it on success and HTTPError.
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def header(headers, name):
    values = [value for key, value in headers.items() if key.casefold() == name.casefold()]
    need(not values or all(value == values[0] for value in values), 'AMBIGUOUS_RESPONSE_HEADER')
    return values[0] if values else ''


def no_store(headers):
    return 'no-store' in {value.strip().casefold() for value in header(headers, 'Cache-Control').split(',')}


def require_private_auth(status, headers):
    need(status == 401 and no_store(headers), 'ACTUAL_PRIVATE_401_OR_NO_STORE_FAILURE')


def canonical_container(info):
    return digest({'Config':info['Config'], 'HostConfig':info['HostConfig'],
                   'Mounts':sorted(info['Mounts'], key=digest)})


def stat_proof(path):
    stat = path.stat()
    return {'device':stat.st_dev, 'inode':stat.st_ino, 'uid':stat.st_uid,
            'mode':stat.st_mode & 0o777, 'nlink':stat.st_nlink}


def original_inventory():
    result = {}
    for path in sorted(RELEASE.rglob('*')):
        relative = path.relative_to(RELEASE)
        if any(part.startswith('resume-attempt-') for part in relative.parts):
            continue
        if relative.as_posix() == 'resume_private_deploy.py':
            continue
        need(not path.is_symlink(), 'ORIGINAL_EVIDENCE_SYMLINK')
        if path.is_file():
            result[relative.as_posix()] = sha(path)
    return result


def runtime_env(deploy, state, crm_info):
    config = deploy.PRIVATE/'config/runtime.env'
    deploy.secure(config)
    need(sha(config) == state['runtime_env_sha256'], 'PRIVATE_RUNTIME_ENV_DRIFT')
    rows = config.read_text().splitlines()
    need(rows and all('=' in row and not row.startswith('#') for row in rows), 'RUNTIME_ENV_FORMAT')
    pairs = [row.split('=', 1) for row in rows]
    need(len({key for key, _ in pairs}) == len(pairs), 'RUNTIME_ENV_DUPLICATE')
    values = dict(pairs)
    expected = {
        'JWT_ALGORITHM':'HS256', 'APP_ENV':'production', 'ENVIRONMENT':'production',
        'DATABASE_URL':'sqlite:///./data/crm_prod.db', 'DATABASE_SCHEMA_MODE':'verify_only',
        'ENFORCE_EMPLOYEE_STATUS':'true', 'ENFORCE_EMPLOYEE_SESSIONS':'true',
        'ENABLE_DEFAULT_EMPLOYEE_ADMIN':'false', 'ENABLE_LEGACY_AUTH':'false',
        'AUTOMATION_SCAN_ENABLED':'false', 'PRIVATE_WORKSPACE_OWNER_IDS':'4',
        'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:////private-data/workspace.db',
        'PRIVATE_WORKSPACE_PUBLIC_URL':'https://t24-crm.com', 'PYTHONDONTWRITEBYTECODE':'1',
        'PYTHONUNBUFFERED':'1', 'DEBUG':'false', 'TZ':'Asia/Shanghai',
    }
    need(set(values) == set(expected)|{'JWT_SECRET_KEY','PRIVATE_WORKSPACE_ENCRYPTION_KEY'} and
         all(values.get(key) == value for key, value in expected.items()), 'PRIVATE_RUNTIME_SETTINGS_DRIFT')
    crm_env = dict(row.split('=', 1) for row in crm_info['Config']['Env'])
    need(values['JWT_SECRET_KEY'] == crm_env.get('JWT_SECRET_KEY') and len(values['JWT_SECRET_KEY']) >= 32 and
         len(values['PRIVATE_WORKSPACE_ENCRYPTION_KEY']) >= 32 and
         not any('\x00' in value or '\r' in value for value in values.values()), 'PRIVATE_RUNTIME_KEY_DRIFT')
    return values


def validate_container(deploy, state, name, values, running):
    proof = state['containers'][name]
    start_path = RELEASE/(name+'-start.log')
    deploy.secure(start_path)
    identity = start_path.read_text().strip()
    need(re.fullmatch(r'[a-f0-9]{64}', identity) is not None and identity == proof['id'], 'ORIGINAL_START_LOG_ID_DRIFT')
    info = deploy.inspect(name)
    need(info['Id'] == identity and info['Name'] == '/'+name and info['Image'] == IMAGE == proof['image_id'] and
         canonical_container(info) == proof['canonical_configuration_sha256'], 'EXISTING_PRIVATE_CONTAINER_DRIFT')
    need(info['State']['Running'] is running and not info['State'].get('Dead', False) and
         not info['State'].get('Restarting', False), 'PRIVATE_RUNNING_STATE_DRIFT')
    if not running:
        need(info['State']['Status'] == 'exited', 'EXISTING_STOPPED_CONTAINER_REQUIRED')
    role = 'api' if name == NAMES[0] else 'worker'
    labels = info['Config'].get('Labels') or {}
    need(labels.get('t24.private.source.sha') == SOURCE and labels.get('t24.private.role') == role and
         labels.get('t24.source.sha') == SOURCE, 'PRIVATE_CONTAINER_LABEL_DRIFT')
    expected_command = ['services.private_workspace_app:app','--host','0.0.0.0','--port','8001','--no-access-log'] if role == 'api' else ['-m','services.private_workspace_worker']
    need(info['Config']['Entrypoint'] == ['uvicorn' if role == 'api' else 'python'] and
         info['Config']['Cmd'] == expected_command, 'PRIVATE_CONTAINER_COMMAND_DRIFT')
    host = info['HostConfig']
    ports = {'8001/tcp':[{'HostIp':'127.0.0.1','HostPort':'8001'}]} if role == 'api' else {}
    need((host.get('PortBindings') or {}) == ports and host['ReadonlyRootfs'] and host['CapDrop'] == ['ALL'] and
         host['RestartPolicy']['Name'] == 'unless-stopped' and not host.get('Privileged') and
         host.get('NetworkMode') in ('bridge','default') and
         host.get('SecurityOpt') in (['no-new-privileges'], ['no-new-privileges:true']), 'PRIVATE_RUNTIME_PROTECTION_DRIFT')
    mounts = {(m['Source'],m['Destination'],m['Type'],m['RW']) for m in info['Mounts']}
    expected = {(str(deploy.BUSINESS.parent),'/app/backend/data','bind',False),
                (str(deploy.PRIVATE/'data'),'/private-data','bind',True)}
    need(mounts in (expected, expected|{('','/tmp','tmpfs',True)}) and
         set(host.get('Tmpfs') or {}) == {'/tmp'} and
         'noexec' in host['Tmpfs']['/tmp'] and 'nosuid' in host['Tmpfs']['/tmp'], 'PRIVATE_RO_MOUNT_OR_TMPFS_DRIFT')
    env = dict(row.split('=', 1) for row in info['Config']['Env'])
    need(all(env.get(key) == value for key, value in values.items()) and
         not any(key.startswith(('STRIPE_','OPENAI_','RINGCENTRAL_','OSS_','PRIVATE_GOOGLE_')) for key in env),
         'PRIVATE_CONTAINER_ENV_DRIFT')
    return identity


def private_metadata(deploy, state):
    path = deploy.PRIVATE/'data/workspace.db'
    deploy.secure(path)
    need(stat_proof(path) == state['private_database_stat'] and path.stat().st_nlink == 1 and
         not os.path.samefile(path, deploy.BUSINESS), 'EXISTING_PRIVATE_DATABASE_IDENTITY_DRIFT')
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'PRIVATE_DATABASE_INTEGRITY_FAILURE')
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY type,name").fetchall()
        tables = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        need(tables == ['private_connections','private_items','private_preferences','private_sync_runs'], 'EXISTING_PRIVATE_SCHEMA_DRIFT')
        probes = db.execute("SELECT id,owner_id,source_id,kind,external_id,title,action_status FROM private_items WHERE external_id LIKE 'release-%'").fetchall()
        need(len(probes) == 1 and probes[0][1:4] == ('4','manual','note') and
             re.fullmatch(r'release-[a-f0-9]{24}', probes[0][4]) is not None and
             probes[0][5:] == ('私人空间上线验证','archived'), 'EXISTING_PERSISTENCE_PROBE_MISSING')
        need(db.execute("SELECT COUNT(*) FROM private_connections WHERE status='connected' OR encrypted_credentials IS NOT NULL").fetchone() == (0,),
             'PLATFORM_CONNECTIONS_UNEXPECTED')
    return {'stat':stat_proof(path), 'schema_sha256':digest(schema), 'existing_probe_sha256':digest(probes),
            'tables':tables, 'read_only':True, 'new_probe_inserted':False}


def main(args):
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'SERVER_IDENTITY_DRIFT')
    need(args.state_proof_sha256 == STATE_SHA, 'FIXED_STATE_PROOF_HASH_REQUIRED')
    os.umask(0o077)
    deploy = load_frozen('deploy_private.py', DEPLOY_SHA, 'frozen_original_private_deploy')
    prep = load_frozen('prepare_private_v3.py', PREPARE_SHA, 'frozen_private_preparer')
    deploy.secure(RELEASE, True)
    candidate_path = RELEASE/'candidate.json'
    deploy.secure(candidate_path)
    need(sha(candidate_path) == CANDIDATE_SHA, 'FROZEN_CANDIDATE_RECEIPT_DRIFT')
    candidate = json.loads(candidate_path.read_text())
    need(candidate['stage'] == 'PRIVATE_WORKSPACE_CANDIDATE_VERIFIED' and candidate['source_sha'] == SOURCE and
         candidate['image_id'] == IMAGE and candidate['candidate_runtime_regression_tests'] == 87 and
         candidate['candidate_runtime_tests_verified'] and candidate['all_baseline_backend_bytes_identical'] and
         candidate['runtime_package_bytes_identical'], 'ACTUAL_VERIFIED_CANDIDATE_REQUIRED')
    state_path = RELEASE/'resume-state.json'
    deploy.secure(state_path)
    need(sha(state_path) == args.state_proof_sha256, 'STOPPED_STATE_PROOF_DRIFT')
    state = json.loads(state_path.read_text())
    need(state['stage'] == 'PRIVATE_STOPPED_RESUME_STATE' and state['candidate_sha256'] == CANDIDATE_SHA and
         set(state['containers']) == set(NAMES), 'STOPPED_STATE_PROOF_SHAPE')
    need(sorted(result['path'] for result in state['isolated_auth_results']) ==
         ['/api/v1/private-workspace','/api/v1/private-workspace/access'], 'ISOLATED_AUTH_PROOF_PATHS')
    for result in state['isolated_auth_results']:
        require_private_auth(result['status'], {'Cache-Control':result['cache_control']})
    before_crm = json.loads((RELEASE/'crm-before-safe.json').read_text())
    need(before_crm == {'container_id':deploy.BASE_CONTAINER,'image_id':deploy.BASE_IMAGE,
                       'started_at':deploy.BASE_STARTED,'configuration_sha256':ORIGINAL_CRM_HASH} and
         deploy.crm_matches_preparation(prep, before_crm), 'ORIGINAL_CRM_CONFIGURATION_DRIFT')
    need(deploy.NGINX.is_file() and not deploy.NGINX.is_symlink() and deploy.NGINX.resolve() == deploy.NGINX and
         sha(deploy.NGINX) == deploy.NGINX_SHA, 'ORIGINAL_NGINX_DRIFT')
    original_nginx = deploy.NGINX.read_bytes()
    deploy.secure(RELEASE/'nginx-original.conf')
    need(sha(RELEASE/'nginx-original.conf') == deploy.NGINX_SHA and
         original_nginx.decode().count(deploy.OLD_BLOCK) == 1, 'ORIGINAL_NGINX_BACKUP_DRIFT')
    need(not (RELEASE/'deployment-receipt.json').exists() and not (RELEASE/'deployment-receipt.json').is_symlink(),
         'EXISTING_SUCCESS_RECEIPT')
    for directory in (deploy.PRIVATE,deploy.PRIVATE/'data',deploy.PRIVATE/'config',deploy.PRIVATE/'logs'):
        deploy.secure(directory, True)
    values = runtime_env(deploy, state, deploy.crm())
    identities = {name:validate_container(deploy,state,name,values,False) for name in NAMES}
    private_before = private_metadata(deploy, state)
    for filename in ('private-persistence-write.log','private-restart.log'):
        deploy.secure(RELEASE/filename)
    need((RELEASE/'private-persistence-write.log').read_text().strip() == 'PRIVATE_PERSISTENCE_PROBE_WRITTEN' and
         (RELEASE/'private-restart.log').read_text().split() == list(NAMES), 'ORIGINAL_PERSISTENCE_EVIDENCE_DRIFT')
    public = Path(candidate['public_directory'])
    need(public == prep.PUBLIC_RELEASES/RELEASE.name and
         sha(RELEASE/'candidate-public-files.json') == candidate['public_manifest_sha256'] and
         sha(RELEASE/'candidate-current-assets.json') == candidate['current_assets_proof_sha256'], 'PUBLIC_PROOF_DRIFT')
    graph = json.loads((RELEASE/'candidate-current-assets.json').read_text())
    need({'/'+name:value for name,value in prep.file_manifest(public).items()} ==
         json.loads((RELEASE/'candidate-public-files.json').read_text()) and
         prep.current_graph(public,candidate['version']) == graph, 'PUBLIC_BYTES_OR_GRAPH_DRIFT')
    finalization_path = Path(candidate['finalization_proof'])
    deploy.secure(finalization_path)
    need(finalization_path.parent.parent == RELEASE and
         sha(finalization_path) == candidate['finalization_proof_sha256'], 'FINALIZATION_PROOF_DRIFT')
    original_evidence = original_inventory()
    logs = RELEASE/('resume-attempt-'+uuid4().hex[:12])
    logs.mkdir(mode=0o700)
    deploy.save(logs/'original-evidence-hashes.json', original_evidence)
    deploy.save(logs/'private-before-safe.json', private_before)

    def run(stage, command, timeout=120):
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        deploy.write(logs/(stage+'.log'), (result.stdout+'\n'+result.stderr).encode())
        need(result.returncode == 0, stage.upper().replace('-','_')+'_FAILED')
        return result.stdout.strip()

    need(run('existing-candidate-image',['docker','image','inspect','-f','{{.Id}}',candidate['image_tag']]) == IMAGE,
         'CANDIDATE_IMAGE_TAG_DRIFT')
    before = deploy.snapshot(deploy.BUSINESS, logs/'business-before.db')
    deploy.save(logs/'business-before-safe.json', before)
    restored = logs/'business-backup-restore-verification.db'
    fd = os.open(restored,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    os.close(fd)
    with sqlite3.connect((logs/'business-before.db').as_uri()+'?mode=ro',uri=True) as source:
        with sqlite3.connect(restored) as target:
            source.backup(target)
    with sqlite3.connect(restored.as_uri()+'?mode=ro',uri=True) as proof:
        need(proof.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SCRATCH_ONLY_BACKUP_RESTORE_FAILED')
    updated = original_nginx.decode().replace(deploy.OLD_BLOCK,deploy.static_block(public)).encode()
    new_nginx_sha = hashlib.sha256(updated).hexdigest()
    started = []
    switched = False
    token = uuid4().hex[:12]
    try:
        for name in NAMES:
            validate_container(deploy,state,name,values,False)
            started.append(name)
            need(run(name+'-existing-start',['docker','start',identities[name]]) == identities[name],
                 'EXISTING_PRIVATE_START_ID_DRIFT')
            if name == NAMES[0]:
                deploy.wait_ready()
        time.sleep(2)
        for name in NAMES:
            validate_container(deploy,state,name,values,True)
        need(private_metadata(deploy,state) == private_before, 'EXISTING_PRIVATE_DATA_OR_PROBE_DRIFT')
        for path in (deploy.PREFIX,deploy.PREFIX+'/access'):
            status,headers,body = request('http://127.0.0.1:8001'+path)
            require_private_auth(status,headers)
        need(deploy.crm_matches_preparation(prep,before_crm) and
             sha(deploy.PRIVATE/'config/runtime.env') == state['runtime_env_sha256'] and
             original_inventory() == original_evidence, 'PRE_SWITCH_ORIGINAL_STATE_DRIFT')
        need(sha(deploy.NGINX) == deploy.NGINX_SHA, 'NGINX_CHANGED_DURING_RESUME')
        deploy.write(logs/'nginx-original.conf',original_nginx)
        deploy.write(logs/'nginx-private.conf',updated)
        deploy.save(logs/'rollback-spec.json',{'nginx_original_sha256':deploy.NGINX_SHA,
                    'private_container_ids':identities,'private_data_retained':True,
                    'business_db_restore_forbidden':True,'original_evidence_retained':True})
        temporary = deploy.NGINX.parent/('.t24-private-resume-'+token)
        need(not temporary.exists() and not temporary.is_symlink(), 'NEW_NGINX_TEMP_REQUIRED')
        deploy.write(temporary,updated)
        temporary.chmod(0o644)
        os.replace(temporary,deploy.NGINX)
        switched = True
        run('nginx-test',['nginx','-t'])
        run('nginx-reload',['systemctl','reload','nginx'])
        status,headers,body = request('https://t24-crm.com/app-version.json')
        need(status == 200 and json.loads(body) == {'version':candidate['version']} and no_store(headers), 'PUBLIC_VERSION_OR_CACHE_DRIFT')
        status,headers,body = request('https://t24-crm.com/private-workspace')
        need(status == 200 and hashlib.sha256(body).hexdigest() == sha(public/'index.html'), 'PUBLIC_FRONTEND_BYTES_DRIFT')
        need(all(header(headers,key) == value for key,value in deploy.SECURITY_HEADERS.items()), 'PUBLIC_SECURITY_HEADERS_DRIFT')
        for asset,asset_sha in graph['assets'].items():
            status,headers,body = request('https://t24-crm.com'+asset)
            need(status == 200 and hashlib.sha256(body).hexdigest() == asset_sha, 'PUBLIC_CURRENT_ASSET_DRIFT')
        for path in (deploy.PREFIX,deploy.PREFIX+'/access'):
            status,headers,body = request('https://t24-crm.com'+path)
            require_private_auth(status,headers)
        need(request('https://t24-crm.com/ready')[0] == 200, 'ORIGINAL_PUBLIC_CRM_NOT_READY')
        for name in NAMES:
            validate_container(deploy,state,name,values,True)
        need(deploy.crm_matches_preparation(prep,before_crm) and sha(deploy.NGINX) == new_nginx_sha and
             sha(deploy.PRIVATE/'config/runtime.env') == state['runtime_env_sha256'] and
             original_inventory() == original_evidence and private_metadata(deploy,state) == private_before,
             'FINAL_ORIGINAL_STATE_OR_PRIVATE_METADATA_DRIFT')
        after = deploy.snapshot(deploy.BUSINESS,logs/'business-after.db')
        deploy.save(logs/'business-after-safe.json',after)
        changed = sorted(name for name in before if before[name] != after[name])
        receipt = {
            'stage':'PRIVATE_WORKSPACE_DEPLOYED_SERVER_VERIFIED','source_sha':SOURCE,'private_image_id':IMAGE,
            'version':candidate['version'],'private_owner_ids':[4],
            'private_api_container_id':identities[NAMES[0]],'private_worker_container_id':identities[NAMES[1]],
            'private_database':str(deploy.PRIVATE/'data/workspace.db'),'private_database_independent':True,
            'private_persistence_after_restart':True,'existing_persistence_probe_reverified':True,'new_probe_inserted':False,
            'crm_identity_unchanged':True,'crm_container_id':deploy.BASE_CONTAINER,'crm_image_id':deploy.BASE_IMAGE,
            'crm_started_at':deploy.BASE_STARTED,'crm_mount_read_only_in_private_services':True,
            'business_table_count':83,'business_schema_unchanged':True,'business_tables_changed_during_live_window':changed,
            'all_business_table_fingerprints_equal':not changed,'business_backup_restore_verified_in_scratch_only':True,
            'business_database_writes_performed_by_deployer':False,'nginx_new_sha256':new_nginx_sha,
            'public_current_assets_verified':len(graph['assets']),'public_version_verified':True,
            'public_unauthenticated_access_rejected':True,'candidate_runtime_tests':87,'candidate_tests_rerun':False,
            'containers_recreated':False,'candidate_rebuilt':False,'original_evidence_preserved':True,
            'runtime_env_sha256':state['runtime_env_sha256'],'stopped_state_proof_sha256':args.state_proof_sha256,
            'resume_log_directory':str(logs),'private_metadata_sha256':digest(private_before),
            'real_platform_accounts_connected':False,'browser_owner_acceptance_pending':True,
        }
        deploy.save(logs/'deployment-receipt.json',receipt)
        print(json.dumps(receipt,sort_keys=True),flush=True)
    except BaseException:
        if switched:
            need(sha(deploy.NGINX) in (new_nginx_sha,deploy.NGINX_SHA), 'ROLLBACK_NGINX_UNEXPECTED_DRIFT')
            if sha(deploy.NGINX) != deploy.NGINX_SHA:
                temporary = deploy.NGINX.parent/('.t24-private-resume-rollback-'+token)
                need(not temporary.exists() and not temporary.is_symlink(), 'NEW_ROLLBACK_TEMP_REQUIRED')
                deploy.write(temporary,original_nginx)
                temporary.chmod(0o644)
                os.replace(temporary,deploy.NGINX)
                run('rollback-nginx-test',['nginx','-t'])
                run('rollback-nginx-reload',['systemctl','reload','nginx'])
        for name in reversed(started):
            info = deploy.inspect(name)
            need(info['Id'] == identities[name] and info['Image'] == IMAGE and
                 canonical_container(info) == state['containers'][name]['canonical_configuration_sha256'],
                 'ROLLBACK_EXISTING_CONTAINER_DRIFT')
            if info['State']['Running']:
                run(name+'-resume-stop',['docker','stop',identities[name]])
        need(deploy.crm_matches_preparation(prep,before_crm) and sha(deploy.NGINX) == deploy.NGINX_SHA and
             original_inventory() == original_evidence, 'SAFE_RESUME_ROLLBACK_VERIFICATION_FAILED')
        deploy.save(logs/'failed-safe-receipt.json',{'stage':'RESUME_FAILED_SAFE_ROLLBACK','crm_unchanged':True,
            'nginx_original_restored':True,'private_data_retained':True,'business_database_writes_performed':False,
            'original_evidence_preserved':True})
        print('PRIVATE_RESUME_FAILED_SAFE_ROLLBACK; original evidence and private data retained',flush=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--state-proof-sha256')
    args = parser.parse_args()
    if args.execute:
        main(args)
    else:
        print('PLAN_ONLY; NO_PRODUCTION_ACTIONS')
