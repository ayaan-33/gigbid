# Tools (MCP surface)

Agents never call GigSim, Upwork, a database or a file directly. Every capability is an MCP tool
with a schema, an owner, annotations and a test. Each agent gets only the tools listed for it in
`agent/config.yaml → mcp.allowlists`, enforced in `agent/mcp_client.py`.

**Auth**
- Our three servers use Streamable HTTP with a **Bearer token** (`MCP_BEARER_TOKEN`, compared in
  constant time). The caller is identified by `X-GigBid-User` and `X-GigBid-Persona`, and the
  trace by `X-Trace-Id`, which also lands in the audit log.
- Local stdio use (Claude Desktop, Cursor) needs no token.

**Schema drift:** `tests/contract/test_tool_schemas.py` snapshots every tool's input and output
schema and its annotations, and fails CI on unintended changes.

## Portfolio server — `mcp_servers/portfolio` (read-only, owner: Fit Matcher / Writer)

| Tool | R/W | readOnly | destructive | idempotent | Auth | Notes |
|---|---|---|---|---|---|---|
| `search_evidence(requirement, k, filters)` | read | ✅ | ❌ | ✅ | Bearer | Returns evidence items with id, type, source, date, outcome, project, snippet and score. Filters: type, skills, outcome, client_industry, since. `k` is 1–20. |
| `get_case_study(id)` | read | ✅ | ❌ | ✅ | Bearer | The full Markdown with metadata. |
| `list_skills()` | read | ✅ | ❌ | ✅ | Bearer | Each skill with its evidence count and projects. |

- **Resources:** `portfolio://case/{case_key}`, `portfolio://proposal/{proposal_key}`,
  `portfolio://repo/{repo}`, `portfolio://cv`, `portfolio://profile`
- **Prompts:** `answer_screening_question`, `summarise_fit`, `rewrite_with_evidence`, `opening_line`

## Marketplace server — `mcp_servers/marketplace` (wraps the marketplace port: GigSim or live Upwork)

| Tool | R/W | readOnly | destructive | idempotent | Auth | Notes |
|---|---|---|---|---|---|---|
| `search_jobs(query, category, skills, posted_after, limit≤50, cursor)` | read | ✅ | ❌ | ✅ | Bearer | Saved-search style. |
| `get_job(job_id)` | read | ✅ | ❌ | ✅ | Bearer | |
| `get_client_history(client_id)` | read | ✅ | ❌ | ✅ | Bearer | Payment verified, spend, hires, rating, reviews. |
| `get_connects_balance()` | read | ✅ | ❌ | ✅ | Bearer | |
| `list_conversations()` | read | ✅ | ❌ | ✅ | Bearer | |
| `list_messages(conversation_id)` | read | ✅ | ❌ | ✅ | Bearer | |
| `list_events(since_id)` | read | ✅ | ❌ | ✅ | Bearer | Pipeline events. |
| `get_market_stats(category, budget_type)` | read | ✅ | ❌ | ✅ | Bearer | Price percentiles. |
| `get_policy()` | read | ✅ | ❌ | ✅ | Bearer | Current platform policy version (change request). |
| `marketplace_status()` | read | ✅ | ❌ | ✅ | Bearer | Mode and circuit-breaker state (degraded mode). |
| `create_proposal_draft(inp)` | **write** | ❌ | ❌ | ✅ | Bearer | `ProposalPayload` (cover letter 50–5000 chars, bid between 0 and 1e6, ≤10 screening answers). `idempotency_key` is required. `dry_run`. |
| `submit_proposal(inp)` | **write, spends Connects** | ❌ | ✅ | ✅ | Bearer | `approved_by` is required. `dry_run` returns the payload, Connects cost, balance after and policy problems. Called only from the approval gate. |
| `send_message(inp)` | **write** | ❌ | ✅ | ✅ | Bearer | `approved_by` is required. `dry_run`. On live Upwork it creates a draft that the user confirms there. |

**Every write is protected at three layers:**
1. **The server's own idempotency store.** It keys on user plus `idempotency_key`; a replay
   returns the first result, and reusing a key for a different payload returns 409.
2. **GigSim's server-side idempotency.**
3. **Retries with the same key** after a post-commit failure. This is tested with 100% dropped
   write responses: exactly one draft is created and Connects are spent exactly once.

**Also on this server:**
- a per-user token-bucket rate limiter (20 req/min, under GigSim's 30);
- an append-only, **hash-chained** audit log (user, tool, PII-masked arguments, result, trace id);
- `AuditLog.verify()` detects tampering.

## Workspace server — `mcp_servers/workspace` (owner: Client Liaison)

| Tool | R/W | readOnly | destructive | idempotent | Auth | Notes |
|---|---|---|---|---|---|---|
| `find_free_slots(duration_min, days_ahead, work hours, max_slots)` | read | ✅ | ❌ | ✅ | Bearer | Local mock calendar (SQLite) with deterministic busy blocks. |
| `create_interview_hold(inp)` | write | ❌ | ❌ | ✅ | Bearer | Tentative hold after approval. Rejects clashes and end-before-start. |
| `create_email_draft(inp)` | write | ❌ | ❌ | ✅ | Bearer | Draft only, never sends. Stores a recipient label, not an address. |

The mock implements the same store interface that a Google Calendar/Gmail backend would. Swapping
it changes `store.py` only; the agent sees the same MCP tools.

## Third-party MCP servers

| Server | Used for | Transport / auth | Trust rationale |
|---|---|---|---|
| **Upwork official MCP** (`https://mcp.upwork.com/mcp`) | Live mode: job search, proposal drafts, messages (adapter `upwork_live.py`) | Streamable HTTP, OAuth 2.1 (PKCE + dynamic client registration). Tokens are Fernet-encrypted per user. | First-party server operated by the marketplace itself. Its write actions are drafts that the user confirms on Upwork, which matches our "never auto-send" rule. |
| **GitHub official MCP** (`ghcr.io/github/github-mcp-server`) | Ingesting the freelancer's repositories (READMEs + code) into the portfolio index | stdio in Docker. Fine-grained **read-only** PAT (Contents + Metadata). | Published and maintained by GitHub. Runs with a token that can only read, so the worst case is reading public or allowed repos. |

## Agent → tool allowlists (summary)

| Agent | Tools |
|---|---|
| Scout | search_jobs, get_job, list_events, marketplace_status |
| Job Analyst | — (no tools) |
| Risk Assessor | get_job, get_client_history |
| Fit Matcher | search_evidence, list_skills, get_case_study |
| Pricing Strategist | get_market_stats, get_connects_balance, get_client_history, get_policy |
| Proposal Writer | search_evidence, get_case_study |
| Claim verifier / Critic | search_evidence |
| Compliance Guard | — (policy comes from config + the policy pack) |
| Client Liaison | list_conversations, list_messages, send_message (after approval), find_free_slots, create_interview_hold, create_email_draft, search_evidence |
| Approval executor (not an LLM agent) | create_proposal_draft, submit_proposal, get_connects_balance, marketplace_status |
