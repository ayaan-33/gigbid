# ADR 0008: SSE for live progress, with replay from Postgres

**Status:** accepted

## Decision
- **Streaming:** graph custom events (`node_start` / `node_end`) and state updates are published
  to Redis (`run:<thread>`) and also stored in `run_events`.
- **Replay first:** `GET /api/runs/{id}/stream` (SSE) replays the stored events first, then
  streams live ones.
- **Pending approvals are read from the checkpoint,** never from memory.

## Why
- **A refresh never loses** the timeline or a pending approval.
- **SSE is simpler than WebSockets** for one-way progress.

## Gotcha found while building it
- **gzip buffers the stream.** Gzip compression in the Next.js proxy buffered the event stream, so
  the timeline stayed empty. Compression is now disabled in Next.js and skipped for the SSE path
  in Caddy.
- **Headers:** the API sets `Cache-Control: no-transform` and `X-Accel-Buffering: no`.
