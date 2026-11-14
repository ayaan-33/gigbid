"""GigSim: a freelance-marketplace simulator (REST). Safe, repeatable stand-in for a real
platform. Jobs are released over a simulated clock, clients with hidden preferences grade
submitted proposals, conversations progress, and the platform misbehaves realistically
(rate limits, 5xx, post-commit failures that only idempotency keys survive).

Run:  uvicorn gigsim.app:app --port 8081
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import statistics
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gigsim import client_sim
from gigsim.db import DB
from gigsim.policy import POLICIES, connects_cost_for, validate_proposal_text

HERE = Path(__file__).parent
DB_PATH = Path(os.getenv("GIGSIM_DB", HERE.parent / ".cache" / "gigsim.sqlite"))
SEED_DIR = Path(os.getenv("GIGSIM_SEED_DIR", HERE.parent / "data" / "gigsim_seed"))
API_SECRET = os.getenv("GIGSIM_API_TOKEN", "dev-gigsim-token")
ADMIN_TOKEN = os.getenv("GIGSIM_ADMIN_TOKEN", "dev-gigsim-admin")
RATE_LIMIT = int(os.getenv("GIGSIM_RATE_LIMIT_PER_MIN", "30"))
ERROR_RATE = float(os.getenv("GIGSIM_ERROR_RATE", "0.03"))
POST_COMMIT_ERROR_RATE = float(os.getenv("GIGSIM_POST_COMMIT_ERROR_RATE", "0.02"))
SIM_SPEED = float(os.getenv("GIGSIM_SPEED", "60"))  # sim minutes per real minute
GRADER = os.getenv("GIGSIM_GRADER", "llm")  # llm | heuristic


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    from gigsim.seed import ensure_seeded

    ensure_seeded(db, SEED_DIR, API_SECRET)
    task = None
    if os.getenv("GIGSIM_DISABLE_LOOP") != "1":
        task = asyncio.create_task(_loop())
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    lifespan=lifespan,
    title="GigSim",
    version="1.0.0",
    description="Freelance marketplace simulator for GigBid development and grading.",
)
db = DB(DB_PATH)
_rng = random.Random(int(os.getenv("GIGSIM_FAULT_SEED", "7")))

# --------------------------------------------------------------------------- clock


def sim_now() -> float:
    """Simulated epoch seconds."""
    start = db.get_sim("real_start")
    if start is None:
        start = time.time()
        db.set_sim("real_start", start)
    epoch = db.get_sim("sim_epoch", start)
    offset = db.get_sim("offset_s", 0.0)
    return epoch + (time.time() - start) * SIM_SPEED + offset


# --------------------------------------------------------------------------- auth + limits

_buckets: dict[str, deque[float]] = defaultdict(deque)


def account(authorization: str = Header(default="")) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    row = db.one("select * from accounts where token=?", (token,))
    if not row:
        raise HTTPException(401, "invalid token")
    q = _buckets[token]
    now = time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        retry = max(1, int(60 - (now - q[0])) + 1)
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(retry)})
    q.append(now)
    return dict(row)


def admin(x_admin_token: str = Header(default="")) -> None:
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "admin token required")


@app.middleware("http")
async def chaos(request: Request, call_next):
    path = request.url.path
    if path.startswith("/v1") and ERROR_RATE > 0 and _rng.random() < ERROR_RATE:
        return JSONResponse({"detail": "simulated upstream failure"}, status_code=503)
    if path.startswith("/v1"):
        await asyncio.sleep(_rng.uniform(0.01, 0.12))
    return await call_next(request)


def _post_commit_fault() -> None:
    """After a write committed, sometimes pretend the connection dropped."""
    if POST_COMMIT_ERROR_RATE > 0 and _rng.random() < POST_COMMIT_ERROR_RATE:
        raise HTTPException(
            502, "connection reset after commit (retry with the same idempotency key)"
        )


# --------------------------------------------------------------------------- helpers


def _job_public(row) -> dict[str, Any]:
    d = json.loads(row["data"])
    d.update(
        id=row["id"],
        client_id=row["client_id"],
        status=row["status"],
        category=row["category"],
        posted_at=row["release_at"],
        proposals_count=row["proposals_count"],
    )
    d["connects_cost"] = connects_cost_for(d, current_policy())
    d.pop("gold", None)
    return d


def current_policy() -> dict[str, Any]:
    return POLICIES[int(db.get_sim("policy_version", 1))]


def _event(
    fid: str, etype: str, ref: str, data: dict | None = None, at: float | None = None
) -> None:
    db.x(
        "insert into events(freelancer_id,type,ref,data,at) values (?,?,?,?,?)",
        (fid, etype, ref, json.dumps(data or {}), at or sim_now()),
    )


def _idem_get(fid: str, key: str, endpoint: str) -> dict | None:
    row = db.one("select * from idempotency where key=? and freelancer_id=?", (key, fid))
    if not row:
        return None
    if row["endpoint"] != endpoint:
        raise HTTPException(409, "idempotency key reused for a different operation")
    return json.loads(row["response"])


def _idem_put(fid: str, key: str, endpoint: str, resp: dict) -> None:
    db.x(
        "insert into idempotency values (?,?,?,?,?)",
        (key, fid, endpoint, json.dumps(resp), time.time()),
    )


# --------------------------------------------------------------------------- schemas


class ScreeningAnswerIn(BaseModel):
    question: str = Field(max_length=1000)
    answer: str = Field(max_length=3000)


class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=50, max_length=5000)
    bid_amount: float = Field(gt=0, le=1_000_000)
    bid_unit: Literal["fixed", "hourly"] = "fixed"
    screening_answers: list[ScreeningAnswerIn] = Field(default_factory=list, max_length=10)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SubmitIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    dry_run: bool = False


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    idempotency_key: str = Field(min_length=8, max_length=128)


# --------------------------------------------------------------------------- read API


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "sim_now": sim_now(), "policy_version": current_policy()["version"]}


@app.get("/v1/jobs")
def search_jobs(
    acct: dict = Depends(account),
    q: str | None = None,
    category: str | None = None,
    skills: str | None = Query(None, description="comma separated"),
    min_budget: float | None = None,
    posted_after: float | None = None,
    limit: int = Query(20, ge=1, le=50),
    cursor: int = Query(0, ge=0),
) -> dict[str, Any]:
    now = sim_now()
    sql = "select * from jobs where release_at<=? and status='open'"
    args: list[Any] = [now]
    if category:
        sql += " and category=?"
        args.append(category)
    if posted_after:
        sql += " and release_at>?"
        args.append(posted_after)
    rows = db.q(sql + " order by release_at desc", args)
    items = [_job_public(r) for r in rows]
    if q:
        terms = [t.lower() for t in q.split() if len(t) > 1]

        def score(j: dict[str, Any]) -> float:
            title = j["title"].lower()
            body = (j["description"] + " " + " ".join(j.get("skills", []))).lower()
            hits = sum(1 for t in terms if t in title or t in body)
            if hits < max(1, (len(terms) + 1) // 2):  # most query terms must match
                return 0.0
            return hits + 0.5 * sum(1 for t in terms if t in title) + (1.0 if q.lower() in title + " " + body else 0.0)

        scored = [(score(j), j) for j in items]
        items = [j for s, j in sorted(scored, key=lambda t: (-t[0], -t[1]["posted_at"])) if s > 0]
    if skills:
        want = {s.strip().lower() for s in skills.split(",") if s.strip()}
        items = [j for j in items if want & {s.lower() for s in j.get("skills", [])}]
    if min_budget:
        items = [j for j in items if (j.get("budget") or {}).get("max", 0) >= min_budget]
    page = items[cursor : cursor + limit]
    nxt = cursor + limit if cursor + limit < len(items) else None
    return {"items": page, "next_cursor": nxt, "total": len(items), "sim_now": now}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, acct: dict = Depends(account)) -> dict[str, Any]:
    row = db.one("select * from jobs where id=? and release_at<=?", (job_id, sim_now()))
    if not row:
        raise HTTPException(404, "job not found")
    return _job_public(row)


@app.get("/v1/clients/{client_id}")
def get_client(client_id: str, acct: dict = Depends(account)) -> dict[str, Any]:
    row = db.one("select * from clients where id=?", (client_id,))
    if not row:
        raise HTTPException(404, "client not found")
    d = json.loads(row["data"])
    d["id"] = client_id
    return d


@app.get("/v1/connects")
def connects(acct: dict = Depends(account)) -> dict[str, Any]:
    ledger = db.q(
        "select delta,reason,ref,at from connects_ledger where freelancer_id=? order by id desc limit 50",
        (acct["freelancer_id"],),
    )
    return {"balance": acct["connects"], "ledger": [dict(r) for r in ledger]}


@app.get("/v1/proposals")
def list_proposals(acct: dict = Depends(account), status: str | None = None) -> dict[str, Any]:
    sql, args = "select * from proposals where freelancer_id=?", [acct["freelancer_id"]]
    if status:
        sql += " and status=?"
        args.append(status)
    rows = db.q(sql + " order by created_at desc", args)
    return {"items": [_proposal_public(r) for r in rows]}


@app.get("/v1/proposals/{pid}")
def get_proposal(pid: str, acct: dict = Depends(account)) -> dict[str, Any]:
    row = db.one(
        "select * from proposals where id=? and freelancer_id=?", (pid, acct["freelancer_id"])
    )
    if not row:
        raise HTTPException(404, "proposal not found")
    return _proposal_public(row)


def _proposal_public(row) -> dict[str, Any]:
    d = json.loads(row["data"])
    d.update(
        id=row["id"],
        job_id=row["job_id"],
        status=row["status"],
        submitted_at=row["submitted_at"],
        connects_spent=row["connects_spent"],
    )
    d.pop("_grade", None)
    return d


@app.get("/v1/conversations")
def list_conversations(acct: dict = Depends(account)) -> dict[str, Any]:
    rows = db.q("select * from conversations where freelancer_id=?", (acct["freelancer_id"],))
    out = []
    for r in rows:
        last = db.one(
            "select * from messages where conversation_id=? order by at desc limit 1", (r["id"],)
        )
        out.append(
            {
                "id": r["id"],
                "client_id": r["client_id"],
                "job_id": r["job_id"],
                "proposal_id": r["proposal_id"],
                "state": r["state"],
                "last_message": dict(last) if last else None,
            }
        )
    return {"items": out}


@app.get("/v1/conversations/{cid}/messages")
def list_messages(cid: str, acct: dict = Depends(account)) -> dict[str, Any]:
    conv = db.one(
        "select * from conversations where id=? and freelancer_id=?", (cid, acct["freelancer_id"])
    )
    if not conv:
        raise HTTPException(404, "conversation not found")
    rows = db.q("select * from messages where conversation_id=? order by at", (cid,))
    return {"conversation_id": cid, "state": conv["state"], "items": [dict(r) for r in rows]}


@app.get("/v1/events")
def events(
    acct: dict = Depends(account), since_id: int = 0, limit: int = Query(100, le=500)
) -> dict[str, Any]:
    rows = db.q(
        "select * from events where freelancer_id=? and id>? and at<=? order by id limit ?",
        (acct["freelancer_id"], since_id, sim_now(), limit),
    )
    return {"items": [{**dict(r), "data": json.loads(r["data"] or "{}")} for r in rows]}


@app.get("/v1/policy")
def policy() -> dict[str, Any]:
    return current_policy()


@app.get("/v1/market/stats")
def market_stats(
    acct: dict = Depends(account),
    category: str | None = None,
    budget_type: Literal["fixed", "hourly"] = "fixed",
) -> dict[str, Any]:
    rows = db.q(
        "select data from historical_jobs" + (" where category=?" if category else ""),
        (category,) if category else (),
    )
    prices = []
    for r in rows:
        d = json.loads(r["data"])
        if d.get("budget_type") == budget_type and d.get("final_price"):
            prices.append(float(d["final_price"]))
    if len(prices) < 5:
        return {"category": category, "budget_type": budget_type, "n": len(prices)}
    qs = statistics.quantiles(prices, n=20)
    return {
        "category": category,
        "budget_type": budget_type,
        "n": len(prices),
        "p10": qs[1],
        "p25": qs[4],
        "median": statistics.median(prices),
        "p75": qs[14],
        "p90": qs[17],
    }


@app.get("/v1/market/historical")
def historical(
    acct: dict = Depends(account),
    category: str | None = None,
    limit: int = Query(200, le=2000),
    cursor: int = 0,
) -> dict[str, Any]:
    sql = (
        "select id,data from historical_jobs"
        + (" where category=?" if category else "")
        + " order by id limit ? offset ?"
    )
    args = ((category,) if category else ()) + (limit, cursor)
    rows = db.q(sql, args)
    return {"items": [{"id": r["id"], **json.loads(r["data"])} for r in rows]}


# --------------------------------------------------------------------------- write API


@app.post("/v1/proposals", status_code=201)
def create_proposal_draft(body: ProposalIn, acct: dict = Depends(account)) -> dict[str, Any]:
    fid = acct["freelancer_id"]
    if (prev := _idem_get(fid, body.idempotency_key, "create_proposal")) is not None:
        return prev
    job = db.one("select * from jobs where id=? and release_at<=?", (body.job_id, sim_now()))
    if not job:
        raise HTTPException(404, "job not found")
    pid = "prop_" + uuid.uuid4().hex[:12]
    data = body.model_dump(exclude={"idempotency_key"})
    with db.tx():
        db.conn.execute(
            "insert into proposals(id,freelancer_id,job_id,status,data,created_at) values (?,?,?,?,?,?)",
            (pid, fid, body.job_id, "draft", json.dumps(data), sim_now()),
        )
        resp = {"id": pid, "status": "draft", "job_id": body.job_id}
        db.conn.execute(
            "insert into idempotency values (?,?,?,?,?)",
            (body.idempotency_key, fid, "create_proposal", json.dumps(resp), time.time()),
        )
    _post_commit_fault()
    return resp


@app.post("/v1/proposals/{pid}/submit")
def submit_proposal(pid: str, body: SubmitIn, acct: dict = Depends(account)) -> dict[str, Any]:
    fid = acct["freelancer_id"]
    if (
        not body.dry_run
        and (prev := _idem_get(fid, body.idempotency_key, "submit_proposal")) is not None
    ):
        return prev
    prop = db.one("select * from proposals where id=? and freelancer_id=?", (pid, fid))
    if not prop:
        raise HTTPException(404, "proposal not found")
    job = db.one("select * from jobs where id=?", (prop["job_id"],))
    pub = _job_public(job)
    pol = current_policy()
    cost = pub["connects_cost"]
    data = json.loads(prop["data"])
    problems = validate_proposal_text(data["cover_letter"], pol)
    preview = {
        "proposal_id": pid,
        "job_id": prop["job_id"],
        "connects_cost": cost,
        "balance_before": acct["connects"],
        "balance_after": acct["connects"] - cost,
        "policy_version": pol["version"],
        "policy_problems": problems,
        "payload": data,
    }
    if body.dry_run:
        return {"dry_run": True, **preview}
    if prop["status"] != "draft":
        raise HTTPException(409, f"proposal already {prop['status']}")
    if problems:
        raise HTTPException(422, {"error": "policy_violation", "problems": problems})
    if acct["connects"] < cost:
        raise HTTPException(402, "insufficient connects")
    if job["status"] != "open":
        raise HTTPException(409, "job is closed")
    now = sim_now()
    decide_at = now + client_sim.rng_for(pid).uniform(20, 240) * 60
    resp = {
        "id": pid,
        "status": "submitted",
        "connects_spent": cost,
        "balance_after": acct["connects"] - cost,
    }
    with db.tx():
        db.conn.execute(
            "update accounts set connects=connects-? where token=?", (cost, acct["token"])
        )
        db.conn.execute(
            "insert into connects_ledger(freelancer_id,delta,reason,ref,at) values (?,?,?,?,?)",
            (fid, -cost, "proposal_submitted", pid, now),
        )
        db.conn.execute(
            "update proposals set status='submitted', submitted_at=?, decide_at=?, connects_spent=? where id=?",
            (now, decide_at, cost, pid),
        )
        db.conn.execute(
            "update jobs set proposals_count=proposals_count+1 where id=?", (prop["job_id"],)
        )
        db.conn.execute(
            "insert into idempotency values (?,?,?,?,?)",
            (body.idempotency_key, fid, "submit_proposal", json.dumps(resp), time.time()),
        )
        db.conn.execute(
            "insert into events(freelancer_id,type,ref,data,at) values (?,?,?,?,?)",
            (fid, "submitted", pid, json.dumps({"job_id": prop["job_id"]}), now),
        )
    _post_commit_fault()
    return resp


@app.post("/v1/conversations/{cid}/messages", status_code=201)
def send_message(cid: str, body: MessageIn, acct: dict = Depends(account)) -> dict[str, Any]:
    fid = acct["freelancer_id"]
    if (prev := _idem_get(fid, body.idempotency_key, "send_message")) is not None:
        return prev
    conv = db.one("select * from conversations where id=? and freelancer_id=?", (cid, fid))
    if not conv:
        raise HTTPException(404, "conversation not found")
    problems = validate_proposal_text(body.text, current_policy(), message=True)
    if problems:
        raise HTTPException(422, {"error": "policy_violation", "problems": problems})
    mid = "msg_" + uuid.uuid4().hex[:12]
    now = sim_now()
    resp = {"id": mid, "conversation_id": cid, "status": "sent"}
    with db.tx():
        db.conn.execute(
            "insert into messages values (?,?,?,?,?)", (mid, cid, "freelancer", body.text, now)
        )
        db.conn.execute(
            "insert into idempotency values (?,?,?,?,?)",
            (body.idempotency_key, fid, "send_message", json.dumps(resp), time.time()),
        )
    # the client answers on the next scripted step
    db.set_sim(f"pending_reply:{cid}", now + client_sim.rng_for(mid).uniform(15, 120) * 60)
    _post_commit_fault()
    return resp


# --------------------------------------------------------------------------- simulation loop


async def _process_decisions() -> int:
    now = sim_now()
    rows = db.q("select * from proposals where status='submitted' and decide_at<=?", (now,))
    for p in rows:
        job = db.one("select * from jobs where id=?", (p["job_id"],))
        client = db.one("select * from clients where id=?", (job["client_id"],))
        hidden = json.loads(client["hidden"])
        data = json.loads(p["data"])
        jd = json.loads(job["data"])
        if GRADER == "llm":
            grade = await client_sim.llm_grade(data, jd, hidden)
        else:
            grade = client_sim.heuristic_grade(data, jd, hidden)
        out = client_sim.decide(grade, hidden, p["id"], job["proposals_count"])
        fid = p["freelancer_id"]
        status = "lost"
        if out["viewed"]:
            _event(fid, "viewed", p["id"], {"job_id": p["job_id"]}, now)
            status = "viewed"
        if out["replied"]:
            status = "replied"
            cid = "conv_" + p["id"][5:]
            script = _client_script(hidden, out)
            db.x(
                "insert or ignore into conversations values (?,?,?,?,?,?,?)",
                (cid, fid, job["client_id"], p["job_id"], p["id"], "open", json.dumps(script)),
            )
            first = script.pop(0)
            db.x("update conversations set script=? where id=?", (json.dumps(script), cid))
            db.x(
                "insert into messages values (?,?,?,?,?)",
                ("msg_" + uuid.uuid4().hex[:12], cid, "client", first["text"], now),
            )
            _event(fid, "replied", p["id"], {"conversation_id": cid, "job_id": p["job_id"]}, now)
        else:
            _event(
                fid, "lost", p["id"], {"job_id": p["job_id"], "reason": "no_reply"}, now + 3 * 86400
            )
        data["_grade"] = {**out, "grade": grade.__dict__}
        db.x(
            "update proposals set status=?, outcome=?, data=? where id=?",
            (status, json.dumps(out), json.dumps(data), p["id"]),
        )
    return len(rows)


def _client_script(hidden: dict[str, Any], out: dict[str, Any]) -> list[dict[str, str]]:
    """Ordered client turns after the first reply. Uses the seeded per-client script."""
    lines = hidden.get("script") or {}
    script = [
        {
            "intent": "question",
            "text": lines.get(
                "question",
                "Thanks for applying. Can you tell me how you would approach the first milestone?",
            ),
        }
    ]
    if hidden.get("is_scam"):
        script = [
            {
                "intent": "scam_signal",
                "text": lines.get(
                    "scam", "Great, let's continue on Telegram and I will pay in crypto."
                ),
            }
        ]
        return script
    script.append(
        {
            "intent": "negotiation",
            "text": lines.get(
                "negotiation", "Your rate is a bit above my budget. Could you do it for less?"
            ),
        }
    )
    if out["interview"]:
        script.append(
            {
                "intent": "interview_request",
                "text": lines.get(
                    "interview",
                    "Let's schedule a 30-minute call this week. What times work for you?",
                ),
            }
        )
        script.append(
            {
                "intent": "hired" if out["hired"] else "lost",
                "text": lines.get(
                    "hired" if out["hired"] else "lost",
                    "Thanks, I'm sending you an offer now."
                    if out["hired"]
                    else "We decided to go with another freelancer. Thanks for your time.",
                ),
            }
        )
    else:
        script.append(
            {
                "intent": "lost",
                "text": lines.get("lost", "Thanks, we decided to go with another freelancer."),
            }
        )
    return script


def _process_replies() -> int:
    now = sim_now()
    n = 0
    for conv in db.q("select * from conversations where state='open'"):
        due = db.get_sim(f"pending_reply:{conv['id']}")
        if due is None or due > now:
            continue
        script = json.loads(conv["script"] or "[]")
        db.x("delete from sim where k=?", (f"pending_reply:{conv['id']}",))
        if not script:
            continue
        step = script.pop(0)
        db.x(
            "insert into messages values (?,?,?,?,?)",
            ("msg_" + uuid.uuid4().hex[:12], conv["id"], "client", step["text"], now),
        )
        state = "open"
        if step["intent"] in ("hired", "lost"):
            state = step["intent"]
            db.x("update proposals set status=? where id=?", (step["intent"], conv["proposal_id"]))
        elif step["intent"] == "interview_request":
            db.x("update proposals set status='interview' where id=?", (conv["proposal_id"],))
        db.x(
            "update conversations set script=?, state=? where id=?",
            (json.dumps(script), state, conv["id"]),
        )
        _event(
            conv["freelancer_id"],
            step["intent"]
            if step["intent"] in ("hired", "lost", "interview_request")
            else "message",
            conv["proposal_id"],
            {"conversation_id": conv["id"], "intent": step["intent"]},
            now,
        )
        n += 1
    return n


async def _loop() -> None:
    while True:
        try:
            await _process_decisions()
            _process_replies()
        except Exception as e:  # noqa: BLE001
            print("gigsim loop error:", e)
        await asyncio.sleep(float(os.getenv("GIGSIM_TICK_S", "5")))


# --------------------------------------------------------------------------- admin (sim control)


class AdvanceIn(BaseModel):
    minutes: float = Field(gt=0, le=60 * 24 * 30)


@app.post("/admin/advance", dependencies=[Depends(admin)])
async def advance(body: AdvanceIn) -> dict[str, Any]:
    db.set_sim("offset_s", db.get_sim("offset_s", 0.0) + body.minutes * 60)
    n = await _process_decisions()
    m = _process_replies()
    return {"sim_now": sim_now(), "decisions": n, "replies": m}


class PolicyIn(BaseModel):
    version: int


@app.post("/admin/policy", dependencies=[Depends(admin)])
def set_policy(body: PolicyIn) -> dict[str, Any]:
    if body.version not in POLICIES:
        raise HTTPException(400, "unknown policy version")
    db.set_sim("policy_version", body.version)
    return POLICIES[body.version]


class FaultsIn(BaseModel):
    error_rate: float = Field(ge=0, le=1)
    post_commit_error_rate: float = Field(ge=0, le=1)


@app.post("/admin/faults", dependencies=[Depends(admin)])
def set_faults(body: FaultsIn) -> dict[str, Any]:
    global ERROR_RATE, POST_COMMIT_ERROR_RATE
    ERROR_RATE, POST_COMMIT_ERROR_RATE = body.error_rate, body.post_commit_error_rate
    return body.model_dump()


class GrantIn(BaseModel):
    freelancer_id: str
    connects: int = Field(gt=0, le=10_000)


@app.post("/admin/grant", dependencies=[Depends(admin)])
def grant(body: GrantIn) -> dict[str, Any]:
    db.x(
        "update accounts set connects=connects+? where freelancer_id=?",
        (body.connects, body.freelancer_id),
    )
    db.x(
        "insert into connects_ledger(freelancer_id,delta,reason,ref,at) values (?,?,?,?,?)",
        (body.freelancer_id, body.connects, "admin_grant", "", sim_now()),
    )
    return {"ok": True}


@app.post("/admin/reset", dependencies=[Depends(admin)])
def reset() -> dict[str, Any]:
    from gigsim.seed import reseed

    reseed(db, SEED_DIR, API_SECRET)
    return {"ok": True, "sim_now": sim_now()}


@app.get("/admin/proposal/{pid}/grade", dependencies=[Depends(admin)])
def proposal_grade(pid: str) -> dict[str, Any]:
    """Evaluation hook: hidden grading details (never exposed on /v1)."""
    row = db.one("select data,outcome,status from proposals where id=?", (pid,))
    if not row:
        raise HTTPException(404)
    return {
        "status": row["status"],
        "outcome": json.loads(row["outcome"] or "null"),
        "grade": json.loads(row["data"]).get("_grade"),
    }
