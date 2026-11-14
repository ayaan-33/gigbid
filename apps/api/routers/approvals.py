"""Proposal studio + approvals: read the pending interrupt payload (survives refresh/restart),
approve / edit / reject (resumes the paused LangGraph thread), regenerate one paragraph."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, desc, select

from agent import runtime
from apps.api import db, services
from apps.api.auth.security import CurrentUser
from apps.api.schemas import ApprovalIn, PendingApproval, RegenerateIn

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


async def _thread(uid: str, thread_id: str):
    async with db.engine().connect() as c:
        t = (await c.execute(select(db.threads).where(and_(db.threads.c.thread_id == thread_id,
                                                           db.threads.c.user_id == uid)))).mappings().first()
    if not t:
        raise HTTPException(404, "thread not found")
    return t


@router.get("", response_model=list[PendingApproval])
async def list_pending(uid: str = CurrentUser) -> list[PendingApproval]:
    async with db.engine().connect() as c:
        rows = (await c.execute(select(db.threads).where(and_(db.threads.c.user_id == uid,
                                                              db.threads.c.status == "awaiting_approval"))
                                .order_by(desc(db.threads.c.updated_at)))).mappings().all()
    out = []
    for t in rows:
        p = await runtime.pending(t["kind"], t["thread_id"])
        if p:
            out.append(PendingApproval(thread_id=t["thread_id"], kind=t["kind"], payload=p))
    return out


@router.get("/{thread_id}", response_model=PendingApproval)
async def get_pending(thread_id: str, uid: str = CurrentUser) -> PendingApproval:
    t = await _thread(uid, thread_id)
    p = await runtime.pending(t["kind"], thread_id)
    if not p:
        raise HTTPException(409, f"thread is not waiting for approval (status: {t['status']})")
    return PendingApproval(thread_id=thread_id, kind=t["kind"], payload=p)


@router.post("/{thread_id}")
async def decide(thread_id: str, body: ApprovalIn, uid: str = CurrentUser) -> dict:
    """Resume the interrupted graph with the human decision. Nothing is sent without this call."""
    t = await _thread(uid, thread_id)
    if not await runtime.pending(t["kind"], thread_id):
        raise HTTPException(409, "nothing to approve on this thread")
    if body.action == "edit" and not (body.edited_text and len(body.edited_text.strip()) >= 50):
        raise HTTPException(422, "edited text must be at least 50 characters")
    if body.action == "reject" and not body.reason:
        raise HTTPException(422, "please give a reason when rejecting")
    async with db.engine().begin() as c:
        from sqlalchemy import update

        await c.execute(update(db.threads).where(db.threads.c.thread_id == thread_id).values(status="resuming"))
    queued = await services.dispatch("resume_thread", user_id=uid, thread_id=thread_id,
                                     decision=body.model_dump(exclude_none=True))
    return {"queued": queued, "thread_id": thread_id}


@router.post("/{thread_id}/regenerate")
async def regenerate_paragraph(thread_id: str, body: RegenerateIn, uid: str = CurrentUser) -> dict:
    """Rewrite one paragraph with the Writer's rules + evidence; returns text for the editor
    (the user still has to approve the whole draft)."""
    from agent import llm
    from agent.prompts import load_prompt

    t = await _thread(uid, thread_id)
    p = await runtime.pending(t["kind"], thread_id)
    if not p or p.get("kind") != "proposal":
        raise HTTPException(409, "no proposal draft pending")
    paras = [x for x in p["draft"]["cover_letter"].split("\n\n") if x.strip()]
    if body.paragraph_index >= len(paras):
        raise HTTPException(422, "paragraph index out of range")
    ev = "\n".join(f"[{k}] {v[:600]}" for k, v in (p.get("evidence") or {}).items())
    pr = load_prompt("regenerate_paragraph")
    new = await llm.complete("writer", pr.text,
                             f"FULL DRAFT:\n{p['draft']['cover_letter']}\n\nPARAGRAPH TO REWRITE:\n{paras[body.paragraph_index]}\n\n"
                             f"INSTRUCTION: {body.instruction or 'make it more specific to this client'}\n\nEVIDENCE:\n{ev}",
                             max_tokens=400)
    new = new.split("</think>")[-1].strip()
    from agent.nodes.proposal import rule_compliance

    cleaned, violations, _ = rule_compliance(new)
    paras[body.paragraph_index] = cleaned
    return {"paragraph": cleaned, "full_text": "\n\n".join(paras), "compliance": [v.model_dump() for v in violations]}
