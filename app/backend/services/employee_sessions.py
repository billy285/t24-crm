"""Issue and validate persistent revocable employee sessions.

Legacy signed tokens have no session ID and are rejected after this security
upgrade. A fresh password login is the only way to create a session. Password
fingerprints also protect against password writes outside the auth service and
login/password-change races; password hashes never enter either token type.
"""
import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.employee_auth_sessions import EmployeeAuthSession


def session_enforcement_enabled() -> bool:
    environments = {(os.getenv(name) or "").strip().lower() for name in ("APP_ENV", "ENVIRONMENT", "ENV")}
    if environments & {"prod", "production"}:
        return True
    return (os.getenv("ENFORCE_EMPLOYEE_SESSIONS", "true").strip().lower() in {"1", "true", "yes", "on"})


def _credential_fingerprint(employee: dict) -> str:
    from services.emp_auth import SECRET_KEY

    material = f"{employee['id']}\0{employee.get('password') or ''}".encode("utf-8")
    return hmac.new(SECRET_KEY.encode("utf-8"), b"t24-employee-session-v1\0" + material, hashlib.sha256).hexdigest()


async def create_employee_session(db: AsyncSession, employee: dict) -> str:
    from services.security_tokens import REFRESH_TOKEN_EXPIRE_DAYS

    # The conditional write takes the same employee row lock as offboarding.
    # PostgreSQL rechecks this predicate after waiting for a concurrent update;
    # a SELECT followed by INSERT alone could issue an unseen session after the
    # administrator's revocation query. SQLite uses its write lock equivalently.
    stamp_comparison = (
        "updated_at IS :stamp" if db.get_bind().dialect.name == "sqlite"
        else "updated_at IS NOT DISTINCT FROM :stamp"
    )
    verified = await db.execute(text(
        "UPDATE employees SET id = id WHERE id = :id "
        "AND status IN ('active', 'probation') AND password = :password "
        f"AND {stamp_comparison} RETURNING id"
    ), {"id": employee["id"], "password": employee.get("password"), "stamp": employee.get("updated_at")})
    if verified.scalar_one_or_none() is None:
        await db.rollback()
        raise HTTPException(status_code=401, detail="账号状态已更新，请重新登录")
    now = int(time.time())
    session_id = secrets.token_urlsafe(32)
    db.add(EmployeeAuthSession(
        id=session_id,
        employee_id=employee["id"],
        credential_fingerprint=_credential_fingerprint(employee),
        created_at=now,
        expires_at=now + REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    ))
    await db.commit()
    return session_id


async def require_employee_session(
    db: AsyncSession, employee: dict, payload: dict, *, expected_token_type: str = "employee_access",
) -> str | None:
    session_id = payload.get("sid")
    if not session_enforcement_enabled() and not session_id:
        # Only isolated legacy test fixtures can opt out; production ignores it.
        return None
    if not isinstance(session_id, str) or not session_id or payload.get("token_type") != expected_token_type:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    session = await db.scalar(select(EmployeeAuthSession).where(
        EmployeeAuthSession.id == session_id,
        EmployeeAuthSession.employee_id == employee["id"],
    ))
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= int(time.time())
        or not hmac.compare_digest(session.credential_fingerprint, _credential_fingerprint(employee))
    ):
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return session_id


async def revoke_employee_sessions(db: AsyncSession, employee_id: int, session_id: str | None = None) -> None:
    # Flush employee status/password edits before revocation and serialize with
    # session issuance even when a caller will deactivate/delete the row later.
    # This lock never changes the employee's update generation.
    await db.flush()
    await db.execute(text("UPDATE employees SET id = id WHERE id = :id"), {"id": employee_id})
    query = update(EmployeeAuthSession).where(
        EmployeeAuthSession.employee_id == employee_id,
        EmployeeAuthSession.revoked_at.is_(None),
    )
    if session_id is not None:
        query = query.where(EmployeeAuthSession.id == session_id)
    await db.execute(query.values(revoked_at=int(time.time())))
