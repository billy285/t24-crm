"""Package the committed exception-priority UI and test only; static output."""
import argparse,gzip,hashlib,io,json,os,re,stat,subprocess,tarfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
H=lambda b:hashlib.sha256(b).hexdigest()
NODE='/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
BASE_SOURCE='5fd379d625d6c18abdec1b98d388494d0900c780'
BASE_FRONTEND='1d94d63752de'
SOURCE='eec3d1d02a97a5b52a1483e0c93f094242aade56'
FRONTEND='8c3b5e1302ac'
FILES=frozenset(['app/frontend/src/components/MediaPortfolioPanels.tsx', 'app/frontend/src/components/media-merchant-workspace.css', 'app/frontend/tests/media-workspace-queue.test.mjs'])
PREFLIGHT_SHA='78bb1249abca9506a9158c88fcbc31edf36c0eef6926c07ddc07f6235e0a9143'
APPLICATION_FREEZE_SHA='917e7976c1474fc5882f39b3dbcd455793ea530f57d1c75224ac5e2e4db063a9'
TRUE_FLAGS=('static_only','exact_monthly_action_layout_only','original162_database_preservation_required','runtime_environment_and_private_boundaries_preservation_required','existing_hashed_assets_preserved')
FALSE_FLAGS=('backend_changes','database_migration','database_writes','container_restarts','environment_changes','permissions_changes','dependencies_changes','content_security_policy_changes','publications_or_provider_writes','credentials_included')
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

def validate_summary(summary):
    need(isinstance(PREFLIGHT_SHA,str) and summary['stage']=='MEDIA_META_MONTHLY_STATIC_PREFLIGHT_CAPTURED' and summary['sha256']==PREFLIGHT_SHA and summary['path']=='/opt/t24-crm/releases/media-meta-monthly-static-preflight-'+PREFLIGHT_SHA[:12]+'.json','EXACT_FRESH_MOBILE_PREFLIGHT_REQUIRED')
    need(summary['source_sha']==BASE_SOURCE and summary['frontend_version']==BASE_FRONTEND and summary['schema_revision']=='g32ed456e792' and summary['table_count']==162 and summary['backend_file_count']==420 and summary['all162_current_tables_preserved'] is True,'EXACT_LIVE162_SOURCE_AND_SCHEMA_REQUIRED')
    need(summary['crm']['id']=='1ee579193b73048fb1120f516d53d2400191c2499cfad5284184ca0506ed698e' and summary['crm']['image']=='sha256:05dc7e8e8ce620e0d92e07e95d304537250d17beb14dbeb63713e06d2319bf41' and summary['content_security_policy_sha256']=='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6','EXACT_UNCHANGED_RUNTIME_AND_CSP_REQUIRED')
    need(all(summary[x] is False for x in ('schema_changed','permissions_changed','business_writes','provider_requests','credential_file_content_read','private_content_read','runtime_changed')),'READONLY_MOBILE_BASELINE_REQUIRED')

def build(summary,freeze_body,dist=None):
    validate_summary(summary)
    need(isinstance(APPLICATION_FREEZE_SHA,str) and H(freeze_body)==APPLICATION_FREEZE_SHA,'EXACT_PRIORITY_APPLICATION_FREEZE_REQUIRED')
    before=inventory(BASE_SOURCE);after=inventory(SOURCE)
    need(inventory('HEAD')==after,'HEAD_APPLICATION_TREE_DRIFT')
    changed={p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    need(changed==FILES and set(before)==set(after),'EXACT_COMPONENT_AND_TEST_DELTA_REQUIRED')
    need(all(H(local_bytes(ROOT/p))==sha for p,sha in after.items()),'LOCAL_COMMITTED_APPLICATION_DRIFT')
    expected={name for name in after if name.startswith('app/frontend/src/')}
    actual={str(path.relative_to(ROOT)) for path in (ROOT/'app/frontend/src').rglob('*') if path.is_file() or path.is_symlink()}
    need(actual==expected,'UNTRACKED_FRONTEND_SOURCE_REJECTED')
    need(frontend_version()==FRONTEND,'EXACT_FRONTEND_SOURCE_VERSION_REQUIRED')
    static=read_static(Path(dist) if dist else ROOT/'app/frontend/dist');dist_sha=static_inventory(static)
    need(strict_json(static['app-version.json'])=={'version':FRONTEND},'EXACT_FRONTEND_BUILD_REQUIRED')
    freeze=strict_json(freeze_body);changed_files={name:after[name] for name in sorted(FILES)}
    need(freeze['source_sha']==SOURCE and freeze['baseline_source_sha']==BASE_SOURCE and freeze['frontend_version']==FRONTEND and freeze['baseline_frontend_version']==BASE_FRONTEND and freeze['files']==changed_files and freeze['dist_inventory_sha256']==dist_sha,'EXACT_SOURCE_AND_QA_DIST_FREEZE_REQUIRED')
    need(all(freeze[x] is True for x in TRUE_FLAGS) and all(freeze[x] is False for x in FALSE_FLAGS),'EXACT_STATIC_PRESERVATION_FREEZE_REQUIRED')
    blob=deterministic_payload({'static/'+name:body for name,body in static.items()})
    manifest={'format_version':1,'stage':'MEDIA_META_MONTHLY_UI_STATIC_PAYLOAD','source_sha':SOURCE,'backend_source_sha':BASE_SOURCE,'baseline_source_sha':BASE_SOURCE,'frontend_version':FRONTEND,'baseline_frontend_version':BASE_FRONTEND,'schema_revision':'g32ed456e792','table_count':162,'preflight_sha256':PREFLIGHT_SHA,'application_freeze_sha256':APPLICATION_FREEZE_SHA,'payload_sha256':H(blob),'changed_source_files':changed_files,'protected_source_inventory':{name:sha for name,sha in before.items() if name not in FILES},'files':{'static/'+name:H(body) for name,body in sorted(static.items())},'dist_inventory_sha256':dist_sha,**{x:True for x in TRUE_FLAGS},**{x:False for x in FALSE_FLAGS}}
    need(read_static(Path(dist) if dist else ROOT/'app/frontend/dist')==static and frontend_version()==FRONTEND,'BUILD_CHANGED_DURING_PACKAGING')
    return blob,manifest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preflight-summary',type=Path,required=True);parser.add_argument('--application-freeze',type=Path,required=True);parser.add_argument('--out',type=Path,default=HERE/'artifacts');args=parser.parse_args()
    blob,manifest=build(strict_json(local_bytes(args.preflight_summary)),local_bytes(args.application_freeze));write_artifacts(blob,manifest,args.out)
    print(json.dumps({'manifest_sha256':H(encoded(manifest)),'payload_sha256':H(blob),'file_count':len(manifest['files']),'source_sha':SOURCE,'frontend_version':FRONTEND,'backend_changes':False,'database_writes':False,'runtime_restarts':False},sort_keys=True))

if __name__=='__main__':main()
