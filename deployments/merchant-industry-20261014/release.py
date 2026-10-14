#!/usr/bin/env python3
"""Merchant industry overlay using pinned, previously deployed release primitives.

No Alembic, SQL mutation, category backfill, or database restoration is performed.
Prepare rehearses both exact images on an offline DB copy. Activate briefly stops
CRM, swaps its backend and static root, and verifies all existing business rows.
Private API/worker configuration and schema must retain the reviewed identities.
"""
import argparse
import copy
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

BASELINE = '9c4efa19a71a9db0f66619070759f57df2e1a6d7'
BASELINE_SOURCE = '5c71dd9baa8121acf53dbde760ff8791ee85eb90'
BASELINE_FRONTEND = '69dec0425660'
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BASE_IMAGE = 'sha256:5bcf59cbf4e241877930fa7609a024a6e5d667e2972d1a5ec382a8e577290f58'
OLD_ID = 'baa4af93812c572ba27f578dd118ec5722fb44a2ae93b27cc4f904e57dd7d6a4'
OLD_PUBLIC = Path('/var/www/t24-crm-public/sales-enrichment-5c71dd9baa81-20261014')
NGINX = Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA = 'c37eeb25fc98f687fed45dbcda0be6bbf35f0202a14ee9d9695aaf7508b8853e'
BUSINESS = Path('/opt/t24-crm/app/data/crm_prod.db')
SCHEMA_HEAD = 'e6c0b4f8a916'
BACKEND = {'routers/merchant_pool.py', 'services/merchant_industries.py'}
FRONTEND = {'pages/MerchantPool.tsx', 'pages/merchant-pool-industries.css'}
PRESERVED = {'company_finance_formulas': True, 'close_conditions': True,
             'private_workspace': True, 'customer_invitation_rules': True,
             'commission_attribution': True, 'import_template': True}
LEGACY = Path('/opt/t24-crm/releases/sales-enrichment-5c71dd9baa81-20261014/release.py')
LEGACY_SHA = '7fb1bbfaf5dba42dde00c4a37cc4b69b1a0b85054ae8f3debef8d3bc670ce85d'
DOCKERIGNORE = b'*\n!Dockerfile\n!backend\n!backend/**\n'
_HELPERS = None
H = lambda body: hashlib.sha256(body).hexdigest()


def need(ok, code):
    if not ok:
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
        spec = importlib.util.spec_from_loader('_merchant_industry_legacy', loader=None)
        module = importlib.util.module_from_spec(spec)
        module.__file__ = str(LEGACY)
        exec(compile(body, str(LEGACY), 'exec'), module.__dict__)
        _HELPERS = module
    return _HELPERS


def safe_error(error):
    return str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+', str(error)) else type(error).__name__.upper()


def rows_unchanged(before, after):
    need(before == after, 'BUSINESS_SCHEMA_OR_ROWS_CHANGED')


def require_schema(path):
    snapshot = helpers().sql_snapshot(path)
    need('alembic_version' in snapshot and snapshot['alembic_version']['count'] == 1, 'SCHEMA_HEAD_REQUIRED')
    import sqlite3
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as database:
        need(database.execute('SELECT version_num FROM alembic_version').fetchall() == [(SCHEMA_HEAD,)], 'SCHEMA_HEAD_DRIFT')
    return snapshot


def boundary(pins, after_crm=None):
    helper = helpers()
    result = helper.private_boundary(pins)
    crm = helper.inspect('t24-crm')
    if after_crm:
        need(crm['Id'] == after_crm and crm['State']['Running'], 'CRM_CANDIDATE_NOT_RUNNING')
    else:
        need(crm['Id'] == OLD_ID and crm['Image'] == BASE_IMAGE and crm['State']['Running'], 'ORIGINAL_CRM_DRIFT')
        helper.require_safe_original_restart(crm)
    return result


def checked_manifest(release, args):
    helper = helpers()
    manifest = json.loads(read(release / 'manifest.json', args.manifest_sha256))
    read(release / 'payload.tar.gz', args.payload_sha256)
    need(manifest['format_version'] == 1 and manifest['payload_sha256'] == args.payload_sha256 and manifest['credentials_included'] is False, 'MANIFEST_SCOPE_REJECTED')
    need(manifest['baseline_source_sha'] == BASELINE and manifest['baseline_deployed_source_sha'] == BASELINE_SOURCE and manifest['baseline_frontend_version'] == BASELINE_FRONTEND, 'BASELINE_PINS_REQUIRED')
    need(bool(re.fullmatch('[a-f0-9]{40}', manifest['source_sha'])) and bool(re.fullmatch('[a-f0-9]{12}', manifest['frontend_version'])), 'SOURCE_PINS_REQUIRED')
    need(manifest['preserved'] == PRESERVED and manifest['database_schema_changes'] is False and manifest['production_row_changes'] is False, 'PRESERVED_BOUNDARY_REQUIRED')
    need(set(manifest['backend_before']) == BACKEND and set(manifest['backend_after']) == BACKEND, 'EXACT_BACKEND_SCOPE_REQUIRED')
    approved = {'app/backend/' + name for name in BACKEND} | {'app/frontend/src/' + name for name in FRONTEND}
    changed = set(manifest['changed_source_files'])
    tests = {name for name in changed if name.startswith('app/backend/tests/test_') or name.startswith('app/frontend/tests/')}
    need(changed - tests == approved, 'EXACT_SOURCE_SCOPE_REQUIRED')
    need(all((name.startswith('static/') and helper.static_path(name[7:])) or name in {'backend/' + path for path in BACKEND} for name in manifest['files']), 'PAYLOAD_SCOPE_REJECTED')
    need({'backend/' + name for name in BACKEND} <= set(manifest['files']), 'BACKEND_PAYLOAD_REQUIRED')
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


def offline_args(release, data, image):
    return ['docker', 'run', '--rm', '--network=none', '--read-only', '--tmpfs', '/tmp:rw,nosuid,noexec', '--env-file', str(release / 'crm.env'), '-e', 'DATABASE_URL=sqlite:///./data/crm_prod.db', '-e', 'AUTOMATION_SCAN_ENABLED=false', '--mount', 'type=bind,src=' + str(data) + ',dst=/app/backend/data', '--mount', 'type=bind,src=' + str(release / 'probe-logs') + ',dst=/app/backend/logs', image]


def build_image(release, manifest):
    helper = helpers()
    need(helper.local_image_id(BASE_IMAGE) == BASE_IMAGE, 'BASE_IMAGE_ID_DRIFT')
    tag = 't24-crm:merchant-industry-base-' + manifest['source_sha'][:12] + '-' + H(str(release).encode())[:12]
    existing = helper.local_image_id(tag)
    need(existing is None or existing == BASE_IMAGE, 'BASE_TAG_ID_DRIFT')
    if existing is None:
        helper.run(['docker', 'image', 'tag', BASE_IMAGE, tag], 'BASE_TAG_CREATE_FAILED')
    need(helper.local_image_id(tag) == BASE_IMAGE, 'BASE_TAG_ID_DRIFT')
    helper.write(release / 'Dockerfile', ('FROM ' + tag + '\nCOPY backend/ /app/backend/\n').encode())
    candidate_tag = 't24-crm:merchant-industry-' + manifest['source_sha'][:12]
    helper.run(['docker', 'build', '--network=none', '--pull=false', '-t', candidate_tag, str(release)], 'CANDIDATE_BUILD_FAILED', 300)
    need(helper.local_image_id(tag) == BASE_IMAGE, 'BASE_TAG_ID_DRIFT')
    return json.loads(helper.run(['docker', 'image', 'inspect', candidate_tag], 'CANDIDATE_IMAGE_INSPECTION_FAILED'))[0]['Id']


def prepare(release, args, manifest, pins):
    helper = helpers()
    boundary(pins)
    need(H(NGINX.read_bytes()) == NGINX_SHA, 'NGINX_BASELINE_DRIFT')
    need(not (release / 'prepared.json').exists(), 'PREPARATION_EXISTS')
    require_schema(BUSINESS)
    need(helper.inventory_in_container('t24-crm', BACKEND) == manifest['backend_before'], 'DEPLOYED_BACKEND_DIFFERS_FROM_BASELINE')
    extract(release, manifest)
    crm = helper.inspect('t24-crm')
    helper.write(release / 'original-container.json', crm)
    helper.environment_file(release, crm)
    helper.write(release / '.dockerignore', DOCKERIGNORE)
    image = build_image(release, manifest)
    data = release / 'probe-data'
    data.mkdir(mode=0o700)
    (release / 'probe-logs').mkdir(mode=0o700)
    helper.backup(BUSINESS, data / 'crm_prod.db')
    before = require_schema(data / 'crm_prod.db')
    for label, target_image, expected in [('candidate', image, manifest['backend_after']), ('rollback', BASE_IMAGE, manifest['backend_before'])]:
        name = 't24-merchant-industry-probe-' + label + '-' + manifest['source_sha'][:12]
        command = offline_args(release, data, target_image)
        command[2:2] = ['--name', name, '-d']
        helper.run(command, 'OFFLINE_STARTUP_FAILED')
        try:
            helper.ready(name)
            need(helper.inventory_in_container(name, BACKEND) == expected, 'OFFLINE_CODE_IDENTITY_DRIFT')
        finally:
            helper.run(['docker', 'stop', '-t', '20', name], 'OFFLINE_PROBE_STOP_FAILED')
        rows_unchanged(before, require_schema(data / 'crm_prod.db'))
    need(H(NGINX.read_bytes()) == NGINX_SHA, 'NGINX_CHANGED_DURING_PREPARATION')
    boundary(pins)
    public = Path('/var/www/t24-crm-public/merchant-industry-' + manifest['source_sha'][:12] + '-20261014')
    need(not public.exists(), 'FRESH_STATIC_ROOT_REQUIRED')
    helper.public_directory(public, public)
    for source in (release / 'static').rglob('*'):
        if source.is_file():
            target = public / source.relative_to(release / 'static')
            helper.public_directory(target.parent, public)
            target.write_bytes(source.read_bytes())
            target.chmod(0o644)
    # Existing tabs retain their old hashed JS/CSS URLs through the new root.
    for source in (OLD_PUBLIC / 'assets').rglob('*'):
        if source.is_file():
            target = public / 'assets' / source.relative_to(OLD_PUBLIC / 'assets')
            helper.public_directory(target.parent, public)
            if target.exists():
                need(H(target.read_bytes()) == H(source.read_bytes()), 'STATIC_ASSET_COLLISION')
            else:
                target.write_bytes(source.read_bytes())
                target.chmod(0o644)
    result = {'stage': 'MERCHANT_INDUSTRY_PREPARED_OFFLINE_VERIFIED', 'source_sha': manifest['source_sha'],
              'version': manifest['frontend_version'], 'candidate_image': image, 'rollback_image': BASE_IMAGE,
              'old_crm': helper.runtime(crm), 'public_root': str(public), 'business_rows_unchanged_in_rehearsal': True,
              'private_runtime_unchanged': True, 'schema_head': SCHEMA_HEAD, 'database_schema_changes': False,
              'manifest_sha256': args.manifest_sha256, 'payload_sha256': args.payload_sha256,
              'preflight_sha256': args.preflight_sha256}
    proof = helper.write(release / 'prepared.json', result)
    print(json.dumps({**result, 'receipt_sha256': proof}))


def prepared_receipt(release, args, manifest):
    receipt = json.loads(read(release / 'prepared.json', args.review_sha256))
    need(receipt['stage'] == 'MERCHANT_INDUSTRY_PREPARED_OFFLINE_VERIFIED' and receipt['manifest_sha256'] == args.manifest_sha256 and receipt['payload_sha256'] == args.payload_sha256 and receipt['preflight_sha256'] == args.preflight_sha256, 'PREPARED_IDENTITY_DRIFT')
    need(bool(re.fullmatch('sha256:[a-f0-9]{64}', receipt['candidate_image'])) and receipt['rollback_image'] == BASE_IMAGE, 'PREPARED_IMAGE_PINS_REQUIRED')
    need(receipt['source_sha'] == manifest['source_sha'] and receipt['version'] == manifest['frontend_version'] and receipt['schema_head'] == SCHEMA_HEAD and receipt['database_schema_changes'] is False, 'PREPARED_SOURCE_DRIFT')
    return receipt


def clone_config(image, original, source):
    helper = helpers()
    config = copy.deepcopy(original['Config'])
    config['Image'], config['Hostname'] = image, ''
    config['Labels'] = {**(config.get('Labels') or {}), 't24.release.scope': 'merchant-industry', 't24.release.source': source}
    config['HostConfig'] = copy.deepcopy(original['HostConfig'])
    config['HostConfig']['AutoRemove'] = False
    networks = helper.clone_networks(original)
    need(bool(networks) or original['HostConfig']['NetworkMode'] in ('host', 'none'), 'ORIGINAL_NETWORKS_REQUIRED')
    config['NetworkingConfig'] = {'EndpointsConfig': networks}
    return config


def docker_create(name, image, original, source):
    status, body = helpers().docker_request('POST', '/containers/create?name=' + name, clone_config(image, original, source))
    need(status == 201, 'CONTAINER_CREATE_FAILED')
    return json.loads(body)['Id']


def owned_release_container(info, receipt, manifest):
    labels = info.get('Config', {}).get('Labels') or {}
    return info['Image'] == receipt['candidate_image'] and labels.get('t24.release.scope') == 'merchant-industry' and labels.get('t24.release.source') == manifest['source_sha']


def cleanup_nginx_temp(original, updated):
    temporary = NGINX.parent / '.t24-merchant-industry-next'
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
    temporary = NGINX.parent / '.t24-merchant-industry-next'
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


def recovery_original(release, receipt):
    helper = helpers()
    original = json.loads(read(release / 'original-container.json'))
    existing = helper.inspect(OLD_ID)
    need(original['Id'] == OLD_ID and original['Image'] == BASE_IMAGE and helper.runtime(original) == receipt['old_crm'], 'ORIGINAL_SAVED_CONFIGURATION_DRIFT')
    need(existing['Id'] == OLD_ID and existing['Image'] == BASE_IMAGE and helper.runtime(existing)['config'] == receipt['old_crm']['config'], 'ORIGINAL_RETAINED_CONFIGURATION_DRIFT')
    return original


def rollback(release, receipt, manifest, pins, original_nginx, next_nginx, reason):
    helper = helpers()
    errors, restored, private_ok = [], None, False
    try:
        cleanup_nginx_temp(original_nginx, next_nginx)
        current = NGINX.read_bytes()
        if current == next_nginx:
            swap_nginx(next_nginx, original_nginx)
        else:
            need(current == original_nginx, 'ROLLBACK_NGINX_DRIFT')
            reload_nginx()
    except BaseException as error:
        errors.append('NGINX_' + safe_error(error))
    try:
        require_schema(BUSINESS)
        recovery_original(release, receipt)
        active = helper.inspect_optional('t24-crm')
        if active and active['Id'] != OLD_ID:
            need(owned_release_container(active, receipt, manifest), 'UNKNOWN_ACTIVE_CRM_CONTAINER')
            helper.run(['docker', 'stop', '-t', '20', active['Id']], 'FAILED_CANDIDATE_STOP_FAILED', 45)
            helper.run(['docker', 'rename', active['Id'], 't24-crm-failed-merchant-industry-' + manifest['source_sha'][:12] + '-' + active['Id'][:12]], 'FAILED_CANDIDATE_RETAIN_FAILED')
        existing = helper.inspect(OLD_ID)
        if existing['Name'] != '/t24-crm':
            helper.run(['docker', 'rename', OLD_ID, 't24-crm'], 'ORIGINAL_RENAME_FAILED')
        helper.run(['docker', 'start', OLD_ID], 'ROLLBACK_START_FAILED')
        helper.ready(OLD_ID)
        restored = OLD_ID
    except BaseException as error:
        errors.append('CRM_' + safe_error(error))
    try:
        helper.private_boundary(pins)
        private_ok = True
    except BaseException as error:
        errors.append('PRIVATE_' + safe_error(error))
    result = {'stage': 'ROLLBACK_INCOMPLETE' if errors else 'ROLLED_BACK', 'database_restored': False,
              'restored_crm_id': restored, 'private_runtime_unchanged': private_ok, 'reason_type': reason, 'failures': errors}
    helper.write(release / ('rollback-' + str(time.time_ns()) + '.json'), result)
    need(not errors, 'ROLLBACK_INCOMPLETE')
    return result


def recover(release, args, manifest, pins):
    helper = helpers()
    receipt = prepared_receipt(release, args, manifest)
    helper.private_boundary(pins)
    need(not (release / 'deployed.json').exists(), 'SUCCESSFUL_RELEASE_REQUIRES_SEPARATE_ROLLBACK_REVIEW')
    started = json.loads(read(release / 'activation-started.json'))
    need(started['prepared_sha256'] == args.review_sha256 and started['source_sha'] == manifest['source_sha'] and started['old_id'] == OLD_ID and started['candidate_image'] == receipt['candidate_image'], 'ACTIVATION_IDENTITY_DRIFT')
    original = read(release / 'nginx-before.conf')
    need(H(original) == NGINX_SHA, 'RECOVERY_NGINX_BASELINE_DRIFT')
    old_root = ('root ' + str(OLD_PUBLIC) + ';').encode()
    need(original.count(old_root) == 1, 'EXACT_STATIC_ROOT_REQUIRED')
    updated = original.replace(old_root, ('root ' + receipt['public_root'] + ';').encode())
    print(json.dumps(rollback(release, receipt, manifest, pins, original, updated, 'INTERRUPTED_ACTIVATION')))


def activate(release, args, manifest, pins):
    helper = helpers()
    receipt = prepared_receipt(release, args, manifest)
    _, _, base, _, _ = boundary(pins)
    need(H(NGINX.read_bytes()) == NGINX_SHA, 'NGINX_BASELINE_DRIFT')
    old = helper.inspect('t24-crm')
    helper.require_safe_original_restart(old)
    need(helper.runtime(old) == receipt['old_crm'], 'CRM_DRIFT_AFTER_REHEARSAL')
    original = json.loads(read(release / 'original-container.json'))
    need(helper.runtime(original) == helper.runtime(old), 'ORIGINAL_CONTAINER_DRIFT')
    public = Path(receipt['public_root'])
    need(json.loads((public / 'app-version.json').read_bytes())['version'] == manifest['frontend_version'], 'STATIC_VERSION_DRIFT')
    for name, expected in manifest['files'].items():
        if name.startswith('static/'):
            need(H((public / name[7:]).read_bytes()) == expected, 'STATIC_FILE_DRIFT')
    original_nginx = NGINX.read_bytes()
    old_root = ('root ' + str(OLD_PUBLIC) + ';').encode()
    need(original_nginx.count(old_root) == 1, 'EXACT_STATIC_ROOT_REQUIRED')
    next_nginx = original_nginx.replace(old_root, ('root ' + str(public) + ';').encode())
    helper.write(release / 'nginx-before.conf', original_nginx)
    retained = 't24-crm-before-merchant-industry-' + manifest['source_sha'][:12]
    helper.write(release / 'activation-started.json', {'stage': 'ACTIVATING', 'prepared_sha256': args.review_sha256,
                 'source_sha': manifest['source_sha'], 'old_id': OLD_ID, 'candidate_image': receipt['candidate_image'], 'retained_name': retained})
    try:
        helper.run(['docker', 'stop', '-t', '30', 't24-crm'], 'CRM_STOP_FAILED', 60)
        stopped = helper.inspect(OLD_ID)
        need(stopped['Id'] == OLD_ID and stopped['Image'] == BASE_IMAGE and not stopped['State']['Running'], 'CRM_NOT_STOPPED')
        helper.backup(BUSINESS, release / 'business-before.db')
        before = require_schema(BUSINESS)
        helper.write(release / 'business-before-digests.json', before)
        helper.run(['docker', 'rename', 't24-crm', retained], 'RETAIN_ORIGINAL_FAILED')
        candidate = docker_create('t24-crm', receipt['candidate_image'], original, manifest['source_sha'])
        helper.run(['docker', 'start', candidate], 'CANDIDATE_START_FAILED')
        helper.ready(candidate)
        need(helper.inventory_in_container(candidate, BACKEND) == manifest['backend_after'], 'LIVE_CODE_IDENTITY_DRIFT')
        rows_unchanged(before, require_schema(BUSINESS))
        boundary(pins, candidate)
        swap_nginx(original_nginx, next_nginx)
        base.public_check(base.file_map(public), manifest['frontend_version'], public, verify_services=False)
        helper.run(['curl', '-fsS', 'https://t24-crm.com/ready'], 'PUBLIC_CRM_NOT_READY')
        boundary(pins, candidate)
        result = {'stage': 'MERCHANT_INDUSTRY_DEPLOYED_VERIFIED', 'deployed': True, 'source_sha': manifest['source_sha'],
                  'frontend_version': manifest['frontend_version'], 'crm': helper.runtime(helper.inspect(candidate)),
                  'retained_original': retained, 'rollback_image': BASE_IMAGE, 'private_runtime_unchanged': True,
                  'business_schema_and_rows_unchanged_before_publication': True, 'database_schema_changes': False,
                  'production_row_changes': False, 'schema_head': SCHEMA_HEAD, 'public_root': str(public),
                  'new_nginx_sha256': H(next_nginx)}
        proof = helper.write(release / 'deployed.json', result)
        print(json.dumps({**result, 'receipt_sha256': proof}))
    except BaseException as error:
        rollback(release, receipt, manifest, pins, original_nginx, next_nginx, safe_error(error))
        raise


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
    descriptor = os.open('/opt/t24-crm/releases/.merchant-industry-release.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
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
        print(json.dumps({'stage': 'MERCHANT_INDUSTRY_RELEASE_REJECTED', 'code': safe_error(error)}))
        sys.exit(1)
