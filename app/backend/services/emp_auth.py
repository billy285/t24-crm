import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import bcrypt
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# JWT config
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "crm-employee-auth-secret-key-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


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

    async def authenticate(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate an employee by email and password. Returns dict with employee data."""
        try:
            result = await self.db.execute(
                text("SELECT id, user_id, name, role, phone, email, status, password FROM employees WHERE email = :email"),
                {"email": email},
            )
            row = result.fetchone()

            if not row:
                logger.warning(f"Employee not found with email: {email}")
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
                logger.warning(f"Employee {email} has no password set")
                return None

            if not verify_password(password, emp_data["password"]):
                logger.warning(f"Invalid password for employee: {email}")
                return None

            return emp_data
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None

    async def get_employee_by_id(self, emp_id: int) -> Optional[Dict[str, Any]]:
        """Get employee by ID using raw SQL."""
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

    async def ensure_default_admin(self) -> None:
        """Ensure a default admin account exists."""
        try:
            result = await self.db.execute(
                text("SELECT id, password FROM employees WHERE email = 'admin@company.com'")
            )
            existing = result.fetchone()
            if not existing:
                hashed = hash_password("admin123")
                await self.db.execute(
                    text(
                        "INSERT INTO employees (user_id, name, role, email, password, status, created_at) "
                        "VALUES (:uid, :name, :role, :email, :pwd, :status, NOW())"
                    ),
                    {
                        "uid": "admin",
                        "name": "系统管理员",
                        "role": "admin",
                        "email": "admin@company.com",
                        "pwd": hashed,
                        "status": "active",
                    },
                )
                await self.db.commit()
                logger.info("Default admin account created: admin@company.com / admin123")
            elif not existing[1]:
                hashed = hash_password("admin123")
                await self.db.execute(
                    text("UPDATE employees SET password = :pwd WHERE email = 'admin@company.com'"),
                    {"pwd": hashed},
                )
                await self.db.commit()
                logger.info("Updated admin password")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating default admin: {e}")