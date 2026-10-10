#!/usr/bin/env python3
"""Create a deterministic relevance payload. Stamp reviewed constants first."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

SOURCE = '938b87da0adb99c2ed89ee677caacff5a325f19d'
VERSION = '38beaf2eaff0'
BASE_IMAGE = 'sha256:c409a9e0b30b48b9e19ddede27c24a9ccd984ed59a57028d07e723258f1051ae'
BACKEND = ('services/private_workspace.py', 'services/private_workspace_providers.py',
           'services/private_mail_relevance.py', 'schemas/private_workspace.py', 'routers/private_workspace.py')
NEW_BACKEND = ('services/private_mail_relevance.py',)
MIN_TESTS = 142  # Root confirmed the combined reviewed private suite count.
TESTS = ('conftest.py', 'test_private_workspace_core.py', 'test_private_workspace_providers.py',
         'test_private_workspace_worker.py', 'test_private_workspace_app.py', 'test_private_mail_relevance.py')
STATIC_SUFFIXES = {'.html', '.js', '.css', '.json', '.png', '.jpg', '.jpeg', '.webp', '.gif',
                   '.svg', '.ico', '.txt', '.woff', '.woff2', '.ttf', '.webmanifest'}


def need(value, code):
    if not value:
        raise RuntimeError(code)


def main(args):
    need(re.fullmatch('[a-f0-9]{40}', SOURCE) and re.fullmatch('[a-f0-9]{12}', VERSION),
         'REVIEWED_CONSTANTS_MUST_BE_STAMPED')
    repo = args.repo.resolve()
    output = args.output.resolve()
    need(output.is_dir() and not output.is_symlink(), 'OUTPUT_DIRECTORY_REQUIRED')
    need(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip() == SOURCE,
         'EXACT_APP_SOURCE_REQUIRED')
    files = {}
    tracked = {}
    paths = ['app/backend/' + name for name in BACKEND]
    paths += ['app/backend/tests/' + name for name in TESTS]
    for path in paths:
        blob = subprocess.check_output(['git', 'show', SOURCE + ':' + path], cwd=repo)
        actual = repo / path
        need(actual.is_file() and not actual.is_symlink() and actual.read_bytes() == blob,
             'TRACKED_SOURCE_BYTES_DRIFT')
        name = path.removeprefix('app/')
        files[name] = blob
        tracked[path] = hashlib.sha256(blob).hexdigest()
    dist = repo / 'app/frontend/dist'
    need(json.loads((dist / 'app-version.json').read_text()) == {'version': VERSION},
         'EXACT_LOCAL_BUILD_VERSION_REQUIRED')
    for path in sorted(dist.rglob('*')):
        need(not path.is_symlink(), 'STATIC_SYMLINK_FORBIDDEN')
        if path.is_dir():
            continue
        relative = path.relative_to(dist)
        need(path.is_file() and path.suffix in STATIC_SUFFIXES and
             not any(part.startswith('.') for part in relative.parts), 'NON_STATIC_PAYLOAD_FORBIDDEN')
        need(path.suffix != '.html' or relative.as_posix() in {'index.html', 'offline.html'},
             'UNEXPECTED_STATIC_HTML')
        files['frontend/dist/' + relative.as_posix()] = path.read_bytes()
    need(len(files) < 10000 and sum(len(blob) for blob in files.values()) < 64 * 1024**2,
         'PAYLOAD_SIZE_LIMIT')
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, blob in sorted(files.items()):
            info = tarfile.TarInfo('payload/' + name)
            info.size = len(blob)
            info.mode = 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            archive.addfile(info, io.BytesIO(blob))
    target = output / 'gmail-relevance-payload.tar.gz'
    need(not target.exists() and not target.is_symlink(), 'NEW_PAYLOAD_REQUIRED')
    with target.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as encoded:
            encoded.write(buffer.getvalue())
    target.chmod(0o600)
    manifest = {
        'source_sha': SOURCE, 'frontend_version': VERSION, 'base_private_image': BASE_IMAGE,
        'payload_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'source_file_sha256': tracked,
        'payload_files': {name: hashlib.sha256(blob).hexdigest() for name, blob in sorted(files.items())},
        'backend_changes': list(BACKEND), 'new_backend_files': list(NEW_BACKEND),
        'runtime_dependency_changes': False, 'credentials_included': False,
        'backend_regression_tests_expected_minimum': MIN_TESTS,
    }
    destination = output / 'gmail-relevance-manifest.json'
    need(not destination.exists() and not destination.is_symlink(), 'NEW_MANIFEST_REQUIRED')
    destination.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    destination.chmod(0o600)
    print(json.dumps({'payload_sha256': manifest['payload_sha256'],
                      'manifest_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                      'payload_files': len(files), 'bytes': target.stat().st_size,
                      'credentials_included': False}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
