"""Execute the actual additive migration on 150 synthetic legacy tables."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
import pytest

ROOT=Path(__file__).resolve().parents[2]
PATH=ROOT/'app/backend/alembic/versions/df0ba123b469_media_monthly.py'
spec=importlib.util.spec_from_file_location('actual_monthly_migration_test',PATH);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
TABLES={'media_monthly_profiles','media_monthly_runs','media_monthly_items'}
INDEXES={'ix_media_monthly_items_run_id','ix_media_monthly_runs_customer_id'}


def seed(path):
    con=sqlite3.connect(path)
    con.execute('CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)');con.execute('INSERT INTO alembic_version VALUES (?)',('cefa9b12a358',))
    con.execute('CREATE TABLE media_operation_tasks(id INTEGER PRIMARY KEY, content TEXT)');con.execute('INSERT INTO media_operation_tasks VALUES (1,?)',('synthetic old task',))
    for i in range(148):
        con.execute(f'CREATE TABLE legacy_{i:03}(id INTEGER PRIMARY KEY,value TEXT)');con.execute(f'INSERT INTO legacy_{i:03} VALUES(1,?)',('synthetic preserved',))
    con.commit();con.close()


def state(path):
    con=sqlite3.connect(path);con.execute('PRAGMA query_only=ON')
    objects={(r[0],r[1],r[2]):r[3] for r in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    tables={name:list(con.execute('SELECT * FROM '+name)) for (kind,name,_),sql in objects.items() if kind=='table'}
    pragma=[con.execute('PRAGMA '+name).fetchone() for name in ('user_version','application_id')];con.close();return objects,tables,pragma


def apply(path):
    engine=sa.create_engine('sqlite:///'+str(path))
    try:
        with engine.connect() as c:
            c.exec_driver_sql('BEGIN IMMEDIATE')
            assert migration.revision=='df0ba123b469' and migration.down_revision=='cefa9b12a358'
            assert c.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[('cefa9b12a358',)]
            with Operations.context(MigrationContext.configure(c)):migration.upgrade()
            assert c.exec_driver_sql("UPDATE alembic_version SET version_num='df0ba123b469' WHERE version_num='cefa9b12a358'").rowcount==1
            c.commit()
    finally:engine.dispose()


def test_actual_three_tables_additive_and_all150_existing_rows_objects_exact(tmp_path):
    path=tmp_path/'synthetic.db';seed(path);old=state(path);source=PATH.read_bytes();apply(path);new=state(path)
    assert len(old[1])==150 and len(new[1])==153 and set(new[1])==set(old[1])|TABLES
    assert all(new[0].get(key)==value for key,value in old[0].items())
    assert {key[:2] for key in set(new[0])-set(old[0])}=={('table',name) for name in TABLES}|{('index',name) for name in INDEXES}
    assert {name:rows for name,rows in old[1].items() if name!='alembic_version'}=={name:new[1][name] for name in old[1] if name!='alembic_version'}
    assert new[1]['alembic_version']==[('df0ba123b469',)] and all(not new[1][name] for name in TABLES)
    assert old[2]==new[2] and PATH.read_bytes()==source


def test_actual_migration_failure_rolls_back_all_ddl_and_old_head_no_db_restore(tmp_path,monkeypatch):
    path=tmp_path/'synthetic.db';seed(path);before=state(path);original=migration.op.create_table;count=0
    def create(*args,**kwargs):
        nonlocal count
        count+=1
        if count==3:raise RuntimeError('SYNTHETIC_DDL_FAILURE')
        return original(*args,**kwargs)
    monkeypatch.setattr(migration.op,'create_table',create)
    with pytest.raises(RuntimeError,match='SYNTHETIC_DDL_FAILURE'):apply(path)
    assert count==3 and state(path)==before
