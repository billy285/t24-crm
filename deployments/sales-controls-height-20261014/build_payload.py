#!/usr/bin/env python3
"""Freeze the sales calling controls static-only source/build delta; never include DB files."""
import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

BASELINE = 'a4bed09cebb68c0f4f5a51d013512bc91bdc5de8'
BASELINE_SOURCE = '969165eaec8a6bd3772dbd44e556b88d8d192230'
BASELINE_FRONTEND = '783a9f6bb897'
BACKEND = set()
FRONTEND = {'pages/sales-calling-controls.css'}
PRESERVED = {'company_finance_formulas': True, 'close_conditions': True,
             'private_workspace': True, 'customer_invitation_rules': True,
             'commission_attribution': True, 'import_template': True}
NODE = '/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
H = lambda body: hashlib.sha256(body).hexdigest()


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def git(*args):
    return subprocess.check_output(['git', *args])


def inventory(ref):
    return {name: H(git('show', ref + ':' + name)) for name in
            git('ls-tree', '-r', '--name-only', ref, '--', 'app/').decode().splitlines()}


def static_path(name):
    path = Path(name)
    if not path.parts or path.is_absolute() or str(path) != name or '\\' in name or any(part.startswith('.') for part in path.parts):
        return False
    if len(path.parts) == 1:
        return name in {'index.html', 'offline.html', 'app-version.json', 'manifest.webmanifest', 'robots.txt', 'sw.js', 'registerSW.js'} or path.suffix in {'.png', '.svg', '.ico'} or bool(re.fullmatch(r'workbox-[a-zA-Z0-9_-]+\.js', name))
    return path.parts[0] == 'assets' and path.suffix in {'.js', '.css', '.png', '.svg', '.ico', '.jpg', '.jpeg', '.webp', '.avif', '.gif', '.woff', '.woff2', '.ttf', '.eot'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    need(bool(re.fullmatch(r'[a-f0-9]{40}', args.source)), 'EXACT_SOURCE_REQUIRED')
    need(git('rev-parse', 'HEAD').decode().strip() == args.source, 'HEAD_DRIFT')
    before, after = inventory(BASELINE), inventory(args.source)
    allowed = {'app/backend/' + name for name in BACKEND} | {'app/frontend/src/' + name for name in FRONTEND}
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    tests = {name for name in changed if name.startswith('app/frontend/tests/')}
    need(changed - tests == allowed, 'SOURCE_SCOPE_DRIFT')
    for name, expected in after.items():
        need(H(Path(name).read_bytes()) == expected, 'WORKING_TREE_DRIFT')
    version = json.loads(Path('app/frontend/dist/app-version.json').read_text())['version']
    script = """const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"""
    need(bool(re.fullmatch(r'[a-f0-9]{12}', version)) and version != BASELINE_FRONTEND, 'NEW_FRONTEND_REQUIRED')
    need(subprocess.check_output([NODE, '-e', script, str(Path('app/frontend/src').resolve())]).decode() == version, 'BUILD_SOURCE_VERSION_DRIFT')
    payload = {}
    for path in Path('app/frontend/dist').rglob('*'):
        need(not path.is_symlink(), 'SYMLINK_REJECTED')
        if path.is_file():
            name = str(path.relative_to('app/frontend/dist'))
            need(static_path(name), 'STATIC_PATH_REJECTED')
            payload['static/' + name] = path.read_bytes()
    for name in BACKEND:
        payload['backend/' + name] = Path('app/backend', name).read_bytes()
    need(sum(map(len, payload.values())) < 64 * 1024 ** 2, 'PAYLOAD_LIMIT')
    need(all(len(body) < 16 * 1024 ** 2 for body in payload.values()), 'PAYLOAD_MEMBER_LIMIT')
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, body in sorted(payload.items()):
                item = tarfile.TarInfo(name)
                item.size, item.mode, item.mtime = len(body), 0o644, 0
                archive.addfile(item, io.BytesIO(body))
    manifest = {'format_version': 1, 'source_sha': args.source, 'baseline_source_sha': BASELINE,
                'baseline_deployed_source_sha': BASELINE_SOURCE,
                'frontend_version': version, 'baseline_frontend_version': BASELINE_FRONTEND,
                'payload_sha256': H(buffer.getvalue()), 'files': {name: H(body) for name, body in payload.items()},
                'backend_before': {name: before.get('app/backend/' + name) for name in BACKEND},
                'backend_after': {name: after['app/backend/' + name] for name in BACKEND},
                'changed_source_files': sorted(changed),
                'protected_source_inventory': {name: expected for name, expected in before.items() if name not in changed},
                'preserved': PRESERVED, 'credentials_included': False,
                'database_schema_changes': False, 'production_row_changes': False,
                'static_only': True, 'backend_changes': False, 'services_modified': False, 'environment_modified': False}
    args.out.mkdir(parents=True, exist_ok=True)
    bodies = {'payload.tar.gz': buffer.getvalue(), 'manifest.json': (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()}
    for name, body in bodies.items():
        with (args.out / name).open('xb') as stream:
            stream.write(body)
    print(json.dumps({'source': args.source, 'version': version, 'payload_sha256': manifest['payload_sha256'],
                      'manifest_sha256': H(bodies['manifest.json']), 'protected_files': len(manifest['protected_source_inventory'])}))


if __name__ == '__main__':
    main()
