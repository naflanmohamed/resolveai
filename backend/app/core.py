import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Generator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
import hashlib
import hmac
import secrets


class Settings(BaseSettings):
    database_url: str = "sqlite:///./resolveai.db"
    jwt_secret: str = "local-development-secret-change-me-in-production"
    cors_origins: str = "http://localhost:5173"
    demo_mode: bool = True
    allow_registration: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache

def settings() -> Settings:
    return Settings()


class Base(DeclarativeBase):
    pass


url = settings().database_url
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
engine = create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 300_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 300_000)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int) -> str:
    return jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=12)}, settings().jwt_secret, algorithm="HS256")


bearer = HTTPBearer(auto_error=False)


def current_user(auth: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    from .models import User
    if not auth:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        payload = jwt.decode(auth.credentials, settings().jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return user


def admin_user(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user
