"""Sales enrichment migration and fail-closed recovery; no production subprocesses."""
import importlib.util
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

r=load('sales_release',Path(__file__).with_name('release.py'))
migration=load('sales_migration',Path(__file__).parents[2]/'app/backend'/r.MIGRATION)

@pytest.fixture(autouse=True)
def no_real_actions(monkeypatch):
    def forbid(*args,**kwargs):raise AssertionError('No real process, Docker or public write allowed')
    monkeypatch.setattr(subprocess,'run',forbid)
    monkeypatch.setattr(subprocess,'check_output',forbid)
    monkeypatch.setattr(r,'docker_request',forbid)

@pytest.fixture
def database(tmp_path):
    path=tmp_path/'crm.db'
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);
          INSERT INTO alembic_version VALUES ('d5b9a3e7f815');
          CREATE TABLE sales_leads(id INTEGER PRIMARY KEY, contact_name TEXT, phone TEXT);
          INSERT INTO sales_leads VALUES (1,'Synthetic owner','+12135550123');
          CREATE TABLE sales_daily_dial_tasks(id INTEGER PRIMARY KEY, lead_id INTEGER, status TEXT);
          INSERT INTO sales_daily_dial_tasks VALUES (1,1,'completed');
          CREATE INDEX ix_old_task_lead ON sales_daily_dial_tasks(lead_id);
          CREATE TABLE sales_call_activities(id INTEGER PRIMARY KEY, lead_id INTEGER, outcome TEXT);
          INSERT INTO sales_call_activities VALUES(1,1,'no_answer');
          CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY, customer_id INTEGER, employee_id INTEGER, access_level TEXT, scopes TEXT, finance_access TEXT, can_export INTEGER, can_delete INTEGER, can_reassign INTEGER, invitation_source TEXT, invitation_status TEXT, invited_at TEXT, invited_by_id INTEGER, invited_by_name TEXT);
          INSERT INTO customer_access_grants VALUES(1,45,2,'read_write','{"basic":"read_write"}','profit',0,0,0,'owner_invitation','active','2026-10-14',1,'Owner');
          INSERT INTO customer_access_grants VALUES(2,46,3,'read_only','{"deals":"read_only"}','none',0,0,0,'legacy','pending_review',NULL,NULL,NULL);
          CREATE TABLE customers(id INTEGER PRIMARY KEY, private_notes TEXT);
          INSERT INTO customers VALUES(45,'Synthetic private note');
          CREATE TABLE customer_materials(id INTEGER PRIMARY KEY, visibility TEXT);
          INSERT INTO customer_materials VALUES(1,'owner');
          CREATE TABLE employees(id INTEGER PRIMARY KEY, role TEXT, status TEXT);
          INSERT INTO employees VALUES(1,'super_admin','active');
          CREATE TABLE app_settings(config_key TEXT PRIMARY KEY,value_json TEXT);
          INSERT INTO app_settings VALUES('role_permissions','{}');
          CREATE TABLE payments(id INTEGER PRIMARY KEY, amount REAL); INSERT INTO payments VALUES(1,987.65);
          CREATE TABLE customer_commission_attributions(id INTEGER PRIMARY KEY, customer_id INTEGER);INSERT INTO customer_commission_attributions VALUES(3,45);
        """)
    return path

def migrate(path):
    engine=sa.create_engine('sqlite:///'+str(path))
    with engine.connect() as db:
        db.exec_driver_sql('BEGIN IMMEDIATE')
        with Operations.context(MigrationContext.configure(db)):migration.upgrade()
        db.exec_driver_sql("UPDATE alembic_version SET version_num='e6c0b4f8a916'")
        db.commit()
    engine.dispose()

def test_real_migration_preserves_every_old_field_and_active_invitation(database,monkeypatch):
    before=r.sql_snapshot(database);security=r.authorization_snapshot(database);migrate(database)
    r.original_rows_unchanged(before,r.sql_snapshot(database,before))
    r.verify_sales_schema(database,pristine=True)
    assert r.authorization_snapshot(database)==security
    monkeypatch.setattr(r,'BUSINESS',database)
    assert r.committed_revision()==r.NEW_REVISION
    with sqlite3.connect(database) as db:
        assert db.execute('select invitation_source,invitation_status,finance_access from customer_access_grants order by id').fetchall()==[('owner_invitation','active','profit'),('legacy','pending_review','none')]
        assert db.execute('select dial_phone,dial_attempt_id from sales_call_activities').fetchone()==(None,None)

@pytest.mark.parametrize('index',[name for entries in r.NEW_INDEXES.values() for name in entries if not name.startswith('sqlite_')])
def test_every_required_explicit_index_is_verified(database,index):
    migrate(database)
    with sqlite3.connect(database) as db:db.execute('DROP INDEX '+index)
    with pytest.raises(RuntimeError,match='SALES_INDEX_SCHEMA_DRIFT'):r.verify_sales_schema(database)

@pytest.mark.parametrize('sql',[
 'CREATE INDEX ix_sales_call_activities_dial_attempt_id ON sales_call_activities(dial_attempt_id)',
 'CREATE UNIQUE INDEX ix_sales_call_activities_dial_attempt_id ON sales_call_activities(dial_phone)',
 'CREATE UNIQUE INDEX ix_sales_call_activities_dial_attempt_id ON sales_call_activities(dial_attempt_id) WHERE dial_attempt_id>1'])
def test_wrong_unique_index_shape_rejected(database,sql):
    migrate(database)
    with sqlite3.connect(database) as db:
        db.execute('DROP INDEX ix_sales_call_activities_dial_attempt_id');db.execute(sql)
    with pytest.raises(RuntimeError,match='SALES_INDEX_SCHEMA_DRIFT'):r.verify_sales_schema(database)

def test_revision_uniqueness_and_dial_id_uniqueness_are_real_constraints(database):
    migrate(database)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO sales_lead_enrichment_audits(lead_id,revision,source,changed_fields,before,after,actor_id) VALUES(1,1,'manual','[]','{}','{}',1)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO sales_lead_enrichment_audits(lead_id,revision,source,changed_fields,before,after,actor_id) VALUES(1,1,'manual','[]','{}','{}',1)")
        db.execute('UPDATE sales_call_activities SET dial_attempt_id=12')
        with pytest.raises(sqlite3.IntegrityError):db.execute("INSERT INTO sales_call_activities(id,dial_attempt_id) VALUES (2,12)")
    r.verify_sales_schema(database)
    with pytest.raises(RuntimeError,match='NEW_SALES_TABLE_NOT_EMPTY'):r.verify_sales_schema(database,pristine=True)

@pytest.mark.parametrize('table,column,value',[('sales_daily_dial_tasks','dial_phone','+12135550123'),('sales_call_activities','dial_phone','+12135550123'),('sales_call_activities','dial_attempt_id',12)])
def test_migration_must_not_invent_old_dial_data_but_recovery_accepts_later_data(database,monkeypatch,table,column,value):
    migrate(database)
    with sqlite3.connect(database) as db:db.execute(f'UPDATE {table} SET {column}=?',(value,))
    with pytest.raises(RuntimeError,match='EXISTING_SALES_ROW_INITIALIZED'):r.verify_sales_schema(database,pristine=True)
    monkeypatch.setattr(r,'BUSINESS',database)
    assert r.committed_revision()==r.NEW_REVISION

@pytest.mark.parametrize('table,assignment',[('payments','amount=1'),('customer_commission_attributions','customer_id=47'),('customer_access_grants',"invitation_status='revoked'"),('sales_leads',"phone='bad'"),('sales_daily_dial_tasks',"status='pending'")])
def test_existing_finance_attribution_invitation_or_lead_rows_cannot_change(database,table,assignment):
    before=r.sql_snapshot(database);migrate(database)
    with sqlite3.connect(database) as db:db.execute(f'UPDATE {table} SET {assignment}')
    with pytest.raises(RuntimeError,match='BUSINESS_ROWS_CHANGED'):r.original_rows_unchanged(before,r.sql_snapshot(database,before))

@pytest.mark.parametrize('field,value',[('invitation_source','legacy'),('invitation_status','revoked'),('invited_by_id',2),('invited_at','2026-10-15'),('invited_by_name','Other')])
def test_authorization_guard_covers_all_invitation_provenance(database,field,value):
    before=r.authorization_snapshot(database)
    with sqlite3.connect(database) as db:db.execute(f'UPDATE customer_access_grants SET {field}=? WHERE id=1',(value,))
    assert r.authorization_snapshot(database)!=before

def test_original_index_cannot_be_removed(database):
    before=r.sql_snapshot(database);migrate(database)
    with sqlite3.connect(database) as db:db.execute('DROP INDEX ix_old_task_lead')
    with pytest.raises(RuntimeError,match='ORIGINAL_INDEX_SCHEMA_CHANGED'):r.original_rows_unchanged(before,r.sql_snapshot(database,before))

def test_old_runtime_never_started_after_invitation_revision(monkeypatch):
    run=Mock(side_effect=AssertionError('legacy startup forbidden'));monkeypatch.setattr(r,'run',run)
    with pytest.raises(RuntimeError,match='OLD_CRM_BUILD_FORBIDDEN'):r.restore_crm({}, {}, {},r.NEW_REVISION)
    assert run.call_count==0

def test_guard_blocks_old_code_even_without_new_grants(monkeypatch,tmp_path):
    monkeypatch.setattr(r,'settle_migration',Mock())
    monkeypatch.setattr(r,'committed_revision',lambda:r.NEW_REVISION)
    with pytest.raises(RuntimeError,match='FORWARD_RECOVERY'):r.guard_old_authorization_code(tmp_path,{}, {})


def test_rollback_dispatches_forward_when_migration_committed(monkeypatch,tmp_path):
    monkeypatch.setattr(r,'settle_migration',Mock())
    monkeypatch.setattr(r,'committed_revision',lambda:r.NEW_REVISION)
    forward=Mock(return_value={'stage':'SALES_ENRICHMENT_FORWARD_RECOVERED'})
    monkeypatch.setattr(r,'forward_recover',forward)
    monkeypatch.setattr(r,'guard_old_authorization_code',Mock(side_effect=AssertionError('wrong recovery path')))
    assert r.rollback(tmp_path,{}, {}, {},b'old',b'new','TEST')['stage']=='SALES_ENRICHMENT_FORWARD_RECOVERED'
    assert forward.call_count==1


def test_forward_failure_does_not_fall_back_to_old_authorization(monkeypatch,tmp_path):
    monkeypatch.setattr(r,'settle_migration',Mock());monkeypatch.setattr(r,'committed_revision',lambda:r.NEW_REVISION)
    monkeypatch.setattr(r,'forward_recover',Mock(side_effect=RuntimeError('UNAVAILABLE')))
    legacy=Mock(side_effect=AssertionError('legacy startup forbidden'));monkeypatch.setattr(r,'restore_crm',legacy)
    with pytest.raises(RuntimeError,match='UNAVAILABLE'):r.rollback(tmp_path,{}, {}, {},b'old',b'new','TEST')
    assert legacy.call_count==0

@pytest.mark.parametrize('active_kind',['old','none','candidate'])
@pytest.mark.parametrize('interrupted_temp',[None,b'new',b'n',b''])
def test_forward_recovery_only_starts_reviewed_candidate(monkeypatch,tmp_path,active_kind,interrupted_temp):
    new='sha256:'+'2'*64;source='1'*40
    original={'Id':r.OLD_ID,'Image':r.BASE_IMAGE,'State':{'Running':False}}
    active={'Id':'candidate','Image':new,'State':{'Running':False}} if active_kind=='candidate' else (original if active_kind=='old' else None)
    receipt={'candidate_image':new,'public_root':str(tmp_path)}
    manifest={'source_sha':source,'files':{},'backend_after':{}}
    monkeypatch.setattr(r,'settle_migration',Mock());monkeypatch.setattr(r,'committed_revision',lambda:r.NEW_REVISION)
    monkeypatch.setattr(r,'private_boundary',Mock());monkeypatch.setattr(r,'recovery_original',lambda *a:original)
    monkeypatch.setattr(r,'inspect_optional',lambda *a:active)
    monkeypatch.setattr(r,'owned_release_container',lambda *a:True)
    create=Mock(return_value='created');monkeypatch.setattr(r,'docker_create',create)
    run=Mock(return_value=b'');monkeypatch.setattr(r,'run',run);monkeypatch.setattr(r,'ready',Mock())
    monkeypatch.setattr(r,'inventory_in_container',lambda *a:{})
    nginx=tmp_path/'nginx';nginx.write_bytes(b'old');monkeypatch.setattr(r,'NGINX',nginx)
    temp=tmp_path/'.t24-sales-enrichment-next'
    if interrupted_temp is not None:
        temp.write_bytes(interrupted_temp);temp.chmod(0o600);pretend_root_owned(monkeypatch,temp)
    monkeypatch.setattr(r,'reload_nginx',Mock());monkeypatch.setattr(r,'current_boundary',Mock());monkeypatch.setattr(r,'write',Mock())
    result=r.forward_recover(tmp_path,receipt,manifest,{},b'old',b'new','TEST')
    assert result['old_crm_build_started'] is False and result['database_restored'] is False
    starts=[call.args[0] for call in run.call_args_list if call.args[0][1]=='start']
    assert starts==[['docker','start','candidate' if active_kind=='candidate' else 'created']]
    if create.called:assert create.call_args.args[1]==new
    assert nginx.read_bytes()==b'new' and not temp.exists()


def test_release_defaults_match_application_migration():
    assert migration.revision==r.NEW_REVISION and migration.down_revision==r.OLD_REVISION
    assert len(r.NEW_TABLES)==3 and sum(map(len,r.ADDITIONS.values()))==3
    assert len([name for table in r.NEW_INDEXES.values() for name in table if not name.startswith('sqlite_')])==6
    assert "'e6c0b4f8a916'" in r.MIGRATE and "'d5b9a3e7f815'" in r.MIGRATE
    with pytest.raises(RuntimeError,match='forward migration'):migration.downgrade()


def pretend_root_owned(monkeypatch,path):
    # Only filesystem ownership is simulated. File bytes, permissions, link
    # counts, inode identity, cleanup and atomic replacement remain real.
    original=Path.lstat
    def protected_lstat(target,*args,**kwargs):
        result=original(target,*args,**kwargs)
        if target!=path:return result
        return SimpleNamespace(st_uid=0,st_mode=result.st_mode,st_nlink=result.st_nlink,
            st_dev=result.st_dev,st_ino=result.st_ino,st_size=result.st_size,st_mtime_ns=result.st_mtime_ns)
    monkeypatch.setattr(Path,'lstat',protected_lstat)


@pytest.mark.parametrize('content',[b'old',b'new',b'o',b'ne',b''])
def test_cleanup_accepts_only_protected_approved_complete_or_partial_temp(monkeypatch,tmp_path,content):
    nginx=tmp_path/'nginx';nginx.write_bytes(b'old');monkeypatch.setattr(r,'NGINX',nginx)
    temp=tmp_path/'.t24-sales-enrichment-next';temp.write_bytes(content);temp.chmod(0o600)
    pretend_root_owned(monkeypatch,temp)
    r.cleanup_nginx_temp(b'old',b'new')
    assert not temp.exists() and nginx.read_bytes()==b'old'


@pytest.mark.parametrize('kind',['unrecognized','oversized','symlink','hardlink','directory','writable'])
def test_cleanup_keeps_unknown_or_unprotected_temp(monkeypatch,tmp_path,kind):
    nginx=tmp_path/'nginx';nginx.write_bytes(b'old');monkeypatch.setattr(r,'NGINX',nginx)
    temp=tmp_path/'.t24-sales-enrichment-next'
    if kind=='symlink':temp.symlink_to(nginx)
    elif kind=='hardlink':temp.hardlink_to(nginx)
    elif kind=='directory':temp.mkdir()
    else:temp.write_bytes(b'else' if kind=='unrecognized' else b'new-extra' if kind=='oversized' else b'new')
    if kind=='writable':temp.chmod(0o666)
    pretend_root_owned(monkeypatch,temp)
    with pytest.raises(RuntimeError,match='UNKNOWN_NGINX_RECOVERY_TEMP'):r.cleanup_nginx_temp(b'old',b'new')
    assert temp.exists() and nginx.read_bytes()==b'old'


def test_cleanup_does_not_remove_temp_when_current_configuration_has_drifted(monkeypatch,tmp_path):
    nginx=tmp_path/'nginx';nginx.write_bytes(b'external');monkeypatch.setattr(r,'NGINX',nginx)
    temp=tmp_path/'.t24-sales-enrichment-next';temp.write_bytes(b'new');temp.chmod(0o600)
    pretend_root_owned(monkeypatch,temp)
    with pytest.raises(RuntimeError,match='NGINX_RECOVERY_DRIFT'):r.cleanup_nginx_temp(b'old',b'new')
    assert temp.exists() and nginx.read_bytes()==b'external'


@pytest.mark.parametrize('name',['','no','unless-stopped'])
def test_retained_legacy_container_accepts_only_restart_safe_policies(name):
    r.require_safe_original_restart({'HostConfig':{'RestartPolicy':{'Name':name}}})


@pytest.mark.parametrize('policy',[{'Name':'always'},{'Name':'on-failure'},{'Name':'unknown'},None,[]])
def test_retained_legacy_container_rejects_other_restart_policies(policy):
    with pytest.raises(RuntimeError,match='UNSAFE_LEGACY_RESTART_POLICY'):
        r.require_safe_original_restart({'HostConfig':{'RestartPolicy':policy}})


@pytest.mark.parametrize('phase',['prepare','activate'])
def test_release_phases_reject_always_before_build_stop_or_migration(monkeypatch,tmp_path,phase):
    monkeypatch.setattr(r,'current_boundary',Mock(return_value=(None,)*5))
    monkeypatch.setattr(r,'prepared_receipt',Mock(return_value={}))
    monkeypatch.setattr(r,'inspect',Mock(return_value={'HostConfig':{'RestartPolicy':{'Name':'always'}}}))
    nginx=tmp_path/'nginx';nginx.write_bytes(b'old');monkeypatch.setattr(r,'NGINX',nginx)
    monkeypatch.setattr(r,'NGINX_SHA',r.H(b'old'))
    extract=Mock(side_effect=AssertionError('payload must not be written'));monkeypatch.setattr(r,'extract',extract)
    with pytest.raises(RuntimeError,match='UNSAFE_LEGACY_RESTART_POLICY'):
        getattr(r,phase)(tmp_path,SimpleNamespace(),{}, {})
    extract.assert_not_called()


def release_manifest():
    return {'payload_sha256':'payload','credentials_included':False,
        'preserved':{'company_finance_formulas':True,'close_conditions':True,'private_workspace':True,'customer_invitation_rules':True},
        'baseline_source_sha':r.BASELINE,'source_sha':r.SOURCE,'baseline_frontend_version':r.BASELINE_FRONTEND,'frontend_version':r.FRONTEND_VERSION,
        'backend_before':dict.fromkeys(r.BACKEND,None),'backend_after':dict.fromkeys(r.BACKEND,'0'*64),
        'files':{'backend/'+path:'0'*64 for path in r.BACKEND}|{'static/index.html':'0'*64}}


def test_manifest_exact_pins_and_scope_are_accepted(monkeypatch,tmp_path):
    manifest=release_manifest()
    monkeypatch.setattr(r,'read',lambda path,*args:json.dumps(manifest).encode() if path.name=='manifest.json' else b'payload')
    assert r.checked_manifest(tmp_path,SimpleNamespace(manifest_sha256='manifest',payload_sha256='payload'))==manifest


@pytest.mark.parametrize('field,value',[
    ('source_sha','0'*40),('baseline_source_sha','0'*40),('frontend_version','0'*12),('baseline_frontend_version','0'*12),
    ('credentials_included',True),('preserved',{'company_finance_formulas':True}),
    ('backend_after',{}),('files',{'backend/routers/payments.py':'0'*64}),
    ('files',{'static/.env':'0'*64}),('files',{'static/../private.db':'0'*64})])
def test_manifest_rejects_unreviewed_source_or_scope(monkeypatch,tmp_path,field,value):
    manifest=release_manifest();manifest[field]=value
    monkeypatch.setattr(r,'read',lambda path,*args:json.dumps(manifest).encode() if path.name=='manifest.json' else b'payload')
    with pytest.raises(RuntimeError):r.checked_manifest(tmp_path,SimpleNamespace(manifest_sha256='manifest',payload_sha256='payload'))


def test_builder_and_release_use_same_exact_backend_and_source():
    builder=load('sales_payload',Path(__file__).with_name('build_payload.py'))
    assert builder.BACKEND==r.BACKEND and builder.SOURCE==r.SOURCE and builder.BASE==r.BASELINE
    assert builder.FRONTEND_VERSION==r.FRONTEND_VERSION and len(builder.BACKEND)==len(builder.FRONTEND)==9
    assert all('private' not in p.lower() and 'finance' not in p.lower() and 'commission' not in p.lower() for p in builder.BACKEND|builder.FRONTEND)


@pytest.mark.parametrize('running,wrong_id,wrong_image',[(True,False,False),(False,True,False),(False,False,True)])
def test_stop_must_be_verified_before_snapshot_or_migration(monkeypatch,tmp_path,running,wrong_id,wrong_image):
    public=tmp_path/'public';public.mkdir();(public/'app-version.json').write_text('{"version":"v"}')
    nginx=tmp_path/'nginx';oldroot=tmp_path/'old';nginx.write_text('root '+str(oldroot)+';')
    monkeypatch.setattr(r,'NGINX',nginx);monkeypatch.setattr(r,'NGINX_SHA',r.H(nginx.read_bytes()));monkeypatch.setattr(r,'OLD_PUBLIC',oldroot)
    before={'Id':r.OLD_ID,'Image':r.BASE_IMAGE,'State':{'Running':True},'HostConfig':{'RestartPolicy':{'Name':'unless-stopped'}}}
    after={**before,'Id':'other' if wrong_id else r.OLD_ID,'Image':'other' if wrong_image else r.BASE_IMAGE,'State':{'Running':running}}
    monkeypatch.setattr(r,'inspect',Mock(side_effect=[before,after]))
    monkeypatch.setattr(r,'runtime',lambda info:{'stable':'original'})
    monkeypatch.setattr(r,'prepared_receipt',lambda *args:{'old_crm':{'stable':'original'},'public_root':str(public),'candidate_image':'new','rollback_image':'new'})
    monkeypatch.setattr(r,'current_boundary',lambda *args:(None,)*5)
    monkeypatch.setattr(r,'read',lambda *args:json.dumps(before).encode());monkeypatch.setattr(r,'write',Mock())
    run=Mock();backup=Mock(side_effect=AssertionError('must not snapshot a running or different CRM'))
    monkeypatch.setattr(r,'run',run);monkeypatch.setattr(r,'backup',backup);monkeypatch.setattr(r,'rollback',Mock())
    with pytest.raises(RuntimeError,match='CRM_NOT_STOPPED'):
        r.activate(tmp_path,SimpleNamespace(review_sha256='review'),{'source_sha':r.SOURCE,'frontend_version':'v','files':{}},{})
    backup.assert_not_called()
    assert run.call_args_list[0].args[0]==['docker','stop','-t','30','t24-crm']
    assert len(run.call_args_list)==1
