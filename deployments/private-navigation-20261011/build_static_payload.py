#!/usr/bin/env python3
"""Freeze the complete built frontend from a reviewed navigation-only commit."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

from static_only_upgrade import ALLOWED_SOURCE_FILES, BACKEND_SOURCE, PREVIOUS_VERSION, SOURCE, VERSION, need

SUFFIXES = {'.html', '.js', '.css', '.json', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.ico', '.txt',
            '.woff', '.woff2', '.ttf', '.webmanifest'}


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


def main(args):
    need(SOURCE.fullmatch(args.source_sha or '') and args.source_sha != BACKEND_SOURCE
         and VERSION.fullmatch(args.version or '') and args.version != PREVIOUS_VERSION, 'NEW_FRONTEND_SOURCE_VERSION_REQUIRED')
    repo, output = args.repo.resolve(), args.output.resolve()
    need(output.is_dir() and not output.is_symlink(), 'OUTPUT_DIRECTORY_REQUIRED')
    need(git(repo, 'rev-parse', 'HEAD') == args.source_sha, 'EXACT_SOURCE_COMMIT_REQUIRED')
    need(not git(repo, 'status', '--porcelain', '--untracked-files=no'), 'CLEAN_TRACKED_CHECKOUT_REQUIRED')
    need(not git(repo, 'ls-files', '--others', '--exclude-standard', '--', 'app/frontend/src', 'app/frontend/public'),
         'UNCOMMITTED_FRONTEND_SOURCE_FORBIDDEN')
    changed = sorted(git(repo, 'diff', '--name-only', BACKEND_SOURCE, args.source_sha, '--', 'app/frontend').splitlines())
    need(changed and set(changed) <= ALLOWED_SOURCE_FILES and 'app/frontend/src/pages/PrivateWorkspace.tsx' in changed,
         'ONLY_APPROVED_PRIVATE_NAVIGATION_FILES_REQUIRED')
    need(sorted(git(repo, 'diff', '--name-only', BACKEND_SOURCE, args.source_sha, '--', 'app').splitlines()) == changed,
         'OTHER_APPLICATION_RUNTIME_CHANGES_FORBIDDEN')
    for name in changed:
        path = repo / name
        need(path.is_file() and not path.is_symlink() and path.resolve() == path, 'REGULAR_CHANGED_SOURCE_REQUIRED')
    need(not git(repo, 'diff', '--name-only', BACKEND_SOURCE, args.source_sha, '--', 'app/backend',
                 'docker-compose.yml', 'docker-compose.yaml', 'Dockerfile', 'package.json', 'pnpm-lock.yaml'),
         'BACKEND_RUNTIME_CHANGES_FORBIDDEN')
    dist = repo / 'app/frontend/dist'
    need(dist.is_dir() and dist.resolve() == dist and not dist.is_symlink(), 'CANONICAL_COMPLETE_DIST_REQUIRED')
    files = {}
    for path in sorted(dist.rglob('*')):
        need(not path.is_symlink(), 'STATIC_SYMLINK_FORBIDDEN')
        if path.is_dir():
            continue
        relative = path.relative_to(dist)
        need(path.is_file() and path.suffix in SUFFIXES and not any(part.startswith('.') for part in relative.parts)
             and (path.suffix != '.html' or relative.as_posix() in {'index.html', 'offline.html'}), 'NON_STATIC_FILE_REJECTED')
        blob = path.read_bytes()
        need(len(blob) <= 16 * 1024 * 1024, 'STATIC_FILE_SIZE_LIMIT')
        files[relative.as_posix()] = blob
    need({'index.html', 'app-version.json'} <= files.keys() and len(files) < 10000
         and sum(map(len, files.values())) < 64 * 1024 * 1024, 'COMPLETE_DIST_SIZE_LIMIT')
    need(json.loads(files['app-version.json']) == {'version': args.version}, 'FROZEN_BUILD_VERSION_REQUIRED')
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, blob in sorted(files.items()):
            info = tarfile.TarInfo('payload/' + name)
            info.size, info.mode, info.mtime = len(blob), 0o644, 0
            archive.addfile(info, io.BytesIO(blob))
    encoded = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=encoded, mtime=0) as stream:
        stream.write(buffer.getvalue())
    payload = encoded.getvalue()
    manifest = {'format_version': 1, 'stage': 'FROZEN_PRIVATE_NAVIGATION_STATIC_SOURCE',
                'frontend_source_sha': args.source_sha, 'frontend_version': args.version,
                'backend_source_sha': BACKEND_SOURCE, 'previous_frontend_version': PREVIOUS_VERSION,
                'changed_source_files': changed, 'payload_sha256': sha(payload),
                'payload_files': {name: sha(blob) for name, blob in sorted(files.items())},
                'static_only': True, 'backend_changes': False, 'databases_modified': False, 'credentials_included': False}
    data = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    need(not (output / 'static-payload.tar.gz').exists() and not (output / 'static-manifest.json').exists(),
         'FRESH_FROZEN_ARTIFACTS_REQUIRED')
    for name, blob in (('static-payload.tar.gz', payload), ('static-manifest.json', data)):
        with (output / name).open('xb') as stream:
            stream.write(blob)
        (output / name).chmod(0o600)
    result = {'stage': manifest['stage'], 'frontend_source_sha': args.source_sha, 'frontend_version': args.version,
              'payload_sha256': sha(payload), 'manifest_sha256': sha(data), 'static_files': len(files),
              'backend_changes': False, 'deployed': False}
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--version', required=True)
    main(parser.parse_args())
