#!/usr/bin/env python3
"""Replace only the reviewed, never-activated Stripe upgrade helper.

The existing candidate, frozen payload, runtime, databases and configuration are
read-only. The helper and acquisition receipt form a fail-closed pair: helper
first, receipt last, with protected originals and a prepared recovery receipt.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import sys
import urllib.error
import urllib.request
from uuid import uuid4
import zipfile

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
BASE_IMAGE = 'sha256:322968e1935a6f7bb2e6d366a9f1cdb98aefab392af28c7269660ff46262a886'
RELEASE = Path('/opt/t24-crm/releases/stripe-report-c1ae19b38fec-20261012')
PUBLIC = Path('/var/www/t24-crm-public/stripe-report-c1ae19b38fec-20261012')
NAV_HELPER = Path('/opt/t24-crm/releases/private-navigation-823cf7a43c88-20261011/static_only_upgrade.py')
NAV_HASH = '0c42a56a6f602f45e58e48f3635f076c2c6db1b502096e6cc0ca80ec162c469a'
NGINX_HASH = 'cb088d05aa0c85424ec99079f81a7a4f30c44fa7f8effb8a2ffaae41ba03f42e'
ENV_HASH = '180f945729234df79c45f5148663f8407c75be55aa8d4e79107305c03c00f82d'
OLD_ACQUIRED_HASH = '487dccd0c0429610c03c6d58925a6ecc6991f5363bb4b7f82a14fa8354401d56'
OLD_UPGRADE_HASH = 'b3c2324f76529d6666b950f2c19968fcda737c86dbb2196f7e0916aad453b58d'
NEW_UPGRADE_HASH = '919f0ecca1d33a46d882a816b70fccb1514144ba4ddc828c2921e5db1a4b5e5b'
PRESERVED = {
    'prepare_candidate.py': '989dc1de81a0b3a39ad978c395bdfd7a3c31725a3e2ebee57a5713cfc8faa613',
    'prepared-backend/candidate.json': '005103022cdc86bee8319ec16d2b310629748dc1254c29a418f354f5d9bda1b5',
    'stripe-report-manifest.json': '35feaa07594fc4743081d5e0d3202bb647410388b66e06f2d6b5f44a30ec1c35',
    'frozen-source.json': '9ea752806526eba6d99d5f9df34b402cf3856a3763a875ea2e284725e8635357',
    'stripe-report-payload.tar.gz': 'fe7e7a412ddc0612e904cb6b9a60c62a480155e762d19578d0a4bb29f6498063',
}
HASH = re.compile('[a-f0-9]{64}')
COMMIT = re.compile('[a-f0-9]{40}')
MAX_ARCHIVE = 32 * 1024**2
ROOT_UID = 0


class RepairError(RuntimeError): pass


def need(condition, code):
    if not condition: raise RepairError(code)


def sha(data): return hashlib.sha256(data).hexdigest()


def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def stable(info):
    # Reading may update atime; mutations still change one of these fields.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def directory_identity(info):
    # APFS counts ordinary directory entries in nlink; our own writes change it.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def ancestors(path):
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == ROOT_UID and not info.st_mode & 0o022, 'PROTECTED_ANCESTOR_REQUIRED')


def protected(path, directory=False):
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_PROTECTED_PATH_REQUIRED')
    ancestors(path); info = path.lstat()
    need(info.st_uid == ROOT_UID and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
         and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1), 'ROOT_PRIVATE_FILE_REQUIRED')
    return info


def read_fixed(path, expected=None, maximum=4 * 1024**2):
    before = protected(path); need(0 < before.st_size <= maximum, 'BOUNDED_PROTECTED_FILE_REQUIRED')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        need(stable(os.fstat(stream.fileno())) == stable(before), 'OPENED_FILE_IDENTITY_DRIFT')
        data = stream.read(maximum + 1)
        need(stable(os.fstat(stream.fileno())) == stable(before), 'OPENED_FILE_MUTATED_DURING_READ')
    need(len(data) == before.st_size and stable(protected(path)) == stable(before), 'FILE_MUTATED_DURING_READ')
    need(expected is None or HASH.fullmatch(expected or '') and sha(data) == expected, 'REVIEWED_FILE_HASH_DRIFT')
    return data


def load_nav():
    read_fixed(NAV_HELPER, NAV_HASH, 1024**2); sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('_stripe_report_repair_navigation', NAV_HELPER)
    need(spec and spec.loader, 'VERIFIED_NAVIGATION_LOADER_REQUIRED')
    nav = importlib.util.module_from_spec(spec); spec.loader.exec_module(nav)
    return nav.retained_tools(), nav


@contextmanager
def lock(base):
    # This existing release lock is opened without creating or changing config.
    path = base.CONFIG / 'private-finance-release.lock'; before = protected(path)
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        need(stable(os.fstat(descriptor)) == stable(before), 'RELEASE_LOCK_IDENTITY_DRIFT')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally: os.close(descriptor)


def never_activated(release):
    for path in (release / 'upgrade-state.json', release / 'live-upgrade', PUBLIC):
        need(not os.path.lexists(path), 'ACTIVATION_ALREADY_STARTED_REPAIR_REJECTED')


def artifacts(release):
    values = {}
    for name, expected in PRESERVED.items():
        data = read_fixed(release / name, expected, 64 * 1024**2 if name.endswith('.tar.gz') else 4 * 1024**2)
        if name.endswith('.json'): values[name] = json.loads(data)
    manifest, frozen, candidate = (values[name] for name in ('stripe-report-manifest.json', 'frozen-source.json', 'prepared-backend/candidate.json'))
    need(manifest.get('source_sha') == frozen.get('source_sha') == candidate.get('source_sha') == SOURCE
         and candidate.get('stage') == 'STRIPE_REPORT_BACKEND_CANDIDATE_VERIFIED' and candidate.get('base_image_id') == BASE_IMAGE
         and candidate.get('payload_manifest_sha256') == PRESERVED['stripe-report-manifest.json']
         and candidate.get('frozen_source_sha256') == manifest.get('frozen_manifest_sha256') == PRESERVED['frozen-source.json']
         and candidate.get('payload_sha256') == manifest.get('payload_sha256') == PRESERVED['stripe-report-payload.tar.gz'], 'EXACT_VERIFIED_ARTIFACT_BINDINGS_REQUIRED')
    root = release / 'prepared-backend/payload'; protected(root, True); found = {}
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink(), 'FROZEN_PAYLOAD_SYMLINK_REJECTED')
        if path.is_dir(): protected(path, True); continue
        name = path.relative_to(root).as_posix()
        need(name in manifest['payload_files'], 'FROZEN_PAYLOAD_INVENTORY_DRIFT')
        found[name] = sha(read_fixed(path, manifest['payload_files'][name], 16 * 1024**2))
    need(found == manifest['payload_files'], 'COMPLETE_FROZEN_PAYLOAD_REQUIRED')
    return {'files': dict(PRESERVED), 'extracted_payload_sha256': sha(encoded(found))}


def checked_acquired(data, release):
    value = json.loads(data)
    expected = {name: digest for name, digest in PRESERVED.items() if '/' not in name}
    expected['upgrade.py'] = OLD_UPGRADE_HASH
    need(value.get('format_version') == 1 and value.get('stage') == 'STRIPE_REPORT_CARRIER_ACQUIRED'
         and value.get('directory') == str(release) and value.get('frontend_source_sha') == SOURCE
         and value.get('files') == expected and COMMIT.fullmatch(value.get('carrier_sha', ''))
         and HASH.fullmatch(value.get('archive_sha256', '')) and 'helper_repair' not in value
         and all(value.get(key) is False for key in ('backend_services_modified', 'databases_modified',
                  'credentials_included', 'public_assets_published', 'deployed')), 'EXACT_OLD_ACQUISITION_REQUIRED')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise RepairError('IMMUTABLE_DOWNLOAD_REDIRECT_REJECTED')


def download(carrier):
    url = 'https://codeload.github.com/billy285/t24-crm/zip/' + carrier
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, headers={'User-Agent': 'T24-Reviewed-Helper-Repair/1'}), timeout=30) as response:
            need(response.status == 200 and response.geturl() == url, 'IMMUTABLE_DOWNLOAD_ORIGIN_REQUIRED')
            return response.read(MAX_ARCHIVE + 1)
    except (urllib.error.URLError, OSError): raise RepairError('IMMUTABLE_CARRIER_DOWNLOAD_FAILED') from None


def selected_helper(blob, carrier, archive_hash, helper_hash):
    need(COMMIT.fullmatch(carrier or '') and HASH.fullmatch(archive_hash or '') and helper_hash == NEW_UPGRADE_HASH
         and 0 < len(blob) <= MAX_ARCHIVE and sha(blob) == archive_hash, 'EXACT_NEW_REVIEWED_CARRIER_REQUIRED')
    top = 't24-crm-' + carrier + '/'; selected = top + 'deployments/stripe-report-20261012/upgrade.py'; result = None
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries = archive.infolist()
        need(0 < len(entries) <= 10000 and len({entry.filename for entry in entries}) == len(entries), 'UNIQUE_BOUNDED_ARCHIVE_REQUIRED')
        for entry in entries:
            path = PurePosixPath(entry.filename)
            need(entry.filename.startswith(top) and path.as_posix() == entry.filename.rstrip('/') and not path.is_absolute()
                 and '..' not in path.parts and '\\' not in entry.filename and '\x00' not in entry.filename, 'CANONICAL_ARCHIVE_PATH_REQUIRED')
            if entry.filename != selected: continue
            mode = entry.external_attr >> 16
            need(not entry.is_dir() and not stat.S_ISLNK(mode) and (not stat.S_IFMT(mode) or stat.S_ISREG(mode))
                 and not entry.flag_bits & 1 and 0 < entry.file_size <= 1024**2, 'REGULAR_BOUNDED_NEW_HELPER_REQUIRED')
            with archive.open(entry) as stream: result = stream.read(1024**2 + 1)
            need(len(result) == entry.file_size and sha(result) == helper_hash, 'NEW_HELPER_BYTES_DRIFT')
    need(result is not None and sha(result) != OLD_UPGRADE_HASH, 'NEW_HELPER_REQUIRED')
    compile(result, 'reviewed_upgrade.py', 'exec')  # Syntax check only; never execute the new helper here.
    return result


def write_new(path, data):
    parent = protected(path.parent, True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        need(directory_identity(os.fstat(directory)) == directory_identity(parent), 'NEW_FILE_PARENT_IDENTITY_DRIFT')
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, 'wb') as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
        current = protected(path.parent, True)
        need(directory_identity(current) == directory_identity(parent), 'NEW_FILE_PARENT_REPLACED')
        os.fsync(directory)
    finally: os.close(directory)


def replace_fixed(path, old_hash, data):
    before = stable(protected(path)); read_fixed(path, old_hash); parent = protected(path.parent, True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.' + path.name + '-reviewed-' + uuid4().hex
    try:
        need(directory_identity(os.fstat(directory)) == directory_identity(parent), 'REPLACEMENT_PARENT_IDENTITY_DRIFT')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, 'wb') as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
        read_fixed(path, old_hash)
        current_parent = protected(path.parent, True)
        need(stable(protected(path)) == before and directory_identity(current_parent) == directory_identity(parent), 'REPLACEMENT_TARGET_OR_PARENT_DRIFT')
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory); os.fsync(directory)
    finally:
        try: os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError: pass
        os.close(directory)
    read_fixed(path, sha(data))


def runtime(base, nav):
    candidate, state, static = nav.accepted_receipts(base)
    current = nav.runtime(base, candidate, state, static)
    need(sha(base.read_nginx()) == NGINX_HASH and sha(read_fixed(base.ENV, ENV_HASH, 65536)) == ENV_HASH, 'UNCHANGED_ACCEPTED_RUNTIME_REQUIRED')
    return current


def repair(release, *, old_acquired_hash, carrier, archive_hash, helper_hash, base=None, nav=None, archive_bytes=None):
    need(old_acquired_hash == OLD_ACQUIRED_HASH and helper_hash == NEW_UPGRADE_HASH and COMMIT.fullmatch(carrier or '')
         and HASH.fullmatch(archive_hash or ''), 'EXPLICIT_REVIEWED_REPAIR_ARGUMENTS_REQUIRED')
    if base is None:
        need(os.geteuid() == 0 and socket.gethostname() == HOST and release == RELEASE, 'EXACT_AUTHENTICATED_REPAIR_HOST_REQUIRED')
        base, nav = load_nav()
    os.umask(0o077); protected(release, True)
    with lock(base):
        never_activated(release); baseline = runtime(base, nav); preserved = artifacts(release)
        old_receipt = read_fixed(release / 'acquired.json', old_acquired_hash); acquired = checked_acquired(old_receipt, release)
        old_helper = read_fixed(release / 'upgrade.py', OLD_UPGRADE_HASH, 1024**2)
        new_helper = selected_helper(download(carrier) if archive_bytes is None else archive_bytes, carrier, archive_hash, helper_hash)
        never_activated(release); need(runtime(base, nav) == baseline and artifacts(release) == preserved, 'PRE_REPAIR_STATE_DRIFT')
        directory = release / 'upgrade-helper-repair'; need(not os.path.lexists(directory), 'NEW_HELPER_REPAIR_DIRECTORY_REQUIRED'); directory.mkdir(mode=0o700)
        root_descriptor = os.open(release, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(root_descriptor)
        finally: os.close(root_descriptor)
        updated = {**acquired, 'files': {**acquired['files'], 'upgrade.py': helper_hash}, 'carrier_sha': carrier, 'archive_sha256': archive_hash,
                   'helper_repair': {'old_acquired_sha256': old_acquired_hash, 'old_upgrade_sha256': OLD_UPGRADE_HASH,
                     'new_upgrade_sha256': helper_hash, 'previous_carrier_sha': acquired['carrier_sha'],
                     'previous_archive_sha256': acquired['archive_sha256'], 'receipt': 'upgrade-helper-repair/repair.json'}}
        next_receipt = encoded(updated)
        proof = {'format_version': 1, 'stage': 'STRIPE_REPORT_UPGRADE_HELPER_REPAIR_PREPARED', 'source_sha': SOURCE,
                 'old_acquired_sha256': old_acquired_hash, 'new_acquired_sha256': sha(next_receipt),
                 'old_upgrade_sha256': OLD_UPGRADE_HASH, 'new_upgrade_sha256': helper_hash, 'carrier_sha': carrier,
                 'archive_sha256': archive_hash, 'preserved_artifacts': preserved, 'accepted_runtime_sha256': sha(encoded(baseline)),
                 'activation_started': False, 'production_databases_modified': False, 'production_configuration_modified': False,
                 'production_services_modified': False, 'public_assets_published': False, 'deployed': False}
        write_new(directory / 'upgrade-before.py', old_helper); write_new(directory / 'acquired-before.json', old_receipt)
        write_new(directory / 'upgrade-reviewed.py', new_helper); write_new(directory / 'acquired-reviewed.json', next_receipt)
        pending = encoded(proof); write_new(directory / 'repair.json', pending)
        # A crash between these replacements remains rejected by upgrade.py's
        # acquisition hash guard. Protected originals and exact next bytes remain.
        never_activated(release); need(runtime(base, nav) == baseline, 'IMMEDIATE_PRE_REPLACEMENT_RUNTIME_DRIFT')
        replace_fixed(release / 'upgrade.py', OLD_UPGRADE_HASH, new_helper)
        replace_fixed(release / 'acquired.json', old_acquired_hash, next_receipt)
        never_activated(release); need(runtime(base, nav) == baseline and artifacts(release) == preserved, 'POST_REPAIR_STATE_DRIFT')
        proof['stage'] = 'STRIPE_REPORT_UPGRADE_HELPER_REPAIRED'
        replace_fixed(directory / 'repair.json', sha(pending), encoded(proof))
        return proof


class SafeParser(argparse.ArgumentParser):
    def error(self, message): raise RepairError('ARGUMENTS_REJECTED')


if __name__ == '__main__':
    parser = SafeParser(); parser.add_argument('--execute', action='store_true')
    for name in ('old-acquired-sha256', 'carrier-sha', 'archive-sha256', 'upgrade-sha256'): parser.add_argument('--' + name, required=True)
    try:
        args = parser.parse_args(); need(args.execute, 'EXPLICIT_HELPER_REPAIR_REQUIRED')
        proof = repair(RELEASE, old_acquired_hash=args.old_acquired_sha256, carrier=args.carrier_sha,
                       archive_hash=args.archive_sha256, helper_hash=args.upgrade_sha256)
        print(json.dumps({'stage': proof['stage'], 'new_upgrade_sha256': proof['new_upgrade_sha256'],
            'new_acquired_sha256': proof['new_acquired_sha256'], 'receipt': str(RELEASE / 'upgrade-helper-repair/repair.json'),
            'receipt_sha256': sha(read_fixed(RELEASE / 'upgrade-helper-repair/repair.json')), 'deployed': False}, sort_keys=True))
    except BaseException as error:
        code = str(error) if isinstance(error, RepairError) and re.fullmatch('[A-Z0-9_]{1,100}', str(error)) else 'UPGRADE_HELPER_REPAIR_FAILED'
        print(json.dumps({'stage': 'STRIPE_REPORT_HELPER_REPAIR_REJECTED', 'error': code, 'deployed': False}, sort_keys=True))
        sys.exit(1)
