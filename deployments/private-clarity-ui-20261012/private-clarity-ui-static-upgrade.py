#!/usr/bin/env python3
"""Frozen frontend-only publisher for the accepted private clarity UI release.

Prepared locally. This file performs no production action unless explicitly run
on the fixed host as root with independently reviewed frontend artifact pins.
Acquire this helper and the exact readonly verifier through an immutable carrier.
Only a fresh release/public directory, proof files and one Nginx root may change.
There are no Docker mutation, credential, provider or database write commands.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import sys
import tarfile
from types import SimpleNamespace


HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BACKEND_SOURCE = 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
BACKEND_VERSION = '913856b4d17b'
BACKEND_RELEASE = Path('/opt/t24-crm/releases/stripe-report-c1ae19b38fec-20261012')
BACKEND_PUBLIC = Path('/var/www/t24-crm-public/stripe-report-c1ae19b38fec-20261012')
PREVIOUS_SOURCE = '08e8505f5a6ea66626e91b2089394ef001c54fd7'
PREVIOUS_VERSION = 'adfb31c0b755'
PREVIOUS_RELEASE = Path('/opt/t24-crm/releases/stripe-report-ui-08e8505f5a6e-20261012')
PREVIOUS_PUBLIC = Path('/var/www/t24-crm-public/stripe-report-ui-08e8505f5a6e-20261012')
PREVIOUS_RECEIPT_SHA = 'dd7ccc6ee0d4273a281a7fb579ea871287305d41142b0363bc1624779ddeae48'
PREVIOUS_MANIFEST_SHA = '68d3261cb84f6aab5070f3955a48644ff59d0659b6fc42348890b8e64f65fcb8'
PREVIOUS_PAYLOAD_SHA = '34ff135b21a094645c41b7d1a606b357833f610c4755dd246bf1884a5941a16d'
PREVIOUS_NGINX_SHA = '17c41c4989662fa8c298677441d5c539949326e534e2d59fd9545b50c205c35b'
FRONTEND_SOURCE = '8e1c07415e78db6b9ef199e997e501d1db4dc5e6'
FRONTEND_VERSION = 'ecae2d8aa23a'
VERIFIER_SHA = '5dab63e2bc897e6e562de5afde65f407ebaa5d0d8de328f44fc3923c66a174b7'
PINS = {
    'acquired_sha256': '8ee1b35f4dfc6643d884edd4c4564328228ae35abd9f600f3e2a3c39bf661fe2',
    'candidate_sha256': '005103022cdc86bee8319ec16d2b310629748dc1254c29a418f354f5d9bda1b5',
    'receipt_sha256': 'a02dd09affee4b0043a4ba233e23ebd68ffc9fe49cc0b777f2ab89b0ab6440d2',
    'upgrade_helper_sha256': '919f0ecca1d33a46d882a816b70fccb1514144ba4ddc828c2921e5db1a4b5e5b',
}
OWNER_AFTER = BACKEND_RELEASE / 'postdeploy-verification-release-20261012/owner-ui-after.json'
OWNER_AFTER_SHA = 'a8865724e246d719b7c9520f8b3a86af47c55e8ee5a5d6cffbcb9a5799788d18'
ALLOWED_SOURCE_FILES = frozenset({
    'app/frontend/src/lib/private-ads.ts',
    'app/frontend/src/lib/private-boss-brief.ts',
    'app/frontend/src/lib/private-workspace-navigation.ts',
    'app/frontend/src/pages/PrivateAdsDashboard.tsx',
    'app/frontend/src/pages/PrivateBankDashboard.tsx',
    'app/frontend/src/pages/PrivateBossBrief.tsx',
    'app/frontend/src/pages/PrivateFundsOverview.tsx',
    'app/frontend/src/pages/PrivateMailBrief.tsx',
    'app/frontend/src/pages/PrivateMailContent.tsx',
    'app/frontend/src/pages/PrivateStripeDashboard.tsx',
    'app/frontend/src/pages/PrivateWorkspace.tsx',
    'app/frontend/src/pages/private-bank.css',
    'app/frontend/src/pages/private-boss-brief.css',
    'app/frontend/src/pages/private-funds-overview.css',
    'app/frontend/src/pages/private-mail-ads-clarity.css',
    'app/frontend/src/pages/private-stripe-dashboard.css',
    'app/frontend/src/pages/private-workspace.css',
    'app/frontend/tests/private-ads.test.mjs',
    'app/frontend/tests/private-boss-brief.test.mjs',
    'app/frontend/tests/private-mail-ads-clarity.test.mjs',
    'app/frontend/tests/private-stripe-report.test.mjs',
    'app/frontend/tests/private-workspace-mail-ui.test.mjs',
})
HASH = re.compile('[a-f0-9]{64}')
SOURCE = re.compile('[a-f0-9]{40}')
VERSION = re.compile('[a-f0-9]{12}')


class StaticError(RuntimeError):
    pass


def need(condition, code):
    if not condition:
        raise StaticError(code)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def stamp(info):
    return tuple(getattr(info, key) for key in (
        'st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_nlink',
        'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def read_bootstrap(path, expected):
    need(HASH.fullmatch(expected or '') and path.is_absolute() and path.resolve() == path,
         'CANONICAL_REVIEWED_HELPER_REQUIRED')
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
             'PROTECTED_HELPER_ANCESTOR_REQUIRED')
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
         and stat.S_IMODE(before.st_mode) == 0o600 and 0 < before.st_size <= 1024**2,
         'ROOT_PRIVATE_HELPER_REQUIRED')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        need(stamp(os.fstat(stream.fileno())) == stamp(before), 'HELPER_IDENTITY_CHANGED')
        blob = stream.read(1024**2 + 1)
    need(stamp(path.lstat()) == stamp(before) and len(blob) <= 1024**2 and sha(blob) == expected,
         'HELPER_BYTES_CHANGED')
    return blob


def load_verifier(release):
    path = release / 'readonly_verifier.py'
    blob = read_bootstrap(path, VERIFIER_SHA)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_loader('_clarity_static_reviewed_verifier', loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    exec(compile(blob, str(path), 'exec'), module.__dict__)
    need(module.HOST == HOST and module.SOURCE == BACKEND_SOURCE
         and module.VERSION == BACKEND_VERSION and module.RELEASE == BACKEND_RELEASE
         and module.PUBLIC == BACKEND_PUBLIC, 'EXACT_ACCEPTED_VERIFIER_REQUIRED')
    return module


def checked_backend_release(verifier, upgrade, base, nav, preparation, switch, args):
    acquired = upgrade.fixed_json(BACKEND_RELEASE / 'acquired.json', args.acquired_sha256)
    candidate = upgrade.fixed_json(BACKEND_RELEASE / 'prepared-backend/candidate.json', args.candidate_sha256)
    receipt = upgrade.fixed_json(BACKEND_RELEASE / 'upgrade-state.json', args.receipt_sha256)
    manifest = upgrade.fixed_json(BACKEND_RELEASE / 'stripe-report-manifest.json', candidate['payload_manifest_sha256'])
    frozen = upgrade.fixed_json(BACKEND_RELEASE / 'frozen-source.json', candidate['frozen_source_sha256'])
    need(acquired['files'].get('upgrade.py') == args.upgrade_helper_sha256
         and acquired['files'].get('stripe-report-manifest.json') == candidate['payload_manifest_sha256']
         and acquired['files'].get('frozen-source.json') == candidate['frozen_source_sha256']
         and acquired['files'].get('stripe-report-payload.tar.gz') == candidate['payload_sha256'],
         'ACQUIRED_CANDIDATE_BINDINGS_REQUIRED')
    need(manifest.get('frozen_manifest_sha256') == candidate['frozen_source_sha256']
         and manifest.get('frontend_version') == BACKEND_VERSION
         and sha(upgrade.read_protected(BACKEND_RELEASE / 'stripe-report-payload.tar.gz', 64 * 1024**2))
         == candidate['payload_sha256'], 'EXACT_FROZEN_PAYLOAD_REQUIRED')
    preparation.checked_payload(manifest, frozen, candidate['payload_sha256'])
    upgrade.checked_candidate(candidate, manifest)
    upgrade.checked_images(switch, candidate)
    need(receipt.get('format_version') == 1 and receipt.get('phase') == 'STRIPE_REPORT_PUBLIC_RELEASE_VERIFIED'
         and receipt.get('deployed') is True and receipt.get('public_assets_published') is True
         and receipt.get('source_sha') == BACKEND_SOURCE and receipt.get('frontend_version') == BACKEND_VERSION
         and receipt.get('candidate_image') == candidate['image_id']
         and receipt.get('rollback_image') == candidate['rollback_image_id']
         and receipt.get('candidate_content_sha256') == upgrade.digest(candidate)
         and receipt.get('payload_manifest_sha256') == candidate['payload_manifest_sha256']
         and receipt.get('frozen_source_sha256') == candidate['frozen_source_sha256']
         and receipt.get('public_root') == str(BACKEND_PUBLIC)
         and receipt.get('business_tables_verified') == 83 and receipt.get('private_tables_verified') == 11
         and all(receipt.get(key) is True for key in ('same_private_inode',
                 'credentials_and_generation_preserved', 'private_reports_require_owner'))
         and all(receipt.get(key) is False for key in ('bank_enabled', 'ai_enabled',
                 'credential_seed_attempted', 'databases_restored'))
         and 'failure_code' not in receipt and 'rollback_attempt' not in receipt,
         'SUCCESSFUL_FINAL_RELEASE_REQUIRED')
    before = verifier.read_json(upgrade, BACKEND_RELEASE / 'live-upgrade/schema-before.json')
    after = verifier.read_json(upgrade, BACKEND_RELEASE / 'live-upgrade/schema-after.json')
    proof = verifier.read_json(upgrade, BACKEND_RELEASE / 'live-upgrade/schema-validation.json')
    need(upgrade.digest(proof) == receipt.get('schema_validation_sha256')
         and upgrade.digest(before) == proof.get('before_sha256')
         and upgrade.digest(after) == proof.get('after_sha256')
         and before['private']['identity'] == after['private']['identity'] == receipt['private_identity']
         and before['private']['schema_objects'] == receipt['old_schema_objects']
         and before['business']['schema_sha256'] == receipt['business_schema_sha256'],
         'PINNED_LIVE_SCHEMA_PROOF_CHAIN_REQUIRED')
    need(preparation.compare_schema_snapshots(before, after, receipt['target_schema_objects'],
         source_sha=BACKEND_SOURCE, mode='in_place') == proof, 'EXACT_LIVE_SCHEMA_VALIDATION_REQUIRED')
    static = upgrade.checked_payload(BACKEND_RELEASE / 'prepared-backend/payload', manifest, base)
    base.RELEASE, base.PUBLIC, base.OLD_PUBLIC = BACKEND_RELEASE, BACKEND_PUBLIC, upgrade.OLD_PUBLIC
    public = verifier.expected_public(upgrade, base, static)
    # Original backend proof remains immutable. The mandatory current Nginx
    # guard is checked against the accepted currency receipt below, because
    # that frontend-only publication legitimately superseded this root.
    upgrade.assert_runtime_boundary(base, receipt['baseline_runtime'])
    snapshot = upgrade.assert_schema(base, preparation, receipt['target_schema_objects'], after, exact_rows=False)
    need(set(snapshot['private']['tables']) == upgrade.TEN_TABLES | {'private_stripe_reports'},
         'EXACT_ELEVEN_PRIVATE_TABLES_REQUIRED')
    nav.disabled_live_features(base)
    profiles, roles = verifier.current_roles(upgrade, base, switch, receipt)
    return candidate, receipt, manifest, after, profiles, roles, public


def checked_current_release(upgrade, base, backend_receipt, roles):
    """Bind the active currency UI and its rollback bytes before any new writes."""
    previous = upgrade.fixed_json(PREVIOUS_RELEASE / 'static-state.json', PREVIOUS_RECEIPT_SHA)
    need(previous.get('format_version') == 1
         and previous.get('phase') == 'STRIPE_REPORT_UI_STATIC_PUBLIC_VERIFIED'
         and previous.get('frontend_source_sha') == PREVIOUS_SOURCE
         and previous.get('frontend_version') == PREVIOUS_VERSION
         and previous.get('backend_source_sha') == BACKEND_SOURCE
         and previous.get('previous_frontend_version') == BACKEND_VERSION
         and previous.get('pins') == PINS
         and previous.get('owner_after_sha256') == OWNER_AFTER_SHA
         and previous.get('manifest_sha256') == PREVIOUS_MANIFEST_SHA
         and previous.get('payload_sha256') == PREVIOUS_PAYLOAD_SHA
         and previous.get('old_public_root') == str(BACKEND_PUBLIC)
         and previous.get('public_root') == str(PREVIOUS_PUBLIC)
         and previous.get('old_nginx_sha256') == backend_receipt['new_nginx_sha256']
         and previous.get('new_nginx_sha256') == PREVIOUS_NGINX_SHA
         and previous.get('roles') == roles
         and previous.get('private_identity') == backend_receipt['private_identity']
         and previous.get('business_tables_verified') == 83
         and previous.get('private_tables_verified') == 11
         and all(previous.get(key) is True for key in (
             'deployed', 'same_private_inode', 'credentials_and_generation_unchanged',
             'crm_runtime_and_all_83_tables_unchanged', 'previous_assets_preserved'))
         and all(previous.get(key) is False for key in (
             'backend_services_modified', 'database_mutation_performed',
             'environment_modified', 'bank_enabled', 'ai_enabled'))
         and not any(key in previous for key in (
             'failure_code', 'rollback_attempted', 'rollback_failure_code')),
         'CURRENT_CURRENCY_RECEIPT_REQUIRED')
    manifest = upgrade.fixed_json(PREVIOUS_RELEASE / 'static-manifest.json', PREVIOUS_MANIFEST_SHA)
    need(manifest.get('format_version') == 1
         and manifest.get('stage') == 'FROZEN_STRIPE_REPORT_UI_STATIC_SOURCE'
         and manifest.get('frontend_source_sha') == PREVIOUS_SOURCE
         and manifest.get('frontend_version') == PREVIOUS_VERSION
         and manifest.get('backend_source_sha') == BACKEND_SOURCE
         and manifest.get('previous_frontend_version') == BACKEND_VERSION
         and manifest.get('payload_sha256') == PREVIOUS_PAYLOAD_SHA
         and manifest.get('static_only') is True
         and all(manifest.get(key) is False for key in (
             'backend_changes', 'credentials_included', 'databases_modified', 'services_modified'))
         and isinstance(manifest.get('payload_files'), dict)
         and {'index.html', 'app-version.json'} <= manifest['payload_files'].keys(),
         'CURRENT_CURRENCY_MANIFEST_REQUIRED')
    need(sha(upgrade.read_protected(PREVIOUS_RELEASE / 'static-payload.tar.gz', 64 * 1024**2))
         == PREVIOUS_PAYLOAD_SHA, 'CURRENT_CURRENCY_PAYLOAD_DRIFT')
    payload = PREVIOUS_RELEASE / 'payload'
    upgrade.protected(payload, True)
    need(base.file_map(payload) == manifest['payload_files']
         and json.loads(upgrade.read_protected(payload / 'app-version.json')) == {'version': PREVIOUS_VERSION},
         'CURRENT_CURRENCY_EXTRACTED_BYTES_DRIFT')
    desired = dict(manifest['payload_files'])
    for name, fingerprint in base.file_map(BACKEND_PUBLIC).items():
        if name.startswith('assets/'):
            need(name not in desired or desired[name] == fingerprint, 'HASHED_ASSET_COLLISION')
            desired.setdefault(name, fingerprint)
    need(json.loads(upgrade.read_protected(PREVIOUS_RELEASE / 'public-manifest.json')) == desired
         and base.file_map(PREVIOUS_PUBLIC) == desired,
         'CURRENT_CURRENCY_PUBLIC_BYTES_DRIFT')
    before = upgrade.read_protected(PREVIOUS_RELEASE / 'nginx-before.bin')
    after = upgrade.read_protected(PREVIOUS_RELEASE / 'nginx-after.bin')
    old_root, new_root = str(BACKEND_PUBLIC).encode(), str(PREVIOUS_PUBLIC).encode()
    need(sha(before) == backend_receipt['new_nginx_sha256']
         and before.count(old_root) == 1 and old_root not in after
         and before.replace(old_root, new_root) == after
         and sha(after) == PREVIOUS_NGINX_SHA
         and base.read_nginx() == after, 'CURRENT_PUBLIC_NGINX_DRIFT')
    baseline = json.loads(upgrade.read_protected(PREVIOUS_RELEASE / 'runtime-schema-before.json'))
    need(upgrade.digest(baseline) == previous.get('baseline_sha256')
         and baseline['private']['identity'] == previous['private_identity'],
         'CURRENT_CURRENCY_BASELINE_PROOF_DRIFT')
    need(upgrade.stable_authorization(base) == previous.get('stable_authorization'),
         'CURRENT_STATIC_AUTHORIZATION_DRIFT')
    return previous, desired


def checked_manifest(upgrade, base, release, args):
    need(HASH.fullmatch(args.manifest_sha256 or '') and HASH.fullmatch(args.payload_sha256 or ''),
         'INDEPENDENT_STATIC_ARTIFACT_PINS_REQUIRED')
    value = upgrade.fixed_json(release / 'static-manifest.json', args.manifest_sha256)
    need(value.get('format_version') == 1 and value.get('stage') == 'FROZEN_PRIVATE_CLARITY_UI_STATIC_SOURCE'
         and value.get('frontend_source_sha') == args.frontend_source_sha
         and value.get('frontend_version') == args.frontend_version
         and value.get('backend_source_sha') == BACKEND_SOURCE
         and value.get('previous_frontend_version') == PREVIOUS_VERSION
         and value.get('static_only') is True
         and all(value.get(key) is False for key in (
             'backend_changes', 'credentials_included', 'databases_modified', 'services_modified'))
         and isinstance(value.get('changed_source_files'), dict)
         and len(value['changed_source_files']) == len(ALLOWED_SOURCE_FILES)
         and set(value['changed_source_files']) == ALLOWED_SOURCE_FILES
         and all(isinstance(expected, str) and HASH.fullmatch(expected)
                 for expected in value['changed_source_files'].values()),
         'EXACT_CLARITY_FRONTEND_ONLY_MANIFEST_REQUIRED')
    files = value.get('payload_files')
    need(isinstance(files, dict) and 2 <= len(files) < 10000
         and {'index.html', 'app-version.json'} <= files.keys(), 'COMPLETE_STATIC_INVENTORY_REQUIRED')
    for name, expected in files.items():
        need(isinstance(name, str) and isinstance(expected, str), 'STATIC_INVENTORY_TYPES_REQUIRED')
        path = PurePosixPath(name)
        need(name == path.as_posix() and not path.is_absolute() and '..' not in path.parts
             and not any(part.startswith('.') for part in path.parts)
             and path.suffix in base.SUFFIXES and HASH.fullmatch(expected)
             and (path.suffix != '.html' or name in {'index.html', 'offline.html'}),
             'STATIC_FILE_SCOPE_REJECTED')
    archive = upgrade.read_protected(release / 'static-payload.tar.gz', 64 * 1024**2)
    need(value.get('payload_sha256') == args.payload_sha256 == sha(archive), 'STATIC_PAYLOAD_HASH_DRIFT')
    return value, archive


def extract_static(base, release, manifest, archive, version):
    root = release / 'payload'
    need(not root.exists() and not root.is_symlink(), 'FRESH_STATIC_PAYLOAD_REQUIRED')
    root.mkdir(mode=0o700)
    extracted, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as stream:
        for member in stream:
            need(member.isfile() and not member.pax_headers and member.name.startswith('payload/'),
                 'REGULAR_STATIC_ARCHIVE_REQUIRED')
            name = member.name.removeprefix('payload/')
            path = PurePosixPath(name)
            need(name == path.as_posix() and not path.is_absolute() and '..' not in path.parts
                 and not any(part.startswith('.') for part in path.parts)
                 and name in manifest['payload_files'] and name not in extracted
                 and 0 <= member.size <= 16 * 1024**2, 'STATIC_ARCHIVE_SCOPE_REJECTED')
            total += member.size
            need(total < 64 * 1024**2, 'STATIC_ARCHIVE_TOTAL_SIZE_LIMIT')
            handle = stream.extractfile(member)
            need(handle is not None, 'STATIC_MEMBER_STREAM_REQUIRED')
            data = handle.read(member.size + 1)
            need(len(data) == member.size and sha(data) == manifest['payload_files'][name],
                 'STATIC_MEMBER_HASH_DRIFT')
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            base.write_new(target, data)
            extracted[name] = sha(data)
    need(extracted == manifest['payload_files'] == base.file_map(root), 'COMPLETE_STATIC_PAYLOAD_REQUIRED')
    need(json.loads((root / 'app-version.json').read_bytes()) == {'version': version},
         'FROZEN_FRONTEND_VERSION_REQUIRED')
    return root


def preserved_boundary(verifier, upgrade, base, nav, preparation, switch, receipt, baseline,
                       roles, authorization, records):
    current = upgrade.assert_schema(base, preparation, receipt['target_schema_objects'], baseline, exact_rows=False)
    need(len(current['private']['tables']) == 11, 'ELEVEN_PRIVATE_TABLES_REQUIRED')
    upgrade.assert_runtime_boundary(base, receipt['baseline_runtime'])
    nav.disabled_live_features(base)
    _, current_roles = verifier.current_roles(upgrade, base, switch, receipt)
    need(current_roles == roles and upgrade.stable_authorization(base) == authorization,
         'BACKEND_OR_CREDENTIAL_GENERATION_CHANGED')
    switch.preserved(records, verifier.stable_digests(upgrade, switch, base.PRIVATE_DB))
    upgrade.fixed_json(BACKEND_RELEASE / 'acquired.json', PINS['acquired_sha256'])
    upgrade.fixed_json(BACKEND_RELEASE / 'upgrade-state.json', PINS['receipt_sha256'])
    upgrade.fixed_json(OWNER_AFTER, OWNER_AFTER_SHA)
    upgrade.fixed_json(PREVIOUS_RELEASE / 'static-state.json', PREVIOUS_RECEIPT_SHA)
    upgrade.fixed_json(PREVIOUS_RELEASE / 'static-manifest.json', PREVIOUS_MANIFEST_SHA)
    need(sha(upgrade.read_protected(PREVIOUS_RELEASE / 'static-payload.tar.gz', 64 * 1024**2))
         == PREVIOUS_PAYLOAD_SHA, 'CURRENT_CURRENCY_PAYLOAD_DRIFT')
    return current


def rollback_static(base, original, changed, public):
    current = sha(base.read_nginx())
    need(current in {sha(original), sha(changed)}, 'STATIC_ROLLBACK_CONCURRENT_CHANGE')
    if current != sha(original):
        base.atomic_nginx(original, {sha(changed)})
        base.run(['nginx', '-t'], 'ROLLBACK_NGINX_TEST_FAILED')
        base.run(['systemctl', 'reload', 'nginx'], 'ROLLBACK_NGINX_RELOAD_FAILED')
    need(sha(base.read_nginx()) == sha(original) and base.file_map(PREVIOUS_PUBLIC) == public,
         'STATIC_ROLLBACK_BYTES_DRIFT')
    base.public_check(public, PREVIOUS_VERSION, PREVIOUS_PUBLIC, verify_services=False)


def apply(args, release, verifier):
    upgrade = verifier.load_upgrade(PINS['upgrade_helper_sha256'])
    upgrade.protected(release, True)
    upgrade.fixed_json(BACKEND_RELEASE / 'acquired.json', PINS['acquired_sha256'])
    base, nav, preparation, switch = upgrade.retained_tools(BACKEND_RELEASE)
    lock = base.CONFIG / 'private-finance-release.lock'
    before = upgrade.protected(lock)
    descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        need(stamp(os.fstat(descriptor)) == stamp(before), 'EXISTING_RELEASE_LOCK_IDENTITY_CHANGED')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        need(stamp(lock.lstat()) == stamp(before), 'EXISTING_RELEASE_LOCK_REBOUND')
        candidate, receipt, _, _, _, roles, _ = checked_backend_release(
            verifier, upgrade, base, nav, preparation, switch, SimpleNamespace(**PINS))
        previous, old_public = checked_current_release(upgrade, base, receipt, roles)
        owner = upgrade.fixed_json(OWNER_AFTER, OWNER_AFTER_SHA)
        need(owner.get('stage') == 'STRIPE_REPORT_OWNER_UI_AFTER_VERIFIED'
             and owner.get('source_sha') == BACKEND_SOURCE and owner.get('frontend_version') == BACKEND_VERSION
             and owner.get('pins') == PINS and owner.get('roles') == roles
             and owner.get('stable_records_and_authorization_preserved') is True
             and owner.get('database_mutation_performed') is False and owner.get('services_modified') is False,
             'ACCEPTED_AFTER_UI_PROOF_REQUIRED')
        baseline = preparation.release_snapshot(base.PRIVATE_DB, base.BUSINESS)
        authorization = upgrade.stable_authorization(base)
        records = verifier.stable_digests(upgrade, switch, base.PRIVATE_DB)
        need(authorization == owner.get('stable_authorization'), 'POST_UI_AUTHORIZATION_DRIFT')
        # Local notes are compared within this publication window, not against
        # historical UI evidence. Current credential identity stays pinned.
        need(authorization == previous.get('stable_authorization'), 'CURRENT_STATIC_AUTHORIZATION_DRIFT')
        need(baseline['private']['identity'] == previous.get('private_identity'), 'CURRENT_PRIVATE_IDENTITY_DRIFT')
        manifest, archive = checked_manifest(upgrade, base, release, args)
        payload = extract_static(base, release, manifest, archive, args.frontend_version)
        base.public_check(old_public, PREVIOUS_VERSION, PREVIOUS_PUBLIC)
        upgrade.report_auth_check(True)
        original = base.read_nginx()
        need(sha(original) == previous['new_nginx_sha256'] == PREVIOUS_NGINX_SHA, 'CURRENT_PUBLIC_NGINX_DRIFT')
        base.RELEASE, base.OLD_PUBLIC = release, PREVIOUS_PUBLIC
        base.PUBLIC = Path('/var/www/t24-crm-public') / release.name
        changed = base.changed_nginx(original, previous['new_nginx_sha256'])
        state = {'format_version': 1, 'phase': 'PRIVATE_CLARITY_UI_STATIC_PREPARED',
                 'frontend_source_sha': args.frontend_source_sha, 'frontend_version': args.frontend_version,
                 'backend_source_sha': BACKEND_SOURCE, 'previous_frontend_version': PREVIOUS_VERSION,
                 'pins': PINS, 'owner_after_sha256': OWNER_AFTER_SHA,
                 'previous_static_receipt_sha256': PREVIOUS_RECEIPT_SHA,
                 'previous_static_manifest_sha256': PREVIOUS_MANIFEST_SHA,
                 'previous_static_payload_sha256': PREVIOUS_PAYLOAD_SHA,
                 'manifest_sha256': args.manifest_sha256, 'payload_sha256': args.payload_sha256,
                 'old_public_root': str(PREVIOUS_PUBLIC), 'public_root': str(base.PUBLIC),
                 'old_nginx_sha256': sha(original), 'new_nginx_sha256': sha(changed),
                 'roles': roles, 'private_identity': baseline['private']['identity'],
                 'baseline_sha256': upgrade.digest(baseline), 'stable_authorization': authorization,
                 'business_tables_verified': 83, 'private_tables_verified': 11,
                 'backend_services_modified': False, 'database_mutation_performed': False,
                 'environment_modified': False, 'bank_enabled': False, 'ai_enabled': False, 'deployed': False}
        state_path = release / 'static-state.json'
        base.write_new(release / 'nginx-before.bin', original)
        base.write_new(release / 'nginx-after.bin', changed)
        base.save(release / 'runtime-schema-before.json', baseline)
        base.save(state_path, state)
        try:
            desired = base.install_public(payload)
            preserved_boundary(verifier, upgrade, base, nav, preparation, switch, receipt,
                               baseline, roles, authorization, records)
            need(base.file_map(PREVIOUS_PUBLIC) == old_public, 'PREVIOUS_ASSETS_CHANGED_BEFORE_SWITCH')
            base.atomic_nginx(changed, {sha(original)})
            state['phase'] = 'PRIVATE_CLARITY_UI_STATIC_ROOT_CHANGED'
            base.save(state_path, state, replace=True)
            base.run(['nginx', '-t'], 'NGINX_TEST_FAILED')
            base.run(['systemctl', 'reload', 'nginx'], 'NGINX_RELOAD_FAILED')
            base.public_check(desired, args.frontend_version, base.PUBLIC)
            upgrade.report_auth_check(True)
            current = preserved_boundary(verifier, upgrade, base, nav, preparation, switch, receipt,
                                         baseline, roles, authorization, records)
            need(sha(base.read_nginx()) == sha(changed) and base.file_map(base.PUBLIC) == desired
                 and base.file_map(PREVIOUS_PUBLIC) == old_public, 'FINAL_STATIC_BOUNDARY_DRIFT')
            base.save(release / 'runtime-schema-after.json', current)
            state.update(phase='PRIVATE_CLARITY_UI_STATIC_PUBLIC_VERIFIED', deployed=True,
                         same_private_inode=True, credentials_and_generation_unchanged=True,
                         crm_runtime_and_all_83_tables_unchanged=True, previous_assets_preserved=True)
            base.save(state_path, state, replace=True)
        except BaseException as error:
            state['failure_code'] = safe_error(error)
            state['rollback_attempted'] = True
            try:
                rollback_static(base, original, changed, old_public)
                state['phase'] = 'PRIVATE_CLARITY_UI_STATIC_ROLLED_BACK'
                state['deployed'] = False
            except BaseException as rollback_error:
                state['phase'] = 'PRIVATE_CLARITY_UI_STATIC_ROLLBACK_NEEDS_REVIEW'
                state['rollback_failure_code'] = safe_error(rollback_error)
            base.save(state_path, state, replace=True)
            raise StaticError(state['failure_code']) from None
        return {'phase': state['phase'], 'frontend_source_sha': args.frontend_source_sha,
                'frontend_version': args.frontend_version, 'backend_source_sha': BACKEND_SOURCE,
                'receipt_path': str(state_path), 'receipt_sha256': sha(upgrade.read_protected(state_path)),
                'business_tables_verified': 83, 'private_tables_verified': 11, 'deployed': True,
                'backend_services_modified': False, 'database_mutation_performed': False,
                'environment_modified': False}
    finally:
        os.close(descriptor)


def main(args):
    need(args.execute and os.geteuid() == 0 and socket.gethostname() == HOST,
         'EXPLICIT_FIXED_ROOT_SERVER_REQUIRED')
    need(args.frontend_source_sha == FRONTEND_SOURCE and args.frontend_version == FRONTEND_VERSION,
         'NEW_IMMUTABLE_FRONTEND_REQUIRED')
    release = Path(__file__).resolve().parent
    need(release == Path('/opt/t24-crm/releases') / ('private-clarity-ui-' + args.frontend_source_sha[:12] + '-20261012'),
         'EXACT_NEW_STATIC_RELEASE_PATH_REQUIRED')
    return apply(args, release, load_verifier(release))


def safe_error(error):
    allowed = isinstance(error, StaticError) or type(error).__name__ in {
        'VerificationError', 'UpgradeError', 'SwitchError', 'GuardError', 'TransferError', 'PrepareError'}
    return str(error) if allowed and re.fullmatch('[A-Z0-9_]{1,100}', str(error)) else 'STATIC_RELEASE_REJECTED'


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise StaticError('ARGUMENTS_REJECTED')


if __name__ == '__main__':
    parser = SafeParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--frontend-source-sha', required=True)
    parser.add_argument('--frontend-version', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--payload-sha256', required=True)
    try:
        print(json.dumps(main(parser.parse_args()), sort_keys=True))
    except BaseException as error:
        print(json.dumps({'stage': 'PRIVATE_CLARITY_UI_STATIC_REJECTED', 'error': safe_error(error),
                          'backend_services_modified': False, 'database_mutation_performed': False,
                          'environment_modified': False}, sort_keys=True))
        sys.exit(1)
