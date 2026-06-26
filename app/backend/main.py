import importlib
import logging
import os
import pkgutil
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from core.config import settings
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRouter

# MODULE_IMPORTS_START
from services.database import initialize_database, close_database
from services.mock_data import initialize_mock_data
from services.auth import initialize_admin_user
from services.emp_auth import initialize_default_employee_admin
from services.deal_payment_sync import backfill_missing_payments_from_deals
from core.database import db_manager
# MODULE_IMPORTS_END


def _is_truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_log_level(raw_level: str | None, default: int = logging.INFO) -> int:
    if not raw_level:
        return default

    level_name = raw_level.strip().upper()
    level = getattr(logging, level_name, None)
    return level if isinstance(level, int) else default


def setup_logging():
    """Configure the logging system."""
    if os.environ.get("IS_LAMBDA") == "true":
        return

    # Create the logs directory
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Generate log filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"{log_dir}/app_{timestamp}.log"

    # Configure log format
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = _resolve_log_level(os.environ.get("LOG_LEVEL"), logging.INFO)

    # Configure the root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            # File handler
            logging.FileHandler(log_file, encoding="utf-8"),
            # Console handler
            logging.StreamHandler(),
        ],
    )

    # Keep noisy infrastructure loggers quiet by default so customer/business
    # data is not sprayed into logs through SQL/debug traces.
    framework_level = logging.DEBUG if log_level <= logging.DEBUG else logging.INFO
    logging.getLogger("uvicorn").setLevel(framework_level)
    logging.getLogger("fastapi").setLevel(framework_level)
    logging.getLogger("aiosqlite").setLevel(logging.DEBUG if _is_truthy_env("ENABLE_SQL_DEBUG_LOGS") else logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if _is_truthy_env("ENABLE_SQL_DEBUG_LOGS") else logging.WARNING
    )
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)

    # Log configuration details
    logger = logging.getLogger(__name__)
    logger.info("=== Logging system initialized ===")
    logger.info(f"Log file: {log_file}")
    logger.info("Log level: %s", logging.getLevelName(log_level))
    if os.environ.get("LOG_LEVEL") and log_level == logging.INFO and os.environ["LOG_LEVEL"].strip().upper() != "INFO":
        logger.warning("Invalid LOG_LEVEL=%s; falling back to INFO", os.environ["LOG_LEVEL"])
    logger.info(f"Timestamp: {timestamp}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger(__name__)
    logger.info("=== Application startup initiated ===")

    # MODULE_STARTUP_START
    await initialize_database()
    await initialize_mock_data()  # re-enabled after user_id autofill
    async with db_manager.async_session_maker() as db:
        await backfill_missing_payments_from_deals(db)
    await initialize_default_employee_admin()
    await initialize_admin_user()
    # MODULE_STARTUP_END

    logger.info("=== Application startup completed successfully ===")
    yield
    # MODULE_SHUTDOWN_START
    await close_database()
    # MODULE_SHUTDOWN_END


app = FastAPI(
title="FastAPI Modular Template",
    description="A best-practice FastAPI template with modular architecture",
    version="1.0.0",
    lifespan=lifespan,
)

FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


# CORS: allow specific frontend origins via env, or the common local dev/preview origins by default.
origins_str = os.getenv("FRONTEND_ORIGINS")
allow_origins = (
    [o.strip() for o in origins_str.split(",") if o.strip()]
    if origins_str
    else [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# MODULE_MIDDLEWARE_START
# MODULE_MIDDLEWARE_END


# Auto-discover and include all routers from the local `routers` package
def include_routers_from_package(app: FastAPI, package_name: str = "routers") -> None:
    """Discover and include all APIRouter objects from a package.

    This scans the given package (and subpackages) for module-level variables that
    are instances of FastAPI's APIRouter. It supports "router", "admin_router" names.
    """

    logger = logging.getLogger(__name__)

    try:
        pkg = importlib.import_module(package_name)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Routers package '%s' not loaded: %s", package_name, exc)
        return

    discovered: int = 0
    for _finder, module_name, is_pkg in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        # Only import leaf modules; subpackages will be walked automatically
        if is_pkg:
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to import module '%s': %s", module_name, exc)
            continue

        # Check for router variable names: router and admin_router
        for attr_name in ("router", "admin_router"):
            if not hasattr(module, attr_name):
                continue

            attr = getattr(module, attr_name)

            if isinstance(attr, APIRouter):
                app.include_router(attr)
                discovered += 1
                logger.info("Included router: %s.%s", module_name, attr_name)
            elif isinstance(attr, (list, tuple)):
                for idx, item in enumerate(attr):
                    if isinstance(item, APIRouter):
                        app.include_router(item)
                        discovered += 1
                        logger.info("Included router from list: %s.%s[%d]", module_name, attr_name, idx)

    if discovered == 0:
        logger.debug("No routers discovered in package '%s'", package_name)


# Setup logging before router discovery
setup_logging()
include_routers_from_package(app, "routers")


# Add exception handler for all exceptions except HTTPException
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all exceptions except HTTPException

    - Dev environment: Return full stack trace and exception details
    - Prod environment: Return only "Internal server error"
    """
    # Re-raise HTTPException to let FastAPI handle it normally
    if isinstance(exc, HTTPException):
        raise exc

    logger = logging.getLogger(__name__)
    error_message = str(exc)
    error_type = type(exc).__name__

    # Log full error details regardless of environment
    logger.error(f"Exception: {error_type}: {error_message}\n{traceback.format_exc()}")

    # Determine if we're in dev environment
    is_dev = os.getenv("ENVIRONMENT", "prod").lower() == "dev"

    if is_dev:
        # Dev environment: return full stack trace and exception details
        error_detail = f"{error_type}: {error_message}\n{traceback.format_exc()}"
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": error_detail})
    else:
        # Prod environment: return only generic error message
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": "Internal Server Error"}
        )


def _frontend_index_response():
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "Frontend build is missing. Run `corepack pnpm build` in app/frontend to generate frontend/dist."
        },
    )


def _frontend_file_response(requested_path: str):
    safe_path = requested_path.lstrip("/")
    candidate = (FRONTEND_DIST_DIR / safe_path).resolve()

    try:
        candidate.relative_to(FRONTEND_DIST_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if candidate.is_file():
        return FileResponse(candidate)

    index_candidate = candidate / "index.html"
    if candidate.is_dir() and index_candidate.exists():
        return FileResponse(index_candidate)

    return None


@app.get("/", include_in_schema=False)
def root():
    return _frontend_index_response()


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/config")
def runtime_config(request: Request):
    """Expose the minimal runtime config required by the frontend."""
    request_origin = str(request.base_url).rstrip("/")
    configured_api_base = os.environ.get("VITE_API_BASE_URL") or os.environ.get("PYTHON_BACKEND_URL")

    # The production frontend is served by this same FastAPI app. Prefer the page origin so
    # browser requests stay same-origin and do not fail due to CORS or mixed-origin caching.
    if request_origin.startswith(("http://", "https://")):
        api_base_url = request_origin
    else:
        api_base_url = configured_api_base or settings.backend_url

    if not isinstance(api_base_url, str) or not api_base_url.startswith(("http://", "https://")):
        api_base_url = request_origin if request_origin.startswith(("http://", "https://")) else "http://127.0.0.1:8000"

    response = JSONResponse(content={"API_BASE_URL": api_base_url})
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_catch_all(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    file_response = _frontend_file_response(full_path)
    if file_response is not None:
        return file_response

    return _frontend_index_response()


def run_in_debug_mode(app: FastAPI):
    """Run the FastAPI app in debug mode with proper asyncio handling.

    This function handles the special case of running in a debugger (PyCharm, VS Code, etc.)
    where asyncio is patched, causing conflicts with uvicorn's asyncio_run.

    It loads environment variables from ../.env and uses asyncio.run() directly
    to avoid uvicorn's asyncio_run conflicts.

    Args:
        app: The FastAPI application instance
    """
    import asyncio
    from pathlib import Path

    import uvicorn
    from dotenv import load_dotenv

    # Load environment variables from ../.env in debug mode
    # If `LOCAL_DEBUG=true` is set, then MetaGPT's `ProjectBuilder.build()` will generate the `.env` file
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        logger = logging.getLogger(__name__)
        logger.info(f"Loaded environment variables from {env_path}")

    # In debug mode, use asyncio.run() directly to avoid uvicorn's asyncio_run conflicts
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(settings.port),
        log_level="info",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    import sys

    import uvicorn

    # Detect if running in debugger (PyCharm, VS Code, etc.)
    # Debuggers patch asyncio which conflicts with uvicorn's asyncio_run
    is_debugging = "pydevd" in sys.modules or (hasattr(sys, "gettrace") and sys.gettrace() is not None)

    if is_debugging:
        run_in_debug_mode(app)
    else:
        # Enable reload in normal mode
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=int(settings.port),
            reload_excludes=["**/*.py"],
        )
