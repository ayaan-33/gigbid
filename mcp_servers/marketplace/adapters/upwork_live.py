"""Live Upwork adapter (A4): the official Upwork MCP server behind the same marketplace port.

* Transport: `MultiServerMCPClient` over Streamable HTTP to https://mcp.upwork.com/mcp.
* Auth: OAuth 2.1 (PKCE + dynamic client registration) via the MCP SDK's OAuthClientProvider.
  Tokens are stored ENCRYPTED per user (Fernet, TOKEN_ENCRYPTION_KEY) and never logged.
* The web OAuth dance is brokered by `OAUTH_BROKER`: the API starts a flow, the UI opens the
  authorisation URL, Upwork redirects to /api/auth/upwork/callback, the broker resumes the flow.
* Tool names are discovered at connect time and mapped onto the port by `upwork_live.tool_map`
  in config.yaml (first match wins), so a renamed upstream tool is a config change.
* Safety: no browser automation, no cookies, no scraping. Writes create DRAFTS only; the user
  confirms them on Upwork (`requires_confirmation_on_marketplace=True`). Reads are scheduled no
  more often than `marketplace.live_poll_interval_minutes`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

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
    ProposalPayload,
    SubmitPreview,
    SubmitResult,
)
from agent.settings import ROOT, cfg

UPWORK_MCP_URL = os.getenv("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp")
TOKEN_DB = Path(os.getenv("OAUTH_TOKEN_DB", ROOT / ".cache" / "oauth_tokens.sqlite"))

DEFAULT_TOOL_MAP: dict[str, list[str]] = {
    "search_jobs": ["search_jobs", "job_search", "searchJobs", "find_jobs", "search_job_postings"],
    "get_job": ["get_job", "get_job_details", "job_details", "getJob", "get_job_posting"],
    "get_client_history": ["get_client", "get_client_details", "client_info", "get_client_history"],
    "get_connects_balance": ["get_connects", "get_connects_balance", "connects_balance"],
    "list_conversations": ["list_rooms", "list_conversations", "list_message_rooms", "get_rooms"],
    "list_messages": ["list_messages", "get_messages", "get_room_messages"],
    "create_proposal_draft": ["create_proposal_draft", "draft_proposal", "create_proposal", "submit_proposal_draft"],
    "send_message": ["draft_message", "create_message_draft", "send_message"],
}


# --------------------------------------------------------------------------- encrypted token store


class EncryptedTokenStorage(TokenStorage):
    """Per-user OAuth tokens + client registration, Fernet-encrypted at rest, tenant-scoped."""

    def __init__(self, user_id: str, provider: str = "upwork", db_path: Path = TOKEN_DB):
        key = os.getenv("TOKEN_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
        self.f = Fernet(key.encode())
        self.user_id, self.provider = user_id, provider
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("create table if not exists oauth (user_id text, provider text, kind text, blob blob,"
                          " primary key (user_id, provider, kind))")

    def _get(self, kind: str) -> dict | None:
        row = self.conn.execute("select blob from oauth where user_id=? and provider=? and kind=?",
                                (self.user_id, self.provider, kind)).fetchone()
        return json.loads(self.f.decrypt(row[0])) if row else None

    def _set(self, kind: str, value: dict) -> None:
        self.conn.execute("insert or replace into oauth values (?,?,?,?)",
                          (self.user_id, self.provider, kind, self.f.encrypt(json.dumps(value).encode())))
        self.conn.commit()

    async def get_tokens(self) -> OAuthToken | None:
        d = self._get("tokens")
        return OAuthToken(**d) if d else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._set("tokens", tokens.model_dump(mode="json"))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        d = self._get("client")
        return OAuthClientInformationFull(**d) if d else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._set("client", client_info.model_dump(mode="json"))

    def connected(self) -> bool:
        return self._get("tokens") is not None

    def disconnect(self) -> None:
        self.conn.execute("delete from oauth where user_id=? and provider=?", (self.user_id, self.provider))
        self.conn.commit()


# --------------------------------------------------------------------------- web OAuth broker


class OAuthBroker:
    """Bridges the SDK's redirect/callback handlers to two HTTP endpoints of the GigBid API."""

    def __init__(self) -> None:
        self.auth_urls: dict[str, asyncio.Future[str]] = {}
        self.callbacks: dict[str, asyncio.Future[tuple[str, str | None]]] = {}

    def handlers(self, user_id: str):
        loop = asyncio.get_running_loop()
        self.auth_urls[user_id] = loop.create_future()
        self.callbacks[user_id] = loop.create_future()

        async def redirect(url: str) -> None:
            fut = self.auth_urls[user_id]
            if not fut.done():
                fut.set_result(url)

        async def callback() -> tuple[str, str | None]:
            return await self.callbacks[user_id]

        return redirect, callback

    async def auth_url(self, user_id: str, wait_s: float = 20) -> str:
        return await asyncio.wait_for(self.auth_urls[user_id], wait_s)

    def complete(self, user_id: str, code: str, state: str | None) -> None:
        fut = self.callbacks.get(user_id)
        if fut is None or fut.done():
            raise MarketplaceError("no pending Upwork authorisation for this user")
        fut.set_result((code, state))


OAUTH_BROKER = OAuthBroker()


def oauth_provider(user_id: str, interactive: bool = False) -> OAuthClientProvider:
    redirect_uri = os.getenv("UPWORK_OAUTH_REDIRECT_URI", "http://localhost:8000/api/auth/upwork/callback")
    meta = OAuthClientMetadata(client_name="GigBid (freelancer copilot)", redirect_uris=[AnyUrl(redirect_uri)],
                               grant_types=["authorization_code", "refresh_token"], response_types=["code"],
                               token_endpoint_auth_method="none")
    redirect = callback = None
    if interactive:
        redirect, callback = OAUTH_BROKER.handlers(user_id)
    return OAuthClientProvider(server_url=UPWORK_MCP_URL.rsplit("/mcp", 1)[0], client_metadata=meta,
                               storage=EncryptedTokenStorage(user_id), redirect_handler=redirect,
                               callback_handler=callback)


# --------------------------------------------------------------------------- adapter


class UpworkLiveAdapter:
    name = "upwork_live"

    def __init__(self, user_id: str, client: Any | None = None):
        self.user_id = user_id
        self._client = client  # injectable for contract tests (fake Upwork MCP)
        self._tools: dict[str, Any] | None = None
        self.tool_map = cfg("upwork_live.tool_map", None) or DEFAULT_TOOL_MAP

    async def _ensure(self, interactive: bool = False) -> dict[str, Any]:
        if self._tools is not None:
            return self._tools
        if self._client is None:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            storage = EncryptedTokenStorage(self.user_id)
            if not interactive and not storage.connected():
                raise MarketplaceUnavailable("Upwork account not connected: connect it in Settings", status=401)
            self._client = MultiServerMCPClient({"upwork": {"transport": "streamable_http", "url": UPWORK_MCP_URL,
                                                            "auth": oauth_provider(self.user_id, interactive),
                                                            "timeout": 30}})
        try:
            tools = await self._client.get_tools()
        except Exception as e:  # noqa: BLE001
            raise MarketplaceUnavailable(f"Upwork MCP unreachable: {type(e).__name__}") from e
        self._tools = {t.name: t for t in tools}
        return self._tools

    async def connect(self) -> list[str]:
        """Interactive first connection (runs the OAuth flow) -> discovered tool names."""
        return sorted(await self._ensure(interactive=True))

    def mapping(self, available: list[str]) -> dict[str, str | None]:
        return {op: next((n for n in names if n in available), None) for op, names in self.tool_map.items()}

    async def _call(self, op: str, args: dict[str, Any]) -> Any:
        tools = await self._ensure()
        name = self.mapping(list(tools)).get(op)
        if not name:
            raise MarketplaceError(f"operation '{op}' is not offered by the live Upwork MCP server", status=501)
        out = await tools[name].ainvoke(args)
        return _parse(out)

    async def aclose(self) -> None:
        self._tools = None

    # ------------------------------------------------------------------ reads
    async def search_jobs(self, query: str = "", *, category=None, skills=None, posted_after=None, limit=20, cursor=0):
        d = await self._call("search_jobs", {"query": query or " ".join(skills or []), "limit": limit})
        items = d.get("jobs") or d.get("items") or d.get("results") or (d if isinstance(d, list) else [])
        return [_job(x) for x in items][:limit], None

    async def get_job(self, job_id: str) -> Job:
        return _job(await self._call("get_job", {"job_id": job_id}))

    async def get_client_history(self, client_id: str) -> ClientHistory:
        d = await self._call("get_client_history", {"client_id": client_id})
        return ClientHistory(id=client_id, name=d.get("name"), country=d.get("country"),
                             payment_verified=bool(d.get("payment_verified") or d.get("paymentVerified")),
                             total_spent=float(d.get("total_spent") or d.get("totalSpent") or 0),
                             hires=int(d.get("hires") or d.get("totalHires") or 0))

    async def get_connects_balance(self) -> ConnectsBalance:
        try:
            d = await self._call("get_connects_balance", {})
            return ConnectsBalance(balance=int(d.get("balance") or d.get("connects") or 0))
        except MarketplaceError:
            return ConnectsBalance(balance=0)

    async def list_conversations(self) -> list[Conversation]:
        d = await self._call("list_conversations", {})
        rooms = d.get("rooms") or d.get("items") or (d if isinstance(d, list) else [])
        return [Conversation(id=str(r.get("id") or r.get("roomId")), client_id=str(r.get("client_id") or ""),
                             state="open") for r in rooms]

    async def list_messages(self, conversation_id: str) -> list[Message]:
        d = await self._call("list_messages", {"room_id": conversation_id})
        msgs = d.get("messages") or d.get("items") or (d if isinstance(d, list) else [])
        return [Message(id=str(m.get("id")), sender="client" if not m.get("is_me") else "freelancer",
                        text=m.get("text") or m.get("message") or "", at=float(m.get("at") or 0)) for m in msgs]

    async def list_events(self, since_id: int = 0) -> list[MarketEvent]:
        return []  # live mode: pipeline updates are derived from scheduled reads, not a push feed

    async def market_stats(self, category: str | None, budget_type: str = "fixed") -> MarketStats:
        from pathlib import Path as _P

        stats = json.loads((_P(ROOT) / "data" / "derived" / "market_stats.json").read_text())
        s = (stats.get(category or "other") or {}).get(budget_type) or {}
        return MarketStats(category=category, budget_type=budget_type, **s)

    async def get_policy(self) -> Policy:
        return Policy(version=int(cfg("policy.version", 1)), rules=["Upwork Terms of Service apply"])

    # ------------------------------------------------------------------ writes (drafts only)
    async def create_proposal_draft(self, payload: ProposalPayload, idempotency_key: str) -> DraftResult:
        d = await self._call("create_proposal_draft", {"job_id": payload.job_id, "cover_letter": payload.cover_letter,
                                                       "bid_amount": payload.bid_amount})
        return DraftResult(proposal_id=str(d.get("id") or d.get("draft_id") or idempotency_key),
                           status="draft_on_upwork", job_id=payload.job_id)

    async def preview_submit(self, proposal_id: str) -> SubmitPreview:
        bal = await self.get_connects_balance()
        return SubmitPreview(proposal_id=proposal_id, job_id="", connects_cost=0, balance_before=bal.balance,
                             balance_after=bal.balance, policy_version=int(cfg("policy.version", 1)),
                             policy_problems=[], payload={"note": "Upwork shows the Connects cost when you confirm the draft"})

    async def submit_proposal(self, proposal_id: str, idempotency_key: str) -> SubmitResult:
        # GigBid never submits on Upwork: the user confirms the draft on Upwork itself.
        return SubmitResult(proposal_id=proposal_id, status="awaiting_confirmation_on_upwork",
                            requires_confirmation_on_marketplace=True)

    async def send_message(self, conversation_id: str, text: str, idempotency_key: str) -> Message:
        d = await self._call("send_message", {"room_id": conversation_id, "text": text})
        return Message(id=str(d.get("id") or idempotency_key), sender="freelancer", text=text, at=0.0)


def _parse(out: Any) -> Any:
    if isinstance(out, list | tuple) and out and isinstance(out[0], dict) and "text" in out[0]:
        out = out[0]["text"]
    if isinstance(out, str):
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"text": out}
    return out


def _job(d: dict) -> Job:
    b = d.get("budget") or {}
    if not isinstance(b, dict):
        b = {"max": float(b) if b else None}
    return Job(id=str(d.get("id") or d.get("ciphertext") or d.get("job_id")), title=d.get("title", ""),
               description=d.get("description", "") or d.get("snippet", ""), category=d.get("category") or "other",
               skills=[s if isinstance(s, str) else s.get("name", "") for s in d.get("skills", [])],
               budget={"type": "hourly" if d.get("hourly") or d.get("type") == "hourly" else "fixed",
                       "min": b.get("min"), "max": b.get("max") or b.get("amount")},
               connects_cost=int(d.get("connects_cost") or d.get("connectPrice") or 0),
               client_id=str(d.get("client_id") or (d.get("client") or {}).get("id") or ""), marketplace="upwork_live")
