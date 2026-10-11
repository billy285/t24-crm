"""Standalone private API with a physically read-only CRM identity connection.

Run ``uvicorn services.private_workspace_app:app --host 127.0.0.1
--port 8001 --no-access-log`` from backend/. This service never imports the
CRM application, its lifespan, schema initializer, or financial background jobs.
"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.database import get_db
from models.employee_auth_sessions import EmployeeAuthSession
from models.employees import Employees
from routers.private_workspace import router
from routers.private_personal_finance import router as personal_finance_router
from services.emp_auth import validate_employee_auth_security_config
from services.private_workspace import close_private_workspace_storage, private_session_factory
from services.private_workspace_worker import create_business_reader


logger = logging.getLogger(__name__)
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


async def _verify_identity_reader(sessions):
    async with sessions() as business_db:
        # Schema verification is SELECT-only; missing auth tables are never repaired.
        await business_db.execute(select(Employees.id, Employees.user_id, Employees.name, Employees.role,
                                         Employees.phone, Employees.email, Employees.status,
                                         Employees.password, Employees.updated_at).limit(0))
        await business_db.execute(select(EmployeeAuthSession).limit(0))


def create_private_workspace_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        validate_employee_auth_security_config()
        engine = create_business_reader()
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await _verify_identity_reader(sessions)
            # Only the separate private metadata may create its own tables.
            await private_session_factory()
            application.state.private_business_sessions = sessions
            yield
        finally:
            application.state.private_business_sessions = None
            await close_private_workspace_storage()
            await engine.dispose()

    application = FastAPI(title="T24 Private Workspace", lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)

    async def business_identity_db(request: Request):
        sessions = getattr(request.app.state, "private_business_sessions", None)
        if sessions is None:
            raise StarletteHTTPException(status_code=503, detail="私人工作空间暂不可用")
        async with sessions() as business_db:
            yield business_db

    # Existing JWT, live employee and revocable-session dependencies still run.
    # Only their DB session is replaced by the read-only identity connection.
    application.dependency_overrides[get_db] = business_identity_db
    application.include_router(router)
    application.include_router(personal_finance_router)

    @application.middleware("http")
    async def no_store(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as exc:
            # Catch inside ServerErrorMiddleware: its Exception handler sends a
            # response and then re-raises, allowing Uvicorn to log raw secrets.
            logger.error("Private API request failed (%s)", type(exc).__name__)
            response = JSONResponse(status_code=500, content={"detail": "私人工作空间暂不可用"},
                                    headers=NO_STORE_HEADERS)
        response.headers.update(NO_STORE_HEADERS)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.exception_handler(StarletteHTTPException)
    async def http_failure(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                            headers={**(exc.headers or {}), **NO_STORE_HEADERS})

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not echo rejected private text, codes, state or credentials.
        return JSONResponse(status_code=422, content={"detail": "请求格式无效，请检查后重试"},
                            headers=NO_STORE_HEADERS)

    @application.get("/ready", include_in_schema=False)
    async def ready(request: Request):
        # This route is for the bound local service, not the public proxy path.
        sessions = getattr(request.app.state, "private_business_sessions", None)
        if sessions is None:
            raise StarletteHTTPException(status_code=503, detail="私人工作空间暂不可用")
        try:
            await _verify_identity_reader(sessions)
            private_sessions = await private_session_factory()
            async with private_sessions() as private_db:
                await private_db.execute(text("SELECT 1"))
        except Exception:
            raise StarletteHTTPException(status_code=503, detail="私人工作空间暂不可用") from None
        return {"ready": True}

    return application


app = create_private_workspace_app()
