#!/usr/bin/env python3
"""Prepare a private-only Google Ads candidate. Does not change running services.

No production environment is loaded into candidate containers. No production
database is mounted into candidate containers. No deployment is performed here.
"""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import tarfile
from uuid import uuid4

SOURCE = 'd6fce1354595368c92ac1c2a78c52282bd31342b'
VERSION = 'e260d507da1d'
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BASE_IMAGE = 'sha256:42c26eaaa6f6aa847548d4f35abb822a43cd9e9c88629c3c711453d6c1fa0fc9'
CRM_IMAGE = 'sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
CRM_ID = 'ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26'
CRM_STARTED = '2026-10-10T17:19:07.948520307Z'
CRM_CONFIG = '2e5c793eae3c192963037652717f91b402d351372378350f44dc2294fa85bdc0'
PRIVATE_IDS = {'t24-private-api': 'e85e70c9a9d48124cc35aa7fc683d0fb151468f2beb5a929a052f316e7a90da3',
               't24-private-worker': '584ffcb43448651568cfd44a736bdf2ee6bf1e0adbf7bfd4778dcccf331193b4'}
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA = '901b91443b0c0c52b9c90568dc409cb853c226b746405a3e65e37a48ea2b4f7f'
BASELINE_SHA = '8437aa76648ee4b3c8ca69bb0ad55b613dfeb219b50e5b52a8af5fc72d971288'
PRIVATE_PROOFS = {
    'api': {'configuration_sha256': 'e42e6ed70b5dab839b8cb525c5450b312cbe216226d6e20ff75f972861e6b7e5', 'started_at': '2026-10-10T21:18:06.817432373Z'},
    'worker': {'configuration_sha256': '05fb633760db0409ca63d11de060b87224cd12dc694236cd1e56bef1b64a010f', 'started_at': '2026-10-10T21:18:12.498761287Z'},
}
RELEASE = Path('/opt/t24-crm/releases/google-ads-d6fce13-20261011')
PUBLIC = Path('/var/www/t24-crm-public/google-ads-d6fce13-20261011')
OLD_PUBLIC = Path('/var/www/t24-crm-public/gmail-responsive-e23fc05-20261011')
OLD_RELEASE = Path('/opt/t24-crm/releases/private-workspace-1a4c952-20261011-retry2')
BACKEND = ('services/private_workspace.py', 'services/private_workspace_providers.py')
NEW_BACKEND = ()
MIN_TESTS = 159  # Root confirmed the combined reviewed private suite count.
TESTS = ('test_private_workspace_core.py', 'test_private_workspace_providers.py',
         'test_private_workspace_worker.py', 'test_private_workspace_app.py', 'test_private_mail_relevance.py')
STATIC_SUFFIXES = {'.html', '.js', '.css', '.json', '.png', '.jpg', '.jpeg', '.webp', '.gif',
                   '.svg', '.ico', '.txt', '.woff', '.woff2', '.ttf', '.webmanifest'}
TEST_TOOLS = {'pytest': '8.4.2', 'pytest-asyncio': '1.2.0', 'iniconfig': '2.3.1', 'pluggy': '1.6.0',
              'pygments': '2.21.0', 'packaging': '26.3', 'tomli': '2.2.1', 'exceptiongroup': '1.3.0',
              'backports.asyncio.runner': '1.2.0'}
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


def need(value, code):
    if not value:
        raise RuntimeError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected(path, directory=False):
    need(path.exists() and not path.is_symlink() and path.resolve() == path and
         path.stat().st_uid == 0 and not path.stat().st_mode & 0o077 and
         (path.is_dir() if directory else path.is_file()), 'PROTECTED_PATH_REQUIRED')


def write(path, blob):
    need(not path.exists() and not path.is_symlink(), 'NEW_EVIDENCE_REQUIRED')
    with path.open('xb') as target:
        target.write(blob)
        target.flush()
        os.fsync(target.fileno())
    path.chmod(0o600)


def save(path, value):
    write(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def inspect(name):
    result = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True, timeout=30)
    need(result.returncode == 0, 'CONTAINER_INSPECT_FAILED')
    return json.loads(result.stdout)[0]


def readonly_baseline():
    path = RELEASE / 'readonly-baseline.json'
    protected(path)
    need(path.stat().st_nlink == 1 and path.stat().st_size <= 2 * 1024**2 and sha(path) == BASELINE_SHA,
         'READONLY_BASELINE_RECEIPT_DRIFT')
    value = json.loads(path.read_bytes())
    need(value['stage'] == 'GOOGLE_ADS_READONLY_BASELINE_VERIFIED' and value['mutation_performed'] is False and
         value['nginx_sha256'] == NGINX_SHA and value['static_root'] == str(OLD_PUBLIC) and
         value['env_sha256'] == '6ebb9e3e1e947106bc8c25bdba782d631f5fd8c83ab1487120f5b16420470296' and
         value['business_tables_verified'] == 83, 'READONLY_BASELINE_PROOF_DRIFT')
    for role, proof in PRIVATE_PROOFS.items():
        actual = value['private']['t24-private-' + role]
        need(actual['id'] == PRIVATE_IDS['t24-private-' + role] and actual['image'] == BASE_IMAGE and
             actual['configuration_sha256'] == proof['configuration_sha256'] and
             actual['started_at'] == proof['started_at'] and actual['restart_count'] == 0,
             'READONLY_PRIVATE_PROOF_DRIFT')
    return value


def baseline():
    readonly_baseline()
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'SERVER_IDENTITY_DRIFT')
    crm = inspect('t24-crm')
    need(crm['Id'] == CRM_ID and crm['Image'] == CRM_IMAGE and
         crm['State']['StartedAt'] == CRM_STARTED and crm['State']['Running'] and
         crm['State'].get('Health', {}).get('Status') == 'healthy', 'CRM_BASELINE_DRIFT')
    variants = [digest({'Config': crm['Config'], 'HostConfig': crm['HostConfig'], 'Mounts': list(order)})
                for order in itertools.permutations(crm['Mounts'])]
    need(len(crm['Mounts']) == 2 and CRM_CONFIG in variants, 'CRM_CONFIGURATION_DRIFT')
    need(NGINX.is_file() and NGINX.resolve() == NGINX and not NGINX.is_symlink() and sha(NGINX) == NGINX_SHA,
         'NGINX_BASELINE_DRIFT')
    private = {}
    for name, identity in PRIVATE_IDS.items():
        info = inspect(name)
        need(info['Id'] == identity and info['Image'] == BASE_IMAGE and info['State']['Running'] and
             not info['State'].get('Restarting') and not info['State'].get('Dead'), 'PRIVATE_RUNTIME_DRIFT')
        role = name.removeprefix('t24-private-')
        need(info['State']['StartedAt'] == PRIVATE_PROOFS[role]['started_at'] and info.get('RestartCount') == 0 and
             digest({'Config': info['Config'], 'HostConfig': info['HostConfig'], 'Mounts': sorted(info['Mounts'], key=digest)}) ==
             PRIVATE_PROOFS[role]['configuration_sha256'], 'PINNED_PRIVATE_CONFIGURATION_DRIFT')
        private[name] = {'id': identity, 'started_at': info['State']['StartedAt'],
                         'configuration_sha256': digest({'Config': info['Config'], 'HostConfig': info['HostConfig'],
                                                         'Mounts': sorted(info['Mounts'], key=digest)})}
    return {'crm_container_id': CRM_ID, 'crm_image_id': CRM_IMAGE, 'crm_started_at': CRM_STARTED,
            'crm_configuration_sha256': CRM_CONFIG, 'nginx_sha256': NGINX_SHA, 'private': private}


def run(stage, command, timeout=120, cwd=None):
    print('GOOGLE_ADS_CANDIDATE_STAGE ' + stage, flush=True)
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    write(RELEASE / (stage + '.log'), (result.stdout + '\n' + result.stderr).encode())
    need(result.returncode == 0, stage.upper().replace('-', '_') + '_FAILED')
    return result.stdout.strip()


def isolated(stage, image, arguments, timeout=600):
    # Test containers are never given production env or production mount paths.
    token = uuid4().hex
    name = 't24-google-ads-check-' + token[:12]
    command = ['docker', 'run', '--rm', '--name', name, '--label', 't24.google_ads.check=' + token,
               '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--no-healthcheck', *arguments]
    try:
        return run(stage, command, timeout)
    finally:
        status = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True, timeout=30)
        if status.returncode == 0:
            info = json.loads(status.stdout)[0]
            need(info['Image'] == image and info['Config'].get('Labels', {}).get('t24.google_ads.check') == token,
                 'CHECK_CONTAINER_CLEANUP_IDENTITY_DRIFT')
            run(stage + '-cleanup', ['docker', 'rm', '-f', name])


def scan(stage, image, code):
    return json.loads(isolated(stage, image, ['--entrypoint', 'python', image, '-c', code]))


def file_map(root, static=False):
    result = {}
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink(), 'FILE_TREE_SYMLINK_FORBIDDEN')
        if path.is_dir():
            continue
        relative = path.relative_to(root)
        need(path.is_file() and not any(part.startswith('.') for part in relative.parts), 'HIDDEN_OR_SPECIAL_FILE')
        if static:
            need(path.suffix in STATIC_SUFFIXES and
                 (path.suffix != '.html' or relative.as_posix() in {'index.html', 'offline.html'}),
                 'NON_STATIC_PUBLIC_FILE_FORBIDDEN')
        result[relative.as_posix()] = sha(path)
    return result


def extract(archive, manifest):
    root = RELEASE / 'payload'
    need(not root.exists() and not root.is_symlink(), 'NEW_PAYLOAD_DIRECTORY_REQUIRED')
    root.mkdir(mode=0o700)
    entries = {}
    total = 0
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream:
            need(member.isfile() and member.name.startswith('payload/'), 'ONLY_REGULAR_PAYLOAD_FILES_ALLOWED')
            name = member.name.removeprefix('payload/')
            relative = PurePosixPath(name)
            need(relative.as_posix() == name and not relative.is_absolute() and '..' not in relative.parts and
                 not any(part.startswith('.') for part in relative.parts), 'PAYLOAD_PATH_INVALID')
            need(name not in entries and name in manifest['payload_files'] and member.size <= 16 * 1024**2,
                 'PAYLOAD_ALLOWLIST_OR_SIZE_DRIFT')
            total += member.size
            need(total < 64 * 1024**2, 'PAYLOAD_TOTAL_LIMIT')
            blob = stream.extractfile(member).read()
            need(len(blob) == member.size and hashlib.sha256(blob).hexdigest() == manifest['payload_files'][name],
                 'PAYLOAD_FILE_HASH_DRIFT')
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write(target, blob)
            entries[name] = sha(target)
    need(entries == manifest['payload_files'], 'PAYLOAD_MANIFEST_INCOMPLETE')
    allowed_source = {'backend/' + path for path in BACKEND} | {'backend/tests/' + name for name in (*TESTS, 'conftest.py')}
    need({name for name in entries if not name.startswith('frontend/dist/')} == allowed_source,
         'BACKEND_OR_TEST_PAYLOAD_SCOPE_DRIFT')
    need(all(name.startswith('frontend/dist/') or name in allowed_source for name in entries), 'PAYLOAD_SCOPE_DRIFT')
    file_map(root / 'frontend/dist', True)
    need(json.loads((root / 'frontend/dist/app-version.json').read_text()) == {'version': VERSION},
         'PAYLOAD_FRONTEND_VERSION_DRIFT')
    return root


def public_tree(payload):
    for path in (Path('/var'), Path('/var/www'), PUBLIC.parent, OLD_PUBLIC):
        need(path.is_dir() and not path.is_symlink() and path.resolve() == path and path.stat().st_uid == 0 and
             not path.stat().st_mode & 0o022 and path.stat().st_mode & 0o005 == 0o005, 'PUBLIC_ANCESTOR_UNTRUSTED')
    need(not PUBLIC.exists() and not PUBLIC.is_symlink(), 'NEW_PUBLIC_DIRECTORY_REQUIRED')
    old_map = file_map(OLD_PUBLIC, True)
    current_map = file_map(payload / 'frontend/dist', True)
    # Keep prior hashed assets for already-open browser tabs, without replacing current entry/version.
    desired = dict(current_map)
    for name, value in old_map.items():
        if name.startswith('assets/'):
            need(name not in desired or desired[name] == value, 'HASHED_ASSET_NAME_COLLISION')
            desired.setdefault(name, value)
    create_public_root(PUBLIC)
    for name in sorted(desired):
        source = payload / 'frontend/dist' / name if name in current_map else OLD_PUBLIC / name
        destination = PUBLIC / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        destination.write_bytes(source.read_bytes())
        destination.chmod(0o644)
    for path in PUBLIC.rglob('*'):
        if path.is_dir():
            path.chmod(0o755)
    need(file_map(PUBLIC, True) == desired, 'PUBLIC_BYTES_DRIFT')
    rows = subprocess.check_output(['ps', '-C', 'nginx', '-o', 'uid=,args='], text=True)
    uids = {int(row.split(None, 1)[0]) for row in rows.splitlines() if 'nginx: worker process' in row}
    import pwd
    need(len(uids) == 1 and 0 not in uids, 'UNPRIVILEGED_NGINX_WORKER_REQUIRED')
    user = pwd.getpwuid(next(iter(uids))).pw_name
    need(user == 'www-data', 'NGINX_WORKER_DRIFT')
    proof_code = "import pathlib,hashlib,json; r=pathlib.Path(" + repr(str(PUBLIC)) + "); print(json.dumps({p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file()},sort_keys=True))"
    actual = json.loads(run('actual-worker-public-read', ['runuser', '-u', user, '--', 'python3', '-c', proof_code]))
    need(actual == desired, 'ACTUAL_NGINX_WORKER_CANNOT_READ_PUBLIC_BYTES')
    save(RELEASE / 'public-manifest.json', desired)
    return {'path': str(PUBLIC), 'files': len(desired), 'manifest_sha256': sha(RELEASE / 'public-manifest.json'),
            'worker_user': user, 'actual_worker_read_verified': True, 'prior_assets_preserved': True}


def create_public_root(path):
    need(not path.exists() and not path.is_symlink(), 'NEW_PUBLIC_DIRECTORY_REQUIRED')
    path.mkdir(mode=0o755)
    # mkdir permissions are masked by umask077. Only this new unserved static
    # root is made readable; private config/release/data stay protected.
    path.chmod(0o755)


def expected_backend(base_files, root):
    expected = dict(base_files)
    for name in BACKEND:
        need((name not in base_files) if name in NEW_BACKEND else (name in base_files),
             'REVIEWED_NEW_OR_EXISTING_BACKEND_FILE_REQUIRED')
        expected[name] = sha(root / 'backend' / name)
    return expected


def regressions(root, image):
    wheels = OLD_RELEASE / 'test-wheels'
    expected = json.loads((OLD_RELEASE / 'test-wheel-manifest.json').read_text())
    need(wheels.is_dir() and not wheels.is_symlink() and expected and file_map(wheels) == expected,
         'PRIOR_TEST_WHEELS_REQUIRED_AND_UNCHANGED')
    normalized = re.compile(r'[-_.]+')
    versions = {normalized.sub('-', name.lower()): version for name, version in TEST_TOOLS.items()}
    tool_names = {normalized.sub('-', name.lower()): name for name in TEST_TOOLS}
    install_tools = []
    for filename in expected:
        parts = filename.split('-')
        need(filename.endswith('.whl') and len(parts) >= 5 and
             versions.get(normalized.sub('-', parts[0].lower())) == parts[1], 'PINNED_TEST_TOOL_DRIFT')
        install_tools.append(tool_names[normalized.sub('-', parts[0].lower())] + '==' + parts[1])
    test_root = root / 'backend/tests'
    results = RELEASE / 'test-results'
    results.mkdir(mode=0o700)
    code = """import os,subprocess,sys,json,pathlib
os.environ['APP_ENV']='test';os.environ['ENVIRONMENT']='test'
os.environ['DATABASE_URL']='sqlite+aiosqlite:////tmp/synthetic-business.db'
os.environ['DATABASE_SCHEMA_MODE']='verify_only'
os.environ['PRIVATE_WORKSPACE_DATABASE_URL']='sqlite+aiosqlite:////tmp/synthetic-private/workspace.db'
os.environ['AUTOMATION_SCAN_ENABLED']='false';os.environ['ENABLE_DEFAULT_EMPLOYEE_ADMIN']='false'
os.environ['ENFORCE_EMPLOYEE_STATUS']='false';os.environ['ENFORCE_EMPLOYEE_SESSIONS']='false'
subprocess.check_call([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-cache-dir',
 '--no-index','--find-links','/test-wheels','--target','/tmp/test-deps','--no-deps',*TOOLS])
os.environ['PYTHONPATH']='/tmp/test-deps:/app:/app/backend'
subprocess.check_call([sys.executable,'-m','pytest',*['/app/backend/tests/'+name for name in TESTS],
 '-q','--disable-warnings','--tb=short','-p','no:cacheprovider','--junitxml=/test-results/regressions.xml'],cwd='/app/backend')
import xml.etree.ElementTree as ET
suites=list(ET.parse('/test-results/regressions.xml').getroot().iter('testsuite'))
assert suites and sum(int(s.get('tests','0')) for s in suites)>=MINIMUM
assert all(int(s.get('failures','0'))==0 and int(s.get('errors','0'))==0 and int(s.get('skipped','0'))==0 for s in suites)
print(json.dumps({'tests':sum(int(s.get('tests','0')) for s in suites),'network':'none',
 'production_env_loaded':False,'production_database_access':False,'actual_image_tested':True}))
""".replace('TOOLS', repr(install_tools)).replace('TESTS', repr(TESTS)).replace('MINIMUM', str(MIN_TESTS))
    output = isolated('candidate-regressions', image,
        ['--tmpfs', '/tmp:rw,nosuid,size=384m', '--tmpfs', '/app/backend/logs:rw,nosuid,noexec,size=16m',
         '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'TZ=Asia/Shanghai',
         '--mount', 'type=bind,src=' + str(test_root) + ',dst=/app/backend/tests,readonly',
         '--mount', 'type=bind,src=' + str(wheels) + ',dst=/test-wheels,readonly',
         '--mount', 'type=bind,src=' + str(results) + ',dst=/test-results',
         '--entrypoint', 'python', image, '-c', code])
    report = json.loads(output.splitlines()[-1])
    save(RELEASE / 'candidate-regressions.json', report)
    return report


def main(args):
    os.umask(0o077)
    need(re.fullmatch('[a-f0-9]{40}', SOURCE) and re.fullmatch('[a-f0-9]{12}', VERSION) and
         re.fullmatch('[a-f0-9]{64}', NGINX_SHA) and '__' not in str(RELEASE) and
         '__' not in str(PUBLIC), 'REVIEWED_CONSTANTS_MUST_BE_STAMPED')
    need(re.fullmatch('[a-f0-9]{64}', args.manifest_sha256), 'MANIFEST_HASH_SHAPE')
    protected(RELEASE, True)
    manifest_path = RELEASE / 'google-ads-manifest.json'
    payload_path = RELEASE / 'google-ads-payload.tar.gz'
    protected(manifest_path)
    protected(payload_path)
    need(sha(manifest_path) == args.manifest_sha256, 'MANIFEST_HASH_DRIFT')
    manifest = json.loads(manifest_path.read_text())
    need(manifest['source_sha'] == SOURCE and manifest['frontend_version'] == VERSION and
         manifest['base_private_image'] == BASE_IMAGE and manifest['backend_changes'] == list(BACKEND) and
         manifest['new_backend_files'] == list(NEW_BACKEND) and
         manifest['backend_regression_tests_expected_minimum'] == MIN_TESTS and
         manifest['runtime_dependency_changes'] is False and manifest['credentials_included'] is False and
         sha(payload_path) == manifest['payload_sha256'], 'APPROVED_PAYLOAD_REQUIRED')
    need(not (RELEASE / 'candidate.json').exists(), 'NEW_PREPARATION_REQUIRED')
    before = baseline()
    need(shutil.disk_usage(RELEASE).free > 4 * 1024**3, 'MINIMUM_FREE_SPACE_REQUIRED')
    save(RELEASE / 'running-baseline.json', before)
    root = extract(payload_path, manifest)
    base_files = scan('base-backend', BASE_IMAGE, SCAN_BACKEND)
    packages = scan('base-package-bytes', BASE_IMAGE, SCAN_PACKAGE_BYTES)
    expected_dist = scan('base-frontend-dist', BASE_IMAGE, SCAN_DIST)
    expected_dist.update(file_map(root / 'frontend/dist', True))
    expected = expected_backend(base_files, root)
    tag = 't24-private:google-ads-d6fce13-20261011'
    base_tag = 't24-private:google-ads-base-42c26ea-d6fce13-20261011'
    tags = subprocess.check_output(['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}'], text=True).splitlines()
    need(tag not in tags and base_tag not in tags, 'NEW_CANDIDATE_IMAGE_TAG_REQUIRED')
    run('base-image-pin', ['docker', 'tag', BASE_IMAGE, base_tag])
    need(run('base-image-pin-proof', ['docker', 'image', 'inspect', '-f', '{{.Id}}', base_tag]) == BASE_IMAGE,
         'PRIVATE_BASE_PIN_DRIFT')
    recipe = 'FROM ' + base_tag + '\n'
    recipe += ''.join('COPY backend/' + name + ' /app/backend/' + name + '\n' for name in BACKEND)
    recipe += 'COPY frontend/dist/ /app/frontend/dist/\n'
    recipe += 'LABEL t24.source.sha="' + SOURCE + '"\n'
    write(root / 'Dockerfile', recipe.encode())
    run('candidate-build', ['docker', 'build', '--pull=false', '--network=none', '-t', tag, '.'], 600, root)
    image = run('candidate-image-id', ['docker', 'image', 'inspect', '-f', '{{.Id}}', tag])
    need(re.fullmatch(r'sha256:[a-f0-9]{64}', image) and image != BASE_IMAGE, 'IMMUTABLE_NEW_IMAGE_REQUIRED')
    need(scan('candidate-backend', image, SCAN_BACKEND) == expected, 'BACKEND_BYTES_OUTSIDE_REVIEWED_ALLOWLIST_CHANGED')
    need(scan('candidate-package-bytes', image, SCAN_PACKAGE_BYTES) == packages, 'RUNTIME_PACKAGE_BYTES_CHANGED')
    need(scan('candidate-frontend-dist', image, SCAN_DIST) == expected_dist, 'IMAGE_FRONTEND_BYTES_DRIFT')
    tests = regressions(root, image)
    public = public_tree(root)
    need(baseline() == before, 'RUNNING_SERVICES_CHANGED_DURING_PREPARATION')
    candidate = {'stage': 'GOOGLE_ADS_CANDIDATE_VERIFIED', 'source_sha': SOURCE, 'frontend_version': VERSION,
                 'image_id': image, 'base_image_id': BASE_IMAGE, 'backend_runtime_changed_files': list(BACKEND),
                 'all_other_backend_bytes_identical': True, 'all_package_bytes_identical': True,
                 'candidate_tests': tests, 'public': public, 'running_baseline': before, 'readonly_baseline_sha256': BASELINE_SHA,
                 'production_services_modified': False, 'production_environment_loaded_in_tests': False,
                 'production_database_mounted_in_tests': False, 'deployed': False}
    save(RELEASE / 'candidate.json', candidate)
    print(json.dumps({'stage': candidate['stage'], 'candidate_sha256': sha(RELEASE / 'candidate.json'),
                      'image_id': image, 'tests': tests['tests'], 'production_services_modified': False}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest-sha256', required=True)
    try:
        main(parser.parse_args())
    except Exception as error:
        # Unexpected exceptions and command outputs can contain paths or provider text;
        # only reviewed constant failure codes are sent to command-assistant output.
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('[A-Z0-9_]+', str(error)) else 'PREPARATION_FAILED'
        print('GOOGLE_ADS_CANDIDATE_ERROR ' + code, flush=True)
        raise SystemExit(1) from None
