"""Immutable carrier tests use fresh temporary Git repositories; no remote phase."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('meta_author_commands', HERE / 'make_commands.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def summary(r):
    return {'stage': 'META_BUSINESS_PREFLIGHT_CAPTURED', 'source_sha': r.BASE_SOURCE, 'backend_source_sha': r.BACKEND_SOURCE, 'frontend_version': r.BASE_FRONTEND, 'schema_revision': r.OLD_REVISION, 'schema_sha256': '9'*64, 'table_count': 136, 'deployed_sha256': r.BASE_DEPLOYED_SHA, 'scheduler_enabled': True, 'scheduler_activation_from': r.ACTIVATION_FROM, 'gbp_feature_enabled': True, 'callback_logging_protection_retained': True, 'image_delivery_logging_protection_retained': True, 'existing_image_policies_and_data_preserved': True, 'private_boundary_verified': True, 'host_docker_timestamp_parser_verified': True, 'credential_content_read': False, 'private_content_read': False, 'executed_business_writes': False, 'meta_environment_keys_absent': True, 'meta_callback_location_absent': True, 'meta_feature_enabled': False, 'meta_credentials_present': False, 'sha256': 'a' * 64, 'path': '/opt/t24-crm/releases/meta-business-preflight-' + 'a' * 12 + '.json'}


@pytest.fixture
def carrier(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'; repo.mkdir(); (repo / 'app').mkdir(); (repo / 'app/source').write_text('synthetic')
    def git(*args): return subprocess.check_output(['git', *args], cwd=repo, stderr=subprocess.PIPE)
    git('init', '-q'); git('config', 'user.name', 'Synthetic'); git('config', 'user.email', 'synthetic@example.invalid'); git('add', 'app'); git('commit', '-qm', 'source'); source = git('rev-parse', 'HEAD').decode().strip()
    directory = repo / m.DIRECTORY; (directory / 'artifacts').mkdir(parents=True)
    for name in ('release.py', 'preflight.py'): (directory / name).write_bytes((HERE / name).read_bytes())
    payload = b'SYNTHETIC_PAYLOAD'; (directory / 'artifacts/payload.tar.gz').write_bytes(payload)
    manifest = {'source_sha': source, 'frontend_version': 'f' * 12, 'schema_revision': m.r.NEW_REVISION, 'old_schema_revision': m.r.OLD_REVISION, 'additive_tables': sorted(m.r.NEW_TABLES), 'preflight_sha256': 'a' * 64, 'database_migration': True, 'meta_feature_enabled': False, 'meta_credentials_present': False, 'meta_environment_keys_absent': True, 'production_seed_rows': False, 'existing_image_policies_and_data_preserved': True, 'runtime_environment_changed': False, 'payload_sha256': m.H(payload), 'application_freeze_sha256': 'd' * 64}
    (directory / 'artifacts/manifest.json').write_bytes(m.r.encoded(manifest)); git('add', '.'); git('commit', '-qm', 'tool'); commit = git('rev-parse', 'HEAD').decode().strip()
    monkeypatch.setattr(m, 'HERE', directory); monkeypatch.setattr(m.r, 'SOURCE_SHA', source); monkeypatch.setattr(m.r, 'FRONTEND', 'f' * 12); monkeypatch.setattr(m.r,'APPLICATION_FREEZE_SHA','d'*64); monkeypatch.chdir(repo)
    return commit, summary(m.r), directory, git


def prepared(carrier):
    commit, value, directory, git = carrier
    result = {'stage': 'META_BUSINESS_PREPARED_OFFLINE_VERIFIED', 'source_sha': m.r.SOURCE_SHA, 'frontend_version': m.r.FRONTEND, 'schema_revision': m.r.NEW_REVISION, 'old_schema_revision': m.r.OLD_REVISION, 'schema_after_sha256': '9'*64, 'manifest_sha256': m.H((directory / 'artifacts/manifest.json').read_bytes()), 'payload_sha256': m.H((directory / 'artifacts/payload.tar.gz').read_bytes()), 'preflight_sha256': value['sha256'], '_canonical_sha256': 'b' * 64}
    result.update(original_table_count=136,new_table_count=141,additive_tables=sorted(m.r.NEW_TABLES))
    for name in ('offline_additive_only', 'offline_original_rows_unchanged', 'offline_new_table_empty', 'offline_own_metadata_exact', 'actual_python310_verified', 'exact_meta_media_google_routes', 'offline_network_none', 'offline_credentials_absent', 'offline_workers_off', 'scheduler_on_and_cutoff_preserved', 'host_docker_timestamp_parser_verified', 'meta_environment_keys_absent', 'meta_disabled_unconfigured', 'meta_callback_logging_protection_prepared', 'existing_image_policies_and_data_preserved'):result[name]=True
    for name in ('provider_requests','production_database_migrated','sequence_written_by_tool'):result[name]=False
    return result


def test_prepare_only_until_exact_prepared_review_then_both_switch_phases(carrier):
    commands, pins = m.generate(carrier[0], carrier[1]); assert set(commands) == {'prepare-command.sh'} and pins['prepared_sha256'] is None
    commands, pins = m.generate(carrier[0], carrier[1], prepared(carrier)); assert set(commands) == {'prepare-command.sh', 'activate-command.sh', 'recover-command.sh'}
    assert pins['prepared_sha256'] == 'b' * 64 and pins['executed'] is False
    for name, command in commands.items():
        assert len(command.encode()) < 11000 and "sudo python3 -I -S -B - <<'WORKFLOW'" in command
        code = command.split("<<'WORKFLOW'\n", 1)[1].rsplit('WORKFLOW\n', 1)[0]; ast.parse(code)
        if name == 'prepare-command.sh':
            assert command.index('os.geteuid()==0') < command.index('opener.open') and 'ProxyHandler({})' in command and 'redirect_request' in command
            assert 'carrier=' + repr(carrier[0]) in command and 'O_EXCL|os.O_NOFOLLOW,0o600' in command
        else:
            constants = {node.value for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            assert {'--review-sha256', 'b' * 64, name.split('-')[0]} <= constants and 'EXACT_RELEASE_HELPER_REQUIRED' in command


@pytest.mark.parametrize('name', ['release.py', 'preflight.py', 'artifacts/manifest.json', 'artifacts/payload.tar.gz'])
def test_committed_member_tampering_refused(carrier, name):
    path = carrier[2] / name; path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(RuntimeError, match='EXACT_COMMITTED_MEMBER_REQUIRED'): m.generate(carrier[0], carrier[1])


@pytest.mark.parametrize('field,value', [('stage', 'PREPARED'), ('schema_revision', 'wrong'), ('offline_original_rows_unchanged', False), ('offline_workers_off', False), ('scheduler_on_and_cutoff_preserved', False), ('provider_requests', True), ('production_database_migrated', True), ('_canonical_sha256', None)])
def test_incomplete_prepared_review_never_generates_switch(carrier, field, value):
    result = prepared(carrier); result[field] = value
    with pytest.raises(RuntimeError): m.generate(carrier[0], carrier[1], result)


def test_other_app_tree_carrier_rejected(carrier):
    repo = carrier[2].parents[1]; (repo / 'app/source').write_text('unreviewed'); carrier[3]('add', 'app'); carrier[3]('commit', '-qm', 'other app')
    with pytest.raises(RuntimeError, match='CARRIER_APPLICATION_TREE_DRIFT'): m.generate(carrier[3]('rev-parse', 'HEAD').decode().strip(), carrier[1])


def test_draft_zero_pins_refuse_before_git_or_file_read(monkeypatch):
    monkeypatch.setattr(m.r, 'SOURCE_SHA', '0' * 40)
    with pytest.raises(RuntimeError, match='ACTUAL_REVIEWED_SOURCE_FRONTEND_AND_FREEZE_REQUIRED'): m.generate('a' * 40, {})
