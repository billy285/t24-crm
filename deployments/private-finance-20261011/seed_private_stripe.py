#!/usr/bin/env python3
"""Explicit root-only Stripe seed, after actual candidate/schema acceptance.

No service switch, worker, application lifespan, payments, sync or AI is run.
An existing sealed private bootstrap is opened in memory. Its key and selected
private configuration go only to a labelled candidate helper's stdin, never
Docker Config/argv, plaintext files, release output or Docker logs. The normal
GET-only connection adapter verifies all six resources and encrypts the key in
the independent private DB. CRM identity is physically readonly.
"""
import argparse
import fcntl
import hashlib
import inspect as source_inspect
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess
from uuid import uuid4

import candidate_prepare as candidate
import credential_transfer as transfer
import live_preflight as live
import private_schema_guard as guard

TARGET_TABLES = candidate.TARGET_TABLES
MINIMUM_TESTS = 738
PRIVATE_ROOT = live.PRIVATE_DB.parent
BUSINESS_ROOT = live.BUSINESS.parent
CONFIG_FIELDS = frozenset({'DATABASE_URL', 'DATABASE_SCHEMA_MODE', 'PRIVATE_WORKSPACE_DATABASE_URL',
    'PRIVATE_WORKSPACE_OWNER_IDS', 'PRIVATE_WORKSPACE_ENCRYPTION_KEY', 'JWT_SECRET_KEY',
    'ENFORCE_EMPLOYEE_STATUS', 'ENFORCE_EMPLOYEE_SESSIONS'})
HELPER_LABEL = 't24.private_finance.stripe_seed'


class SeedError(RuntimeError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise SeedError('ARGUMENTS_REJECTED')


def need(condition, code):
    if not condition:
        raise SeedError(code)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def fixed_json(path, expected, maximum=4 * 1024**2):
    need(re.fullmatch('[a-f0-9]{64}', expected or ''), 'INDEPENDENT_REVIEWED_HASH_REQUIRED')
    blob = transfer.read_protected(path, maximum)
    need(sha(blob) == expected, 'REVIEWED_EVIDENCE_HASH_DRIFT')
    value = json.loads(blob)
    need(isinstance(value, dict), 'OBJECT_RECEIPT_REQUIRED')
    return value


def checked_candidate(receipt, *, source_sha, release):
    need(re.fullmatch('[a-f0-9]{40}', source_sha or '') and
         receipt.get('format_version') == 1 and receipt.get('stage') == 'PRIVATE_FINANCE_CANDIDATE_VERIFIED' and
         receipt.get('source_sha') == source_sha and receipt.get('base_image_id') == live.PRIVATE_IMAGE and
         re.fullmatch('sha256:[a-f0-9]{64}', receipt.get('image_id', '')) and
         receipt['image_id'] != live.PRIVATE_IMAGE, 'ACTUAL_REVIEWED_CANDIDATE_REQUIRED')
    need(all(receipt.get(name) is True for name in ('base_pin_verified_before_and_after_build', 'base_layers_verified',
         'all_other_backend_bytes_identical', 'all_package_bytes_identical', 'complete_frontend_dist_bytes_verified',
         'existing_hashed_static_assets_preserved')) and all(receipt.get(name) is False for name in
         ('production_services_modified', 'public_assets_published', 'production_databases_modified', 'deployed')),
         'COMPLETE_ISOLATED_CANDIDATE_PROOF_REQUIRED')
    regressions = receipt.get('candidate_regressions', {})
    need(type(regressions.get('tests')) is int and type(regressions.get('minimum')) is int and
         regressions['minimum'] >= MINIMUM_TESTS and regressions['tests'] >= regressions['minimum'] and
         regressions.get('network') == 'none' and regressions.get('production_environment_loaded') is False and
         regressions.get('production_database_access') is False, 'ACTUAL_COMPLETE_REGRESSIONS_REQUIRED')
    xml = transfer.read_protected(release / 'test-results' / 'regressions.xml', 8 * 1024**2)
    need(sha(xml) == regressions.get('xml_sha256') and
         candidate.test_report(xml, regressions['minimum']) == regressions['tests'], 'REGRESSION_XML_PROOF_DRIFT')
    tools = fixed_json(release / 'candidate-test-tools.json', regressions.get('test_tools_proof_sha256'))
    need(tools.get('base_image_id') == live.PRIVATE_IMAGE and tools.get('python') == candidate.BASE_PYTHON_VERSION and
         tools.get('base_package_versions') == candidate.BASE_PACKAGE_VERSIONS and
         tools.get('retained_wheel_versions') == candidate.WHEEL_VERSIONS and
         tools.get('retained_wheel_manifest_sha256') == candidate.BASE_WHEEL_MANIFEST_SHA and
         tools.get('runtime_packages_modified') is False and tools.get('network') == 'none',
         'ACTUAL_RETAINED_RUNTIME_PROOF_REQUIRED')
    synthetic = receipt.get('synthetic_schema', {})
    need(synthetic.get('stage') == 'SYNTHETIC_SCHEMA_AND_OLD_IMAGE_COMPATIBILITY_VERIFIED' and
         set(synthetic.get('tables', [])) == TARGET_TABLES and
         synthetic.get('base_image_id') == live.PRIVATE_IMAGE and synthetic.get('candidate_image_id') == receipt['image_id'] and
         all(synthetic.get(name) is True for name in ('old_image_reads_upgraded_schema', 'original_rows_columns_indexes_preserved',
         'new_tables_empty', 'business_unchanged')) and synthetic.get('production_database_access') is False,
         'ACTUAL_OLD_IMAGE_ROLLBACK_REHEARSAL_REQUIRED')
    return receipt


def checked_schema(before, after, manifest, validation, receipt):
    need(set(manifest.get('target_tables', [])) == TARGET_TABLES and manifest.get('business_table_count') == 83 and
         manifest.get('target_schema_objects') == receipt['synthetic_schema']['schema_objects'],
         'EXACT_PRODUCTION_TEN_TABLE_MANIFEST_REQUIRED')
    proof = guard.compare_snapshots(before, after, manifest, source_sha=receipt['source_sha'], mode='in_place')
    need(validation == proof, 'ACTUAL_IN_PLACE_SCHEMA_ACCEPTANCE_REQUIRED')
    need(after['private']['identity']['path_sha256'] == guard.digest(str(live.PRIVATE_DB)) and
         after['business']['identity']['path_sha256'] == guard.digest(str(live.BUSINESS)),
         'LIVE_PRIVATE_AND_BUSINESS_PATH_REQUIRED')
    current = guard.release_snapshot(live.PRIVATE_DB, live.BUSINESS)
    need(current == after, 'MIGRATED_PRIVATE_OR_BUSINESS_SNAPSHOT_DRIFT')
    return current


def checked_backup(path, expected_hash, before):
    blob = transfer.read_protected(path, 512 * 1024**2)
    need(re.fullmatch('[a-f0-9]{64}', expected_hash or '') and sha(blob) == expected_hash,
         'REVIEWED_ORIGINAL_BACKUP_HASH_REQUIRED')
    need(not os.path.samefile(path, live.PRIVATE_DB) and not os.path.samefile(path, live.BUSINESS), 'BACKUP_CANNOT_ALIAS_LIVE_DB')
    saved = guard.database_snapshot(path, private=True)
    need(set(saved['tables']) == guard.BASE_TABLES and all(saved.get(name) == before['private'].get(name)
         for name in ('tables', 'schema_objects', 'schema_sha256', 'data_sha256')), 'ORIGINAL_PRIVATE_BACKUP_PROOF_DRIFT')


def connection_state(private_path):
    """Only hashes and setup state leave the in-memory readonly query."""
    with sqlite3.connect(Path(private_path).as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        columns = [row[1] for row in db.execute('PRAGMA table_info(private_connections)')]
        rows = db.execute("SELECT * FROM private_connections WHERE owner_id='4' AND source_id='stripe'").fetchall()
        need(len(rows) <= 1 and columns, 'STRIPE_CONNECTION_SCOPE_REJECTED')
        other = db.execute("SELECT * FROM private_connections WHERE NOT(owner_id='4' AND source_id='stripe') ORDER BY id").fetchall()
    value = dict(zip(columns, rows[0])) if rows else None
    return {'row': value, 'stripe_sha256': guard.digest(rows), 'other_connections_sha256': guard.digest(other)}


def seedable(state):
    row = state['row']
    if row is None:
        return 0
    need(row.get('owner_id') == '4' and row.get('source_id') == 'stripe' and
         row.get('status') in {'disconnected', 'not_connected', 'error'} and not row.get('encrypted_credentials') and
         not row.get('oauth_state_hash') and not row.get('oauth_expires_at') and not row.get('sync_lease_until') and
         type(row.get('generation')) is int and row['generation'] >= 0, 'EXISTING_STRIPE_CONNECTION_PRESERVED')
    return row['generation']


def checked_configuration(blob):
    parsed = live.parse_env(blob)
    need(not any(name.startswith(('STRIPE_', 'OPENAI_', 'RINGCENTRAL_', 'OSS_')) for name in parsed) and
         not parsed.get('PRIVATE_WORKSPACE_STRIPE_KEY'), 'NO_CUSTOMER_OR_PERSISTED_STRIPE_KEY_ALLOWED')
    selected = {name: parsed[name] for name in CONFIG_FIELDS if name in parsed}
    need(selected.get('PRIVATE_WORKSPACE_OWNER_IDS') == '4' and
         selected.get('PRIVATE_WORKSPACE_ENCRYPTION_KEY') and selected.get('JWT_SECRET_KEY'), 'PRIVATE_ENCRYPTION_IDENTITY_REQUIRED')
    selected.update(PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID=transfer.ACCOUNT, PRIVATE_WORKSPACE_STRIPE_MODE=transfer.MODE,
        PRIVATE_WORKSPACE_PLAID_ENABLED='false', PRIVATE_MAIL_BRIEF_ENABLED='false', PRIVATE_MAIL_TRANSLATION_ENABLED='false',
        PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT='false', PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED='false',
        PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT='false', PYTHONDONTWRITEBYTECODE='1')
    return selected


def docker(argv, *, input=None, timeout=30):
    try:
        result = subprocess.run(['docker', *argv], input=input, capture_output=True, check=False, timeout=timeout)
    except Exception:
        raise SeedError('DOCKER_OPERATION_FAILED') from None
    need(result.returncode == 0, 'DOCKER_OPERATION_FAILED')
    return result.stdout


def inspect_container(identity):
    values = json.loads(docker(['inspect', identity]))
    need(isinstance(values, list) and len(values) == 1, 'SINGLE_CONTAINER_REQUIRED')
    return values[0]


def no_private_writers(*, allowed_id=None):
    ids = docker(['ps', '--quiet', '--no-trunc']).decode().splitlines()
    need(all(re.fullmatch('[a-f0-9]{64}', identity) for identity in ids), 'RUNNING_CONTAINER_INVENTORY_REJECTED')
    for identity in ids:
        info = inspect_container(identity)
        for mount in info.get('Mounts', []):
            if mount.get('Type') == 'bind' and mount.get('RW') and mount.get('Source'):
                source = Path(mount['Source']).resolve()
                if source == PRIVATE_ROOT or source in PRIVATE_ROOT.parents or PRIVATE_ROOT in source.parents:
                    need(identity == allowed_id, 'ALL_PRIVATE_WRITERS_MUST_BE_STOPPED')
    for identity in live.PRIVATE_IDS.values():
        need(not inspect_container(identity)['State']['Running'], 'OLD_PRIVATE_SERVICE_MUST_BE_STOPPED')


def helper_code():
    # This fixed code contains names/protocol only. Credentials are stdin values.
    return ("import asyncio,hashlib,io,json,os,sqlite3,sys\n"
            "from contextlib import redirect_stdout,redirect_stderr\nfrom pathlib import Path\n"
            "class SeedError(RuntimeError):pass\n"
            "def need(ok,code):\n if not ok:raise SeedError(code)\n"
            "class G:\n @staticmethod\n def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()\n"
            "guard=G()\n" + source_inspect.getsource(connection_state) + "\n" + source_inspect.getsource(seedable) + "\n" +
            """packet=json.load(sys.stdin)
report=None
async def operation():
 from sqlalchemy.ext.asyncio import async_sessionmaker
 from dependencies.private_workspace import valid_private_owner
 from services.private_workspace_worker import create_business_reader
 from services import private_workspace as core
 assert os.environ.get('PRIVATE_WORKSPACE_OWNER_IDS')=='4'
 assert os.environ.get('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID')==packet['credentials']['stripe_account_id']
 assert os.environ.get('PRIVATE_WORKSPACE_STRIPE_MODE')==packet['credentials']['mode']=='live'
 assert os.environ.get('PRIVATE_WORKSPACE_DATABASE_URL')=='sqlite+aiosqlite:////private-data/workspace.db'
 assert not os.environ.get('PRIVATE_WORKSPACE_STRIPE_KEY')
 engine=create_business_reader();business_sessions=async_sessionmaker(engine,expire_on_commit=False)
 async def validator():
  async with business_sessions() as identity_db:
   allowed=await valid_private_owner('4',identity_db)
  current=connection_state('/private-data/workspace.db')
  return allowed and current['stripe_sha256']==packet['stripe_before_sha256'] and current['other_connections_sha256']==packet['other_before_sha256']
 try:
  need(await validator(),'OWNER_OR_CONNECTION_CHANGED')
  sessions=await core.private_session_factory()
  async with sessions() as private_db:
   # Validate all existing connected credentials before touching Stripe.
   from sqlalchemy import select
   from models.private_workspace import PrivateConnection
   rows=(await private_db.execute(select(PrivateConnection))).scalars().all()
   for row in rows:
    if row.status=='connected':need(bool(core.decrypt_credentials(row.encrypted_credentials)),'EXISTING_CREDENTIAL_UNREADABLE')
   need(seedable(connection_state('/private-data/workspace.db'))==packet['generation_before'],'CONNECTION_GENERATION_CHANGED')
   os.environ['PRIVATE_WORKSPACE_STRIPE_KEY']=packet['credentials']['api_key']
   try:
    result=await core.connect_source(private_db,'4','stripe',owner_validator=validator)
   finally:
    os.environ.pop('PRIVATE_WORKSPACE_STRIPE_KEY',None)
   need(result.get('requires_redirect') is False,'STRIPE_CONNECT_NOT_COMPLETED')
   saved=await core.connection_for(private_db,'4','stripe')
   metadata=saved.metadata_json or {}
   need(saved.status=='connected' and saved.generation==packet['generation_before']+1,'STRIPE_FINAL_STATE_REJECTED')
   need(metadata.get('stripe_account_id')==packet['credentials']['stripe_account_id'] and metadata.get('mode')=='live' and metadata.get('read_only_adapter') is True,'STRIPE_FINAL_IDENTITY_REJECTED')
   need(core.decrypt_credentials(saved.encrypted_credentials)==packet['credentials'],'STRIPE_FINAL_CREDENTIAL_REJECTED')
   return {'stage':'PRIVATE_STRIPE_SEED_CONNECTED','owner_id':'4','mode':'live','six_get_probes_verified':True,'encrypted_db_credential_verified':True,'generation':saved.generation,'key_removed_from_process_environment':True}
 finally:
  os.environ.pop('PRIVATE_WORKSPACE_STRIPE_KEY',None)
  await core.close_private_workspace_storage();await engine.dispose()
try:
 with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
  os.environ.update(packet['configuration'])
  report=asyncio.run(asyncio.wait_for(operation(),timeout=60))
except BaseException:
 report={'stage':'PRIVATE_STRIPE_SEED_HELPER_REJECTED','error':'OWNER_CONNECTION_OR_PROVIDER_VALIDATION_FAILED'}
print(json.dumps(report,sort_keys=True))
raise SystemExit(0 if report['stage']=='PRIVATE_STRIPE_SEED_CONNECTED' else 1)
""")


def create_command(name, attempt, image):
    return ['create', '--interactive', '--name', name, '--label', HELPER_LABEL + '=' + attempt,
        '--restart', 'no', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--network', 'bridge', '--no-healthcheck', '--log-driver', 'none', '--pids-limit', '64',
        '--memory', '256m', '--cpus', '1', '--tmpfs', '/tmp:rw,nosuid,noexec,size=64m',
        '--env', 'PYTHONDONTWRITEBYTECODE=1', '--workdir', '/app/backend',
        '--mount', 'type=bind,src=' + str(BUSINESS_ROOT) + ',dst=/app/backend/data,readonly',
        '--mount', 'type=bind,src=' + str(PRIVATE_ROOT) + ',dst=/private-data',
        '--entrypoint', 'python', image, '-c', helper_code()]


def checked_helper(info, identity, attempt, image):
    need(info.get('Id') == identity and info.get('Image') == image and identity not in {*live.PRIVATE_IDS.values(), live.CRM_ID} and
         info.get('Config', {}).get('Labels', {}).get(HELPER_LABEL) == attempt, 'OWNED_HELPER_IDENTITY_REQUIRED')
    host, config = info['HostConfig'], info['Config']
    need(host.get('ReadonlyRootfs') is True and host.get('CapDrop') == ['ALL'] and
         host.get('SecurityOpt') in (['no-new-privileges'], ['no-new-privileges:true']) and
         host.get('NetworkMode') == 'bridge' and host.get('RestartPolicy', {}).get('Name') == 'no' and
         host.get('LogConfig', {}).get('Type') == 'none' and not host.get('PortBindings') and
         not host.get('Privileged') and not host.get('CapAdd') and not host.get('Devices') and
         not host.get('DeviceRequests') and not host.get('Binds') and host.get('PidMode', '') == '' and
         host.get('IpcMode') == 'private' and host.get('UTSMode', '') == '' and
         host.get('PidsLimit') == 64 and host.get('Memory') == 256 * 1024**2 and host.get('NanoCpus') == 10**9 and
         host.get('Tmpfs') == {'/tmp': 'rw,nosuid,noexec,size=64m'}, 'HELPER_ISOLATION_REQUIRED')
    binds = [mount for mount in info.get('Mounts', []) if mount.get('Type') == 'bind']
    need(len(binds) == 2 and {(mount['Source'], mount['Destination'], mount['RW']) for mount in binds} ==
         {(str(BUSINESS_ROOT), '/app/backend/data', False), (str(PRIVATE_ROOT), '/private-data', True)} and
         all(mount.get('Type') == 'bind' or (mount.get('Type') == 'tmpfs' and mount.get('Destination') == '/tmp')
             for mount in info['Mounts']), 'ONLY_PRIVATE_DB_WRITABLE_BIND_REQUIRED')
    need(config.get('Entrypoint') == ['python'] and config.get('Cmd') == ['-c', helper_code()] and
         config.get('WorkingDir') == '/app/backend' and config.get('OpenStdin') is True, 'FIXED_HELPER_PROGRAM_REQUIRED')
    for row in config.get('Env', []):
        need(isinstance(row, str) and '=' in row, 'HELPER_ENV_REJECTED')
        name, value = row.split('=', 1)
        need(name in transfer.SAFE_IMAGE_ENV_NAMES and not re.search(r'rk_(?:live|test)_|sk_(?:live|test)_|Bearer ', value),
             'NO_CREDENTIAL_IN_DOCKER_CONFIG_ALLOWED')
    return info


def checked_report(raw, expected_generation):
    need(len(raw) <= 2048, 'HELPER_OUTPUT_REJECTED')
    value = json.loads(raw)
    need(set(value) == {'stage','owner_id','mode','six_get_probes_verified','encrypted_db_credential_verified',
         'generation','key_removed_from_process_environment'} and value['stage'] == 'PRIVATE_STRIPE_SEED_CONNECTED' and
         value['owner_id'] == '4' and value['mode'] == 'live' and type(value['generation']) is int and
         value['generation'] == expected_generation + 1 and all(value[name] is True for name in
         ('six_get_probes_verified','encrypted_db_credential_verified','key_removed_from_process_environment')),
         'SAFE_COMPLETE_HELPER_SUCCESS_REQUIRED')
    return value


def claim_bootstrap(bootstrap_sha256, candidate_sha256, source_sha, attempt):
    need(all(re.fullmatch('[a-f0-9]{64}', value or '') for value in (bootstrap_sha256, candidate_sha256)) and
         re.fullmatch('[a-f0-9]{40}', source_sha or '') and re.fullmatch('[a-f0-9]{32}', attempt or ''),
         'EXACT_ONE_USE_CLAIM_BINDING_REQUIRED')
    claims = transfer.CONFIG / 'stripe-seed-claims'
    if not claims.exists():
        try:
            claims.mkdir(mode=0o700); transfer.fsync_directory(transfer.CONFIG)
        except FileExistsError:
            pass
    transfer.protected_directory(claims)
    path = claims / (bootstrap_sha256 + '.json')
    try:
        transfer.write_exclusive(path, transfer.encoded({'stage':'STRIPE_SEED_ONE_USE_CLAIMED','attempt':attempt,
            'candidate_sha256':candidate_sha256,'bootstrap_sha256':bootstrap_sha256,'source_sha':source_sha}))
    except FileExistsError:
        raise SeedError('SEALED_BOOTSTRAP_ALREADY_CLAIMED_REVIEW_REQUIRED') from None
    return path


def checked_after(before, after, before_connections, after_connections):
    need(before['business'] == after['business'], 'BUSINESS_DATA_DRIFT_REQUIRES_REVIEW')
    need(before['private']['identity'] == after['private']['identity'] and
         before['private']['schema_objects'] == after['private']['schema_objects'], 'PRIVATE_FILE_OR_SCHEMA_CHANGED')
    for name in TARGET_TABLES - {'private_connections'}:
        need(before['private']['tables'][name] == after['private']['tables'][name], 'UNRELATED_PRIVATE_ROWS_CHANGED')
    need(before_connections['other_connections_sha256'] == after_connections['other_connections_sha256'], 'OTHER_PRIVATE_CONNECTION_CHANGED')
    row = after_connections['row']
    need(row and row.get('status') == 'connected' and row.get('encrypted_credentials') and
         row.get('generation') == seedable(before_connections) + 1, 'STRIPE_CONNECTION_NOT_PERSISTED')
    metadata = json.loads(row.get('metadata_json') or '{}')
    need(metadata.get('stripe_account_id') == transfer.ACCOUNT and metadata.get('mode') == transfer.MODE and
         metadata.get('read_only_adapter') is True, 'STRIPE_PERSISTED_IDENTITY_REJECTED')


def main(args):
    need(args.execute and os.geteuid() == 0 and socket.gethostname() == live.HOST, 'EXPLICIT_VERIFIED_ROOT_SERVER_REQUIRED')
    os.umask(0o077)
    transfer.environment_guard()
    need(args.runtime_env_sha256 == transfer.ENV_SHA, 'ORIGINAL_RUNTIME_ENV_PIN_REQUIRED')
    release = args.candidate.parent
    transfer.protected_directory(release)
    need(release.parent == Path('/opt/t24-crm/releases') and re.fullmatch(
         'private-finance-' + args.source_sha[:12] + '-20261011-candidate(?:-[a-z0-9]{1,16})?', release.name) and
         args.candidate.name == 'candidate.json' and args.output == release / 'stripe-seed-receipt.json' and
         not args.output.exists() and not args.output.is_symlink(), 'EXCLUSIVE_REVIEWED_RELEASE_OUTPUT_REQUIRED')
    lock_path = transfer.CONFIG / 'private-finance-release.lock'
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    identity = None; attempt = uuid4().hex; claimed = False; helper_completed = False
    try:
        opened = os.fstat(descriptor); saved = lock_path.lstat()
        need(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_uid == 0 and
             stat.S_IMODE(opened.st_mode) == 0o600 and (opened.st_dev,opened.st_ino) == (saved.st_dev,saved.st_ino),
             'RELEASE_LOCK_PROTECTION_REQUIRED')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = checked_candidate(fixed_json(args.candidate, args.candidate_sha256), source_sha=args.source_sha, release=release)
        image = receipt['image_id']; image_info = json.loads(docker(['image','inspect',image]))
        need(len(image_info) == 1 and image_info[0].get('Id') == image and
             image_info[0].get('Config', {}).get('Labels', {}).get('t24.private.source.sha') == args.source_sha,
             'ACTUAL_CANDIDATE_IMAGE_ID_OR_SOURCE_DRIFT')
        base_info = json.loads(docker(['image','inspect',live.PRIVATE_IMAGE]))
        candidate.verify_candidate_base(base_info[0], image_info[0])
        before = fixed_json(args.schema_before, args.schema_before_sha256)
        after = fixed_json(args.schema_after, args.schema_after_sha256)
        manifest = fixed_json(args.schema_manifest, args.schema_manifest_sha256)
        validation = fixed_json(args.schema_validation, args.schema_validation_sha256)
        current = checked_schema(before, after, manifest, validation, receipt)
        checked_backup(args.backup, args.backup_sha256, before)
        live.crm_snapshot(); no_private_writers()
        environment = transfer.read_protected(transfer.ENV)
        need(sha(environment) == args.runtime_env_sha256, 'RUNTIME_ENV_HASH_DRIFT')
        configuration = checked_configuration(environment)
        bootstrap_blob = transfer.read_protected(transfer.BOOTSTRAP, 32768)
        need(re.fullmatch('[a-f0-9]{64}', args.bootstrap_sha256 or '') and sha(bootstrap_blob) == args.bootstrap_sha256,
             'EXISTING_SEALED_BOOTSTRAP_PIN_REQUIRED')
        payload = transfer.get_bootstrap(sealed_crypto='docker')
        connection_before = connection_state(live.PRIVATE_DB); generation = seedable(connection_before)
        claim_bootstrap(args.bootstrap_sha256,args.candidate_sha256,args.source_sha,attempt)
        claimed = True
        name = 't24-private-stripe-seed-' + attempt
        exists = subprocess.run(['docker','inspect',name], capture_output=True, timeout=15, check=False)
        need(exists.returncode != 0, 'EXCLUSIVE_HELPER_NAME_REQUIRED')
        created = docker(create_command(name, attempt, image)).decode().strip()
        need(re.fullmatch('[a-f0-9]{64}',created), 'HELPER_ID_REQUIRED'); identity = created
        checked_helper(inspect_container(identity),identity,attempt,image)
        no_private_writers(); live.crm_snapshot()
        need(guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS) == current and
             sha(transfer.read_protected(transfer.ENV)) == args.runtime_env_sha256 and
             sha(transfer.read_protected(transfer.BOOTSTRAP,32768)) == args.bootstrap_sha256, 'FINAL_SEED_PREFLIGHT_DRIFT')
        packet = transfer.encoded({'configuration':configuration,'credentials':payload['credentials'],
            'stripe_before_sha256':connection_before['stripe_sha256'], 'other_before_sha256':connection_before['other_connections_sha256'],
            'generation_before':generation})
        raw = docker(['start','--attach','--interactive',identity], input=packet, timeout=75)
        result = checked_report(raw,generation); helper_completed = True
        checked_helper(inspect_container(identity),identity,attempt,image)
        need(not inspect_container(identity)['State']['Running'], 'HELPER_MUST_HAVE_EXITED')
        no_private_writers(); live.crm_snapshot()
        final = guard.release_snapshot(live.PRIVATE_DB,live.BUSINESS)
        connection_after = connection_state(live.PRIVATE_DB)
        checked_after(current,final,connection_before,connection_after)
        need(sha(transfer.read_protected(transfer.ENV)) == args.runtime_env_sha256 and
             sha(transfer.read_protected(transfer.BOOTSTRAP,32768)) == args.bootstrap_sha256, 'PRIVATE_CONFIG_OR_BOOTSTRAP_CHANGED')
        value = {**result,'format_version':1,'stage':'PRIVATE_STRIPE_SEED_VERIFIED_NOT_DEPLOYED','source_sha':args.source_sha,
            'candidate_sha256':args.candidate_sha256,'image_id':image,'bootstrap_sha256':args.bootstrap_sha256,
            'schema_acceptance_sha256':args.schema_validation_sha256,'backup_sha256':args.backup_sha256,
            'runtime_env_changed':False,'customer_data_changed':False,'other_private_connections_changed':False,
            'private_rows_changed_only_stripe_connection':True,'worker_started':False,'services_switched':False,
            'public_assets_published':False,'deployed':False,'before_snapshot_sha256':guard.digest(current),'after_snapshot_sha256':guard.digest(final)}
        transfer.write_exclusive(args.output,transfer.encoded(value))
        print(json.dumps({'stage':value['stage'],'receipt_sha256':sha(transfer.read_protected(args.output)), 'deployed':False},sort_keys=True))
    except BaseException:
        # A timeout may have happened after commit. Never delete, restore or
        # overwrite DB credentials in response to an ambiguous outcome.
        if claimed:
            print(json.dumps({'stage':'STRIPE_SEED_OUTCOME_REQUIRES_OPERATOR_REVIEW',
                'helper_success_observed':helper_completed,'automatic_database_restore':False},sort_keys=True))
        raise
    finally:
        if identity:
            checked_helper(inspect_container(identity),identity,attempt,receipt['image_id'])
            docker(['rm','--force',identity])
        os.close(descriptor)


def cli(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--source-sha',required=True)
    for name in ('candidate','schema-before','schema-after','schema-manifest','schema-validation','backup'):
        parser.add_argument('--'+name,type=Path,required=True)
        parser.add_argument('--'+name+'-sha256',required=True)
    parser.add_argument('--runtime-env-sha256',required=True)
    parser.add_argument('--bootstrap-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    try:
        main(parser.parse_args(argv))
    except BaseException as error:
        code = str(error) if isinstance(error,SeedError) and re.fullmatch('[A-Z0-9_]{1,90}',str(error)) else 'SEED_REJECTED'
        print(json.dumps({'stage':'PRIVATE_STRIPE_SEED_REJECTED','error':code,'deployed':False},sort_keys=True))
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(cli())
