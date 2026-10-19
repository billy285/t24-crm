#!/usr/bin/env python3
"""Freeze only the reviewed daily scan/reminder source and its frontend build."""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('stripe_history_daily_scan_release', Path(__file__).with_name('release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
SOURCE, BASE, BACKEND = release.SOURCE, release.BASELINE, release.BACKEND
H = lambda body: hashlib.sha256(body).hexdigest()
EXPECTED_BACKEND = {
    'main.py', 'models/stripe_history_daily_scan.py',
    'services/stripe_history_daily_scan.py', 'routers/stripe_history_reconciliation.py',
    'alembic/versions/e2b6c0f8a345_stripe_history_daily_scan.py',
}
EXPECTED_NEW_BACKEND = EXPECTED_BACKEND - {'main.py', 'routers/stripe_history_reconciliation.py'}
EXPECTED_FRONTEND = {
    'components/ServiceFollowThrough.tsx', 'components/StripeHistoryReconciliation.tsx',
    'components/StripeHistoryReminders.tsx', 'components/stripe-history-reminders.css',
    'lib/stripe-history-reminders.ts',
}
EXPECTED_TESTS = {
    'app/backend/tests/test_stripe_history_daily_scan.py',
    'app/frontend/tests/stripe-history-reminders.spec.ts',
    'app/frontend/tests/stripe-history-reminders.unit.test.mjs',
}


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def git(*args):
    return subprocess.check_output(['git', *args])


def inventory(ref):
    return {name: H(git('show', ref + ':' + name))
            for name in git('ls-tree', '-r', '--name-only', ref, '--', 'app/').decode().splitlines()}


def source_version():
    node = '/Users/billyli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script = """const fs=require('node:fs'),path=require('node:path'),c=require('node:crypto'),h=c.createHash('sha256'),root=process.argv[1];function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(e.isSymbolicLink())throw Error('symlink');const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(e.isFile()){h.update(path.relative(root,p));h.update(fs.readFileSync(p));}}}walk(root);process.stdout.write(h.digest('hex').slice(0,12));"""
    return subprocess.check_output([node, '-e', script, str(Path('app/frontend/src').resolve())]).decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    need(SOURCE == '285c3377e6d04765116ef553a7692933ad9815b0'
         and BASE == 'fd1ae7239330a418e6d2df44b0fb7fcb632d2567'
         and args.source == SOURCE
         and bool(re.fullmatch('[a-f0-9]{64}', release.LIVE_PREFLIGHT_SHA))
         and release.FRONTEND_VERSION == '0f8ad5c23245', 'FROZEN_SOURCE_AND_PREFLIGHT_REQUIRED')
    need(set(BACKEND) == EXPECTED_BACKEND and set(release.FRONTEND) == EXPECTED_FRONTEND
         and set(release.TESTS) == EXPECTED_TESTS, 'EXACT_DAILY_SCAN_FILE_ALLOWLIST_REQUIRED')
    need(release.OLD_REVISION == 'd1a5b9e7f234' and release.REVISION == 'e2b6c0f8a345', 'EXACT_SINGLE_TABLE_MIGRATION_REQUIRED')
    before, after = inventory(BASE), inventory(SOURCE)
    # A later deployment-tools carrier may be HEAD, but its app tree must be identical.
    need(inventory('HEAD') == after, 'SOURCE_HEAD_APPLICATION_DRIFT')
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    frontend = {'app/frontend/src/' + name for name in EXPECTED_FRONTEND}
    expected_changes = {'app/backend/' + name for name in EXPECTED_BACKEND} | frontend | EXPECTED_TESTS
    need(len(changed) == 13 and changed == expected_changes, 'EXACT_SOURCE_SCOPE_REQUIRED')
    for path, value in after.items():
        target = Path(path)
        need(target.is_file() and not target.is_symlink() and H(target.read_bytes()) == value, 'WORKING_TREE_DRIFT')
    need(before['app/frontend/src/pages/Finance.tsx'] == after['app/frontend/src/pages/Finance.tsx'], 'ORIGINAL_FINANCE_SOURCE_CHANGED')
    missing_before = {name for name in EXPECTED_BACKEND if 'app/backend/' + name not in before}
    need(missing_before == EXPECTED_NEW_BACKEND, 'EXACT_NEW_RUNTIME_FILES_REQUIRED')
    need(source_version() == release.FRONTEND_VERSION == json.loads(Path('app/frontend/dist/app-version.json').read_bytes())['version'], 'EXACT_FRONTEND_BUILD_REQUIRED')

    payload = {'backend/' + name: Path('app/backend', name).read_bytes() for name in EXPECTED_BACKEND}
    for path in Path('app/frontend/dist').rglob('*'):
        need(not path.is_symlink(), 'DIST_LINK_REJECTED')
        if path.is_file():
            name = str(path.relative_to('app/frontend/dist'))
            need(release.static_path(name), 'DIST_PATH_REJECTED')
            payload['static/' + name] = path.read_bytes()
    need(sum(map(len, payload.values())) < 64 * 1024**2
         and all(len(body) < 16 * 1024**2 for body in payload.values()), 'PAYLOAD_LIMIT')
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, filename='') as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for path, body in sorted(payload.items()):
                member = tarfile.TarInfo(path)
                member.size, member.mode, member.mtime = len(body), 0o644, 0
                archive.addfile(member, io.BytesIO(body))
    manifest = {
        'format_version': 1, 'source_sha': SOURCE, 'baseline_source_sha': BASE,
        'baseline_application_source': release.BASELINE_APPLICATION_SOURCE,
        'frontend_version': release.FRONTEND_VERSION, 'baseline_frontend_version': release.BASELINE_FRONTEND,
        'old_schema_revision': release.OLD_REVISION, 'schema_revision': release.REVISION,
        'additive_tables': ['stripe_history_scan_states'], 'production_seed_rows': False,
        'backend_only': False, 'static_transition': True,
        'live_preflight_sha256': release.LIVE_PREFLIGHT_SHA,
        'baseline_backend_inventory_sha256': release.BASE_BACKEND_SHA,
        'payload_sha256': H(buffer.getvalue()), 'credentials_included': False,
        'preserved': release.PRESERVED,
        'files': {path: H(body) for path, body in payload.items()},
        'backend_before': {name: before.get('app/backend/' + name) for name in sorted(EXPECTED_BACKEND)},
        'backend_after': {name: after['app/backend/' + name] for name in sorted(EXPECTED_BACKEND)},
        'changed_source_files': sorted(changed),
        'protected_source_inventory': {path: value for path, value in before.items() if path not in changed},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    for name, body in {
        'payload.tar.gz': buffer.getvalue(),
        'manifest.json': (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode(),
    }.items():
        with (args.out / name).open('xb') as stream:
            stream.write(body)
    print(json.dumps({'source': SOURCE, 'backend_files': len(EXPECTED_BACKEND),
                      'payload_sha256': manifest['payload_sha256'],
                      'manifest_sha256': H((args.out / 'manifest.json').read_bytes())}))


if __name__ == '__main__':
    main()
