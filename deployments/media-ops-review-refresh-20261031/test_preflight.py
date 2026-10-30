import importlib.util
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parent

def module(name):
    spec=importlib.util.spec_from_file_location('refresh_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m
p=module('preflight');g=module('generate_preflight_command')


def test_db_metadata_is_readonly_and_includes_pragma_sequence(tmp_path):
    path=tmp_path/'synthetic.db'
    with sqlite3.connect(path) as con:
        con.executescript('CREATE TABLE example(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT);INSERT INTO example(name) VALUES(\'test\');PRAGMA user_version=9;PRAGMA application_id=123;')
    before=path.read_bytes();meta=p.db_metadata(path)
    assert path.read_bytes()==before and meta['sequence_exists'] and set(meta)=={'pragma_sha256','sequence_sha256','sequence_exists','sequence_values'}
    assert 'test' not in json.dumps(meta)
    with sqlite3.connect(path) as con:con.execute('UPDATE sqlite_sequence SET seq=99')
    assert p.db_metadata(path)!=meta


def test_db_metadata_handles_no_autoincrement_table(tmp_path):
    path=tmp_path/'synthetic.db'
    with sqlite3.connect(path) as con:con.execute('CREATE TABLE example(id INTEGER PRIMARY KEY)')
    assert p.db_metadata(path)['sequence_exists'] is False


def test_row_evidence_exports_only_counts_and_hashes():
    m=SimpleNamespace(BUSINESS=Path('/synthetic.db'),sql_snapshot=lambda _: {'financial_canary':{'count':1,'rows_sha256':'a'*64,'columns':['name'],'schema':{'name':'TEXT'},'indexes':[],'raw_canary':'NEVER_EXPORT'}})
    value=p.row_evidence(m)
    assert set(value['financial_canary'])=={'count','rows_sha256','shape_sha256'} and 'NEVER_EXPORT' not in json.dumps(value)


def test_collect_guard_precedes_all_dependencies(monkeypatch):
    calls=[];monkeypatch.setattr(p,'guard',lambda:(_ for _ in ()).throw(RuntimeError('guard')))
    monkeypatch.setattr(p,'dependencies',lambda:calls.append('unexpected'))
    with pytest.raises(RuntimeError):p.collect()
    assert calls==[]


def test_collect_rejects_changed_snapshot(monkeypatch):
    monkeypatch.setattr(p,'guard',lambda:None);monkeypatch.setattr(p,'dependencies',lambda:(None,None,None));calls=[0]
    def baseline(*_):calls[0]+=1;return {'counter':calls[0]}
    monkeypatch.setattr(p,'baseline',baseline)
    with pytest.raises(RuntimeError,match='PREFLIGHT_CHANGED_DURING_READ'):p.collect()


def test_preflight_wrapper_is_isolated_bounded_hash_exact():
    value=g.command();assert len(value.encode())<11000 and 'sudo python3 -I -S -B' in value
    assert value.index('os.geteuid()')<value.index('exec(compile')
    assert hashlib.sha256((HERE/'preflight.py').read_bytes()).hexdigest() in value
    assert 'urllib' not in value and 'module.capture()' in value


@pytest.mark.parametrize('name',['SOURCE','BASE_SOURCE','BASE_FRONTEND','ORIGINAL_ID','IMAGE','DEPLOYED_SHA'])
def test_exact_pins_exist(name):
    field='BASE_SOURCE' if name=='SOURCE' else name
    assert isinstance(getattr(p,field),str) and getattr(p,field)


def test_only_sql_selects_and_metadata_pragma_present():
    source=(HERE/'preflight.py').read_text()
    assert 'mode=ro' in source and 'PRAGMA query_only=ON' in source
    assert '.private_boundary(' not in source and '.safe_private_boundary(' in source
    assert 'UPDATE ' not in source and 'INSERT ' not in source and 'DELETE ' not in source


def test_release_loader_pins_exact_current_prefight_source():
    release=module('release')
    assert release.PREFLIGHT_SHA==hashlib.sha256((HERE/'preflight.py').read_bytes()).hexdigest()
