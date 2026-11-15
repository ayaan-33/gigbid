# Viva preparation

The viva multiplier (0 to 1.0) applies to the whole score: you're graded on the system you can
**explain and change live**. Read this once, then practise the live changes in section 3.

## 1. Explain it in 60 seconds
> "GigBid is a LangGraph system with two durable graphs. The bid graph takes a job from the Scout, runs a Job Analyst, Risk Assessor and Fit Matcher in parallel with `Send`, and a deferred `decide` node chooses skip, watch or bid. For a bid: pricing, then the Writer, then a claim verifier that removes unsupported claims, then a Critic that can send the draft back at most twice, then a Compliance Guard. Then `interrupt()` pauses for my approval in the web UI. Approval resumes the thread and submits through our Marketplace MCP server with an idempotency key, so it happens exactly once even after a crash. Agents only see MCP tools filtered by per-agent allowlists. The marketplace port has two adapters, GigSim and live Upwork, switched by config. Memory changes only through explicit promotion rules."

## 2. Where things are (open these files if asked)

| Question | File |
|---|---|
| Where's the graph? | `agent/graphs/bid_graph.py` (`build_bid_graph`), `agent/graphs/conversation_graph.py` |
| What's in the state, and the reducers? | `agent/state.py` (`operator.add` on lists and counters, `merge_dicts` for usage) |
| Hand-offs between agents | `agent/handoffs.py` (JobSpec, RiskReport, FitReport, BidDecision, PriceQuote, ProposalDraft, ClaimReport, Critique, ComplianceVerdict) |
| Budgets, retries, timeouts, dead letter | `agent/nodes/base.py` (`@node` wrapper) |
| Human approval | `agent/nodes/approval.py` (`interrupt()`, edit/reject paths, `submit` with idempotency keys) |
| Models per node | `agent/config.yaml → models.nodes` |
| Prompts | `agent/prompts/*.md` (versioned; CI forbids inline prompts) |
| Allowlists | `agent/config.yaml → mcp.allowlists`, enforced in `agent/mcp_client.py` |
| Marketplace port | `agent/marketplace_port.py`, `mcp_servers/marketplace/adapters/{gigsim,upwork_live}.py` |
| Idempotency, dry run, audit | `mcp_servers/marketplace/server.py`, `mcp_servers/common.py` (AuditLog) |
| Retrieval variants | `rag/variants/pipeline.py` (flags), `rag/variants/presets.py` |
| Claim verification | `rag/verify.py` |
| Memory rules | `agent/memory/promotion_rules.py`, `agent/memory/store.py` |
| Durability | `agent/runtime.py` (AsyncPostgresSaver + AsyncPostgresStore) |
| Streaming | `agent/runtime.py` (publish), `apps/api/routers/runs.py` (SSE) |
| Guardrails | `agent/guardrails.py`, `agent/nodes/common.py` (Prompt Guard) |

## 3. Live changes to practise (each under 2 minutes)

| They ask you to… | Do this | Then show |
|---|---|---|
| "Make GigBid stricter about fit" | `agent/config.yaml → thresholds.minimum_fit_score: 0.6` | Re-analyse a job; the inbox recommendation changes |
| "Use a different model for the Critic" | `models.nodes.critic: small` | Run viewer → the per-node model and cost change |
| "Allow only one Critic revision" | `budgets.max_revisions: 1` | Run test: `uv run pytest tests/unit/test_bid_graph.py -k critic` (adjust the expectation) |
| "Add a forbidden phrase to compliance" | In `agent/nodes/proposal.py`, add to the `GUARANTEE` regex, e.g. `\|money.back` | Edit a draft to include it: Compliance removes it |
| "Kill the marketplace" | `docker compose stop mcp-marketplace` (or `gigsim`) | Yellow banner; Scout queues; `start` again and it recovers |
| "Crash during approval" | Leave a draft waiting → `docker compose restart api worker` → refresh studio → Approve | One submission in Pipeline; run viewer checkpoints |
| "Platform changed policy" | `docker compose exec gigsim curl -X POST localhost:8081/admin/policy -H "X-Admin-Token: $GIGSIM_ADMIN_TOKEN" -H content-type:application/json -d '{"version":1}'` | Price rationale shows a policy-drift warning; see `docs/CHANGE_REQUEST.md` |
| "Switch RAG variant" | `RAG_VARIANT=v0_naive` env, or `rag.variant` in config | Job detail → the evidence matrix changes |
| "Show the learned memory" | Edit 3 drafts removing the same word, e.g. "passionate" | Settings → What GigBid has learned; click "forget" |
| "Prove no auto-send" | `grep -rn submit_proposal agent/` → only `approval.py::submit`, reached only after `approval_gate` | `test_reject_with_reason`, E2E reject test |

## 4. Likely questions, with honest answers

**Why a hand-built graph, not a single agent?**
Measured in R&D C (`evals/results/multiagent_compare_*.json`):
- The graph gives parallel analysis, deterministic guards and bounded loops.
- A single ReAct agent is simpler and can be competitive on easy skip decisions.
- It can't enforce "verify before critique" or "nothing sent without approval" structurally.

Quote the table, including wherever (a) won.

**Why is the decision rule-based?**
It's auditable, cheap (a skip costs about 3k tokens) and stable in CI, and a policy change becomes
a config edit (ADR 0007). The LLMs are used where language matters.

**How do you stop hallucinated experience?**
Three layers:
1. The Writer must cite `[evidence_id]`.
2. The claim verifier removes or rewrites unsupported claims before the Critic sees the draft.
   It's an LLM batch check plus a deterministic number gate: numbers must appear in the evidence.
3. The Critic and the Compliance Guard check again.

On the labelled claim set it went from 2.0 to 0.2 unsupported or wrong claims per draft, with 0
fabricated claims kept.

**What is the "execution trace" vs "state" vs "memory"?**
See the table in `docs/ARCHITECTURE.md`. Raw tool output never goes into memory. Memory changes
only through `promote()`, when a rule fires (3 of the last 10 edits; or 5+ outcomes with a 10-point
lift).

**Exactly-once submission?**
- The idempotency key is the thread id + draft version + text hash.
- It's enforced in the MCP server's SQLite store **and** by GigSim's server-side idempotency.
- The adapter retries post-commit 502s with the same key.
- Tested with 100% dropped write responses.

**Why did reranking get removed?**
See the ablation. Once projects are grouped (multi-vector), the small MiniLM cross-encoder reorders
project items worse than RRF. The 10× bigger bge reranker wasn't worth its latency (ADR 0006).

**Is GigSim fair, given you built it?**
- It was built before the evals and frozen by checksum.
- The hidden test set uses a separate seed, disjoint real postings and new clients.
- Clients grade proposals against hidden preferences, either with an LLM or with a deterministic
  heuristic.

Results measure agreement with *our* client model, and the report says so.

**What still gets through?**
See report section 9:
- injected instructions phrased as legitimate requirements;
- scams with verified-looking clients and no explicit off-platform request;
- numbers written in words, which the number gate misses.

## 5. Commands cheat-sheet

```bash
uv run pytest -q                         # all python tests (fake LLM, no keys)
./scripts/e2e_stack.sh && (cd apps/web && npx playwright test)
uv run python -m evals.runners.smoke     # CI smoke eval with thresholds
uv run python -m scripts.make_readme_tables
docker compose -f infra/docker-compose.yml logs -f api worker
```
