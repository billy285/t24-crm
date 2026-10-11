#!/usr/bin/env python3
"""Build a local carrier only from an explicitly frozen, reviewed Git source.

The complete private backend delta and private tests are collected from Git,
not the working tree. Every static file must match the separately reviewed build
inventory. No build, push, production access or automatic deployment occurs.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

BASE_SOURCE = 'dd8061ca30b91554f3f431446616dffc12c81b7a'
BASE_IMAGE = 'sha256:2ed347b29ba8f29ffeaab26df75e8c5d75c7479b477a1e45e80bdf2b19d098db'
HASH = re.compile(r'[a-f0-9]{64}')
SOURCE_HASH = re.compile(r'[a-f0-9]{40}')
PRIVATE_RUNTIME = re.compile(r'app/backend/(?:services/private_[a-z0-9_]+|(?:models|routers|schemas|dependencies)/private_workspace)\.py')
PRIVATE_TEST = re.compile(r'app/backend/tests/test_private_[a-z0-9_]+\.py')
DEPENDENCY_NAMES = re.compile(r'(?:requirements(?:[.][A-Za-z0-9_-]+)?|requirements[A-Za-z0-9_.-]*\.txt|'
    r'package\.json|(?:package|npm-shrinkwrap)-lock\.json|pnpm-lock\.yaml|yarn\.lock|'
    r'pyproject\.toml|poetry\.lock|Pipfile(?:\.lock)?|Dockerfile(?:[.][A-Za-z0-9_-]+)?)')
STATIC_SUFFIXES = {'.html', '.js', '.css', '.json', '.png', '.jpg', '.jpeg', '.webp', '.gif',
                   '.svg', '.ico', '.txt', '.woff', '.woff2', '.ttf', '.webmanifest'}


class PayloadError(RuntimeError):
    pass


def need(condition, code):
    if not condition: raise PayloadError(code)


def sha(blob): return hashlib.sha256(blob).hexdigest()


def git(repo, *args):
    need(args and args[0] in {'rev-parse', 'show', 'diff', 'ls-tree', 'status'}, 'READONLY_GIT_COMMAND_REQUIRED')
    result = subprocess.run(['git', *args], cwd=repo, capture_output=True, timeout=30, check=False)
    need(result.returncode == 0, 'GIT_SOURCE_READ_FAILED')
    return result.stdout


def paths(repo, source):
    return git(repo, 'ls-tree', '-r', '--name-only', '-z', source).decode().rstrip('\0').split('\0')


def blob(repo, source, path):
    need(PurePosixPath(path).as_posix() == path and not path.startswith('/') and '..' not in PurePosixPath(path).parts,
         'CANONICAL_SOURCE_PATH_REQUIRED')
    modes = git(repo, 'ls-tree', source, '--', path).decode().split()
    need(len(modes) >= 3 and modes[0] in {'100644', '100755'} and modes[1] == 'blob', 'REGULAR_GIT_SOURCE_REQUIRED')
    return git(repo, 'show', source + ':' + path)


def freeze(path, expected):
    need(HASH.fullmatch(expected or '') and path.is_file() and not path.is_symlink(), 'FROZEN_MANIFEST_HASH_REQUIRED')
    data = path.read_bytes()
    need(sha(data) == expected, 'FROZEN_MANIFEST_HASH_DRIFT')
    value = json.loads(data)
    need(value.get('format_version') == 1 and value.get('stage') == 'FROZEN_PRIVATE_FINANCE_SOURCE' and
         SOURCE_HASH.fullmatch(value.get('source_sha', '')) and value.get('baseline_private_source_sha') == BASE_SOURCE and
         value.get('base_private_image') == BASE_IMAGE and re.fullmatch('[a-f0-9]{12}', value.get('frontend_version', '')),
         'EXACT_REVIEWED_SOURCE_MANIFEST_REQUIRED')
    need(type(value.get('backend_regression_tests_minimum')) is int and value['backend_regression_tests_minimum'] > 0,
         'REVIEWED_TEST_EVIDENCE_REQUIRED')
    for field in ('backend_delta_sha256', 'dependency_file_sha256', 'frontend_dist_sha256'):
        inventory = value.get(field)
        need(isinstance(inventory, dict) and inventory and
             all(isinstance(name, str) and isinstance(digest, str) and HASH.fullmatch(digest) for name, digest in inventory.items()),
             'COMPLETE_REVIEWED_FILE_INVENTORY_REQUIRED')
    return value


def backend_delta(repo, source, frozen):
    raw = git(repo, 'diff', '--name-status', '--no-renames', '-z', BASE_SOURCE, source, '--', 'app/backend').decode()
    parts = raw.rstrip('\0').split('\0') if raw else []
    need(len(parts) % 2 == 0, 'BACKEND_DIFF_FORMAT_INVALID')
    changes = {}
    for status, path in zip(parts[::2], parts[1::2]):
        need(status in {'A', 'M'} and (PRIVATE_RUNTIME.fullmatch(path) or PRIVATE_TEST.fullmatch(path)),
             'NON_PRIVATE_BACKEND_DELTA_REJECTED')
        changes[path] = blob(repo, source, path)
    need(changes and {path: sha(data) for path, data in changes.items()} == frozen, 'COMPLETE_BACKEND_DELTA_DRIFT')
    return changes


def dependencies(repo, source, frozen):
    old, new = set(paths(repo, BASE_SOURCE)), set(paths(repo, source))
    names = sorted(path for path in old | new if DEPENDENCY_NAMES.fullmatch(PurePosixPath(path).name))
    need(names and all(path in old and path in new for path in names), 'DEPENDENCY_INVENTORY_DRIFT')
    hashes = {}
    for path in names:
        before = blob(repo, BASE_SOURCE, path); after = blob(repo, source, path)
        need(before == after, 'RUNTIME_DEPENDENCY_CHANGED')
        hashes[path] = sha(after)
    need(hashes == frozen, 'COMPLETE_DEPENDENCY_PROOF_DRIFT')
    return hashes


def static_files(dist, expected, version):
    need(dist.is_dir() and not dist.is_symlink(), 'STATIC_BUILD_DIRECTORY_REQUIRED')
    files = {}
    for path in sorted(dist.rglob('*')):
        need(not path.is_symlink(), 'STATIC_SYMLINK_FORBIDDEN')
        if path.is_dir(): continue
        relative = path.relative_to(dist)
        need(path.is_file() and path.suffix in STATIC_SUFFIXES and not any(part.startswith('.') for part in relative.parts),
             'NON_STATIC_PAYLOAD_REJECTED')
        need(path.suffix != '.html' or relative.as_posix() in {'index.html', 'offline.html'}, 'UNEXPECTED_STATIC_HTML')
        files[relative.as_posix()] = path.read_bytes()
    need({'index.html', 'app-version.json'} <= set(files) and
         json.loads(files['app-version.json']) == {'version': version}, 'FRONTEND_VERSION_DRIFT')
    need({name: sha(data) for name, data in files.items()} == expected, 'COMPLETE_STATIC_BUILD_DRIFT')
    return files


def assemble(repo, frozen):
    source = frozen['source_sha']
    need(git(repo, 'rev-parse', 'HEAD').decode().strip() == source, 'EXACT_FINAL_REVIEWED_HEAD_REQUIRED')
    need(not git(repo, 'status', '--porcelain', '--untracked-files=no', '--', 'app').strip(), 'TRACKED_APPLICATION_DRIFT')
    # Untracked implementation/test files must be committed before freezing.
    untracked = git(repo, 'ls-tree', '-r', '--name-only', source, '--', 'app/backend', 'app/frontend/src', 'app/frontend/tests').decode().splitlines()
    tracked = set(untracked)
    for prefix in ('app/backend', 'app/frontend/src', 'app/frontend/tests'):
        for file in (repo / prefix).rglob('*'):
            if file.is_file() and (file.suffix in {'.py', '.ts', '.tsx', '.css', '.mjs', '.js'}) and '__pycache__' not in file.parts:
                need(file.relative_to(repo).as_posix() in tracked and not file.is_symlink(), 'UNTRACKED_APPLICATION_SOURCE_REJECTED')
    changes = backend_delta(repo, source, frozen['backend_delta_sha256'])
    dependency_hashes = dependencies(repo, source, frozen['dependency_file_sha256'])
    files = {path.removeprefix('app/'): data for path, data in changes.items()}
    source_hashes = {path: sha(data) for path, data in changes.items()}
    test_paths = [path for path in paths(repo, source) if PRIVATE_TEST.fullmatch(path)]
    need(test_paths, 'PRIVATE_REGRESSION_TESTS_REQUIRED')
    test_paths.append('app/backend/tests/conftest.py')
    for path in sorted(test_paths):
        data = blob(repo, source, path); files[path.removeprefix('app/')] = data; source_hashes[path] = sha(data)
    static = static_files(repo / 'app/frontend/dist', frozen['frontend_dist_sha256'], frozen['frontend_version'])
    files.update({'frontend/dist/' + name: data for name, data in static.items()})
    need(len(files) < 10000 and sum(map(len, files.values())) < 64 * 1024 * 1024, 'PAYLOAD_SIZE_LIMIT')
    return files, source_hashes, dependency_hashes


def encode(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo('payload/' + name)
            entry.size = len(data); entry.mode = 0o644; entry.mtime = 0
            entry.uid = entry.gid = 0; entry.uname = entry.gname = ''
            archive.addfile(entry, io.BytesIO(data))
    output = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as stream: stream.write(buffer.getvalue())
    return output.getvalue()


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream: stream.write(data)


def main(args):
    repo = args.repo.resolve(); output = args.output.resolve()
    need(repo.is_dir() and output.is_dir() and not args.output.is_symlink(), 'EXISTING_LOCAL_OUTPUT_REQUIRED')
    frozen = freeze(args.freeze, args.freeze_sha256)
    files, source_hashes, dependency_hashes = assemble(repo, frozen)
    archive = encode(files)
    manifest = {'format_version': 1, 'stage': 'PRIVATE_FINANCE_PAYLOAD_PREPARED',
        'source_sha': frozen['source_sha'], 'baseline_private_source_sha': BASE_SOURCE, 'base_private_image': BASE_IMAGE,
        'frontend_version': frozen['frontend_version'], 'frozen_manifest_sha256': args.freeze_sha256,
        'payload_sha256': sha(archive), 'payload_files': {name: sha(data) for name, data in sorted(files.items())},
        'source_file_sha256': source_hashes, 'backend_changes': sorted(frozen['backend_delta_sha256']),
        'private_tests': sorted(name for name in source_hashes if name.startswith('app/backend/tests/')),
        'runtime_dependency_file_sha256': dependency_hashes, 'runtime_dependency_changes': False,
        'backend_regression_tests_expected_minimum': frozen['backend_regression_tests_minimum'],
        'credentials_included': False, 'production_access': False, 'deployed': False}
    target = output / 'private-finance-payload.tar.gz'; destination = output / 'private-finance-manifest.json'
    need(not target.exists() and not target.is_symlink() and not destination.exists() and not destination.is_symlink(),
         'NEW_PAYLOAD_AND_MANIFEST_REQUIRED')
    write_new(target, archive)
    document = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode(); write_new(destination, document)
    print(json.dumps({'stage': manifest['stage'], 'source_sha': frozen['source_sha'], 'payload_files': len(files),
        'payload_sha256': sha(archive), 'manifest_sha256': sha(document), 'credentials_included': False, 'deployed': False}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True); parser.add_argument('--freeze-sha256', required=True)
    try: main(parser.parse_args())
    except Exception as error:
        code = str(error) if isinstance(error, PayloadError) and re.fullmatch('[A-Z0-9_]+', str(error)) else 'PAYLOAD_PREPARATION_FAILED'
        print('PRIVATE_FINANCE_PAYLOAD_ERROR ' + code)
        raise SystemExit(1) from None
