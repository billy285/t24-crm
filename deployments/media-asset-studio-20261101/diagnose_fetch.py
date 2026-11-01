"""Read only the exact failed new dependency container and public staging."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
import subprocess

NAME = 't24-asset-fetch-4fe7ee52647f'
WORK = Path('/opt/t24-crm/releases/media-asset-studio-toolchain-4fe7ee52647f-20261101')
IMAGE = 'sha256:3e948625074aa6af891ace1e814f98aa9ed8d9bc004d85f6c5cadc6b423c1536'
FETCH_SHA = '609a572610907e695237bff91a3a4419d32fecd30fe32d82bb4b99e37f4fb2e8'
H = lambda body: hashlib.sha256(body).hexdigest()


def need(value, code):
    if not value: raise RuntimeError(code)


def call(args, maximum=131072):
    p = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, check=False,
        env={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LANG':'C.UTF-8'})
    need(len(p.stdout) <= maximum, 'BOUNDED_READONLY_DIAGNOSTIC_REQUIRED')
    return p.returncode, p.stdout


def diagnostic():
    need(os.geteuid() == 0 and socket.gethostname() == 'iZj6c4cj7edgnhdimts4l7Z', 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077)
    for parent in (WORK, *WORK.parents):
        row = parent.lstat(); need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'EXACT_NEW_PUBLIC_STAGE_REQUIRED')
    fmt = '{"name":{{json .Name}},"image":{{json .Image}},"state":{{json .State}},"mounts":{{json .Mounts}},"entrypoint":{{json .Config.Entrypoint}},"cmd":{{json .Config.Cmd}}}'
    code, body = call(['docker', 'inspect', '--format', fmt, NAME])
    if code:
        return {'stage':'ASSET_TOOLCHAIN_READONLY_FETCH_DIAGNOSTIC', 'exact_container_present':False, 'inspection_message':body.decode(errors='replace')[:600], 'changes_performed':False}
    info = json.loads(body); need(info['name'] == '/' + NAME and info['image'] == IMAGE and info['state']['Running'] is False and info['entrypoint'] == ['/usr/bin/env'], 'EXACT_STOPPED_NEW_FETCH_CONTAINER_REQUIRED')
    need(len(info['mounts']) == 1 and info['mounts'][0]['Source'] == str(WORK / 'fetch-data') and info['mounts'][0]['Destination'] == '/out', 'ONLY_NEW_PUBLIC_PACKAGE_MOUNT_REQUIRED')
    cmd = info['cmd']; need(cmd[:8] == ['-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'LANG=C.UTF-8', 'PYTHONDONTWRITEBYTECODE=1', '/usr/local/bin/python', '-I', '-B', '-c'] and len(cmd) == 9 and H(cmd[-1].encode()) == FETCH_SHA, 'EXACT_REVIEWED_FETCH_SCRIPT_REQUIRED')
    code, logs = call(['docker', 'logs', '--tail', '100', NAME])
    need(code == 0, 'READONLY_FETCH_LOGS_REQUIRED')
    lines = logs.decode(errors='replace').splitlines()
    safe = [line[:500] for line in lines if re.search(r'Traceback|File "<string>"|RuntimeError:|Error:|^E:|^W:|^N:', line)][:30]
    files = []
    root = WORK / 'fetch-data'
    for path in sorted(root.rglob('*')):
        need(len(files) < 256 and len(path.relative_to(root).parts) <= 3 and not path.is_symlink(), 'BOUNDED_PUBLIC_STAGE_INVENTORY_REQUIRED')
        row = path.lstat()
        if stat.S_ISREG(row.st_mode):
            files.append({'relative_path':str(path.relative_to(root)), 'bytes':row.st_size, 'mode':oct(stat.S_IMODE(row.st_mode)), 'owner':row.st_uid})
        else: need(stat.S_ISDIR(row.st_mode), 'REGULAR_PUBLIC_STAGING_ONLY')
    code, diff = call(['docker', 'diff', NAME])
    need(code == 0, 'READONLY_FETCH_DIFF_REQUIRED')
    paths = [line[:240] for line in diff.decode(errors='replace').splitlines() if re.match(r'^[ACD] /(?:etc/apt/|var/lib/apt/|var/cache/apt/|var/log/apt/)', line)][:80]
    state = {key:info['state'].get(key) for key in ('Status','Running','ExitCode','OOMKilled','StartedAt','FinishedAt')}
    return {'stage':'ASSET_TOOLCHAIN_READONLY_FETCH_DIAGNOSTIC', 'exact_container_present':True, 'state':state,
        'bounded_public_fetch_traceback':safe, 'raw_log_sha256':H(logs), 'public_staging_files':files, 'apt_filesystem_diff_paths':paths,
        'original_apt_subprocess_output_was_persisted':False, 'note':'The first fetch helper captured APT subprocess output in memory; if it raised, those APT bytes were not retained. This diagnostic exports only existing container logs and public staging metadata.',
        'credential_environment_or_files_read':False, 'production_container_read_or_changed':False, 'existing_container_or_staging_changed':False,
        'installation_or_network_request_performed':False, 'changes_performed':False}
