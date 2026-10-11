#!/usr/bin/env python3
"""Apply the frozen private Stripe report release without restoring either DB.

The CRM container and database are never writable deployment targets. The only
schema change is an independently rehearsed private ten-to-eleven-table addition.
Failures switch to the rehearsed schema-compatible private rollback image and
retain the current database, credentials and encrypted report cache.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import sqlite3
import stat
import sys
import urllib.error
import urllib.request
from uuid import uuid4

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE = 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
BASE_SOURCE = '3c5b8c1d63b8f078e162e228750b508715699479'
BASE_IMAGE = 'sha256:322968e1935a6f7bb2e6d366a9f1cdb98aefab392af28c7269660ff46262a886'
RELEASE = Path('/opt/t24-crm/releases/stripe-report-c1ae19b38fec-20261012')
NAV_HELPER = Path('/opt/t24-crm/releases/private-navigation-823cf7a43c88-20261011/static_only_upgrade.py')
NAV_HASH = '0c42a56a6f602f45e58e48f3635f076c2c6db1b502096e6cc0ca80ec162c469a'
OLD_PUBLIC = Path('/var/www/t24-crm-public/private-navigation-823cf7a43c88-20261011')
OLD_VERSION = 'a9b66e086cb0'
OLD_NGINX = 'cb088d05aa0c85424ec99079f81a7a4f30c44fa7f8effb8a2ffaae41ba03f42e'
ENV_HASH = '180f945729234df79c45f5148663f8407c75be55aa8d4e79107305c03c00f82d'
HASH = re.compile('[a-f0-9]{64}')
IMAGE = re.compile('sha256:[a-f0-9]{64}')
TEN_TABLES = frozenset({'private_connections', 'private_items', 'private_preferences', 'private_sync_runs',
    'private_mail_translations', 'private_translation_usage', 'private_mail_briefs', 'private_mail_brief_usage',
    'private_workspace_briefs', 'private_bank_links'})


class UpgradeError(RuntimeError):
    pass


def need(condition, code):
    if not condition:
        raise UpgradeError(code)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def safe_error(error):
    allowed = isinstance(error, UpgradeError) or type(error).__name__ in {'StaticError', 'SwitchError', 'PreparationError', 'PrepareError', 'GuardError', 'TransferError'}
    return str(error) if allowed and re.fullmatch('[A-Z0-9_]{1,100}', str(error)) else 'STRIPE_REPORT_UPGRADE_FAILED'


def protected(path, directory=False):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_PROTECTED_PATH_REQUIRED')
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, 'PROTECTED_ANCESTOR_REQUIRED')
    info = path.lstat()
    need(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
         and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
         'ROOT_PRIVATE_FILE_OR_DIRECTORY_REQUIRED')
    return info


def file_stamp(info):
    # Reading can update atime. All identity, ownership, protection, length and
    # mutation metadata remain pinned before/opened/after the bounded read.
    return tuple(getattr(info, name) for name in (
        'st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def read_protected(path, maximum=4 * 1024**2):
    before = protected(path)
    need(before.st_size <= maximum, 'PROTECTED_FILE_SIZE_LIMIT')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        need(file_stamp(before) == file_stamp(opened), 'PROTECTED_FILE_IDENTITY_CHANGED')
        data = stream.read(maximum + 1)
    need(len(data) <= maximum and file_stamp(protected(path)) == file_stamp(before), 'PROTECTED_FILE_CHANGED_DURING_READ')
    return data


def fixed_json(path, expected):
    need(HASH.fullmatch(expected or ''), 'REVIEWED_RECEIPT_HASH_REQUIRED')
    data = read_protected(path)
    need(sha(data) == expected, 'FIXED_RECEIPT_HASH_DRIFT')
    value = json.loads(data)
    need(isinstance(value, dict), 'OBJECT_RECEIPT_REQUIRED')
    return value


def load_module(path, name):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec and spec.loader, 'VERIFIED_HELPER_LOADER_REQUIRED')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def retained_tools(release):
    need(sha(read_protected(NAV_HELPER, 1024**2)) == NAV_HASH, 'RETAINED_NAVIGATION_HELPER_DRIFT')
    nav = load_module(NAV_HELPER, '_stripe_report_retained_navigation')
    base = nav.retained_tools()  # All financial primitives are hash-checked before import.
    acquired = json.loads(read_protected(release / 'acquired.json'))
    need(acquired.get('stage') == 'STRIPE_REPORT_CARRIER_ACQUIRED' and acquired.get('directory') == str(release)
         and acquired.get('frontend_source_sha') == SOURCE, 'REVIEWED_CARRIER_ACQUISITION_REQUIRED')
    files = acquired.get('files', {})
    for name in ('prepare_candidate.py', 'upgrade.py'):
        need(HASH.fullmatch(files.get(name, '')) and sha(read_protected(release / name, 1024**2)) == files[name],
             'ACQUIRED_RELEASE_HELPER_DRIFT')
    preparation = load_module(release / 'prepare_candidate.py', '_stripe_report_preparation')
    import switch_completed
    return base, nav, preparation, switch_completed


def checked_candidate(candidate, manifest):
    need(candidate.get('format_version') == 1 and candidate.get('stage') == 'STRIPE_REPORT_BACKEND_CANDIDATE_VERIFIED'
         and candidate.get('source_sha') == SOURCE and candidate.get('baseline_private_source_sha') == BASE_SOURCE
         and candidate.get('base_image_id') == BASE_IMAGE, 'EXACT_REHEARSED_CANDIDATE_REQUIRED')
    need(all(candidate.get(key) is True for key in ('rollback_model_only', 'base_layers_verified',
         'base_pin_verified_before_and_after_build', 'all_other_backend_bytes_identical',
         'all_runtime_package_bytes_identical', 'bundled_static_bytes_unchanged')), 'RETAINED_RUNTIME_BYTES_REQUIRED')
    need(all(candidate.get(key) is False for key in ('production_environment_loaded', 'production_database_access',
         'production_services_modified', 'public_assets_published', 'deployed')), 'ISOLATED_PREPARATION_REQUIRED')
    images = [candidate.get('image_id', ''), candidate.get('rollback_image_id', '')]
    need(all(IMAGE.fullmatch(value) for value in images) and len(set([BASE_IMAGE, *images])) == 3, 'DISTINCT_REVIEWED_IMAGES_REQUIRED')
    regressions = candidate.get('regressions', {})
    need(type(regressions.get('tests')) is int and type(regressions.get('minimum')) is int
         and regressions['tests'] >= regressions['minimum'] >= 1173 and regressions.get('python') == '3.10.22'
         and regressions.get('network') == 'none' and regressions.get('all_private_tests') == manifest.get('private_tests')
         and HASH.fullmatch(regressions.get('xml_sha256', '')), 'COMPLETE_PRIVATE_REGRESSIONS_REQUIRED')
    schema = candidate.get('synthetic_schema', {})
    need(schema.get('stage') == 'STRIPE_REPORT_SYNTHETIC_SCHEMA_AND_ROLLBACK_VERIFIED'
         and set(schema.get('tables', [])) == TEN_TABLES | {'private_stripe_reports'}
         and schema.get('base_image_id') == BASE_IMAGE and schema.get('candidate_image_id') == images[0]
         and schema.get('rollback_image_id') == images[1], 'REHEARSED_ELEVEN_TABLE_SCHEMA_REQUIRED')
    need(all(schema.get(key) is True for key in ('original_rows_columns_indexes_preserved', 'new_cache_initially_empty',
         'compatible_old_api_started_and_owner_read', 'encrypted_existing_credentials_decrypted',
         'populated_encrypted_report_cache_preserved', 'business_physically_readonly_for_init_and_read', 'business_unchanged'))
         and schema.get('production_database_access') is False, 'DATA_PRESERVING_COMPATIBLE_ROLLBACK_REQUIRED')
    objects = schema.get('schema_objects')
    need(isinstance(objects, dict) and {name for name, row in objects.items() if row.get('type') == 'table'}
         == TEN_TABLES | {'private_stripe_reports'}, 'EXACT_TARGET_SCHEMA_REQUIRED')
    return candidate


def checked_payload(payload, manifest, base):
    need(payload.is_dir() and payload.resolve() == payload and not payload.is_symlink(), 'FROZEN_PAYLOAD_DIRECTORY_REQUIRED')
    found = {}
    for path in sorted(payload.rglob('*')):
        need(not path.is_symlink(), 'PAYLOAD_SYMLINK_REJECTED')
        if path.is_dir():
            continue
        name = path.relative_to(payload).as_posix()
        relative = PurePosixPath(name)
        need(path.is_file() and not any(part.startswith('.') for part in relative.parts)
             and name in manifest['payload_files'] and path.stat().st_size <= 16 * 1024**2, 'PAYLOAD_SCOPE_DRIFT')
        found[name] = sha(path.read_bytes())
    need(found == manifest['payload_files'], 'COMPLETE_FROZEN_PAYLOAD_BYTES_REQUIRED')
    root = payload / 'frontend/dist'
    expected = {name.removeprefix('frontend/dist/'): value for name, value in found.items() if name.startswith('frontend/dist/')}
    need(expected and base.file_map(root) == expected and re.fullmatch('[a-f0-9]{12}', manifest.get('frontend_version', ''))
         and json.loads((root / 'app-version.json').read_bytes()) == {'version': manifest['frontend_version']}, 'MATCHING_COMPLETE_FRONTEND_REQUIRED')
    return root


def checked_images(switch, candidate):
    identities = [BASE_IMAGE, candidate['image_id'], candidate['rollback_image_id']]
    rows = json.loads(switch.docker(['image', 'inspect', *identities]))
    need(isinstance(rows, list) and len(rows) == 3 and {row.get('Id') for row in rows} == set(identities),
         'ALL_RETAINED_CANDIDATE_AND_ROLLBACK_IMAGES_REQUIRED')
    images = {row['Id']: row for row in rows}
    layers = images[BASE_IMAGE].get('RootFS', {}).get('Layers')
    need(isinstance(layers, list) and layers, 'RETAINED_BASE_LAYERS_REQUIRED')
    for identity in identities[1:]:
        actual = images[identity].get('RootFS', {}).get('Layers', [])
        need(isinstance(actual, list) and len(actual) > len(layers) and actual[:len(layers)] == layers,
             'EXACT_RETAINED_IMAGE_LAYERS_REQUIRED')
    need(images[candidate['image_id']].get('Config', {}).get('Labels', {}).get('t24.private.source.sha') == SOURCE
         and images[candidate['rollback_image_id']].get('Config', {}).get('Labels', {}).get(
             't24.private.rollback.schema-compatible') == 'ten-to-eleven-cache', 'EXACT_PREPARED_IMAGE_LABELS_REQUIRED')


@contextmanager
def release_lock(base):
    path = base.CONFIG / 'private-finance-release.lock'
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = protected(path)
        opened = os.fstat(descriptor)
        need((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino), 'RELEASE_LOCK_IDENTITY_DRIFT')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def no_writers(base, switch, allowed=()):
    allowed = set(allowed)
    need(base.CRM_ID not in allowed, 'CRM_WRITER_CANNOT_BE_ALLOWED')
    identities = switch.docker(['ps', '--quiet', '--no-trunc']).decode().splitlines()
    need(all(HASH.fullmatch(value) for value in identities), 'RUNNING_CONTAINER_INVENTORY_REJECTED')
    for identity in identities:
        info = base.inspect(identity)
        for mount in info.get('Mounts', []):
            if mount.get('Type') == 'bind' and mount.get('RW') and mount.get('Source'):
                source, root = Path(mount['Source']).resolve(), base.PRIVATE_DB.parent
                if source == root or source in root.parents or root in source.parents:
                    need(identity in allowed, 'UNEXPECTED_PRIVATE_DATABASE_WRITER')


def stable_authorization(base):
    with sqlite3.connect(base.PRIVATE_DB.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        columns = [row[1] for row in db.execute('PRAGMA table_info(private_connections)')]
        result = {}
        for row in db.execute('SELECT * FROM private_connections ORDER BY id'):
            value = dict(zip(columns, row))
            metadata = json.loads(value.get('metadata_json') or '{}')
            bound = {key: value.get(key) for key in ('id', 'owner_id', 'source_id', 'status', 'generation',
                     'encrypted_credentials', 'oauth_state_hash', 'oauth_expires_at', 'oauth_used_at', 'created_at')}
            bound['metadata'] = {key: metadata.get(key) for key in ('stripe_account_id', 'mode', 'read_only_adapter',
                                'account_label', 'scope', 'connection_mode', 'ads_customer_id')}
            result[digest(value['id'])] = digest(bound)
    return result


def assert_runtime_boundary(base, baseline):
    need(base.crm_check() == baseline['crm'] and sha(base.read_protected(base.ENV)) == ENV_HASH,
         'CRM_OR_IDENTITY_ENVIRONMENT_CHANGED')


def target_schema_objects(before, candidate):
    need(set(before['tables']) == TEN_TABLES, 'EXACT_TEN_TABLE_BASE_REQUIRED')
    fresh = candidate['synthetic_schema']['schema_objects']
    additions = {name: row for name, row in fresh.items() if row['table'] == 'private_stripe_reports'}
    need(set(additions) == {'private_stripe_reports', 'ix_private_stripe_reports_owner_id',
                           'sqlite_autoindex_private_stripe_reports_1'} and
         not set(additions) & set(before['schema_objects']), 'ONLY_INDEPENDENT_CACHE_TABLE_AND_INDEXES_ALLOWED')
    # Existing ALTERed table SQL may differ from fresh metadata. Preserve exact
    # live objects and pin only the independently rehearsed additive objects.
    return {**before['schema_objects'], **additions}


def assert_schema(base, preparation, target, baseline, *, exact_rows=False):
    current = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
    need(current['business'] == baseline['business'] and len(current['business']['tables']) == 83, 'CRM_DATABASE_CHANGED')
    need(current['private']['identity'] == baseline['private']['identity']
         and current['private']['schema_objects'] == target, 'PRIVATE_INODE_OR_ELEVEN_SCHEMA_CHANGED')
    if exact_rows:
        need(current['private']['tables'] == baseline['private']['tables'], 'PRIVATE_ROWS_CHANGED_BEFORE_WORKER_START')
    return current


def backup_private(base, preparation, frozen, path):
    need(not path.exists() and not path.is_symlink() and path.parent.resolve() == path.parent, 'NEW_DISTINCT_BACKUP_REQUIRED')
    base.write_new(path, b'')
    with sqlite3.connect(base.PRIVATE_DB.as_uri() + '?mode=ro', uri=True, timeout=15) as old, sqlite3.connect(path, timeout=15) as new:
        old.execute('PRAGMA query_only=ON')
        old.backup(new)
        need(new.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'PRIVATE_BACKUP_INTEGRITY_FAILED')
    copied = preparation.database_snapshot(path, private=True)
    need((copied['identity']['device'], copied['identity']['inode']) !=
         (frozen['private']['identity']['device'], frozen['private']['identity']['inode']) and
         all(copied[key] == frozen['private'][key] for key in ('tables', 'schema_objects', 'schema_sha256', 'data_sha256')),
         'EXACT_PRIVATE_BACKUP_REQUIRED')
    return sha(path.read_bytes())


def report_auth_check(public=False):
    origin = 'https://t24-crm.com' if public else 'http://127.0.0.1:8001'
    request = urllib.request.Request(origin + '/api/v1/private-workspace/stripe/report', data=b'{"period":"month"}',
                                     headers={'Content-Type': 'application/json'}, method='POST')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
    try:
        response = opener.open(request, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read(65537)
        need(len(body) <= 65536 and response.code == 401 and
             'no-store' in {piece.strip().lower() for piece in response.headers.get('Cache-Control', '').split(',')},
             'STRIPE_REPORT_AUTH_OR_CACHE_BOUNDARY_FAILED')


def own_role(base, switch, identity, role, image, attempt, source, values, running=None, *, require_stable=True):
    return switch.staged_check(identity, role, image, attempt, source, values, running=running, require_stable=require_stable)


def run_initializer(base, switch, image, attempt, progress, state_path):
    name = 't24-private-finance-initialize-' + attempt
    need(base.inspect(name, optional=True) is None, 'NEW_INITIALIZER_NAME_REQUIRED')
    progress['initializer_name'] = name
    base.save(state_path, progress, replace=True)
    identity = switch.docker(switch.initializer_command(name, image, attempt)).decode().strip()
    need(HASH.fullmatch(identity or ''), 'INITIALIZER_ID_REQUIRED')
    progress['initializer_id'] = identity
    switch.initializer_check(base.inspect(identity), image, attempt)
    base.save(state_path, progress, replace=True)
    no_writers(base, switch)
    result = switch.docker(['start', '--attach', identity], timeout=90)
    info = switch.initializer_check(base.inspect(identity), image, attempt)
    need(not info['State']['Running'] and info['State'].get('ExitCode') == 0
         and json.loads(result) == {'stage': 'PRIVATE_INITIALIZER_EXITED'}, 'INITIALIZER_SAFE_SUCCESS_REQUIRED')
    switch.docker(['rm', identity])
    progress['initializer_completed'] = True
    base.save(state_path, progress, replace=True)


def start_role(base, switch, release, progress, role, image, source, values, *, rollback=False):
    attempt = progress['rollback_attempt'] if rollback else progress['attempt']
    name = 't24-private-finance-stage-' + role + '-' + attempt
    profile = release / 'live-upgrade' / (('rollback-' if rollback else '') + role + '-runtime.env')
    base.write_new(profile, switch.profile_bytes(values))
    need(base.inspect(name, optional=True) is None, 'NEW_PRIVATE_ROLE_NAME_COLLISION')
    key = 'rollback_roles' if rollback else 'roles'
    progress.setdefault(key, {})[role] = {'name': name, 'image': image, 'source': source, 'attempt': attempt}
    base.save(release / 'upgrade-state.json', progress, replace=True)
    identity = switch.docker(switch.create_command(name, role, image, attempt, source, profile)).decode().strip()
    need(HASH.fullmatch(identity or ''), 'CREATED_PRIVATE_ROLE_ID_REQUIRED')
    progress[key][role]['id'] = identity
    own_role(base, switch, identity, role, image, attempt, source, values, False)
    base.save(release / 'upgrade-state.json', progress, replace=True)
    canonical = 't24-private-' + role
    previous = base.inspect(canonical, optional=True)
    if previous is not None:
        need(previous['Id'] == progress['old_ids'][role] and not previous['State']['Running'], 'ONLY_RETAINED_PRIVATE_ROLE_CAN_BE_RENAMED')
        switch.docker(['rename', previous['Id'], 't24-private-stripe-retained-' + role + '-' + progress['attempt']])
    switch.docker(['rename', identity, canonical])
    switch.docker(['start', identity])
    if role == 'api':
        switch.wait_api(identity)
    proof = own_role(base, switch, identity, role, image, attempt, source, values, True)
    progress[key][role]['runtime'] = proof
    base.save(release / 'upgrade-state.json', progress, replace=True)
    return identity


def stop_owned(base, switch, progress, values):
    # Names are recorded before docker create, so an ambiguous create result can
    # be inspected and stopped without touching unrelated containers.
    for key in ('roles', 'rollback_roles'):
        for role in ('worker', 'api'):
            entry = progress.get(key, {}).get(role)
            if not entry:
                continue
            info = base.inspect(entry.get('id') or entry['name'], optional=True)
            if info is None:
                continue
            own_role(base, switch, info['Id'], role, entry['image'], entry['attempt'], entry['source'], values[role], require_stable=False)
            if info['State']['Running']:
                switch.docker(['stop', '--time', '30', info['Id']], timeout=45)
            canonical = base.inspect('t24-private-' + role, optional=True)
            if canonical and canonical['Id'] == info['Id']:
                switch.docker(['rename', info['Id'], entry['name'] + '-failed'])
    if progress.get('initializer_id') or progress.get('initializer_name'):
        info = base.inspect(progress.get('initializer_id') or progress['initializer_name'], optional=True)
        if info:
            switch.initializer_check(info, progress['candidate_image'], progress['attempt'])
            if info['State']['Running']:
                switch.docker(['stop', '--time', '30', info['Id']], timeout=45)


def rollback(base, nav, preparation, switch, release, manifest, candidate, progress, values):
    assert_runtime_boundary(base, progress['baseline_runtime'])
    stop_owned(base, switch, progress, values)
    for role in ('worker', 'api'):
        info = base.inspect(progress['old_ids'][role])
        pinned = progress['old_runtime'][role]
        need(info['Image'] == BASE_IMAGE and base.config_hash(info) == pinned['configuration_sha256'], 'RETAINED_PRIVATE_CONFIGURATION_CHANGED')
        if info['State']['Running']:
            switch.docker(['stop', '--time', '30', info['Id']], timeout=45)
    no_writers(base, switch)
    frozen = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
    need(frozen['private']['identity'] == progress['private_identity'], 'ROLLBACK_PRIVATE_DATABASE_REPLACED')
    tables = set(frozen['private']['tables'])
    need(tables in (TEN_TABLES, TEN_TABLES | {'private_stripe_reports'}), 'ROLLBACK_PRIVATE_SCHEMA_REQUIRES_REVIEW')
    expected = progress['target_schema_objects'] if 'private_stripe_reports' in tables else progress['old_schema_objects']
    need(frozen['private']['schema_objects'] == expected and
         frozen['business']['schema_sha256'] == progress['business_schema_sha256'], 'ROLLBACK_SCHEMA_DRIFT')
    stable = switch.stable_records(base.PRIVATE_DB)
    authorization = stable_authorization(base)
    current_nginx = sha(base.read_nginx())
    need(current_nginx in {progress['original_nginx_sha256'], progress['new_nginx_sha256']}, 'ROLLBACK_NGINX_CONCURRENT_CHANGE')
    original = read_protected(release / 'live-upgrade/nginx-before.conf', 65536)
    need(sha(original) == progress['original_nginx_sha256'], 'ROLLBACK_ORIGINAL_NGINX_BYTES_DRIFT')
    if current_nginx != progress['original_nginx_sha256']:
        base.atomic_nginx(original, {progress['new_nginx_sha256']})
        base.run(['nginx', '-t'], 'ROLLBACK_NGINX_TEST_FAILED')
        base.run(['systemctl', 'reload', 'nginx'], 'ROLLBACK_NGINX_RELOAD_FAILED')
    progress['rollback_attempt'] = uuid4().hex
    progress['rollback_roles'] = {}
    # Before migration the retained ten-table model preserves ten tables. After
    # migration only the append-only compatibility model can initialize safely.
    rollback_image = candidate['rollback_image_id'] if 'private_stripe_reports' in tables else BASE_IMAGE
    progress['rollback_image_used'] = rollback_image
    start_role(base, switch, release, progress, 'api', rollback_image, BASE_SOURCE, values['api'], rollback=True)
    need(preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS) == frozen, 'ROLLBACK_API_CHANGED_DATABASE')
    base.public_check(base.file_map(OLD_PUBLIC), OLD_VERSION, OLD_PUBLIC)
    start_role(base, switch, release, progress, 'worker', rollback_image, BASE_SOURCE, values['worker'], rollback=True)
    no_writers(base, switch, [row['id'] for row in progress['rollback_roles'].values()])
    current = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
    need(current['business'] == frozen['business'] and current['private']['identity'] == frozen['private']['identity']
         and current['private']['schema_objects'] == frozen['private']['schema_objects'], 'ROLLBACK_DATABASE_BOUNDARY_CHANGED')
    switch.preserved(stable, switch.stable_records(base.PRIVATE_DB))
    need(stable_authorization(base) == authorization, 'ROLLBACK_PRIVATE_CREDENTIALS_OR_GENERATION_CHANGED')
    assert_runtime_boundary(base, progress['baseline_runtime'])
    nav.disabled_live_features(base)
    progress.update(phase='STRIPE_REPORT_COMPATIBLE_ROLLBACK_VERIFIED', deployed=False,
                    databases_restored=False, cache_schema_retained='private_stripe_reports' in tables)
    base.save(release / 'upgrade-state.json', progress, replace=True)
    return progress


def apply(release, manifest, payload, candidate, *, base=None, nav=None, preparation=None, switch=None):
    release, payload = Path(release), Path(payload)
    if base is None:
        need(os.geteuid() == 0 and socket.gethostname() == HOST and release == RELEASE,
             'EXPLICIT_AUTHENTICATED_RELEASE_HOST_REQUIRED')
        base, nav, preparation, switch = retained_tools(release)
    checked_candidate(candidate, manifest)
    static = checked_payload(payload, manifest, base)
    checked_images(switch, candidate)
    base.RELEASE, base.OLD_PUBLIC = release, OLD_PUBLIC
    base.PUBLIC = OLD_PUBLIC.parent / ('stripe-report-' + SOURCE[:12] + '-20261012')
    with release_lock(base):
        prior_candidate, prior_state, prior_static = nav.accepted_receipts(base)
        baseline = nav.runtime(base, prior_candidate, prior_state, prior_static)
        original = base.read_nginx()
        need(sha(original) == OLD_NGINX and sha(base.read_protected(base.ENV)) == ENV_HASH, 'FRESH_ACCEPTED_PUBLIC_AND_ENVIRONMENT_REQUIRED')
        base.public_check(base.file_map(OLD_PUBLIC), OLD_VERSION, OLD_PUBLIC)
        before = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
        need(set(before['private']['tables']) == TEN_TABLES and len(before['business']['tables']) == 83, 'CURRENT_TEN_PRIVATE_AND_83_CRM_TABLES_REQUIRED')
        target = target_schema_objects(before['private'], candidate)
        changed = base.changed_nginx(original, OLD_NGINX)
        need(not (release / 'live-upgrade').exists() and not (release / 'upgrade-state.json').exists(), 'NEW_UPGRADE_STATE_REQUIRED')
        (release / 'live-upgrade').mkdir(mode=0o700)
        values, old_runtime = {}, {}
        for role in ('api', 'worker'):
            info = base.inspect(prior_state['new_ids'][role])
            values[role] = switch.environment(info)
            need(all('\n' not in key + value and '\r' not in key + value for key, value in values[role].items()), 'SINGLE_LINE_ROLE_ENVIRONMENT_REQUIRED')
            old_attempt = info['Config']['Labels'].get(switch.ROLE_LABEL)
            own_role(base, switch, info['Id'], role, BASE_IMAGE, old_attempt, BASE_SOURCE, values[role], True)
            old_runtime[role] = baseline['private'][role]
        progress = {'format_version': 1, 'phase': 'STRIPE_REPORT_UPGRADE_PREPARED', 'source_sha': SOURCE,
            'frontend_version': manifest['frontend_version'], 'candidate_image': candidate['image_id'],
            'rollback_image': candidate['rollback_image_id'], 'candidate_content_sha256': digest(candidate), 'attempt': uuid4().hex,
            'payload_manifest_sha256': candidate['payload_manifest_sha256'], 'frozen_source_sha256': candidate['frozen_source_sha256'],
            'old_ids': prior_state['new_ids'], 'old_runtime': old_runtime, 'baseline_runtime': baseline,
            'private_identity': before['private']['identity'], 'old_schema_objects': before['private']['schema_objects'],
            'target_schema_objects': target,
            'business_schema_sha256': before['business']['schema_sha256'], 'original_nginx_sha256': sha(original),
            'new_nginx_sha256': sha(changed), 'public_root': str(base.PUBLIC), 'bank_enabled': False, 'ai_enabled': False,
            'credential_seed_attempted': False, 'databases_restored': False, 'deployed': False, 'roles': {}}
        base.write_new(release / 'live-upgrade/nginx-before.conf', original)
        base.save(release / 'upgrade-state.json', progress)
        try:
            # Revalidate the accepted identities immediately before stopping only
            # the private writers. The CRM container is never a mutation target.
            need(nav.runtime(base, prior_candidate, prior_state, prior_static) == baseline and
                 sha(base.read_nginx()) == sha(original), 'FINAL_PREFLIGHT_RUNTIME_DRIFT')
            for role in ('worker', 'api'):
                switch.docker(['stop', '--time', '30', progress['old_ids'][role]], timeout=45)
                need(not base.inspect(progress['old_ids'][role])['State']['Running'], 'PRIVATE_WRITER_DID_NOT_STOP')
            no_writers(base, switch)
            assert_runtime_boundary(base, baseline)
            frozen = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
            need(frozen['private']['identity'] == before['private']['identity'] and frozen['private']['schema_objects'] == before['private']['schema_objects']
                 and frozen['business'] == before['business'], 'DATABASE_BOUNDARY_CHANGED_DURING_FREEZE')
            base.save(release / 'live-upgrade/schema-before.json', frozen)
            progress['backup_sha256'] = backup_private(base, preparation, frozen, release / 'live-upgrade/original-private.db')
            stable, authorization = switch.stable_records(base.PRIVATE_DB), stable_authorization(base)
            run_initializer(base, switch, candidate['image_id'], progress['attempt'], progress, release / 'upgrade-state.json')
            no_writers(base, switch)
            after = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
            proof = preparation.compare_schema_snapshots(frozen, after, target, source_sha=SOURCE, mode='in_place')
            base.save(release / 'live-upgrade/schema-after.json', after)
            base.save(release / 'live-upgrade/schema-validation.json', proof)
            progress.update(phase='STRIPE_REPORT_LIVE_SCHEMA_VERIFIED', original_private_tables_preserved=10,
                            business_tables_verified=83, schema_validation_sha256=digest(proof))
            base.save(release / 'upgrade-state.json', progress, replace=True)
            start_role(base, switch, release, progress, 'api', candidate['image_id'], SOURCE, values['api'])
            assert_schema(base, preparation, target, after, exact_rows=True)
            report_auth_check()
            public = base.install_public(static)
            need(sha(base.read_nginx()) == sha(original), 'PUBLICATION_NGINX_CONCURRENT_CHANGE')
            assert_runtime_boundary(base, baseline)
            base.atomic_nginx(changed, {sha(original)})
            base.run(['nginx', '-t'], 'STRIPE_REPORT_NGINX_TEST_FAILED')
            base.run(['systemctl', 'reload', 'nginx'], 'STRIPE_REPORT_NGINX_RELOAD_FAILED')
            progress['phase'] = 'STRIPE_REPORT_STATIC_SWITCHED'
            base.save(release / 'upgrade-state.json', progress, replace=True)
            base.public_check(public, manifest['frontend_version'], base.PUBLIC)
            report_auth_check(True)
            assert_schema(base, preparation, target, after, exact_rows=True)
            start_role(base, switch, release, progress, 'worker', candidate['image_id'], SOURCE, values['worker'])
            no_writers(base, switch, [row['id'] for row in progress['roles'].values()])
            final = assert_schema(base, preparation, target, after)
            switch.preserved(stable, switch.stable_records(base.PRIVATE_DB))
            need(stable_authorization(base) == authorization, 'PRIVATE_AUTHORIZATION_CHANGED')
            assert_runtime_boundary(base, baseline)
            nav.disabled_live_features(base)
            need(sha(base.read_nginx()) == sha(changed) and base.file_map(base.PUBLIC) == public, 'FINAL_PUBLIC_BYTES_OR_NGINX_DRIFT')
            for role, row in progress['roles'].items():
                own_role(base, switch, row['id'], role, row['image'], row['attempt'], row['source'], values[role], True)
            base.save(release / 'live-upgrade/final-snapshot.json', final)
            progress.update(phase='STRIPE_REPORT_PUBLIC_RELEASE_VERIFIED', deployed=True, public_assets_published=True,
                            business_tables_verified=83, private_tables_verified=11, same_private_inode=True,
                            credentials_and_generation_preserved=True, private_reports_require_owner=True)
            base.save(release / 'upgrade-state.json', progress, replace=True)
            return progress
        except BaseException as error:
            progress.update(deployed=False, failure_code=safe_error(error))
            try:
                rollback(base, nav, preparation, switch, release, manifest, candidate, progress, values)
            except BaseException as rollback_error:
                progress.update(phase='STRIPE_REPORT_ROLLBACK_REQUIRES_REVIEW', rollback_failure_code=safe_error(rollback_error))
                base.save(release / 'upgrade-state.json', progress, replace=True)
                raise UpgradeError('STRIPE_REPORT_ROLLBACK_REQUIRES_REVIEW') from None
            raise UpgradeError('STRIPE_REPORT_UPGRADE_REJECTED_COMPATIBLE_ROLLBACK_VERIFIED') from None


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise UpgradeError('ARGUMENTS_REJECTED')


def main(args):
    need(args.execute and os.geteuid() == 0 and socket.gethostname() == HOST and args.release == RELEASE,
         'EXPLICIT_AUTHENTICATED_RELEASE_HOST_REQUIRED')
    protected(args.release, True)
    base, nav, preparation, switch = retained_tools(args.release)
    manifest = fixed_json(args.release / 'stripe-report-manifest.json', args.manifest_sha256)
    candidate = fixed_json(args.release / 'prepared-backend/candidate.json', args.candidate_sha256)
    frozen = fixed_json(args.release / 'frozen-source.json', candidate['frozen_source_sha256'])
    need(candidate.get('payload_manifest_sha256') == args.manifest_sha256 and
         manifest.get('frozen_manifest_sha256') == candidate['frozen_source_sha256'] and
         sha(read_protected(args.release / 'stripe-report-payload.tar.gz', 64 * 1024**2)) == candidate.get('payload_sha256'),
         'INDEPENDENT_CANDIDATE_ARTIFACT_BINDINGS_REQUIRED')
    preparation.checked_payload(manifest, frozen, candidate['payload_sha256'])
    result = apply(args.release, manifest, args.release / 'prepared-backend/payload', candidate,
                   base=base, nav=nav, preparation=preparation, switch=switch)
    print(json.dumps({'phase': result['phase'], 'source_sha': SOURCE, 'frontend_version': manifest['frontend_version'],
          'receipt_path': str(args.release / 'upgrade-state.json'),
          'receipt_sha256': sha(read_protected(args.release / 'upgrade-state.json')),
          'candidate_sha256': args.candidate_sha256, 'business_tables_verified': 83, 'private_tables_verified': 11,
          'databases_restored': False, 'bank_enabled': False, 'ai_enabled': False, 'deployed': result['deployed']}, sort_keys=True))


if __name__ == '__main__':
    parser = SafeParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--candidate-sha256', required=True)
    try:
        main(parser.parse_args())
    except BaseException as error:
        print(json.dumps({'stage': 'STRIPE_REPORT_UPGRADE_REJECTED', 'error': safe_error(error), 'deployed': False}, sort_keys=True))
        sys.exit(1)
