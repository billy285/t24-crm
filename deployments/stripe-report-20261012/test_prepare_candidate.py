"""Synthetic preparation tests. No Docker, live config or production DB access."""
import copy
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

import pytest

SPEC = importlib.util.spec_from_file_location('stripe_report_candidate', Path(__file__).with_name('prepare_candidate.py'))
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def source():
    files = {name.removeprefix('app/'): (REPO / name).read_bytes() for name in candidate.BACKEND_CHANGES | candidate.PRIVATE_TESTS}
    files['frontend/dist/index.html'] = b'<html>Synthetic reviewed frontend</html>'
    files['frontend/dist/app-version.json'] = b'{"version":"c1ae19b38fec"}'
    hashes = {'app/' + name: candidate.sha(data) for name, data in files.items() if name.startswith('backend/')}
    frozen = {'format_version': 1, 'stage': 'FROZEN_STRIPE_REPORT_SOURCE', 'source_sha': candidate.SOURCE_SHA,
              'baseline_private_source_sha': candidate.BASE_SOURCE, 'base_private_image': candidate.BASE_IMAGE,
              'backend_delta_sha256': {name: hashes[name] for name in candidate.BACKEND_CHANGES},
              'frontend_dist_sha256': {name.removeprefix('frontend/dist/'): candidate.sha(data) for name, data in files.items() if name.startswith('frontend/')},
              'dependency_file_sha256': {'app/backend/requirements.txt': '9' * 64}, 'backend_regression_tests_minimum': 1173}
    manifest = {'format_version': 1, 'stage': 'STRIPE_REPORT_BACKEND_PAYLOAD_PREPARED', 'source_sha': candidate.SOURCE_SHA,
                'baseline_private_source_sha': candidate.BASE_SOURCE, 'base_private_image': candidate.BASE_IMAGE,
                'payload_sha256': '1' * 64, 'payload_files': {name: candidate.sha(data) for name, data in files.items()},
                'source_file_sha256': hashes, 'backend_changes': sorted(candidate.BACKEND_CHANGES),
                'private_tests': sorted(candidate.PRIVATE_TESTS), 'runtime_dependency_file_sha256': frozen['dependency_file_sha256'],
                'backend_regression_tests_expected_minimum': 1173, 'runtime_dependency_changes': False,
                'credentials_included': False, 'production_access': False, 'deployed': False}
    return files, manifest, frozen


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as tar:
        for name, data, kind in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(data) if kind == tarfile.REGTYPE else 0
            if kind == tarfile.SYMTYPE: entry.linkname = '/etc/passwd'
            tar.addfile(entry, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return output.getvalue()


def test_complete_frozen_payload_and_all_private_tests(source):
    files, manifest, frozen = source
    assert candidate.checked_payload(manifest, frozen, '1' * 64) is manifest
    assert len(manifest['private_tests']) == 21
    assert manifest['payload_files'] == {name: candidate.sha(data) for name, data in files.items()}


@pytest.mark.parametrize('field,value', [
    ('source_sha', '0' * 40), ('baseline_private_source_sha', '0' * 40), ('base_private_image', 'sha256:' + '0' * 64),
    ('runtime_dependency_changes', True), ('credentials_included', True), ('production_access', True), ('deployed', True),
    ('backend_regression_tests_expected_minimum', 1), ('private_tests', []), ('backend_changes', []),
    ('runtime_dependency_file_sha256', {}), ('payload_sha256', '2' * 64),
])
def test_payload_rejects_identity_scope_and_coverage_drift(source, field, value):
    _, manifest, frozen = source
    manifest[field] = value
    with pytest.raises(candidate.PrepareError): candidate.checked_payload(manifest, frozen, '1' * 64)


def test_payload_rejects_omitted_static_file_and_added_backend_file(source):
    _, manifest, frozen = source
    missing = copy.deepcopy(manifest); del missing['payload_files']['frontend/dist/index.html']
    with pytest.raises(candidate.PrepareError, match='COMPLETE_FROZEN_PAYLOAD_DRIFT'): candidate.checked_payload(missing, frozen, '1' * 64)
    extra = copy.deepcopy(manifest); extra['payload_files']['backend/main.py'] = '4' * 64
    with pytest.raises(candidate.PrepareError, match='COMPLETE_FROZEN_PAYLOAD_DRIFT'): candidate.checked_payload(extra, frozen, '1' * 64)


def test_payload_rejects_source_hash_drift_and_lowered_test_minimum(source):
    _, manifest, frozen = source
    name = 'app/backend/services/private_stripe_report_provider.py'
    manifest['source_file_sha256'][name] = '4' * 64
    with pytest.raises(candidate.PrepareError, match='FROZEN_DELTA_HASH_DRIFT'): candidate.checked_payload(manifest, frozen, '1' * 64)
    frozen['backend_regression_tests_minimum'] = 1
    with pytest.raises(candidate.PrepareError): candidate.checked_payload(manifest, frozen, '1' * 64)


def test_extract_complete_archive_and_protected_files(tmp_path, source):
    files, manifest, _ = source
    payload = archive([('payload/' + name, data, tarfile.REGTYPE) for name, data in files.items()])
    destination = tmp_path / 'new'
    candidate.extract(payload, manifest, destination)
    assert {p.relative_to(destination).as_posix(): candidate.sha(p.read_bytes()) for p in destination.rglob('*') if p.is_file()} == manifest['payload_files']
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in destination.rglob('*') if p.is_file())


@pytest.mark.parametrize('name,kind', [
    ('payload/../escape', tarfile.REGTYPE), ('payload/backend/../../escape', tarfile.REGTYPE),
    ('payload//backend/a.py', tarfile.REGTYPE), ('payload/backend/.env', tarfile.REGTYPE),
    ('/payload/backend/a.py', tarfile.REGTYPE), ('payload/backend/a.py', tarfile.SYMTYPE),
])
def test_extract_rejects_traversal_hidden_files_symlinks_and_absolute_paths(tmp_path, name, kind):
    payload = archive([(name, b'fixture', kind)])
    with pytest.raises(candidate.PrepareError, match='REGULAR_ALLOWLISTED_ARCHIVE_ONLY'):
        candidate.extract(payload, {'payload_files': {'backend/a.py': candidate.sha(b'fixture')}}, tmp_path / 'new')
    assert not (tmp_path / 'escape').exists()


def test_extract_rejects_missing_duplicate_and_wrong_hash(tmp_path):
    manifest = {'payload_files': {'backend/a.py': candidate.sha(b'a'), 'frontend/dist/index.html': candidate.sha(b'html')}}
    with pytest.raises(candidate.PrepareError, match='PAYLOAD_INCOMPLETE'):
        candidate.extract(archive([('payload/backend/a.py', b'a', tarfile.REGTYPE)]), manifest, tmp_path / 'missing')
    with pytest.raises(candidate.PrepareError, match='REGULAR_ALLOWLISTED_ARCHIVE_ONLY'):
        candidate.extract(archive([('payload/backend/a.py', b'a', tarfile.REGTYPE)] * 2), manifest, tmp_path / 'duplicate')
    with pytest.raises(candidate.PrepareError, match='PAYLOAD_MEMBER_HASH_DRIFT'):
        candidate.extract(archive([('payload/backend/a.py', b'wrong', tarfile.REGTYPE)]), manifest, tmp_path / 'wrong')


def test_recipes_copy_frozen_private_delta_only_and_rollback_model_only(source):
    _, manifest, _ = source
    tag = 't24-private-stripe-report-base:' + candidate.SOURCE_SHA[:12] + '-123456abcdef'
    normal = candidate.recipe(manifest, tag).decode(); rollback = candidate.recipe(manifest, tag, rollback=True).decode()
    assert normal.startswith('FROM ' + tag + '\n') and 'frontend/' not in normal
    assert 'RUN ' not in normal and 'pip' not in normal
    assert rollback.count('COPY ') == 1 and 'COPY backend/models/private_workspace.py /app/backend/models/private_workspace.py' in rollback
    assert 't24.private.source.sha' not in rollback
    with pytest.raises(candidate.PrepareError): candidate.recipe(manifest, 'python:3.10')


def test_full_backend_byte_map_keeps_unrelated_files_and_original_rollback(source):
    _, manifest, _ = source
    base = {'main.py': 'a' * 64, 'services/private_workspace.py': 'b' * 64, 'models/private_workspace.py': candidate.BASE_MODEL_SHA}
    normal = candidate.expected_backend(base, manifest); rollback = candidate.expected_backend(base, manifest, rollback=True)
    assert normal['main.py'] == base['main.py'] and normal['services/private_workspace.py'] == base['services/private_workspace.py']
    assert rollback == {**base, 'models/private_workspace.py': candidate.MODEL_SHA}
    assert normal['services/private_stripe_report_provider.py'] == manifest['payload_files']['backend/services/private_stripe_report_provider.py']


@pytest.mark.parametrize('layers', [[], ['foreign'], ['base1'], ['base1', 'foreign', 'delta']])
def test_rejects_image_without_exact_retained_layers(layers):
    with pytest.raises(candidate.PrepareError): candidate.verify_candidate_base({'RootFS': {'Layers': ['base1', 'base2']}}, {'RootFS': {'Layers': layers}})


def test_accepts_only_actual_retained_runtime_and_test_tool_versions():
    runtime = {'python': '3.10.22', 'packages': {**candidate.BASE_PACKAGE_VERSIONS, **{name: None for name in candidate.WHEEL_VERSIONS}}}
    candidate.checked_base_runtime(runtime)
    for change in ({'python': '3.11.0'}, {'packages': {}}):
        with pytest.raises(candidate.PrepareError): candidate.checked_base_runtime({**runtime, **change})


def junit(count=3, *, failure=False, skipped=False):
    cases = ''.join('<testcase name="case' + str(i) + '">' + ('<failure/>' if failure and i == 0 else '<skipped/>' if skipped and i == 0 else '') + '</testcase>' for i in range(count))
    return ('<testsuites><testsuite tests="' + str(count) + '" failures="' + str(int(failure)) + '" errors="0" skipped="' + str(int(skipped)) + '">' + cases + '</testsuite></testsuites>').encode()


@pytest.mark.parametrize('xml,minimum', [(junit(2), 3), (junit(failure=True), 3), (junit(skipped=True), 3), (b'<testsuites/>', 1), (junit().replace(b'tests="3"', b'tests="4"'), 3)])
def test_junit_requires_all_private_tests_pass_without_skips(xml, minimum):
    with pytest.raises(candidate.PrepareError): candidate.test_report(xml, minimum)


def test_junit_counts_verified_cases(): assert candidate.test_report(junit(), 3) == 3


def new_database(path, tables, *, private=True, populated=True):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True); path.parent.chmod(0o700)
    with sqlite3.connect(path) as db:
        for name in sorted(tables):
            db.execute('CREATE TABLE "' + name + '" (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, encrypted_value TEXT, amount INTEGER)')
            db.execute('CREATE INDEX "ix_' + name + '_owner" ON "' + name + '" (owner_id)')
            if populated: db.execute('INSERT INTO "' + name + '" VALUES (?,?,?,?)', ('fixture', '4', 'SYNTHETIC_ENCRYPTED_VALUE_NEVER_LIVE', 70000))
    path.chmod(0o600)
    return path


@pytest.fixture
def databases(tmp_path):
    private = new_database(tmp_path / 'private/original.db', candidate.BASE_TABLES)
    business = new_database(tmp_path / 'business/crm.db', {'finance_sentinel'}, private=False)
    clone = tmp_path / 'private/clone.db'
    with sqlite3.connect(private) as old, sqlite3.connect(clone) as new: old.backup(new)
    clone.chmod(0o600)
    with sqlite3.connect(clone) as db:
        db.execute('CREATE TABLE private_stripe_reports (cache_key TEXT PRIMARY KEY, owner_id TEXT NOT NULL, encrypted_report TEXT)')
        db.execute('CREATE INDEX ix_private_stripe_reports_owner_id ON private_stripe_reports(owner_id)')
    return private, business, clone


def test_readonly_snapshot_hides_record_values_and_verifies_additive_clone(databases):
    private, business, clone = databases
    before = candidate.release_snapshot(private, business); after = candidate.release_snapshot(clone, business)
    proof = candidate.compare_schema_snapshots(before, after, after['private']['schema_objects'])
    assert proof['original_rows_columns_indexes_preserved'] and proof['business_unchanged'] and proof['new_cache_empty']
    encoded = json.dumps(before)
    assert 'SYNTHETIC_ENCRYPTED_VALUE_NEVER_LIVE' not in encoded and 'CREATE TABLE' not in encoded and str(private) not in encoded
    assert before == candidate.release_snapshot(private, business)


@pytest.mark.parametrize('change,code', [
    ('old_row', 'ORIGINAL_PRIVATE_ROWS_OR_COLUMNS_CHANGED'), ('old_index', 'ORIGINAL_PRIVATE_DDL_OR_INDEX_CHANGED'),
    ('new_cache', 'NEW_REPORT_CACHE_MUST_START_EMPTY'), ('business', 'BUSINESS_DATABASE_CHANGED'),
    ('extra_private', 'EXACT_TEN_TO_ELEVEN_PRIVATE_TABLES_REQUIRED'), ('target', 'INDEPENDENT_TARGET_DDL_REQUIRED'),
    ('identity', 'CLONE_MUST_HAVE_DISTINCT_IDENTITY'),
])
def test_schema_compare_rejects_existing_data_ddl_scope_business_and_identity_changes(databases, change, code):
    private, business, clone = databases
    before = candidate.release_snapshot(private, business)
    if change in {'old_row', 'old_index', 'new_cache', 'extra_private'}:
        with sqlite3.connect(clone) as db:
            if change == 'old_row': db.execute("UPDATE private_connections SET encrypted_value='mutated'")
            elif change == 'old_index': db.execute('DROP INDEX ix_private_connections_owner')
            elif change == 'new_cache': db.execute("INSERT INTO private_stripe_reports VALUES ('cache','4','synthetic')")
            else: db.execute('CREATE TABLE private_extra(owner_id TEXT)')
    if change == 'business':
        with sqlite3.connect(business) as db: db.execute('UPDATE finance_sentinel SET amount=0')
    after = candidate.release_snapshot(clone, business); target = copy.deepcopy(after['private']['schema_objects'])
    if change == 'target': target['private_stripe_reports']['sql_sha256'] = '0' * 64
    if change == 'identity': after['private']['identity'] = before['private']['identity']
    with pytest.raises(candidate.PrepareError, match=code): candidate.compare_schema_snapshots(before, after, target)


def test_in_place_compare_requires_same_database_file(databases):
    private, business, clone = databases
    before = candidate.release_snapshot(private, business); after = candidate.release_snapshot(clone, business)
    with pytest.raises(candidate.PrepareError, match='PRIVATE_DATABASE_FILE_REPLACED'):
        candidate.compare_schema_snapshots(before, after, after['private']['schema_objects'], mode='in_place')
    after['private']['identity'] = before['private']['identity']
    assert candidate.compare_schema_snapshots(before, after, after['private']['schema_objects'], mode='in_place')['mode'] == 'in_place'


@pytest.mark.parametrize('kind', ['owner', 'crm_table', 'trigger', 'view'])
def test_snapshot_rejects_foreign_owner_and_schema_boundary(databases, kind):
    private, _, _ = databases
    with sqlite3.connect(private) as db:
        if kind == 'owner': db.execute("UPDATE private_connections SET owner_id='5'")
        elif kind == 'crm_table': db.execute('CREATE TABLE finance_table(owner_id TEXT)')
        elif kind == 'trigger': db.execute('CREATE TRIGGER fixture_trigger AFTER UPDATE ON private_connections BEGIN SELECT 1; END')
        else: db.execute('CREATE VIEW fixture_view AS SELECT 1')
    with pytest.raises(candidate.PrepareError): candidate.database_snapshot(private, private=True)


def test_protected_files_reject_symlink_hardlink_and_shared_permissions(tmp_path):
    tmp_path.chmod(0o700); file = tmp_path / 'fixture'; candidate.write_new(file, b'synthetic')
    candidate.protected(file)
    linked = tmp_path / 'linked'; linked.symlink_to(file)
    with pytest.raises(candidate.PrepareError): candidate.protected(linked)
    linked.unlink(); os.link(file, linked)
    with pytest.raises(candidate.PrepareError): candidate.protected(file)
    linked.unlink(); file.chmod(0o644)
    with pytest.raises(candidate.PrepareError): candidate.protected(file)


def test_frozen_file_requires_pinned_content(tmp_path):
    tmp_path.chmod(0o700); file = tmp_path / 'frozen.json'; candidate.write_new(file, b'{"synthetic":true}')
    assert candidate.frozen_file(file, candidate.sha(file.read_bytes())) == file.read_bytes()
    with pytest.raises(candidate.PrepareError): candidate.frozen_file(file, '0' * 64)


def test_runner_uses_offline_readonly_containers_and_rejects_external_mount(tmp_path, monkeypatch):
    tmp_path.chmod(0o700); fixture = tmp_path / 'synthetic'; fixture.mkdir(mode=0o700)
    commands = []
    monkeypatch.setattr(candidate.subprocess, 'run', lambda command, **kwargs: SimpleNamespace(returncode=1, stdout=b'', stderr=b''))
    runner = candidate.Runner(tmp_path)
    monkeypatch.setattr(runner, 'run', lambda stage, command, **kwargs: commands.append(command) or b'{"synthetic":true}')
    runner.isolated('fixture', candidate.BASE_IMAGE, 'print("synthetic")', mounts=[(fixture, '/synthetic/business', True)])
    command = commands[0]
    assert command[command.index('--network') + 1] == 'none' and '--read-only' in command and '--no-healthcheck' in command
    assert command[command.index('--cap-drop') + 1] == 'ALL' and 'no-new-privileges' in command
    assert not any(value in command for value in ['-p', '--publish', '--env-file', '/var/run/docker.sock'])
    assert 'type=bind,src=' + str(fixture) + ',dst=/synthetic/business,readonly' in command
    assert all('production' not in value.lower() or 'never_production' in value.lower() for value in command)
    external = tmp_path.parent / (tmp_path.name + '-external'); external.mkdir(mode=0o700)
    try:
        with pytest.raises(candidate.PrepareError, match='ONLY_SYNTHETIC_AND_TEST_MOUNTS_ALLOWED'):
            runner.isolated('external', candidate.BASE_IMAGE, '', mounts=[(external, '/synthetic/private', False)])
    finally: external.rmdir()


def test_regression_install_is_pinned_offline_and_runs_full_test_inventory(source):
    _, manifest, _ = source
    code = candidate.regression_code(['pytest==8.4.2'], manifest['private_tests'])
    assert "'--no-index'" in code and "'--no-deps'" in code and "'/tmp/test-deps'" in code
    assert all('/app/' + name.removeprefix('app/') in code for name in candidate.PRIVATE_TESTS if not name.endswith('conftest.py'))
    assert '/app/backend/tests/conftest.py' not in code and "'--junitxml=/test-results/regressions.xml'" in code


def test_actual_synthetic_initializer_and_model_only_old_api_read(tmp_path, source):
    """Execute the reviewed fixture, migration and rollback API in local copies.

    This catches invalid ORM fixtures/auth/startup code before the mandatory
    separate Docker Python 3.10 rehearsal. Only synthetic files are used.
    """
    tmp_path.chmod(0o700)
    roots = {}
    for role, source_sha in [('base', candidate.BASE_SOURCE), ('candidate', candidate.SOURCE_SHA), ('rollback', candidate.BASE_SOURCE)]:
        root = tmp_path / role; root.mkdir(mode=0o700)
        output = subprocess.run(['git', 'archive', source_sha, 'app/backend'], cwd=REPO, capture_output=True, check=True, timeout=30).stdout
        with tarfile.open(fileobj=io.BytesIO(output)) as tar:
            for member in tar:
                if member.isdir(): continue
                assert member.isfile() and member.name.startswith('app/backend/') and '..' not in Path(member.name).parts
                relative = member.name.removeprefix('app/backend/')
                assert Path(relative).name != '.env'
                path = root / relative; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.write_bytes(tar.extractfile(member).read())
        roots[role] = root
    (roots['rollback'] / 'models/private_workspace.py').write_bytes((roots['candidate'] / 'models/private_workspace.py').read_bytes())
    release = tmp_path / 'prepared'; release.mkdir(mode=0o700)
    image = 'sha256:' + 'a' * 64; rollback = 'sha256:' + 'b' * 64

    class LocalSyntheticRunner:
        def __init__(self): self.release = release
        def isolated(self, stage, selected_image, code, *, mounts=(), timeout=180):
            source_root = roots['base' if selected_image == candidate.BASE_IMAGE else 'candidate' if selected_image == image else 'rollback']
            # Each process gets only the declared fictional environment.
            environment = dict(candidate.SYNTHETIC_ENV)
            environment.update({'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(source_root), 'HOME': str(tmp_path)})
            replacements = {'/synthetic/private': release / 'synthetic/private', '/synthetic/business': release / 'synthetic/business'}
            for remote, local in replacements.items():
                code = code.replace(remote, str(local))
                environment = {key: value.replace(remote, str(local)) for key, value in environment.items()}
            block_network = "import socket\ndef no_network(*a,**kw):raise RuntimeError('SYNTHETIC_NETWORK_FORBIDDEN')\nsocket.socket.connect=no_network\n"
            result = subprocess.run([sys.executable, '-c', block_network + code], cwd=source_root, env=environment,
                                    capture_output=True, timeout=timeout)
            assert result.returncode == 0, stage + ': ' + result.stderr.decode(errors='replace')
            assert result.stdout.strip().startswith(b'{')
            return result.stdout

    _, manifest, _ = source
    proof = candidate.schema_rehearsal(LocalSyntheticRunner(), image, rollback, manifest)
    assert proof['compatible_old_api_started_and_owner_read'] and proof['populated_encrypted_report_cache_preserved']
    assert proof['business_unchanged'] and proof['production_database_access'] is False
    assert set(proof['tables']) == candidate.TARGET_TABLES
