"""Diagnose two frozen aggregate proofs and quarantine exact unextracted staging.

No business rows or credential values are selected. This tool does not capture
or approve a new baseline; the original release drift rejection remains valid.
"""
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import stat
import subprocess
import sys
from types import ModuleType

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
OWNER_UID = 0
ROOT = Path('/opt/t24-crm/releases')
NAME = 'meta-operations-95588aa2e630-20261101'
ARCHIVE = NAME + '-baseline-stale-1'
OLD_PROOF_SHA = '3ee6ceadf311ed15fdb63be14461fc0460e2b560a6be422af05a5cd2ec2a4262'
NEW_PROOF_SHA = '9f8a8877a9934496cfbe100e03f62ff6189b53a5c99056e6c7060e1f114b7b18'
SOURCE = 'a03766539ef3430f350f467652511a43ee3c4abf'
FRONTEND = '58d2c585210f'
REVISION = 'bde8da01f247'
PINS = {'release.py': ('be7f3c282d84f7049b5d7ec4a804ba5e0d7238c6d5dc4ff18b1b0eb22147db5d', 46881), 'preflight.py': ('f08cc8d90fe726b4fe89b18b0c4018ceed0b0b32c54763e7bb04ace911ed45dc', 7676), 'manifest.json': ('fea6f7513b7ba2c96ce7193a592b3aa1be25e534e5860079b94b97045d443a42', 140673), 'payload.tar.gz': ('3283bf5f1c1d25faa04e7a0eda205e3326009345762712a657c949a4d6f4dacb', 9099269)}
LOCK = '.meta-operations-release.lock'
ARCHIVED = False
H = lambda body: hashlib.sha256(body).hexdigest()
identity = lambda row: (row.st_dev, row.st_ino, row.st_uid, row.st_gid, stat.S_IMODE(row.st_mode), stat.S_IFMT(row.st_mode))
file_identity = lambda row: (*identity(row), row.st_nlink, row.st_size, row.st_mtime_ns, row.st_ctime_ns)


def need(ok, code):
    if not ok: raise RuntimeError(code)


def protected_parents():
    for parent in (ROOT, *ROOT.parents):
        row = parent.lstat()
        need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == OWNER_UID and not row.st_mode & 0o022, 'PROTECTED_RELEASE_PARENT_REQUIRED')


def absent(name, parent_fd):
    try: os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError: return True
    return False


def members(directory_fd):
    need(set(os.listdir(directory_fd)) == set(PINS), 'ONLY_EXACT_FOUR_UNEXTRACTED_FILES_REQUIRED')
    result = {}
    for name, (sha, size) in PINS.items():
        row = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        need(stat.S_ISREG(row.st_mode) and row.st_uid == OWNER_UID and row.st_nlink == 1 and stat.S_IMODE(row.st_mode) == 0o600 and row.st_size == size, 'EXACT_PROTECTED_STAGING_MEMBER_REQUIRED')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno()); body = stream.read(size + 1)
        after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        need(file_identity(row) == file_identity(opened) == file_identity(after) and len(body) == size and H(body) == sha, 'EXACT_STAGING_MEMBER_HASH_SIZE_REQUIRED')
        result[name] = body
    need(set(os.listdir(directory_fd)) == set(PINS), 'STAGING_MEMBERS_CHANGED_DURING_READ')
    return result


def docker_metadata(*parts):
    # Fixed local socket and explicit nonsecret format; never request Config.Env,
    # Mounts, logs, full inspect JSON, registry credentials or business API data.
    value = subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', *parts], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, cwd='/', env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    need(value.returncode == 0 and len(value.stdout) <= 262144, 'BOUNDED_LOCAL_DOCKER_METADATA_REQUIRED')
    return value.stdout


def current_runtime(proof):
    template = '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"started":{{json .State.StartedAt}},"restart":{{json .RestartCount}}}'
    value = json.loads(docker_metadata('container', 'inspect', '--format', template, 't24-crm'))
    expected = {key: proof['crm'][key] for key in ('id', 'image', 'started', 'restart')}
    need(value == {**expected, 'running': True}, 'EXACT_RUNNING_ORIGINAL_RUNTIME_REQUIRED')
    return value


def no_started_prepare():
    names = set(docker_metadata('container', 'ls', '--all', '--format', '{{.Names}}').decode('ascii').splitlines())
    forbidden = {'t24-crm-before-meta-operations-95588aa2e630', 't24-crm-candidate-meta-operations-95588aa2e630', 't24-meta-operations-probe-95588aa2e630'}
    need(not names.intersection(forbidden), 'PREPARE_CONTAINER_EVIDENCE_REQUIRES_SEPARATE_REVIEW')
    images = set(docker_metadata('image', 'ls', '--format', '{{.Repository}}:{{.Tag}}').decode('ascii').splitlines())
    need(not images.intersection({'t24-crm:meta-operations-base-95588aa2e630', 't24-crm:meta-operations-95588aa2e630'}), 'PREPARE_IMAGE_EVIDENCE_REQUIRES_SEPARATE_REVIEW')
    public = Path('/var/www/t24-crm-public') / NAME
    need(not public.exists() and not public.is_symlink(), 'PREPARE_STATIC_EVIDENCE_REQUIRES_SEPARATE_REVIEW')


def aggregate_changes(old, new):
    for proof in (old, new):
        need(proof['stage'] == 'META_OPERATIONS_READONLY_PREFLIGHT' and proof['host'] == HOST and proof['source_sha'] == SOURCE and proof['frontend_version'] == FRONTEND and proof['schema_revision'] == REVISION and len(proof['rows']) == 141, 'EXACT_ORIGINAL_141_TABLE_PROOF_REQUIRED')
        need(all(proof[key] is False for key in ('credential_file_content_read', 'private_content_read', 'business_writes', 'provider_requests', 'runtime_changed')) and proof['meta_operations_environment_absent'] is True, 'READONLY_UNCONFIGURED_PROOF_REQUIRED')
    need({**new, 'rows': old['rows'], 'database_metadata': old['database_metadata']} == old, 'NON_ROW_BASELINE_DRIFT_REQUIRES_SEPARATE_REVIEW')
    need(set(old['rows']) == set(new['rows']), 'ORIGINAL_TABLE_SET_CHANGED')
    changed = []
    for name in sorted(old['rows']):
        need(re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}', name), 'SAFE_TABLE_IDENTIFIER_REQUIRED')
        before, after = old['rows'][name], new['rows'][name]
        for row in (before, after):
            need(set(row) == {'count', 'rows_sha256', 'shape_sha256'} and type(row['count']) is int and row['count'] >= 0 and all(isinstance(row[k], str) and re.fullmatch('[a-f0-9]{64}', row[k]) for k in ('rows_sha256', 'shape_sha256')), 'AGGREGATE_TABLE_EVIDENCE_ONLY_REQUIRED')
        need(before['shape_sha256'] == after['shape_sha256'], 'ORIGINAL_TABLE_SHAPE_CHANGED')
        if before != after: changed.append({'table': name, 'before_count': before['count'], 'after_count': after['count']})
    need(bool(changed), 'ROW_DRIFT_NOT_PRESENT_IN_FROZEN_PROOFS')
    return changed


def context_from_frozen_preflight(body):
    pf = ModuleType('_quarantine_exact_frozen_preflight'); pf.__file__ = str(ROOT / NAME / 'preflight.py')
    exec(compile(body, pf.__file__, 'exec'), pf.__dict__)
    core, _, context = pf.dependencies()
    old = core.strict_json(core.read(ROOT / ('meta-operations-preflight-' + OLD_PROOF_SHA[:12] + '.json'), sha=OLD_PROOF_SHA))
    new = core.strict_json(core.read(ROOT / ('meta-operations-preflight-' + NEW_PROOF_SHA[:12] + '.json'), sha=NEW_PROOF_SHA))
    changed = aggregate_changes(old, new)
    return context, new, changed


def original_boundary(context, proof):
    runtime = current_runtime(proof)
    need(context.m.inventory(runtime['id']) == context.inventory, 'EXACT_ORIGINAL_BACKEND_SOURCE_REQUIRED')
    need(context.m.schema_signature(context.m.BUSINESS, REVISION) == proof['schema_sha256'], 'EXACT_ORIGINAL_SCHEMA_REQUIRED')
    no_started_prepare()
    return runtime


def rename_noreplace(parent_fd):
    need(sys.platform.startswith('linux'), 'LINUX_ATOMIC_NOREPLACE_REQUIRED')
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, 'renameat2', None)
    need(function is not None, 'ATOMIC_RENAME_NOREPLACE_UNAVAILABLE')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]; function.restype = ctypes.c_int
    result = function(parent_fd, os.fsencode(NAME), parent_fd, os.fsencode(ARCHIVE), 1)
    if result != 0:
        need(ctypes.get_errno() != errno.EEXIST, 'FRESH_QUARANTINE_TARGET_REQUIRED')
        raise RuntimeError('ATOMIC_QUARANTINE_RENAME_REJECTED')


def quarantine():
    global ARCHIVED
    protected_parents(); parent_fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW); lock_fd = directory_fd = None
    try:
        parent = os.fstat(parent_fd)
        def boundary(name=NAME):
            need(identity(parent) == identity(os.fstat(parent_fd)) == identity(ROOT.lstat()), 'RELEASE_PARENT_NAMESPACE_DRIFT')
            row = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            need(stat.S_ISDIR(row.st_mode) and row.st_uid == OWNER_UID and stat.S_IMODE(row.st_mode) == 0o700, 'EXACT_PRIVATE_STAGING_DIRECTORY_REQUIRED')
            return row
        lock_fd = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW, dir_fd=parent_fd)
        lock = os.fstat(lock_fd)
        need(stat.S_ISREG(lock.st_mode) and lock.st_uid == OWNER_UID and lock.st_nlink == 1 and stat.S_IMODE(lock.st_mode) == 0o600, 'EXISTING_PROTECTED_RELEASE_LOCK_REQUIRED')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        need(absent(ARCHIVE, parent_fd), 'FRESH_QUARANTINE_TARGET_REQUIRED')
        prior = boundary(); directory_fd = os.open(NAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        need(identity(prior) == identity(os.fstat(directory_fd)) == identity(boundary()), 'STAGING_OPEN_NAMESPACE_DRIFT')
        frozen = members(directory_fd); context, proof, changed = context_from_frozen_preflight(frozen['preflight.py'])
        runtime = original_boundary(context, proof)
        need(frozen == members(directory_fd) and identity(prior) == identity(boundary()) == identity(os.fstat(directory_fd)), 'STAGING_CHANGED_DURING_REVIEW')
        need(absent(ARCHIVE, parent_fd), 'FRESH_QUARANTINE_TARGET_REQUIRED')
        rename_noreplace(parent_fd); ARCHIVED = True; os.fsync(parent_fd)
        need(absent(NAME, parent_fd) and identity(prior) == identity(boundary(ARCHIVE)) == identity(os.fstat(directory_fd)) and frozen == members(directory_fd), 'QUARANTINE_IDENTITY_OR_MEMBER_DRIFT')
        need(current_runtime(proof) == runtime, 'POST_QUARANTINE_ORIGINAL_RUNTIME_DRIFT')
        return {'stage': 'META_OPERATIONS_STALE_BASELINE_STAGING_QUARANTINED', 'archive_path': str(ROOT / ARCHIVE), 'files_preserved': 4, 'original_source_sha': SOURCE, 'frontend_version': FRONTEND, 'schema_revision': REVISION, 'table_count': 141, 'old_preflight_sha256': OLD_PROOF_SHA, 'comparison_preflight_sha256': NEW_PROOF_SHA, 'changed_tables': changed, 'changed_table_count': len(changed), 'diagnostic_from_frozen_aggregate_proofs': True, 'raw_business_rows_read': False, 'credential_values_read': False, 'original_runtime_unchanged': True, 'docker_changed': False, 'business_writes': False, 'database_migrated': False, 'nginx_changed': False, 'preflight_captured_or_approved': False, 'new_baseline_still_requires_separate_capture_and_review': True}
    finally:
        if directory_fd is not None: os.close(directory_fd)
        if lock_fd is not None: os.close(lock_fd)
        os.close(parent_fd)


def main():
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); sys.dont_write_bytecode = True; os.umask(0o077)
    print(json.dumps(quarantine(), sort_keys=True))


if __name__ == '__main__':
    try: main()
    except BaseException as error:
        value = str(error); code = value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}', value) else 'META_OPERATIONS_QUARANTINE_REJECTED'
        print(json.dumps({'stage': 'META_OPERATIONS_QUARANTINE_REJECTED', 'code': code, 'archive_completed': ARCHIVED})); raise SystemExit(1)
