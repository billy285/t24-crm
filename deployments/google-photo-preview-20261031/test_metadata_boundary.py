"""Real retained metadata with nonempty SQLite counters; no production access."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import pytest

HERE=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v);return v

metadata=load('photo_actual_sequence_metadata',HERE.parent/'media-ops-review-refresh-retry-20261031/preflight.py')
w=load('photo_actual_strict_sequence_guard',HERE.parent/'media-workflow-20261031/release.py')
old_tests=load('photo_actual_table_fingerprint_fixture',HERE.parent/'media-workflow-20261031/test_release.py')


def database(path):
    with sqlite3.connect(path) as con:
        con.executescript("CREATE TABLE finance_canary(id INTEGER PRIMARY KEY AUTOINCREMENT,amount INTEGER UNIQUE);INSERT INTO finance_canary(id,amount) VALUES(42,198);CREATE TABLE media_operation_tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,status TEXT);INSERT INTO media_operation_tasks(id,status) VALUES(3,'draft');CREATE TABLE media_publication_image_policies(owner_id INTEGER PRIMARY KEY,enabled INTEGER);INSERT INTO media_publication_image_policies VALUES(1,1);PRAGMA user_version=17;PRAGMA application_id=42;")


def test_real_nonempty_sequence_metadata_survives_server_proof_json_roundtrip_exactly(tmp_path):
    path=tmp_path/'synthetic.db';database(path);before=metadata.db_metadata(path);captured=json.loads(json.dumps(before));current=metadata.db_metadata(path)
    assert captured['sequence_values']=={'finance_canary':42,'media_operation_tasks':3}
    assert set(captured)=={'pragma_sha256','sequence_exists','sequence_sha256','sequence_values'}
    assert captured==current
    w.sequence_boundary(captured,current)


def test_ignored_autoincrement_insert_advances_counter_without_changing_any_business_rows(tmp_path):
    path=tmp_path/'synthetic.db';database(path);captured=json.loads(json.dumps(metadata.db_metadata(path)));rows=old_tests.sql_snapshot(path)
    with sqlite3.connect(path) as con:con.execute('INSERT OR IGNORE INTO finance_canary(amount) VALUES(198)')
    current=metadata.db_metadata(path)
    assert old_tests.sql_snapshot(path)==rows and captured['pragma_sha256']==current['pragma_sha256']
    assert current['sequence_values']=={'finance_canary':43,'media_operation_tasks':3}
    with pytest.raises(RuntimeError,match='EXACT_OWN_SEQUENCE_METADATA_REQUIRED'):w.sequence_boundary(captured,current)


def test_fresh_capture_accepts_new_counter_and_readonly_probes_do_not_advance_it(tmp_path):
    path=tmp_path/'synthetic.db';database(path)
    with sqlite3.connect(path) as con:con.execute('INSERT OR IGNORE INTO finance_canary(amount) VALUES(198)')
    fresh=json.loads(json.dumps(metadata.db_metadata(path)));source_bytes=path.read_bytes()
    for _ in range(3):
        old_tests.sql_snapshot(path);w.objects(path);w.sequence_boundary(fresh,metadata.db_metadata(path))
    assert path.read_bytes()==source_bytes and metadata.db_metadata(path)==fresh


def test_idle_google_sqlite_lock_pattern_does_not_advance_any_autoincrement_counter(tmp_path):
    path=tmp_path/'synthetic.db';database(path);before=metadata.db_metadata(path)
    with sqlite3.connect(path) as con:con.execute('UPDATE media_operation_tasks SET id=id WHERE 0')
    assert metadata.db_metadata(path)==before


retry=load('photo_retry_observed_counter_compatibility',HERE/'release.py')


def monthly_database(path):
    with sqlite3.connect(path) as con:
        con.executescript("CREATE TABLE monthly_deduction_rates(id INTEGER PRIMARY KEY AUTOINCREMENT,year_month TEXT UNIQUE,rate TEXT);INSERT INTO monthly_deduction_rates VALUES(42,'2026-10','0.15');CREATE TABLE another_counter(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT UNIQUE);INSERT INTO another_counter VALUES(7,'EXISTING');PRAGMA user_version=17;PRAGMA application_id=42;")


def test_only_actual_observed_monthly_ignored_insert_is_compatible_without_mutation(tmp_path):
    path=tmp_path/'synthetic-monthly.db';monthly_database(path);before=json.loads(json.dumps(metadata.db_metadata(path)));rows=old_tests.sql_snapshot(path)
    with sqlite3.connect(path) as con:con.execute("INSERT OR IGNORE INTO monthly_deduction_rates(year_month,rate) VALUES('2026-10','0.15')")
    current=metadata.db_metadata(path);inputs=json.loads(json.dumps([before,current]));after_insert_bytes=path.read_bytes()
    assert before['sequence_values']['monthly_deduction_rates']==42 and current['sequence_values']['monthly_deduction_rates']==43
    assert old_tests.sql_snapshot(path)==rows
    retry.static_sequence_boundary(before,current,w.sequence_boundary)
    assert [before,current]==inputs and path.read_bytes()==after_insert_bytes


@pytest.mark.parametrize('change',['other_counter','added_key','removed_key','regression','hash_forgery','pragma','sequence_exists'])
def test_scoped_compatibility_rejects_other_counter_key_regression_hash_or_pragma_change(tmp_path,change):
    path=tmp_path/'synthetic-monthly.db';monthly_database(path);before=metadata.db_metadata(path);current=json.loads(json.dumps(before))
    if change=='other_counter':current['sequence_values']['another_counter']+=1
    elif change=='added_key':current['sequence_values']['new_counter']=1
    elif change=='removed_key':del current['sequence_values']['another_counter']
    elif change=='regression':current['sequence_values']['monthly_deduction_rates']-=1
    elif change=='pragma':current['pragma_sha256']='0'*64
    elif change=='sequence_exists':current['sequence_exists']=False
    current['sequence_sha256']=w.digest(sorted(current['sequence_values'].items()))
    if change=='hash_forgery':current['sequence_sha256']='0'*64
    with pytest.raises(RuntimeError):retry.static_sequence_boundary(before,current,w.sequence_boundary)
