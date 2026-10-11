#!/usr/bin/env python3
"""Publish a frozen private-navigation frontend without changing any backend.

Only a fresh static directory, this release's proof files and the exact Nginx
root replacement are writable. The accepted 3c5b8c1 backend remains running.
Runtime and database reads emit identities/hashes/counts, never record values.
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
import sqlite3
import stat
import sys
import tarfile


HOST = 'iZj6c4cj7edgnhdimts4l7Z'
BACKEND_SOURCE = '3c5b8c1d63b8f078e162e228750b508715699479'
BACKEND_IMAGE = 'sha256:322968e1935a6f7bb2e6d366a9f1cdb98aefab392af28c7269660ff46262a886'
BACKEND_IDS = {
    'api': '64d94c4fc688dfd0b0238c1d88eb86aa8836003f7803cbc1bd8e75ac2457f5e0',
    'worker': 'd62dc74857a6e33219d342b09520e0bdbd71c2c5223555e2999522751a8a1dda',
}
CANDIDATE_ROOT = Path('/opt/t24-crm/releases/private-finance-3c5b8c1d63b8-20261011-candidate')
CANDIDATE = CANDIDATE_ROOT / 'candidate.json'
CANDIDATE_SHA = '98b0cab59c3611db73c3282baad69ebc7011cd6eb01a36627fdbc0f3967c5301'
SWITCH_STATE = CANDIDATE_ROOT / 'seeded-repair/switch-state.json'
SWITCH_SHA = 'f120864160e750bdc51cdb8d1ffc7840cd9c0253aa1ac6c9d151688014a7c803'
PREVIOUS_STATIC = CANDIDATE_ROOT / 'seeded-repair/static-release/static-state.json'
PREVIOUS_STATIC_SHA = 'ac9c8416bc64b40355557f266371e12c80d661ac91d67c06549af3b7b042409c'
PREVIOUS_VERSION = '374558c66144'
PREVIOUS_PUBLIC = Path('/var/www/t24-crm-public/private-completed-3c5b8c1d63b8-20261011')
RETAINED_TOOLS = Path('/opt/t24-crm/releases/private-finance-carrier-f2f3df48f6d2-20261011')
RETAINED_HASHES = {
    'seed_private_stripe.py': 'e4c3b2690a316f102f2f66da3001334ffe51636982e283910dfd75f4f8a62f4c',
    'resume_seed_private_stripe.py': '4f72789d96afbee889117f7a0a8442ba5e7b4790d353e235eb2411db236b20ef',
    'candidate_prepare.py': 'ae909d12bebc7ada62bae5487085bf45c718ef38e6a71ec644e408421622c6ec',
    'switch_completed.py': 'a3b2dedac7763f9dc1b0615ec1cd9730c2b68bb772bc11e8bb10696f5e52503c',
    'credential_transfer.py': 'ebb8b42c332247dec30b39f99c857defef11e360a5e7fedc90792ca8614d64e3',
    'resume_preflight.py': 'bd8daa6c52daadd97f2c37d63b268cdb0694a4aa5e2b3d98eabd723f70b8a24a',
    'acquire_candidate.py': '66f26ee5490847e1777ebee1172eadeaf3865ef55bd5fac7432e0dbaee0a1070',
    'live_preflight.py': '0660a94d11b31986b3b0b8edc706f5a4c0b026396b466e3589b15c2fdf78bdcc',
    'seeded_repair.py': '5fe8544bbe25cd56b4bc364cabc264b53b57bdfa5770e811ab5276b202607416',
    'private_schema_guard.py': 'e9d6039c391434da7af26e0528f259a6373e80eeec0808c0a936f9caf975910c',
    'build_payload.py': 'cbb36192e631b2e0916c77a0e4935b52e31da720dab578eb2889e6b1a305107f',
    'diagnose_private_stripe.py': '17b62c87e576dd6586bc3641279fe7727d69ffcd2ce76a951d8dca8cabc44483',
    'static_completed.py': 'fb9d29fb70d38bf206b059cad27ba764d8bea705834bd43949cfca2e3d2498d7',
}
ALLOWED_SOURCE_FILES = frozenset({
    'app/frontend/src/pages/PrivateWorkspace.tsx',
    'app/frontend/src/pages/private-workspace.css',
    'app/frontend/src/pages/PrivateAdsDashboard.tsx',
    'app/frontend/src/lib/private-workspace-navigation.ts',
    'app/frontend/tests/private-workspace-mail-ui.test.mjs',
    'app/frontend/tests/private-workspace-navigation.test.mjs',
})
DISABLED_FLAGS = {
    'PRIVATE_WORKSPACE_PLAID_ENABLED': 'false',
    'PRIVATE_MAIL_TRANSLATION_ENABLED': 'false',
    'PRIVATE_MAIL_BRIEF_ENABLED': 'false',
    'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT': 'false',
    'PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED': 'false',
    'PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT': 'false',
}
HASH = re.compile('[a-f0-9]{64}')
SOURCE = re.compile('[a-f0-9]{40}')
VERSION = re.compile('[a-f0-9]{12}')


class StaticError(RuntimeError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise StaticError('ARGUMENTS_REJECTED')


def need(condition, code):
    if not condition:
        raise StaticError(code)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def safe_error(error):
    allowed = isinstance(error, StaticError) or type(error).__name__ in {'SwitchError', 'GuardError', 'TransferError'}
    return str(error) if allowed and re.fullmatch('[A-Z0-9_]{1,100}', str(error)) else 'STATIC_RELEASE_FAILED'


def protected(path, directory=False):
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_PROTECTED_PATH_REQUIRED')
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid == 0
             and not stat.S_IMODE(info.st_mode) & 0o022, 'PROTECTED_ANCESTOR_REQUIRED')
    info = path.lstat()
    need(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
         and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
         'ROOT_PRIVATE_FILE_OR_DIRECTORY_REQUIRED')
    return info


def protected_bytes(path, maximum):
    before = protected(path)
    need(before.st_size <= maximum, 'PROTECTED_FILE_SIZE_LIMIT')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        need((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), 'PROTECTED_FILE_CHANGED')
        blob = stream.read(maximum + 1)
    need(len(blob) <= maximum, 'PROTECTED_FILE_SIZE_LIMIT')
    return blob


def retained_tools():
    protected(RETAINED_TOOLS, True)
    for name, expected in RETAINED_HASHES.items():
        need(sha(protected_bytes(RETAINED_TOOLS / name, 1024 * 1024)) == expected, 'RETAINED_TOOL_HASH_DRIFT')
        need(name.removesuffix('.py') not in sys.modules, 'RETAINED_TOOL_MODULE_ALREADY_LOADED')
    # Imports must not create bytecode in the retained immutable carrier.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(RETAINED_TOOLS))
    spec = importlib.util.spec_from_file_location('_t24_navigation_static_base', RETAINED_TOOLS / 'static_completed.py')
    need(spec and spec.loader, 'RETAINED_STATIC_LOADER_REQUIRED')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def accepted_receipts(base):
    candidate = base.fixed_json(CANDIDATE, CANDIDATE_SHA)
    state = base.fixed_json(SWITCH_STATE, SWITCH_SHA)
    previous = base.fixed_json(PREVIOUS_STATIC, PREVIOUS_STATIC_SHA)
    need(candidate.get('stage') == 'PRIVATE_FINANCE_CANDIDATE_VERIFIED'
         and candidate.get('source_sha') == BACKEND_SOURCE and candidate.get('image_id') == BACKEND_IMAGE
         and candidate.get('frontend_version') == PREVIOUS_VERSION, 'ACCEPTED_BACKEND_CANDIDATE_REQUIRED')
    need(state.get('phase') == 'PRIVATE_COMPLETED_RELEASE_SERVER_VERIFIED'
         and state.get('source_sha') == BACKEND_SOURCE and state.get('candidate_image') == BACKEND_IMAGE
         and state.get('new_ids') == BACKEND_IDS and state.get('deployed') is True
         and state.get('business_tables_verified') == 83 and state.get('public_assets_published') is False
         and all(state.get(key) is False for key in ('bank_enabled', 'ai_enabled', 'initializer_rerun',
                 'credential_seed_attempted', 'databases_restored')), 'ACCEPTED_BACKEND_SWITCH_REQUIRED')
    need(previous.get('phase') == 'PRIVATE_COMPLETED_PUBLIC_RELEASE_VERIFIED'
         and previous.get('source_sha') == BACKEND_SOURCE and previous.get('frontend_version') == PREVIOUS_VERSION
         and previous.get('candidate_sha256') == CANDIDATE_SHA and previous.get('switch_state_sha256') == SWITCH_SHA
         and previous.get('public_root') == str(PREVIOUS_PUBLIC) and previous.get('deployed') is True
         and previous.get('business_tables_verified') == 83
         and all(previous.get(key) is False for key in ('backend_services_modified', 'databases_restored',
                 'bank_enabled', 'ai_enabled')) and HASH.fullmatch(previous.get('new_nginx_sha256', '')),
         'ACCEPTED_PREVIOUS_STATIC_REQUIRED')
    return candidate, state, previous


def disabled_live_features(base, healthy=True):
    if healthy:
        for role in ('api', 'worker'):
            rows = base.inspect('t24-private-' + role)['Config'].get('Env', [])
            need(all(isinstance(row, str) and '=' in row for row in rows), 'PRIVATE_ENVIRONMENT_SHAPE_DRIFT')
            values = dict(row.split('=', 1) for row in rows)
            need(len(values) == len(rows) and all(values.get(key) == value for key, value in DISABLED_FLAGS.items()),
                 'BANK_AND_AI_MUST_REMAIN_DISABLED')
    # Provider syncs may change rows normally. Only disabled-feature state is
    # checked; neither historical business rows nor mail/private actions are pinned.
    with sqlite3.connect(base.PRIVATE_DB.as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        for table in ('private_mail_translations', 'private_translation_usage', 'private_mail_briefs',
                      'private_mail_brief_usage', 'private_workspace_briefs', 'private_bank_links'):
            need(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0, 'BANK_OR_AI_DATA_MUST_REMAIN_DISABLED')
        need(db.execute("SELECT 1 FROM private_connections WHERE source_id='bofa_bank' AND "
                        "(status='connected' OR encrypted_credentials IS NOT NULL) LIMIT 1").fetchone() is None,
             'BANK_CONNECTION_MUST_REMAIN_DISABLED')


def runtime(base, candidate, state, previous, healthy=True):
    current = base.runtime_snapshot(state, candidate, healthy=healthy)
    need(current == previous['private_and_crm_runtime'], 'FORMAL_BACKEND_RUNTIME_OR_SCHEMA_DRIFT')
    disabled_live_features(base, healthy=healthy)
    return current


def checked_manifest(base, release, expected, source, version):
    need(HASH.fullmatch(expected or ''), 'REVIEWED_MANIFEST_HASH_REQUIRED')
    blob = protected_bytes(release / 'static-manifest.json', 4 * 1024 * 1024)
    need(sha(blob) == expected, 'STATIC_MANIFEST_HASH_DRIFT')
    value = json.loads(blob)
    changed = value.get('changed_source_files')
    need(value.get('format_version') == 1 and value.get('stage') == 'FROZEN_PRIVATE_NAVIGATION_STATIC_SOURCE'
         and value.get('frontend_source_sha') == source and value.get('frontend_version') == version
         and value.get('backend_source_sha') == BACKEND_SOURCE and value.get('previous_frontend_version') == PREVIOUS_VERSION
         and all(value.get(key) is False for key in ('backend_changes', 'credentials_included', 'databases_modified'))
         and value.get('static_only') is True and isinstance(changed, list) and len(changed) == len(set(changed))
         and 1 <= len(changed) <= len(ALLOWED_SOURCE_FILES) and set(changed) <= ALLOWED_SOURCE_FILES
         and 'app/frontend/src/pages/PrivateWorkspace.tsx' in changed, 'NAVIGATION_ONLY_MANIFEST_REQUIRED')
    files = value.get('payload_files')
    need(isinstance(files, dict) and 2 <= len(files) < 10000 and {'index.html', 'app-version.json'} <= files.keys(),
         'COMPLETE_STATIC_FILE_INVENTORY_REQUIRED')
    for name, expected_hash in files.items():
        relative = PurePosixPath(name)
        need(isinstance(name, str) and name == relative.as_posix() and not relative.is_absolute()
             and '..' not in relative.parts and not any(part.startswith('.') for part in relative.parts)
             and relative.suffix in base.SUFFIXES and HASH.fullmatch(expected_hash or '')
             and (relative.suffix != '.html' or name in {'index.html', 'offline.html'}), 'STATIC_FILE_ALLOWLIST_REJECTED')
    archive = protected_bytes(release / 'static-payload.tar.gz', 64 * 1024 * 1024)
    need(HASH.fullmatch(value.get('payload_sha256', '')) and sha(archive) == value['payload_sha256'],
         'STATIC_PAYLOAD_HASH_DRIFT')
    return value, archive


def extract_static(base, release, manifest, archive, version):
    root = release / 'payload'
    need(not root.exists() and not root.is_symlink(), 'NEW_PAYLOAD_DIRECTORY_REQUIRED')
    root.mkdir(mode=0o700)
    extracted = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as stream:
        for member in stream:
            need(member.isfile() and not member.pax_headers and member.name.startswith('payload/'), 'REGULAR_STATIC_FILES_ONLY')
            name = member.name.removeprefix('payload/')
            relative = PurePosixPath(name)
            need(name == relative.as_posix() and not relative.is_absolute() and '..' not in relative.parts
                 and not any(part.startswith('.') for part in relative.parts) and name in manifest['payload_files']
                 and name not in extracted and 0 <= member.size <= 16 * 1024 * 1024, 'STATIC_ARCHIVE_ALLOWLIST_DRIFT')
            total += member.size
            need(total < 64 * 1024 * 1024, 'STATIC_ARCHIVE_TOTAL_SIZE_LIMIT')
            handle = stream.extractfile(member)
            need(handle is not None, 'STATIC_MEMBER_STREAM_REQUIRED')
            data = handle.read(member.size + 1)
            need(len(data) == member.size and sha(data) == manifest['payload_files'][name], 'STATIC_MEMBER_HASH_DRIFT')
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            base.write_new(target, data)
            extracted[name] = sha(data)
    need(extracted == manifest['payload_files'] and base.file_map(root) == extracted, 'COMPLETE_STATIC_ARCHIVE_REQUIRED')
    need(json.loads((root / 'app-version.json').read_bytes()) == {'version': version}, 'FROZEN_FRONTEND_VERSION_DRIFT')
    return root


def rollback(base, original, changed, candidate, state, previous):
    runtime(base, candidate, state, previous, healthy=False)
    current = sha(base.read_nginx())
    need(current in {sha(original), sha(changed)}, 'STATIC_ROLLBACK_CONCURRENT_CHANGE')
    if current != sha(original):
        base.atomic_nginx(original, {sha(changed)})
        base.run(['nginx', '-t'], 'ROLLBACK_NGINX_TEST_FAILED')
        base.run(['systemctl', 'reload', 'nginx'], 'ROLLBACK_NGINX_RELOAD_FAILED')
    need(sha(base.read_nginx()) == sha(original), 'STATIC_ROLLBACK_BYTES_DRIFT')
    base.public_check(base.file_map(PREVIOUS_PUBLIC), PREVIOUS_VERSION, PREVIOUS_PUBLIC, verify_services=False)


def main(args, base=None):
    need(args.execute and os.geteuid() == 0 and socket.gethostname() == HOST, 'EXPLICIT_AUTHENTICATED_ROOT_SERVER_REQUIRED')
    need(SOURCE.fullmatch(args.frontend_source_sha or '') and args.frontend_source_sha != BACKEND_SOURCE
         and VERSION.fullmatch(args.frontend_version or '') and args.frontend_version != PREVIOUS_VERSION
         and HASH.fullmatch(args.manifest_sha256 or ''), 'NEW_FROZEN_FRONTEND_IDENTITY_REQUIRED')
    release = Path(__file__).resolve().parent
    need(release == Path('/opt/t24-crm/releases') / ('private-navigation-' + args.frontend_source_sha[:12] + '-20261011'),
         'EXACT_FRESH_NAVIGATION_RELEASE_PATH_REQUIRED')
    protected(release, True)
    base = base or retained_tools()
    candidate, state, previous = accepted_receipts(base)
    base.RELEASE = release
    base.OLD_PUBLIC = PREVIOUS_PUBLIC
    base.PUBLIC = Path('/var/www/t24-crm-public') / ('private-navigation-' + args.frontend_source_sha[:12] + '-20261011')
    lock = base.CONFIG / 'private-finance-release.lock'
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        protected(lock)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        baseline = runtime(base, candidate, state, previous)
        original = base.read_nginx()
        changed = base.changed_nginx(original, previous['new_nginx_sha256'])
        # Verify the exact currently served version before any publication.
        base.public_check(base.file_map(PREVIOUS_PUBLIC), PREVIOUS_VERSION, PREVIOUS_PUBLIC)
        manifest, archive = checked_manifest(base, release, args.manifest_sha256,
                                             args.frontend_source_sha, args.frontend_version)
        payload = extract_static(base, release, manifest, archive, args.frontend_version)
        public = base.install_public(payload)
        need(runtime(base, candidate, state, previous) == baseline and sha(base.read_nginx()) == sha(original),
             'PREPARATION_RUNTIME_OR_NGINX_DRIFT')
        before = base.business_fingerprints()
        receipt = release / 'static-state.json'
        report = {
            'format_version': 1, 'phase': 'PRIVATE_NAVIGATION_STATIC_PREPARED',
            'frontend_source_sha': args.frontend_source_sha, 'frontend_version': args.frontend_version,
            'backend_source_sha': BACKEND_SOURCE, 'backend_candidate_sha256': CANDIDATE_SHA,
            'backend_switch_state_sha256': SWITCH_SHA, 'previous_static_state_sha256': PREVIOUS_STATIC_SHA,
            'manifest_sha256': args.manifest_sha256, 'payload_sha256': manifest['payload_sha256'],
            'previous_frontend_version': PREVIOUS_VERSION, 'public_root': str(base.PUBLIC),
            'original_nginx_sha256': sha(original), 'new_nginx_sha256': sha(changed),
            'private_and_crm_runtime': baseline, 'business_before_fingerprint_sha256': base.digest(before),
            'backend_services_modified': False, 'databases_modified': False, 'databases_restored': False,
            'credential_seed_attempted': False, 'bank_enabled': False, 'ai_enabled': False, 'deployed': False,
        }
        base.write_new(release / 'nginx-before.conf', original)
        base.save(receipt, report)
        try:
            need(runtime(base, candidate, state, previous) == baseline and sha(base.read_nginx()) == sha(original),
                 'FINAL_STATIC_PREFLIGHT_DRIFT')
            base.atomic_nginx(changed, {sha(original)})
            base.run(['nginx', '-t'], 'STATIC_NGINX_TEST_FAILED')
            base.run(['systemctl', 'reload', 'nginx'], 'STATIC_NGINX_RELOAD_FAILED')
            report['phase'] = 'PRIVATE_NAVIGATION_STATIC_SWITCHED'
            base.save(receipt, report, replace=True)
            base.public_check(public, args.frontend_version, base.PUBLIC)
            need(runtime(base, candidate, state, previous) == baseline and sha(base.read_nginx()) == sha(changed)
                 and base.file_map(base.PUBLIC) == public, 'STATIC_POST_PUBLISH_DRIFT')
            after = base.business_fingerprints()
            need(before == after, 'CURRENT_RELEASE_CUSTOMER_FINGERPRINT_DRIFT')
            report.update(phase='PRIVATE_NAVIGATION_STATIC_RELEASE_VERIFIED', business_tables_verified=83,
                          business_after_fingerprint_sha256=base.digest(after), deployed=True)
            base.save(receipt, report, replace=True)
            print(json.dumps({'stage': report['phase'], 'receipt_path': str(receipt),
                              'receipt_sha256': sha(receipt.read_bytes()), 'frontend_version': args.frontend_version,
                              'backend_source_sha': BACKEND_SOURCE, 'business_tables_verified': 83,
                              'backend_services_modified': False, 'databases_modified': False,
                              'bank_enabled': False, 'ai_enabled': False, 'deployed': True}, sort_keys=True))
            return report
        except BaseException as error:
            report['deployed'] = False
            report['failure_code'] = safe_error(error)
            try:
                rollback(base, original, changed, candidate, state, previous)
                report['phase'] = 'PRIVATE_NAVIGATION_STATIC_ROLLBACK_VERIFIED'
                base.save(receipt, report, replace=True)
            except BaseException:
                report['phase'] = 'PRIVATE_NAVIGATION_STATIC_ROLLBACK_REQUIRES_REVIEW'
                base.save(receipt, report, replace=True)
                raise StaticError('STATIC_ROLLBACK_REQUIRES_REVIEW') from None
            raise StaticError('STATIC_RELEASE_REJECTED_ROLLBACK_VERIFIED') from None
    finally:
        os.close(fd)


if __name__ == '__main__':
    parser = SafeParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--frontend-source-sha', required=True)
    parser.add_argument('--frontend-version', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    try:
        main(parser.parse_args())
    except BaseException as error:
        code = safe_error(error)
        print(json.dumps({'stage': 'PRIVATE_NAVIGATION_STATIC_RELEASE_REJECTED', 'error': code, 'deployed': False}, sort_keys=True))
        raise SystemExit(1) from None
