"""Real additive migration over158 populated tables; no backfill or old DDL."""
import importlib.util
from pathlib import Path
import sqlite3
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from models.google_business_onboarding import GoogleOnboardingCatalog,GoogleOnboardingBatch,GoogleOnboardingItem,GoogleOnboardingRequest

PATH=Path(__file__).resolve().parents[1]/"alembic/versions/g32ed456e792_google_business_onboarding.py"
spec=importlib.util.spec_from_file_location("onboarding_actual_migration",PATH);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
NEW={x.__tablename__:x.__table__ for x in (GoogleOnboardingCatalog,GoogleOnboardingBatch,GoogleOnboardingItem,GoogleOnboardingRequest)}


def seed(path):
    con=sqlite3.connect(path)
    con.execute("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)");con.execute("INSERT INTO alembic_version VALUES('f21dc345d681')")
    names=["google_business_bindings","google_business_grants","customers","private_space_canary","media_monthly_workflows","media_asset_jobs","media_asset_profiles","customer_materials","financial_canary"]+["old_"+str(x) for x in range(148)]
    for name in names:
        con.execute('CREATE TABLE "'+name+'"(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT)')
        count=15 if name=="google_business_bindings" else 2 if name=="media_asset_jobs" else 1
        con.executemany('INSERT INTO "'+name+'" VALUES(?,?)',[(x+1,"ORIGINAL_NO_BACKFILL_"+name) for x in range(count)])
    con.execute("INSERT INTO financial_canary VALUES(2,'removed counter proof')");con.execute("DELETE FROM financial_canary WHERE id=2")
    con.execute("PRAGMA user_version=19");con.execute("PRAGMA application_id=240024");con.commit();con.close()


def state(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    try:
        objects={(x[0],x[1],x[2]):x[3] for x in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        rows={name:list(con.execute('SELECT * FROM "'+name+'" ORDER BY 1')) for kind,name,_ in objects if kind=="table"}
        metadata=[list(con.execute("SELECT * FROM sqlite_sequence ORDER BY name")),con.execute("PRAGMA user_version").fetchone(),con.execute("PRAGMA application_id").fetchone()]
        return objects,rows,metadata
    finally:con.close()


def upgrade(path,fail=False):
    engine=sa.create_engine("sqlite:///"+str(path))
    if fail:
        def inject(conn,cursor,statement,params,ctx,many):
            if "CREATE TABLE google_business_onboarding_items" in statement:raise RuntimeError("synthetic mid-DDL failure")
        sa.event.listen(engine,"before_cursor_execute",inject)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            with Operations.context(MigrationContext.configure(conn)):migration.upgrade()
            conn.exec_driver_sql("UPDATE alembic_version SET version_num='g32ed456e792'");conn.commit()
    finally:engine.dispose()


def test_actual_four_empty_tables_preserve_all158_original_tables_and_counters(tmp_path):
    path=tmp_path/"synthetic.db";seed(path);before=state(path);assert len(before[1])==158
    upgrade(path);after=state(path);assert len(after[1])==162 and set(after[1])==set(before[1])|set(NEW)
    assert migration.down_revision=="f21dc345d681" and migration.revision=="g32ed456e792"
    assert all(after[0][key]==value for key,value in before[0].items())
    assert all(after[1][name]==rows for name,rows in before[1].items() if name!="alembic_version")
    assert after[1]["alembic_version"]==[("g32ed456e792",)] and after[2]==before[2]
    assert all(after[1][name]==[] for name in NEW)
    assert len(after[1]["google_business_bindings"])==15


def test_actual_migration_shape_matches_models_and_index(tmp_path):
    path=tmp_path/"synthetic.db";seed(path);upgrade(path);engine=sa.create_engine("sqlite:///"+str(path));inspector=sa.inspect(engine)
    try:
        for name,table in NEW.items():
            actual=inspector.get_columns(name)
            assert [x["name"] for x in actual]==list(table.columns.keys())
            assert [(x["name"],x["nullable"]) for x in actual]==[(x.name,x.nullable) for x in table.columns]
            assert {tuple(x["column_names"]) for x in inspector.get_unique_constraints(name)}=={tuple(x.name for x in constraint.columns) for constraint in table.constraints if isinstance(constraint,sa.UniqueConstraint)}
        assert inspector.get_indexes("google_business_onboarding_items")[0]["name"]=="ix_google_business_onboarding_items_batch_id"
    finally:engine.dispose()


def test_mid_ddl_failure_rolls_back_every_new_table_and_old_rows(tmp_path):
    path=tmp_path/"synthetic.db";seed(path);before=state(path)
    with pytest.raises(RuntimeError,match="mid-DDL"):upgrade(path,fail=True)
    assert state(path)==before
