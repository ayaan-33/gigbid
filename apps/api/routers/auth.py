"""Sign-in, onboarding and the Upwork OAuth connection."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.api import db
from apps.api.auth.security import COOKIE, TTL, CurrentUser, hash_password, issue, verify_password
from apps.api.schemas import LoginIn, OnboardingIn, RegisterIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _cookie(resp: Response, token: str) -> None:
    import os

    resp.set_cookie(COOKIE, token, max_age=TTL, httponly=True, samesite="lax",
                    secure=os.getenv("APP_ENV") == "production", path="/")


async def _user(uid: str) -> UserOut:
    async with db.engine().connect() as c:
        u = (await c.execute(select(db.users).where(db.users.c.id == uid))).mappings().first()
    if not u:
        raise HTTPException(401, "unknown user")
    return UserOut(id=u["id"], email=u["email"], name=u["name"], persona=u["persona"], onboarded=u["onboarded"])


@router.post("/register", response_model=UserOut)
async def register(body: RegisterIn, resp: Response) -> UserOut:
    uid = "u_" + uuid.uuid4().hex[:12]
    async with db.engine().begin() as c:
        if (await c.execute(select(db.users.c.id).where(db.users.c.email == body.email.lower()))).first():
            raise HTTPException(409, "email already registered")
        await c.execute(insert(db.users).values(id=uid, email=body.email.lower(), password_hash=hash_password(body.password),
                                                name=body.name, persona="ai_ml_engineer", onboarded=False))
        await c.execute(insert(db.user_settings).values(user_id=uid))
    _cookie(resp, issue(uid))
    return await _user(uid)


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, resp: Response) -> UserOut:
    async with db.engine().connect() as c:
        u = (await c.execute(select(db.users).where(db.users.c.email == body.email.lower()))).mappings().first()
    if not u or not verify_password(u["password_hash"], body.password):
        raise HTTPException(401, "wrong email or password")
    _cookie(resp, issue(u["id"]))
    return await _user(u["id"])


@router.post("/logout")
async def logout(resp: Response) -> dict:
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(uid: str = CurrentUser) -> UserOut:
    return await _user(uid)


@router.post("/onboarding", response_model=UserOut)
async def onboarding(body: OnboardingIn, uid: str = CurrentUser) -> UserOut:
    async with db.engine().begin() as c:
        await c.execute(update(db.users).where(db.users.c.id == uid).values(persona=body.persona, onboarded=True))
        await c.execute(pg_insert(db.user_settings).values(user_id=uid).on_conflict_do_nothing())
        await c.execute(update(db.user_settings).where(db.user_settings.c.user_id == uid).values(
            hourly_rate=body.hourly_rate, fixed_floor=body.fixed_floor, weekly_connects_budget=body.weekly_connects_budget,
            marketplace_mode=body.marketplace_mode))
        if body.saved_search is not None:
            await c.execute(insert(db.saved_searches).values(id="ss_" + uuid.uuid4().hex[:10], user_id=uid,
                                                             name=body.saved_search or "All matching jobs",
                                                             query=body.saved_search or "", category=body.category,
                                                             skills=[], interval_minutes=30, enabled=True))
    return await _user(uid)


# --------------------------------------------------------------------------- Upwork OAuth (live mode)


@router.post("/upwork/start")
async def upwork_start(uid: str = CurrentUser) -> dict:
    """Begin the OAuth 2.1 flow; returns the Upwork authorisation URL for the browser."""
    import asyncio

    from mcp_servers.marketplace.adapters.upwork_live import OAUTH_BROKER, UpworkLiveAdapter

    adapter = UpworkLiveAdapter(uid)
    task = asyncio.create_task(adapter.connect())
    _pending[uid] = task
    try:
        url = await OAUTH_BROKER.auth_url(uid, wait_s=20)
    except TimeoutError:
        if task.done() and not task.exception():
            return {"connected": True, "tools": task.result()}
        raise HTTPException(502, "Upwork did not return an authorisation URL") from None
    return {"authorization_url": url}


_pending: dict = {}


@router.get("/upwork/callback")
async def upwork_callback(code: str, state: str | None = None, uid: str = CurrentUser) -> Response:
    from mcp_servers.marketplace.adapters.upwork_live import OAUTH_BROKER

    OAUTH_BROKER.complete(uid, code, state)
    task = _pending.pop(uid, None)
    tools: list[str] = []
    if task:
        try:
            import asyncio

            tools = await asyncio.wait_for(task, 30)
        except Exception as e:  # noqa: BLE001
            return Response(f"Upwork connection failed: {type(e).__name__}", status_code=502)
    async with db.engine().begin() as c:
        await c.execute(update(db.user_settings).where(db.user_settings.c.user_id == uid).values(marketplace_mode="upwork_live"))
    import os

    web = os.getenv("PUBLIC_WEB_URL", "http://localhost:3000")
    return Response(status_code=303, headers={"Location": f"{web}/settings?upwork=connected&tools={len(tools)}"})


@router.post("/upwork/disconnect")
async def upwork_disconnect(uid: str = CurrentUser) -> dict:
    from mcp_servers.marketplace.adapters.upwork_live import EncryptedTokenStorage

    EncryptedTokenStorage(uid).disconnect()
    async with db.engine().begin() as c:
        await c.execute(update(db.user_settings).where(db.user_settings.c.user_id == uid).values(marketplace_mode="gigsim"))
    return {"ok": True}


@router.get("/upwork/status")
async def upwork_status(uid: str = CurrentUser) -> dict:
    from mcp_servers.marketplace.adapters.upwork_live import EncryptedTokenStorage

    try:
        return {"connected": EncryptedTokenStorage(uid).connected()}
    except RuntimeError:
        return {"connected": False}
