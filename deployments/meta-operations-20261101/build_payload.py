"""Local-only immutable source/static/wheel packager; no fetch, install or deploy.

Source/FE/freeze pins are explicit inputs. This never edits release.py or Git.
The reviewed static inventory must be frozen after QA, before packaging.
"""
import argparse
import gzip
import hashlib
import importlib.util
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
spec = importlib.util.spec_from_file_location('meta_operations_build_scope', HERE / 'release.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
H = lambda body: hashlib.sha256(body).hexdigest()
NODE = '/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
PILLOW_SOURCE = 'https://pypi.org/pypi/Pillow/12.3.0/json'
TRUE_FLAGS = ('database_migration', 'existing_meta_environment_preserved', 'ops_environment_keys_absent')
FALSE_FLAGS = ('production_seed_rows', 'credentials_included', 'runtime_environment_changed', 'ops_feature_enabled', 'ops_execution_enabled', 'ops_scheduler_enabled')


def strict_json(body):
    def pairs(rows):
        result = {}
        for key,value in rows:
            r.need(key not in result, 'DUPLICATE_JSON_KEY_REJECTED'); result[key] = value
        return result
    def constant(value): raise RuntimeError('NONFINITE_JSON_VALUE_REJECTED')
    return json.loads(body, object_pairs_hook=pairs, parse_constant=constant)


def git(*args, maximum=160*1024**2):
    # No shell, remote command or user-controlled ref syntax is used.
    child = subprocess.Popen(['git', *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        body = child.stdout.read(maximum+1)
        r.need(len(body) <= maximum, 'BOUNDED_LOCAL_GIT_OUTPUT_REQUIRED')
        r.need(child.wait(timeout=60) == 0, 'LOCAL_COMMITTED_GIT_OBJECT_REQUIRED')
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
            r.need(item.name not in seen and not path.is_absolute() and str(path) == item.name.rstrip('/') and '..' not in path.parts and path.parts[0] == 'app', 'CANONICAL_UNIQUE_SOURCE_MEMBER_REQUIRED')
            seen.add(item.name)
            r.need(item.isdir() or item.isfile(), 'SOURCE_LINK_OR_SPECIAL_REJECTED')
            if item.isdir(): continue
            r.need(0 <= item.size <= 16*1024**2 and len(seen) <= 20000, 'BOUNDED_SOURCE_MEMBER_REQUIRED')
            total += item.size; r.need(total <= 128*1024**2, 'BOUNDED_APPLICATION_SOURCE_REQUIRED')
            stream = archive.extractfile(item); body = stream.read(item.size+1)
            r.need(len(body) == item.size, 'COMPLETE_COMMITTED_SOURCE_REQUIRED'); result[item.name] = H(body)
    r.need(bool(result), 'NONEMPTY_APPLICATION_SOURCE_REQUIRED')
    return result


def frontend_version():
    # This is the exact existing Vite sourceVersion algorithm, including the
    # Node localeCompare order. It does not build, install or contact a service.
    code = "const fs=require('node:fs'),p=require('node:path'),h=require('node:crypto').createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){const q=p.join(d,e.name);if(e.isSymbolicLink())throw Error('link');if(e.isDirectory())walk(q);else if(e.isFile()){h.update(p.relative(root,q));h.update(fs.readFileSync(q));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"
    value = subprocess.check_output([NODE,'-e',code,str(ROOT/'app/frontend/src')], cwd=ROOT).decode()
    r.need(re.fullmatch('[a-f0-9]{12}',value), 'EXACT_FRONTEND_SOURCE_VERSION_REQUIRED')
    return value


def static_path(name):
    path = Path(name); parts = path.parts
    if not parts or path.is_absolute() or str(path) != name or '\\' in name or any(part.startswith('.') for part in parts): return False
    if len(parts) == 1: return name in {'index.html','offline.html','app-version.json','manifest.webmanifest','robots.txt','sw.js','registerSW.js'} or path.suffix in {'.png','.svg','.ico'} or bool(re.fullmatch(r'workbox-[a-zA-Z0-9_-]+[.]js',name))
    return parts[0] == 'assets' and path.suffix in {'.js','.css','.png','.svg','.ico','.jpg','.jpeg','.webp','.avif','.gif','.woff','.woff2','.ttf','.eot'}


def read_static(dist):
    dist = Path(dist)
    r.need(dist.resolve() == dist.absolute() and dist.is_dir() and not dist.is_symlink(), 'CANONICAL_DIST_DIRECTORY_REQUIRED')
    result = {}; total = 0
    for path in sorted(dist.rglob('*')):
        row = path.lstat(); r.need(not path.is_symlink() and (stat.S_ISDIR(row.st_mode) or stat.S_ISREG(row.st_mode)), 'DIST_LINK_OR_SPECIAL_REJECTED')
        if path.is_dir(): continue
        name = str(path.relative_to(dist)); r.need(static_path(name), 'DIST_PATH_REJECTED')
        body = r.local_bytes(path); total += len(body)
        r.need(len(result) < 10000 and total < 64*1024**2 and body, 'BOUNDED_NONEMPTY_DIST_REQUIRED'); result[name] = body
    r.need({'index.html','app-version.json'} <= set(result), 'COMPLETE_DIST_REQUIRED')
    return result


def static_inventory(files): return r.digest({name:H(body) for name,body in files.items()})


def inspect_static(dist):
    files = read_static(dist); version = strict_json(files['app-version.json'])
    r.need(isinstance(version,dict) and set(version) == {'version'} and re.fullmatch('[a-f0-9]{12}',version.get('version','')), 'EXACT_DIST_VERSION_FORMAT_REQUIRED')
    return {'frontend_version':version['version'],'dist_inventory_sha256':static_inventory(files),'file_count':len(files),'total_bytes':sum(map(len,files.values())),'artifacts_written':False}


def inputs(source_sha, frontend, freeze_sha):
    r.need(isinstance(source_sha,str) and re.fullmatch('[a-f0-9]{40}',source_sha) and source_sha != '0'*40 and source_sha != r.BASE_SOURCE and
           isinstance(frontend,str) and re.fullmatch('[a-f0-9]{12}',frontend) and frontend != '0'*12 and
           isinstance(freeze_sha,str) and re.fullmatch('[a-f0-9]{64}',freeze_sha) and freeze_sha != '0'*64, 'EXPLICIT_FINAL_SOURCE_FRONTEND_FREEZE_REQUIRED')
    r.need(len(r.SOURCE_FILES) == 18 and len(r.BACKEND_FILES) == 9 and len(r.FRONTEND_FILES) == 5 and len(r.TEST_FILES) == 4 and len(r.NEW_TABLES) == 9 and isinstance(r.NEW_TABLE_SHAPES,dict) and set(r.NEW_TABLE_SHAPES) == r.NEW_TABLES, 'EXACT_REVIEWED_EIGHTEEN_FILE_NINE_TABLE_SCOPE_REQUIRED')
    for stored,given in ((r.SOURCE_SHA,source_sha),(r.FRONTEND,frontend),(r.APPLICATION_FREEZE_SHA,freeze_sha)):
        r.need(stored is None or stored == given, 'EXPLICIT_PINS_MUST_MATCH_RELEASE_PINS')
    r.need(git('rev-parse','--verify',source_sha+'^{commit}',maximum=100).decode().strip() == source_sha, 'EXACT_IMMUTABLE_SOURCE_COMMIT_REQUIRED')


def frozen_sources(path, sha, after, source_sha, frontend, dist_sha):
    body = r.local_bytes(Path(path),1048576); r.need(H(body) == sha, 'EXACT_APPLICATION_FREEZE_REQUIRED'); value = strict_json(body)
    r.need(value['source_sha'] == source_sha and value['frontend_version'] == frontend and value['baseline_source_sha'] == r.BASE_SOURCE and value['baseline_frontend_version'] == r.BASE_FRONTEND and
           value['schema_revision'] == r.NEW_REVISION and value['old_schema_revision'] == r.OLD_REVISION and value['dist_inventory_sha256'] == dist_sha, 'EXACT_SOURCE_SCHEMA_AND_QA_DIST_FREEZE_REQUIRED')
    rows = value['files']; r.need(isinstance(rows,dict) and set(rows) == r.SOURCE_FILES and all(isinstance(pin,str) and re.fullmatch('[a-f0-9]{64}',pin) and after.get(name) == pin for name,pin in rows.items()), 'FROZEN_APPLICATION_SOURCE_DRIFT')
    r.need(all(value[key] is True for key in TRUE_FLAGS) and all(value[key] is False for key in FALSE_FLAGS), 'EXACT_DISABLED_ADDITIVE_PRESERVATION_FREEZE_REQUIRED')


def deterministic_payload(files):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output,mode='wb',mtime=0,filename='') as compressed:
        with tarfile.open(fileobj=compressed,mode='w',format=tarfile.USTAR_FORMAT) as archive:
            for name,body in sorted(files.items()):
                item = tarfile.TarInfo(name); item.size = len(body); item.mode = 0o644; item.mtime = 0; item.uid = item.gid = 0; item.uname = item.gname = ''
                archive.addfile(item,io.BytesIO(body))
    blob = output.getvalue(); r.need(len(blob) <= 16*1024**2, 'BOUNDED_CARRIER_PAYLOAD_REQUIRED'); return blob


def build(summary, *, source_sha, frontend, freeze_path, freeze_sha, wheel_path, dist=None):
    inputs(source_sha,frontend,freeze_sha); r.validate_summary(summary)
    before,after = inventory(r.BASE_SOURCE),inventory(source_sha)
    r.need(inventory('HEAD') == after, 'HEAD_APPLICATION_TREE_DRIFT')
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    diff = git('diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',r.BASE_SOURCE,source_sha,'--','app/',maximum=1048576).decode().split('\0')
    diff = [name for name in diff if name]
    r.need(changed == r.SOURCE_FILES and set(diff) == changed and len(diff) == len(changed) and set(before) <= set(after), 'EXACT_EIGHTEEN_APPLICATION_DELTA_REQUIRED')
    for name,pin in after.items(): r.need(H(r.local_bytes(ROOT/name)) == pin, 'LOCAL_COMMITTED_APPLICATION_SOURCE_DRIFT')
    expected = {name for name in after if name.startswith('app/frontend/src/')}
    actual = {str(path.relative_to(ROOT)) for path in (ROOT/'app/frontend/src').rglob('*') if path.is_file() or path.is_symlink()}
    r.need(actual == expected, 'UNTRACKED_FRONTEND_SOURCE_REJECTED')
    backend_before = {name:before.get('app/backend/'+name) for name in sorted(r.BACKEND_FILES)}
    r.need(backend_before == {name:r.ORIGINAL_BACKEND_HASHES.get(name) for name in r.BACKEND_FILES}, 'EXACT_ACTUAL_BACKEND_BASELINE_REQUIRED')
    r.need(frontend_version() == frontend, 'FRONTEND_SOURCE_VERSION_DRIFT')
    dist = Path(dist) if dist is not None else ROOT/'app/frontend/dist'; static = read_static(dist); dist_sha = static_inventory(static)
    r.need(strict_json(static['app-version.json']) == {'version':frontend}, 'EXACT_FRONTEND_BUILD_REQUIRED')
    frozen_sources(freeze_path,freeze_sha,after,source_sha,frontend,dist_sha)
    wheel_path = Path(wheel_path)
    r.need(wheel_path.name == r.WHEEL, 'EXACT_OFFICIAL_WHEEL_FILENAME_REQUIRED')
    wheel = r.local_bytes(wheel_path,r.WHEEL_BYTES)
    r.need(len(wheel) == r.WHEEL_BYTES and H(wheel) == r.WHEEL_SHA, 'EXACT_OFFICIAL_PYPI_WHEEL_BYTES_REQUIRED')
    payload = {'backend/'+name:r.local_bytes(ROOT/'app/backend'/name) for name in r.BACKEND_FILES}
    r.need(all(H(payload['backend/'+name]) == after['app/backend/'+name] for name in r.BACKEND_FILES), 'FINAL_RUNTIME_SOURCE_HASH_DRIFT')
    payload.update({'static/'+name:body for name,body in static.items()}); payload[r.WHEEL_MEMBER] = wheel
    r.need(sum(map(len,payload.values())) < 100*1024**2 and all(0 < len(body) <= 16*1024**2 for body in payload.values()), 'BOUNDED_EXACT_RUNTIME_STATIC_WHEEL_PAYLOAD_REQUIRED')
    # Detect a concurrent edit/rebuild before returning the immutable buffers.
    r.need(read_static(dist) == static and frontend_version() == frontend and H(r.local_bytes(Path(freeze_path),1048576)) == freeze_sha, 'SOURCE_OR_QA_DIST_CHANGED_DURING_PACKAGING')
    blob = deterministic_payload(payload)
    manifest = {'format_version':1,'source_sha':source_sha,'frontend_version':frontend,'baseline_source_sha':r.BASE_SOURCE,'baseline_frontend_version':r.BASE_FRONTEND,
        'schema_revision':r.NEW_REVISION,'old_schema_revision':r.OLD_REVISION,'additive_tables':sorted(r.NEW_TABLES),'preflight_sha256':summary['sha256'],'payload_sha256':H(blob),
        'application_freeze_sha256':freeze_sha,'changed_source_files':sorted(changed),'backend_before':backend_before,'backend_after':{name:after['app/backend/'+name] for name in sorted(r.BACKEND_FILES)},
        'files':{name:H(body) for name,body in sorted(payload.items())},'dist_inventory_sha256':dist_sha,'pillow_wheel':{'filename':r.WHEEL,'sha256':r.WHEEL_SHA,'bytes':r.WHEEL_BYTES,'source':PILLOW_SOURCE},
        'protected_source_inventory':{name:pin for name,pin in before.items() if name not in changed},**{name:True for name in TRUE_FLAGS},**{name:False for name in FALSE_FLAGS}}
    return blob,manifest


def write_artifacts(blob, manifest, out):
    out = Path(out)
    r.need(out.absolute() == HERE/'artifacts' and out.resolve() == out.absolute() and not out.exists() and not out.is_symlink(), 'FRESH_EXACT_ARTIFACT_DIRECTORY_REQUIRED')
    identity = lambda row:(row.st_dev,row.st_ino,row.st_uid,row.st_gid,stat.S_IMODE(row.st_mode),stat.S_IFMT(row.st_mode))
    parent_before = HERE.lstat()
    r.need(HERE.resolve() == HERE and stat.S_ISDIR(parent_before.st_mode), 'CANONICAL_ARTIFACT_PARENT_REQUIRED')
    parent_fd = os.open(HERE,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    directory_fd = None
    try:
        parent_opened = os.fstat(parent_fd)
        r.need(identity(parent_before) == identity(parent_opened) == identity(HERE.lstat()), 'ARTIFACT_PARENT_OPEN_DRIFT')
        os.mkdir('artifacts',mode=0o700,dir_fd=parent_fd)
        before = os.stat('artifacts',dir_fd=parent_fd,follow_symlinks=False)
        r.need(stat.S_ISDIR(before.st_mode) and before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) == 0o700, 'OWNED_PRIVATE_ARTIFACT_DIRECTORY_REQUIRED')
        directory_fd = os.open('artifacts',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
        opened = os.fstat(directory_fd)
        def boundary():
            r.need(identity(parent_opened) == identity(os.fstat(parent_fd)) == identity(HERE.lstat()), 'ARTIFACT_PARENT_NAMESPACE_DRIFT')
            named = os.stat('artifacts',dir_fd=parent_fd,follow_symlinks=False)
            r.need(identity(before) == identity(opened) == identity(os.fstat(directory_fd)) == identity(named) == identity(out.lstat()), 'ARTIFACT_DIRECTORY_NAMESPACE_DRIFT')
        boundary(); r.need(os.listdir(directory_fd) == [], 'FRESH_EMPTY_ARTIFACT_DIRECTORY_REQUIRED')
        created = set()
        for name,body in (('payload.tar.gz',blob),('manifest.json',r.encoded(manifest))):
            boundary(); r.need(set(os.listdir(directory_fd)) == created, 'ARTIFACT_DIRECTORY_MEMBERS_DRIFT')
            fd = os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory_fd)
            with os.fdopen(fd,'wb') as stream:
                file_before = os.fstat(stream.fileno())
                r.need(stat.S_ISREG(file_before.st_mode) and file_before.st_uid == os.geteuid() and file_before.st_nlink == 1 and stat.S_IMODE(file_before.st_mode) == 0o600, 'OWNED_REGULAR_ARTIFACT_FILE_REQUIRED')
                boundary(); stream.write(body); stream.flush(); os.fsync(stream.fileno())
                file_after = os.fstat(stream.fileno()); named = os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
                r.need(identity(file_before) == identity(file_after) == identity(named) and file_after.st_nlink == named.st_nlink == 1 and file_after.st_size == len(body), 'ARTIFACT_FILE_NAMESPACE_DRIFT')
                boundary()
            created.add(name)
        boundary(); r.need(set(os.listdir(directory_fd)) == created, 'ARTIFACT_DIRECTORY_MEMBERS_DRIFT')
        os.fsync(directory_fd); os.fsync(parent_fd); boundary()
    finally:
        if directory_fd is not None: os.close(directory_fd)
        os.close(parent_fd)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--inspect-dist',action='store_true'); parser.add_argument('--dist',type=Path,default=ROOT/'app/frontend/dist')
    parser.add_argument('--source-sha');parser.add_argument('--frontend-version');parser.add_argument('--application-freeze',type=Path);parser.add_argument('--application-freeze-sha256')
    parser.add_argument('--preflight-summary',type=Path);parser.add_argument('--pillow-wheel',type=Path);parser.add_argument('--out',type=Path,default=HERE/'artifacts');a=parser.parse_args()
    if a.inspect_dist: print(json.dumps(inspect_static(a.dist),sort_keys=True)); return
    r.need(all(value is not None for value in (a.source_sha,a.frontend_version,a.application_freeze,a.application_freeze_sha256,a.preflight_summary,a.pillow_wheel)), 'EXPLICIT_FINAL_BUILD_INPUTS_REQUIRED')
    blob,manifest = build(strict_json(r.local_bytes(a.preflight_summary,1048576)),source_sha=a.source_sha,frontend=a.frontend_version,freeze_path=a.application_freeze,
                          freeze_sha=a.application_freeze_sha256,wheel_path=a.pillow_wheel,dist=a.dist)
    write_artifacts(blob,manifest,a.out)
    print(json.dumps({'source_sha':a.source_sha,'frontend_version':a.frontend_version,'payload_sha256':H(blob),'manifest_sha256':H(r.encoded(manifest)),
        'dist_inventory_sha256':manifest['dist_inventory_sha256'],'file_count':len(manifest['files']),'application_delta_count':18,'original_table_count':141,'new_table_count':150,
        'pillow_wheel_sha256':r.WHEEL_SHA,'network_requests':False,'git_changed':False,'deployment_performed':False},sort_keys=True))


if __name__ == '__main__': main()
