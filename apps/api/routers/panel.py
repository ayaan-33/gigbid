"""Blind pairwise human panel (B4): classmates compare two anonymised proposals for the same job.
Public (no account): a voter nickname + the pair id are stored; sides are shuffled per pair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.api import db

router = APIRouter(prefix="/api/panel", tags=["panel"])
PAIRS = Path(__file__).resolve().parents[3] / "evals" / "datasets" / "panel_pairs.json"


def _pairs() -> list[dict]:
    return json.loads(PAIRS.read_text()) if PAIRS.exists() else []


def _flip(pair_id: str) -> bool:
    return int(hashlib.sha1(pair_id.encode()).hexdigest(), 16) % 2 == 1


class PanelPair(BaseModel):
    pair_id: str
    job_title: str
    job_description: str
    left: str
    right: str


class VoteIn(BaseModel):
    voter: str = Field(min_length=2, max_length=60)
    pair_id: str = Field(max_length=120)
    choice: Literal["left", "right", "tie"]


@router.get("/pairs", response_model=list[PanelPair])
async def pairs() -> list[PanelPair]:
    out = []
    for p in _pairs():
        a, b = p["a_text"], p["b_text"]
        left, right = (b, a) if _flip(p["pair_id"]) else (a, b)
        out.append(PanelPair(pair_id=p["pair_id"], job_title=p["job_title"], job_description=p["job_description"][:1200],
                             left=left, right=right))
    return out


@router.post("/vote")
async def vote(body: VoteIn) -> dict:
    p = next((x for x in _pairs() if x["pair_id"] == body.pair_id), None)
    if not p:
        raise HTTPException(404, "unknown pair")
    flipped = _flip(body.pair_id)
    choice = "tie" if body.choice == "tie" else ("A" if (body.choice == "left") != flipped else "B")
    async with db.engine().begin() as c:
        await c.execute(pg_insert(db.panel_votes).values(voter=body.voter.strip().lower(), pair_id=body.pair_id, choice=choice)
                        .on_conflict_do_update(index_elements=["voter", "pair_id"], set_={"choice": choice}))
    return {"ok": True}


@router.get("/results")
async def results() -> dict:
    async with db.engine().connect() as c:
        rows = (await c.execute(select(db.panel_votes.c.choice, func.count()).group_by(db.panel_votes.c.choice))).all()
        voters = (await c.execute(select(func.count(func.distinct(db.panel_votes.c.voter))))).scalar()
    counts = {k: v for k, v in rows}
    meta = {"A": (_pairs() or [{}])[0].get("a_label", "A"), "B": (_pairs() or [{}])[0].get("b_label", "B")}
    n = counts.get("A", 0) + counts.get("B", 0)
    from scipy.stats import binomtest

    p = float(binomtest(counts.get("A", 0), n, 0.5).pvalue) if n else None
    return {"labels": meta, "votes": counts, "voters": voters, "a_win_rate_excl_ties": round(counts.get("A", 0) / n, 4) if n else None,
            "sign_test_p": round(p, 4) if p is not None else None}
