"""Actual f21 upgrade over155 populated old tables, including private packet1."""
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
PATH=ROOT/"app/backend/alembic/versions/f21dc345d681_media_asset_studio.py"
PRIOR=ROOT/"app/backend/alembic/versions/e10cb234c570_media_monthly_workflow.py"
TABLES={"media_asset_profiles","media_asset_jobs","media_asset_requests"}
INDEXES={"ix_media_asset_jobs_customer_id"}


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


migration=load(PATH,"actual_asset_migration_release_test")
prior=load(PRIOR,"actual_monthly_prior_schema_release_test")
retained=load(ROOT/"deployments/meta-business-20261031/release.py","asset_schema_retained_shape_test")
retained.NEW_TABLES=frozenset(TABLES)


def seed(path):
    con=sqlite3.connect(path)
    con.execute("PRAGMA user_version=17");con.execute("PRAGMA application_id=240024")
    con.execute("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
    con.execute("INSERT INTO alembic_version VALUES('df0ba123b469')")
    con.execute("CREATE TABLE media_operation_tasks(id INTEGER PRIMARY KEY,content TEXT)")
    con.execute("INSERT INTO media_operation_tasks VALUES(1,'synthetic original task')")
    for i in range(148):
        key="INTEGER PRIMARY KEY AUTOINCREMENT" if i==0 else "INTEGER PRIMARY KEY"
        con.execute(f"CREATE TABLE legacy_{i:03}(id {key},value TEXT)")
        con.execute(f"INSERT INTO legacy_{i:03}(id,value) VALUES(1,'preserved original row')")
    for name,count in (("media_monthly_profiles",1),("media_monthly_runs",1),("media_monthly_items",12)):
        con.execute("CREATE TABLE "+name+"(id INTEGER PRIMARY KEY,content TEXT)")
        con.executemany("INSERT INTO "+name+" VALUES(?,?)",[(i+1,"original polished monthly copy") for i in range(count)])
    con.commit();con.close()
    # The two already-deployed private workflow tables use their real schema.
    engine=sa.create_engine("sqlite:///"+str(path))
    try:
        with engine.connect() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            with Operations.context(MigrationContext.configure(c)):prior.upgrade()
            c.exec_driver_sql("UPDATE alembic_version SET version_num='e10cb234c570'")
            c.exec_driver_sql("INSERT INTO media_monthly_workflows(id,owner_id,customer_id,run_id,revision,status,snapshot,preview_hash,source_hash,task_refs,schedule_refs,expires_at,created_at,updated_at) VALUES(1,1,20,1,1,'prepared',?, ?, ?, '[]','[]','2026-11-02T00:00:00','2026-11-01T00:00:00','2026-11-01T00:00:00')",
                (json.dumps({"private_packet":"SYNTHETIC PRIVATE PREVIEW ONLY","items":[{"slot":i,"content":"polished copy retained"} for i in range(12)]}),"a"*64,"b"*64))
            c.exec_driver_sql("INSERT INTO media_monthly_workflow_requests(id,owner_id,run_id,request_id,kind,fingerprint,result,created_at) VALUES(1,1,1,'00000000-0000-4000-8000-000000000001','prepare',?,?,'2026-11-01T00:00:00')",
                ("c"*64,json.dumps({"private_receipt":"ORIGINAL PRIVATE PACKET RECEIPT","revision":1})))
            c.commit()
    finally:engine.dispose()


def state(path):
    con=sqlite3.connect(path)
    try:
        con.execute("PRAGMA query_only=ON");con.execute("BEGIN")
        objects={(r[0],r[1],r[2]):r[3] for r in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        tables={name:list(con.execute("SELECT * FROM "+name)) for kind,name,_ in objects if kind=="table"}
        sequences=list(con.execute("SELECT name,seq FROM sqlite_sequence ORDER BY name"))
        pragma=[con.execute("PRAGMA "+name).fetchone() for name in ("user_version","application_id")]
        return objects,tables,sequences,pragma
    finally:con.close()


def apply(path):
    engine=sa.create_engine("sqlite:///"+str(path))
    try:
        with engine.connect() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            assert migration.revision=="f21dc345d681" and migration.down_revision=="e10cb234c570"
            assert c.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall()==[("e10cb234c570",)]
            with Operations.context(MigrationContext.configure(c)):migration.upgrade()
            assert c.exec_driver_sql("UPDATE alembic_version SET version_num='f21dc345d681' WHERE version_num='e10cb234c570'").rowcount==1
            c.commit()
    finally:engine.dispose()


def shapes(path):
    retained.NEW_TABLES=frozenset(TABLES)
    con=sqlite3.connect(path)
    try:return {name:retained.table_shape(con,name) for name in sorted(TABLES)}
    finally:con.close()


def test_actual_migration_preserves_all155_populated_tables_private_packet_receipt_sequences_and_metadata(tmp_path):
    path=tmp_path/"synthetic-current155.db";seed(path);before=state(path);source=PATH.read_bytes()
    assert len(before[1])==155 and len(before[1]["media_monthly_workflows"])==len(before[1]["media_monthly_workflow_requests"])==1
    assert before[2]==[("legacy_000",1)]
    apply(path);after=state(path)
    assert len(after[1])==158 and set(after[1])==set(before[1])|TABLES
    assert all(after[0].get(key)==value for key,value in before[0].items())
    assert {key[:2] for key in set(after[0])-set(before[0])}=={("table",name) for name in TABLES}|{("index",name) for name in INDEXES}
    assert {name:rows for name,rows in before[1].items() if name!="alembic_version"}=={name:after[1][name] for name in before[1] if name!="alembic_version"}
    assert after[1]["alembic_version"]==[("f21dc345d681",)] and all(after[1][name]==[] for name in TABLES)
    assert before[2:]==after[2:] and PATH.read_bytes()==source
    frozen=ROOT/"outputs/media-asset-studio-20261101/schema-freeze.json"
    if frozen.exists():assert shapes(path)==json.loads(frozen.read_bytes())["table_shapes"]


@pytest.mark.parametrize("operation",["third_table","index"])
def test_actual_mid_ddl_failure_rolls_back_every_new_object_head_private_rows_and_sequences(tmp_path,monkeypatch,operation):
    path=tmp_path/"synthetic-rollback155.db";seed(path);before=state(path)
    method="create_table" if operation=="third_table" else "create_index";original=getattr(migration.op,method);count=0
    def fail(*args,**kwargs):
        nonlocal count
        count+=1
        if method=="create_index" or count==3:raise RuntimeError("SYNTHETIC_MID_DDL_FAILURE")
        return original(*args,**kwargs)
    monkeypatch.setattr(migration.op,method,fail)
    with pytest.raises(RuntimeError,match="SYNTHETIC_MID_DDL_FAILURE"):apply(path)
    assert state(path)==before


def test_retained_shape_guard_is_exactly_the_three_reviewed_new_tables(tmp_path):
    path=tmp_path/"synthetic-shapes.db";seed(path);apply(path)
    result=shapes(path)
    assert set(result)==TABLES and all(len(value)==64 for value in result.values())
    con=sqlite3.connect(path)
    try:
        with pytest.raises(RuntimeError,match="EXACT_NEW_TABLE_NAME_REQUIRED"):retained.table_shape(con,"media_monthly_workflows")
    finally:con.close()
