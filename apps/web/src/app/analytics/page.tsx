"use client";
import { api, ok } from "@/lib/api/client";
import { pct, useData } from "@/lib/hooks";
import { ErrorBox, PageHeader, Spinner } from "@/components/ui";

type Row = Record<string, unknown>;

function RateTable({ title, rows, keyName }: { title: string; rows: Row[]; keyName: string }) {
  return (
    <section className="card overflow-x-auto" aria-labelledby={`${keyName}-h`}>
      <h2 id={`${keyName}-h`} className="mb-2 font-medium">
        {title}
      </h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">No submitted proposals yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="py-1">{keyName}</th>
              <th className="py-1 text-right">Sent</th>
              <th className="py-1">Reply rate</th>
              <th className="py-1 text-right">Hire rate</th>
              <th className="py-1 text-right">Connects</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={String(r[keyName])} className="border-t border-line/60">
                <td className="py-1">{String(r[keyName])}</td>
                <td className="py-1 text-right tabular-nums">{String(r.submitted)}</td>
                <td className="py-1">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-line" aria-hidden>
                      <div className="h-full bg-brand" style={{ width: `${Number(r.reply_rate) * 100}%` }} />
                    </div>
                    <span className="tabular-nums">{pct(Number(r.reply_rate))}</span>
                  </div>
                </td>
                <td className="py-1 text-right tabular-nums">{pct(Number(r.hire_rate))}</td>
                <td className="py-1 text-right tabular-nums">{String(r.connects)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default function Analytics() {
  const { data, error, refresh } = useData(async () => ok(await api.GET("/api/analytics")), [], 30000);
  if (error) return <ErrorBox error={error} onRetry={refresh} />;
  if (!data) return <Spinner label="Loading analytics" />;
  const cl = data.cost_latency as Row;
  const stats = [
    ["Jobs analysed", cl.jobs_analysed],
    ["Proposals", cl.proposals],
    ["Cost / job", `$${Number(cl.cost_per_job_usd).toFixed(4)}`],
    ["Cost / proposal", `$${Number(cl.cost_per_proposal_usd).toFixed(4)}`],
    ["p95 latency / job", cl.p95_latency_job_s ? `${cl.p95_latency_job_s}s` : "—"],
    ["p95 latency / proposal", cl.p95_latency_proposal_s ? `${cl.p95_latency_proposal_s}s` : "—"],
    ["Connects spent", (data.connects as Row).spent],
    ["Connects / reply", (data.connects as Row).connects_per_reply],
  ];
  const funnel = data.funnel as Record<string, number>;
  const maxF = Math.max(1, ...Object.values(funnel));
  return (
    <>
      <PageHeader title="Analytics" sub="Outcomes, Connects and the cost of running the agents. Cost is at list price; this deployment uses free tiers." />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {stats.map(([k, v]) => (
          <div key={String(k)} className="card">
            <p className="label">{String(k)}</p>
            <p className="mt-1 text-xl font-semibold tabular-nums">{String(v ?? "—")}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <RateTable title="Reply and hire rate by category" rows={data.by_category as Row[]} keyName="category" />
        <RateTable title="By proposal strategy (A/B test)" rows={data.by_strategy as Row[]} keyName="strategy" />
        <section className="card" aria-labelledby="funnel-h">
          <h2 id="funnel-h" className="mb-2 font-medium">
            Funnel
          </h2>
          <ul className="space-y-1">
            {Object.entries(funnel).map(([k, v]) => (
              <li key={k} className="flex items-center gap-2 text-sm">
                <span className="w-20 text-xs text-muted">{k}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-line" aria-hidden>
                  <div className="h-full bg-brand/70" style={{ width: `${(v / maxF) * 100}%` }} />
                </div>
                <span className="w-8 text-right tabular-nums">{v}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="rej-h">
          <h2 id="rej-h" className="mb-2 font-medium">
            Top rejection reasons
          </h2>
          <ul className="space-y-1 text-sm">
            {(data.rejection_reasons as Row[]).map((r) => (
              <li key={String(r.reason)} className="flex justify-between gap-3">
                <span className="truncate text-muted">{String(r.reason).replace("rejected by user: ", "")}</span>
                <span className="tabular-nums">{String(r.count)}</span>
              </li>
            ))}
            {(data.rejection_reasons as Row[]).length === 0 && <li className="text-muted">No rejections yet.</li>}
          </ul>
        </section>
      </div>
    </>
  );
}
