import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from jose import jwt

# Read secrets from env; fall back to a single SECRET_KEY if specific ones are not provided
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET") or os.environ.get("SECRET_KEY", "change-me-access")
REFRESH_TOKEN_SECRET = os.environ.get("REFRESH_TOKEN_SECRET") or os.environ.get("SECRET_KEY", "change-me-refresh")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

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
