# ============================================
# SECTION: Auth — register / login JWT
# ============================================

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from typing import Optional

from pydantic import BaseModel, Field

from .database import get_db

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

router = APIRouter(prefix="/auth", tags=["auth"])


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2)
    password: str = Field(..., min_length=4)
    full_name: Optional[str] = None
    phone: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None


class UserPublic(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: str = "user"
    is_active: bool = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _jwt_secret() -> str:
    secret = (os.environ.get("JWT_SECRET") or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT auth is not configured. Set JWT_SECRET in the environment.",
        )
    return secret


def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)


def hash_password(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    # Store an absolute UTC expiry so FastAPI and Streamlit clients can treat the token consistently.
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _jwt_secret(), algorithm=ALGORITHM)


def get_user_by_username(username: str):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _row_to_public(row: dict) -> UserPublic:
    # The project currently uses username as both login id and public email-style identifier.
    return UserPublic(
        id=row["id"],
        username=row["username"],
        email=row["username"],
        full_name=row["full_name"] if row.get("full_name") else None,
        phone=row["phone"] if row.get("phone") else None,
    )


@router.post("/register", response_model=Token)
def register(body: UserCreate):
    conn = get_db()
    try:
        hp = hash_password(body.password)
        conn.execute(
            "INSERT INTO users (username, hashed_password, full_name, phone) VALUES (?, ?, ?, ?)",
            (body.username, hp, body.full_name or None, body.phone or None),
        )
        conn.commit()
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            raise HTTPException(400, "Username taken")
        raise HTTPException(500, "db")
    finally:
        conn.close()
    token = create_access_token({"sub": body.username})
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_username(form.username)
    if not user or not verify_password(form.password, user["hashed_password"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = create_access_token({"sub": user["username"]})
    return Token(access_token=token)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def get_current_username_optional(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    if not token:
        return None
    return decode_token(token)


def get_current_username(token: Optional[str] = Depends(oauth2_scheme)) -> str:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    sub = decode_token(token)
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return sub


@router.get("/me", response_model=UserPublic)
def read_me(username: str = Depends(get_current_username)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return _row_to_public(user)


@router.patch("/me", response_model=UserPublic)
def update_me(body: UserUpdate, username: str = Depends(get_current_username)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    # Preserve existing profile values when a partial PATCH omits one of the optional fields.
    fn = body.full_name if body.full_name is not None else user.get("full_name")
    ph = body.phone if body.phone is not None else user.get("phone")
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET full_name = ?, phone = ? WHERE username = ?",
            (fn, ph, username),
        )
        conn.commit()
    finally:
        conn.close()
    return _row_to_public(get_user_by_username(username))
