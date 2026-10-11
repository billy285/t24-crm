#!/usr/bin/env python3
"""Prepare an isolated private candidate; never switch services or mount live DBs.

Operator must supply independent frozen hashes. Docker runs have no network,
production environment, live data mounts, ports or privileged capabilities.
The only writable mounts contain synthetic fixtures and new release evidence.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import tarfile
from uuid import uuid4
import xml.etree.ElementTree as ET

import build_payload as builder
import live_preflight as live
import private_schema_guard as guard

TARGET_TABLES = guard.BASE_TABLES | frozenset({'private_mail_translations', 'private_translation_usage',
    'private_mail_briefs', 'private_mail_brief_usage', 'private_workspace_briefs', 'private_bank_links'})
WHEEL_VERSIONS = {'pytest': '8.4.2', 'pytest-asyncio': '1.2.0', 'iniconfig': '2.3.1', 'pluggy': '1.6.0',
    'pygments': '2.21.0', 'packaging': '26.3', 'tomli': '2.2.1', 'exceptiongroup': '1.3.0',
    'backports-asyncio-runner': '1.2.0'}
BASE_TEST_ROOT = Path('/opt/t24-crm/releases/private-workspace-1a4c952-20261011-retry2')
SCAN_BACKEND = """import hashlib,json,pathlib
r=pathlib.Path('/app/backend');out={}
for p in sorted(r.rglob('*')):
 rel=p.relative_to(r)
 if {'data','logs','private-data','__pycache__'}.intersection(rel.parts) or p.suffix in ('.pyc','.pyo'):continue
 assert not p.is_symlink()
 if p.is_file():out[rel.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
assert out
print(json.dumps(out,sort_keys=True))
"""
SCAN_PACKAGES = """import hashlib,json,pathlib,sysconfig
h=hashlib.sha256();count=0
for label in ('purelib','scripts'):
 r=pathlib.Path(sysconfig.get_path(label))
 for p in sorted(r.rglob('*')):
  if p.is_file():
   b=p.read_bytes();h.update(json.dumps([label+'/'+p.relative_to(r).as_posix(),len(b),hashlib.sha256(b).hexdigest()],separators=(',',':')).encode());count+=1
assert count>100
print(json.dumps({'files':count,'sha256':h.hexdigest()},sort_keys=True))
"""
SCAN_DIST = SCAN_BACKEND.replace("'/app/backend'", "'/app/frontend/dist'")
SYNTHETIC_ENV = {
    'APP_ENV': 'test', 'ENVIRONMENT': 'test', 'ENV': 'test', 'TZ': 'Asia/Shanghai',
    'DATABASE_URL': 'sqlite+aiosqlite:////tmp/synthetic-business.db', 'DATABASE_SCHEMA_MODE': 'verify_only',
    'PRIVATE_WORKSPACE_DATABASE_URL': 'sqlite+aiosqlite:////tmp/synthetic-private/workspace.db',
    'PRIVATE_WORKSPACE_OWNER_IDS': '4', 'PRIVATE_WORKSPACE_ENCRYPTION_KEY': 'synthetic_candidate_encryption_key_never_production',
    'JWT_SECRET_KEY': 'synthetic_candidate_employee_signing_key_never_production',
    'AUTOMATION_SCAN_ENABLED': 'false', 'ENABLE_DEFAULT_EMPLOYEE_ADMIN': 'false',
    'PRIVATE_MAIL_BRIEF_ENABLED': 'false', 'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT': 'false',
    'PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED': 'false', 'PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT': 'false',
    'PRIVATE_WORKSPACE_PLAID_ENABLED': 'false', 'ENFORCE_EMPLOYEE_STATUS': 'false',
    'ENFORCE_EMPLOYEE_SESSIONS': 'false', 'PYTHONDONTWRITEBYTECODE': '1',
}
FIXTURE_BASE = """import os,pathlib,sqlite3
from sqlalchemy import create_engine
from models.private_workspace import PrivateWorkspaceBase
from services.private_workspace import encrypt_credentials
r=pathlib.Path('/synthetic');p=r/'original.db';b=r/'business.db'
e=create_engine('sqlite:///'+str(p));PrivateWorkspaceBase.metadata.create_all(e);e.dispose()
with sqlite3.connect(p) as c:
 token=encrypt_credentials({'synthetic':'fixture-only-never-live'})
 c.execute(\"INSERT INTO private_connections(id,owner_id,source_id,status,encrypted_credentials,metadata_json,generation,created_at,updated_at) VALUES ('synthetic','4','gmail','connected',?,'{}',1,'2026-10-11','2026-10-11')\",(token,))
 c.execute(\"INSERT INTO private_preferences(owner_id,preferences_json,updated_at) VALUES ('4','{}','2026-10-11')\")
 c.execute(\"INSERT INTO private_items(id,owner_id,source_id,external_id,kind,title,summary,status,priority,evidence,action_status,created_at,updated_at) VALUES ('synthetic-item','4','gmail','fixture-message','mail','Synthetic fixture','No real mail','unread','normal','{}','done','2026-10-11','2026-10-11')\")
 c.execute(\"INSERT INTO private_sync_runs(id,owner_id,source_id,status,started_at,created_count,updated_count) VALUES ('synthetic-run','4','gmail','complete','2026-10-11',1,0)\")
with sqlite3.connect(b) as c:
 c.execute('CREATE TABLE finance_sentinel(id INTEGER PRIMARY KEY,amount INTEGER NOT NULL)')
 c.execute('INSERT INTO finance_sentinel VALUES (1,70000)')
for f in (p,b):os.chmod(f,0o600)
print('{"synthetic_only":true,"original_four_created":true}')
"""
EMPTY_SCHEMA = """import os
from sqlalchemy import create_engine
from models.private_workspace import PrivateWorkspaceBase
p='/synthetic/empty.db';e=create_engine('sqlite:///'+p);PrivateWorkspaceBase.metadata.create_all(e);e.dispose();os.chmod(p,0o600)
print('{"empty_candidate_schema":true}')
"""
INIT_MIGRATION = """import os,asyncio
os.environ['DATABASE_URL']='sqlite+aiosqlite:////synthetic/business.db'
os.environ['PRIVATE_WORKSPACE_DATABASE_URL']='sqlite+aiosqlite:////synthetic/migrated/workspace.db'
from services.private_workspace import private_session_factory,close_private_workspace_storage
async def run():
 await private_session_factory();await close_private_workspace_storage()
asyncio.run(run());print('{"synthetic_initializer_completed":true}')
"""
ROLLBACK_READ = """import os,asyncio
os.environ['DATABASE_URL']='sqlite+aiosqlite:////synthetic/business.db'
os.environ['PRIVATE_WORKSPACE_DATABASE_URL']='sqlite+aiosqlite:////synthetic/migrated/workspace.db'
from sqlalchemy import select
from models.private_workspace import PrivateConnection
from services.private_workspace import private_session_factory,close_private_workspace_storage,decrypt_credentials
async def run():
 sessions=await private_session_factory()
 async with sessions() as db:
  row=(await db.execute(select(PrivateConnection))).scalar_one()
  assert row.owner_id=='4' and decrypt_credentials(row.encrypted_credentials)=={'synthetic':'fixture-only-never-live'}
 await close_private_workspace_storage()
asyncio.run(run());print('{"old_image_reads_upgraded_private_schema":true}')
"""


class PrepareError(RuntimeError): pass

def need(condition, code):
    if not condition: raise PrepareError(code)

def sha(blob): return hashlib.sha256(blob).hexdigest()

def protected(path, *, directory=False):
    need(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'CANONICAL_PROTECTED_PATH_REQUIRED')
    for p in (path, *path.parents): need(not p.is_symlink(), 'PROTECTED_PATH_SYMLINK')
    s = path.stat()
    need(s.st_uid == os.geteuid() and not stat.S_IMODE(s.st_mode) & 0o077 and
         (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink == 1), 'PROTECTED_OWNER_MODE_REQUIRED')


def frozen_file(path, expected, maximum=64 * 1024**2):
    protected(path); need(builder.HASH.fullmatch(expected or '') and path.stat().st_size <= maximum, 'FROZEN_FILE_REQUIRED')
    blob = path.read_bytes(); need(sha(blob) == expected, 'FROZEN_FILE_HASH_DRIFT'); return blob


def save(path, value): builder.write_new(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def checked_payload(manifest, frozen, archive_hash):
    need(isinstance(manifest, dict) and manifest.get('stage') == 'PRIVATE_FINANCE_PAYLOAD_PREPARED' and manifest.get('format_version') == 1,
         'PREPARED_PAYLOAD_REQUIRED')
    need(manifest.get('source_sha') == frozen['source_sha'] and manifest.get('base_private_image') == builder.BASE_IMAGE and
         manifest.get('baseline_private_source_sha') == builder.BASE_SOURCE and manifest.get('frontend_version') == frozen['frontend_version'] and
         manifest.get('payload_sha256') == archive_hash and manifest.get('runtime_dependency_changes') is False and
         manifest.get('credentials_included') is False and manifest.get('production_access') is False and manifest.get('deployed') is False,
         'FROZEN_PAYLOAD_SCOPE_DRIFT')
    inventory = manifest.get('payload_files')
    need(isinstance(inventory, dict) and inventory and len(inventory) < 10000 and
         all(isinstance(name, str) and isinstance(value, str) and builder.HASH.fullmatch(value) for name,value in inventory.items()), 'EXACT_PAYLOAD_INVENTORY_REQUIRED')
    delta = frozen['backend_delta_sha256']
    need(set(manifest.get('backend_changes', [])) == set(delta) and
         all(builder.PRIVATE_RUNTIME.fullmatch(name) or builder.PRIVATE_TEST.fullmatch(name) for name in delta), 'PRIVATE_DELTA_SCOPE_REQUIRED')
    source_files = manifest.get('source_file_sha256')
    tests = manifest.get('private_tests')
    need(isinstance(source_files, dict) and isinstance(tests, list) and tests and len(tests) == len(set(tests)) and
         all(builder.PRIVATE_TEST.fullmatch(name) or name == 'app/backend/tests/conftest.py' for name in tests) and
         'app/backend/tests/conftest.py' in tests, 'ALL_PRIVATE_TESTS_REQUIRED')
    need(set(source_files) == set(delta) | set(tests) and all(source_files.get(name) == value for name,value in delta.items()),
         'SOURCE_MANIFEST_DELTA_DRIFT')
    expected = {name.removeprefix('app/'): value for name,value in source_files.items()}
    expected.update({'frontend/dist/' + name:value for name,value in frozen['frontend_dist_sha256'].items()})
    need(inventory == expected and manifest.get('runtime_dependency_file_sha256') == frozen['dependency_file_sha256'] and
         manifest.get('backend_regression_tests_expected_minimum') == frozen['backend_regression_tests_minimum'], 'COMPLETE_FROZEN_PAYLOAD_DRIFT')
    for name in inventory:
        p = PurePosixPath(name)
        need(p.as_posix() == name and not p.is_absolute() and '..' not in p.parts and not any(part.startswith('.') for part in p.parts), 'PAYLOAD_PATH_REJECTED')
    return manifest


def extract(blob, manifest, root):
    need(not root.exists() and not root.is_symlink(), 'NEW_PAYLOAD_ROOT_REQUIRED'); root.mkdir(mode=0o700)
    files = {}; total = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        for member in archive:
            name = member.name.removeprefix('payload/')
            p = PurePosixPath(name)
            need(member.isfile() and member.name.startswith('payload/') and p.as_posix() == name and not p.is_absolute()
                 and '..' not in p.parts and not any(part.startswith('.') for part in p.parts)
                 and name not in files and name in manifest['payload_files'] and 0 <= member.size <= 16 * 1024**2, 'REGULAR_ALLOWLISTED_ARCHIVE_ONLY')
            total += member.size; need(total <= 64 * 1024**2, 'PAYLOAD_EXPANSION_LIMIT')
            blob = archive.extractfile(member).read(member.size + 1)
            need(len(blob) == member.size and sha(blob) == manifest['payload_files'][name], 'PAYLOAD_MEMBER_HASH_DRIFT')
            target = root / name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700); builder.write_new(target, blob); files[name] = sha(blob)
    need(files == manifest['payload_files'], 'PAYLOAD_INCOMPLETE'); return files


def recipe(manifest):
    backend = sorted(name for name in manifest['payload_files'] if name.startswith('backend/'))
    need(backend and builder.SOURCE_HASH.fullmatch(manifest['source_sha']), 'PRIVATE_IMAGE_RECIPE_REQUIRED')
    return ('FROM ' + builder.BASE_IMAGE + '\n' + ''.join('COPY ' + name + ' /app/' + name + '\n' for name in backend)
        + 'COPY frontend/dist/ /app/frontend/dist/\nLABEL t24.private.source.sha="' + manifest['source_sha'] + '"\n').encode()


def expected_backend(base, manifest):
    expected = dict(base)
    for name,value in manifest['payload_files'].items():
        if name.startswith('backend/'): expected[name.removeprefix('backend/')] = value
    return expected


def expected_dist(base, manifest):
    expected = dict(base)
    for name, value in manifest['payload_files'].items():
        if name.startswith('frontend/dist/'):
            relative = name.removeprefix('frontend/dist/')
            # Previously served hashed asset URLs must continue to name identical bytes.
            need(not (relative.startswith('assets/') and relative in base and base[relative] != value),
                 'EXISTING_STATIC_ASSET_HASH_COLLISION')
            expected[relative] = value
    return expected


def test_report(xml, minimum):
    root = ET.fromstring(xml); suites = list(root.iter('testsuite')); cases = list(root.iter('testcase'))
    total = sum(int(suite.get('tests', '0')) for suite in suites)
    need(suites and total >= minimum and len(cases) == total and
         all(int(suite.get(key, '0')) == 0 for suite in suites for key in ('failures','errors','skipped')) and
         not any(list(root.iter(tag)) for tag in ('failure','error','skipped')), 'COMPLETE_CANDIDATE_REGRESSIONS_REQUIRED')
    return total


def wheel_tools(wheels, manifest):
    need(isinstance(manifest,dict) and manifest, 'FROZEN_TEST_WHEELS_REQUIRED'); protected(wheels, directory=True)
    actual = {}; tools = []
    for path in wheels.iterdir():
        # Wheels are public test tooling. The protected parent prevents other users reading
        # release files; historical wheel files may have immutable 0644 rather than 0600.
        s = path.lstat()
        need(not path.is_symlink() and stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and
             s.st_uid == os.geteuid() and not stat.S_IMODE(s.st_mode) & 0o022,
             'IMMUTABLE_TEST_WHEEL_REQUIRED')
        name = path.name; bits = name.split('-'); normalized = re.sub('[-_.]+','-',bits[0]).lower()
        need(name.endswith('.whl') and len(bits) >= 5 and WHEEL_VERSIONS.get(normalized) == bits[1], 'ONLY_PINNED_TEST_TOOLS_ALLOWED')
        actual[name] = sha(path.read_bytes()); tools.append(normalized + '==' + bits[1])
    need(actual == manifest and {tool.split('==')[0] for tool in tools} == set(WHEEL_VERSIONS), 'TEST_WHEEL_INVENTORY_DRIFT')
    return sorted(tools)


class Runner:
    def __init__(self, release): self.release = release
    def run(self, stage, command, *, timeout=180, cwd=None):
        result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout, check=False)
        builder.write_new(self.release / (stage + '.log'), result.stdout + b'\n' + result.stderr)
        need(result.returncode == 0, 'ISOLATED_' + stage.upper().replace('-','_') + '_FAILED')
        return result.stdout
    def isolated(self, stage, image, code, *, mounts=(), timeout=180):
        need(re.fullmatch('sha256:[a-f0-9]{64}',image), 'IMMUTABLE_IMAGE_REQUIRED')
        token = uuid4().hex; name = 't24-private-finance-check-' + token[:12]
        arguments = ['docker','run','--rm','--name',name,'--label','t24.private.finance.check=' + token,
            '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--no-healthcheck',
            '--workdir','/app/backend','--pids-limit','128','--memory','1g','--cpus','2',
            '--tmpfs','/tmp:rw,nosuid,size=512m','--tmpfs','/app/backend/logs:rw,nosuid,noexec,size=16m']
        for key,value in sorted(SYNTHETIC_ENV.items()): arguments += ['--env',key + '=' + value]
        for source,destination,readonly in mounts:
            protected(source,directory=True)
            need(source.is_relative_to(self.release) or source == BASE_TEST_ROOT / 'test-wheels', 'SYNTHETIC_OR_TEST_MOUNT_ONLY')
            arguments += ['--mount','type=bind,src=' + str(source) + ',dst=' + destination + (',readonly' if readonly else '')]
        arguments += ['--entrypoint','python',image,'-c',code]
        try: return self.run(stage,arguments,timeout=timeout)
        finally:
            found = subprocess.run(['docker','inspect',name],capture_output=True,timeout=30,check=False)
            if found.returncode == 0:
                rows = json.loads(found.stdout)
                need(len(rows)==1 and rows[0]['Image']==image and rows[0]['Config'].get('Labels',{}).get('t24.private.finance.check')==token,
                     'OWN_TEST_CONTAINER_CLEANUP_IDENTITY_REQUIRED')
                subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=30,check=True)
    def scan(self,stage,image,code): return json.loads(self.isolated(stage,image,code))


def schema_rehearsal(runner,image,manifest):
    synthetic = runner.release / 'synthetic'; synthetic.mkdir(mode=0o700)
    mounts = [(synthetic,'/synthetic',False)]
    runner.isolated('schema-original-fixture',builder.BASE_IMAGE,FIXTURE_BASE,mounts=mounts)
    original,business = synthetic/'original.db',synthetic/'business.db'
    before = guard.release_snapshot(original,business)
    need(set(before['private']['tables']) == guard.BASE_TABLES, 'ACTUAL_BASE_IMAGE_FOUR_TABLES_REQUIRED')
    runner.isolated('schema-empty-candidate',image,EMPTY_SCHEMA,mounts=mounts)
    empty = guard.database_snapshot(synthetic/'empty.db',private=True)
    need(set(empty['tables']) == TARGET_TABLES and all(row['rows']==0 for row in empty['tables'].values()), 'EXACT_EMPTY_TEN_TABLE_SCHEMA_REQUIRED')
    schema = {'format_version':1,'stage':'FROZEN_PRIVATE_ADDITIVE_SCHEMA_MANIFEST','source_sha':manifest['source_sha'],
        'baseline_tables':sorted(guard.BASE_TABLES),'target_tables':sorted(TARGET_TABLES),'target_schema_objects':empty['schema_objects'],
        'business_table_count':len(before['business']['tables']),'business_schema_sha256':before['business']['schema_sha256']}
    save(runner.release/'synthetic-schema-manifest.json',schema); save(runner.release/'synthetic-before.json',before)
    migrated = synthetic/'migrated'; migrated.mkdir(mode=0o700)
    with sqlite3.connect(original) as old,sqlite3.connect(migrated/'workspace.db') as new: old.backup(new)
    (migrated/'workspace.db').chmod(0o600)
    runner.isolated('schema-candidate-initializer',image,INIT_MIGRATION,mounts=mounts)
    after = guard.release_snapshot(migrated/'workspace.db',business)
    proof = guard.compare_snapshots(before,after,schema,source_sha=manifest['source_sha'],mode='clone')
    save(runner.release/'synthetic-after.json',after); save(runner.release/'synthetic-schema-validation.json',proof)
    runner.isolated('schema-old-image-rollback-read',builder.BASE_IMAGE,ROLLBACK_READ,mounts=mounts)
    need(guard.release_snapshot(migrated/'workspace.db',business)==after, 'ROLLBACK_READ_CHANGED_SYNTHETIC_DATA_OR_SCHEMA')
    return {'stage':'SYNTHETIC_SCHEMA_AND_OLD_IMAGE_COMPATIBILITY_VERIFIED','tables':sorted(TARGET_TABLES),
        'schema_manifest_sha256':sha((runner.release/'synthetic-schema-manifest.json').read_bytes()),
        'schema_objects':empty['schema_objects'],'base_image_id':builder.BASE_IMAGE,'candidate_image_id':image,
        'original_rows_columns_indexes_preserved':True,'new_tables_empty':True,'business_unchanged':True,
        'old_image_reads_upgraded_schema':True,'production_database_access':False}


def main(args):
    os.umask(0o077)
    frozen_blob = frozen_file(args.freeze,args.freeze_sha256,4*1024**2); frozen = builder.freeze(args.freeze,args.freeze_sha256)
    manifest = json.loads(frozen_file(args.manifest,args.manifest_sha256,4*1024**2))
    archive = frozen_file(args.payload,args.payload_sha256)
    checked_payload(manifest,frozen,args.payload_sha256)
    need(manifest.get('frozen_manifest_sha256')==args.freeze_sha256,'ORIGINAL_FROZEN_SOURCE_HASH_DRIFT')
    baseline = json.loads(frozen_file(args.baseline,args.baseline_sha256,4*1024**2))
    live.compare_baseline(live.preflight(),baseline)
    need(args.release.is_absolute() and args.release.parent == Path('/opt/t24-crm/releases') and
         re.fullmatch('private-finance-' + frozen['source_sha'][:12] + '-20261011-candidate(?:-[a-z0-9]{1,16})?',args.release.name)
         and not args.release.exists() and not args.release.is_symlink(),'NEW_REVIEWED_RELEASE_DIRECTORY_REQUIRED')
    need(shutil.disk_usage(args.release.parent).free > 4*1024**3,'MINIMUM_CANDIDATE_SPACE_REQUIRED')
    args.release.mkdir(mode=0o700); protected(args.release,directory=True); runner = Runner(args.release)
    save(args.release/'running-baseline.json',baseline)
    root = args.release/'payload'; extract(archive,manifest,root); builder.write_new(root/'Dockerfile',recipe(manifest))
    # Image inspection is captured in memory only: baked production credentials are forbidden.
    inspection = subprocess.run(['docker','image','inspect',builder.BASE_IMAGE], capture_output=True,
                                timeout=30, check=False)
    need(inspection.returncode == 0, 'EXACT_EXISTING_PRIVATE_BASE_IMAGE_REQUIRED')
    inspect = json.loads(inspection.stdout)
    need(len(inspect)==1 and inspect[0]['Id']==builder.BASE_IMAGE,'EXACT_EXISTING_PRIVATE_BASE_IMAGE_REQUIRED')
    env = dict(value.split('=',1) for value in inspect[0]['Config'].get('Env',[]))
    need(not any(value and re.search('SECRET|TOKEN|PASSWORD|PRIVATE_.*KEY|OPENAI|PLAID',key) for key,value in env.items()),'PRODUCTION_CREDENTIALS_BAKED_IN_BASE_IMAGE')
    base = runner.scan('base-backend',builder.BASE_IMAGE,SCAN_BACKEND); packages = runner.scan('base-packages',builder.BASE_IMAGE,SCAN_PACKAGES)
    dist = runner.scan('base-static',builder.BASE_IMAGE,SCAN_DIST)
    tag = 't24-private-finance-candidate:' + frozen['source_sha'][:12]
    exists = subprocess.run(['docker','image','inspect',tag],capture_output=True,timeout=30,check=False)
    need(exists.returncode!=0,'NEW_CANDIDATE_IMAGE_TAG_REQUIRED')
    runner.run('candidate-build',['docker','build','--pull=false','--network=none','--no-cache','-t',tag,'.'],timeout=600,cwd=root)
    image = runner.run('candidate-image-id',['docker','image','inspect','-f','{{.Id}}',tag]).decode().strip()
    need(re.fullmatch('sha256:[a-f0-9]{64}',image) and image!=builder.BASE_IMAGE,'IMMUTABLE_DISTINCT_CANDIDATE_REQUIRED')
    need(runner.scan('candidate-backend',image,SCAN_BACKEND)==expected_backend(base,manifest),'UNRELATED_BACKEND_OR_DEPENDENCY_BYTES_CHANGED')
    need(runner.scan('candidate-packages',image,SCAN_PACKAGES)==packages,'RUNTIME_PACKAGE_BYTES_CHANGED')
    need(runner.scan('candidate-static',image,SCAN_DIST)==expected_dist(dist,manifest),'COMPLETE_CANDIDATE_STATIC_BYTES_CHANGED')
    wheels = BASE_TEST_ROOT/'test-wheels'; wheel_manifest = json.loads(frozen_file(BASE_TEST_ROOT/'test-wheel-manifest.json',args.test_wheel_manifest_sha256,1024**2))
    tools = wheel_tools(wheels,wheel_manifest)
    results = args.release/'test-results'; results.mkdir(mode=0o700)
    code = "import os,sys,subprocess\n" + "subprocess.check_call([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-cache-dir','--no-index','--find-links','/test-wheels','--target','/tmp/test-deps','--no-deps',*" + repr(tools) + "])\n"
    code += "os.environ['PYTHONPATH']='/tmp/test-deps:/app:/app/backend'\nsubprocess.check_call([sys.executable,'-m','pytest',*" + repr(['/app/'+name.removeprefix('app/') for name in manifest['private_tests'] if name.endswith('.py') and not name.endswith('/conftest.py')]) + ",'-q','--disable-warnings','--tb=short','-p','no:cacheprovider','--junitxml=/test-results/regressions.xml'],cwd='/app/backend')\n"
    runner.isolated('candidate-regressions',image,code,mounts=[(wheels,'/test-wheels',True),(results,'/test-results',False)],timeout=600)
    total = test_report((results/'regressions.xml').read_bytes(),frozen['backend_regression_tests_minimum'])
    schema = schema_rehearsal(runner,image,manifest)
    live.compare_baseline(live.preflight(),baseline)
    # Re-read frozen evidence after all external waits before issuing a receipt.
    need(frozen_file(args.freeze,args.freeze_sha256)==frozen_blob,'FROZEN_SOURCE_CHANGED')
    frozen_file(args.manifest,args.manifest_sha256); frozen_file(args.payload,args.payload_sha256); frozen_file(args.baseline,args.baseline_sha256)
    receipt = {'format_version':1,'stage':'PRIVATE_FINANCE_CANDIDATE_VERIFIED','source_sha':frozen['source_sha'],
        'frontend_version':frozen['frontend_version'],'image_id':image,'base_image_id':builder.BASE_IMAGE,
        'frozen_source_sha256':args.freeze_sha256,'payload_manifest_sha256':args.manifest_sha256,'payload_sha256':args.payload_sha256,
        'baseline_sha256':args.baseline_sha256,'all_other_backend_bytes_identical':True,'all_package_bytes_identical':True,
        'complete_frontend_dist_bytes_verified':True,'existing_hashed_static_assets_preserved':True,
        'candidate_regressions':{'tests':total,'minimum':frozen['backend_regression_tests_minimum'],'network':'none',
        'xml_sha256':sha((results/'regressions.xml').read_bytes()),'all_private_tests':manifest['private_tests'],
        'production_environment_loaded':False,'production_database_access':False},'synthetic_schema':schema,
        'production_services_modified':False,'public_assets_published':False,'production_databases_modified':False,'deployed':False}
    save(args.release/'candidate.json',receipt)
    print(json.dumps({'stage':receipt['stage'],'image_id':image,'tests':total,'candidate_sha256':sha((args.release/'candidate.json').read_bytes()),'deployed':False},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('freeze','manifest','payload','baseline','release'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('freeze','manifest','payload','baseline','test-wheel-manifest'):parser.add_argument('--'+name+'-sha256',required=True)
    try:main(parser.parse_args())
    except Exception as error:
        code=str(error) if isinstance(error,(PrepareError,builder.PayloadError,live.PreflightError,guard.GuardError)) and re.fullmatch('[A-Z0-9_]+',str(error)) else 'CANDIDATE_PREPARATION_FAILED'
        print('PRIVATE_FINANCE_CANDIDATE_ERROR '+code);raise SystemExit(1) from None
