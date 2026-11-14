"use client";
import Link from "next/link";
import { use } from "react";
import { api, ok } from "@/lib/api/client";
import { useData } from "@/lib/hooks";
import { RunTimeline } from "@/components/RunTimeline";
import { ErrorBox, PageHeader, Spinner, StatusBadge } from "@/components/ui";

type Any = Record<string, unknown>;

export default function RunDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, refresh } = useData(
    async () => ok(await api.GET("/api/runs/{thread_id}", { params: { path: { thread_id: id } } })) as Any,
    [id],
    5000,
  );
  const hist = useData(async () => ok(await api.GET("/api/runs/{thread_id}/history", { params: { path: { thread_id: id } } })) as Any[], [id]);
  if (error) return <ErrorBox error={error} onRetry={refresh} />;
  if (!data) return <Spinner label="Loading run" />;
  const usage = (data.usage ?? {}) as Record<string, Any>;
  const tools = (data.tool_events ?? []) as Any[];
  const thread = (data.thread ?? {}) as Any;
  const waiting = ((data.next as string[]) ?? []).includes("approval_gate") || ((data.next as string[]) ?? []).includes("reply_approval");

  return (
    <>
      <PageHeader
        title={`Run · ${String(thread.kind)} · ${String(thread.job_id ?? thread.conversation_id)}`}
        sub={String(data.status_reason ?? "")}
        actions={
          <>
            {waiting && thread.kind === "bid" && (
              <Link className="btn-primary" href={`/studio/${id}`}>
                Review draft
              </Link>
            )}
            {data.trace_url ? (
              <a className="btn-ghost" href={String(data.trace_url)} target="_blank" rel="noreferrer">
                Full trace ↗
              </a>
            ) : null}
          </>
        }
      />
      <div className="mb-4 flex flex-wrap gap-3 text-sm">
        <StatusBadge status={data.status as string} />
        <span className="text-muted">
          {Number(thread.tokens ?? 0).toLocaleString()} tokens · ${Number(thread.cost_usd ?? 0).toFixed(4)} · {Number(thread.latency_s ?? 0).toFixed(1)}s
        </span>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <RunTimeline key={id} threadId={id} />
        <section className="card lg:col-span-2" aria-labelledby="usage-h">
          <h2 id="usage-h" className="mb-2 font-medium">
            Tokens, cost and latency per node
          </h2>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-1">Node</th>
                <th className="py-1 text-right">LLM calls</th>
                <th className="py-1 text-right">Tokens</th>
                <th className="py-1 text-right">Cost</th>
                <th className="py-1 text-right">Latency</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(usage).map(([n, u]) => (
                <tr key={n} className="border-t border-line/60">
                  <td className="py-1 font-mono text-xs">{n}</td>
                  <td className="py-1 text-right tabular-nums">{String(u.calls ?? 0)}</td>
                  <td className="py-1 text-right tabular-nums">{Number(u.tokens ?? 0).toLocaleString()}</td>
                  <td className="py-1 text-right tabular-nums">${Number(u.cost_usd ?? 0).toFixed(5)}</td>
                  <td className="py-1 text-right tabular-nums">{Number(u.latency_s ?? 0).toFixed(2)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
          {((data.errors as string[]) ?? []).length > 0 && (
            <div className="mt-3 rounded bg-bad/10 p-2 text-xs">
              {(data.errors as string[]).map((e, i) => (
                <p key={i}>{e}</p>
              ))}
            </div>
          )}
        </section>
        <section className="card lg:col-span-2" aria-labelledby="tools-h">
          <h2 id="tools-h" className="mb-2 font-medium">
            Execution trace (MCP tool calls)
          </h2>
          <ul className="max-h-96 space-y-1 overflow-auto text-xs">
            {tools.map((t) => (
              <li key={String(t.id)} className="rounded border border-line/60 p-2">
                <span className={t.ok ? "text-ok" : "text-bad"}>{t.ok ? "✓" : "✗"}</span> <span className="font-mono">{String(t.agent)}</span> →{" "}
                <span className="font-mono">
                  {String(t.server)}.{String(t.tool)}
                </span>{" "}
                <span className="text-muted">{Number(t.latency_s).toFixed(2)}s</span>
                <p className="truncate text-muted">{JSON.stringify(t.args)}</p>
                {t.error ? <p className="text-bad">{String(t.error)}</p> : null}
              </li>
            ))}
            {tools.length === 0 && <li className="text-muted">No tool calls recorded.</li>}
          </ul>
        </section>
        <section className="card" aria-labelledby="hist-h">
          <h2 id="hist-h" className="mb-2 font-medium">
            Checkpoints
          </h2>
          <ol className="max-h-96 space-y-1 overflow-auto text-xs">
            {(hist.data ?? []).map((h) => (
              <li key={String(h.checkpoint_id)} className="flex items-center justify-between gap-2">
                <span>
                  step {String(h.step)} · {((h.writes as string[]) ?? []).join(", ") || "start"}
                </span>
                <button
                  className="text-brand"
                  onClick={async () => {
                    await api.POST("/api/runs/{thread_id}/replay/{checkpoint_id}", {
                      params: { path: { thread_id: id, checkpoint_id: String(h.checkpoint_id) } },
                    });
                    refresh();
                  }}
                >
                  replay
                </button>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </>
  );
}
