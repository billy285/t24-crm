from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from routers import reports_export
from routers.ai_settings import AiSettingsUpdate, update_ai_settings
from routers.app_config import (
    DEFAULT_APP_CONFIGS,
    AppConfigUpdate,
    read_config_value,
    update_app_config,
)
from routers.finance_deduction import (
    MonthlyDeductionRateCreate,
    create_deduction,
    get_default_deduction,
)
from routers.media_accounts import can_view_media_account_password
from routers.reports_export import _get_default_deduction_rate, _get_monthly_deduction_map
from schemas.auth import UserResponse
from services.ai_config import DEFAULT_AI_CONFIG, read_saved_ai_config
from services.emp_auth import EmpAuthService


@pytest_asyncio.fixture
async def empty_schema_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.strip().upper())

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        commits: list[bool] = []

        @event.listens_for(session.sync_session, "after_commit")
        def record_commit(_session):
            commits.append(True)

        yield session, statements, commits, engine

    await engine.dispose()


def _user(role: str) -> UserResponse:
    return UserResponse(id=f"{role}-user", email=f"{role}@example.com", role=role)


def _assert_no_runtime_ddl(statements: list[str]) -> None:
    forbidden_prefixes = ("CREATE ", "ALTER ", "DROP ")
    assert not any(statement.startswith(forbidden_prefixes) for statement in statements)


@pytest.mark.asyncio
async def test_missing_app_settings_uses_safe_read_defaults_without_ddl(empty_schema_session):
    session, statements, commits, _engine = empty_schema_session

    app_config = await read_config_value(session, "security_config")
    ai_config, has_saved_ai_config, updated_at = await read_saved_ai_config(session)
    admin_can_view_password = await can_view_media_account_password(_user("admin"), session)
    sales_can_view_password = await can_view_media_account_password(_user("sales"), session)

    assert app_config.value == DEFAULT_APP_CONFIGS["security_config"]
    assert app_config.updated_at is None
    assert ai_config == DEFAULT_AI_CONFIG
    assert has_saved_ai_config is False
    assert updated_at is None
    assert admin_can_view_password is True
    assert sales_can_view_password is False
    assert commits == []
    _assert_no_runtime_ddl(statements)


@pytest.mark.asyncio
async def test_missing_app_settings_rejects_config_writes_with_503_without_ddl(empty_schema_session):
    session, statements, commits, _engine = empty_schema_session

    with pytest.raises(HTTPException) as app_config_error:
        await update_app_config(
            "security_config",
            AppConfigUpdate(value={"passwordViewRoles": ["admin"]}),
            _user("admin"),
            session,
        )
    with pytest.raises(HTTPException) as ai_config_error:
        await update_ai_settings(
            AiSettingsUpdate(enabled=False),
            _user("admin"),
            session,
        )

    assert app_config_error.value.status_code == 503
    assert ai_config_error.value.status_code == 503
    assert commits == []
    _assert_no_runtime_ddl(statements)


@pytest.mark.asyncio
async def test_missing_deduction_tables_return_503_for_reads_and_writes_without_ddl(empty_schema_session):
    session, statements, commits, engine = empty_schema_session

    with pytest.raises(HTTPException) as read_error:
        await get_default_deduction(session)
    with pytest.raises(HTTPException) as write_error:
        await create_deduction(
            MonthlyDeductionRateCreate(year_month="2026-08", rate=0.15),
            _user("admin"),
            session,
        )

    assert read_error.value.status_code == 503
    assert write_error.value.status_code == 503
    assert commits == []
    _assert_no_runtime_ddl(statements)
    async with engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync_connection: inspect(sync_connection).get_table_names())
    assert table_names == []


@pytest.mark.asyncio
async def test_missing_deduction_tables_make_finance_reports_503_without_ddl(empty_schema_session):
    session, statements, commits, _engine = empty_schema_session

    with pytest.raises(HTTPException) as default_error:
        await _get_default_deduction_rate(session)
    with pytest.raises(HTTPException) as monthly_error:
        await _get_monthly_deduction_map(session, "2026-01", "2026-08")

    assert default_error.value.status_code == 503
    assert monthly_error.value.status_code == 503
    assert commits == []
    _assert_no_runtime_ddl(statements)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "export_handler",
    (reports_export.export_profit_monthly_csv, reports_export.export_profit_monthly_xlsx),
)
async def test_finance_export_routes_preserve_schema_503(
    empty_schema_session,
    monkeypatch,
    export_handler,
):
    session, statements, commits, _engine = empty_schema_session
    monkeypatch.setattr(
        reports_export,
        "_aggregate_monthly",
        AsyncMock(return_value=({}, [])),
    )

    with pytest.raises(HTTPException) as error:
        await export_handler(None, None, None, None, None, _user("finance"), session)

    assert error.value.status_code == 503
    assert commits == []
    _assert_no_runtime_ddl(statements)


@pytest.mark.asyncio
async def test_employee_auth_never_repairs_schema_during_request(
    empty_schema_session,
    monkeypatch,
):
    session, statements, commits, engine = empty_schema_session
    monkeypatch.setenv("ALLOW_RUNTIME_SCHEMA_REPAIR", "true")

    with pytest.raises(RuntimeError, match="employees.password column is unavailable"):
        await EmpAuthService(session).ensure_password_column()

    assert commits == []
    _assert_no_runtime_ddl(statements)
    async with engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync_connection: inspect(sync_connection).get_table_names())
    assert table_names == []
