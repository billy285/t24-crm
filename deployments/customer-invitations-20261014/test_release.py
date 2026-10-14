"""Invitation migration and fail-closed recovery; no production subprocesses."""
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

r=load('invitation_release',Path(__file__).with_name('release.py'))
migration=load('invitation_migration',Path(__file__).parents[2]/'app/backend'/r.MIGRATION)

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
          INSERT INTO alembic_version VALUES ('c4a8f2d6e714');
          CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY, customer_id INTEGER, employee_id INTEGER, access_level TEXT, scopes TEXT, finance_access TEXT);
          INSERT INTO customer_access_grants VALUES(1,45,2,'read_write','{"basic":"read_write"}','profit');
          CREATE TABLE payments(id INTEGER PRIMARY KEY, amount REAL); INSERT INTO payments VALUES(1,987.65);
          CREATE TABLE customer_commission_attributions(id INTEGER PRIMARY KEY, customer_id INTEGER);INSERT INTO customer_commission_attributions VALUES(3,45);
        """)
    return path

def migrate(path):
    engine=sa.create_engine('sqlite:///'+str(path))
    with engine.connect() as db:
        db.exec_driver_sql('BEGIN IMMEDIATE')
        with Operations.context(MigrationContext.configure(db)):migration.upgrade()
        db.exec_driver_sql("UPDATE alembic_version SET version_num='d5b9a3e7f815'")
        db.commit()
    engine.dispose()

def test_real_migration_preserves_every_old_field_and_requires_review(database,monkeypatch):
    before=r.sql_snapshot(database);migrate(database)
    r.original_rows_unchanged(before,r.sql_snapshot(database,before))
    r.verify_invitation_defaults(database)
    monkeypatch.setattr(r,'BUSINESS',database)
    assert r.committed_revision()==r.NEW_REVISION
    with sqlite3.connect(database) as db:
        assert db.execute('select access_level,finance_access,invitation_source,invitation_status from customer_access_grants').fetchone()==('read_write','profit','legacy','pending_review')

@pytest.mark.parametrize('field,value',[('invitation_source','owner_invitation'),('invitation_status','active'),('invited_by_id','owner'),('invited_at','2026-10-14'),('invited_by_name','owner')])
def test_any_auto_invitation_in_migration_rejected(database,field,value):
    migrate(database)
    with sqlite3.connect(database) as db:db.execute(f'UPDATE customer_access_grants SET {field}=?',(value,))
    with pytest.raises(RuntimeError,match='LEGACY_GRANT_AUTO_ACTIVATED'):r.verify_invitation_defaults(database)

def test_financial_or_attribution_change_rejected(database):
    before=r.sql_snapshot(database);migrate(database)
    with sqlite3.connect(database) as db:db.execute('UPDATE payments SET amount=1')
    with pytest.raises(RuntimeError,match='BUSINESS_ROWS_CHANGED_PAYMENTS'):r.original_rows_unchanged(before,r.sql_snapshot(database,before))

def test_old_runtime_never_started_after_invitation_revision(monkeypatch):
    run=Mock(side_effect=AssertionError('legacy startup forbidden'));monkeypatch.setattr(r,'run',run)
    with pytest.raises(RuntimeError,match='OLD_AUTHORIZATION_CODE_FORBIDDEN'):r.restore_crm({}, {}, {},r.NEW_REVISION)
    assert run.call_count==0

def test_guard_blocks_old_code_even_without_new_grants(monkeypatch,tmp_path):
    monkeypatch.setattr(r,'settle_migration',Mock())
    monkeypatch.setattr(r,'committed_revision',lambda:r.NEW_REVISION)
    with pytest.raises(RuntimeError,match='FORWARD_RECOVERY'):r.guard_old_authorization_code(tmp_path,{}, {})


def test_rollback_dispatches_forward_when_migration_committed(monkeypatch,tmp_path):
    monkeypatch.setattr(r,'settle_migration',Mock())
    monkeypatch.setattr(r,'committed_revision',lambda:r.NEW_REVISION)
    forward=Mock(return_value={'stage':'INVITATIONS_FORWARD_RECOVERED'})
    monkeypatch.setattr(r,'forward_recover',forward)
    monkeypatch.setattr(r,'guard_old_authorization_code',Mock(side_effect=AssertionError('wrong recovery path')))
    assert r.rollback(tmp_path,{}, {}, {},b'old',b'new','TEST')['stage']=='INVITATIONS_FORWARD_RECOVERED'
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
    temp=tmp_path/'.t24-customer-invitations-next'
    if interrupted_temp is not None:
        temp.write_bytes(interrupted_temp);temp.chmod(0o600);pretend_root_owned(monkeypatch,temp)
    monkeypatch.setattr(r,'reload_nginx',Mock());monkeypatch.setattr(r,'current_boundary',Mock());monkeypatch.setattr(r,'write',Mock())
    result=r.forward_recover(tmp_path,receipt,manifest,{},b'old',b'new','TEST')
    assert result['old_authorization_code_started'] is False and result['database_restored'] is False
    starts=[call.args[0] for call in run.call_args_list if call.args[0][1]=='start']
    assert starts==[['docker','start','candidate' if active_kind=='candidate' else 'created']]
    if create.called:assert create.call_args.args[1]==new
    assert nginx.read_bytes()==b'new' and not temp.exists()


def test_release_defaults_match_application_migration():
    assert migration.revision==r.NEW_REVISION and migration.down_revision==r.OLD_REVISION
    assert set(r.INVITATION_DEFAULTS)==r.ADDITIONS['customer_access_grants']
    assert r.NEW_TABLES=={}


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
    temp=tmp_path/'.t24-customer-invitations-next';temp.write_bytes(content);temp.chmod(0o600)
    pretend_root_owned(monkeypatch,temp)
    r.cleanup_nginx_temp(b'old',b'new')
    assert not temp.exists() and nginx.read_bytes()==b'old'


@pytest.mark.parametrize('kind',['unrecognized','oversized','symlink','hardlink','directory','writable'])
def test_cleanup_keeps_unknown_or_unprotected_temp(monkeypatch,tmp_path,kind):
    nginx=tmp_path/'nginx';nginx.write_bytes(b'old');monkeypatch.setattr(r,'NGINX',nginx)
    temp=tmp_path/'.t24-customer-invitations-next'
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
    temp=tmp_path/'.t24-customer-invitations-next';temp.write_bytes(b'new');temp.chmod(0o600)
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
