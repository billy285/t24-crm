"""Actual new migration over populated158, never a production database."""
import importlib.util
import json
from pathlib import Path
import sqlite3

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

ROOT=Path(__file__).resolve().parents[2]
PATH=ROOT/'app/backend/alembic/versions/g32ed456e792_google_business_onboarding.py'
NEW=frozenset({'google_business_onboarding_catalogs','google_business_onboarding_batches','google_business_onboarding_items','google_business_onboarding_requests'})
INDEXES=frozenset({'ix_google_business_onboarding_items_batch_id'})


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


prior=load(ROOT/'deployments/media-asset-studio-20261101/test_schema_migration.py','onboarding_actual_asset_schema_seed')
migration=load(PATH,'onboarding_actual_new_migration')


def seed(path):
    prior.seed(path);prior.apply(path)
    con=sqlite3.connect(path)
    try:
        con.execute('DROP TABLE legacy_147')
        con.execute('CREATE TABLE google_business_bindings(id INTEGER PRIMARY KEY,customer_id INTEGER UNIQUE,location_name TEXT UNIQUE,active INTEGER,revision INTEGER)')
        con.executemany('INSERT INTO google_business_bindings VALUES(?,?,?,1,1)',[(i,i,'accounts/1/locations/'+str(i)) for i in range(1,16)])
        con.execute('DROP TABLE legacy_146')
        con.execute('CREATE TABLE customer_materials(id INTEGER PRIMARY KEY,customer_id INTEGER,approval_status TEXT,private_original_marker TEXT)')
        con.executemany('INSERT INTO customer_materials VALUES(?,20,?,?)',[(i,'pending' if i in (6,7) else 'approved','synthetic original material '+str(i)) for i in range(1,8)])
        con.execute('DROP TABLE legacy_145')
        con.execute('CREATE TABLE customer_record_audits(id INTEGER PRIMARY KEY,entity_id INTEGER,action TEXT)')
        con.executemany("INSERT INTO customer_record_audits VALUES(?,?,'create')",[(1,6),(2,7)])
        con.execute("INSERT INTO media_asset_profiles(owner_id,customer_id,revision,settings,updated_at) VALUES(1,20,1,?,'2026-11-01T00:00:00')",(json.dumps({'brand_name':'synthetic private brand'}),))
        for i,kind in enumerate(('poster','video')):
            identity=chr(ord('a')+i)*32
            con.execute("INSERT INTO media_asset_jobs(id,owner_id,customer_id,request_id,fingerprint,revision,kind,status,snapshot,attempt,output,adoption,message,created_at,updated_at) VALUES(?,1,20,?,?,4,?,'adopted',?,1,?,?,'synthetic adopted','2026-11-01T00:00:00','2026-11-01T00:00:00')",
                (identity,'00000000-0000-4000-8000-'+str(i+1).zfill(12),'c'*64,kind,json.dumps({'original_private_source':'synthetic-only'}),json.dumps({'mime_type':'image/png' if i==0 else 'video/mp4','duration_seconds':None if i==0 else 6}),json.dumps({'material_id':6+i})))
        for i in range(5):
            kind='profile' if i==0 else 'create' if i<3 else 'adopt'
            con.execute("INSERT INTO media_asset_requests(id,owner_id,customer_id,request_id,kind,fingerprint,result,created_at) VALUES(?,1,20,?,?,?,?, '2026-11-01T00:00:00')",(i+1,'00000000-0000-4000-8000-'+str(i+1).zfill(12),kind,'d'*64,json.dumps({'original_receipt':i})))
        con.commit()
    finally:con.close()


def state(path):return prior.state(path)


def apply(path):
    engine=sa.create_engine('sqlite:///'+str(path))
    try:
        with engine.connect() as con:
            con.exec_driver_sql('BEGIN IMMEDIATE')
            assert migration.revision=='g32ed456e792' and migration.down_revision=='f21dc345d681'
            assert con.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[('f21dc345d681',)]
            with Operations.context(MigrationContext.configure(con)):migration.upgrade()
            assert con.exec_driver_sql("UPDATE alembic_version SET version_num='g32ed456e792' WHERE version_num='f21dc345d681'").rowcount==1
            con.commit()
    finally:engine.dispose()


def shapes(path):
    prior.retained.NEW_TABLES=NEW
    con=sqlite3.connect(path)
    try:return {name:prior.retained.table_shape(con,name) for name in sorted(NEW)}
    finally:con.close()


def test_actual_migration_keeps_all158_original_rows_15_bindings_and_private_pilots(tmp_path):
    path=tmp_path/'synthetic-current158.db';seed(path);before=state(path);source=PATH.read_bytes()
    assert len(before[1])==158 and len(before[1]['google_business_bindings'])==15
    assert len(before[1]['media_asset_profiles'])==1 and len(before[1]['media_asset_jobs'])==2 and len(before[1]['media_asset_requests'])==5
    assert len(before[1]['media_monthly_workflows'])==len(before[1]['media_monthly_workflow_requests'])==1
    apply(path);after=state(path)
    assert len(after[1])==162 and set(after[1])==set(before[1])|NEW
    assert all(after[0].get(key)==value for key,value in before[0].items())
    assert {key[:2] for key in set(after[0])-set(before[0])}=={('table',name) for name in NEW}|{('index',name) for name in INDEXES}
    assert {name:rows for name,rows in before[1].items() if name!='alembic_version'}=={name:after[1][name] for name in before[1] if name!='alembic_version'}
    assert after[1]['alembic_version']==[('g32ed456e792',)] and all(after[1][name]==[] for name in NEW)
    assert before[2:]==after[2:] and PATH.read_bytes()==source
    frozen=ROOT/'outputs/google-business-onboarding-20261102/schema-freeze.json'
    if frozen.exists():assert shapes(path)==json.loads(frozen.read_text())['table_shapes']


@pytest.mark.parametrize('operation',['fourth_table','index'])
def test_failure_during_actual_migration_rolls_back_every_new_object_and_original158(tmp_path,monkeypatch,operation):
    path=tmp_path/'synthetic-rollback158.db';seed(path);before=state(path)
    name='create_table' if operation=='fourth_table' else 'create_index';original=getattr(migration.op,name);count=0
    def fail(*args,**kwargs):
        nonlocal count
        count+=1
        if name=='create_index' or count==4:raise RuntimeError('SYNTHETIC_MID_DDL_FAILURE')
        return original(*args,**kwargs)
    monkeypatch.setattr(migration.op,name,fail)
    with pytest.raises(RuntimeError,match='SYNTHETIC_MID_DDL_FAILURE'):apply(path)
    assert state(path)==before


def test_exact_new_shapes_only_four_empty_tables(tmp_path):
    path=tmp_path/'synthetic-shapes.db';seed(path);apply(path);values=shapes(path)
    assert set(values)==NEW and all(len(value)==64 for value in values.values())
