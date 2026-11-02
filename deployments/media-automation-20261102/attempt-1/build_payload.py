"""Local-only committed-source freeze and additive media automation packager."""
import argparse,gzip,hashlib,importlib.util,io,json,os,re,stat,subprocess,tarfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
H=lambda body:hashlib.sha256(body).hexdigest()
NODE='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
APP_BASELINE='eec3d1d02a97a5b52a1483e0c93f094242aade56'
SOURCE_SHA = '53d66ebb6c69d283c22596e806778989206763ec'
FRONTEND = '569fa342f1c3'
APPLICATION_FREEZE_SHA = '711fb12eb54b1ca6f1f940a69cbadd581865579aff37bfd555ae1a3cfd2aaf81'
PREFLIGHT_SHA = 'ecc7ae9cf9dfbdff68306b928b9b3a8f0ad98c90e5785611a061730f78a8beda'
BACKEND_BEFORE = {'alembic/versions/h43fe567f803_media_monthly_automation.py': None, 'main.py': '1e7411f7cf58bd9dcbeb29b8976d507b9f09422c8da469def7aed98088f14255', 'models/media_monthly_automation.py': None, 'routers/media_monthly_automation.py': None, 'schemas/media_monthly_automation.py': None, 'services/media_monthly.py': '4033f5c2365a801b586315a08d72f1e0a670990ac749b31a4fd5493d79fa19a7', 'services/media_monthly_automation.py': None, 'services/media_monthly_automation_worker.py': None, 'services/media_monthly_editorial.py': None}
BACKEND_AFTER = {'alembic/versions/h43fe567f803_media_monthly_automation.py': '736cce595e9ae8d7903bba3308a69440c1c253c667c526b4a63196f1704df9e2', 'main.py': '9edae4fae9ecaedf8466176d61f51e7fda09ef2ab1aafb04496ddc95576f8203', 'models/media_monthly_automation.py': 'be7cc8a478820f499928d69095d0d96c9e7e134a6e1b5efde025e974ea1abb95', 'routers/media_monthly_automation.py': '79415b0f50b934376665d157dee9604832278368bc098532e082b5b9a75a6091', 'schemas/media_monthly_automation.py': '2f084a8ded8925287a3f2b58d2b78ba0898350f4c4435f9fc3f3425e90b211bb', 'services/media_monthly.py': '129a4752fb54c3299c1da799cba457671f2441474ea6f1db15f832cbf004699d', 'services/media_monthly_automation.py': 'dcd5c71a6bfc361127343c5f1262836641828a7941a7265446b059cbc624d851', 'services/media_monthly_automation_worker.py': 'e84b09dda41aea86d9e5957b59a2f21f1fe8824d59afeba774bc90809d110308', 'services/media_monthly_editorial.py': '5753761a0526aa81cf11f883f558d51201adfb517e6e68ad6486bc29b8957751'}
CHANGED_SOURCE_HASHES = {'app/backend/alembic/versions/h43fe567f803_media_monthly_automation.py': '736cce595e9ae8d7903bba3308a69440c1c253c667c526b4a63196f1704df9e2', 'app/backend/main.py': '9edae4fae9ecaedf8466176d61f51e7fda09ef2ab1aafb04496ddc95576f8203', 'app/backend/models/media_monthly_automation.py': 'be7cc8a478820f499928d69095d0d96c9e7e134a6e1b5efde025e974ea1abb95', 'app/backend/routers/media_monthly_automation.py': '79415b0f50b934376665d157dee9604832278368bc098532e082b5b9a75a6091', 'app/backend/schemas/media_monthly_automation.py': '2f084a8ded8925287a3f2b58d2b78ba0898350f4c4435f9fc3f3425e90b211bb', 'app/backend/services/media_monthly.py': '129a4752fb54c3299c1da799cba457671f2441474ea6f1db15f832cbf004699d', 'app/backend/services/media_monthly_automation.py': 'dcd5c71a6bfc361127343c5f1262836641828a7941a7265446b059cbc624d851', 'app/backend/services/media_monthly_automation_worker.py': 'e84b09dda41aea86d9e5957b59a2f21f1fe8824d59afeba774bc90809d110308', 'app/backend/services/media_monthly_editorial.py': '5753761a0526aa81cf11f883f558d51201adfb517e6e68ad6486bc29b8957751', 'app/backend/tests/test_media_monthly_automation.py': '6a4ae579ddf3bcfc280251dad51f393df94b6417551be09c0f2dfbf87dee46bf', 'app/backend/tests/test_media_monthly_editorial.py': 'e156ef032486013943c55db59985b540bc40f807eca44734aa2971c69f5278da', 'app/frontend/src/components/MediaAutomationOverview.tsx': 'dc479f69e5cb7664f3b2ee1486477769dc0fb7ce3038bf0efb02cff7080b69a7', 'app/frontend/src/components/MediaAutomationPanel.tsx': '9f054194df5c4db1e49ba95bdbbcac7aeaa73312d7465b1482dd0c56e5832244', 'app/frontend/src/components/MediaMerchantWorkspace.tsx': '13a28385a4772b1307c54e8824961eb98a67a5a60ac262eae37f8dd14cbce619', 'app/frontend/src/components/MediaMonthlyWorkspace.tsx': '9f11b5de6bfad21822d397b7764deb5c12a065329cdc340b4fdf78b77c416383', 'app/frontend/src/components/MediaPublicationImage.tsx': '10fd2e63b56de725599f45aa6bfaee45dabf97e05974c19e7cb23a4adcd64203', 'app/frontend/src/components/media-automation-panel.css': '135360a18aee60b312f5ed44d51e7452a8191a51d0bd44091025df6a66d64b7f', 'app/frontend/src/components/media-publication-image.css': '921e1aaadc0c3ef925220917df828ea952e14e99c9472382c0fef0c73cf4b595', 'app/frontend/src/lib/media-automation-api.ts': '1edd7d21c1257dc775c88bd0ea7d5e41cee292cb0801713a556c52614898085a', 'app/frontend/src/lib/media-monthly-api.ts': '98175ed225fc70900c93c368c4e9de4d65506316cffb02613bba6c9176426ac3', 'app/frontend/src/lib/media-publication-images.ts': '9f496e9d83e26633de02768ca1d2f1bbde8839054fc5451ba4fce6cb6641406b', 'app/frontend/tests/media-automation.test.mjs': '296e1f8c9df708ce3997594e91721e19275411eac5008b8b7e3635fe00a7b983', 'app/frontend/tests/media-publication-images.test.mjs': '0bb70f65513b0ed06b02a27d90c0488e3f622e98fc1ce9cd76173184c8102950'}
BACKEND_SCOPE=frozenset({'main.py','services/media_monthly.py','alembic/versions/h43fe567f803_media_monthly_automation.py','models/media_monthly_automation.py','routers/media_monthly_automation.py','schemas/media_monthly_automation.py','services/media_monthly_automation.py','services/media_monthly_automation_worker.py','services/media_monthly_editorial.py'})
FRONTEND_SCOPE=frozenset({'app/frontend/src/components/MediaMerchantWorkspace.tsx','app/frontend/src/components/MediaMonthlyWorkspace.tsx','app/frontend/src/components/MediaPublicationImage.tsx','app/frontend/src/components/media-publication-image.css','app/frontend/src/lib/media-monthly-api.ts','app/frontend/src/lib/media-publication-images.ts','app/frontend/src/components/MediaAutomationOverview.tsx','app/frontend/src/components/MediaAutomationPanel.tsx','app/frontend/src/components/media-automation-panel.css','app/frontend/src/lib/media-automation-api.ts'})
TEST_SCOPE=frozenset({'app/backend/tests/test_media_monthly_automation.py','app/backend/tests/test_media_monthly_editorial.py','app/frontend/tests/media-publication-images.test.mjs','app/frontend/tests/media-automation.test.mjs'})
SOURCE_SCOPE=frozenset('app/backend/'+n for n in BACKEND_SCOPE)|FRONTEND_SCOPE|TEST_SCOPE
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

def release_module():
    spec=importlib.util.spec_from_file_location('_automation_release_pins',HERE/'release.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def validate_summary(p):
    r=release_module()
    need(p['stage']=='MEDIA_AUTOMATION_PREFLIGHT_CAPTURED' and re.fullmatch('[a-f0-9]{64}',p['sha256']) and p['path']=='/opt/t24-crm/releases/media-automation-preflight-'+p['sha256'][:12]+'.json' and p['source_sha']==r.BASE_SOURCE and p['frontend_version']==r.BASE_FRONTEND and p['schema_revision']==r.OLD_REVISION and p['table_count']==162 and p['backend_file_count']==420 and p['two_fresh_stable_samples_verified'] is True,'EXACT_FRESH_CURRENT162_BASELINE_REQUIRED')
    need(p['crm']['id']=='1ee579193b73048fb1120f516d53d2400191c2499cfad5284184ca0506ed698e' and p['schema_sha256']=='c111f3fc3154eab704a25536280bf02dfd00d120867da7ed9727ec2c85ac4a7f' and p['nginx_sha256']=='0184a613c95d04fb74f6d674213b1d787c000af33c5add5c90eb02637302ba40' and p['content_security_policy_sha256']=='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6','EXACT_CURRENT_RUNTIME_SCHEMA_NGINX_CSP_REQUIRED')
    need(p['environment_sha256']=='3d414fb4b9b5b1ae9bb5ecc1ce503be3c788f8bee27d0806de9d72fd3df0e223' and p['ops_environment_sha256']=='f334ac086b4f8eef3d92cc4b6444558f500590a2bd4020ce07d9d13f1947dfb2','EXACT_CURRENT_ENVIRONMENT_REQUIRED')
    need(p['google_scheduler_enabled'] is True and p['google_scheduler_activation_from']=='2026-10-30T19:42:04Z' and all(p[k] is False for k in ('ops_execution_enabled','ops_scheduler_enabled','new_automation_worker_enabled','schema_changed','business_writes','provider_requests','private_content_read','credential_file_content_read','runtime_changed','permissions_changed')),'READONLY_EXISTING_WORKER_POLICY_REQUIRED')
def committed_sources(source):
    need(re.fullmatch('[a-f0-9]{40}',source or '') and git('rev-parse','--verify',source+'^{commit}',maximum=100).decode().strip()==source,'EXACT_IMMUTABLE_APPLICATION_REQUIRED')
    before,after=inventory(APP_BASELINE),inventory(source)
    changed={n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)}
    need(changed==SOURCE_SCOPE and set(before)<=set(after),'EXACT_ADDITIVE_AUTOMATION_SOURCE_SCOPE_REQUIRED')
    need(git('rev-parse','HEAD:app',maximum=100)==git('rev-parse',source+':app',maximum=100),'HEAD_APPLICATION_TREE_DRIFT')
    for name,sha in after.items():need(H(local_bytes(ROOT/name))==sha,'LOCAL_COMMITTED_APPLICATION_SOURCE_DRIFT')
    expected={name for name in after if name.startswith('app/frontend/src/')}
    actual={str(p.relative_to(ROOT)) for p in (ROOT/'app/frontend/src').rglob('*') if p.is_file() or p.is_symlink()}
    need(actual==expected,'UNTRACKED_FRONTEND_SOURCE_REJECTED');return before,after,changed
def build(summary,*,source_sha,frontend,freeze_path,freeze_sha,dist):
    r=release_module();r.pins_ready();validate_summary(summary)
    need((source_sha,frontend,freeze_sha,summary['sha256'])==(r.SOURCE_SHA,r.FRONTEND,r.APPLICATION_FREEZE_SHA,r.PREFLIGHT_SHA),'EXACT_FROZEN_BUILD_INPUTS_REQUIRED')
    before,after,changed=committed_sources(source_sha);source_hashes={n:after[n] for n in sorted(changed)}
    need(source_hashes==r.CHANGED_SOURCE_HASHES and {n:before.get('app/backend/'+n) for n in BACKEND_SCOPE}==r.BACKEND_BEFORE and {n:after['app/backend/'+n] for n in BACKEND_SCOPE}==r.BACKEND_AFTER,'EXACT_SOURCE_PINS_REQUIRED')
    static=read_static(dist);version=frontend_version();need(version==frontend and strict_json(static['app-version.json'])=={'version':frontend},'EXACT_REVIEWED_BUILD_REQUIRED');dist_sha=static_inventory(static)
    body=local_bytes(freeze_path,1048576);need(H(body)==freeze_sha,'EXACT_APPLICATION_FREEZE_BYTES_REQUIRED');freeze=strict_json(body)
    need(freeze['stage']=='MEDIA_AUTOMATION_APPLICATION_FREEZE' and freeze['source_sha']==source_sha and freeze['frontend_version']==frontend and freeze['files']==source_hashes and freeze['preflight_sha256']==summary['sha256'] and freeze['dist_inventory_sha256']==dist_sha,'EXACT_SOURCE_QA_DIST_FREEZE_REQUIRED')
    payload={'backend/'+n:local_bytes(ROOT/'app/backend'/n) for n in BACKEND_SCOPE};payload.update({'static/'+n:b for n,b in static.items()});need(all(H(payload['backend/'+n])==r.BACKEND_AFTER[n] for n in BACKEND_SCOPE),'RUNTIME_MEMBER_HASH_DRIFT')
    blob=deterministic_payload(payload)
    manifest={'stage':'MEDIA_AUTOMATION_PAYLOAD','format_version':1,'source_sha':source_sha,'frontend_version':frontend,'baseline_source_sha':r.BASE_SOURCE,'baseline_static_source_sha':APP_BASELINE,'baseline_frontend_version':r.BASE_FRONTEND,'old_schema_revision':r.OLD_REVISION,'schema_revision':r.NEW_REVISION,'additive_tables':sorted(r.NEW_TABLES),'preflight_sha256':summary['sha256'],'application_freeze_sha256':freeze_sha,'payload_sha256':H(blob),'changed_source_files':source_hashes,'backend_before':r.BACKEND_BEFORE,'backend_after':r.BACKEND_AFTER,'files':{n:H(b) for n,b in sorted(payload.items())},'dist_inventory_sha256':dist_sha,'protected_source_inventory':{n:s for n,s in before.items() if n not in changed},**{k:False for k in ('dependencies_changed','credentials_included','runtime_environment_changed','production_seed_rows','provider_requests','automation_worker_enabled','operations_execution_enabled','operations_scheduler_enabled','permissions_changed')}}
    r.validate_manifest(manifest,H(blob));need(read_static(dist)==static and frontend_version()==frontend,'BUILD_CHANGED_DURING_PACKAGING');return blob,manifest
def main():
    p=argparse.ArgumentParser();p.add_argument('--inspect-dist',action='store_true');p.add_argument('--dist',type=Path,default=ROOT/'app/frontend/dist');p.add_argument('--source-sha');p.add_argument('--frontend-version');p.add_argument('--application-freeze',type=Path);p.add_argument('--application-freeze-sha256');p.add_argument('--preflight-summary',type=Path);p.add_argument('--out',type=Path,default=HERE/'artifacts');a=p.parse_args()
    if a.inspect_dist:print(json.dumps(inspect_static(a.dist),sort_keys=True));return
    need(all(x is not None for x in (a.source_sha,a.frontend_version,a.application_freeze,a.application_freeze_sha256,a.preflight_summary)),'EXPLICIT_FROZEN_BUILD_INPUTS_REQUIRED')
    blob,manifest=build(strict_json(local_bytes(a.preflight_summary,1048576)),source_sha=a.source_sha,frontend=a.frontend_version,freeze_path=a.application_freeze,freeze_sha=a.application_freeze_sha256,dist=a.dist);write_artifacts(blob,manifest,a.out)
    print(json.dumps({'source_sha':a.source_sha,'frontend_version':a.frontend_version,'payload_sha256':H(blob),'manifest_sha256':H(encoded(manifest)),'file_count':len(manifest['files']),'changed_source_count':len(SOURCE_SCOPE),'original_table_count':162,'new_table_count':165,'provider_requests':False,'deployment_performed':False},sort_keys=True))
if __name__=='__main__':main()


