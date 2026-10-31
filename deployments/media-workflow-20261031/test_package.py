"""Exact source/freezes/summary package tests on synthetic local files."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('workflow_author_builder', HERE / 'build_payload.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


def summary(r):
    return {'stage': 'MEDIA_WORKFLOW_PREFLIGHT_CAPTURED', 'source_sha': r.BASE_SOURCE, 'frontend_version': r.BASE_FRONTEND, 'schema_revision': r.OLD_REVISION, 'table_count': 130, 'deployed_sha256': r.BASE_DEPLOYED_SHA, 'scheduler_enabled_receipt_sha256': r.BASE_ENABLED_SHA, 'scheduler_enabled': True, 'scheduler_activation_from': r.ACTIVATION_FROM, 'gbp_feature_enabled': True, 'callback_logging_protection_retained': True, 'image_delivery_prefix_absent': True, 'private_boundary_verified': True, 'host_docker_timestamp_parser_verified': True, 'credential_content_read': False, 'private_content_read': False, 'executed_business_writes': False, 'sha256': 'a' * 64, 'path': '/opt/t24-crm/releases/media-workflow-preflight-' + 'a' * 12 + '.json'}


MAIN_BEFORE = b'''synthetic start
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            request.url.path,
synthetic end
'''
MAIN_AFTER = b'''synthetic start
    image_delivery = request.url.path.startswith("/api/v1/media-publication-images/delivery/")
    response.headers["Referrer-Policy"] = "no-referrer" if image_delivery else "strict-origin-when-cross-origin"
            "/api/v1/media-publication-images/delivery/[image].png" if image_delivery else request.url.path,
synthetic end
'''


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); monkeypatch.setattr(b.r, 'SOURCE_SHA', 'e' * 40); monkeypatch.setattr(b.r, 'FRONTEND', 'f' * 12)
    after = {}; before = {}
    for name in b.r.SOURCE_FILES | {'app/backend/preserved.py'}:
        path = Path(name); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(('SYNTHETIC ' + name).encode()); after[name] = b.H(path.read_bytes())
        if name not in b.r.TEST_FILES and (not name.startswith('app/backend/') or name[12:] in b.r.EXISTING_BACKEND_FILES): before[name] = b.H(('OLD ' + name).encode())
    before['app/backend/preserved.py'] = after['app/backend/preserved.py']
    Path('app/backend/main.py').write_bytes(MAIN_AFTER);after['app/backend/main.py']=b.H(MAIN_AFTER);before['app/backend/main.py']=b.H(MAIN_BEFORE)
    monkeypatch.setattr(b,'git',lambda *args:MAIN_BEFORE if args[1].startswith(b.r.BASE_SOURCE+':') else MAIN_AFTER)
    monkeypatch.setattr(b, 'inventory', lambda ref: dict(before if ref == b.r.BASE_SOURCE else after)); monkeypatch.setattr(b, 'frontend_version', lambda: b.r.FRONTEND)
    dist = Path('app/frontend/dist'); dist.mkdir(parents=True); (dist / 'index.html').write_text('<html>synthetic</html>'); (dist / 'app-version.json').write_text(json.dumps({'version': b.r.FRONTEND})); (dist / 'assets').mkdir(); (dist / 'assets/test.js').write_text('synthetic')
    freezes = Path('outputs/media-workflow-20261031'); freezes.mkdir(parents=True)
    value = {'source_sha': b.r.SOURCE_SHA, 'frontend_version': b.r.FRONTEND, 'baseline_source_sha': b.r.BASE_SOURCE,
        'files': {name:after[name] for name in b.r.SOURCE_FILES}, 'old_schema_revision': b.r.OLD_REVISION,
        'schema_revision': b.r.NEW_REVISION, 'additive_tables':sorted(b.r.NEW_TABLES), 'production_seed_rows':False,
        'image_delivery_policy_enabled':False}
    (freezes / 'application-freeze.json').write_text(json.dumps(value))
    monkeypatch.setattr(b.r, 'APPLICATION_FREEZE_SHA', b.H((freezes / 'application-freeze.json').read_bytes()))
    value = summary(b.r); value['backend_changed_before'] = {name: before.get('app/backend/' + name) for name in b.r.BACKEND_FILES}
    return value, before, after


def test_package_exact_five_runtime_plus_static_and_no_test_or_secret_payload(package):
    blob, manifest = b.build(package[0])
    assert manifest['database_migration'] is True and manifest['production_seed_rows'] is False
    assert manifest['additive_tables'] == sorted(b.r.NEW_TABLES) and set(manifest['changed_source_files']) == b.r.SOURCE_FILES
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        names = {item.name for item in archive}; assert {name[8:] for name in names if name.startswith('backend/')} == b.r.BACKEND_FILES
        assert all(not name.startswith('app/') and '.env' not in name and 'test_' not in name and 'secret' not in name for name in names)


@pytest.mark.parametrize('mutation', ['extra_app', 'missing_change', 'local_source', 'untracked_frontend', 'freeze', 'backend_baseline', 'wrong_dist', 'dist_secret', 'dist_symlink', 'dist_root_symlink', 'version_symlink'])
def test_package_rejects_unreviewed_or_secret_content(package, mutation):
    value, before, after = package
    if mutation == 'extra_app': after['app/backend/unapproved.py'] = '0' * 64
    if mutation == 'missing_change': after['app/backend/services/media_operations.py'] = before['app/backend/services/media_operations.py']
    if mutation == 'local_source': Path('app/backend/services/media_operations.py').write_text('unreviewed')
    if mutation == 'untracked_frontend': Path('app/frontend/src/untracked.ts').write_text('unreviewed')
    if mutation == 'freeze': Path('outputs/media-workflow-20261031/application-freeze.json').write_text('{}')
    if mutation == 'backend_baseline': value['backend_changed_before']['services/google_business.py'] = '0' * 64
    if mutation == 'wrong_dist': Path('app/frontend/dist/app-version.json').write_text('{"version":"wrong"}')
    if mutation == 'dist_secret': Path('app/frontend/dist/runtime.env').write_text('SYNTHETIC_SECRET')
    if mutation == 'dist_symlink': Path('app/frontend/dist/assets/link.js').symlink_to(Path('app/frontend/dist/assets/test.js').resolve())
    if mutation == 'dist_root_symlink':
        Path('app/frontend/dist').rename('app/frontend/other-dist'); Path('app/frontend/dist').symlink_to('other-dist', target_is_directory=True)
    if mutation == 'version_symlink':
        path = Path('app/frontend/dist/app-version.json'); path.rename('app/frontend/version.json'); path.symlink_to('../version.json')
    with pytest.raises(RuntimeError): b.build(value)


@pytest.mark.parametrize('field,value', [('scheduler_enabled', False), ('scheduler_activation_from', 'wrong'), ('schema_revision', b.r.NEW_REVISION), ('table_count', 131), ('deployed_sha256', '0' * 64), ('scheduler_enabled_receipt_sha256', '0' * 64), ('private_boundary_verified', False), ('host_docker_timestamp_parser_verified', False), ('executed_business_writes', True), ('path', '/tmp/proof.json')])
def test_summary_is_exact_on_baseline_only(package, field, value):
    package[0][field] = value
    with pytest.raises(RuntimeError): b.build(package[0])


def test_zero_pins_refuse_before_git_or_source_access(monkeypatch):
    monkeypatch.setattr(b.r, 'SOURCE_SHA', '0' * 40); monkeypatch.setattr(b, 'inventory', lambda _: pytest.fail('git before actual pins'))
    with pytest.raises(RuntimeError, match='ACTUAL_REVIEWED_SOURCE_FRONTEND_AND_FREEZE_REQUIRED'): b.build({})


def test_main_guard_allows_only_exact_image_referrer_and_performance_privacy_change():
    b.main_only_image_delivery(MAIN_BEFORE,MAIN_AFTER)
    with pytest.raises(RuntimeError):b.main_only_image_delivery(MAIN_BEFORE,MAIN_AFTER+b'\napp logic change')
    with pytest.raises(RuntimeError):b.main_only_image_delivery(MAIN_BEFORE,MAIN_AFTER.replace(b'/delivery/',b'/'))
