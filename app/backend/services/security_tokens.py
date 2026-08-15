import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from jose import jwt

# Legacy access-token helpers are kept separate from employee authentication.
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET") or os.environ.get("SECRET_KEY", "change-me-access")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

_EPHEMERAL_REFRESH_SECRET_ENV = "T24_EPHEMERAL_REFRESH_TOKEN_SECRET"
_KNOWN_WEAK_SECRETS = {
    "change-me-refresh",
    "change-me-access",
    "crm-employee-auth-secret-key-2024",
    "dev-secret-change-me",
    "replace-with-a-long-random-secret",
}


def _is_production_env() -> bool:
    value = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "").strip().lower()
    return value in {"prod", "production"}


def _require_strong_secret(value: str, variable_name: str) -> str:
    secret = value.strip()
    if len(secret) < 32 or secret.lower() in _KNOWN_WEAK_SECRETS or "replace-with" in secret.lower():
        raise RuntimeError(f"{variable_name} must be a non-placeholder secret of at least 32 characters")
    return secret


def _resolve_refresh_token_secret() -> str:
    """Resolve a non-public refresh secret and fail closed in production.

    A dedicated REFRESH_TOKEN_SECRET takes priority. Otherwise we derive a
    domain-separated key from the already-required employee JWT secret. Local
    development without either secret receives a process-local random key,
    never a bundled public default.
    """
    configured = (os.environ.get("REFRESH_TOKEN_SECRET") or "").strip()
    if configured:
        return _require_strong_secret(configured, "REFRESH_TOKEN_SECRET")

    employee_jwt_secret = (os.environ.get("JWT_SECRET_KEY") or "").strip()
    if employee_jwt_secret:
        strong_jwt_secret = _require_strong_secret(employee_jwt_secret, "JWT_SECRET_KEY")
        return hashlib.sha256(b"t24-crm-refresh-v1\0" + strong_jwt_secret.encode("utf-8")).hexdigest()

    if _is_production_env():
        raise RuntimeError("Production refresh tokens require REFRESH_TOKEN_SECRET or JWT_SECRET_KEY")

    ephemeral = (os.environ.get(_EPHEMERAL_REFRESH_SECRET_ENV) or "").strip()
    if not ephemeral:
        ephemeral = secrets.token_urlsafe(48)
        os.environ[_EPHEMERAL_REFRESH_SECRET_ENV] = ephemeral
    return ephemeral


REFRESH_TOKEN_SECRET = _resolve_refresh_token_secret()

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def create_access_token(subject: str, extra_claims: Dict[str, Any] | None = None, expires_minutes: int | None = None) -> str:
    to_encode: Dict[str, Any] = {"sub": subject, "iat": int(_utcnow().timestamp())}
    if extra_claims:
        to_encode.update(extra_claims)
    expire = _utcnow() + timedelta(minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, ACCESS_TOKEN_SECRET, algorithm=ALGORITHM)

def create_refresh_token(subject: str, extra_claims: Dict[str, Any] | None = None, expires_days: int | None = None) -> str:
    to_encode: Dict[str, Any] = {"sub": subject, "iat": int(_utcnow().timestamp())}
    if extra_claims:
        to_encode.update(extra_claims)
    expire = _utcnow() + timedelta(days=expires_days or REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, REFRESH_TOKEN_SECRET, algorithm=ALGORITHM)

def verify_refresh_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, REFRESH_TOKEN_SECRET, algorithms=[ALGORITHM])
