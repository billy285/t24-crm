#!/usr/bin/env python3
"""Publish only sales calling controls static assets; no service or DB mutation.

Prepare stages exact immutable assets while keeping the live root unchanged.
Activate requires the reviewed prepared receipt and only replaces the nginx root.
CRM/private containers and database identities/schemas must remain identical.
Legitimate concurrent business row changes do not authorize any DB restoration.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import re
import socket
import stat
import sys
import tarfile
import time
from pathlib import Path

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BASELINE = '74b1cf1cd96e4880301dfa7e4c40e72acc8cad1e'
BASELINE_SOURCE = 'c8f595126bf48108bbbc1637a3de1e3d4bff8bd5'
BASELINE_FRONTEND = '18302b0ab935'
OLD_PUBLIC = Path('/var/www/t24-crm-public/merchant-industry-labels-c8f595126bf4-20261014')
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA = '38cda37c9507a5b51004a522a210f52067288cc9c3b492cfd2ff51bb1adc7ba0'
BASE_CRM = {'id': '06716fe2398628a3f19103ca8b6c3d60ae58f63621d395b0bed8de0231c31915',
            'image': 'sha256:c538ec8a7ae0f1f715c2cd6c9b221e8614f3040039217ade4fc5d8f650acce27',
            'started': '2026-10-14T04:21:50.177236651Z', 'restart': 0,
            'config': '04d335218786997a6b9a7d2741fe485b1f03af8d8e5cceb24905cb049d287f61'}
FRONTEND = {'pages/SalesWorkbench.tsx', 'components/SalesCallRecord.tsx', 'pages/sales-calling-controls.css'}
PRESERVED = {'company_finance_formulas': True, 'close_conditions': True,
             'private_workspace': True, 'customer_invitation_rules': True,
             'commission_attribution': True, 'import_template': True}
LEGACY = Path('/opt/t24-crm/releases/sales-enrichment-5c71dd9baa81-20261014/release.py')
LEGACY_SHA = '7fb1bbfaf5dba42dde00c4a37cc4b69b1a0b85054ae8f3debef8d3bc670ce85d'
_HELPERS = None
H = lambda body: hashlib.sha256(body).hexdigest()


def need(value, code):
    if not value:
        raise RuntimeError(code)


def read(path, expected=None):
    path = Path(path)
    info = path.lstat()
    need(path.resolve() == path and stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and not info.st_mode & 0o077, 'PROTECTED_FILE_REQUIRED')
    body = path.read_bytes()
    need(not expected or H(body) == expected, 'FILE_HASH_DRIFT')
    return body


def helpers():
    global _HELPERS
    body = read(LEGACY, LEGACY_SHA)
    if _HELPERS is None:
        spec = importlib.util.spec_from_loader('_sales_controls_legacy', loader=None)
        module = importlib.util.module_from_spec(spec)
        module.__file__ = str(LEGACY)
        exec(compile(body, str(LEGACY), 'exec'), module.__dict__)
        _HELPERS = module
    return _HELPERS


def safe_error(error):
    return str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+', str(error)) else type(error).__name__.upper()


def stable_databases(snapshot):
    need(isinstance(snapshot, dict), 'DATABASE_SNAPSHOT_REQUIRED')
    result = {}
    for label in ('business', 'private'):
        row = snapshot.get(label)
        need(isinstance(row, dict) and isinstance(row.get('identity'), dict) and bool(row['identity']) and isinstance(row.get('schema_objects'), dict) and bool(row['schema_objects']) and isinstance(row.get('schema_sha256'), str) and bool(re.fullmatch('[a-f0-9]{64}', row['schema_sha256'])) and isinstance(row.get('tables'), dict) and bool(row['tables']), 'DATABASE_IDENTITY_AND_SCHEMA_REQUIRED')
        columns = {}
        for table, entry in row['tables'].items():
            need(isinstance(entry, dict) and isinstance(entry.get('columns_sha256'), str) and bool(re.fullmatch('[a-f0-9]{64}', entry['columns_sha256'])), 'DATABASE_COLUMN_PROOF_REQUIRED')
            columns[table] = entry['columns_sha256']
        result[label] = {'identity': row['identity'], 'schema_objects': row['schema_objects'],
                         'schema_sha256': row['schema_sha256'], 'columns': columns}
    return result


def boundary(pins):
    helper = helpers()
    _, _, base, preparation, _ = helper.private_boundary(pins)
    crm = helper.inspect('t24-crm')
    need(crm['State']['Running'] and helper.runtime(crm) == BASE_CRM, 'CRM_RUNTIME_MUST_REMAIN_IDENTICAL')
    snapshot = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
    return {'crm': helper.runtime(crm), 'databases': stable_databases(snapshot)}


def checked_manifest(release, args):
    helper = helpers()
    manifest = json.loads(read(release / 'manifest.json', args.manifest_sha256))
    read(release / 'payload.tar.gz', args.payload_sha256)
    need(manifest['format_version'] == 1 and manifest['payload_sha256'] == args.payload_sha256, 'MANIFEST_IDENTITY_REQUIRED')
    need(manifest['baseline_source_sha'] == BASELINE and manifest['baseline_deployed_source_sha'] == BASELINE_SOURCE and manifest['baseline_frontend_version'] == BASELINE_FRONTEND, 'BASELINE_PINS_REQUIRED')
    need(bool(re.fullmatch('[a-f0-9]{40}', manifest['source_sha'])) and bool(re.fullmatch('[a-f0-9]{12}', manifest['frontend_version'])) and manifest['frontend_version'] != BASELINE_FRONTEND, 'NEW_FRONTEND_SOURCE_REQUIRED')
    need(manifest['preserved'] == PRESERVED and manifest['static_only'] is True and all(manifest[key] is False for key in ('credentials_included', 'database_schema_changes', 'production_row_changes', 'backend_changes', 'services_modified', 'environment_modified')), 'PURE_STATIC_SCOPE_REQUIRED')
    need(manifest['backend_before'] == {} and manifest['backend_after'] == {}, 'NO_BACKEND_OVERLAY_ALLOWED')
    changed = set(manifest['changed_source_files'])
    tests = {name for name in changed if name.startswith('app/frontend/tests/')}
    need(changed - tests == {'app/frontend/src/' + name for name in FRONTEND}, 'EXACT_SALES_CONTROLS_SOURCE_SCOPE_REQUIRED')
    protected = manifest['protected_source_inventory']
    need(isinstance(protected, dict) and bool(protected) and any(name.startswith('app/backend/') for name in protected) and all(isinstance(value, str) and bool(re.fullmatch('[a-f0-9]{64}', value)) for value in protected.values()), 'PROTECTED_SOURCE_INVENTORY_REQUIRED')
    need({'static/index.html', 'static/app-version.json'} <= set(manifest['files']) and all(name.startswith('static/') and helper.static_path(name[7:]) for name in manifest['files']), 'ONLY_STATIC_PAYLOAD_ALLOWED')
    return manifest


def extract(release, manifest):
    helper = helpers()
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(read(release / 'payload.tar.gz')), mode='r:gz') as archive:
        for item in archive:
            name, path = item.name, Path(item.name)
            need(item.isfile() and not path.is_absolute() and '..' not in path.parts and str(path) == name and not any(part.startswith('.') for part in path.parts) and name in manifest['files'] and name not in seen and item.size < 16 * 1024 ** 2, 'PAYLOAD_MEMBER_REJECTED')
            body = archive.extractfile(item).read()
            need(H(body) == manifest['files'][name], 'PAYLOAD_HASH_DRIFT')
            target = release / path
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            helper.write(target, body)
            seen.add(name)
    need(seen == set(manifest['files']), 'PAYLOAD_INCOMPLETE')
    need(json.loads((release / 'static/app-version.json').read_bytes())['version'] == manifest['frontend_version'], 'PAYLOAD_VERSION_DRIFT')


def public_check(public, manifest):
    _, _, base, _, _ = helpers().tools()
    base.public_check(base.file_map(public), manifest['frontend_version'], public, verify_services=False)


def prepare(release, args, manifest, pins):
    helper = helpers()
    before = boundary(pins)
    need(H(NGINX.read_bytes()) == NGINX_SHA, 'NGINX_BASELINE_DRIFT')
    need(not (release / 'prepared.json').exists(), 'PREPARATION_EXISTS')
    extract(release, manifest)
    public = Path('/var/www/t24-crm-public/sales-controls-' + manifest['source_sha'][:12] + '-20261014')
    need(not public.exists(), 'FRESH_STATIC_ROOT_REQUIRED')
    helper.public_directory(public, public)
    for source in (release / 'static').rglob('*'):
        if source.is_file():
            target = public / source.relative_to(release / 'static')
            helper.public_directory(target.parent, public)
            target.write_bytes(source.read_bytes())
            target.chmod(0o644)
    for source in (OLD_PUBLIC / 'assets').rglob('*'):
        if source.is_file():
            target = public / 'assets' / source.relative_to(OLD_PUBLIC / 'assets')
            helper.public_directory(target.parent, public)
            if target.exists():
                need(H(target.read_bytes()) == H(source.read_bytes()), 'STATIC_ASSET_COLLISION')
            else:
                target.write_bytes(source.read_bytes())
                target.chmod(0o644)
    need(H(NGINX.read_bytes()) == NGINX_SHA, 'NGINX_CHANGED_DURING_PREPARATION')
    need(boundary(pins) == before, 'RUNTIME_OR_DATABASE_SCHEMA_CHANGED')
    result = {'stage': 'SALES_CONTROLS_PREPARED_STATIC_VERIFIED', 'source_sha': manifest['source_sha'],
              'version': manifest['frontend_version'], 'public_root': str(public), 'boundary': before,
              'crm_runtime_unchanged': True, 'private_runtime_unchanged': True,
              'database_schema_changes': False, 'production_row_changes': False, 'services_modified': False,
              'manifest_sha256': args.manifest_sha256, 'payload_sha256': args.payload_sha256,
              'preflight_sha256': args.preflight_sha256, 'old_nginx_sha256': NGINX_SHA}
    proof = helper.write(release / 'prepared.json', result)
    print(json.dumps({**result, 'receipt_sha256': proof}))


def prepared_receipt(release, args, manifest):
    receipt = json.loads(read(release / 'prepared.json', args.review_sha256))
    need(receipt['stage'] == 'SALES_CONTROLS_PREPARED_STATIC_VERIFIED' and receipt['source_sha'] == manifest['source_sha'] and receipt['version'] == manifest['frontend_version'] and receipt['manifest_sha256'] == args.manifest_sha256 and receipt['payload_sha256'] == args.payload_sha256 and receipt['preflight_sha256'] == args.preflight_sha256 and receipt['old_nginx_sha256'] == NGINX_SHA, 'PREPARED_IDENTITY_DRIFT')
    need(receipt['boundary']['crm'] == BASE_CRM and receipt['crm_runtime_unchanged'] is True and receipt['private_runtime_unchanged'] is True and all(receipt[key] is False for key in ('database_schema_changes', 'production_row_changes', 'services_modified')), 'PREPARED_PRESERVATION_REQUIRED')
    expected = '/var/www/t24-crm-public/sales-controls-' + manifest['source_sha'][:12] + '-20261014'
    need(receipt['public_root'] == expected, 'EXACT_STATIC_ROOT_REQUIRED')
    return receipt


def cleanup_nginx_temp(original, updated):
    temporary = NGINX.parent / '.t24-sales-controls-next'
    if not temporary.exists() and not temporary.is_symlink():
        return
    need(NGINX.read_bytes() in (original, updated), 'NGINX_RECOVERY_DRIFT')
    before = temporary.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1 and not before.st_mode & 0o022, 'UNKNOWN_NGINX_RECOVERY_TEMP')
    descriptor = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        need((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'NGINX_RECOVERY_TEMP_CHANGED')
        content = stream.read(max(len(original), len(updated)) + 1)
    need(any(value.startswith(content) for value in (original, updated)), 'UNKNOWN_NGINX_RECOVERY_TEMP')
    after = temporary.lstat()
    need((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns), 'NGINX_RECOVERY_TEMP_CHANGED')
    temporary.unlink()


def replace_nginx(original, updated):
    need(NGINX.read_bytes() == original, 'NGINX_CONCURRENT_CHANGE')
    temporary = NGINX.parent / '.t24-sales-controls-next'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(updated)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, NGINX)


def reload_nginx():
    helper = helpers()
    helper.run(['nginx', '-t'], 'NGINX_TEST_FAILED')
    helper.run(['systemctl', 'reload', 'nginx'], 'NGINX_RELOAD_FAILED')


def swap_nginx(original, updated):
    replace_nginx(original, updated)
    try:
        reload_nginx()
    except BaseException:
        try:
            replace_nginx(updated, original)
            reload_nginx()
        except BaseException as error:
            raise RuntimeError('NGINX_SWAP_AND_RESTORE_FAILED') from error
        raise


def rollback(release, receipt, manifest, pins, original, updated, reason):
    helper = helpers()
    errors = []
    try:
        cleanup_nginx_temp(original, updated)
        current = NGINX.read_bytes()
        if current == updated:
            swap_nginx(updated, original)
        else:
            need(current == original, 'ROLLBACK_NGINX_DRIFT')
            reload_nginx()
    except BaseException as error:
        errors.append('NGINX_' + safe_error(error))
    try:
        need(boundary(pins) == receipt['boundary'], 'RUNTIME_OR_DATABASE_SCHEMA_CHANGED')
    except BaseException as error:
        errors.append('BOUNDARY_' + safe_error(error))
    result = {'stage': 'SALES_CONTROLS_ROLLBACK_INCOMPLETE' if errors else 'SALES_CONTROLS_ROLLED_BACK',
              'database_restored': False, 'services_modified': False, 'reason_type': reason, 'failures': errors}
    helper.write(release / ('rollback-' + str(time.time_ns()) + '.json'), result)
    need(not errors, 'STATIC_ROLLBACK_INCOMPLETE')
    return result


def next_nginx(receipt):
    original = NGINX.read_bytes()
    need(H(original) == NGINX_SHA, 'NGINX_BASELINE_DRIFT')
    old_root = ('root ' + str(OLD_PUBLIC) + ';').encode()
    need(original.count(old_root) == 1, 'EXACT_OLD_STATIC_ROOT_REQUIRED')
    return original, original.replace(old_root, ('root ' + receipt['public_root'] + ';').encode())


def activate(release, args, manifest, pins):
    helper = helpers()
    receipt = prepared_receipt(release, args, manifest)
    need(boundary(pins) == receipt['boundary'], 'RUNTIME_OR_DATABASE_SCHEMA_CHANGED')
    public = Path(receipt['public_root'])
    for name, expected in manifest['files'].items():
        need(H((public / name[7:]).read_bytes()) == expected, 'STATIC_FILE_DRIFT')
    need(json.loads((public / 'app-version.json').read_bytes())['version'] == manifest['frontend_version'], 'STATIC_VERSION_DRIFT')
    original, updated = next_nginx(receipt)
    helper.write(release / 'nginx-before.conf', original)
    helper.write(release / 'activation-started.json', {'stage': 'ACTIVATING_STATIC', 'prepared_sha256': args.review_sha256, 'source_sha': manifest['source_sha']})
    try:
        need(boundary(pins) == receipt['boundary'], 'RUNTIME_OR_DATABASE_SCHEMA_CHANGED')
        swap_nginx(original, updated)
        public_check(public, manifest)
        helper.run(['curl', '-fsS', 'https://t24-crm.com/ready'], 'PUBLIC_CRM_NOT_READY')
        need(boundary(pins) == receipt['boundary'], 'RUNTIME_OR_DATABASE_SCHEMA_CHANGED')
        result = {'stage': 'SALES_CONTROLS_DEPLOYED_STATIC_VERIFIED', 'deployed': True, 'source_sha': manifest['source_sha'],
                  'frontend_version': manifest['frontend_version'], 'crm': receipt['boundary']['crm'],
                  'crm_runtime_unchanged': True, 'private_runtime_unchanged': True,
                  'same_database_identity_and_schema': True, 'database_schema_changes': False,
                  'production_row_changes': False, 'database_restored': False, 'services_modified': False,
                  'public_root': str(public), 'new_nginx_sha256': H(updated)}
        proof = helper.write(release / 'deployed.json', result)
        print(json.dumps({**result, 'receipt_sha256': proof}))
    except BaseException as error:
        rollback(release, receipt, manifest, pins, original, updated, safe_error(error))
        raise


def recover(release, args, manifest, pins):
    receipt = prepared_receipt(release, args, manifest)
    need(not (release / 'deployed.json').exists(), 'SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_ROLLBACK_REVIEW')
    started = json.loads(read(release / 'activation-started.json'))
    need(started['prepared_sha256'] == args.review_sha256 and started['source_sha'] == manifest['source_sha'], 'ACTIVATION_IDENTITY_DRIFT')
    original = read(release / 'nginx-before.conf')
    need(H(original) == NGINX_SHA, 'RECOVERY_NGINX_BASELINE_DRIFT')
    old_root = ('root ' + str(OLD_PUBLIC) + ';').encode()
    need(original.count(old_root) == 1, 'EXACT_OLD_STATIC_ROOT_REQUIRED')
    updated = original.replace(old_root, ('root ' + receipt['public_root'] + ';').encode())
    print(json.dumps(rollback(release, receipt, manifest, pins, original, updated, 'INTERRUPTED_ACTIVATION')))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['prepare', 'activate', 'recover'], required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--payload-sha256', required=True)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--preflight-sha256', required=True)
    parser.add_argument('--review-sha256')
    args = parser.parse_args()
    need(socket.gethostname() == HOST and os.geteuid() == 0, 'EXACT_SERVER_ROOT_REQUIRED')
    os.umask(0o077)
    sys.dont_write_bytecode = True
    need(args.release.resolve() == args.release and args.release.parent == Path('/opt/t24-crm/releases') and args.release.stat().st_uid == 0 and stat.S_IMODE(args.release.stat().st_mode) == 0o700, 'PROTECTED_RELEASE_REQUIRED')
    descriptor = os.open('/opt/t24-crm/releases/.sales-controls-release.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest = checked_manifest(args.release, args)
    pins = json.loads(read(args.preflight, args.preflight_sha256))
    if args.phase == 'prepare':
        prepare(args.release, args, manifest, pins)
    else:
        need(bool(args.review_sha256), 'INDEPENDENT_PREPARE_RECEIPT_REQUIRED')
        (activate if args.phase == 'activate' else recover)(args.release, args, manifest, pins)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(json.dumps({'stage': 'SALES_CONTROLS_RELEASE_REJECTED', 'code': safe_error(error)}))
        sys.exit(1)
