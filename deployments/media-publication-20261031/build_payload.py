"""Build the exact reviewed application delta using only captured public summary."""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('publication_build_scope', HERE / 'release.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
H = lambda body: hashlib.sha256(body).hexdigest()


def git(*args): return subprocess.check_output(['git', *args])


def inventory(ref):
    with tarfile.open(fileobj=io.BytesIO(git('archive', ref, 'app/'))) as archive:
        members = archive.getmembers(); r.need(all(item.isdir() or item.isfile() for item in members), 'SOURCE_LINK_OR_SPECIAL_REJECTED')
        r.need(len({item.name for item in members}) == len(members), 'DUPLICATE_SOURCE_MEMBER_REJECTED')
        return {item.name: H(archive.extractfile(item).read()) for item in members if item.isfile()}


def frontend_version():
    node = '/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    code = "const fs=require('node:fs'),p=require('node:path'),h=require('node:crypto').createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){const q=p.join(d,e.name);if(e.isSymbolicLink())throw Error('link');if(e.isDirectory())walk(q);else if(e.isFile()){h.update(p.relative(root,q));h.update(fs.readFileSync(q));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"
    return subprocess.check_output([node, '-e', code, str(Path('app/frontend/src').resolve())]).decode()


def static_path(name):
    parts = Path(name).parts
    if not parts or Path(name).is_absolute() or str(Path(name)) != name or '\\' in name or any(part.startswith('.') for part in parts): return False
    if len(parts) == 1: return name in {'index.html', 'offline.html', 'app-version.json', 'manifest.webmanifest', 'robots.txt', 'sw.js', 'registerSW.js'} or Path(name).suffix in {'.png', '.svg', '.ico'} or bool(re.fullmatch(r'workbox-[a-zA-Z0-9_-]+\.js', name))
    return parts[0] == 'assets' and Path(name).suffix in {'.js', '.css', '.png', '.svg', '.ico', '.jpg', '.jpeg', '.webp', '.avif', '.gif', '.woff', '.woff2', '.ttf', '.eot'}


def frozen_sources(after):
    root = Path('outputs/media-publication-20261031')
    front_blob = r.local_bytes(root / 'frontend-freeze.json', 1048576); back_blob = r.local_bytes(root / 'backend-freeze.json', 1048576)
    r.need(H(front_blob) == r.FRONTEND_FREEZE_SHA and H(back_blob) == r.BACKEND_FREEZE_SHA, 'EXACT_APPLICATION_FREEZES_REQUIRED')
    front, back = json.loads(front_blob), json.loads(back_blob)
    front_rows = front['source_files']; back_rows = back['members']
    r.need(len(front_rows) == 13 and {row['file'] for row in front_rows} == r.FRONTEND_FILES, 'EXACT_FRONTEND_FREEZE_SCOPE_REQUIRED')
    r.need(len(back_rows) == 7 and {row['path'] for row in back_rows} == {'app/backend/' + name for name in r.BACKEND_FILES} | r.TEST_FILES, 'EXACT_BACKEND_FREEZE_SCOPE_REQUIRED')
    r.need(set(back['runtime_files']) == {'app/backend/' + name for name in r.BACKEND_FILES} and back['new_tables'] == [r.NEW_TABLE] and back['migration_revision'] == r.NEW_REVISION and back['migration_down_revision'] == r.OLD_REVISION, 'EXACT_MIGRATION_FREEZE_REQUIRED')
    r.need(all(after.get(row['file']) == row['sha256'] for row in front_rows) and all(after.get(row['path']) == row['sha256'] for row in back_rows), 'FROZEN_APPLICATION_SOURCE_DRIFT')


def build(summary):
    r.pins_ready(); r.validate_summary(summary)
    before, after = inventory(r.BASE_SOURCE), inventory(r.SOURCE_SHA)
    r.need(inventory('HEAD') == after, 'HEAD_APPLICATION_SOURCE_DRIFT')
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    r.need(changed == r.SOURCE_FILES and set(before) <= set(after), 'EXACT_TWENTY_FILE_APPLICATION_DELTA_REQUIRED')
    frozen_sources(after)
    for name, pin in after.items():
        path = Path(name); r.need(H(r.local_bytes(path)) == pin, 'LOCAL_APPLICATION_SOURCE_DRIFT')
    expected = {name for name in after if name.startswith('app/frontend/src/')}
    actual = {str(path) for path in Path('app/frontend/src').rglob('*') if path.is_file() or path.is_symlink()}
    r.need(actual == expected, 'UNTRACKED_FRONTEND_SOURCE_REJECTED')
    backend_before = {name: before.get('app/backend/' + name) for name in sorted(r.BACKEND_FILES)}
    r.need(summary['backend_changed_before'] == backend_before and backend_before[r.MIGRATION] is None, 'ACTUAL_RUNTIME_BACKEND_BASELINE_DRIFT')
    dist = Path('app/frontend/dist')
    r.need(dist.resolve() == dist.absolute() and dist.is_dir() and not dist.is_symlink(), 'CANONICAL_DIST_DIRECTORY_REQUIRED')
    paths = list(dist.rglob('*'))
    for path in paths:
        r.need(not path.is_symlink(), 'DIST_LINK_REJECTED')
        r.need(path.is_dir() or path.is_file(), 'DIST_SPECIAL_FILE_REJECTED')
    r.need(frontend_version() == r.FRONTEND and json.loads(r.local_bytes(dist / 'app-version.json'))['version'] == r.FRONTEND, 'EXACT_FRONTEND_BUILD_REQUIRED')
    payload = {'backend/' + name: r.local_bytes(Path('app/backend', name)) for name in r.BACKEND_FILES}
    for path in paths:
        if path.is_file():
            name = str(path.relative_to(dist)); r.need(static_path(name), 'DIST_PATH_REJECTED'); payload['static/' + name] = r.local_bytes(path)
    r.need({'static/index.html', 'static/app-version.json'} <= set(payload) and sum(map(len, payload.values())) < 64 * 1024 ** 2 and all(len(body) < 16 * 1024 ** 2 for body in payload.values()), 'BOUNDED_EXACT_PAYLOAD_REQUIRED')
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, body in sorted(payload.items()):
                item = tarfile.TarInfo(name); item.size = len(body); item.mode = 0o644; item.mtime = 0; archive.addfile(item, io.BytesIO(body))
    blob = output.getvalue()
    manifest = {'format_version': 1, 'source_sha': r.SOURCE_SHA, 'frontend_version': r.FRONTEND, 'baseline_source_sha': r.BASE_SOURCE, 'baseline_frontend_version': r.BASE_FRONTEND, 'old_schema_revision': r.OLD_REVISION, 'schema_revision': r.NEW_REVISION, 'additive_tables': [r.NEW_TABLE], 'database_migration': True, 'production_seed_rows': False, 'credentials_included': False, 'preflight_sha256': summary['sha256'], 'payload_sha256': H(blob), 'frontend_freeze_sha256': r.FRONTEND_FREEZE_SHA, 'backend_freeze_sha256': r.BACKEND_FREEZE_SHA, 'changed_source_files': sorted(changed), 'backend_before': backend_before, 'backend_after': {name: after['app/backend/' + name] for name in sorted(r.BACKEND_FILES)}, 'files': {name: H(body) for name, body in payload.items()}, 'protected_source_inventory': {name: pin for name, pin in before.items() if name not in changed}}
    return blob, manifest


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--preflight-summary', type=Path, required=True); parser.add_argument('--out', type=Path, required=True); args = parser.parse_args()
    blob, manifest = build(json.loads(r.local_bytes(args.preflight_summary, 1048576))); args.out.mkdir(parents=True, exist_ok=True)
    for name, body in {'payload.tar.gz': blob, 'manifest.json': r.encoded(manifest)}.items():
        with (args.out / name).open('xb') as stream: stream.write(body)
    print(json.dumps({'source_sha': r.SOURCE_SHA, 'frontend_version': r.FRONTEND, 'payload_sha256': H(blob), 'manifest_sha256': H(r.encoded(manifest)), 'database_migration': True, 'new_empty_tables': [r.NEW_TABLE]}))


if __name__ == '__main__': main()
