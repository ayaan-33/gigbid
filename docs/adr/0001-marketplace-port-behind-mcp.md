# ADR 0001: One marketplace port, reached only through our Marketplace MCP server

**Status:** accepted

## Context
GigBid must work against GigSim (development and grading) and against live Upwork (real use),
switched by config (R1). Agents must never call a marketplace directly (Part A).

## Decision
- **One port.** `agent/marketplace_port.py` defines a single `MarketplacePort` protocol with two
  adapters, `gigsim` (REST) and `upwork_live` (the official Upwork MCP server over OAuth 2.1).
- **One consumer.** Only the Marketplace MCP server uses the port. Agents get MCP tools filtered by
  per-agent allowlists.
- **Writes are protected at the server:** idempotency keys, `dry_run`, `approved_by`, rate limits
  and the audit log all live in the MCP server, so they apply to both adapters.

## Consequences
- The graph can't tell which marketplace it's using.
- Live mode reuses every safety mechanism.
- Upwork tool names are mapped by config, so a rename upstream is a config change.
- **Cost:** one extra network hop per call (about 10–30 ms locally).
