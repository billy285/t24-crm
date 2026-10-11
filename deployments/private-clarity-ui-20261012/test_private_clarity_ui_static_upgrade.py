"""Offline regressions; never import a server helper or contact production."""
import copy
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography.fernet import Fernet
import pytest


HERE = Path(__file__).resolve().parent
REVIEWED_SOURCE = '8e1c07415e78db6b9ef199e997e501d1db4dc5e6'
REVIEWED_VERSION = 'ecae2d8aa23a'
REVIEWED_MANIFEST = '19b6b72ed7db9bfc52821777a511381f77035a4974cd89863ed1b9969f56d210'
REVIEWED_PAYLOAD = '51c5e12784dca30be0a0b5c4ba819fa5dcf6cec61ad8bb20d8d6be65d9b25d90'
REVIEWED_SCOPE = frozenset({
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
spec = importlib.util.spec_from_file_location('private_clarity_static_tested', HERE / 'private-clarity-ui-static-upgrade.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def file_map(root):
    return {path.relative_to(root).as_posix(): s.sha(path.read_bytes())
            for path in sorted(root.rglob('*')) if path.is_file()}


def write_new(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(value)


def archive(files, *, names=None, link=None):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz', format=tarfile.USTAR_FORMAT) as stream:
        for name in names or list(files):
            value = files[name]
            item = tarfile.TarInfo('payload/' + name)
            item.size = len(value)
            stream.addfile(item, io.BytesIO(value))
        if link:
            item = tarfile.TarInfo('payload/' + link)
            item.type, item.linkname = tarfile.SYMTYPE, '/etc/passwd'
            stream.addfile(item)
    return result.getvalue()


@pytest.fixture
def frozen(tmp_path):
    release = tmp_path / 'release'
    release.mkdir(mode=0o700)
    args = SimpleNamespace(frontend_source_sha='8e1c07415e78db6b9ef199e997e501d1db4dc5e6',
                           frontend_version='ecae2d8aa23a')
    files = {'index.html': b'<script src="/assets/new.js"></script>',
             'app-version.json': encoded({'version': args.frontend_version}),
             'assets/new.js': b'console.log("usd")'}
    payload = archive(files)
    manifest = {'format_version': 1, 'stage': 'FROZEN_PRIVATE_CLARITY_UI_STATIC_SOURCE',
                'frontend_source_sha': args.frontend_source_sha, 'frontend_version': args.frontend_version,
                'backend_source_sha': s.BACKEND_SOURCE, 'previous_frontend_version': s.PREVIOUS_VERSION,
                'static_only': True, 'backend_changes': False, 'credentials_included': False,
                'databases_modified': False, 'services_modified': False,
                'changed_source_files': {name: 'a' * 64 for name in s.ALLOWED_SOURCE_FILES},
                'payload_files': {name: s.sha(value) for name, value in files.items()},
                'payload_sha256': s.sha(payload)}
    args.manifest_sha256, args.payload_sha256 = s.sha(encoded(manifest)), s.sha(payload)
    (release / 'static-manifest.json').write_bytes(encoded(manifest))
    (release / 'static-payload.tar.gz').write_bytes(payload)
    base = SimpleNamespace(SUFFIXES={'.html', '.json', '.js', '.css', '.png'},
                           write_new=write_new, file_map=file_map)
    upgrade = SimpleNamespace(fixed_json=lambda path, expected: checked_json(path, expected),
                              read_protected=lambda path, maximum=4*1024**2: path.read_bytes())
    return release, args, files, payload, manifest, base, upgrade


def checked_json(path, expected):
    value = path.read_bytes()
    s.need(s.sha(value) == expected, 'FIXED_HASH_DRIFT')
    return json.loads(value)


def refreeze(frozen, manifest=None, payload=None):
    release, args, _, old_payload, old_manifest, _, _ = frozen
    manifest = copy.deepcopy(old_manifest if manifest is None else manifest)
    payload = old_payload if payload is None else payload
    manifest['payload_sha256'] = args.payload_sha256 = s.sha(payload)
    args.manifest_sha256 = s.sha(encoded(manifest))
    (release / 'static-manifest.json').write_bytes(encoded(manifest))
    (release / 'static-payload.tar.gz').write_bytes(payload)
    return manifest, payload


def test_complete_valid_frozen_payload_extracts_only_declared_bytes(frozen):
    release, args, files, _, _, base, upgrade = frozen
    manifest, payload = s.checked_manifest(upgrade, base, release, args)
    result = s.extract_static(base, release, manifest, payload, args.frontend_version)
    assert file_map(result) == {name: s.sha(value) for name, value in files.items()}
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in result.rglob('*') if path.is_file())
    with pytest.raises(s.StaticError, match='FRESH_STATIC_PAYLOAD_REQUIRED'):
        s.extract_static(base, release, manifest, payload, args.frontend_version)


def test_actual_reviewed_113_file_clarity_artifacts_match_publisher_contract(frozen):
    release, args, _, _, _, base, upgrade = frozen
    source = HERE / 'artifacts'
    for name in ('static-manifest.json', 'static-payload.tar.gz'):
        (release / name).write_bytes((source / name).read_bytes())
    args.manifest_sha256 = '19b6b72ed7db9bfc52821777a511381f77035a4974cd89863ed1b9969f56d210'
    args.payload_sha256 = '51c5e12784dca30be0a0b5c4ba819fa5dcf6cec61ad8bb20d8d6be65d9b25d90'
    base.SUFFIXES = {'.html','.js','.css','.json','.png','.jpg','.jpeg','.webp','.gif','.svg',
                     '.ico','.txt','.woff','.woff2','.ttf','.webmanifest'}
    manifest, payload = s.checked_manifest(upgrade, base, release, args)
    root = s.extract_static(base, release, manifest, payload, args.frontend_version)
    assert len(file_map(root)) == 113
    assert len(REVIEWED_SCOPE) == 22
    assert set(manifest['changed_source_files']) == s.ALLOWED_SOURCE_FILES == REVIEWED_SCOPE
    assert manifest['frontend_source_sha'] == REVIEWED_SOURCE
    assert manifest['frontend_version'] == REVIEWED_VERSION
    repo = HERE.parents[1]
    assert {name: s.sha((repo / name).read_bytes()) for name in REVIEWED_SCOPE} == manifest['changed_source_files']


def test_exact_reviewed_release_constants_and_current_currency_baseline_are_pinned():
    assert s.FRONTEND_SOURCE == REVIEWED_SOURCE and s.FRONTEND_VERSION == REVIEWED_VERSION
    assert s.PREVIOUS_SOURCE == '08e8505f5a6ea66626e91b2089394ef001c54fd7'
    assert s.PREVIOUS_VERSION == 'adfb31c0b755'
    assert s.BACKEND_SOURCE == 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
    assert s.BACKEND_VERSION == '913856b4d17b'
    assert s.PREVIOUS_RECEIPT_SHA == 'dd7ccc6ee0d4273a281a7fb579ea871287305d41142b0363bc1624779ddeae48'
    assert s.PREVIOUS_MANIFEST_SHA == '68d3261cb84f6aab5070f3955a48644ff59d0659b6fc42348890b8e64f65fcb8'
    assert s.PREVIOUS_PAYLOAD_SHA == '34ff135b21a094645c41b7d1a606b357833f610c4755dd246bf1884a5941a16d'
    assert s.PREVIOUS_NGINX_SHA == '17c41c4989662fa8c298677441d5c539949326e534e2d59fd9545b50c205c35b'
    assert s.PREVIOUS_RELEASE != s.BACKEND_RELEASE
    assert s.PREVIOUS_PUBLIC != s.BACKEND_PUBLIC
    assert s.sha((HERE / 'artifacts/static-manifest.json').read_bytes()) == REVIEWED_MANIFEST
    assert s.sha((HERE / 'artifacts/static-payload.tar.gz').read_bytes()) == REVIEWED_PAYLOAD


@pytest.mark.parametrize('key,value', [
    ('backend_source_sha', 'f' * 40), ('previous_frontend_version', 'f' * 12),
    ('frontend_source_sha', 'f' * 40), ('frontend_version', 'f' * 12),
    ('stage', 'FROZEN_PRIVATE_NAVIGATION_STATIC_SOURCE'), ('static_only', False),
    ('backend_changes', True), ('credentials_included', True), ('databases_modified', True),
    ('services_modified', True), ('changed_source_files', ['app/frontend/src/lib/private-stripe-report.ts']),
    ('changed_source_files', {'app/backend/main.py': 'a'*64}),
    ('changed_source_files', {name: 'INVALID' for name in s.ALLOWED_SOURCE_FILES}),
])
def test_backend_credential_scope_and_provenance_fail_closed(frozen, key, value):
    release, args, _, _, manifest, base, upgrade = frozen
    manifest[key] = value
    refreeze(frozen, manifest)
    with pytest.raises(s.StaticError, match='EXACT_CLARITY_FRONTEND_ONLY_MANIFEST_REQUIRED'):
        s.checked_manifest(upgrade, base, release, args)
    assert not (release / 'payload').exists()


@pytest.mark.parametrize('name', ['../escape.js', '/absolute.js', 'assets/.hidden.js',
                                 'assets/nested/../../escape.js', 'credentials.env', 'other.html'])
def test_manifest_rejects_path_and_nonstatic_files_before_extraction(frozen, name):
    release, args, _, _, manifest, base, upgrade = frozen
    manifest['payload_files'][name] = 'a'*64
    refreeze(frozen, manifest)
    with pytest.raises(s.StaticError, match='STATIC_FILE_SCOPE_REJECTED'):
        s.checked_manifest(upgrade, base, release, args)


@pytest.mark.parametrize('which', ['manifest', 'payload', 'manifest_pin', 'payload_pin'])
def test_independent_artifact_hashes_required(frozen, which):
    release, args, _, _, _, base, upgrade = frozen
    if which in {'manifest', 'payload'}:
        path = release / ('static-manifest.json' if which == 'manifest' else 'static-payload.tar.gz')
        path.write_bytes(path.read_bytes() + b'X')
    else:
        setattr(args, which.replace('_pin', '_sha256'), 'g' * 64)
    with pytest.raises(s.StaticError):
        s.checked_manifest(upgrade, base, release, args)


@pytest.mark.parametrize('case', ['duplicate', 'undeclared', 'missing', 'symlink', 'traversal', 'hash', 'version'])
def test_archive_member_attacks_and_incomplete_payload_fail_closed(frozen, case):
    release, args, files, _, manifest, base, _ = frozen
    if case == 'duplicate':
        blob = archive(files, names=['index.html', 'index.html'])
    elif case == 'undeclared':
        blob = archive({**files, 'assets/unlisted.js': b'X'})
    elif case == 'missing':
        blob = archive({key: value for key, value in files.items() if key != 'index.html'})
    elif case == 'symlink':
        blob = archive(files, link='assets/link.js')
    elif case == 'traversal':
        blob = archive({'../escape.js': b'X'})
    elif case == 'hash':
        blob = archive({**files, 'assets/new.js': b'other bytes'})
    else:
        files['app-version.json'] = encoded({'version': s.PREVIOUS_VERSION})
        manifest['payload_files']['app-version.json'] = s.sha(files['app-version.json'])
        blob = archive(files)
    with pytest.raises(s.StaticError):
        s.extract_static(base, release, manifest, blob, args.frontend_version)
    assert not (release.parent / 'escape.js').exists()


def currency_fixture(base, upgrade, roles, baseline, authorization, monkeypatch):
    before = b'root ' + str(s.BACKEND_PUBLIC).encode() + b';\n'
    after = before.replace(str(s.BACKEND_PUBLIC).encode(), str(s.PREVIOUS_PUBLIC).encode())
    blob = archive({'index.html': b'currency', 'app-version.json': encoded({'version': s.PREVIOUS_VERSION})})
    monkeypatch.setattr(s, 'PREVIOUS_NGINX_SHA', s.sha(after))
    monkeypatch.setattr(s, 'PREVIOUS_PAYLOAD_SHA', s.sha(blob))
    backend_public = {'index.html': '0'*64, 'app-version.json': '1'*64, 'assets/backend.js': '2'*64}
    payload_files = {'index.html': '3'*64, 'app-version.json': '4'*64, 'assets/currency.js': '5'*64}
    public = {**payload_files, 'assets/backend.js': '2'*64}
    backend_receipt = {'new_nginx_sha256': s.sha(before), 'baseline_runtime': {'crm': 'unchanged'},
                       'private_identity': baseline['private']['identity'],
                       'target_schema_objects': {'private_stripe_reports': 'accepted'}}
    manifest = {'format_version': 1, 'stage': 'FROZEN_STRIPE_REPORT_UI_STATIC_SOURCE',
                'frontend_source_sha': s.PREVIOUS_SOURCE, 'frontend_version': s.PREVIOUS_VERSION,
                'backend_source_sha': s.BACKEND_SOURCE, 'previous_frontend_version': s.BACKEND_VERSION,
                'payload_sha256': s.PREVIOUS_PAYLOAD_SHA, 'static_only': True,
                'backend_changes': False, 'credentials_included': False,
                'databases_modified': False, 'services_modified': False, 'payload_files': payload_files}
    previous = {'format_version': 1, 'phase': 'STRIPE_REPORT_UI_STATIC_PUBLIC_VERIFIED',
                'frontend_source_sha': s.PREVIOUS_SOURCE, 'frontend_version': s.PREVIOUS_VERSION,
                'backend_source_sha': s.BACKEND_SOURCE, 'previous_frontend_version': s.BACKEND_VERSION,
                'pins': s.PINS, 'owner_after_sha256': s.OWNER_AFTER_SHA,
                'manifest_sha256': s.PREVIOUS_MANIFEST_SHA, 'payload_sha256': s.PREVIOUS_PAYLOAD_SHA,
                'old_public_root': str(s.BACKEND_PUBLIC), 'public_root': str(s.PREVIOUS_PUBLIC),
                'old_nginx_sha256': s.sha(before), 'new_nginx_sha256': s.PREVIOUS_NGINX_SHA,
                'roles': roles, 'private_identity': baseline['private']['identity'],
                'business_tables_verified': 83, 'private_tables_verified': 11,
                'deployed': True, 'same_private_inode': True, 'credentials_and_generation_unchanged': True,
                'crm_runtime_and_all_83_tables_unchanged': True, 'previous_assets_preserved': True,
                'backend_services_modified': False, 'database_mutation_performed': False,
                'environment_modified': False, 'bank_enabled': False, 'ai_enabled': False,
                'baseline_sha256': upgrade.digest(baseline), 'stable_authorization': authorization}
    json_files = {s.PREVIOUS_RELEASE / 'static-state.json': previous,
                  s.PREVIOUS_RELEASE / 'static-manifest.json': manifest}
    byte_files = {s.PREVIOUS_RELEASE / 'static-payload.tar.gz': blob,
                  s.PREVIOUS_RELEASE / 'payload/app-version.json': encoded({'version': s.PREVIOUS_VERSION}),
                  s.PREVIOUS_RELEASE / 'public-manifest.json': encoded(public),
                  s.PREVIOUS_RELEASE / 'nginx-before.bin': before,
                  s.PREVIOUS_RELEASE / 'nginx-after.bin': after,
                  s.PREVIOUS_RELEASE / 'runtime-schema-before.json': encoded(baseline)}
    expected_pins = {s.PREVIOUS_RELEASE / 'static-state.json': s.PREVIOUS_RECEIPT_SHA,
                     s.PREVIOUS_RELEASE / 'static-manifest.json': s.PREVIOUS_MANIFEST_SHA}
    reads = []
    old_fixed, old_read = upgrade.fixed_json, upgrade.read_protected
    def fixed_json(path, expected):
        reads.append((path, expected))
        if path in json_files:
            s.need(expected_pins[path] == expected, 'FIXED_HASH_DRIFT')
            return json_files[path]
        return old_fixed(path, expected)
    upgrade.fixed_json = fixed_json
    upgrade.read_protected = lambda path, maximum=4*1024**2: byte_files[path] if path in byte_files else old_read(path, maximum)
    old_map = base.file_map
    maps = {s.BACKEND_PUBLIC: backend_public, s.PREVIOUS_RELEASE / 'payload': payload_files,
            s.PREVIOUS_PUBLIC: public}
    base.file_map = lambda path: maps[path] if path in maps else old_map(path)
    current_nginx = [after]
    base.read_nginx = lambda: current_nginx[0]
    return SimpleNamespace(previous=previous, manifest=manifest, bytes=byte_files, maps=maps,
                           receipt=backend_receipt, public=public, before=before, after=after,
                           current_nginx=current_nginx, expected_pins=expected_pins, reads=reads)


def make_runtime(frozen, monkeypatch):
    release, args, _, _, manifest, base, upgrade = frozen
    config = release / 'config'
    config.mkdir()
    (config / 'private-finance-release.lock').write_bytes(b'')
    commands = []
    roles = {'api': {'id': 'a'*64, 'image': 'sha256:'+'c'*64, 'started_at': 'accepted'},
             'worker': {'id': 'b'*64, 'image': 'sha256:'+'c'*64, 'started_at': 'accepted'}}
    baseline = {'business': {'tables': {str(i): {'count': i} for i in range(83)}},
                'private': {'identity': {'device': 1, 'inode': 2},
                            'tables': {str(i): {} for i in range(11)}}}
    authorization, records = {'opaque': 'generation-and-ciphertext'}, {'items': 'manual-note-hash'}
    owner = {'stage': 'STRIPE_REPORT_OWNER_UI_AFTER_VERIFIED', 'source_sha': s.BACKEND_SOURCE,
             'frontend_version': s.BACKEND_VERSION, 'pins': s.PINS, 'roles': roles,
             'stable_records_and_authorization_preserved': True, 'database_mutation_performed': False,
             'services_modified': False, 'stable_authorization': authorization, 'stable_records': records}
    protected_files = {s.OWNER_AFTER: owner, s.BACKEND_RELEASE / 'acquired.json': {},
                       s.BACKEND_RELEASE / 'upgrade-state.json': {}}
    fixed_json = upgrade.fixed_json
    upgrade.fixed_json = lambda path, expected: protected_files[path] if path in protected_files else fixed_json(path, expected)
    upgrade.protected = lambda path, directory=False: path.stat() if path.exists() else None
    upgrade.stable_authorization = Mock(return_value=authorization)
    upgrade.assert_runtime_boundary = Mock()
    upgrade.assert_schema = Mock(return_value=baseline)
    upgrade.report_auth_check = Mock()
    upgrade.digest = lambda value: s.sha(encoded(value))
    currency = currency_fixture(base, upgrade, roles, baseline, authorization, monkeypatch)
    protected_files[s.BACKEND_RELEASE / 'upgrade-state.json'] = currency.receipt
    original, changed = currency.after, b'new static nginx'
    new_public = {**currency.public, 'assets/new.js': 'b'*64}
    nav = SimpleNamespace(disabled_live_features=Mock())
    preparation = SimpleNamespace(release_snapshot=Mock(return_value=baseline))
    switch = SimpleNamespace(preserved=lambda before, after: s.need(before == after, 'MANUAL_RECORDS_CHANGED'))
    upgrade.retained_tools = lambda ignored: (base, nav, preparation, switch)
    base.CONFIG, base.PRIVATE_DB, base.BUSINESS = config, release / 'private.db', release / 'business.db'
    base.changed_nginx = lambda value, expected: changed
    base.atomic_nginx = Mock(side_effect=lambda value, accepted: (s.need(s.sha(currency.current_nginx[0]) in accepted,
        'NGINX_CONCURRENT_CHANGE'), currency.current_nginx.__setitem__(0, value)))
    base.run = Mock(side_effect=lambda command, code: commands.append(command))
    base.public_check = Mock()
    base.save = lambda path, value, replace=False: path.write_bytes(encoded(value)) if replace else write_new(path, encoded(value))
    local_file_map = base.file_map
    base.file_map = lambda path: new_public if path == getattr(base, 'PUBLIC', None) else local_file_map(path)
    base.install_public = Mock(return_value=new_public)
    verifier = SimpleNamespace(load_upgrade=lambda expected: upgrade,
        stable_digests=Mock(return_value=records), current_roles=Mock(return_value=(None, roles)))
    # The retained backend proof is separately reviewed. Apply tests exercise
    # the actual currency baseline validator, static boundary checks and rollback.
    monkeypatch.setattr(s, 'checked_backend_release', lambda *ignored: (None, currency.receipt, None, None, None, roles, currency.maps[s.BACKEND_PUBLIC]))
    return SimpleNamespace(release=release, args=args, base=base, upgrade=upgrade, verifier=verifier,
        current_nginx=currency.current_nginx, original=original, changed=changed, commands=commands,
        receipt=currency.receipt, roles=roles, baseline=baseline, currency=currency)

def test_static_publish_preserves_backend_crm_credentials_and_old_assets(frozen, monkeypatch):
    runtime = make_runtime(frozen, monkeypatch)
    result = s.apply(runtime.args, runtime.release, runtime.verifier)
    assert result['deployed'] is True and result['private_tables_verified'] == 11
    assert result['business_tables_verified'] == 83
    assert runtime.current_nginx == [runtime.changed]
    assert runtime.commands == [['nginx', '-t'], ['systemctl', 'reload', 'nginx']]
    state = json.loads((runtime.release / 'static-state.json').read_bytes())
    assert state['previous_assets_preserved'] and state['same_private_inode']
    assert state['roles'] == runtime.roles and state['credentials_and_generation_unchanged']
    assert all(state[key] is False for key in ('backend_services_modified', 'database_mutation_performed', 'environment_modified'))
    assert state['previous_frontend_version'] == 'adfb31c0b755'
    assert state['old_public_root'] == str(s.PREVIOUS_PUBLIC)
    assert state['previous_static_receipt_sha256'] == s.PREVIOUS_RECEIPT_SHA


@pytest.mark.parametrize('key,value', [
    ('phase', 'STRIPE_REPORT_PUBLIC_RELEASE_VERIFIED'), ('frontend_source_sha', 'f'*40),
    ('frontend_version', s.BACKEND_VERSION), ('backend_source_sha', 'f'*40),
    ('previous_frontend_version', 'f'*12), ('pins', {}), ('owner_after_sha256', 'f'*64),
    ('manifest_sha256', 'f'*64), ('payload_sha256', 'f'*64),
    ('old_public_root', '/var/www/unreviewed'), ('public_root', str(s.BACKEND_PUBLIC)),
    ('old_nginx_sha256', 'f'*64), ('new_nginx_sha256', 'f'*64), ('roles', {}),
    ('private_identity', {'device': 1, 'inode': 999}),
    ('business_tables_verified', 82), ('private_tables_verified', 10),
    ('deployed', False), ('same_private_inode', False),
    ('credentials_and_generation_unchanged', False),
    ('crm_runtime_and_all_83_tables_unchanged', False), ('previous_assets_preserved', False),
    ('backend_services_modified', True), ('database_mutation_performed', True),
    ('environment_modified', True), ('bank_enabled', True), ('ai_enabled', True),
    ('failure_code', None), ('rollback_attempted', False), ('rollback_failure_code', None),
])
def test_current_currency_receipt_drift_prevents_all_new_static_writes(frozen, monkeypatch, key, value):
    runtime = make_runtime(frozen, monkeypatch)
    runtime.currency.previous[key] = value
    with pytest.raises(s.StaticError, match='CURRENT_CURRENCY_RECEIPT_REQUIRED'):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    assert not (runtime.release / 'payload').exists()
    assert not (runtime.release / 'static-state.json').exists()
    runtime.base.install_public.assert_not_called()
    runtime.base.atomic_nginx.assert_not_called()
    assert runtime.commands == [] and runtime.current_nginx == [runtime.original]


@pytest.mark.parametrize('key,value', [
    ('format_version', 2), ('stage', 'FROZEN_PRIVATE_CLARITY_UI_STATIC_SOURCE'),
    ('frontend_source_sha', REVIEWED_SOURCE), ('frontend_version', REVIEWED_VERSION),
    ('backend_source_sha', 'f'*40), ('previous_frontend_version', s.PREVIOUS_VERSION),
    ('payload_sha256', 'f'*64), ('static_only', False), ('backend_changes', True),
    ('credentials_included', True), ('databases_modified', True), ('services_modified', True),
    ('payload_files', {'assets/only.js': 'a'*64}),
])
def test_current_currency_manifest_drift_is_rejected(frozen, monkeypatch, key, value):
    runtime = make_runtime(frozen, monkeypatch)
    runtime.currency.manifest[key] = value
    with pytest.raises(s.StaticError, match='CURRENT_CURRENCY_MANIFEST_REQUIRED'):
        s.checked_current_release(runtime.upgrade, runtime.base, runtime.receipt, runtime.roles)
    runtime.base.atomic_nginx.assert_not_called()


@pytest.mark.parametrize('case', [
    'receipt_pin', 'manifest_pin', 'payload_bytes', 'extracted_bytes', 'version',
    'asset_collision', 'public_manifest', 'public_bytes', 'nginx_before', 'nginx_after',
    'active_nginx', 'baseline_digest', 'baseline_identity', 'authorization',
])
def test_current_currency_artifact_and_nginx_guards_fail_closed(frozen, monkeypatch, case):
    runtime = make_runtime(frozen, monkeypatch)
    currency = runtime.currency
    if case in {'receipt_pin', 'manifest_pin'}:
        name = 'static-state.json' if case == 'receipt_pin' else 'static-manifest.json'
        currency.expected_pins[s.PREVIOUS_RELEASE / name] = 'f'*64
    elif case == 'payload_bytes':
        currency.bytes[s.PREVIOUS_RELEASE / 'static-payload.tar.gz'] += b'tampered'
    elif case == 'extracted_bytes':
        currency.maps[s.PREVIOUS_RELEASE / 'payload'] = {'index.html': 'f'*64}
    elif case == 'version':
        currency.bytes[s.PREVIOUS_RELEASE / 'payload/app-version.json'] = encoded({'version': REVIEWED_VERSION})
    elif case == 'asset_collision':
        currency.maps[s.BACKEND_PUBLIC]['assets/currency.js'] = 'f'*64
    elif case == 'public_manifest':
        currency.bytes[s.PREVIOUS_RELEASE / 'public-manifest.json'] = encoded({})
    elif case == 'public_bytes':
        currency.maps[s.PREVIOUS_PUBLIC] = {'index.html': 'f'*64}
    elif case == 'nginx_before':
        currency.bytes[s.PREVIOUS_RELEASE / 'nginx-before.bin'] += b'tampered'
    elif case == 'nginx_after':
        currency.bytes[s.PREVIOUS_RELEASE / 'nginx-after.bin'] += b'tampered'
    elif case == 'active_nginx':
        runtime.current_nginx[0] = currency.before
    elif case == 'baseline_digest':
        currency.previous['baseline_sha256'] = 'f'*64
    elif case == 'baseline_identity':
        altered = copy.deepcopy(runtime.baseline)
        altered['private']['identity'] = {'device': 1, 'inode': 999}
        currency.bytes[s.PREVIOUS_RELEASE / 'runtime-schema-before.json'] = encoded(altered)
        currency.previous['baseline_sha256'] = runtime.upgrade.digest(altered)
    else:
        runtime.upgrade.stable_authorization.return_value = {'opaque': 'rotated'}
    with pytest.raises(s.StaticError):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    assert not (runtime.release / 'payload').exists()
    assert not (runtime.release / 'static-state.json').exists()
    runtime.base.install_public.assert_not_called()
    runtime.base.atomic_nginx.assert_not_called()
    assert runtime.commands == []


def test_current_currency_validator_reads_independent_pins_without_invoking_provider_or_service(frozen, monkeypatch):
    runtime = make_runtime(frozen, monkeypatch)
    previous, public = s.checked_current_release(runtime.upgrade, runtime.base, runtime.receipt, runtime.roles)
    assert previous['frontend_version'] == 'adfb31c0b755' and public == runtime.currency.public
    assert (s.PREVIOUS_RELEASE / 'static-state.json', s.PREVIOUS_RECEIPT_SHA) in runtime.currency.reads
    assert (s.PREVIOUS_RELEASE / 'static-manifest.json', s.PREVIOUS_MANIFEST_SHA) in runtime.currency.reads
    runtime.upgrade.report_auth_check.assert_not_called()
    runtime.base.public_check.assert_not_called()
    runtime.base.install_public.assert_not_called()
    runtime.base.atomic_nginx.assert_not_called()
    assert runtime.commands == []


@pytest.mark.parametrize('drift', ['schema', 'runtime', 'credentials', 'roles', 'records'])
def test_boundary_drift_prevents_nginx_switch_and_never_mutates_backend(frozen, monkeypatch, drift):
    runtime = make_runtime(frozen, monkeypatch)
    if drift == 'schema':
        runtime.upgrade.assert_schema.side_effect = s.StaticError('PRIVATE_SCHEMA_CHANGED')
    elif drift == 'runtime':
        runtime.upgrade.assert_runtime_boundary.side_effect = s.StaticError('CRM_RUNTIME_CHANGED')
    elif drift == 'credentials':
        runtime.upgrade.stable_authorization.side_effect = [{'opaque': 'generation-and-ciphertext'}, {'opaque': 'rotated'}]
    elif drift == 'roles':
        runtime.verifier.current_roles.return_value = (None, {'api': {'id': 'restarted'}})
    else:
        runtime.verifier.stable_digests.side_effect = [{'items': 'manual-note-hash'}, {'items': 'changed'}]
    with pytest.raises(s.StaticError):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    runtime.base.atomic_nginx.assert_not_called()
    assert runtime.current_nginx == [runtime.original] and runtime.commands == []


def test_failed_new_public_check_restores_only_original_nginx(frozen, monkeypatch):
    runtime = make_runtime(frozen, monkeypatch)
    runtime.base.public_check.side_effect = [None, s.StaticError('NEW_PUBLIC_ASSET_FAILED'), None]
    with pytest.raises(s.StaticError, match='NEW_PUBLIC_ASSET_FAILED'):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    assert runtime.current_nginx == [runtime.original]
    assert runtime.commands == [['nginx', '-t'], ['systemctl', 'reload', 'nginx']] * 2
    assert json.loads((runtime.release / 'static-state.json').read_bytes())['phase'] == 'PRIVATE_CLARITY_UI_STATIC_ROLLED_BACK'
    assert runtime.base.public_check.call_args.args == (runtime.currency.public, 'adfb31c0b755', s.PREVIOUS_PUBLIC)
    assert runtime.base.public_check.call_args.kwargs == {'verify_services': False}


def test_concurrent_nginx_change_blocks_rollback_overwrite(frozen, monkeypatch):
    runtime = make_runtime(frozen, monkeypatch)
    def public_check(*ignored, **kwargs):
        if runtime.current_nginx == [runtime.changed]:
            runtime.current_nginx[0] = b'other reviewed release'
            raise s.StaticError('CONCURRENT_RELEASE')
    runtime.base.public_check.side_effect = public_check
    with pytest.raises(s.StaticError, match='CONCURRENT_RELEASE'):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    assert runtime.current_nginx == [b'other reviewed release']
    assert runtime.base.atomic_nginx.call_count == 1
    assert json.loads((runtime.release / 'static-state.json').read_bytes())['phase'] == 'PRIVATE_CLARITY_UI_STATIC_ROLLBACK_NEEDS_REVIEW'


def test_safe_errors_do_not_disclose_raw_commands_or_credentials():
    assert s.safe_error(RuntimeError('rk_live_SECRET output')) == 'STATIC_RELEASE_REJECTED'
    assert s.safe_error(s.StaticError('SAFE_UPPERCASE_CODE')) == 'SAFE_UPPERCASE_CODE'
    assert s.safe_error(s.StaticError('SELECT secret FROM private_connections')) == 'STATIC_RELEASE_REJECTED'


@pytest.fixture
def oauth_refresh(frozen, monkeypatch):
    """Real local SQLite/Fernet evidence; only provider transport is substituted."""
    runtime = make_runtime(frozen, monkeypatch)
    database = runtime.release / 'current-private.db'
    backup = runtime.release / 'original-private.db'
    secret = 'SYNTHETIC-LOCAL-ONLY-ENCRYPTION-KEY'
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
    credentials = {}
    with sqlite3.connect(database) as db:
        db.execute('''CREATE TABLE private_connections (
            id TEXT PRIMARY KEY, owner_id TEXT, source_id TEXT, status TEXT,
            generation INTEGER, encrypted_credentials TEXT, metadata_json TEXT,
            oauth_state_hash TEXT, oauth_expires_at TEXT, oauth_used_at TEXT,
            created_at TEXT, updated_at TEXT)''')
        for source in ('gmail', 'google_ads', 'stripe', 'bofa_bank'):
            metadata = {'connection_mode': 'oauth' if source in {'gmail', 'google_ads'} else 'server',
                        'account_label': 'synthetic-account', 'scope': f'synthetic-{source}-scope',
                        'stripe_account_id': 'acct_synthetic' if source == 'stripe' else None,
                        'mode': 'live', 'read_only_adapter': True,
                        'ads_customer_id': '1234567890' if source == 'google_ads' else None}
            credentials[source] = {'access_token': f'SYNTHETIC-{source}-OLD-ACCESS', 'expires_at': 1000,
                                   'refresh_token': f'SYNTHETIC-{source}-REFRESH', 'scope': metadata['scope'],
                                   'client_id': 'SYNTHETIC-CLIENT', 'client_secret': 'SYNTHETIC-CLIENT-SECRET',
                                   'token_type': 'Bearer'}
            encrypted = cipher.encrypt(encoded(credentials[source])).decode()
            db.execute('INSERT INTO private_connections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                       (f'synthetic-{source}', '4', source, 'connected', 7, encrypted, json.dumps(metadata),
                        'SYNTHETIC-STATE-HASH', '2026-10-12T04:00:00Z', '2026-10-12T03:00:00Z',
                        '2026-10-11T04:00:00Z', '2026-10-12T03:00:00Z'))
    backup.write_bytes(database.read_bytes())
    database.chmod(0o600); backup.chmod(0o600)
    monkeypatch.setattr(s, 'ORIGINAL_PRIVATE', backup)
    runtime.base.PRIVATE_DB = database
    runtime.upgrade.stable_authorization = lambda base: {
        key: runtime.upgrade.digest(value)
        for key, value in s.connection_authorization_rows(runtime.upgrade, base.PRIVATE_DB).items()}
    historical = runtime.upgrade.stable_authorization(runtime.base)
    runtime.currency.previous['stable_authorization'] = historical
    runtime.receipt['backup_sha256'] = s.sha(backup.read_bytes())
    old_fixed = runtime.upgrade.fixed_json
    owner = {'stage': 'STRIPE_REPORT_OWNER_UI_AFTER_VERIFIED', 'source_sha': s.BACKEND_SOURCE,
             'frontend_version': s.BACKEND_VERSION, 'pins': s.PINS, 'roles': runtime.roles,
             'stable_records_and_authorization_preserved': True, 'database_mutation_performed': False,
             'services_modified': False, 'stable_authorization': historical}
    runtime.upgrade.fixed_json = lambda path, expected: owner if path == s.OWNER_AFTER else old_fixed(path, expected)
    calls = []
    def decrypt_probe(base, receipt, roles, pairs):
        calls.append(copy.deepcopy(pairs))
        # Supply only the established Fernet credential decoder. The full probe
        # comparison runs unchanged, without loading any business DB/service.
        decoder = '''import os,sys,types,json,base64,hashlib
from cryptography.fernet import Fernet
service=types.ModuleType('services.private_workspace')
def decrypt_credentials(value):
 key=os.environ['PRIVATE_WORKSPACE_ENCRYPTION_KEY'].strip()
 cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
 return json.loads(cipher.decrypt(value.encode()))
service.decrypt_credentials=decrypt_credentials
sys.modules['services']=types.ModuleType('services')
sys.modules['services.private_workspace']=service
'''
        process = subprocess.run([sys.executable, '-B', '-c', decoder + s.REFRESH_CREDENTIAL_PROBE],
            input=encoded(pairs), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, 'PRIVATE_WORKSPACE_ENCRYPTION_KEY': secret}, check=False, timeout=5)
        s.need(process.returncode == 0, 'ONLY_ACCESS_TOKEN_REFRESH_ALLOWED')
        return json.loads(process.stdout)
    monkeypatch.setattr(s, 'verify_refresh_credentials', decrypt_probe)
    def write_credentials(source, values):
        encrypted = cipher.encrypt(encoded(values)).decode()
        with sqlite3.connect(database) as db:
            db.execute('UPDATE private_connections SET encrypted_credentials=? WHERE source_id=?', (encrypted, source))
    for source in ('gmail', 'google_ads'):
        write_credentials(source, {**credentials[source], 'access_token': f'SYNTHETIC-{source}-NEW-ACCESS', 'expires_at': 2000})
    return SimpleNamespace(runtime=runtime, database=database, backup=backup, historical=historical,
                           credentials=credentials, write_credentials=write_credentials,
                           probe_calls=calls, secret=secret)


def refresh_check(fixture):
    runtime = fixture.runtime
    current = runtime.upgrade.stable_authorization(runtime.base)
    proof = s.checked_refreshed_authorization(runtime.upgrade, runtime.base, runtime.receipt, runtime.roles,
                                              fixture.historical, current)
    return current, proof


def test_only_google_access_token_and_expiry_refresh_preserves_authorization(oauth_refresh):
    fixture = oauth_refresh
    database_before, backup_before = fixture.database.read_bytes(), fixture.backup.read_bytes()
    live, proof = refresh_check(fixture)
    assert live == fixture.runtime.upgrade.stable_authorization(fixture.runtime.base)
    assert live != fixture.historical
    assert {pair['source_id'] for pair in fixture.probe_calls[0]} == {'gmail', 'google_ads'}
    assert fixture.database.read_bytes() == database_before and fixture.backup.read_bytes() == backup_before
    assert proof['stage'] == 'OAUTH_REFRESH_CREDENTIAL_IDENTITY_VERIFIED'
    assert proof['changed_plaintext_fields'] == ['access_token', 'expires_at']
    assert proof['writes'] is False and proof['provider_requests'] is False
    evidence = json.dumps(proof)
    assert 'SYNTHETIC-' not in evidence
    assert not any(name in evidence for name in ('old_encrypted', 'current_encrypted', 'refresh_token', 'client_secret'))
    assert 'gAAAA' not in evidence


@pytest.mark.parametrize('field', ['refresh_token', 'scope', 'client_secret', 'client_id', 'token_type'])
@pytest.mark.parametrize('source', ['gmail', 'google_ads'])
def test_refresh_exception_rejects_any_long_lived_credential_change(oauth_refresh, source, field):
    fixture = oauth_refresh
    fixture.write_credentials(source, {**fixture.credentials[source], 'access_token': 'SYNTHETIC-NEW-ACCESS',
                                      'expires_at': 2000, field: 'SYNTHETIC-CHANGED'})
    with pytest.raises(s.StaticError):
        refresh_check(fixture)


@pytest.mark.parametrize('column,value', [
    ('owner_id', '5'), ('generation', 8), ('status', 'error'),
    ('source_id', 'stripe'),
    ('oauth_state_hash', 'SYNTHETIC-DIFFERENT-STATE'), ('oauth_expires_at', '2099-01-01T00:00:00Z'),
    ('oauth_used_at', '2099-01-01T00:00:00Z'), ('created_at', '2099-01-01T00:00:00Z'),
])
def test_refresh_exception_rejects_connection_owner_generation_state_and_identity_change(oauth_refresh, column, value):
    fixture = oauth_refresh
    with sqlite3.connect(fixture.database) as db:
        db.execute(f'UPDATE private_connections SET {column}=? WHERE source_id=?', (value, 'gmail'))
    with pytest.raises(s.StaticError):
        refresh_check(fixture)


@pytest.mark.parametrize('field', ['scope', 'account_label', 'connection_mode', 'ads_customer_id', 'read_only_adapter'])
def test_refresh_exception_rejects_connection_metadata_scope_and_account_change(oauth_refresh, field):
    fixture = oauth_refresh
    with sqlite3.connect(fixture.database) as db:
        metadata = json.loads(db.execute('SELECT metadata_json FROM private_connections WHERE source_id=?', ('google_ads',)).fetchone()[0])
        metadata[field] = 'SYNTHETIC-CHANGED'
        db.execute('UPDATE private_connections SET metadata_json=? WHERE source_id=?', (json.dumps(metadata), 'google_ads'))
    with pytest.raises(s.StaticError):
        refresh_check(fixture)


def test_normal_google_refresh_cannot_hide_non_google_metadata_boolean_to_number_drift(oauth_refresh):
    fixture = oauth_refresh
    with sqlite3.connect(fixture.database) as db:
        original_cipher, raw = db.execute(
            'SELECT encrypted_credentials,metadata_json FROM private_connections WHERE source_id=?',
            ('stripe',)).fetchone()
        metadata = json.loads(raw)
        assert metadata['read_only_adapter'] is True
        metadata['read_only_adapter'] = 1
        db.execute('UPDATE private_connections SET metadata_json=? WHERE source_id=?',
                   (json.dumps(metadata), 'stripe'))
        assert db.execute('SELECT encrypted_credentials FROM private_connections WHERE source_id=?',
                          ('stripe',)).fetchone()[0] == original_cipher
    with pytest.raises(s.StaticError, match='AUTHORIZATION_IDENTITY_SCOPE_OR_OAUTH_STATE_CHANGED'):
        refresh_check(fixture)


@pytest.mark.parametrize('case', ['backup_hash', 'missing_backup_hash', 'missing_connection', 'new_connection'])
def test_refresh_exception_requires_the_exact_backup_and_both_historical_maps(oauth_refresh, case):
    fixture = oauth_refresh
    runtime = fixture.runtime
    if case == 'backup_hash':
        runtime.receipt['backup_sha256'] = 'f'*64
    elif case == 'missing_backup_hash':
        del runtime.receipt['backup_sha256']
    elif case == 'missing_connection':
        with sqlite3.connect(fixture.database) as db:
            db.execute("DELETE FROM private_connections WHERE source_id='gmail'")
    else:
        with sqlite3.connect(fixture.database) as db:
            db.execute("INSERT INTO private_connections SELECT id||'-new',owner_id,source_id,status,generation,encrypted_credentials,metadata_json,oauth_state_hash,oauth_expires_at,oauth_used_at,created_at,updated_at FROM private_connections WHERE source_id='gmail'")
    with pytest.raises(s.StaticError):
        refresh_check(fixture)


@pytest.mark.parametrize('source', ['stripe', 'bofa_bank'])
def test_refresh_exception_rejects_non_google_source_credential_changes(oauth_refresh, source):
    fixture = oauth_refresh
    fixture.write_credentials(source, {**fixture.credentials[source], 'access_token': 'SYNTHETIC-NEW-ACCESS', 'expires_at': 2000})
    with pytest.raises(s.StaticError):
        refresh_check(fixture)


def test_refresh_exception_rejects_backup_historical_full_map_mismatch(oauth_refresh):
    fixture = oauth_refresh
    historical = dict(fixture.historical)
    historical[next(iter(historical))] = 'f'*64
    runtime = fixture.runtime
    current = runtime.upgrade.stable_authorization(runtime.base)
    with pytest.raises(s.StaticError, match='ORIGINAL_BACKUP_AUTHORIZATION_HISTORY_DRIFT'):
        s.checked_refreshed_authorization(runtime.upgrade, runtime.base, runtime.receipt,
                                          runtime.roles, historical, current)


def test_publisher_requires_owner_and_currency_receipt_to_bind_the_same_full_history(frozen, monkeypatch):
    runtime = make_runtime(frozen, monkeypatch)
    runtime.currency.previous['stable_authorization'] = {'opaque': 'other-history'}
    with pytest.raises(s.StaticError, match='SAME_ACCEPTED_AUTHORIZATION_HISTORY_REQUIRED'):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    assert not (runtime.release / 'payload').exists()
    runtime.base.atomic_nginx.assert_not_called()
    assert runtime.commands == []


def test_refresh_between_capture_and_authorization_verification_is_rejected(oauth_refresh):
    fixture = oauth_refresh
    runtime = fixture.runtime
    captured = runtime.upgrade.stable_authorization(runtime.base)
    fixture.write_credentials('gmail', {**fixture.credentials['gmail'], 'access_token': 'SYNTHETIC-CONCURRENT-REFRESH', 'expires_at': 3000})
    with pytest.raises(s.StaticError, match='CAPTURED_AUTHORIZATION_DRIFT'):
        s.checked_refreshed_authorization(runtime.upgrade, runtime.base, runtime.receipt,
                                          runtime.roles, fixture.historical, captured)


def test_refresh_after_proof_during_publication_is_rejected_without_nginx_switch(oauth_refresh):
    fixture = oauth_refresh
    runtime = fixture.runtime
    def concurrent_refresh(payload):
        fixture.write_credentials('gmail', {**fixture.credentials['gmail'], 'access_token': 'SYNTHETIC-PUBLISH-REFRESH', 'expires_at': 3000})
        return {**runtime.currency.public, 'assets/new.js': 'b'*64}
    runtime.base.install_public.side_effect = concurrent_refresh
    with pytest.raises(s.StaticError, match='BACKEND_OR_CREDENTIAL_GENERATION_CHANGED'):
        s.apply(runtime.args, runtime.release, runtime.verifier)
    runtime.base.atomic_nginx.assert_not_called()
    assert runtime.current_nginx == [runtime.original] and runtime.commands == []
    state = json.loads((runtime.release / 'static-state.json').read_bytes())
    assert state['phase'] == 'PRIVATE_CLARITY_UI_STATIC_ROLLED_BACK'
    assert state['deployed'] is False


def test_legitimate_prepublication_refresh_can_publish_with_the_captured_full_map(oauth_refresh):
    fixture = oauth_refresh
    runtime = fixture.runtime
    expected = runtime.upgrade.stable_authorization(runtime.base)
    result = s.apply(runtime.args, runtime.release, runtime.verifier)
    assert result['deployed'] is True
    state = json.loads((runtime.release / 'static-state.json').read_bytes())
    assert state['stable_authorization'] == expected
    assert state['stable_authorization'] != fixture.historical
    assert state['oauth_refresh_proof']['changed_sources'] == ['gmail', 'google_ads']
    assert state['oauth_refresh_proof']['all_bound_identity_scope_generation_oauth_fields_unchanged'] is True


@pytest.mark.parametrize('case', ['add_access_field', 'add_expires_in', 'delete_refresh_token', 'delete_scope', 'delete_client_secret'])
def test_refresh_exception_requires_the_same_credential_keyset(oauth_refresh, case):
    fixture = oauth_refresh
    credentials = {**fixture.credentials['gmail'], 'access_token': 'SYNTHETIC-NEW-ACCESS', 'expires_at': 2000}
    if case == 'add_access_field':
        credentials['extra_access_token'] = 'SYNTHETIC-UNREVIEWED-ACCESS'
    elif case == 'add_expires_in':
        credentials['expires_in'] = 3600
    else:
        del credentials[case.removeprefix('delete_')]
    fixture.write_credentials('gmail', credentials)
    with pytest.raises(s.StaticError, match='ONLY_ACCESS_TOKEN_REFRESH_ALLOWED'):
        refresh_check(fixture)


def test_credential_probe_uses_stdin_only_and_rechecks_the_same_healthy_api(monkeypatch):
    identity, image = 'a'*64, 'sha256:'+'b'*64
    runtime = {'id': identity, 'image': image, 'started_at': 'accepted'}
    info = {'Id': identity, 'Name': '/t24-private-api', 'Image': image,
            'State': {'Running': True, 'Health': {'Status': 'healthy'}}}
    base = SimpleNamespace(inspect=Mock(return_value=info))
    receipt = {'candidate_image': image, 'roles': {'api': {'id': identity, 'image': image, 'runtime': runtime}}}
    pairs = [{'source_id': 'gmail', 'old_encrypted': 'SYNTHETIC-OLD-CIPHERTEXT',
              'current_encrypted': 'SYNTHETIC-CURRENT-CIPHERTEXT'}]
    proof = {'stage': 'OAUTH_REFRESH_CREDENTIAL_IDENTITY_VERIFIED', 'changed_sources': ['gmail'],
             'checked_connections': 1, 'changed_plaintext_fields': ['access_token', 'expires_at'],
             'writes': False, 'provider_requests': False}
    invoke = Mock(return_value=SimpleNamespace(returncode=0, stdout=encoded(proof), stderr=b''))
    monkeypatch.setattr(s.subprocess, 'run', invoke)
    actual = s.verify_refresh_credentials(base, receipt, {'api': runtime}, pairs)
    assert actual == proof
    command = invoke.call_args.args[0]
    assert command == ['docker', 'exec', '-i', '--workdir', '/app/backend', '--env',
                       'PYTHONDONTWRITEBYTECODE=1', identity, 'python', '-B', '-c', s.REFRESH_CREDENTIAL_PROBE]
    assert 'SYNTHETIC-' not in ' '.join(command)
    assert json.loads(invoke.call_args.kwargs['input']) == pairs
    assert 'env' not in invoke.call_args.kwargs
    assert invoke.call_args.kwargs['capture_output'] is True
    assert base.inspect.call_args_list == [((('t24-private-api',)), {}), ((('t24-private-api',)), {})]
