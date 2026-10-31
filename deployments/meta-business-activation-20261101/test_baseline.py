"""Read-only capture/recheck tests. Synthetic metadata only; never production."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


b = load('activation_baseline_under_test', HERE/'baseline.py')
r = load('activation_retained_metadata_guard', HERE.parent/'meta-business-20261031/release.py')


def sample():
    values = {'monthly_deduction_rates': 42, 'other': 7}
    return {'rows': {f'table_{n}': {'count': 1, 'rows_sha256': 'a'*64, 'shape_sha256': 'b'*64} for n in range(141)},
            'database_metadata': {'pragma_sha256': 'c'*64, 'sequence_exists': True, 'sequence_values': values, 'sequence_sha256': r.digest(sorted(values.items()))},
            'crm': {'id': 'd'*64}, 'other_boundary': 'fixed'}


@pytest.fixture
def fake(monkeypatch):
    saved = {}
    def need(ok, code):
        if not ok: raise RuntimeError(code)
    c = SimpleNamespace(server_guard=lambda: None, pins_ready=lambda: pytest.fail('Capture must not require an uncreated Meta config'),
        need=need, ROOT=Path('/synthetic-stage'), mkdir=lambda path: None, SOURCE_SHA='6'*40, FRONTEND='f'*12,
        SCHEMA_REVISION='bde8da01f247', ACTIVATION_FROM='2026-10-30T19:42:04Z',
        write=lambda path, value: saved.setdefault('proof', copy.deepcopy(value)) and 'e'*64)
    b.configure(c); monkeypatch.setattr(b, 'dependencies', lambda: SimpleNamespace(release=r))
    return saved


def test_capture_can_precede_secret_consent_and_exports_only_fingerprints(fake, monkeypatch):
    value = sample(); monkeypatch.setattr(b, 'collect', lambda: copy.deepcopy(value))
    result = b.capture()
    assert result['table_count'] == 141 and result['credential_content_read'] is False and result['runtime_changed'] is False
    assert fake['proof'] == value and 'rows' not in result and 'database_metadata' not in result


def test_capture_adopts_only_observed_independent_counter_not_other_boundary_changes(fake, monkeypatch):
    first = sample(); second = copy.deepcopy(first); second['database_metadata']['sequence_values']['monthly_deduction_rates'] = 43
    second['database_metadata']['sequence_sha256'] = r.digest(sorted(second['database_metadata']['sequence_values'].items()))
    values = iter([first, second]); monkeypatch.setattr(b, 'collect', lambda: next(values)); b.capture()
    assert fake['proof'] == second and first['database_metadata']['sequence_values']['monthly_deduction_rates'] == 42


@pytest.mark.parametrize('change', ['rows', 'other_boundary', 'other_counter'])
def test_capture_rejects_any_business_or_unreviewed_metadata_drift(fake, monkeypatch, change):
    first = sample(); second = copy.deepcopy(first)
    if change == 'rows': second['rows']['table_0']['count'] = 2
    elif change == 'other_boundary': second['other_boundary'] = 'changed'
    else:
        second['database_metadata']['sequence_values']['other'] += 1
        second['database_metadata']['sequence_sha256'] = r.digest(sorted(second['database_metadata']['sequence_values'].items()))
    values = iter([first, second]); monkeypatch.setattr(b, 'collect', lambda: next(values))
    with pytest.raises(RuntimeError): b.capture()
    assert not fake


def test_small_capture_wrapper_embeds_exact_sources_without_execution():
    commands = load('activation_capture_factory_under_test', HERE/'make_commands.py')
    command, pins = commands.capture_command()
    assert len(command.encode()) < 11000 and 'baseline.py' in command and 'capture()' in command
    assert set(pins) == {'core.py', 'baseline.py'}
    for name, pin in pins.items(): assert hashlib.sha256((HERE/name).read_bytes()).hexdigest() == pin['sha256']


@pytest.mark.parametrize('count', [0, 1])
def test_first_capture_rejects_existing_meta_rows_before_new_key_creation(fake, count):
    meta = r.NEW_TABLES
    rows = {**{f'table_{n}': {'count': 1} for n in range(136)}, **{name: {'count': 0} for name in meta}}
    rows[next(iter(meta))]['count'] = count
    def later_schema_check(*args): raise RuntimeError('AFTER_INITIAL_META_EMPTY_CHECK')
    ctx = SimpleNamespace(m=SimpleNamespace(BUSINESS=SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=1, st_ino=2)),
        sql_snapshot=lambda path: rows, schema_signature=later_schema_check), release=SimpleNamespace(evidence=lambda data: data, NEW_TABLES=meta), receipt={})
    with pytest.raises(RuntimeError, match='EXISTING_META_DATA_REQUIRES_KEY_REUSE_REVIEW' if count else 'AFTER_INITIAL_META_EMPTY_CHECK'):
        b.protected_sample(ctx, require_meta_empty=True)
