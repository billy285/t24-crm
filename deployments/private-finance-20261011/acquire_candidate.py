#!/usr/bin/env python3
"""Acquire reviewed code and static artifacts only; never switch live services."""
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
PREFIX = 'deployments/private-finance-20261011/'
ARTIFACTS = ('frozen-source.json', 'private-finance-manifest.json', 'private-finance-payload.tar.gz')
TOOLS = ('acquire_candidate.py', 'build_payload.py', 'candidate_prepare.py', 'credential_transfer.py',
         'live_preflight.py', 'private_schema_guard.py', 'seed_private_stripe.py',
         'switch_completed.py', 'static_completed.py')
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024
SHA = re.compile(r'[a-f0-9]{64}')
SOURCE = re.compile(r'[a-f0-9]{40}')


class AcquireError(RuntimeError):
    pass


def need(condition, code):
    if not condition:
        raise AcquireError(code)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def archive_url(carrier):
    need(SOURCE.fullmatch(carrier or ''), 'IMMUTABLE_CARRIER_REQUIRED')
    return 'https://codeload.github.com/billy285/t24-crm/zip/' + carrier


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AcquireError('UNEXPECTED_DOWNLOAD_REDIRECT')


def download(carrier, digest):
    need(SHA.fullmatch(digest or ''), 'REVIEWED_ARCHIVE_HASH_REQUIRED')
    # This fixed public GitHub archive URL has no user credential or query.
    request = urllib.request.Request(archive_url(carrier), headers={'User-Agent': 'T24-Reviewed-Carrier/1'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            need(response.status == 200 and response.geturl() == request.full_url, 'DOWNLOAD_ORIGIN_DRIFT')
            blob = response.read(MAX_ARCHIVE_BYTES + 1)
    except (urllib.error.URLError, OSError):
        raise AcquireError('CARRIER_DOWNLOAD_FAILED') from None
    need(0 < len(blob) <= MAX_ARCHIVE_BYTES and sha(blob) == digest, 'CARRIER_ARCHIVE_HASH_DRIFT')
    return blob


def reviewed_files(blob, carrier, source, digests):
    need(SOURCE.fullmatch(carrier or '') and SOURCE.fullmatch(source or ''), 'REVIEWED_SOURCE_REQUIRED')
    need(set(digests) == set(ARTIFACTS) and all(SHA.fullmatch(value or '') for value in digests.values()),
         'REVIEWED_ARTIFACT_HASHES_REQUIRED')
    top = 't24-crm-' + carrier + '/'
    selected = {PREFIX + name: name for name in TOOLS}
    selected.update({PREFIX + 'artifacts/' + name: name for name in ARTIFACTS})
    result = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        infos = archive.infolist()
        need(0 < len(infos) <= 10000 and len({info.filename for info in infos}) == len(infos),
             'CARRIER_ENTRY_INVENTORY_REJECTED')
        for info in infos:
            name = info.filename
            path = PurePosixPath(name)
            need(name.startswith(top) and not path.is_absolute() and '..' not in path.parts
                 and path.as_posix() == name.rstrip('/'), 'CARRIER_PATH_REJECTED')
            relative = name[len(top):]
            if relative not in selected:
                continue
            target = selected[relative]
            mode = info.external_attr >> 16
            need(not info.is_dir() and not stat.S_ISLNK(mode) and (not stat.S_IFMT(mode) or stat.S_ISREG(mode))
                 and not info.flag_bits & 1, 'CARRIER_SELECTED_FILE_REJECTED')
            limit = MAX_PAYLOAD_BYTES if target.endswith('.tar.gz') else 1024 * 1024
            need(0 < info.file_size <= limit, 'CARRIER_FILE_SIZE_REJECTED')
            with archive.open(info) as stream:
                value = stream.read(limit + 1)
            need(len(value) == info.file_size and len(value) <= limit, 'CARRIER_FILE_SIZE_REJECTED')
            result[target] = value
    need(set(result) == set(TOOLS) | set(ARTIFACTS), 'COMPLETE_CARRIER_REQUIRED')
    for name, digest in digests.items():
        need(sha(result[name]) == digest, 'FROZEN_ARTIFACT_HASH_DRIFT')
    frozen = json.loads(result['frozen-source.json'])
    manifest = json.loads(result['private-finance-manifest.json'])
    need(frozen.get('stage') == 'FROZEN_PRIVATE_FINANCE_SOURCE' and frozen.get('source_sha') == source
         and manifest.get('stage') == 'PRIVATE_FINANCE_PAYLOAD_PREPARED' and manifest.get('source_sha') == source
         and manifest.get('frozen_manifest_sha256') == digests['frozen-source.json']
         and manifest.get('payload_sha256') == digests['private-finance-payload.tar.gz']
         and manifest.get('credentials_included') is False and manifest.get('production_access') is False
         and manifest.get('deployed') is False, 'CARRIER_SCOPE_BINDING_REJECTED')
    return result


def protected_directory(path, *, owner=0, ancestors=False):
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_RELEASE_DIRECTORY_REQUIRED')
    for directory in (path, *path.parents) if ancestors else (path,):
        try: info = directory.lstat()
        except OSError: raise AcquireError('PROTECTED_RELEASE_DIRECTORY_REQUIRED') from None
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == owner and not info.st_mode & 0o022,
             'PROTECTED_RELEASE_DIRECTORY_REQUIRED')
    return path.stat()


def install(files, destination, *, receipt=None):
    # Caller supplies an unused root-owned release directory. Never extract the
    # archive, overwrite a file or consume credentials/live baseline from Git.
    need(set(files) == set(TOOLS) | set(ARTIFACTS), 'COMPLETE_CARRIER_REQUIRED')
    need(not destination.exists() and not destination.is_symlink(), 'NEW_CARRIER_DIRECTORY_REQUIRED')
    parent_info = protected_directory(destination.parent, owner=os.geteuid())
    parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        pinned_parent = os.fstat(parent_fd)
        need((pinned_parent.st_dev, pinned_parent.st_ino) == (parent_info.st_dev, parent_info.st_ino),
             'RELEASE_PARENT_IDENTITY_DRIFT')
        os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
        descriptor = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        pinned = os.fstat(descriptor)
        need(pinned.st_uid == os.geteuid() and stat.S_IMODE(pinned.st_mode) == 0o700,
             'PROTECTED_NEW_CARRIER_REQUIRED')
        output = {**files, **({'acquired.json': receipt} if receipt is not None else {})}
        for name, blob in sorted(output.items()):
            need(name in set(TOOLS) | set(ARTIFACTS) | {'acquired.json'} and isinstance(blob, bytes),
                 'CARRIER_INSTALL_FILE_REJECTED')
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(blob); stream.flush(); os.fsync(stream.fileno())
        os.fsync(descriptor)
        current_parent = protected_directory(destination.parent, owner=os.geteuid())
        current = protected_directory(destination, owner=os.geteuid())
        need((current_parent.st_dev, current_parent.st_ino) == (pinned_parent.st_dev, pinned_parent.st_ino)
             and (current.st_dev, current.st_ino) == (pinned.st_dev, pinned.st_ino),
             'CARRIER_DIRECTORY_IDENTITY_DRIFT')
        os.fsync(parent_fd)
    finally:
        if descriptor is not None: os.close(descriptor)
        os.close(parent_fd)


def main(args):
    need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_AUTHENTICATED_TARGET_REQUIRED')
    protected_directory(ROOT, ancestors=True)
    need(SOURCE.fullmatch(args.source_sha or ''), 'REVIEWED_SOURCE_REQUIRED')
    digests = {'frozen-source.json': args.freeze_sha256, 'private-finance-manifest.json': args.manifest_sha256,
               'private-finance-payload.tar.gz': args.payload_sha256}
    blob = download(args.carrier_sha, args.archive_sha256)
    files = reviewed_files(blob, args.carrier_sha, args.source_sha, digests)
    destination = ROOT / ('private-finance-carrier-' + args.carrier_sha[:12] + '-20261011')
    os.umask(0o077)
    receipt = {'stage': 'PRIVATE_FINANCE_CARRIER_ACQUIRED', 'carrier_sha': args.carrier_sha,
        'source_sha': args.source_sha, 'archive_sha256': args.archive_sha256,
        'files': {name: sha(value) for name, value in sorted(files.items())},
        'credentials_included': False, 'live_database_access': False,
        'services_changed': False, 'public_assets_published': False, 'deployed': False}
    install(files, destination, receipt=(json.dumps(receipt, sort_keys=True) + '\n').encode())
    protected_directory(ROOT, ancestors=True)
    print(json.dumps({'stage': receipt['stage'], 'source_sha': args.source_sha,
        'carrier_sha': args.carrier_sha, 'directory': str(destination), 'files': len(files), 'deployed': False}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('carrier-sha', 'source-sha', 'archive-sha256', 'freeze-sha256', 'manifest-sha256', 'payload-sha256'):
        parser.add_argument('--' + name, required=True)
    try:
        main(parser.parse_args())
    except Exception as error:
        code = str(error) if isinstance(error, AcquireError) and re.fullmatch(r'[A-Z0-9_]+', str(error)) else 'CARRIER_ACQUISITION_FAILED'
        print('PRIVATE_FINANCE_CARRIER_ERROR ' + code)
        raise SystemExit(1) from None
