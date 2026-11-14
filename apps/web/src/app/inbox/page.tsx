"use client";
import Link from "next/link";
import { useState } from "react";
import { api, ok } from "@/lib/api/client";
import { fmtMoney, useData } from "@/lib/hooks";
import { Empty, ErrorBox, FitBar, PageHeader, RiskBadge, Spinner, StatusBadge } from "@/components/ui";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "bid", label: "Recommended bids" },
  { key: "awaiting_approval", label: "Awaiting approval" },
  { key: "watch", label: "Watch" },
  { key: "skip", label: "Skipped" },
] as const;

export default function Inbox() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [q, setQ] = useState("");
  const { data, error, loading, refresh } = useData(
    async () =>
      ok(
        await api.GET("/api/jobs", {
          params: {
            query: {
              action: filter === "bid" || filter === "skip" ? filter : undefined,
              status: filter === "awaiting_approval" || filter === "watch" ? filter : undefined,
              q: q || undefined,
            },
          },
        }),
      ),
    [filter, q],
    10000,
  );

  return (
    <>
      <PageHeader
        title="Job inbox"
        sub="New jobs ranked by fit. GigBid analyses each one; you decide what to send."
        actions={
          <button
            className="btn-primary"
            onClick={async () => {
              await api.POST("/api/jobs/scout");
              setTimeout(refresh, 1500);
            }}
          >
            Scout now
          </button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Filter jobs" className="flex flex-wrap gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              className={`btn ${filter === f.key ? "bg-brand/10 text-brand" : "text-muted"}`}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input className="input ml-auto max-w-xs" placeholder="Search titles" aria-label="Search job titles" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {loading && !data && <Spinner label="Loading jobs" />}
      {error && <ErrorBox error={error} onRetry={refresh} />}
      {data && data.length === 0 && (
        <Empty title="No jobs yet">Run your saved searches with “Scout now”. New jobs are also pulled on a schedule.</Empty>
      )}
      <ul className="space-y-2" data-testid="job-list">
        {data?.map((j) => (
          <li key={j.job_id} className="card flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <Link href={`/jobs/${j.job_id}`} className="font-medium hover:text-brand">
                {j.title}
              </Link>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                <StatusBadge status={j.status} />
                {j.action && <span className="badge bg-line">recommend: {j.action}</span>}
                <RiskBadge risk={j.risk} scam={j.is_scam} injection={j.injection} />
                <span>{j.category}</span>
                <span>
                  budget {fmtMoney(j.budget?.max as number | undefined, j.budget?.type as string | undefined)}
                </span>
                <span>{j.connects_cost ?? "?"} Connects</span>
              </div>
              {j.reasons?.[0] && <p className="mt-1 truncate text-xs text-muted">{j.reasons[0]}</p>}
            </div>
            <div className="flex items-center gap-3">
              <FitBar fit={j.fit} />
              <span className="w-16 text-right text-sm tabular-nums">{fmtMoney(j.price)}</span>
              {j.status === "awaiting_approval" && j.thread_id ? (
                <Link className="btn-primary" href={`/studio/${j.thread_id}`}>
                  Review
                </Link>
              ) : (
                <Link className="btn-ghost" href={`/jobs/${j.job_id}`}>
                  Open
                </Link>
              )}
              {j.status !== "skipped" && j.status !== "submitted" && (
                <button
                  className="btn-ghost"
                  aria-label={`Skip ${j.title}`}
                  onClick={async () => {
                    await api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: j.job_id } } });
                    refresh();
                  }}
                >
                  Skip
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
