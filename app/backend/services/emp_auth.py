import logging
import os
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import bcrypt
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import db_manager

logger = logging.getLogger(__name__)

# JWT config
DEFAULT_EMPLOYEE_JWT_SECRET = "crm-employee-auth-secret-key-2024"
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", DEFAULT_EMPLOYEE_JWT_SECRET)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
DEFAULT_ADMIN_EMAIL = "admin@company.com"
WEAK_DEFAULT_ADMIN_PASSWORD = "admin123"


def _is_truthy_env(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_production_env() -> bool:
    raw = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or os.getenv("ENV") or "").strip().lower()
    return raw in {"prod", "production"}


def _email_log_token(email: str) -> str:
    """Return a stable non-PII token for authentication audit logs."""
    normalized = (email or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def validate_employee_auth_security_config() -> None:
    """Validate security-sensitive employee auth environment settings."""
    if SECRET_KEY == DEFAULT_EMPLOYEE_JWT_SECRET:
        message = "JWT_SECRET_KEY is using the bundled development default; set a strong secret before production use"
        if _is_production_env():
            raise RuntimeError(message)
        logger.warning(message)


def _default_admin_seed_config() -> Dict[str, Any]:
    return {
        "email": (os.getenv("DEFAULT_ADMIN_EMAIL") or DEFAULT_ADMIN_EMAIL).strip().lower(),
        "password": os.getenv("DEFAULT_ADMIN_PASSWORD") or "",
        "name": (os.getenv("DEFAULT_ADMIN_NAME") or "系统管理员").strip() or "系统管理员",
        "allow_weak_password": _is_truthy_env("ALLOW_WEAK_DEFAULT_ADMIN"),
    }


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception as e:
        logger.error(f"Token decode error: {e}")
        return None


class EmpAuthService:
    """Employee authentication service using raw SQL for password field access."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_password_column(self) -> None:
        """Verify auth schema without attempting request-time repair."""
        try:
            await self.db.execute(text("SELECT password FROM employees LIMIT 1"))
        except Exception as exc:
            await self.db.rollback()
            raise RuntimeError(
                "employees.password column is unavailable; run the database migration before starting the service"
            ) from exc

    def _current_timestamp_sql(self) -> str:
        bind = self.db.get_bind()
        return "CURRENT_TIMESTAMP" if bind and bind.dialect.name == "sqlite" else "NOW()"

    async def authenticate(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate an employee by email and password. Returns dict with employee data."""
        await self.ensure_password_column()
        normalized_email = (email or "").strip().lower()
        email_token = _email_log_token(normalized_email)
        try:
            result = await self.db.execute(
                text("SELECT id, user_id, name, role, phone, email, status, password FROM employees WHERE email = :email"),
                {"email": normalized_email},
            )
            row = result.fetchone()

            if not row:
                logger.warning("Employee login account not found token=%s", email_token)
                return None

            emp_data = {
                "id": row[0],
                "user_id": row[1],
                "name": row[2],
                "role": row[3],
                "phone": row[4],
                "email": row[5],
                "status": row[6],
                "password": row[7],
            }

            if not emp_data["password"]:
                logger.warning("Employee login has no password token=%s", email_token)
                return None

            if not verify_password(password, emp_data["password"]):
                logger.warning("Invalid employee password token=%s", email_token)
                return None

            return emp_data
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None

    async def get_employee_by_id(self, emp_id: int) -> Optional[Dict[str, Any]]:
        """Get employee by ID using raw SQL."""
        await self.ensure_password_column()
        try:
            result = await self.db.execute(
                text("SELECT id, user_id, name, role, phone, email, status, password FROM employees WHERE id = :id"),
                {"id": emp_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "user_id": row[1],
                "name": row[2],
                "role": row[3],
                "phone": row[4],
                "email": row[5],
                "status": row[6],
                "password": row[7],
            }
        except Exception as e:
            logger.error(f"Error fetching employee {emp_id}: {e}")
            return None

    async def update_password(self, emp_id: int, new_password: str) -> bool:
        """Update employee password."""
        await self.ensure_password_column()
        try:
            hashed = hash_password(new_password)
            await self.db.execute(
                text("UPDATE employees SET password = :pwd WHERE id = :id"),
                {"pwd": hashed, "id": emp_id},
            )
            await self.db.commit()
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating password for employee {emp_id}: {e}")
            return False

    async def ensure_default_admin(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        name: Optional[str] = None,
        allow_weak_password: bool = False,
    ) -> None:
        """Ensure a configured admin account exists.

        This is intentionally opt-in and refuses the historical bundled weak
        password unless explicitly allowed for local development.
        """
        await self.ensure_password_column()
        seed = _default_admin_seed_config()
        admin_email = (email or seed["email"] or "").strip().lower()
        admin_password = password if password is not None else seed["password"]
        admin_name = (name or seed["name"] or "系统管理员").strip()
        allow_weak = allow_weak_password or bool(seed["allow_weak_password"])

        if not admin_email:
            logger.warning("Default admin initialization skipped: DEFAULT_ADMIN_EMAIL is empty")
            return
        if not admin_password:
            logger.info("Default admin initialization skipped: set DEFAULT_ADMIN_PASSWORD to enable it")
            return
        if admin_password == WEAK_DEFAULT_ADMIN_PASSWORD and not allow_weak:
            logger.error("Default admin initialization refused: admin123 is not allowed without ALLOW_WEAK_DEFAULT_ADMIN=true")
            return
        if len(admin_password) < 8:
            logger.error("Default admin initialization refused: DEFAULT_ADMIN_PASSWORD must be at least 8 characters")
            return

        try:
            now_sql = self._current_timestamp_sql()
            result = await self.db.execute(
                text("SELECT id, password FROM employees WHERE email = :email"),
                {"email": admin_email},
            )
            existing = result.fetchone()
            if not existing:
                hashed = hash_password(admin_password)
                await self.db.execute(
                    text(
                        "INSERT INTO employees (user_id, name, role, email, password, status, created_at) "
                        f"VALUES (:uid, :name, :role, :email, :pwd, :status, {now_sql})"
                    ),
                    {
                        "uid": f"admin:{admin_email}",
                        "name": admin_name,
                        "role": "admin",
                        "email": admin_email,
                        "pwd": hashed,
                        "status": "active",
                    },
                )
                await self.db.commit()
                logger.info("Default admin account created for %s", admin_email)
            elif not existing[1]:
                hashed = hash_password(admin_password)
                await self.db.execute(
                    text("UPDATE employees SET password = :pwd WHERE email = :email"),
                    {"pwd": hashed, "email": admin_email},
                )
                await self.db.commit()
                logger.info("Initialized missing password for configured admin %s", admin_email)
            else:
                logger.info("Configured admin %s already exists with a password; leaving it unchanged", admin_email)
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating default admin: {e}")


async def initialize_default_employee_admin() -> None:
    """Optionally ensure the employee-login admin account exists for local/dev usage."""
    validate_employee_auth_security_config()

    if not _is_truthy_env("ENABLE_DEFAULT_EMPLOYEE_ADMIN"):
        logger.info("Default employee admin initialization disabled; set ENABLE_DEFAULT_EMPLOYEE_ADMIN=true to enable")
        return
    if not db_manager.async_session_maker:
        logger.warning("Database session maker unavailable, skipping employee admin initialization")
        return

    async with db_manager.async_session_maker() as db:
        service = EmpAuthService(db)
        await service.ensure_default_admin()
