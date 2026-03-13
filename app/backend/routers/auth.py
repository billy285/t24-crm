from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel
from datetime import timedelta
from jose import jwt, JWTError
from core.security import create_access_token, create_refresh_token, SECRET_KEY, ALGORITHM, REFRESH_TOKEN_EXPIRE_DAYS

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

def verify_user(username: str, password: str) -> bool:
    # TODO: replace with real user lookup; for now accept any non-empty
    return bool(username and password)

@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, res: Response):
    if not verify_user(req.username, req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(req.username)
    if req.remember_me:
        refresh_token = create_refresh_token(req.username)
        max_age = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        res.set_cookie("refresh_token", refresh_token, httponly=True, samesite="lax", max_age=max_age, path="/")
    return {"access_token": access_token, "expires_in": 1800}

@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    new_access = create_access_token(sub)
    return {"access_token": new_access, "expires_in": 1800}

@router.post("/logout")
def logout(res: Response):
    res.set_cookie("refresh_token", "", max_age=0, httponly=True, samesite="lax", path="/")
    return {"ok": True}
