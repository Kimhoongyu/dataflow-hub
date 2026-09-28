from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import LoginSession, Membership, Tenant, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
password_hasher = PasswordHasher()
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))
COOKIE = "dataflow_session"
SESSION_SECONDS = 8 * 60 * 60
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        raise HTTPException(401, "로그인이 필요합니다.")
    session = db.get(LoginSession, hash_token(token))
    if not session or session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "로그인이 필요합니다.")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


def user_info(user: User, db: Session):
    tenants = db.scalars(select(Tenant).join(Membership).where(Membership.user_id == user.id).order_by(Tenant.name)).all()
    return {"id": str(user.id), "name": user.name, "email": user.email,
            "tenants": [{"id": str(t.id), "name": t.name} for t in tenants]}


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    try:
        password_hasher.verify(user.password_hash if user else DUMMY_HASH, data.password)
    except (VerificationError, InvalidHashError):
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
    if not user:
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
    old_token = request.cookies.get(COOKIE, "")
    db.execute(delete(LoginSession).where(LoginSession.token_hash == hash_token(old_token)))
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id, LoginSession.expires_at <= datetime.now(timezone.utc)))
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=hash_token(token), user_id=user.id,
                        expires_at=datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=COOKIE_SECURE, samesite="lax", path="/api")
    return user_info(user, db)


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)):
    db.execute(delete(LoginSession).where(LoginSession.token_hash == hash_token(request.cookies.get(COOKIE, ""))))
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/api", secure=COOKIE_SECURE, httponly=True, samesite="lax")
    return response


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_info(user, db)
