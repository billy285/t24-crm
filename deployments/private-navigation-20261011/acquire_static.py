#!/usr/bin/env python3
"""Acquire only a hash-reviewed private-navigation helper and static artifacts.

Standalone so the operator can run the reviewed source inline before the helper
exists on the server. No extraction, installation or directory creation happens
before all immutable archive, file and manifest bindings have been verified.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import urllib.error
import urllib.request
import zipfile


HOST = 'iZj6c4cj7edgnhdimts4l7Z'
ROOT = Path('/opt/t24-crm/releases')
PREFIX = 'deployments/private-navigation-20261011/'
SELECTED = {
    PREFIX + 'static_only_upgrade.py': 'static_only_upgrade.py',
    PREFIX + 'artifacts/static-manifest.json': 'static-manifest.json',
    PREFIX + 'artifacts/static-payload.tar.gz': 'static-payload.tar.gz',
}
BACKEND_SOURCE = '3c5b8c1d63b8f078e162e228750b508715699479'
PREVIOUS_VERSION = '374558c66144'
ALLOWED_SOURCE_FILES = frozenset({
    'app/frontend/src/pages/PrivateWorkspace.tsx',
    'app/frontend/src/pages/private-workspace.css',
    'app/frontend/src/pages/PrivateAdsDashboard.tsx',
    'app/frontend/src/lib/private-workspace-navigation.ts',
    'app/frontend/tests/private-workspace-mail-ui.test.mjs',
    'app/frontend/tests/private-workspace-navigation.test.mjs',
})
HASH = re.compile('[a-f0-9]{64}')
SOURCE = re.compile('[a-f0-9]{40}')
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_SELECTED_BYTES = 64 * 1024 * 1024


class AcquireError(RuntimeError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise AcquireError('ARGUMENTS_REJECTED')


def need(condition, code):
    if not condition:
        raise AcquireError(code)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def archive_url(carrier):
    need(SOURCE.fullmatch(carrier or ''), 'FULL_IMMUTABLE_CARRIER_REQUIRED')
    return 'https://codeload.github.com/billy285/t24-crm/zip/' + carrier


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AcquireError('DOWNLOAD_REDIRECT_REJECTED')


def download(carrier, expected):
    need(HASH.fullmatch(expected or ''), 'REVIEWED_ARCHIVE_HASH_REQUIRED')
    url = archive_url(carrier)
    request = urllib.request.Request(url, headers={'User-Agent': 'T24-Reviewed-Navigation-Carrier/1'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            need(response.status == 200 and response.geturl() == url, 'EXACT_ARCHIVE_ORIGIN_REQUIRED')
            blob = response.read(MAX_ARCHIVE_BYTES + 1)
    except (urllib.error.URLError, OSError):
        raise AcquireError('CARRIER_DOWNLOAD_FAILED') from None
    need(0 < len(blob) <= MAX_ARCHIVE_BYTES and sha(blob) == expected, 'ARCHIVE_BYTES_OR_HASH_DRIFT')
    return blob


def reviewed_files(blob, carrier, source, digests):
    need(SOURCE.fullmatch(carrier or '') and SOURCE.fullmatch(source or '') and source != BACKEND_SOURCE,
         'NEW_REVIEWED_NAVIGATION_SOURCE_REQUIRED')
    need(set(digests) == set(SELECTED.values()) and all(HASH.fullmatch(value or '') for value in digests.values()),
         'EXACT_REVIEWED_STATIC_HASHES_REQUIRED')
    need(0 < len(blob) <= MAX_ARCHIVE_BYTES, 'ARCHIVE_SIZE_LIMIT')
    top = 't24-crm-' + carrier + '/'
    files = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries = archive.infolist()
        need(0 < len(entries) <= 10000 and len({entry.filename for entry in entries}) == len(entries),
             'UNIQUE_BOUNDED_ARCHIVE_INVENTORY_REQUIRED')
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            need(name.startswith(top) and not path.is_absolute() and '..' not in path.parts
                 and path.as_posix() == name.rstrip('/') and '\\' not in name and '\x00' not in name,
                 'CANONICAL_ARCHIVE_PATH_REQUIRED')
            relative = name[len(top):]
            if relative not in SELECTED:
                continue
            target = SELECTED[relative]
            mode = entry.external_attr >> 16
            need(not entry.is_dir() and not stat.S_ISLNK(mode)
                 and (not stat.S_IFMT(mode) or stat.S_ISREG(mode)) and not entry.flag_bits & 1,
                 'REGULAR_UNENCRYPTED_SELECTED_FILE_REQUIRED')
            limit = MAX_SELECTED_BYTES if target.endswith('.tar.gz') else 4 * 1024 * 1024 if target.endswith('.json') else 1024 * 1024
            need(0 < entry.file_size <= limit, 'SELECTED_FILE_SIZE_LIMIT')
            total += entry.file_size
            need(total < MAX_SELECTED_BYTES, 'SELECTED_TOTAL_SIZE_LIMIT')
            with archive.open(entry) as stream:
                data = stream.read(limit + 1)
            need(len(data) == entry.file_size and len(data) <= limit, 'SELECTED_FILE_LENGTH_DRIFT')
            files[target] = data
    need(set(files) == set(SELECTED.values()), 'COMPLETE_STATIC_CARRIER_REQUIRED')
    need(all(sha(files[name]) == expected for name, expected in digests.items()), 'REVIEWED_SELECTED_HASH_DRIFT')
    manifest = json.loads(files['static-manifest.json'])
    changed = manifest.get('changed_source_files')
    need(manifest.get('format_version') == 1 and manifest.get('stage') == 'FROZEN_PRIVATE_NAVIGATION_STATIC_SOURCE'
         and manifest.get('frontend_source_sha') == source and manifest.get('backend_source_sha') == BACKEND_SOURCE
         and manifest.get('previous_frontend_version') == PREVIOUS_VERSION
         and re.fullmatch('[a-f0-9]{12}', manifest.get('frontend_version', ''))
         and manifest['frontend_version'] != PREVIOUS_VERSION and manifest.get('static_only') is True
         and all(manifest.get(key) is False for key in ('backend_changes', 'databases_modified', 'credentials_included'))
         and manifest.get('payload_sha256') == digests['static-payload.tar.gz']
         and isinstance(changed, list) and len(changed) == len(set(changed)) and changed
         and set(changed) <= ALLOWED_SOURCE_FILES and 'app/frontend/src/pages/PrivateWorkspace.tsx' in changed,
         'EXACT_NAVIGATION_MANIFEST_BINDING_REQUIRED')
    return files


def protected_directory(path, ancestors=False):
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_PROTECTED_DIRECTORY_REQUIRED')
    for directory in (path, *path.parents) if ancestors else (path,):
        info = directory.lstat()
        need(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid == os.geteuid()
             and not stat.S_IMODE(info.st_mode) & 0o022, 'PROTECTED_DIRECTORY_REQUIRED')
    return path.stat()


def install(files, destination, receipt):
    # All archive and binding checks run before this function. Use pinned
    # directory descriptors so a path replacement cannot redirect file writes.
    need(set(files) == set(SELECTED.values()) and all(isinstance(blob, bytes) and blob for blob in files.values())
         and isinstance(receipt, bytes), 'ONLY_COMPLETE_REVIEWED_STATIC_FILES_REQUIRED')
    need(not destination.exists() and not destination.is_symlink(), 'FRESH_EXACT_RELEASE_DIRECTORY_REQUIRED')
    parent_info = protected_directory(destination.parent)
    parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_fd = None
    try:
        parent = os.fstat(parent_fd)
        need((parent.st_dev, parent.st_ino) == (parent_info.st_dev, parent_info.st_ino), 'RELEASE_PARENT_IDENTITY_DRIFT')
        os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
        directory_fd = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        directory = os.fstat(directory_fd)
        need(directory.st_uid == os.geteuid() and stat.S_IMODE(directory.st_mode) == 0o700, 'PROTECTED_NEW_RELEASE_REQUIRED')
        for name, blob in sorted({**files, 'acquired.json': receipt}.items()):
            need(name in set(SELECTED.values()) | {'acquired.json'}, 'STATIC_INSTALL_NAME_REJECTED')
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
        os.fsync(directory_fd)
        current_parent = protected_directory(destination.parent)
        current = protected_directory(destination)
        need((current_parent.st_dev, current_parent.st_ino) == (parent.st_dev, parent.st_ino)
             and (current.st_dev, current.st_ino) == (directory.st_dev, directory.st_ino)
             and stat.S_IMODE(current.st_mode) == 0o700, 'RELEASE_DIRECTORY_IDENTITY_DRIFT')
        os.fsync(parent_fd)
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        os.close(parent_fd)


def main(args):
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_AUTHENTICATED_ROOT_SERVER_REQUIRED')
    need(SOURCE.fullmatch(args.source_sha or '') and SOURCE.fullmatch(args.carrier_sha or '')
         and all(HASH.fullmatch(value or '') for value in (args.archive_sha256, args.manifest_sha256,
                 args.payload_sha256, args.helper_sha256)), 'FULL_REVIEWED_SOURCE_AND_HASH_ARGUMENTS_REQUIRED')
    protected_directory(ROOT, ancestors=True)
    destination = ROOT / ('private-navigation-' + args.source_sha[:12] + '-20261011')
    need(not destination.exists() and not destination.is_symlink(), 'FRESH_EXACT_RELEASE_DIRECTORY_REQUIRED')
    digests = {'static_only_upgrade.py': args.helper_sha256, 'static-manifest.json': args.manifest_sha256,
               'static-payload.tar.gz': args.payload_sha256}
    blob = download(args.carrier_sha, args.archive_sha256)
    files = reviewed_files(blob, args.carrier_sha, args.source_sha, digests)
    report = {'format_version': 1, 'stage': 'PRIVATE_NAVIGATION_STATIC_CARRIER_ACQUIRED',
              'frontend_source_sha': args.source_sha, 'carrier_sha': args.carrier_sha,
              'archive_sha256': args.archive_sha256, 'files': digests, 'directory': str(destination),
              'backend_services_modified': False, 'databases_modified': False,
              'credentials_included': False, 'public_assets_published': False, 'deployed': False}
    os.umask(0o077)
    install(files, destination, (json.dumps(report, sort_keys=True, indent=2) + '\n').encode())
    protected_directory(ROOT, ancestors=True)
    print(json.dumps({'stage': report['stage'], 'directory': str(destination),
                      'frontend_source_sha': args.source_sha, 'carrier_sha': args.carrier_sha,
                      'archive_sha256': args.archive_sha256, 'files': digests, 'deployed': False}, sort_keys=True))
    return report


if __name__ == '__main__':
    parser = SafeParser()
    for name in ('source-sha', 'carrier-sha', 'archive-sha256', 'manifest-sha256', 'payload-sha256', 'helper-sha256'):
        parser.add_argument('--' + name, required=True)
    try:
        main(parser.parse_args())
    except BaseException as error:
        code = str(error) if isinstance(error, AcquireError) and re.fullmatch('[A-Z0-9_]{1,100}', str(error)) else 'STATIC_CARRIER_ACQUISITION_FAILED'
        print(json.dumps({'stage': 'PRIVATE_NAVIGATION_STATIC_CARRIER_REJECTED', 'error': code, 'deployed': False}, sort_keys=True))
        raise SystemExit(1) from None
