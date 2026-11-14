"""Settings: autonomy, budgets, saved searches, connected accounts, memory viewer, portfolio upload."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import and_, delete, insert, select, update

from agent import runtime
from agent.memory.store import delete_memory, list_memory
from apps.api import db, services
from apps.api.auth.security import CurrentUser
from apps.api.schemas import (
    MemoryItem,
    SavedSearchIn,
    SavedSearchOut,
    SettingsIn,
    SettingsOut,
    StatusOut,
)

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsOut)
async def get_settings(uid: str = CurrentUser) -> SettingsOut:
    s = await services.user_settings(uid)
    return SettingsOut(**{k: s.get(k) for k in SettingsOut.model_fields if s.get(k) is not None})


@router.patch("/settings", response_model=SettingsOut)
async def patch_settings(body: SettingsIn, uid: str = CurrentUser) -> SettingsOut:
    vals = body.model_dump(exclude_none=True)
    if vals:
        async with db.engine().begin() as c:
            await c.execute(update(db.user_settings).where(db.user_settings.c.user_id == uid).values(**vals))
    return await get_settings(uid)


@router.get("/searches", response_model=list[SavedSearchOut])
async def searches(uid: str = CurrentUser) -> list[SavedSearchOut]:
    async with db.engine().connect() as c:
        rows = (await c.execute(select(db.saved_searches).where(db.saved_searches.c.user_id == uid))).mappings().all()
    return [SavedSearchOut(**{k: r[k] for k in SavedSearchOut.model_fields}) for r in rows]


@router.post("/searches", response_model=SavedSearchOut)
async def add_search(body: SavedSearchIn, uid: str = CurrentUser) -> SavedSearchOut:
    sid = "ss_" + uuid.uuid4().hex[:10]
    async with db.engine().begin() as c:
        await c.execute(insert(db.saved_searches).values(id=sid, user_id=uid, **body.model_dump()))
    return SavedSearchOut(id=sid, **body.model_dump())


@router.delete("/searches/{sid}")
async def del_search(sid: str, uid: str = CurrentUser) -> dict:
    async with db.engine().begin() as c:
        await c.execute(delete(db.saved_searches).where(and_(db.saved_searches.c.id == sid, db.saved_searches.c.user_id == uid)))
    return {"ok": True}


@router.get("/memory", response_model=list[MemoryItem])
async def memory(uid: str = CurrentUser) -> list[MemoryItem]:
    """What GigBid has learned (promoted style rules + outcome insights)."""
    if runtime.store() is None:
        return []
    return [MemoryItem(**{k: m.get(k) for k in MemoryItem.model_fields}) for m in await list_memory(runtime.store(), uid)]


@router.delete("/memory/{kind}/{key}")
async def forget(kind: str, key: str, uid: str = CurrentUser) -> dict:
    if kind not in ("style", "outcome"):
        raise HTTPException(422, "kind must be style or outcome")
    await delete_memory(runtime.store(), uid, kind, key)
    return {"ok": True}


@router.post("/portfolio/upload")
async def upload(file: UploadFile = File(...), kind: str = "case_study", uid: str = CurrentUser) -> dict:
    """Add work in the UI -> incremental re-index of only the new item (B1)."""
    from rag.index.store import get_index
    from rag.ingest.loaders import load_uploaded

    if kind not in ("case_study", "cv", "review", "proposal", "upload"):
        raise HTTPException(422, "unknown kind")
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "file too large (5 MB max)")
    s = await services.user_settings(uid)
    chunks = load_uploaded(s["persona"], file.filename or "upload.md", data, kind)
    n = get_index().add_chunks(s["persona"], chunks)
    return {"indexed_chunks": n, "evidence_id": chunks[0].evidence_id if chunks else None}


@router.get("/status", response_model=StatusOut)
async def status(uid: str = CurrentUser) -> StatusOut:
    """Drives the 'marketplace unavailable' banner (degraded mode)."""
    from agent.mcp_client import Caller, Degraded, ToolBox

    s = await services.user_settings(uid)
    async with db.engine().connect() as c:
        queued = len((await c.execute(select(db.threads.c.thread_id).where(and_(
            db.threads.c.user_id == uid, db.threads.c.status == "queued_degraded")))).all())
    try:
        st = await ToolBox("scout", Caller(user=uid, persona=s["persona"])).call("marketplace_status", {})
        circuit = st.get("circuit", {})
        ok = circuit.get("state") != "open"
        return StatusOut(marketplace="ok" if ok else "unavailable", marketplace_mode=st.get("mode", "gigsim"),
                         circuit=circuit, queued_threads=queued,
                         message=None if ok else "Marketplace unavailable: work is queued and will resume automatically.")
    except (Degraded, Exception) as e:  # noqa: BLE001
        return StatusOut(marketplace="unavailable", marketplace_mode=s.get("marketplace_mode", "gigsim"), queued_threads=queued,
                         message=f"Marketplace unavailable ({type(e).__name__}): work is queued and will resume automatically.")
