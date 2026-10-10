#!/usr/bin/env python3
"""Prepare an isolated private-workspace image and public static tree.

This does not recreate the CRM container, read credentials, access a database,
change Nginx, or start either private production service. Run only after exact
source/manifest approval. The existing CRM image and assets are preserved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import tarfile
import urllib.request
from uuid import uuid4

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BASE_SOURCE = '517c0138576ff2896b7bf442228540e95fd75791'
BASE_IMAGE = 'sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
BASE_ARCHIVE_SHA = 'f57c1fbda3b3637cf20d08e47616284003d43a902bc29a0322a1f70880422633'
BASE_RELEASE = Path('/opt/t24-crm/releases/sales-auth-517c013-20261011')
APP = Path('/opt/t24-crm/app')
RELEASES = Path('/opt/t24-crm/releases')
PUBLIC_RELEASES = Path('/opt/t24-crm/public-releases')
BACKEND_ADDITIONS = frozenset({
    'app/backend/dependencies/private_workspace.py',
    'app/backend/models/private_workspace.py',
    'app/backend/schemas/private_workspace.py',
    'app/backend/routers/private_workspace.py',
    'app/backend/services/private_workspace.py',
    'app/backend/services/private_workspace_providers.py',
    'app/backend/services/private_workspace_worker.py',
    'app/backend/services/private_workspace_app.py',
})
ALLOWED_CHANGES = BACKEND_ADDITIONS | frozenset({
    '.gitignore', 'PRIVATE_WORKSPACE.md',
    'app/backend/tests/test_private_workspace_core.py',
    'app/backend/tests/test_private_workspace_providers.py',
    'app/backend/tests/test_private_workspace_worker.py',
    'app/backend/tests/test_private_workspace_app.py',
    'app/frontend/src/App.tsx',
    'app/frontend/src/components/Layout.tsx',
    'app/frontend/src/components/PrivateWorkspaceEntry.tsx',
    'app/frontend/src/lib/private-workspace-api.ts',
    'app/frontend/src/lib/private-workspace-access.ts',
    'app/frontend/src/components/MobileMorePage.tsx',
    'app/frontend/src/pages/PrivateWorkspace.tsx',
    'app/frontend/src/pages/private-workspace.css',
    'app/frontend/tests/private-workspace-api.test.mjs',
})
HASH = re.compile(r'[a-f0-9]{64}')
SCAN_BACKEND = """import hashlib,json,pathlib
r=pathlib.Path('/app/backend'); out={}
for p in sorted(r.rglob('*')):
    rel=p.relative_to(r)
    if {'data','logs','private-data','__pycache__'}.intersection(rel.parts) or p.suffix in ('.pyc','.pyo') or p.name.startswith('.env'):continue
    assert not p.is_symlink(),'BACKEND_SYMLINK'
    if p.is_file():out[rel.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
assert out
print(json.dumps(out,sort_keys=True))
"""
SCAN_PACKAGES = "import importlib.metadata,json; print(json.dumps({d.metadata['Name'].lower():d.version for d in importlib.metadata.distributions()},sort_keys=True))"
SCAN_PACKAGE_BYTES = """import hashlib,json,pathlib,sysconfig
h=hashlib.sha256(); count=0
for label in ('purelib','scripts'):
    root=pathlib.Path(sysconfig.get_path(label))
    for p in sorted(root.rglob('*')):
        if p.is_file():
            b=p.read_bytes(); name=label+'/'+p.relative_to(root).as_posix()
            h.update(json.dumps([name,len(b),hashlib.sha256(b).hexdigest()],separators=(',',':')).encode());count+=1
assert count>100
print(json.dumps({'files':count,'sha256':h.hexdigest()},sort_keys=True))
"""
SCAN_DIST = """import hashlib,json,pathlib
r=pathlib.Path('/app/frontend/dist'); out={}
for p in sorted(r.rglob('*')):
    assert not p.is_symlink(),'DIST_SYMLINK'
    if p.is_file():out[p.relative_to(r).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
assert 'index.html' in out and 'app-version.json' in out
print(json.dumps(out,sort_keys=True))
"""


class PrepareError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise PrepareError(code)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for part in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def private_file(path):
    require(path.is_file() and not path.is_symlink() and path.resolve() == path and
            path.stat().st_uid == 0 and not path.stat().st_mode & 0o077, 'PRIVATE_INPUT_UNTRUSTED')
    return path


def trusted_parent(path, allow_public=False):
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path and
            path.stat().st_uid == 0 and not path.stat().st_mode & 0o022, 'OUTPUT_PARENT_UNTRUSTED')
    if not allow_public:
        require(path == RELEASES, 'RELEASE_PARENT_SCOPE')


def write(path, blob):
    require(not path.exists() and not path.is_symlink(), 'NEW_OUTPUT_REQUIRED')
    with path.open('xb') as target:
        target.write(blob)
        target.flush()
        os.fsync(target.fileno())
    path.chmod(0o600)


def write_json(path, value):
    write(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def run(stage, command, directory, timeout=120, cwd=None):
    print('PRIVATE_CANDIDATE_STAGE '+stage,flush=True)
    result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=timeout)
    # Commands never receive secrets. Do not use docker inspect output as a logged command.
    write(directory / (stage + '.log'), (result.stdout + '\n' + result.stderr).encode())
    require(result.returncode == 0, stage.upper().replace('-', '_') + '_FAILED')
    return result.stdout.strip()


def crm_identity():
    result = subprocess.run(['docker', 'inspect', 't24-crm'], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=30)
    require(result.returncode == 0, 'CRM_INSPECTION_FAILED')
    info = json.loads(result.stdout)[0]
    labels = info['Config'].get('Labels') or {}
    require(info['Image'] == BASE_IMAGE and info['State']['Running'] and
            info['State'].get('Health', {}).get('Status') == 'healthy', 'ACCEPTED_CRM_RUNTIME_REQUIRED')
    require(labels.get('t24.source.sha') == BASE_SOURCE and
            labels.get('com.docker.compose.service') == 'crm' and
            labels.get('com.docker.compose.project.working_dir') == str(APP) and
            labels.get('com.docker.compose.project.config_files') ==
            str(APP / 'docker-compose.yml') + ',' + str(BASE_RELEASE / 'compose-new.json'), 'CRM_COMPOSE_IDENTITY_DRIFT')
    expected_mounts = {(str(APP / 'data'), '/app/backend/data', 'bind', True),
                       (str(APP / 'logs'), '/app/backend/logs', 'bind', True)}
    require({(m['Source'], m['Destination'], m['Type'], m['RW']) for m in info['Mounts']} == expected_mounts,
            'CRM_MOUNTS_DRIFT')
    require(info['HostConfig']['PortBindings'] == {'8000/tcp': [{'HostIp':'127.0.0.1','HostPort':'8000'}]},
            'CRM_PORT_DRIFT')
    # Hash the captured environment/config rather than saving or displaying it.
    identity = {'container_id': info['Id'], 'image_id': info['Image'],
                'started_at': info['State']['StartedAt'],
                'configuration_sha256': digest({'Config':info['Config'], 'HostConfig':info['HostConfig'], 'Mounts':info['Mounts']})}
    return identity


def archive_files(archive, source_sha, target=None):
    prefix = 't24-crm-' + source_sha + '/'
    output = {}
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        require(len(members) < 20000, 'ARCHIVE_MEMBER_LIMIT')
        total = 0
        for member in members:
            require(member.name == prefix[:-1] or member.name.startswith(prefix), 'ARCHIVE_PREFIX_DRIFT')
            relative = member.name[len(prefix):]
            if not relative:
                require(member.isdir(), 'ARCHIVE_ROOT_TYPE')
                continue
            pure = PurePosixPath(relative)
            require(not pure.is_absolute() and '..' not in pure.parts and str(pure) == relative.rstrip('/'),
                    'ARCHIVE_PATH_UNSAFE')
            require(member.isdir() or member.isfile(), 'ARCHIVE_SPECIAL_FILE_FORBIDDEN')
            if member.isdir():
                continue
            require(relative not in output and member.size <= 32 * 1024**2, 'ARCHIVE_DUPLICATE_OR_FILE_LIMIT')
            total += member.size
            require(total <= 256 * 1024**2, 'ARCHIVE_TOTAL_LIMIT')
            blob = source.extractfile(member).read()
            require(len(blob) == member.size, 'ARCHIVE_FILE_TRUNCATED')
            output[relative] = hashlib.sha256(blob).hexdigest()
            if target is not None:
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                write(path, blob)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
    require(output, 'SOURCE_ARCHIVE_EMPTY')
    return output


def checked_manifest(spec, args, before, after):
    require(spec.get('source_sha') == args.source_sha and spec.get('archive_sha256') == args.archive_sha256,
            'SOURCE_MANIFEST_IDENTITY_DRIFT')
    require(spec.get('baseline_source_sha', BASE_SOURCE) == BASE_SOURCE and
            spec.get('baseline_image_id', BASE_IMAGE) == BASE_IMAGE, 'BASELINE_MANIFEST_DRIFT')
    require(spec.get('local_verification_passed') is True and
            re.fullmatch(r'[a-f0-9]{12}', spec.get('frontend_version', '')) is not None, 'LOCAL_VERIFICATION_REQUIRED')
    require(spec.get('source_file_sha256') == after and all(HASH.fullmatch(v) for v in after.values()),
            'FULL_SOURCE_MANIFEST_DRIFT')
    changes = {name:{'before_sha256':before.get(name), 'after_sha256':after.get(name)}
               for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)}
    require(changes == spec.get('changed_file_sha256') and set(changes) <= ALLOWED_CHANGES,
            'SOURCE_CHANGES_OUTSIDE_REVIEWED_ALLOWLIST')
    require(all(value['after_sha256'] is not None for value in changes.values()), 'SOURCE_DELETION_FORBIDDEN')
    require(set(spec.get('backend_runtime_added_files', [])) == BACKEND_ADDITIONS and
            len(spec['backend_runtime_added_files']) == len(BACKEND_ADDITIONS), 'BACKEND_ADDITION_SET_DRIFT')
    require(all(name not in before and name in after for name in BACKEND_ADDITIONS), 'BACKEND_ADDITIONS_MUST_BE_NEW')
    require(all(before.get(name) == after.get(name) for name in before if name.startswith('app/backend/')),
            'EXISTING_BACKEND_SOURCE_CHANGED')
    require(not any(name in changes for name in ('app/Dockerfile','app/.dockerignore','app/docker-compose.yml')),
            'BUILD_OR_COMPOSE_INPUT_CHANGED')
    return changes


def image_scan(stage, image, code, directory):
    return json.loads(run(stage, ['docker','run','--rm','--network','none','--read-only',
                                 '--entrypoint','python',image,'-c',code], directory))


def file_manifest(root):
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'PUBLIC_SYMLINK_FORBIDDEN')
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            require(not any(part.startswith('.') for part in Path(relative).parts), 'HIDDEN_PUBLIC_FILE_FORBIDDEN')
            require(path.suffix.lower() in {'.html','.js','.css','.json','.png','.jpg','.jpeg','.webp','.gif',
                                           '.svg','.ico','.txt','.woff','.woff2','.ttf','.webmanifest'}, 'NON_STATIC_PUBLIC_FILE_FORBIDDEN')
            require(path.suffix != '.html' or relative in {'index.html','offline.html'}, 'UNEXPECTED_PUBLIC_HTML')
            result[relative] = sha(path)
    require('index.html' in result and 'app-version.json' in result, 'PUBLIC_DIST_INCOMPLETE')
    return result


def current_graph(root, version):
    index = (root / 'index.html').read_text()
    start = re.findall(r'(?:src|href)=["\'](/assets/[A-Za-z0-9_.-]+\.(?:js|css))["\']', index)
    require(start and any(name.endswith('.js') for name in start), 'CURRENT_ENTRY_REQUIRED')
    graph = {}
    pending = [name.lstrip('/') for name in start]
    pattern = re.compile(r'["\'](?:(?:\./|/assets/|assets/))?([A-Za-z0-9_-]+\.(?:js|css))["\']')
    while pending:
        name = pending.pop()
        if name in graph:
            continue
        path = root / name
        require(path.is_file() and not path.is_symlink(), 'CURRENT_ASSET_MISSING')
        body = path.read_text()
        graph[name] = sha(path)
        if name.endswith('.js'):
            for referenced in pattern.findall(body):
                require((root / 'assets' / referenced).is_file(), 'REFERENCED_CURRENT_ASSET_MISSING')
                pending.append('assets/' + referenced)
    modules = sorted(name for name in graph if name.startswith('assets/PrivateWorkspace-') and name.endswith('.js'))
    require(len(modules) == 1, 'CURRENT_PRIVATE_WORKSPACE_MODULE_REQUIRED')
    combined = '\n'.join((root/name).read_text() for name in graph if name.endswith('.js'))
    require(version in combined and '/private-workspace' in combined and
            '私人工作空间' in combined and '/api/v1/private-workspace' in combined, 'CURRENT_PRIVATE_UI_MARKERS_REQUIRED')
    require(json.loads((root / 'app-version.json').read_text()) == {'version':version}, 'FRONTEND_VERSION_DRIFT')
    return {'version':version, 'index_sha256':sha(root/'index.html'),
            'assets':{'/'+name:value for name,value in sorted(graph.items())},
            'private_workspace_module':'/'+modules[0], 'current_entry_graph_only':True,
            'current_asset_count':len(graph)}



REGRESSION_TESTS = ('test_private_workspace_core.py', 'test_private_workspace_providers.py',
                    'test_private_workspace_worker.py', 'test_private_workspace_app.py')
TEST_TOOLS = {'pytest':'8.4.2', 'pytest-asyncio':'1.2.0', 'iniconfig':'2.3.1', 'pluggy':'1.6.0',
              'pygments':'2.21.0', 'packaging':'26.3', 'tomli':'2.2.1', 'exceptiongroup':'1.3.0',
              'backports.asyncio.runner':'1.2.0'}


def test_container(stage, image, command, directory, timeout=600):
    token = uuid4().hex
    name = 't24-private-tests-' + token[:12]
    complete = ['docker','run','--rm','--name',name,'--label','t24.private.tests='+token,*command]
    try:
        return run(stage, complete, directory, timeout)
    finally:
        status = subprocess.run(['docker','inspect',name], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=30)
        if status.returncode == 0:
            info = json.loads(status.stdout)[0]
            require(info['Image'] == image and info['Config'].get('Labels',{}).get('t24.private.tests') == token,
                    'TEST_CONTAINER_CLEANUP_IDENTITY_DRIFT')
            run(stage+'-cleanup',['docker','rm','-f',name],directory)


def candidate_regressions(directory, image, packages):
    test_root = directory/'source/app/backend/tests'
    require(all((test_root/name).is_file() and not (test_root/name).is_symlink() for name in REGRESSION_TESTS)
            and (test_root/'conftest.py').is_file(), 'EXACT_SOURCE_TESTS_REQUIRED')
    normalized = {re.sub(r'[-_.]+','-',name.lower()):version for name,version in packages.items()}
    missing = [name+'=='+version for name,version in TEST_TOOLS.items()
               if re.sub(r'[-_.]+','-',name.lower()) not in normalized]
    wheels = directory/'test-wheels'
    wheels.mkdir(mode=0o700)
    if missing:
        # Download pinned tools separately. The regression container itself has no network.
        code = "import subprocess,sys; assert sys.version_info[:2]==(3,10); subprocess.check_call([sys.executable,'-m','pip','download','--disable-pip-version-check','--no-cache-dir','--only-binary=:all:','--no-deps','--dest','/test-wheels',*"+repr(missing)+"])"
        test_container('test-tools-download',image,
            ['--network','bridge','--read-only','--tmpfs','/tmp:rw,nosuid,size=256m',
             '--mount','type=bind,src='+str(wheels)+',dst=/test-wheels',
             '--entrypoint','python',image,'-c',code],directory,600)
    wheel_proof = {}
    for path in sorted(wheels.iterdir()):
        require(path.is_file() and not path.is_symlink() and path.suffix == '.whl', 'PINNED_TEST_WHEEL_REQUIRED')
        wheel_proof[path.name] = sha(path)
    require(not missing or wheel_proof, 'TEST_TOOLS_DOWNLOAD_EMPTY')
    write_json(directory/'test-wheel-manifest.json',wheel_proof)
    result_path = directory/'test-results'
    result_path.mkdir(mode=0o700)
    code = """import os,subprocess,sys,json,pathlib
os.environ['APP_ENV']='test';os.environ['ENVIRONMENT']='test'
os.environ['DATABASE_URL']='sqlite+aiosqlite:////tmp/private-business-fixture.db'
os.environ['DATABASE_SCHEMA_MODE']='verify_only'
os.environ['PRIVATE_WORKSPACE_DATABASE_URL']='sqlite+aiosqlite:////tmp/private-fixture/workspace.db'
os.environ['AUTOMATION_SCAN_ENABLED']='false';os.environ['ENABLE_DEFAULT_EMPLOYEE_ADMIN']='false'
os.environ['ENFORCE_EMPLOYEE_STATUS']='false';os.environ['ENFORCE_EMPLOYEE_SESSIONS']='false'
if MISSING:
    subprocess.check_call([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-cache-dir',
                           '--no-index','--find-links','/test-wheels','--target','/tmp/test-deps','--no-deps',*MISSING])
os.environ['PYTHONPATH']='/tmp/test-deps:/app:/app/backend'
args=[sys.executable,'-m','pytest',*[str(pathlib.Path('/app/backend/tests')/name) for name in TESTS],
      '-q','--disable-warnings','--tb=short','-p','no:cacheprovider','--junitxml=/test-results/regressions.xml']
subprocess.check_call(args,cwd='/app/backend')
import xml.etree.ElementTree as ET
suites=list(ET.parse('/test-results/regressions.xml').getroot().iter('testsuite'))
assert suites and sum(int(s.get('tests','0')) for s in suites)>=77
assert all(int(s.get('failures','0'))==0 and int(s.get('errors','0'))==0 and int(s.get('skipped','0'))==0 for s in suites)
print(json.dumps({'stage':'PRIVATE_CANDIDATE_REGRESSIONS_PASSED','tests':sum(int(s.get('tests','0')) for s in suites),
                  'source_test_files':list(TESTS),'actual_candidate_image_tested':True,
                  'network':'none','production_env_loaded':False,'production_database_access':False,
                  'test_only_packages_in_tmpfs':True},sort_keys=True))
""".replace('MISSING',repr(missing)).replace('TESTS',repr(REGRESSION_TESTS))
    result = test_container('candidate-regressions',image,
        ['--network','none','--read-only','--tmpfs','/tmp:rw,nosuid,size=384m',
         '--tmpfs','/app/backend/logs:rw,nosuid,noexec,size=16m',
         '--env','PYTHONDONTWRITEBYTECODE=1','--env','TZ=Asia/Shanghai',
         '--mount','type=bind,src='+str(test_root)+',dst=/app/backend/tests,readonly',
         '--mount','type=bind,src='+str(wheels)+',dst=/test-wheels,readonly',
         '--mount','type=bind,src='+str(result_path)+',dst=/test-results',
         '--entrypoint','python',image,'-c',code],directory,600)
    report = json.loads(result.splitlines()[-1])
    write_json(directory/'candidate-runtime-regressions.json',report)
    return report


def prepare(args):
    require(os.geteuid() == 0 and socket.gethostname() == HOST, 'SERVER_IDENTITY_MISMATCH')
    os.umask(0o077)
    require(re.fullmatch(r'[a-f0-9]{40}',args.source_sha) is not None and
            HASH.fullmatch(args.archive_sha256) and HASH.fullmatch(args.manifest_sha256), 'RELEASE_HASH_SHAPE')
    name = 'private-workspace-' + args.source_sha[:7] + '-20261011'
    directory = RELEASES/name
    public = PUBLIC_RELEASES/name
    trusted_parent(RELEASES)
    require(directory.is_dir() and not directory.is_symlink() and directory.resolve() == directory and
            directory.stat().st_uid == 0 and not directory.stat().st_mode & 0o077, 'PRIVATE_RELEASE_DIRECTORY_REQUIRED')
    require(not public.exists() and not public.is_symlink(), 'NEW_PUBLIC_RELEASE_REQUIRED')
    require(not any((directory/part).exists() or (directory/part).is_symlink()
                    for part in ('source','source.tar.gz','candidate.json','static-dist')), 'NEW_PREPARATION_REQUIRED')
    manifest = private_file(directory/'release-spec.json')
    require(sha(manifest) == args.manifest_sha256, 'MANIFEST_HASH_DRIFT')
    spec = json.loads(manifest.read_text())
    baseline_archive = private_file(BASE_RELEASE/'source.tar.gz')
    require(sha(baseline_archive) == BASE_ARCHIVE_SHA, 'ACCEPTED_BASE_ARCHIVE_DRIFT')
    before_crm = crm_identity()
    write_json(directory/'crm-before-safe.json', before_crm)
    require(shutil.disk_usage(RELEASES).free > 4*1024**3, 'CANDIDATE_DISK_SPACE_REQUIRED')
    source_archive = directory/'source.tar.gz'
    with urllib.request.urlopen('https://codeload.github.com/billy285/t24-crm/tar.gz/'+args.source_sha,
                                timeout=60) as response:
        require(response.status == 200, 'EXACT_SOURCE_DOWNLOAD_FAILED')
        write(source_archive, response.read(256*1024**2+1))
    require(source_archive.stat().st_size <= 256*1024**2 and sha(source_archive) == args.archive_sha256,
            'EXACT_ARCHIVE_HASH_DRIFT')
    source = directory/'source'
    source.mkdir(mode=0o700)
    after = archive_files(source_archive,args.source_sha,source)
    before = archive_files(baseline_archive,BASE_SOURCE)
    changes = checked_manifest(spec,args,before,after)
    write_json(directory/'source-files.json',after)
    write_json(directory/'reviewed-changes.json',changes)
    base_backend = image_scan('base-backend',BASE_IMAGE,SCAN_BACKEND,directory)
    packages = image_scan('base-packages',BASE_IMAGE,SCAN_PACKAGES,directory)
    package_bytes = image_scan('base-package-bytes',BASE_IMAGE,SCAN_PACKAGE_BYTES,directory)
    base_dist = image_scan('base-dist',BASE_IMAGE,SCAN_DIST,directory)
    expected = dict(base_backend)
    for name in sorted(BACKEND_ADDITIONS):
        relative = name[len('app/backend/'):]
        require(relative not in expected, 'PRIVATE_BACKEND_ALREADY_IN_BASE')
        expected[relative] = after[name]
    write_json(directory/'expected-runtime-backend.json',expected)
    tag = 't24-crm:'+name
    base_tag = tag+'-base'
    existing_tags = run('existing-tags',['docker','image','ls','--format','{{.Repository}}:{{.Tag}}'],directory).splitlines()
    require(tag not in existing_tags and base_tag not in existing_tags, 'CANDIDATE_TAG_ALREADY_EXISTS')
    run('base-pin',['docker','tag',BASE_IMAGE,base_tag],directory)
    require(run('base-pin-proof',['docker','image','inspect','-f','{{.Id}}',base_tag],directory) == BASE_IMAGE,
            'BASE_PIN_DRIFT')
    # Exact existing Dockerfile frontend stage, official Node 22 and fixed pnpm 11.16.0.
    original = (source/'app/Dockerfile').read_text()
    require(original.count('FROM python:') == 1 and
            original.startswith('# syntax=docker/dockerfile:1\n') and
            'FROM node:22-bookworm-slim AS frontend-builder' in original and
            'corepack prepare pnpm@11.16.0 --activate' in original and
            'pnpm install --frozen-lockfile' in original, 'REVIEWED_FRONTEND_BUILD_SHAPE_DRIFT')
    recipe = original.split('FROM python:',1)[0] + 'FROM '+base_tag+'\n'
    for name in sorted(BACKEND_ADDITIONS):
        relative = name[len('app/'):]
        recipe += 'COPY '+relative+' /app/'+relative+'\n'
    recipe += 'COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist\n'
    recipe += 'LABEL t24.source.sha="'+args.source_sha+'"\n'
    recipe_path = directory/'Dockerfile.private'
    write(recipe_path,recipe.encode())
    print('PRIVATE_WORKSPACE_CANDIDATE_BUILD_STARTED',flush=True)
    run('candidate-build',['docker','build','-f',str(recipe_path),'-t',tag,'.'],directory,1800,source/'app')
    image = run('candidate-image',['docker','image','inspect','-f','{{.Id}}',tag],directory)
    require(re.fullmatch(r'sha256:[a-f0-9]{64}',image) and image != BASE_IMAGE, 'IMMUTABLE_CANDIDATE_REQUIRED')
    require(run('candidate-source',['docker','image','inspect','-f','{{index .Config.Labels "t24.source.sha"}}',image],directory) == args.source_sha,
            'CANDIDATE_SOURCE_DRIFT')
    require(image_scan('candidate-backend',image,SCAN_BACKEND,directory) == expected, 'CANDIDATE_BACKEND_BYTES_DRIFT')
    require(image_scan('candidate-packages',image,SCAN_PACKAGES,directory) == packages, 'RUNTIME_DEPENDENCIES_CHANGED')
    require(image_scan('candidate-package-bytes',image,SCAN_PACKAGE_BYTES,directory) == package_bytes, 'RUNTIME_PACKAGE_BYTES_CHANGED')
    tests = candidate_regressions(directory,image,packages)
    dist = image_scan('candidate-dist',image,SCAN_DIST,directory)
    require(all(dist.get(name) == value for name,value in base_dist.items() if name.startswith('assets/')),
            'EXISTING_ASSET_BYTES_OVERWRITTEN_OR_MISSING')
    probe = 't24-private-export-'+uuid4().hex[:12]
    created = False
    try:
        run('export-create',['docker','create','--name',probe,'--network','none',
                             '--label','t24.private.prepare='+args.source_sha,'--entrypoint','/bin/true',image],directory)
        created = True
        run('export-dist',['docker','cp',probe+':/app/frontend/dist',str(directory/'static-dist')],directory)
    finally:
        if created:
            run('export-remove',['docker','rm',probe],directory)
    exported = file_manifest(directory/'static-dist')
    require(exported == dist, 'EXPORTED_DIST_BYTES_DRIFT')
    graph = current_graph(directory/'static-dist',spec['frontend_version'])
    write_json(directory/'candidate-current-assets.json',graph)
    write_json(directory/'candidate-public-files.json',{'/'+name:value for name,value in exported.items()})
    require(crm_identity() == before_crm, 'ORIGINAL_CRM_CONTAINER_CHANGED_DURING_PREPARATION')
    if not PUBLIC_RELEASES.exists():
        require(not PUBLIC_RELEASES.is_symlink(), 'PUBLIC_PARENT_SYMLINK')
        PUBLIC_RELEASES.mkdir(mode=0o755)
    trusted_parent(PUBLIC_RELEASES,allow_public=True)
    shutil.copytree(directory/'static-dist',public,symlinks=False)
    for path in [public,*public.rglob('*')]:
        require(not path.is_symlink() and path.stat().st_uid == 0, 'PUBLIC_TREE_OWNERSHIP_DRIFT')
        path.chmod(0o755 if path.is_dir() else 0o644)
    require(file_manifest(public) == exported, 'PUBLIC_DIST_BYTES_DRIFT')
    require(crm_identity() == before_crm, 'CRM_CONTAINER_CHANGED_DURING_EXPORT')
    result = {'stage':'PRIVATE_WORKSPACE_CANDIDATE_VERIFIED','source_sha':args.source_sha,
              'archive_sha256':args.archive_sha256,'release_spec_sha256':args.manifest_sha256,
              'baseline_source_sha':BASE_SOURCE,'base_image_id':BASE_IMAGE,'image_id':image,'image_tag':tag,
              'version':spec['frontend_version'],'release_directory':str(directory),'public_directory':str(public),
              'backend_added_files':sorted(BACKEND_ADDITIONS),'all_baseline_backend_bytes_identical':True,
              'backend_manifest_sha256':digest(expected),'runtime_dependencies_unchanged':True,
              'runtime_package_bytes_identical':True,'runtime_package_tree_sha256':package_bytes['sha256'],
              'candidate_runtime_regression_tests':tests['tests'],'candidate_runtime_tests_verified':True,
              'existing_assets_preserved':True,'existing_asset_count':sum(name.startswith('assets/') for name in base_dist),
              'public_files':len(exported),'public_manifest_sha256':sha(directory/'candidate-public-files.json'),
              'current_assets_proof_sha256':sha(directory/'candidate-current-assets.json'),
              'crm_container_id':before_crm['container_id'],'crm_container_unchanged':True,
              'production_database_accessed':False,'production_database_mutations_performed':False,
              'private_production_services_started':False,'nginx_modified':False,'deployment_performed':False}
    write_json(directory/'candidate.json',result)
    print(json.dumps(result,sort_keys=True),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    for name in ('source-sha','archive-sha256','manifest-sha256'):
        parser.add_argument('--'+name,required=True)
    arguments = parser.parse_args()
    if not arguments.execute:
        print(json.dumps({'stage':'PLAN_ONLY','source_sha':arguments.source_sha,
                          'production_actions_performed':False},sort_keys=True))
    else:
        try:
            prepare(arguments)
        except Exception as error:
            print('PRIVATE_CANDIDATE_FAILED:'+type(error).__name__,flush=True)
            raise
