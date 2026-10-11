"""Synthetic SQLite migration and private-container failure recovery only."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import prepare_candidate as preparation
import upgrade as u


CACHE_DDL = '''CREATE TABLE private_stripe_reports (
 cache_key VARCHAR(64) NOT NULL PRIMARY KEY, owner_id VARCHAR(64) NOT NULL,
 connection_id VARCHAR(36) NOT NULL, generation INTEGER NOT NULL,
 encrypted_report TEXT NOT NULL, expires_at DATETIME NOT NULL, created_at DATETIME NOT NULL)'''


def create_cache(path):
    with sqlite3.connect(path) as db:
        db.execute(CACHE_DDL)
        db.execute('CREATE INDEX ix_private_stripe_reports_owner_id ON private_stripe_reports (owner_id)')


def file_map(root):
    return {path.relative_to(root).as_posix(): u.sha(path.read_bytes()) for path in root.rglob('*') if path.is_file()}


def write_new(path, data):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)


class SyntheticRuntime:
    def __init__(self, tmp_path, monkeypatch):
        self.release = tmp_path / 'release'
        self.release.mkdir(mode=0o700)
        self.CONFIG = tmp_path / 'config'
        self.CONFIG.mkdir(mode=0o700)
        self.ENV = self.CONFIG / 'runtime.env'
        write_new(self.ENV, b'SYNTHETIC_ENVIRONMENT=only\n')
        private = tmp_path / 'private'
        private.mkdir(mode=0o700)
        self.PRIVATE_DB = private / 'workspace.db'
        business = tmp_path / 'business'
        business.mkdir(mode=0o700)
        self.BUSINESS = business / 'crm.db'
        with sqlite3.connect(self.BUSINESS) as db:
            for number in range(83):
                db.execute(f'CREATE TABLE customer_{number}(id INTEGER, value TEXT)')
                db.execute(f'INSERT INTO customer_{number} VALUES(1,?)', ('synthetic-customer',))
        with sqlite3.connect(self.PRIVATE_DB) as db:
            for name in u.TEN_TABLES - {'private_connections'}:
                db.execute(f'CREATE TABLE {name} ( owner_id TEXT NOT NULL, id TEXT PRIMARY KEY, value TEXT )')
                if name in {'private_items', 'private_preferences', 'private_sync_runs'}:
                    db.execute(f'INSERT INTO {name} VALUES(?,?,?)', ('4', name, 'synthetic-private-state'))
            db.execute('''CREATE TABLE private_connections (owner_id TEXT NOT NULL, id TEXT PRIMARY KEY,
                source_id TEXT, status TEXT, generation INTEGER, encrypted_credentials TEXT, metadata_json TEXT,
                created_at TEXT, updated_at TEXT, oauth_state_hash TEXT, oauth_expires_at TEXT, oauth_used_at TEXT)''')
            db.execute('INSERT INTO private_connections VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('4', 'synthetic-stripe', 'stripe', 'connected', 7, 'synthetic-encrypted-credential',
                        json.dumps({'stripe_account_id': 'acct_synthetic', 'mode': 'live', 'read_only_adapter': True}),
                        'synthetic-created', 'synthetic-updated', None, None, None))
        self.PRIVATE_DB.chmod(0o600)
        independent = private / 'independent.db'
        with sqlite3.connect(self.PRIVATE_DB) as old, sqlite3.connect(independent) as new:
            old.backup(new)
        independent.chmod(0o600)
        create_cache(independent)
        schema = preparation.database_snapshot(independent, private=True)['schema_objects']
        # Simulate differently formatted historical ALTER SQL. Only the three
        # new objects may come from independent fresh metadata in the live path.
        for name, row in schema.items():
            if row['table'] != 'private_stripe_reports':
                row['sql_sha256'] = 'e' * 64
        self.payload = self.release / 'prepared-backend/payload'
        dist = self.payload / 'frontend/dist'
        (dist / 'assets').mkdir(parents=True, mode=0o700)
        write_new(dist / 'app-version.json', b'{"version":"123456789abc"}')
        write_new(dist / 'index.html', b'<script src="/assets/frozen.js"></script>')
        write_new(dist / 'assets/frozen.js', b'console.log("synthetic report")')
        self.manifest = {'frontend_version': '123456789abc', 'private_tests': ['synthetic_private_test.py'],
                         'payload_files': file_map(self.payload)}
        self.candidate = {
            'format_version': 1, 'stage': 'STRIPE_REPORT_BACKEND_CANDIDATE_VERIFIED', 'source_sha': u.SOURCE,
            'baseline_private_source_sha': u.BASE_SOURCE, 'base_image_id': u.BASE_IMAGE,
            'image_id': 'sha256:' + '1' * 64, 'rollback_image_id': 'sha256:' + '2' * 64,
            'frozen_source_sha256': '3' * 64, 'payload_manifest_sha256': '4' * 64, 'payload_sha256': '5' * 64,
            **{key: True for key in ('rollback_model_only', 'base_layers_verified', 'base_pin_verified_before_and_after_build',
               'all_other_backend_bytes_identical', 'all_runtime_package_bytes_identical', 'bundled_static_bytes_unchanged')},
            **{key: False for key in ('production_environment_loaded', 'production_database_access', 'production_services_modified',
                'public_assets_published', 'deployed')},
            'regressions': {'tests': 1173, 'minimum': 1173, 'python': '3.10.22', 'network': 'none',
                            'all_private_tests': self.manifest['private_tests'], 'xml_sha256': '6' * 64},
            'synthetic_schema': {'stage': 'STRIPE_REPORT_SYNTHETIC_SCHEMA_AND_ROLLBACK_VERIFIED',
                'tables': sorted(u.TEN_TABLES | {'private_stripe_reports'}), 'schema_objects': schema,
                'base_image_id': u.BASE_IMAGE, 'candidate_image_id': 'sha256:' + '1' * 64,
                'rollback_image_id': 'sha256:' + '2' * 64, 'production_database_access': False,
                **{key: True for key in ('original_rows_columns_indexes_preserved', 'new_cache_initially_empty',
                   'compatible_old_api_started_and_owner_read', 'encrypted_existing_credentials_decrypted',
                   'populated_encrypted_report_cache_preserved', 'business_physically_readonly_for_init_and_read', 'business_unchanged')}}}
        self.previous_public = tmp_path / 'previous-public'
        (self.previous_public / 'assets').mkdir(parents=True)
        write_new(self.previous_public / 'app-version.json', json.dumps({'version': u.OLD_VERSION}).encode())
        write_new(self.previous_public / 'index.html', b'<script src="/assets/previous.js"></script>')
        write_new(self.previous_public / 'assets/previous.js', b'console.log("synthetic previous")')
        self.nginx = tmp_path / 'nginx.conf'
        self.nginx.write_bytes(b'server {root ' + str(self.previous_public).encode() + b';}')
        monkeypatch.setattr(u, 'OLD_PUBLIC', self.previous_public)
        monkeypatch.setattr(u, 'OLD_NGINX', u.sha(self.nginx.read_bytes()))
        monkeypatch.setattr(u, 'ENV_HASH', u.sha(self.ENV.read_bytes()))
        monkeypatch.setattr(u, 'protected', lambda path, directory=False: Path(path).lstat())
        monkeypatch.setattr(u, 'report_auth_check', lambda public=False: self.events.append(('auth', public)))
        self.events = []
        self.CRM_ID = 'c' * 64
        self.counter = 10
        self.fail_public = False
        self.fail_api = False
        self.fail_initializer = False
        self.missing_rollback_image = False
        self.seed_cache_before_failure = False
        self.concurrent_nginx = False
        self.containers = {}
        self.crm = {'id': self.CRM_ID, 'image': 'synthetic-crm', 'started_at': 'unchanged', 'configuration_sha256': '0' * 64}
        self.prior_ids = {'api': 'a' * 64, 'worker': 'b' * 64}
        for role, identity in self.prior_ids.items():
            values = {'JWT_SECRET_KEY': 'synthetic-jwt-key-never-production',
                      'PRIVATE_WORKSPACE_ENCRYPTION_KEY': 'synthetic-private-key-never-production',
                      'PRIVATE_WORKSPACE_PROCESS_ROLE': role}
            self.containers[identity] = self.container(identity, 't24-private-' + role, role, u.BASE_IMAGE,
                                                        u.BASE_SOURCE, '7' * 32, values, running=True)
        self.containers[self.CRM_ID] = self.container(self.CRM_ID, 't24-crm', 'crm', 'synthetic-crm', '', '', {}, running=True)
        self.containers[self.CRM_ID]['Mounts'] = [{'Type': 'bind', 'Source': str(business), 'Destination': '/crm', 'RW': True}]
        self.baseline = {'crm': self.crm, 'private': {role: self.proof(identity) for role, identity in self.prior_ids.items()},
                         'private_database': {'identity': preparation.database_snapshot(self.PRIVATE_DB, private=True)['identity']}}
        self.nav = SimpleNamespace(accepted_receipts=lambda base: ({}, {'new_ids': self.prior_ids}, {}),
                                   runtime=self.runtime, disabled_live_features=lambda base: None)
        self.switch = SimpleNamespace(ROLE_LABEL='t24.private_finance.release.attempt',
            environment=lambda info: dict(row.split('=', 1) for row in info['Config']['Env']),
            profile_bytes=lambda values: ('\n'.join(key + '=' + value for key, value in sorted(values.items())) + '\n').encode(),
            staged_check=self.staged_check, docker=self.docker, create_command=self.create_command,
            wait_api=self.wait_api, stable_records=self.stable_records, preserved=self.preserved,
            initializer_command=lambda name, image, attempt: ['create', '--initializer', name, image, attempt],
            initializer_check=self.initializer_check)

    def container(self, identity, name, role, image, source, attempt, values, running=False):
        return {'Id': identity, 'Name': '/' + name, 'Image': image, 'RestartCount': 0,
                'State': {'Running': running, 'StartedAt': 'synthetic-start', 'ExitCode': 0},
                'Config': {'Env': [key + '=' + value for key, value in sorted(values.items())],
                    'Labels': {'t24.private.source.sha': source, 't24.private.role': role,
                               't24.private_finance.release.attempt': attempt}},
                'Mounts': [{'Type': 'bind', 'Source': str(self.PRIVATE_DB.parent), 'Destination': '/private-data', 'RW': True}]}

    def inspect(self, identity, optional=False):
        result = self.containers.get(identity) or next((info for info in self.containers.values() if info['Name'] == '/' + identity), None)
        if result is None and not optional:
            raise u.UpgradeError('SYNTHETIC_CONTAINER_MISSING')
        return copy.deepcopy(result)

    def config_hash(self, info):
        return u.digest({'Config': info['Config'], 'Mounts': info['Mounts']})

    def proof(self, identity):
        info = self.inspect(identity)
        return {'id': identity, 'image': info['Image'], 'configuration_sha256': self.config_hash(info),
                'started_at': info['State']['StartedAt'], 'restart_count': info['RestartCount']}

    def runtime(self, base, candidate, state, previous):
        for identity in self.prior_ids.values():
            u.need(self.inspect(identity)['State']['Running'], 'SYNTHETIC_BASELINE_NOT_RUNNING')
        return copy.deepcopy(self.baseline)

    def read_protected(self, path):
        return Path(path).read_bytes()

    def read_nginx(self):
        return self.nginx.read_bytes()

    def changed_nginx(self, original, expected):
        u.need(u.sha(original) == expected, 'NGINX_BASELINE_DRIFT')
        return original.replace(str(self.OLD_PUBLIC).encode(), str(self.PUBLIC).encode(), 1)

    def atomic_nginx(self, data, allowed_hashes):
        u.need(u.sha(self.read_nginx()) in allowed_hashes, 'NGINX_CONCURRENT_CHANGE')
        self.nginx.write_bytes(data)
        self.events.append(('nginx', data))

    def save(self, path, value, replace=False):
        data = (json.dumps(value, sort_keys=True) + '\n').encode()
        if replace:
            assert path.exists()
            path.write_bytes(data)
        else:
            write_new(path, data)

    write_new = staticmethod(write_new)
    file_map = staticmethod(file_map)

    def crm_check(self):
        return copy.deepcopy(self.crm)

    def run(self, command, code):
        self.events.append(('system', command))

    def public_check(self, manifest, version, root):
        self.events.append(('public', version))
        assert file_map(root) == manifest
        if root != self.previous_public and self.fail_public:
            self.fail_public = False
            if self.seed_cache_before_failure:
                with sqlite3.connect(self.PRIVATE_DB) as db:
                    db.execute('INSERT INTO private_stripe_reports VALUES(?,?,?,?,?,?,?)',
                        ('synthetic-cache', '4', 'synthetic-stripe', 7, 'synthetic-encrypted-report', 'later', 'now'))
            if self.concurrent_nginx:
                self.nginx.write_bytes(b'concurrent unrelated Nginx edit')
            raise u.UpgradeError('SYNTHETIC_PUBLIC_CHECK_FAILED')

    def install_public(self, source):
        shutil.copytree(source, self.PUBLIC)
        for path in (self.previous_public / 'assets').iterdir():
            destination = self.PUBLIC / 'assets' / path.name
            u.need(not destination.exists() or destination.read_bytes() == path.read_bytes(), 'HASHED_ASSET_COLLISION')
            if not destination.exists():
                shutil.copyfile(path, destination)
        return file_map(self.PUBLIC)

    def create_command(self, name, role, image, attempt, source, profile):
        return ['create', '--role', name, role, image, attempt, source, str(profile)]

    def docker(self, command, timeout=30):
        self.events.append(('docker', list(command)))
        action = command[0]
        if action == 'image':
            rows = []
            for identity in command[2:]:
                if identity == self.candidate['rollback_image_id'] and self.missing_rollback_image:
                    continue
                labels = {'t24.private.source.sha': u.SOURCE} if identity == self.candidate['image_id'] else {
                    't24.private.rollback.schema-compatible': 'ten-to-eleven-cache'}
                layers = ['synthetic-base-layer'] + ([] if identity == u.BASE_IMAGE else ['synthetic-new-layer'])
                rows.append({'Id': identity, 'Config': {'Labels': labels}, 'RootFS': {'Layers': layers}})
            return json.dumps(rows).encode()
        if action == 'ps':
            return ('\n'.join(identity for identity, info in self.containers.items() if info['State']['Running']) + '\n').encode()
        if action == 'create':
            self.counter += 1
            identity = f'{self.counter:064x}'
            if command[1] == '--initializer':
                if self.fail_initializer:
                    raise u.UpgradeError('SYNTHETIC_INITIALIZER_CREATE_FAILED')
                _, _, name, image, attempt = command
                info = self.container(identity, name, 'initializer', image, u.SOURCE, attempt, {})
            else:
                _, _, name, role, image, attempt, source, profile = command
                values = dict(line.split('=', 1) for line in Path(profile).read_text().splitlines())
                info = self.container(identity, name, role, image, source, attempt, values)
            self.containers[identity] = info
            return identity.encode()
        if action == 'rename':
            info = self.containers[command[1]]
            assert self.inspect(command[2], optional=True) is None
            info['Name'] = '/' + command[2]
            return b''
        identity = command[-1]
        info = self.containers[identity]
        assert identity != self.CRM_ID
        if action == 'stop':
            info['State']['Running'] = False
            return b''
        if action == 'rm':
            assert info['Config']['Labels']['t24.private.role'] == 'initializer' and not info['State']['Running']
            del self.containers[identity]
            return b''
        if action == 'start' and '--attach' in command:
            create_cache(self.PRIVATE_DB)
            return b'{"stage":"PRIVATE_INITIALIZER_EXITED"}'
        if action == 'start':
            info['State']['Running'] = True
            return b''
        raise AssertionError(command)

    def staged_check(self, identity, role, image, attempt, source, values, running=None, require_stable=True):
        info = self.inspect(identity)
        labels = info['Config']['Labels']
        assert info['Image'] == image and labels['t24.private.role'] == role
        assert labels['t24.private.source.sha'] == source and labels['t24.private_finance.release.attempt'] == attempt
        assert self.switch.environment(info) == values
        if running is not None:
            assert info['State']['Running'] is running
        if require_stable:
            u.need(info['RestartCount'] == 0, 'NEW_PRIVATE_UNSTABLE_RUNTIME')
        return self.proof(identity)

    def initializer_check(self, info, image, attempt):
        assert info['Image'] == image and info['Config']['Labels']['t24.private.role'] == 'initializer'
        return info

    def wait_api(self, identity):
        if self.fail_api and self.inspect(identity)['Image'] == self.candidate['image_id']:
            self.fail_api = False
            self.containers[identity]['RestartCount'] = 1
            raise u.UpgradeError('NEW_PRIVATE_API_NOT_READY')

    def stable_records(self, path):
        snapshot = preparation.database_snapshot(path, private=True)
        return {name: snapshot['tables'][name] for name in ('private_items', 'private_preferences')}

    def preserved(self, before, after):
        u.need(before == after, 'PRIVATE_NOTES_OR_ACTIONS_CHANGED')

    def apply(self):
        return u.apply(self.release, self.manifest, self.payload, self.candidate,
                       base=self, nav=self.nav, preparation=preparation, switch=self.switch)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    return SyntheticRuntime(tmp_path, monkeypatch)


def test_complete_apply_only_adds_cache_preserves_credentials_and_crm(runtime):
    before = preparation.release_snapshot(runtime.PRIVATE_DB, runtime.BUSINESS)
    authorization = u.stable_authorization(runtime)
    result = runtime.apply()
    after = preparation.release_snapshot(runtime.PRIVATE_DB, runtime.BUSINESS)
    assert result['phase'] == 'STRIPE_REPORT_PUBLIC_RELEASE_VERIFIED' and result['deployed']
    assert after['business'] == before['business']
    assert after['private']['identity'] == before['private']['identity']
    assert set(after['private']['tables']) == u.TEN_TABLES | {'private_stripe_reports'}
    assert all(after['private']['tables'][name] == before['private']['tables'][name] for name in u.TEN_TABLES)
    assert u.stable_authorization(runtime) == authorization
    assert after['private']['tables']['private_stripe_reports']['rows'] == 0
    assert runtime.inspect('t24-private-api')['Image'] == runtime.candidate['image_id']
    assert runtime.inspect('t24-private-worker')['Image'] == runtime.candidate['image_id']
    stopped = [event[1][-1] for event in runtime.events if event[0] == 'docker' and event[1][0] == 'stop']
    assert stopped == [runtime.prior_ids['worker'], runtime.prior_ids['api']]
    assert runtime.CRM_ID not in stopped
    old_assets = runtime.PUBLIC / 'assets/previous.js'
    assert old_assets.read_bytes() == (runtime.previous_public / 'assets/previous.js').read_bytes()
    new_public_at = runtime.events.index(('public', runtime.manifest['frontend_version']))
    worker_start_at = next(index for index, event in enumerate(runtime.events)
                          if event[0] == 'docker' and event[1] == ['start', result['roles']['worker']['id']])
    assert new_public_at < worker_start_at
    backup = preparation.database_snapshot(runtime.release / 'live-upgrade/original-private.db', private=True)
    assert backup['tables'] == before['private']['tables'] and backup['identity'] != before['private']['identity']
    receipt = (runtime.release / 'upgrade-state.json').read_text()
    assert 'synthetic-encrypted-credential' not in receipt and 'synthetic-jwt-key' not in receipt


def test_public_failure_rolls_back_compatible_images_and_retains_populated_cache(runtime):
    before = preparation.release_snapshot(runtime.PRIVATE_DB, runtime.BUSINESS)
    runtime.fail_public = runtime.seed_cache_before_failure = True
    with pytest.raises(u.UpgradeError, match='COMPATIBLE_ROLLBACK_VERIFIED'):
        runtime.apply()
    after = preparation.release_snapshot(runtime.PRIVATE_DB, runtime.BUSINESS)
    assert after['business'] == before['business']
    assert after['private']['identity'] == before['private']['identity']
    assert after['private']['tables']['private_stripe_reports']['rows'] == 1
    assert all(after['private']['tables'][name] == before['private']['tables'][name] for name in u.TEN_TABLES)
    assert runtime.inspect('t24-private-api')['Image'] == runtime.candidate['rollback_image_id']
    assert runtime.inspect('t24-private-worker')['Image'] == runtime.candidate['rollback_image_id']
    assert str(runtime.previous_public).encode() in runtime.nginx.read_bytes()
    state = json.loads((runtime.release / 'upgrade-state.json').read_text())
    assert state['phase'] == 'STRIPE_REPORT_COMPATIBLE_ROLLBACK_VERIFIED' and not state['deployed']
    assert state['databases_restored'] is False and state['cache_schema_retained'] is True
    assert all(event[1][-1] != runtime.CRM_ID for event in runtime.events if event[0] == 'docker' and event[1][0] == 'stop')


def test_unhealthy_restarting_owned_candidate_can_be_stopped_and_rolled_back(runtime):
    runtime.fail_api = True
    with pytest.raises(u.UpgradeError, match='COMPATIBLE_ROLLBACK_VERIFIED'):
        runtime.apply()
    assert runtime.inspect('t24-private-api')['Image'] == runtime.candidate['rollback_image_id']
    assert runtime.inspect('t24-private-worker')['Image'] == runtime.candidate['rollback_image_id']


def test_early_initializer_failure_recovers_retained_images_without_adding_cache(runtime):
    before = preparation.release_snapshot(runtime.PRIVATE_DB, runtime.BUSINESS)
    runtime.fail_initializer = True
    with pytest.raises(u.UpgradeError, match='COMPATIBLE_ROLLBACK_VERIFIED'):
        runtime.apply()
    assert preparation.release_snapshot(runtime.PRIVATE_DB, runtime.BUSINESS) == before
    assert runtime.inspect('t24-private-api')['Image'] == u.BASE_IMAGE
    assert runtime.inspect('t24-private-worker')['Image'] == u.BASE_IMAGE
    state = json.loads((runtime.release / 'upgrade-state.json').read_text())
    assert state['rollback_image_used'] == u.BASE_IMAGE and state['cache_schema_retained'] is False


def test_missing_rollback_image_rejected_before_stopping_either_private_role(runtime):
    runtime.missing_rollback_image = True
    with pytest.raises(u.UpgradeError, match='ROLLBACK_IMAGES_REQUIRED'):
        runtime.apply()
    assert not (runtime.release / 'upgrade-state.json').exists()
    assert all(runtime.inspect(identity)['State']['Running'] for identity in runtime.prior_ids.values())
    assert not any(event[0] == 'docker' and event[1][0] in {'stop', 'start', 'rename', 'create'} for event in runtime.events)


def test_concurrent_nginx_edit_is_never_overwritten(runtime):
    runtime.fail_public = runtime.concurrent_nginx = True
    with pytest.raises(u.UpgradeError, match='ROLLBACK_REQUIRES_REVIEW'):
        runtime.apply()
    assert runtime.nginx.read_bytes() == b'concurrent unrelated Nginx edit'
    assert json.loads((runtime.release / 'upgrade-state.json').read_text())['rollback_failure_code'] == 'ROLLBACK_NGINX_CONCURRENT_CHANGE'


@pytest.mark.parametrize('section,key,value', [
    ('', 'source_sha', 'f' * 40), ('', 'stage', 'UNVERIFIED'), ('', 'rollback_image_id', u.BASE_IMAGE),
    ('', 'production_database_access', True), ('', 'all_other_backend_bytes_identical', False),
    ('regressions', 'tests', 1172), ('regressions', 'minimum', 1), ('regressions', 'python', '3.11'),
    ('regressions', 'network', 'bridge'), ('synthetic_schema', 'populated_encrypted_report_cache_preserved', False),
    ('synthetic_schema', 'encrypted_existing_credentials_decrypted', False),
])
def test_unrehearsed_candidates_rejected_before_live_mutation(runtime, section, key, value):
    candidate = copy.deepcopy(runtime.candidate)
    target = candidate[section] if section else candidate
    target[key] = value
    with pytest.raises(u.UpgradeError):
        u.checked_candidate(candidate, runtime.manifest)
    assert runtime.events == []


def test_composite_target_preserves_legacy_ddl_and_only_uses_independent_cache_objects(runtime):
    before = preparation.database_snapshot(runtime.PRIVATE_DB, private=True)
    target = u.target_schema_objects(before, runtime.candidate)
    assert all(target[name] == row for name, row in before['schema_objects'].items())
    fresh = runtime.candidate['synthetic_schema']['schema_objects']
    assert target['private_items']['sql_sha256'] != fresh['private_items']['sql_sha256']
    assert {name for name, row in target.items() if row['table'] == 'private_stripe_reports'} == {
        'private_stripe_reports', 'ix_private_stripe_reports_owner_id', 'sqlite_autoindex_private_stripe_reports_1'}


@pytest.mark.parametrize('kind', ['missing_index', 'extra_index', 'collision'])
def test_unreviewed_additive_objects_rejected(runtime, kind):
    before = preparation.database_snapshot(runtime.PRIVATE_DB, private=True)
    candidate = copy.deepcopy(runtime.candidate)
    if kind == 'missing_index':
        candidate['synthetic_schema']['schema_objects'].pop('ix_private_stripe_reports_owner_id')
    elif kind == 'extra_index':
        candidate['synthetic_schema']['schema_objects']['extra'] = {
            'type': 'index', 'table': 'private_stripe_reports', 'sql_sha256': 'a' * 64}
    else:
        before['schema_objects']['ix_private_stripe_reports_owner_id'] = {
            'type': 'index', 'table': 'private_items', 'sql_sha256': 'a' * 64}
    with pytest.raises(u.UpgradeError, match='ONLY_INDEPENDENT'):
        u.target_schema_objects(before, candidate)


@pytest.mark.parametrize('kind', ['extra', 'changed', 'symlink'])
def test_payload_bytes_cannot_drift_after_candidate_preparation(runtime, kind):
    if kind == 'extra':
        write_new(runtime.payload / 'Dockerfile.candidate', b'unreviewed recipe')
    elif kind == 'changed':
        (runtime.payload / 'frontend/dist/assets/frozen.js').write_bytes(b'changed bytes')
    else:
        (runtime.payload / 'unexpected').symlink_to(runtime.BUSINESS)
    with pytest.raises(u.UpgradeError):
        runtime.apply()
    assert not (runtime.release / 'upgrade-state.json').exists()
    assert all(runtime.inspect(identity)['State']['Running'] for identity in runtime.prior_ids.values())


@pytest.mark.parametrize('mount_scope', ['exact', 'parent', 'child'])
def test_unexpected_private_writer_rejected_without_touching_any_container(runtime, mount_scope):
    for identity in runtime.prior_ids.values():
        runtime.containers[identity]['State']['Running'] = False
    identity = 'd' * 64
    root = runtime.PRIVATE_DB.parent
    source = root if mount_scope == 'exact' else root.parent if mount_scope == 'parent' else root / 'child'
    runtime.containers[identity] = runtime.container(identity, 'unrelated-writer', 'other', 'other', '', '', {}, True)
    runtime.containers[identity]['Mounts'][0]['Source'] = str(source)
    with pytest.raises(u.UpgradeError, match='UNEXPECTED_PRIVATE_DATABASE_WRITER'):
        u.no_writers(runtime, runtime.switch)
    assert runtime.inspect(identity)['State']['Running']
    assert not any(event[0] == 'docker' and event[1][0] in {'stop', 'start', 'rm'} for event in runtime.events)


def test_rollback_snapshot_checks_are_readonly_and_reject_replaced_database(runtime):
    runtime.apply()
    baseline = preparation.release_snapshot(runtime.PRIVATE_DB, runtime.BUSINESS)
    target = baseline['private']['schema_objects']
    old = runtime.PRIVATE_DB.with_name('retained-original.db')
    runtime.PRIVATE_DB.rename(old)
    shutil.copyfile(old, runtime.PRIVATE_DB)
    runtime.PRIVATE_DB.chmod(0o600)
    with pytest.raises(u.UpgradeError, match='PRIVATE_INODE'):
        u.assert_schema(runtime, preparation, target, baseline)
    assert preparation.database_snapshot(old, private=True)['tables'] == baseline['private']['tables']


def test_cli_rejects_wrong_host_before_any_helper_or_action(monkeypatch):
    monkeypatch.setattr(u.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(u.socket, 'gethostname', lambda: 'synthetic-host')
    loader = Mock()
    monkeypatch.setattr(u, 'retained_tools', loader)
    with pytest.raises(u.UpgradeError, match='AUTHENTICATED_RELEASE_HOST'):
        u.main(SimpleNamespace(execute=True, release=u.RELEASE))
    loader.assert_not_called()


def test_exception_output_never_contains_raw_secrets_or_provider_errors():
    assert u.safe_error(RuntimeError('synthetic-private-key account@example.test')) == 'STRIPE_REPORT_UPGRADE_FAILED'
    assert u.safe_error(u.UpgradeError('PRIVATE_SCHEMA_CHANGED')) == 'PRIVATE_SCHEMA_CHANGED'
    assert u.safe_error(u.UpgradeError('synthetic-private-key')) == 'STRIPE_REPORT_UPGRADE_FAILED'
