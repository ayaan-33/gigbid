"use client";
import Link from "next/link";
import { api, ok } from "@/lib/api/client";
import { useData, when } from "@/lib/hooks";
import { Empty, ErrorBox, PageHeader, Spinner, StatusBadge } from "@/components/ui";

export default function Runs() {
  const { data, error, loading, refresh } = useData(async () => ok(await api.GET("/api/runs", { params: { query: { limit: 100 } } })), [], 8000);
  return (
    <>
      <PageHeader title="Agent runs" sub="Every graph run with its status, tokens, cost and latency." />
      {loading && !data && <Spinner />}
      {error && <ErrorBox error={error} onRetry={refresh} />}
      {data?.length === 0 && <Empty title="No runs yet" />}
      {data && data.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="p-3">Run</th>
                <th className="p-3">Status</th>
                <th className="p-3 text-right">Tokens</th>
                <th className="p-3 text-right">Cost</th>
                <th className="p-3 text-right">Latency</th>
                <th className="p-3">Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.thread_id} className="border-b border-line/60 last:border-0">
                  <td className="p-3">
                    <Link href={`/runs/${t.thread_id}`} className="font-medium hover:text-brand">
                      {t.kind} · {t.job_id ?? t.conversation_id}
                    </Link>
                    <p className="max-w-md truncate text-xs text-muted">{t.status_reason}</p>
                  </td>
                  <td className="p-3">
                    <StatusBadge status={t.status} />
                  </td>
                  <td className="p-3 text-right tabular-nums">{t.tokens.toLocaleString()}</td>
                  <td className="p-3 text-right tabular-nums">${t.cost_usd.toFixed(4)}</td>
                  <td className="p-3 text-right tabular-nums">{t.latency_s.toFixed(1)}s</td>
                  <td className="p-3 text-xs text-muted">{when(t.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
