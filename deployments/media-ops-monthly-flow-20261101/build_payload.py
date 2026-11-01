"""Local-only monthly draft preparation with additive tables packager.

The builder performs no network, install, Git write, database write or deployment.
It packages the reviewed additive migration, new monthly modules, exact existing
projection adapter and full frontend static tree for separate guarded phases.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
H = lambda body: hashlib.sha256(body).hexdigest()
NODE = '/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
SOURCE_SHA = 'd39337fccfd622e506ca3c1a655a126f5218dc42'
FRONTEND = '8113d14d204f'
APPLICATION_FREEZE_SHA = '1e3edce0603d35fe5728fff2f762ed3723aafb2f75d0b7b35a1f75dc3dde8699'
BASE_SOURCE = '6ab1ded2e139e8622596a2a71ca1041015a0b95f'
BASE_FRONTEND = '628bd059a499'
OLD_REVISION = 'df0ba123b469'
SCHEMA_REVISION = NEW_REVISION = 'e10cb234c570'
NEW_TABLES = frozenset({'media_monthly_workflows','media_monthly_workflow_requests'})
PREFLIGHT_SHA='42bc79e1b7041e3b376ca94ab8bef01d6dc6224e151821958cf48225f90faaaf'
NEW_BACKEND_FILES = frozenset({'models/media_monthly_workflow.py','services/media_monthly_workflow.py','schemas/media_monthly_workflow.py','routers/media_monthly_workflow.py','alembic/versions/e10cb234c570_media_monthly_workflow.py'})
EXISTING_BACKEND_HASHES={'services/media_operations.py': '770a9faec2adc3da198805c5c07521c203c02726f05be6094728cf58d2af3d4c', 'services/google_business_scheduler.py': 'bbd41181d2331cc1f0205b77c9a0bf417454c6cc94f7a43978a3e8433edaf9dc', 'services/google_business.py': 'aee16b8d281be5c88e06d7150882cd0a10ae4e20b89b2521ca4bd24746b8ed8f', 'services/google_business_management.py': '98c68806871f26cbb3600eba56d99ab145373310dd4e2f3c25cfe38579524fd4', 'services/media_monthly.py': '12d1e7a43e811ff49608efaf1265aaa8047e52cc7296d759f936d5e48d952a90'}
BACKEND_FILES = NEW_BACKEND_FILES|frozenset(EXISTING_BACKEND_HASHES)
FRONTEND_FILES = frozenset(['app/frontend/src/components/MediaMerchantWorkspace.tsx', 'app/frontend/src/components/MediaMonthlyAttention.tsx', 'app/frontend/src/components/MediaMonthlyPipeline.tsx', 'app/frontend/src/components/MediaMonthlyWorkspace.tsx', 'app/frontend/src/components/media-monthly-attention.css', 'app/frontend/src/components/media-monthly-pipeline.css', 'app/frontend/src/components/media-monthly-workspace.css', 'app/frontend/src/lib/media-monthly-api.ts', 'app/frontend/src/lib/media-monthly-attention.ts', 'app/frontend/src/lib/media-monthly-workflow-api.ts'])
TEST_FILES = frozenset(['app/backend/tests/test_media_monthly_projection_workflow.py', 'app/backend/tests/test_media_monthly_workflow.py', 'app/frontend/tests/media-monthly-attention.test.mjs', 'app/frontend/tests/media-monthly-pipeline.test.mjs', 'app/frontend/tests/media-monthly-workflow.test.mjs'])
SOURCE_FILES = frozenset('app/backend/' + name for name in BACKEND_FILES) | FRONTEND_FILES | TEST_FILES
BACKEND_BEFORE = {name:EXISTING_BACKEND_HASHES.get(name) for name in sorted(BACKEND_FILES)}
BACKEND_AFTER = {'alembic/versions/e10cb234c570_media_monthly_workflow.py': 'cd865b83a44fd7b1d39bee350b2ec74437bad08aee416b2e4896bf7c074fe3be', 'models/media_monthly_workflow.py': 'd81dfcb0d9a5682dc8ee0b1dcfbb86be8f3c0cf090950be21c10b31948e0cc7e', 'routers/media_monthly_workflow.py': '7a22b2119bb930a4f405eaa3557e94425b10dc71499b5d13b6f46d6cdc468729', 'schemas/media_monthly_workflow.py': '6af2d989b862753179e771739cb8947ae05c5d608fb88568195705a7776a8bd2', 'services/google_business.py': '12622e71ed6c1b0c28dcb4db9742bc011c79e711c3029981ccff1d33b04064e0', 'services/google_business_management.py': '84b37b911113f593e17a1ee9e2b03fa072cf4fe9445b23cc4586839c801f5364', 'services/google_business_scheduler.py': '19947e4fc4c598628b33edeec37251e75b0a97ff61534448b9053bfb22a0bf46', 'services/media_monthly.py': 'c6cfab6a3ad4eaae145a3aa816b8f6263ddbf6383484b4670d67955c5c0f7229', 'services/media_monthly_workflow.py': 'bb7671a4017b75a4dec36b0cae6099cb22f1f4386dcc166a31edacf855c1f20f', 'services/media_operations.py': 'd8cca0bbbf78f71967f3dbc0d2c5c7b20223bee5519dc047ee8ea715d8ce290a'}
TRUE_FLAGS = ('frontend_changed','all153_original_tables_preserved_except_reviewed_schema_head','existing_full_environment_preserved','existing_ops_credentials_preserved','database_migration','schema_changed')
FALSE_FLAGS = ('dependencies_changed','credentials_included','runtime_environment_changed','production_seed_rows','provider_requests','operations_execution_enabled','operations_scheduler_enabled')

CAPTURE_FOCUS_HASHES={'models/media_monthly.py': '9a9df045ae0ce840d145a235a3e6cde20ac7f2f0d9882b39da0672e6b99434f7', 'routers/media_monthly.py': '006105d08609e4c93bf63d6aff705a7010938bd755cdf99eb314b969b7f020ac', 'schemas/media_monthly.py': '061aafc8b067c1433cba4e2089ff57fdeacc824f3aa571d4ad45e520feb256ce', 'services/google_business_management.py': '98c68806871f26cbb3600eba56d99ab145373310dd4e2f3c25cfe38579524fd4', 'services/google_business_scheduler.py': 'bbd41181d2331cc1f0205b77c9a0bf417454c6cc94f7a43978a3e8433edaf9dc', 'services/media_monthly.py': '12d1e7a43e811ff49608efaf1265aaa8047e52cc7296d759f936d5e48d952a90', 'services/media_workspace.py': '14e031977f8db04f16bc40b7818416279eac52222e6352d39976bee848471bf9'}

def need(ok, code):
    if not ok: raise RuntimeError(code)


def digest(value): return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def local_bytes(path, maximum=16*1024**2):
    path = Path(path); row = path.lstat()
    need(path.resolve() == path.absolute() and stat.S_ISREG(row.st_mode) and row.st_nlink == 1, 'REGULAR_LOCAL_INPUT_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream: opened = os.fstat(stream.fileno()); body = stream.read(maximum+1)
    after = path.lstat(); identity = lambda r: (r.st_dev,r.st_ino,r.st_size,r.st_mtime_ns,r.st_ctime_ns,r.st_mode,r.st_nlink)
    need(identity(row) == identity(opened) == identity(after) and len(body) <= maximum, 'BOUNDED_LOCAL_INPUT_REQUIRED')
    return body


def strict_json(body):
    def pairs(rows):
        result = {}
        for key,value in rows:
            need(key not in result, 'DUPLICATE_JSON_KEY_REJECTED'); result[key] = value
        return result
    def constant(value): raise RuntimeError('NONFINITE_JSON_VALUE_REJECTED')
    return json.loads(body, object_pairs_hook=pairs, parse_constant=constant)


def git(*args, maximum=160*1024**2):
    # No shell, remote command or user-controlled ref syntax is used.
    child = subprocess.Popen(['git', *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        body = child.stdout.read(maximum+1)
        need(len(body) <= maximum, 'BOUNDED_LOCAL_GIT_OUTPUT_REQUIRED')
        need(child.wait(timeout=60) == 0, 'LOCAL_COMMITTED_GIT_OBJECT_REQUIRED')
        return body
    finally:
        if child.poll() is None: child.kill(); child.wait(timeout=5)
        child.stdout.close()


def inventory(ref):
    blob = git('archive', '--format=tar', ref, 'app/')
    result = {}; seen = set(); total = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
        for item in archive:
            path = Path(item.name)
            need(item.name not in seen and not path.is_absolute() and str(path) == item.name.rstrip('/') and '..' not in path.parts and path.parts[0] == 'app', 'CANONICAL_UNIQUE_SOURCE_MEMBER_REQUIRED')
            seen.add(item.name)
            need(item.isdir() or item.isfile(), 'SOURCE_LINK_OR_SPECIAL_REJECTED')
            if item.isdir(): continue
            need(0 <= item.size <= 16*1024**2 and len(seen) <= 20000, 'BOUNDED_SOURCE_MEMBER_REQUIRED')
            total += item.size; need(total <= 128*1024**2, 'BOUNDED_APPLICATION_SOURCE_REQUIRED')
            stream = archive.extractfile(item); body = stream.read(item.size+1)
            need(len(body) == item.size, 'COMPLETE_COMMITTED_SOURCE_REQUIRED'); result[item.name] = H(body)
    need(bool(result), 'NONEMPTY_APPLICATION_SOURCE_REQUIRED')
    return result


def frontend_version():
    # This is the exact existing Vite sourceVersion algorithm, including the
    # Node localeCompare order. It does not build, install or contact a service.
    code = "const fs=require('node:fs'),p=require('node:path'),h=require('node:crypto').createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){const q=p.join(d,e.name);if(e.isSymbolicLink())throw Error('link');if(e.isDirectory())walk(q);else if(e.isFile()){h.update(p.relative(root,q));h.update(fs.readFileSync(q));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"
    value = subprocess.check_output([NODE,'-e',code,str(ROOT/'app/frontend/src')], cwd=ROOT).decode()
    need(re.fullmatch('[a-f0-9]{12}',value), 'EXACT_FRONTEND_SOURCE_VERSION_REQUIRED')
    return value


def static_path(name):
    path = Path(name); parts = path.parts
    if not parts or path.is_absolute() or str(path) != name or '\\' in name or any(part.startswith('.') for part in parts): return False
    if len(parts) == 1: return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or path.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch(r'workbox-[a-zA-Z0-9_-]+[.]js',name))
    return parts[0] == 'assets' and path.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}


def read_static(dist):
    dist = Path(dist)
    need(dist.resolve() == dist.absolute() and dist.is_dir() and not dist.is_symlink(), 'CANONICAL_DIST_DIRECTORY_REQUIRED')
    result = {}; total = 0
    for path in sorted(dist.rglob('*')):
        row = path.lstat(); need(not path.is_symlink() and (stat.S_ISDIR(row.st_mode) or stat.S_ISREG(row.st_mode)), 'DIST_LINK_OR_SPECIAL_REJECTED')
        if path.is_dir(): continue
        name = str(path.relative_to(dist)); need(static_path(name), 'DIST_PATH_REJECTED')
        body = local_bytes(path); total += len(body)
        need(len(result) < 10000 and total < 64*1024**2 and body, 'BOUNDED_NONEMPTY_DIST_REQUIRED'); result[name] = body
    need({'index.html','app-version.json'} <= set(result), 'COMPLETE_DIST_REQUIRED')
    return result


def static_inventory(files): return digest({name:H(body) for name,body in files.items()})


def inspect_static(dist):
    files = read_static(dist); version = strict_json(files['app-version.json'])
    need(isinstance(version,dict) and set(version) == {'version'} and re.fullmatch('[a-f0-9]{12}',version.get('version','')), 'EXACT_DIST_VERSION_FORMAT_REQUIRED')
    return {'frontend_version':version['version'],'dist_inventory_sha256':static_inventory(files),'file_count':len(files),'total_bytes':sum(map(len,files.values())),'artifacts_written':False}


def deterministic_payload(files):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output,mode='wb',mtime=0,filename='') as compressed:
        with tarfile.open(fileobj=compressed,mode='w',format=tarfile.USTAR_FORMAT) as archive:
            for name,body in sorted(files.items()):
                item = tarfile.TarInfo(name); item.size = len(body); item.mode = 0o644; item.mtime = 0; item.uid = item.gid = 0; item.uname = item.gname = ''
                archive.addfile(item,io.BytesIO(body))
    blob = output.getvalue(); need(len(blob) <= 16*1024**2, 'BOUNDED_CARRIER_PAYLOAD_REQUIRED'); return blob


def write_artifacts(blob, manifest, out):
    out = Path(out)
    need(out.absolute() == HERE/'artifacts' and out.resolve() == out.absolute() and not out.exists() and not out.is_symlink(), 'FRESH_EXACT_ARTIFACT_DIRECTORY_REQUIRED')
    identity = lambda row:(row.st_dev,row.st_ino,row.st_uid,row.st_gid,stat.S_IMODE(row.st_mode),stat.S_IFMT(row.st_mode))
    parent_before = HERE.lstat()
    need(HERE.resolve() == HERE and stat.S_ISDIR(parent_before.st_mode), 'CANONICAL_ARTIFACT_PARENT_REQUIRED')
    parent_fd = os.open(HERE,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    directory_fd = None
    try:
        parent_opened = os.fstat(parent_fd)
        need(identity(parent_before) == identity(parent_opened) == identity(HERE.lstat()), 'ARTIFACT_PARENT_OPEN_DRIFT')
        os.mkdir('artifacts',mode=0o700,dir_fd=parent_fd)
        before = os.stat('artifacts',dir_fd=parent_fd,follow_symlinks=False)
        need(stat.S_ISDIR(before.st_mode) and before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) == 0o700, 'OWNED_PRIVATE_ARTIFACT_DIRECTORY_REQUIRED')
        directory_fd = os.open('artifacts',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
        opened = os.fstat(directory_fd)
        def boundary():
            need(identity(parent_opened) == identity(os.fstat(parent_fd)) == identity(HERE.lstat()), 'ARTIFACT_PARENT_NAMESPACE_DRIFT')
            named = os.stat('artifacts',dir_fd=parent_fd,follow_symlinks=False)
            need(identity(before) == identity(opened) == identity(os.fstat(directory_fd)) == identity(named) == identity(out.lstat()), 'ARTIFACT_DIRECTORY_NAMESPACE_DRIFT')
        boundary(); need(os.listdir(directory_fd) == [], 'FRESH_EMPTY_ARTIFACT_DIRECTORY_REQUIRED')
        created = set()
        for name,body in (('payload.tar.gz',blob),('manifest.json',encoded(manifest))):
            boundary(); need(set(os.listdir(directory_fd)) == created, 'ARTIFACT_DIRECTORY_MEMBERS_DRIFT')
            fd = os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory_fd)
            with os.fdopen(fd,'wb') as stream:
                file_before = os.fstat(stream.fileno())
                need(stat.S_ISREG(file_before.st_mode) and file_before.st_uid == os.geteuid() and file_before.st_nlink == 1 and stat.S_IMODE(file_before.st_mode) == 0o600, 'OWNED_REGULAR_ARTIFACT_FILE_REQUIRED')
                boundary(); stream.write(body); stream.flush(); os.fsync(stream.fileno())
                file_after = os.fstat(stream.fileno()); named = os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
                need(identity(file_before) == identity(file_after) == identity(named) and file_after.st_nlink == named.st_nlink == 1 and file_after.st_size == len(body), 'ARTIFACT_FILE_NAMESPACE_DRIFT')
                boundary()
            created.add(name)
        boundary(); need(set(os.listdir(directory_fd)) == created, 'ARTIFACT_DIRECTORY_MEMBERS_DRIFT')
        os.fsync(directory_fd); os.fsync(parent_fd); boundary()
    finally:
        if directory_fd is not None: os.close(directory_fd)
        os.close(parent_fd)


def validate_summary(p):
    need(p['stage']=='MEDIA_OPS_MONTHLY_FLOW_PREFLIGHT_CAPTURED' and p['sha256']==PREFLIGHT_SHA and p['path']=='/opt/t24-crm/releases/media-ops-monthly-flow-preflight-'+PREFLIGHT_SHA[:12]+'.json' and
         p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==OLD_REVISION and p['table_count']==153 and p['all153_populated_tables_preserved'] is True and
         p['crm']=={'id':'1bb27a7b759a8195968e5891fc124bd6efdffece985db8759954af3054e97027','config':'01e708ba2e4c29d3029dbb4981cd452b086fe2ca301d19b2f8b47e43aedaded0','image':'sha256:2377c980b99e56a0637fd0c7c90b9a90f97432c5ee8bd3e30c05a21dbb5edc9d','restart':0,'started':'2026-11-01T03:42:26.485641774Z'} and
         p['backend_changed_before']==CAPTURE_FOCUS_HASHES and p['backend_file_count']==403 and p['environment_sha256']=='3d414fb4b9b5b1ae9bb5ecc1ce503be3c788f8bee27d0806de9d72fd3df0e223' and p['ops_environment_sha256']=='f334ac086b4f8eef3d92cc4b6444558f500590a2bd4020ce07d9d13f1947dfb2','EXACT_CONFIGURED_ALL153_BASELINE_REQUIRED')
    need(p['google_scheduler_enabled'] is True and p['google_scheduler_activation_from']=='2026-10-30T19:42:04Z','EXACT_EXISTING_GOOGLE_POLICY_REQUIRED')
    need(all(p[key] is False for key in ('ops_execution_enabled','ops_scheduler_enabled','schema_changed','permissions_changed','credential_file_content_read','private_content_read','business_writes','provider_requests','runtime_changed')),'READONLY_PRESERVING_BASELINE_REQUIRED')


def inputs(source_sha, frontend, freeze_sha):
    need(isinstance(SOURCE_SHA,str) and re.fullmatch('[a-f0-9]{40}',SOURCE_SHA) and SOURCE_SHA != BASE_SOURCE and source_sha == SOURCE_SHA and
         isinstance(FRONTEND,str) and re.fullmatch('[a-f0-9]{12}',FRONTEND) and FRONTEND != BASE_FRONTEND and frontend == FRONTEND and
         isinstance(APPLICATION_FREEZE_SHA,str) and re.fullmatch('[a-f0-9]{64}',APPLICATION_FREEZE_SHA) and APPLICATION_FREEZE_SHA != '0'*64 and freeze_sha == APPLICATION_FREEZE_SHA,
         'EXPLICIT_FINAL_SOURCE_FRONTEND_FREEZE_REQUIRED')
    need(NEW_BACKEND_FILES == {'models/media_monthly_workflow.py','services/media_monthly_workflow.py','schemas/media_monthly_workflow.py','routers/media_monthly_workflow.py','alembic/versions/e10cb234c570_media_monthly_workflow.py'} and BACKEND_FILES == NEW_BACKEND_FILES|frozenset(EXISTING_BACKEND_HASHES) and bool(FRONTEND_FILES) and bool(TEST_FILES) and
         BACKEND_BEFORE == {name:EXISTING_BACKEND_HASHES.get(name) for name in BACKEND_FILES} and isinstance(BACKEND_AFTER,dict) and set(BACKEND_AFTER)==BACKEND_FILES and
         all(isinstance(sha,str) and re.fullmatch('[a-f0-9]{64}',sha) for sha in BACKEND_AFTER.values()),'EXACT_ADDITIVE_MONTHLY_DRAFT_SCOPE_REQUIRED')
    need(git('rev-parse','--verify',source_sha+'^{commit}',maximum=100).decode().strip()==source_sha,'EXACT_IMMUTABLE_SOURCE_COMMIT_REQUIRED')



def frozen_sources(path, sha, after, source_sha, frontend, dist_sha):
    body = local_bytes(Path(path), 1048576); need(H(body) == sha, 'EXACT_APPLICATION_FREEZE_REQUIRED'); value = strict_json(body)
    need(value['source_sha'] == source_sha and value['frontend_version'] == frontend and value['baseline_source_sha'] == BASE_SOURCE and value['baseline_frontend_version'] == BASE_FRONTEND and
         value['schema_revision'] == NEW_REVISION and value['old_schema_revision'] == OLD_REVISION and value['dist_inventory_sha256'] == dist_sha,
         'EXACT_SOURCE_SCHEMA_AND_QA_DIST_FREEZE_REQUIRED')
    rows = value['files']; need(isinstance(rows, dict) and set(rows) == SOURCE_FILES and all(isinstance(pin, str) and re.fullmatch('[a-f0-9]{64}', pin) and after.get(name) == pin for name, pin in rows.items()), 'FROZEN_APPLICATION_SOURCE_DRIFT')
    need(all(value[key] is True for key in TRUE_FLAGS) and all(value[key] is False for key in FALSE_FLAGS), 'EXACT_NONMIGRATING_PRESERVATION_FREEZE_REQUIRED')


def build(summary, *, source_sha, frontend, freeze_path, freeze_sha, dist=None):
    inputs(source_sha, frontend, freeze_sha); validate_summary(summary)
    before, after = inventory(BASE_SOURCE), inventory(source_sha)
    need(inventory('HEAD') == after, 'HEAD_APPLICATION_TREE_DRIFT')
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    diff = git('diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--name-only', '-z', BASE_SOURCE, source_sha, '--', 'app/', maximum=1048576).decode().split('\0')
    diff = [name for name in diff if name]
    need(changed == SOURCE_FILES and set(diff) == changed and len(diff) == len(changed) and set(before) <= set(after) and set(after)-set(before) <= SOURCE_FILES, 'EXACT_ADDITIVE_UI_PROJECTION_APPLICATION_DELTA_REQUIRED')
    for name, pin in after.items(): need(H(local_bytes(ROOT / name)) == pin, 'LOCAL_COMMITTED_APPLICATION_SOURCE_DRIFT')
    expected = {name for name in after if name.startswith('app/frontend/src/')}
    actual = {str(path.relative_to(ROOT)) for path in (ROOT / 'app/frontend/src').rglob('*') if path.is_file() or path.is_symlink()}
    need(actual == expected, 'UNTRACKED_FRONTEND_SOURCE_REJECTED')
    backend_before = {name: before.get('app/backend/' + name) for name in sorted(BACKEND_FILES)}
    backend_after = {name: after.get('app/backend/' + name) for name in sorted(BACKEND_FILES)}
    need(backend_before == BACKEND_BEFORE and backend_after == BACKEND_AFTER, 'EXACT_REVIEWED_BACKEND_BEFORE_AFTER_REQUIRED')
    need(frontend_version() == frontend, 'FRONTEND_SOURCE_VERSION_DRIFT')
    dist = Path(dist) if dist is not None else ROOT / 'app/frontend/dist'; static = read_static(dist); dist_sha = static_inventory(static)
    need(strict_json(static['app-version.json']) == {'version': frontend}, 'EXACT_FRONTEND_BUILD_REQUIRED')
    frozen_sources(freeze_path, freeze_sha, after, source_sha, frontend, dist_sha)
    payload = {'backend/' + name: local_bytes(ROOT / 'app/backend' / name) for name in BACKEND_FILES}
    need(all(H(payload['backend/' + name]) == backend_after[name] for name in BACKEND_FILES), 'FINAL_RUNTIME_SOURCE_HASH_DRIFT')
    payload.update({'static/' + name: body for name, body in static.items()})
    need(sum(map(len, payload.values())) < 80 * 1024 ** 2 and all(0 < len(body) <= 16 * 1024 ** 2 for body in payload.values()), 'BOUNDED_EXACT_RUNTIME_STATIC_PAYLOAD_REQUIRED')
    need(read_static(dist) == static and frontend_version() == frontend and H(local_bytes(Path(freeze_path), 1048576)) == freeze_sha, 'SOURCE_OR_QA_DIST_CHANGED_DURING_PACKAGING')
    blob = deterministic_payload(payload)
    manifest = {'format_version': 1, 'source_sha': source_sha, 'frontend_version': frontend, 'baseline_source_sha': BASE_SOURCE, 'baseline_frontend_version': BASE_FRONTEND,
        'schema_revision': NEW_REVISION, 'old_schema_revision': OLD_REVISION, 'additive_tables': sorted(NEW_TABLES), 'preflight_sha256': summary['sha256'], 'payload_sha256': H(blob),
        'application_freeze_sha256': freeze_sha, 'changed_source_files': sorted(changed), 'backend_before': backend_before, 'backend_after': backend_after,
        'files': {name: H(body) for name, body in sorted(payload.items())}, 'dist_inventory_sha256': dist_sha,
        'protected_source_inventory': {name: pin for name, pin in before.items() if name not in changed}, **{name: True for name in TRUE_FLAGS}, **{name: False for name in FALSE_FLAGS}}
    return blob, manifest


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--inspect-dist', action='store_true'); parser.add_argument('--dist', type=Path, default=ROOT / 'app/frontend/dist')
    parser.add_argument('--source-sha'); parser.add_argument('--frontend-version'); parser.add_argument('--application-freeze', type=Path); parser.add_argument('--application-freeze-sha256')
    parser.add_argument('--preflight-summary', type=Path); parser.add_argument('--out', type=Path, default=HERE / 'artifacts'); args = parser.parse_args()
    if args.inspect_dist: print(json.dumps(inspect_static(args.dist), sort_keys=True)); return
    need(all(value is not None for value in (args.source_sha, args.frontend_version, args.application_freeze, args.application_freeze_sha256, args.preflight_summary)), 'EXPLICIT_FINAL_BUILD_INPUTS_REQUIRED')
    blob, manifest = build(strict_json(local_bytes(args.preflight_summary, 1048576)), source_sha=args.source_sha, frontend=args.frontend_version,
        freeze_path=args.application_freeze, freeze_sha=args.application_freeze_sha256, dist=args.dist)
    write_artifacts(blob, manifest, args.out)
    print(json.dumps({'source_sha': args.source_sha, 'frontend_version': args.frontend_version, 'payload_sha256': H(blob), 'manifest_sha256': H(encoded(manifest)),
        'dist_inventory_sha256': manifest['dist_inventory_sha256'], 'file_count': len(manifest['files']), 'application_delta_count': len(SOURCE_FILES), 'original_table_count': 153, 'new_table_count': 155,
        'database_migration': True, 'dependencies_changed': False, 'network_requests': False, 'git_changed': False, 'deployment_performed': False}, sort_keys=True))


if __name__ == '__main__': main()
