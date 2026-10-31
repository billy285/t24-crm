"""Independent publisher attacks: temporary SQLite/files and fake Docker only."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('workflow_author_fixture_for_independent', HERE / 'test_release.py')
author = importlib.util.module_from_spec(spec); sys.modules[spec.name] = author; spec.loader.exec_module(author)
r = author.r
publisher = author.publisher
sentinel = author.sentinel


def test_actual_retained_four_value_dependency_chain_without_server(monkeypatch):
    def load_module(name, path):
        spec = importlib.util.spec_from_file_location(name, path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
    current = load_module('independent_actual_new_preflight', HERE / 'preflight.py')
    previous = load_module('independent_actual_phase_one_preflight', HERE.parent / 'media-publication-20261031/preflight.py')
    sentinel = tuple(SimpleNamespace(name=name) for name in ('legacy', 'base', 'safe'))
    oldest = SimpleNamespace(dependencies=lambda: sentinel)
    calls = []
    def previous_load(path, sha, name):
        assert path == previous.OLD / 'preflight.py' and sha == previous.OLD_PREFLIGHT_SHA
        calls.append('oldest'); return oldest
    def current_load(path, sha, name):
        assert path == current.OLD / 'preflight.py' and sha == current.OLD_PREFLIGHT_SHA
        assert current.OLD_PREFLIGHT_SHA == current.H((HERE.parent / 'media-publication-20261031/preflight.py').read_bytes())
        calls.append('phase1'); return previous
    monkeypatch.setattr(previous, 'load', previous_load); monkeypatch.setattr(current, 'load', current_load)
    assert current.dependencies() == (oldest, *sentinel)
    assert calls == ['phase1', 'oldest']


def test_original_stop_failure_cannot_start_candidate_or_new_worker_before_migration(publisher):
    w = publisher
    def fail(argv, code):
        if argv[:2] == ['docker', 'stop']: raise RuntimeError('SYNTHETIC_STOP_FAILED')
    w.m.fault = fail
    with pytest.raises(RuntimeError, match='SYNTHETIC_STOP_FAILED'): w.activate()
    assert w.m.head == r.OLD_REVISION and w.m.inspect('t24-crm')['Id'] == author.OLD
    assert w.m.inspect(author.OLD)['State']['Running'] is True and w.m.inspect(author.NEW)['State']['Running'] is False
    assert not any(argv[:2] == ['docker', 'start'] for argv in w.m.calls)


@pytest.mark.parametrize('field', ['unknown_primary', 'unknown_reserved', 'candidate_image', 'candidate_id', 'original_source'])
def test_recovery_never_guesses_other_container_identity_or_source(publisher, field):
    w = publisher; w.activate(); w.m.calls.clear()
    if field == 'unknown_primary':
        w.m.items[author.NEW]['Name'] = '/' + w.candidate_name
        intruder = copy.deepcopy(author.original()); intruder.update(Id='9' * 64, Name='/t24-crm'); w.m.items[intruder['Id']] = intruder
    elif field == 'unknown_reserved':
        w.m.items[author.OLD]['Name'] = '/t24-unknown-previous'
        intruder = copy.deepcopy(author.original()); intruder.update(Id='9' * 64, Name='/' + w.old_name); w.m.items[intruder['Id']] = intruder
    elif field == 'candidate_image': w.m.items[author.NEW]['Image'] = 'sha256:' + '9' * 64
    elif field == 'candidate_id':
        path = w.args.release / 'candidate-created.json'; value = json.loads(path.read_bytes()); value['candidate_id'] = '9' * 64; path.write_bytes(r.encoded(value))
    else: w.m.sources[author.OLD] = 'unreviewed-overlay'
    with pytest.raises(RuntimeError): w.recover_internal(w.receipt, author.original(), w.before, w.expected)
    assert not any(argv[:3] == ['docker', 'start', author.OLD] for argv in w.m.calls)
    assert not any('9' * 64 in argv and argv[:2] in (['docker', 'stop'], ['docker', 'start'], ['docker', 'rename']) for argv in w.m.calls)
    assert not any(argv[:2] in (['docker', 'rm'], ['docker', 'create']) for argv in w.m.calls)


@pytest.mark.parametrize('stage', ['source_before_stop', 'fresh_after_start'])
def test_source_drift_is_detected_and_never_resumes_old_code_after_new_schema(publisher, stage):
    w = publisher
    if stage == 'source_before_stop':
        create = w.m.docker_request
        def changed(*args):
            result = create(*args); w.m.sources[author.NEW] = 'unreviewed-overlay'; return result
        w.m.docker_request = changed
    else:
        def changed(argv, code):
            if argv[:3] == ['docker', 'start', author.NEW]: w.m.sources[author.NEW] = 'unreviewed-overlay'
        w.m.fault = changed
    with pytest.raises(RuntimeError, match='SYNTHETIC_SOURCE_DRIFT'): w.activate()
    if stage == 'source_before_stop':
        assert w.m.head == r.OLD_REVISION and w.m.inspect(author.OLD)['State']['Running'] is True
    else:
        assert w.m.head == r.NEW_REVISION and w.m.inspect(author.OLD)['State']['Running'] is False
        assert w.m.inspect(author.NEW)['State']['Running'] is False


@pytest.mark.parametrize('malformed', [{'counter': -1}, {'counter': True}, {'counter': 1.0}, {'counter': '1'}])
def test_sequence_map_exact_integer_types_and_no_regression(malformed):
    def metadata(values):
        return {'pragma_sha256': 'a' * 64, 'sequence_exists': True, 'sequence_values': values, 'sequence_sha256': r.digest(sorted(values.items()))}
    baseline = metadata({'counter': 4})
    with pytest.raises(RuntimeError): r.sequence_boundary(baseline, metadata(malformed), forward=True)
    with pytest.raises(RuntimeError): r.sequence_boundary(baseline, metadata({'counter': 3}), forward=True)
    with pytest.raises(RuntimeError): r.sequence_boundary(baseline, metadata({'counter': 5, 'unapproved': 1}), forward=True)
    r.sequence_boundary(baseline, metadata({'counter': 6}), forward=True)


@pytest.mark.parametrize('change', ['sequence', 'user_version', 'application_id'])
def test_real_two_migration_transaction_rolls_back_metadata_drift(tmp_path, change):
    database = tmp_path / 'metadata.db'; author.create_db(database, True)
    before = author.sql_snapshot(database); before_objects = r.objects(database)
    with sqlite3.connect(database) as db:
        before_meta = (db.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall(), db.execute('PRAGMA user_version').fetchall(), db.execute('PRAGMA application_id').fetchall())
    mutation = {'sequence': "c.exec_driver_sql(\"UPDATE sqlite_sequence SET seq=999 WHERE name='finance_canary'\")", 'user_version': "c.exec_driver_sql('PRAGMA user_version=18')", 'application_id': "c.exec_driver_sql('PRAGMA application_id=43')"}[change]
    code = author.migration(database).replace('  head=revision', '  ' + mutation + '\n  head=revision')
    with pytest.raises(AssertionError): exec(compile(code, '<synthetic-metadata-drift>', 'exec'), {})
    assert author.sql_snapshot(database) == before and r.objects(database) == before_objects
    with sqlite3.connect(database) as db:
        assert (db.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall(), db.execute('PRAGMA user_version').fetchall(), db.execute('PRAGMA application_id').fetchall()) == before_meta


@pytest.mark.parametrize('changed', [b'proxy_pass http://127.0.0.1:8000/;', b'proxy_pass http://localhost:8000;', b'proxy_pass http://127.0.0.1:8000$uri;'])
def test_nginx_never_copies_path_rewriting_variable_or_nonliteral_upstream(changed):
    original = author.NGINX.replace(b'proxy_pass http://127.0.0.1:8000;', changed)
    with pytest.raises(RuntimeError): r.image_delivery_nginx(original)


def test_nginx_added_prefix_is_one_exact_subtree_and_original_bytes_survive():
    original = author.NGINX.replace(b'# Existing callback must remain byte-identical.', b'# literal comment with braces { } and quoted fake location')
    modified, added = r.image_delivery_nginx(original)
    assert modified.replace(added, b'', 1) == original
    _, blocks = r.nginx_blocks(modified)
    delivery = [item for item in blocks if item['header'] == ['location', '^~', r.DELIVERY_PREFIX]]
    assert len(delivery) == 1
    assert ['access_log', 'off'] in delivery[0]['directives'] and ['error_log', '/dev/null', 'crit'] in delivery[0]['directives']
    assert not any(item[0] in {'root', 'alias', 'try_files', 'rewrite'} for item in delivery[0]['directives'])


def test_local_input_symlink_and_hardlink_rejected_before_read(tmp_path):
    secret = tmp_path / 'secret'; secret.write_bytes(b'PRIVATE-CANARY-MUST-NOT-OPEN')
    linked = tmp_path / 'linked'; linked.symlink_to(secret)
    with pytest.raises(RuntimeError, match='REGULAR_CANONICAL_LOCAL_INPUT_REQUIRED'): r.local_bytes(linked)
    linked.unlink(); linked.hardlink_to(secret)
    with pytest.raises(RuntimeError, match='REGULAR_CANONICAL_LOCAL_INPUT_REQUIRED'): r.local_bytes(linked)


@pytest.mark.parametrize('fail_directory', [False, True])
def test_real_retained_migration_identity_directory_is_durable_before_start(publisher, tmp_path, monkeypatch, fail_directory):
    w = publisher
    path = HERE.parent / 'media-ops-management-20261031/release.py'
    spec = importlib.util.spec_from_file_location('workflow_independent_real_migration', path)
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    base.OLD_REVISION, base.NEW_REVISION, base.MIGRATION = r.OLD_REVISION, r.NEW_REVISION, r.MIGRATION
    base.migration_script = r.migration_script; w.base = base; w.source = 'f' * 40
    data = tmp_path / 'production-data'; data.mkdir(); (data / 'crm_prod.db').write_bytes(b'SYNTHETIC-INODE-ONLY')
    w.m.BUSINESS = data / 'crm_prod.db'; w.migration_identity = lambda data: base.Release.migration_identity(w, data)
    w.settle_migration = lambda data, required=False: base.Release.settle_migration(w, data, required=required)
    events = []; real_fsync = os.fsync
    def fsync(fd):
        directory = stat.S_ISDIR(os.fstat(fd).st_mode); events.append('directory-fsync' if directory else 'file-fsync')
        if directory and fail_directory: raise OSError('SYNTHETIC_DIRECTORY_FSYNC_FAILED')
        return real_fsync(fd)
    monkeypatch.setattr(r.os, 'fsync', fsync)
    def write(path, value):
        body = value if isinstance(value, bytes) else r.encoded(value)
        with path.open('xb') as stream: stream.write(body); stream.flush(); os.fsync(stream.fileno())
        return r.H(body)
    w.m.write = write; initial_write = w.m.write; identity = '6' * 64
    def run(argv, code, *timeout):
        if argv[:2] == ['docker', 'create']:
            events.append('create')
            assert '--rm' not in argv and '--network=none' in argv and '--read-only' in argv
            env = [argv[i + 1] for i, value in enumerate(argv) if value == '-e']
            assert 'T24_GBP_SCHEDULER_ENABLED=false' in env and 'T24_GBP_SCHEDULER_ACTIVATION_FROM=' in env
            name = argv[argv.index('--name') + 1]
            w.m.items[identity] = {'Id': identity, 'Image': author.IMAGE, 'Name': '/' + name,
                'Config': {'Env': env, 'Cmd': ['python', '-B', '-c', r.migration_script()]},
                'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True},
                'Mounts': [{'Type': 'bind', 'Source': str(data), 'Destination': '/app/backend/data', 'RW': True},
                    {'Type': 'bind', 'Source': str(w.args.release / 'probe-logs'), 'Destination': '/app/backend/logs', 'RW': True},
                    {'Type': 'tmpfs', 'Destination': '/tmp'}],
                'State': {'Running': False, 'Status': 'created', 'ExitCode': 0}}
            return identity.encode()
        if argv[:3] == ['docker', 'start', identity]:
            events.append('start'); w.m.items[identity]['State'].update(Running=True, Status='running'); return b''
        if argv[:3] == ['docker', 'wait', identity]:
            events.append('wait'); w.m.items[identity]['State'].update(Running=False, Status='exited'); return b'0'
        pytest.fail('Unexpected migration command: ' + repr(argv[:2]))
    w.m.run = run
    if fail_directory:
        with pytest.raises(OSError, match='SYNTHETIC_DIRECTORY_FSYNC_FAILED'): r.Release.run_migration(w, data, author.IMAGE)
        assert 'directory-fsync' in events and 'start' not in events and not w.m.items[identity]['State']['Running']
    else:
        r.Release.run_migration(w, data, author.IMAGE)
        assert events.index('create') < events.index('file-fsync') < events.index('directory-fsync') < events.index('start') < events.index('wait')
    assert w.m.write is initial_write


def test_forward_recovery_fresh_boundary_after_public_sentinel_catches_late_metadata_change(publisher):
    w = publisher; w.activate()
    def late_change(candidate_id):
        assert candidate_id == author.NEW
        w.metadata = 'changed-during-public-probe'
        return {'delivery_prefix_logging_protected': True}
    w.public_check = late_change
    with pytest.raises(RuntimeError, match='SYNTHETIC_METADATA_DRIFT'):
        w.recover_internal(w.receipt, author.original(), w.before, w.expected)
    assert w.m.inspect(author.NEW)['State']['Running'] is False
    assert w.m.inspect(author.OLD)['State']['Running'] is False


@pytest.mark.parametrize('directive', [b'not-no-store', b'no-store-false', b'private, x-no-store=1'])
def test_sentinel_requires_exact_cache_control_no_store_token(directive):
    with pytest.raises(RuntimeError): r.sentinel_headers(author.SENTINEL_HEADERS.replace(b'private, no-store', directive))


@pytest.mark.parametrize('destination', ['/var/log/nginx/access.log', '/var/log/nginx/error.log', '/var/log/nginx/t24-private-error.log'])
def test_each_effective_nginx_log_is_scanned_for_new_marker_without_export(sentinel, destination):
    s = sentinel; original = s.w.m.run
    marker = b't24_noncapability_probe_' + b'e' * 32
    def leaking(argv, *args):
        if argv[0] == 'curl':
            with s.mapping[destination].open('ab') as stream: stream.write(b'UNRELATED-PRIVATE-RECORD ' + marker)
        return original(argv, *args)
    s.w.m.run = leaking
    with pytest.raises(RuntimeError, match='SENTINEL_PATH_PRESENT_IN_NGINX_LOG') as caught: s.w.delivery_sentinel(author.NEW)
    assert 'PRIVATE-RECORD' not in str(caught.value) and marker.decode() not in str(caught.value)


def test_log_append_scan_rejects_more_than_bound_instead_of_silently_sampling(sentinel):
    s = sentinel; original = s.w.m.run; written = [False]
    def overflowing(argv, *args):
        if argv[0] == 'curl' and not written[0]:
            written[0] = True
            with next(iter(s.mapping.values())).open('ab') as stream: stream.write(b'X' * (4 * 1024**2 + 1))
        return original(argv, *args)
    s.w.m.run = overflowing
    with pytest.raises(RuntimeError, match='SENTINEL_PATH_PRESENT_IN_NGINX_LOG'): s.w.delivery_sentinel(author.NEW)


def test_log_metadata_drift_during_canary_rejects(sentinel):
    s = sentinel; original = s.w.m.run; changed = [False]
    def chmod(argv, *args):
        if argv[0] == 'curl' and not changed[0]:
            changed[0] = True; path = next(iter(s.mapping.values())); path.chmod(0o444)
        return original(argv, *args)
    s.w.m.run = chmod
    with pytest.raises(RuntimeError, match='SENTINEL_LOG_ROTATION_OR_METADATA_DRIFT'): s.w.delivery_sentinel(author.NEW)


@pytest.mark.parametrize('directive', [b'access_log /tmp/unreviewed.log;', b'error_log syslog:server=127.0.0.1:514;', b'error_log /var/log/nginx/error.log debug;', b'debug_connection 127.0.0.1;'])
def test_extra_destination_and_debug_logging_fail_before_sending_marker(directive):
    active = b'access_log /var/log/nginx/access.log;\nerror_log /var/log/nginx/error.log;\nerror_log /var/log/nginx/t24-private-error.log;\n' + r.image_delivery_nginx(author.NGINX)[0]
    with pytest.raises(RuntimeError): r.delivery_log_paths(active + b'\n' + directive)


def test_actual_container_stderr_is_in_the_same_bounded_log_capture():
    marker = 'SYNTHETIC_STDERR_CANARY'
    output = r.bounded_output([sys.executable, '-c', 'import sys;sys.stderr.write(' + repr(marker) + ')'], maximum=128)
    assert output == marker.encode()


def test_actual_log_command_timeout_kills_only_its_child():
    with pytest.raises(RuntimeError, match='BOUNDED_LOG_COMMAND_TIMEOUT'):
        r.bounded_output([sys.executable, '-c', 'import time;time.sleep(3)'], timeout=.05, maximum=128)
