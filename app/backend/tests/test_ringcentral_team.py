"""Salesperson attribution and passive team health in multi-account RingCentral."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from models.employees import Employees
from models.ringcentral_connections import RingCentralConnections
from models.ringcentral_call_records import RingCentralCallRecords
from routers import ringcentral
from schemas.auth import UserResponse
from services.ringcentral_sync import _connection_for_event, upsert_call_log_record
from services.ringcentral_team import passive_connection_status


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=[
            Employees.__table__, RingCentralConnections.__table__, RingCentralCallRecords.__table__]))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        # Emulate pre-migration legacy data for duplicate diagnostics tests.
        from sqlalchemy import text
        await session.execute(text("DROP INDEX uq_ringcentral_connection_provider_identity"))
        session.add_all([
            Employees(id=1, user_id="1", name="Boss", role="super_admin", status="active"),
            Employees(id=10, user_id="10", name="Manager", role="sales_manager", status="active"),
            Employees(id=11, user_id="11", name="Sales A", role="sales", status="active", supervisor="Manager"),
            Employees(id=12, user_id="12", name="PRIVATE_OTHER_TEAM", role="sales", status="probation", supervisor="Other"),
            Employees(id=13, user_id="13", name="Departed", role="sales", status="inactive", supervisor="Manager"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


def user(employee_id, role, name=""):
    return UserResponse(id=str(employee_id), role=role, name=name, email="synthetic@test.invalid")


def connection(employee_id=11, account_id="account-a", extension_id="ext-1", **kwargs):
    values = dict(employee_id=employee_id, ringcentral_account_id=account_id,
                  ringcentral_extension_id=extension_id, extension_number="101", is_active=True,
                  access_token_encrypted="PRIVATE_ACCESS_TOKEN", refresh_token_encrypted="PRIVATE_REFRESH_TOKEN",
                  token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                  webhook_subscription_status="active",
                  webhook_expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    values.update(kwargs)
    return RingCentralConnections(**values)


@pytest.mark.asyncio
async def test_team_status_scope_does_not_refresh_or_expose_other_teams(db, monkeypatch):
    monkeypatch.setattr(ringcentral, "connection_configured", lambda: True)
    async def forbidden_refresh(*args):
        raise AssertionError("Passive team lookup must not refresh another employee's token")
    monkeypatch.setattr(ringcentral, "_refresh_connection_if_needed", forbidden_refresh)
    db.add_all([connection(), connection(12, "account-b", "ext-2")])
    await db.commit()
    for current_user, expected in [(user(11,"sales"), {11}), (user(10,"sales_manager","Manager"), {11}),
                                   (user(1,"super_admin"), {11,12})]:
        result = await ringcentral.ringcentral_team_status(current_user=current_user, db=db)
        assert {row["employee_id"] for row in result["items"]} == expected
        assert result["summary"]["ready"] == len(expected)
        assert "PRIVATE_ACCESS_TOKEN" not in str(result) and "PRIVATE_REFRESH_TOKEN" not in str(result)
        if current_user.role != "super_admin":
            assert "PRIVATE_OTHER_TEAM" not in str(result)
    with pytest.raises(HTTPException) as exc:
        await ringcentral.ringcentral_team_status(current_user=user(1,"operations"), db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unconnected_sales_and_expired_webhook_are_not_healthy(db, monkeypatch):
    monkeypatch.setattr(ringcentral, "connection_configured", lambda: True)
    db.add(connection(webhook_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
    await db.commit()
    result = await ringcentral.ringcentral_team_status(current_user=user(1,"super_admin"), db=db)
    by_id = {row["employee_id"]:row for row in result["items"]}
    assert by_id[11]["sync_health"] == "attention" and not by_id[11]["realtime_sync_enabled"]
    assert by_id[12]["sync_health"] == "disconnected"
    assert result["summary"] == dict(total=2, ready=0, attention=1, not_connected=1)
    expired_token = connection(token_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
    assert passive_connection_status(expired_token)["sync_health"] == "attention"
    unknown_expiration = connection(webhook_expires_at=None)
    assert not passive_connection_status(unknown_expiration)["realtime_sync_enabled"]


@pytest.mark.asyncio
async def test_conflict_across_team_is_reported_without_other_identity(db,monkeypatch):
    monkeypatch.setattr(ringcentral,"connection_configured",lambda:True)
    db.add_all([connection(),connection(12,is_active=False)])
    await db.commit()
    result=await ringcentral.ringcentral_team_status(current_user=user(10,"sales_manager","Manager"),db=db)
    assert len(result["items"])==1
    assert result["items"][0]["binding_conflict"]
    assert not result["items"][0]["realtime_sync_enabled"]
    assert "PRIVATE_OTHER_TEAM" not in str(result)


@pytest.mark.asyncio
async def test_oauth_conflicting_historical_binding_preserves_both_records(db,monkeypatch):
    db.add_all([connection(),connection(12,"account-b","ext-2",is_active=False)])
    await db.commit()
    monkeypatch.setattr(ringcentral,"verify_oauth_state",lambda _:11)
    async def exchange(_): return {"access_token":"new-token","refresh_token":"new-refresh"}
    async def profile(_): return {"id":"ext-2","account":{"id":"account-b"},"extensionNumber":"102"}
    monkeypatch.setattr(ringcentral,"exchange_authorization_code",exchange)
    monkeypatch.setattr(ringcentral,"get_extension_profile",profile)
    result=await ringcentral.ringcentral_callback(code="synthetic-code",state="synthetic-state",error=None,db=db)
    assert result.headers["location"]=="/sales-workbench?ringcentral=binding_conflict"
    rows=(await db.execute(select(RingCentralConnections).order_by(RingCentralConnections.employee_id))).scalars().all()
    assert [(row.ringcentral_account_id,row.ringcentral_extension_id,row.is_active) for row in rows]==[
        ("account-a","ext-1",True),("account-b","ext-2",False)]
    assert all(row.access_token_encrypted=="PRIVATE_ACCESS_TOKEN" for row in rows)


@pytest.mark.asyncio
async def test_events_use_account_scope_and_skip_missing_or_ambiguous_identity(db):
    first,second=connection(),connection(12,"account-b","ext-1")
    db.add_all([first,second]);await db.commit()
    base={"body":{"parties":[{"extensionId":"ext-1"}]}}
    assert await _connection_for_event(db,base) is None
    assert (await _connection_for_event(db,{**base,"event":"/restapi/v1.0/account/account-b/extension/ext-1/telephony/sessions"})).employee_id==12
    assert await _connection_for_event(db,{**base,"accountId":"unknown-account"}) is None
    assert await _connection_for_event(db,{**base,"accountId":"account-a","body":{"accountId":"account-b","parties":[{"extensionId":"ext-1"}]}}) is None
    second.ringcentral_account_id="account-a";second.is_active=False
    await db.commit()
    assert await _connection_for_event(db,{**base,"accountId":"account-a"}) is None


@pytest.mark.asyncio
async def test_same_provider_call_id_in_different_accounts_remains_separate_and_idempotent(db):
    first,second=connection(),connection(12,"account-b","ext-1")
    db.add_all([first,second]);await db.commit()
    record={"id":"same-call-id","telephonySessionId":"same-session", "direction":"Outbound",
            "startTime":"2026-11-09T01:00:00Z","result":"Call connected","duration":60}
    call_a=await upsert_call_log_record(db,first,record)
    call_b=await upsert_call_log_record(db,second,{**record,"duration":120})
    await db.commit()
    assert call_a.id!=call_b.id and call_a.duration_seconds==60 and call_b.duration_seconds==120
    repeat=await upsert_call_log_record(db,second,{**record,"duration":150})
    await db.commit()
    assert repeat.id==call_b.id and call_a.duration_seconds==60
    assert len((await db.execute(select(RingCentralCallRecords))).scalars().all())==2


@pytest.mark.asyncio
async def test_own_status_exposes_identity_and_conflict_after_refresh(db,monkeypatch):
    monkeypatch.setattr(ringcentral,"connection_configured",lambda:True)
    db.add_all([connection(),connection(12,is_active=False)]);await db.commit()
    async def unchanged(employee_id,row,db): return row
    monkeypatch.setattr(ringcentral,"_refresh_connection_if_needed",unchanged)
    result=await ringcentral.ringcentral_status(current_user=user(11,"sales"),db=db)
    assert result["employee_id"]==11 and result["binding_conflict"]
    assert not result["realtime_sync_enabled"]


@pytest.mark.asyncio
async def test_oauth_is_not_a_successful_call_log_sync(db,monkeypatch):
    old_sync=datetime(2026,11,1,tzinfo=timezone.utc)
    existing=connection(last_synced_at=old_sync)
    db.add(existing);await db.commit()
    monkeypatch.setattr(ringcentral,"verify_oauth_state",lambda _:11)
    async def exchange(_): return {"access_token":"new-token","refresh_token":"new-refresh","expires_in":3600}
    async def profile(_): return {"id":"ext-1","account":{"id":"account-a"},"extensionNumber":"101"}
    async def subscribe(*args,**kwargs): return {"id":"subscription-new","status":"Active","expirationTime":"2027-01-01T00:00:00Z"}
    monkeypatch.setattr(ringcentral,"exchange_authorization_code",exchange)
    monkeypatch.setattr(ringcentral,"get_extension_profile",profile)
    monkeypatch.setattr(ringcentral,"create_telephony_subscription",subscribe)
    monkeypatch.setattr(ringcentral,"encrypt_token",lambda _:"synthetic-encrypted")
    response=await ringcentral.ringcentral_callback(code="code",state="state",error=None,db=db)
    assert response.headers["location"].endswith("ringcentral=connected")
    assert existing.last_synced_at==old_sync
    async def different_profile(_): return {"id":"new-ext","account":{"id":"account-a"},"extensionNumber":"102"}
    monkeypatch.setattr(ringcentral,"get_extension_profile",different_profile)
    await ringcentral.ringcentral_callback(code="code",state="state",error=None,db=db)
    assert existing.last_synced_at is None and existing.last_event_at is None


def test_provider_identity_migration_preserves_rows_and_refuses_lossy_downgrade():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import IntegrityError
    path=Path(__file__).parents[1]/"alembic/versions/j65bc789b025_ringcentral_provider_identity.py"
    spec=importlib.util.spec_from_file_location("ringcentral_identity_migration",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        RingCentralCallRecords.__table__.create(conn)
        RingCentralConnections.__table__.create(conn)
        conn.execute(sa.text("DROP INDEX uq_ringcentral_connection_provider_identity"))
        conn.execute(RingCentralConnections.__table__.insert().values(employee_id=11,ringcentral_account_id="a",ringcentral_extension_id="e",access_token_encrypted="preserved-token"))
        conn.execute(sa.text("DROP INDEX uq_ringcentral_call_provider_identity"))
        conn.execute(sa.text("DROP INDEX ix_ringcentral_call_records_ringcentral_call_id"))
        conn.execute(sa.text("CREATE UNIQUE INDEX ix_ringcentral_call_records_ringcentral_call_id ON ringcentral_call_records (ringcentral_call_id)"))
        conn.execute(RingCentralCallRecords.__table__.insert().values(provider_key="retained",ringcentral_call_id="same-id",ringcentral_account_id="a",ringcentral_extension_id="e",sales_employee_id=11,duration_seconds=42))
        migration.op=Operations(MigrationContext.configure(conn))
        migration.upgrade()
        with pytest.raises(IntegrityError):
            conn.execute(RingCentralConnections.__table__.insert().values(employee_id=12,ringcentral_account_id="a",ringcentral_extension_id="e",access_token_encrypted="should-not-save"))
        assert conn.execute(sa.text("SELECT employee_id,access_token_encrypted FROM ringcentral_connections")).one()==(11,"preserved-token")
        retained=conn.execute(sa.text("SELECT provider_key,sales_employee_id,duration_seconds FROM ringcentral_call_records")).one()
        assert tuple(retained)==("retained",11,42)
        migration.downgrade()
        migration.upgrade()
        conn.execute(RingCentralCallRecords.__table__.insert().values(provider_key="different-account",ringcentral_call_id="same-id",ringcentral_account_id="b",ringcentral_extension_id="e",sales_employee_id=12))
        with pytest.raises(IntegrityError):
            conn.execute(RingCentralCallRecords.__table__.insert().values(provider_key="same-identity",ringcentral_call_id="same-id",ringcentral_account_id="b",ringcentral_extension_id="e",sales_employee_id=12))
        with pytest.raises(RuntimeError,match="collide across accounts"):
            migration.downgrade()
        assert conn.execute(sa.text("SELECT COUNT(*) FROM ringcentral_call_records")).scalar()==2
    engine.dispose()


@pytest.mark.asyncio
async def test_conflicting_bindings_cannot_import_call_log_even_after_callback_race(db):
    first,second=connection(),connection(12,is_active=False)
    db.add_all([first,second]);await db.commit()
    result=await upsert_call_log_record(db,first,{"id":"unattributable","direction":"Outbound"})
    assert result is None
    assert "绑定冲突" in first.last_error
    assert not (await db.execute(select(RingCentralCallRecords))).scalars().all()


@pytest.mark.asyncio
async def test_database_constraint_handles_concurrent_oauth_binding_conflict(db,monkeypatch):
    from sqlalchemy import text
    from types import SimpleNamespace
    db.add_all([connection(),connection(12,"account-b","ext-2")]);await db.commit()
    await db.execute(text("CREATE UNIQUE INDEX uq_ringcentral_connection_provider_identity ON ringcentral_connections (ringcentral_account_id,ringcentral_extension_id)"));await db.commit()
    original_execute=db.execute
    async def miss_preflight(statement,*args,**kwargs):
        # Emulate two callbacks both having observed no competing binding;
        # the database still has to reject the losing commit atomically.
        if "ringcentral_connections.employee_id !=" in str(statement):
            return SimpleNamespace(first=lambda:None)
        return await original_execute(statement,*args,**kwargs)
    monkeypatch.setattr(db,"execute",miss_preflight)
    monkeypatch.setattr(ringcentral,"verify_oauth_state",lambda _:12)
    async def exchange(_): return {"access_token":"new-token","expires_in":3600}
    async def profile(_): return {"id":"ext-1","account":{"id":"account-a"},"extensionNumber":"101"}
    async def subscribe(*args,**kwargs): return {"id":"subscription","status":"Active","expirationTime":"2027-01-01T00:00:00Z"}
    monkeypatch.setattr(ringcentral,"exchange_authorization_code",exchange)
    monkeypatch.setattr(ringcentral,"get_extension_profile",profile)
    monkeypatch.setattr(ringcentral,"create_telephony_subscription",subscribe)
    monkeypatch.setattr(ringcentral,"encrypt_token",lambda _:"synthetic-new-token")
    result=await ringcentral.ringcentral_callback(code="code",state="state",error=None,db=db)
    assert result.headers["location"].endswith("ringcentral=binding_conflict")
    rows=(await original_execute(select(RingCentralConnections).order_by(RingCentralConnections.employee_id))).scalars().all()
    assert [(row.ringcentral_account_id,row.ringcentral_extension_id,row.access_token_encrypted) for row in rows]==[
        ("account-a","ext-1","PRIVATE_ACCESS_TOKEN"),("account-b","ext-2","PRIVATE_ACCESS_TOKEN")]


def test_binding_migration_preflight_preserves_existing_conflicts_for_review():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).parents[1]/"alembic/versions/j65bc789b025_ringcentral_provider_identity.py"
    spec=importlib.util.spec_from_file_location("ringcentral_conflict_migration",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        RingCentralConnections.__table__.create(conn)
        RingCentralCallRecords.__table__.create(conn)
        conn.execute(sa.text("DROP INDEX uq_ringcentral_connection_provider_identity"))
        for employee_id in (11,12):
            conn.execute(RingCentralConnections.__table__.insert().values(employee_id=employee_id,ringcentral_account_id="a",ringcentral_extension_id="e",access_token_encrypted="keep-both",is_active=employee_id==11))
        before=sa.inspect(conn).get_indexes("ringcentral_connections")
        migration.op=Operations(MigrationContext.configure(conn))
        with pytest.raises(RuntimeError,match="duplicate account/extension ownership"):
            migration.upgrade()
        assert conn.execute(sa.text("SELECT employee_id FROM ringcentral_connections ORDER BY employee_id")).scalars().all()==[11,12]
        assert sa.inspect(conn).get_indexes("ringcentral_connections")==before
    engine.dispose()
