from datetime import datetime, timedelta
from typing import Any, Optional
from jose import jwt

SECRET_KEY = "dev-secret-change-me"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30

def create_token(sub: str, minutes: int) -> str:
  expire = datetime.utcnow() + timedelta(minutes=minutes)
  payload: dict[str, Any] = {"sub": sub, "exp": expire}
  return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def create_access_token(sub: str) -> str:
  return create_token(sub, ACCESS_TOKEN_EXPIRE_MINUTES)

def create_refresh_token(sub: str) -> str:
  return create_token(sub, REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60)
