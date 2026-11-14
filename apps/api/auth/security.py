"""Multi-user auth: argon2 password hashes, JWT session in an httpOnly cookie (or Bearer)."""

from __future__ import annotations

import os
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request

_ph = PasswordHasher()
COOKIE = "gigbid_session"
TTL = 60 * 60 * 24 * 7


def _secret() -> str:
    s = os.getenv("APP_SECRET_KEY")
    if not s or len(s) < 32:
        raise RuntimeError("APP_SECRET_KEY must be set (>= 32 chars)")
    return s


def hash_password(p: str) -> str:
    return _ph.hash(p)


def verify_password(h: str, p: str) -> bool:
    try:
        return _ph.verify(h, p)
    except VerifyMismatchError:
        return False


def issue(user_id: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + TTL}, _secret(), algorithm="HS256")


def decode(token: str) -> str:
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])["sub"]
    except jwt.PyJWTError as e:
        raise HTTPException(401, "invalid or expired session") from e


async def current_user_id(request: Request) -> str:
    token = request.cookies.get(COOKIE)
    auth = request.headers.get("authorization", "")
    if not token and auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        raise HTTPException(401, "not signed in")
    return decode(token)


CurrentUser = Depends(current_user_id)
