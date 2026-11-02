"""Local-only freeze/package for the unified owner automation settings release."""
import argparse,gzip,hashlib,importlib.util,io,json,os,re,stat,subprocess,tarfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
H=lambda body:hashlib.sha256(body).hexdigest()
NODE='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
APP_BASELINE='c78b50a11e020674ad53b34fbbfb5b1badd4a9a5'
SOURCE_SHA = '54e027aad00e81a4ebb747ada1299e7a10e1ec52'
FRONTEND = '32a580644502'
PREFLIGHT_SHA = '0dd43fefcf43ee7c925cbf825b3d88fb125abe1168f3adde9478ba603205dc83'
FREEZE_SHA = '741cab247da5f316d946e76fb8fddda5cd92e46788b12a1ede835d822ef6e333'
BACKEND_BEFORE = {'alembic/versions/i54af678a914_media_automation_settings.py': None, 'models/media_automation_settings.py': None, 'routers/media_automation_settings.py': None, 'schemas/media_automation_settings.py': None, 'services/media_automation_settings.py': None, 'services/media_monthly.py': '129a4752fb54c3299c1da799cba457671f2441474ea6f1db15f832cbf004699d', 'services/media_monthly_automation.py': '3b431233f665bd8cbae629cf965f66848270525a5ac9b22f1065457e2d47d06b', 'services/media_monthly_editorial.py': '5753761a0526aa81cf11f883f558d51201adfb517e6e68ad6486bc29b8957751'}
BACKEND_AFTER = {'alembic/versions/i54af678a914_media_automation_settings.py': '29146c5673cfce364eb1b868de25695c3815f02f40cbfc044f0000cf12e78bce', 'models/media_automation_settings.py': '3ec119125b27200aa75dd7df12e5c0d1f8416dbb444ffd6c0c118053adaab32a', 'routers/media_automation_settings.py': 'b5389eb5dc797b9c10d3ea8aa9b864a6735dd2ddf880aebaf719a7225feca622', 'schemas/media_automation_settings.py': 'c478c561476b4b6a943e371e1d12c57b8e17f6e5942c889dd1bda88eb055dbe6', 'services/media_automation_settings.py': '6bd889b58064194759c16beb91e73a408db85b0f33424f938194dd09990971ec', 'services/media_monthly.py': '21e079775d89bc6c97110c474786872508c05bd28ae40112f08fb2e3c3c5248a', 'services/media_monthly_automation.py': '04545a23eb1b6a2a3cdd7f718faca080118092bc6789e7e1ab98064f137e34ef', 'services/media_monthly_editorial.py': '91bcb1e27c5f955ed94a09b24a06f3970a59f9ecbcee8f0ce14e7f53053e6220'}
SOURCE_FILES = {'app/backend/alembic/versions/i54af678a914_media_automation_settings.py': '29146c5673cfce364eb1b868de25695c3815f02f40cbfc044f0000cf12e78bce', 'app/backend/models/media_automation_settings.py': '3ec119125b27200aa75dd7df12e5c0d1f8416dbb444ffd6c0c118053adaab32a', 'app/backend/routers/media_automation_settings.py': 'b5389eb5dc797b9c10d3ea8aa9b864a6735dd2ddf880aebaf719a7225feca622', 'app/backend/schemas/media_automation_settings.py': 'c478c561476b4b6a943e371e1d12c57b8e17f6e5942c889dd1bda88eb055dbe6', 'app/backend/services/media_automation_settings.py': '6bd889b58064194759c16beb91e73a408db85b0f33424f938194dd09990971ec', 'app/backend/services/media_monthly.py': '21e079775d89bc6c97110c474786872508c05bd28ae40112f08fb2e3c3c5248a', 'app/backend/services/media_monthly_automation.py': '04545a23eb1b6a2a3cdd7f718faca080118092bc6789e7e1ab98064f137e34ef', 'app/backend/services/media_monthly_editorial.py': '91bcb1e27c5f955ed94a09b24a06f3970a59f9ecbcee8f0ce14e7f53053e6220', 'app/backend/tests/test_media_automation_settings.py': 'ff09109393fc13f6671251514df0354712c8a00a21cdbdb5e008b40cae5f329a', 'app/backend/tests/test_media_monthly_editorial.py': 'e3d4ec229e649b5ce483a7dea2d1b333400a796a9f42534d446999482579e67d', 'app/frontend/src/components/MediaMerchantWorkspace.tsx': '8a8b0c4ddbedd642ebd060f22d67e82ffa5ed13f3a3e6a2999e8562a622cd6e5', 'app/frontend/src/components/MediaMonthlyWorkspace.tsx': 'f3d95599771b542a46c2b47205469951955d871a5914042f81fc72a93dacb3a8', 'app/frontend/src/components/MediaUnifiedAutomationSettings.tsx': '2987977b2e75c48001f39a05222aab1a5df31841b26249d4fb02446bd1ecc293', 'app/frontend/src/components/media-unified-automation-settings.css': 'fe808df63e660dc9dd6d2035c98f2ef6f4c8b89c2519c6189184038e57510c8b', 'app/frontend/src/lib/media-automation-settings-api.ts': '1885b3858fde29436e3e9a3097dd12c08bf67e38dcec8ff07c6061dde0fe04b5', 'app/frontend/src/lib/media-monthly-api.ts': '338bb94d6b848b11514ba7b8f145a5a3085ae85f21101c8913c995f438e97f7a', 'app/frontend/tests/media-automation-settings.test.mjs': '25798e87a724b64db40771883a8378c8d187625322a9005a0177ff46c1d68991'}
BACKEND_SCOPE=frozenset({'services/media_monthly.py','services/media_monthly_automation.py','services/media_monthly_editorial.py','alembic/versions/i54af678a914_media_automation_settings.py','models/media_automation_settings.py','routers/media_automation_settings.py','schemas/media_automation_settings.py','services/media_automation_settings.py'})
FRONTEND_SCOPE=frozenset({'app/frontend/src/components/MediaMerchantWorkspace.tsx','app/frontend/src/components/MediaMonthlyWorkspace.tsx','app/frontend/src/lib/media-monthly-api.ts','app/frontend/src/components/MediaUnifiedAutomationSettings.tsx','app/frontend/src/components/media-unified-automation-settings.css','app/frontend/src/lib/media-automation-settings-api.ts'})
TEST_SCOPE=frozenset({'app/backend/tests/test_media_automation_settings.py','app/backend/tests/test_media_monthly_editorial.py','app/frontend/tests/media-automation-settings.test.mjs'})
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
    spec=importlib.util.spec_from_file_location('_unified_release_pins',HERE/'release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def validate_summary(v):
    need(v['stage']=='MEDIA_UNIFIED_SETTINGS_BASELINE_CAPTURED' and re.fullmatch('[a-f0-9]{64}',v['sha256'] or '') and v['path']=='/opt/t24-crm/releases/media-unified-settings-baseline-'+v['sha256'][:12]+'.json' and v['source_sha']==APP_BASELINE and v['frontend_version']=='569fa342f1c3' and v['schema_revision']=='h43fe567f803' and v['table_count']==165 and v['backend_file_count']==427,'EXACT_CURRENT427_165_BASELINE_REQUIRED')
    need(v['crm']=={'config':'b01627120f6ade88898d49db1301837104817ec67c66f211dd99a0f0ed368529','id':'0e33ad4fcfb91258d37206ff66473cb95e6a033fb15b572e8cbc89a8a56849b2','image':'sha256:f456f7aaca2452db96c9df796f3c01efda9a2f23403bdd5e3b755b409c6de8f1','restart':0,'started':'2026-11-02T04:19:00.366678579Z'} and v['schema_sha256']=='7bccbd8ff34d0d10d102b5fe3510470ee6b7817be7f168921f2887e7f6bf3872','EXACT_CURRENT_RUNTIME_SCHEMA_REQUIRED')
    need(v['monthly_auto_prep_enabled'] is True and v['google_scheduler_enabled'] is True and v['google_scheduler_activation_from']=='2026-10-30T19:42:04Z' and v['old_flags_preserved'] is True and v['meta_execution_enabled'] is False and v['meta_scheduler_enabled'] is False and v['immutable_two_samples_verified'] is True and v['live_rows_may_advance_before_stop'] is True and all(v[k] is False for k in ('business_writes','provider_requests','runtime_changed','schema_changed','credentials_exported','private_content_exported')),'READONLY_EXISTING_FLAGS_BASELINE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',v[k] or '') for k in ('environment_sha256','ordered_environment_sha256','backend_inventory_sha256','content_security_policy_sha256','public_inventory_sha256','nginx_sha256','active_nginx_sha256')),'EXACT_IMMUTABLE_BASELINE_HASHES_REQUIRED')
def committed_sources(source):
    need(re.fullmatch('[a-f0-9]{40}',source or '') and source!=APP_BASELINE and git('rev-parse','--verify',source+'^{commit}',maximum=100).decode().strip()==source,'EXACT_NEW_COMMITTED_APPLICATION_REQUIRED');before,after=inventory(APP_BASELINE),inventory(source);changed={n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)};need(changed==SOURCE_SCOPE and set(before)<=set(after),'EXACT_SCOPED_SETTINGS_APPLICATION_REQUIRED');need(git('rev-parse','HEAD:app',maximum=100)==git('rev-parse',source+':app',maximum=100),'HEAD_APPLICATION_TREE_CHANGED')
    for name,sha in after.items():need(H(local_bytes(ROOT/name))==sha,'LOCAL_COMMITTED_SOURCE_CHANGED')
    expected={name for name in after if name.startswith('app/frontend/src/')};actual={str(p.relative_to(ROOT)) for p in (ROOT/'app/frontend/src').rglob('*') if p.is_file() or p.is_symlink()};need(actual==expected,'UNTRACKED_FRONTEND_SOURCE_REJECTED');return before,after,changed
def build(summary,*,source_sha,frontend,freeze_path,freeze_sha,dist):
    r=release_module();r.pins_ready();validate_summary(summary);need((source_sha,frontend,freeze_sha,summary['sha256'])==(r.SOURCE_SHA,r.FRONTEND,r.FREEZE_SHA,r.PREFLIGHT_SHA),'EXACT_FROZEN_BUILD_INPUTS_REQUIRED');before,after,changed=committed_sources(source_sha);files={n:after[n] for n in sorted(changed)};need(files==r.SOURCE_FILES and {n:before.get('app/backend/'+n) for n in BACKEND_SCOPE}==r.BACKEND_BEFORE and {n:after['app/backend/'+n] for n in BACKEND_SCOPE}==r.BACKEND_AFTER,'EXACT_FINAL_SOURCE_OVERLAY_REQUIRED');static=read_static(dist);need(frontend_version()==frontend and strict_json(static['app-version.json'])=={'version':frontend},'EXACT_REVIEWED_FRONTEND_BUILD_REQUIRED');dist_sha=static_inventory(static);body=local_bytes(freeze_path,1048576);need(H(body)==freeze_sha,'EXACT_FREEZE_BYTES_REQUIRED');freeze=strict_json(body);need(freeze['stage']=='MEDIA_UNIFIED_SETTINGS_APPLICATION_FREEZE' and freeze['source_sha']==source_sha and freeze['source_files']==files and freeze['frontend_version']==frontend and freeze['dist_inventory_sha256']==dist_sha and freeze['preflight_sha256']==summary['sha256'],'EXACT_SOURCE_DIST_BASELINE_FREEZE_REQUIRED');payload={'backend/'+name:local_bytes(ROOT/'app/backend'/name) for name in BACKEND_SCOPE};payload.update({'static/'+name:value for name,value in static.items()});need(all(H(payload['backend/'+name])==r.BACKEND_AFTER[name] for name in BACKEND_SCOPE),'RUNTIME_SOURCE_HASH_CHANGED');blob=deterministic_payload(payload)
    manifest={'stage':'MEDIA_UNIFIED_SETTINGS_PAYLOAD','format_version':1,'source_sha':source_sha,'frontend_version':frontend,'baseline_source_sha':APP_BASELINE,'baseline_frontend_version':'569fa342f1c3','old_schema_revision':r.OLD_REVISION,'schema_revision':r.NEW_REVISION,'new_tables':sorted(r.NEW_TABLES),'preflight_sha256':summary['sha256'],'freeze_sha256':freeze_sha,'payload_sha256':H(blob),'source_files':files,'backend_before':r.BACKEND_BEFORE,'backend_after':r.BACKEND_AFTER,'files':{n:H(v) for n,v in sorted(payload.items())},'dist_inventory_sha256':dist_sha,'protected_source_inventory':{n:v for n,v in before.items() if n not in changed},**{name:False for name in ('dependencies_changed','credentials_included','environment_changed','worker_flags_changed','production_seed_rows','provider_requests','permissions_changed')}};r.validate_manifest(manifest,H(blob));need(read_static(dist)==static and frontend_version()==frontend,'REVIEWED_BUILD_CHANGED_DURING_PACKAGING');return blob,manifest
def main():
    p=argparse.ArgumentParser();p.add_argument('--inspect-dist',action='store_true');p.add_argument('--dist',type=Path,default=ROOT/'app/frontend/dist');p.add_argument('--source-sha');p.add_argument('--frontend-version');p.add_argument('--freeze',type=Path);p.add_argument('--freeze-sha256');p.add_argument('--baseline-summary',type=Path);p.add_argument('--out',type=Path,default=HERE/'artifacts');a=p.parse_args()
    if a.inspect_dist:print(json.dumps(inspect_static(a.dist),sort_keys=True));return
    need(all(v is not None for v in (a.source_sha,a.frontend_version,a.freeze,a.freeze_sha256,a.baseline_summary)),'EXPLICIT_BUILD_INPUTS_REQUIRED');blob,manifest=build(strict_json(local_bytes(a.baseline_summary,1048576)),source_sha=a.source_sha,frontend=a.frontend_version,freeze_path=a.freeze,freeze_sha=a.freeze_sha256,dist=a.dist);write_artifacts(blob,manifest,a.out);print(json.dumps({'source_sha':a.source_sha,'frontend_version':a.frontend_version,'manifest_sha256':H(encoded(manifest)),'payload_sha256':H(blob),'source_delta_count':len(SOURCE_SCOPE),'runtime_overlay_count':len(BACKEND_SCOPE),'old_table_count':165,'new_table_count':169,'production_writes':False,'deployment_performed':False},sort_keys=True))
if __name__=='__main__':main()

