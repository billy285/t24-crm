"""Nonempty read and Ops tables stay in read-only all-150-table evidence."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file); value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


c = load('ops_activation_baseline_core', HERE/'core.py')
b = load('ops_activation_baseline_test', HERE/'baseline.py')
r = load('ops_activation_baseline_retained', HERE.parent/'meta-business-20261031/release.py')


def test_snapshot_allows_nonempty_legacy_grants_and_all_nine_ops_tables(tmp_path, monkeypatch):
    table_names = {'original_'+str(n) for n in range(136)} | r.NEW_TABLES | {'meta_operations_'+name for name in (
        'credentials', 'oauth_states', 'bindings', 'media', 'targets', 'drafts', 'actions', 'schedules', 'requests')}
    rows = {name: {'count': 3, 'rows_sha256': 'a'*64, 'columns':['id'], 'schema':{'id':'integer'}, 'indexes':{}} for name in table_names}
    counters = {'monthly_deduction_rates':42, 'other':7}
    metadata = {'pragma_sha256':'b'*64,'sequence_exists':True,'sequence_values':counters,'sequence_sha256':r.digest(sorted(counters.items()))}
    nginx = tmp_path/'nginx.conf'; nginx.write_bytes(b'SYNTHETIC_UNCHANGED_NGINX')
    calls = []
    m = SimpleNamespace(BUSINESS=tmp_path/'not-opened', NGINX=nginx,
        run=lambda argv,code:calls.append((argv,code)) or b'SYNTHETIC_EFFECTIVE_NGINX', verify_public=lambda path,manifest:'static-fixed')
    w = SimpleNamespace(m=m, retained=r, proof={'database_identity':[1,2], 'private_boundary':'private-fixed','content_security_policy_sha256':'csp-fixed'},
        protections=lambda **kwargs:calls.append(kwargs), rows=lambda:copy.deepcopy(rows), new_schema=lambda path,empty:'schema-fixed' if empty is False else pytest.fail('No emptiness gate'),
        metadata=lambda path:copy.deepcopy(metadata), public=tmp_path/'public',manifest={})
    ctx = SimpleNamespace(m=m, workflow=w, receipt={'schema_sha256':'schema-fixed'})
    b.configure(c); before = copy.deepcopy(rows); value = b._sample(ctx)
    assert len(value['rows']) == 150 and value['rows'] == r.evidence(rows) and rows == before
    assert all(row['count'] == 3 for row in value['rows'].values())
    assert all(not isinstance(row, tuple) or row[0] == ['nginx', '-T'] for row in calls)
    assert 'key_rotation_eligibility' not in value


def test_capture_requires_two_stable_samples_and_preserves_actual_new_rows(monkeypatch):
    counters = {'monthly_deduction_rates':42, 'other':7}
    first = {'rows':{str(i):{'count':i+1,'rows_sha256':'a'*64} for i in range(150)},
        'crm':{'id':'known'}, 'database_metadata':{'pragma_sha256':'b'*64,'sequence_exists':True,'sequence_values':counters,'sequence_sha256':r.digest(sorted(counters.items()))}}
    latest = copy.deepcopy(first); latest['database_metadata']['sequence_values']['monthly_deduction_rates'] += 1
    latest['database_metadata']['sequence_sha256'] = r.digest(sorted(latest['database_metadata']['sequence_values'].items()))
    values = iter([first, latest]); saved = {}
    fake = SimpleNamespace(server_guard=lambda:None, need=c.need, ROOT=Path('/synthetic'), mkdir=lambda path:None,
        write=lambda path,value:saved.setdefault('proof',value) and 'a'*64, SOURCE_SHA='1'*40, FRONTEND='2'*12,
        SCHEMA_REVISION=c.SCHEMA_REVISION, ACTIVATION_FROM=c.ACTIVATION_FROM)
    b.configure(fake); monkeypatch.setattr(b,'collect',lambda:next(values))
    monkeypatch.setattr(b,'dependencies',lambda:SimpleNamespace(workflow=SimpleNamespace(retained=r)))
    try:
        result = b.capture()
        assert result['table_count'] == 150 and result['all_existing_meta_and_ops_rows_preserved'] is True
        assert result['credential_file_content_read'] is False and saved['proof'] == latest
    finally: b.configure(c)


def test_capture_rejects_business_row_drift_before_writing_any_proof(monkeypatch):
    first = {'rows':{str(i):{'count':1,'rows_sha256':'a'*64} for i in range(150)}, 'database_metadata':{
        'pragma_sha256':'b'*64,'sequence_exists':False,'sequence_values':{},'sequence_sha256':r.digest([])}}
    latest = copy.deepcopy(first); latest['rows']['149']['count'] = 2; values = iter([first, latest])
    fake = SimpleNamespace(server_guard=lambda:None, need=c.need, ROOT=Path('/synthetic'), mkdir=lambda path:pytest.fail('No write before stable sample'),
        write=lambda *args:pytest.fail('No proof before stable sample'))
    b.configure(fake); monkeypatch.setattr(b,'collect',lambda:next(values))
    monkeypatch.setattr(b,'dependencies',lambda:SimpleNamespace(workflow=SimpleNamespace(retained=r)))
    try:
        with pytest.raises(c.GuardError, match='ACTIVATION_BASELINE_CHANGED_DURING_CAPTURE'): b.capture()
    finally: b.configure(c)
