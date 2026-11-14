"use client";
import { useEffect, useState } from "react";

type Ev = { type: string; node?: string; status?: string | null; status_reason?: string | null; latency_s?: number; tokens?: number; ts?: number };

const NODES = [
  "ingest", "analyst", "risk_assessor", "fit_matcher", "decision", "pricing", "writer", "verifier", "critic",
  "compliance", "mark_awaiting", "approval_gate", "apply_edit", "submit",
];

/** Live node-by-node progress streamed from LangGraph over Server-Sent Events. Replays history
 *  first, so a refresh never loses the timeline. */
export function RunTimeline({ threadId }: { threadId: string }) {
  // the SSE endpoint replays persisted events first, so the stream alone rebuilds the timeline
  const [events, setEvents] = useState<Ev[]>([]);
  const [live, setLive] = useState(false);

  useEffect(() => {
    const es = new EventSource(`/api/runs/${threadId}/stream`, { withCredentials: true });
    const seen = new Set<string>();
    es.addEventListener("node", (m) => {
      const e = JSON.parse((m as MessageEvent).data) as Ev;
      const key = `${e.type}:${e.node}:${e.ts}`;
      if (seen.has(key)) return;
      seen.add(key);
      setEvents((prev) => [...prev, e]);
    });
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    return () => es.close();
  }, [threadId]);

  const ends = events.filter((e) => e.type === "node_end");
  const starts = new Set(events.filter((e) => e.type === "node_start").map((e) => e.node));
  const doneSet = new Set(ends.map((e) => e.node));
  const running = [...starts].filter((n) => !doneSet.has(n));
  const last = [...events].reverse().find((e) => e.type === "run_end");

  return (
    <section className="card" aria-labelledby="tl-h">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="tl-h" className="font-medium">
          Live progress
        </h2>
        <span className={`badge ${live ? "bg-ok/15 text-ok" : "bg-line text-muted"}`}>{live ? "● streaming" : "offline"}</span>
      </div>
      <ol className="space-y-1" aria-live="polite" data-testid="run-timeline">
        {NODES.filter((n) => starts.has(n) || doneSet.has(n)).map((n) => {
          const end = ends.filter((e) => e.node === n).at(-1);
          const isRunning = running.includes(n);
          return (
            <li key={n} className="flex items-center gap-2 text-sm">
              <span
                aria-hidden
                className={`h-2.5 w-2.5 rounded-full ${isRunning ? "animate-pulse bg-brand" : end?.status === "ok" ? "bg-ok" : end ? "bg-bad" : "bg-line"}`}
              />
              <span className="w-32 font-mono text-xs">{n}</span>
              <span className="text-xs text-muted">
                {isRunning ? "running…" : end ? `${end.status} · ${end.latency_s?.toFixed(1)}s${end.tokens ? ` · ${end.tokens} tok` : ""}` : ""}
                {ends.filter((e) => e.node === n).length > 1 ? ` · ×${ends.filter((e) => e.node === n).length}` : ""}
              </span>
            </li>
          );
        })}
        {events.length === 0 && <li className="text-sm text-muted">Waiting for events…</li>}
      </ol>
      {last && (
        <p className="mt-3 text-sm">
          Run finished: <strong>{last.status}</strong>
        </p>
      )}
    </section>
  );
}
