"""GigSim adapter for the marketplace port.

Handles GigSim's realistic failure modes:
  * 429 -> wait `Retry-After` (polite) and retry;
  * 5xx / timeouts -> bounded exponential backoff with jitter;
  * 502 after commit on writes -> retry with the SAME idempotency key (exactly-once);
  * repeated failures -> circuit opens -> MarketplaceUnavailable (degraded mode upstream).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from agent.marketplace_port import (
    ClientHistory,
    ConnectsBalance,
    Conversation,
    DraftResult,
    Job,
    MarketEvent,
    MarketplaceError,
    MarketplaceUnavailable,
    MarketStats,
    Message,
    Policy,
    PolicyViolation,
    ProposalPayload,
    SubmitPreview,
    SubmitResult,
)
from mcp_servers.marketplace.resilience import CircuitBreaker, sleep_backoff

BREAKER = CircuitBreaker()  # process-wide: one upstream


class GigSimAdapter:
    name = "gigsim"

    def __init__(self, token: str | None = None, base_url: str | None = None, max_retries: int = 4,
                 timeout_s: float = 15.0, transport: httpx.AsyncBaseTransport | None = None):
        self.base = (base_url or os.getenv("GIGSIM_BASE_URL", "http://localhost:8081")).rstrip("/")
        persona = os.getenv("PORTFOLIO_PERSONA", "ai_ml_engineer")
        self.token = token or f"{os.getenv('GIGSIM_API_TOKEN', 'dev-gigsim-token')}.{persona}"
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(base_url=self.base, timeout=timeout_s, transport=transport,
                                        headers={"Authorization": f"Bearer {self.token}"})

    async def aclose(self) -> None:
        await self.client.aclose()

    # ------------------------------------------------------------------ transport
    async def _req(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                   write: bool = False) -> Any:
        if not BREAKER.allow():
            raise MarketplaceUnavailable(f"GigSim unavailable (circuit open): {BREAKER.last_error}", retryable=True)
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                r = await self.client.request(method, path, json=json, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
                BREAKER.failure(type(e).__name__)
                if not BREAKER.allow():
                    break
                await sleep_backoff(attempt)
                continue
            if r.status_code == 429:
                await sleep_backoff(attempt, float(r.headers.get("Retry-After", "2")))
                continue
            if r.status_code >= 500:
                last = MarketplaceError(f"GigSim {r.status_code}: {r.text[:200]}", r.status_code, True)
                BREAKER.failure(f"HTTP {r.status_code}")
                if not BREAKER.allow():
                    break
                await sleep_backoff(attempt)
                continue  # writes are safe to retry: same idempotency key in the body
            BREAKER.success()
            if r.status_code == 422:
                detail = r.json().get("detail", {})
                if isinstance(detail, dict) and detail.get("error") == "policy_violation":
                    raise PolicyViolation(detail.get("problems", []))
                raise MarketplaceError(f"invalid request: {detail}", 422)
            if r.status_code >= 400:
                raise MarketplaceError(f"GigSim {r.status_code}: {r.json().get('detail', r.text)[:300]}", r.status_code)
            return r.json()
        raise MarketplaceUnavailable(f"GigSim unavailable after {self.max_retries + 1} attempts: {last}", retryable=True)

    # ------------------------------------------------------------------ reads
    async def search_jobs(self, query: str = "", *, category=None, skills=None, posted_after=None, limit=20, cursor=0):
        params: dict[str, Any] = {"limit": limit, "cursor": cursor}
        if query:
            params["q"] = query
        if category:
            params["category"] = category
        if skills:
            params["skills"] = ",".join(skills)
        if posted_after:
            params["posted_after"] = posted_after
        d = await self._req("GET", "/v1/jobs", params=params)
        return [_job(j) for j in d["items"]], d.get("next_cursor")

    async def get_job(self, job_id: str) -> Job:
        return _job(await self._req("GET", f"/v1/jobs/{job_id}"))

    async def get_client_history(self, client_id: str) -> ClientHistory:
        d = await self._req("GET", f"/v1/clients/{client_id}")
        return ClientHistory(**{k: d.get(k) for k in ClientHistory.model_fields if d.get(k) is not None})

    async def get_connects_balance(self) -> ConnectsBalance:
        return ConnectsBalance(**await self._req("GET", "/v1/connects"))

    async def list_conversations(self) -> list[Conversation]:
        d = await self._req("GET", "/v1/conversations")
        out = []
        for c in d["items"]:
            lm = c.get("last_message")
            out.append(Conversation(id=c["id"], client_id=c["client_id"], job_id=c.get("job_id"),
                                    proposal_id=c.get("proposal_id"), state=c["state"],
                                    last_message=_msg(lm) if lm else None))
        return out

    async def list_messages(self, conversation_id: str) -> list[Message]:
        d = await self._req("GET", f"/v1/conversations/{conversation_id}/messages")
        return [_msg(m) for m in d["items"]]

    async def list_events(self, since_id: int = 0) -> list[MarketEvent]:
        d = await self._req("GET", "/v1/events", params={"since_id": since_id})
        return [MarketEvent(**e) for e in d["items"]]

    async def market_stats(self, category: str | None, budget_type: str = "fixed") -> MarketStats:
        params = {"budget_type": budget_type}
        if category:
            params["category"] = category
        return MarketStats(**await self._req("GET", "/v1/market/stats", params=params))

    async def get_policy(self) -> Policy:
        return Policy(**await self._req("GET", "/v1/policy"))

    # ------------------------------------------------------------------ writes
    async def create_proposal_draft(self, payload: ProposalPayload, idempotency_key: str) -> DraftResult:
        d = await self._req("POST", "/v1/proposals", json={**payload.model_dump(), "idempotency_key": idempotency_key},
                            write=True)
        return DraftResult(proposal_id=d["id"], status=d["status"], job_id=d["job_id"])

    async def preview_submit(self, proposal_id: str) -> SubmitPreview:
        d = await self._req("POST", f"/v1/proposals/{proposal_id}/submit",
                            json={"idempotency_key": "dry-run-" + proposal_id, "dry_run": True})
        d.pop("dry_run", None)
        return SubmitPreview(**d)

    async def submit_proposal(self, proposal_id: str, idempotency_key: str) -> SubmitResult:
        d = await self._req("POST", f"/v1/proposals/{proposal_id}/submit", json={"idempotency_key": idempotency_key},
                            write=True)
        return SubmitResult(proposal_id=d["id"], status=d["status"], connects_spent=d.get("connects_spent", 0),
                            balance_after=d.get("balance_after"))

    async def send_message(self, conversation_id: str, text: str, idempotency_key: str) -> Message:
        d = await self._req("POST", f"/v1/conversations/{conversation_id}/messages",
                            json={"text": text, "idempotency_key": idempotency_key}, write=True)
        return Message(id=d["id"], sender="freelancer", text=text, at=0.0)


def _job(d: dict) -> Job:
    return Job(id=d["id"], title=d["title"], description=d["description"], category=d.get("category", "other"),
               skills=d.get("skills", []), budget=d.get("budget") or {}, duration_days=d.get("duration_days"),
               experience_level=d.get("experience_level"), screening_questions=d.get("screening_questions", []),
               connects_cost=d.get("connects_cost", 0), proposals_count=d.get("proposals_count", 0),
               client_id=d.get("client_id"), posted_at=d.get("posted_at"), status=d.get("status", "open"))


def _msg(m: dict) -> Message:
    return Message(id=m["id"], sender=m["sender"], text=m["text"], at=m["at"])
