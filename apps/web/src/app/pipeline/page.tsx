"use client";
import Link from "next/link";
import { api, ok } from "@/lib/api/client";
import { useData, when } from "@/lib/hooks";
import { Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";

const STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"] as const;

export default function Pipeline() {
  const { data, error, loading, refresh } = useData(async () => ok(await api.GET("/api/pipeline")), [], 10000);
  return (
    <>
      <PageHeader
        title="Pipeline"
        sub="Every proposal from draft to outcome. Cards move as marketplace events arrive."
        actions={
          <button
            className="btn-ghost"
            onClick={async () => {
              await api.POST("/api/pipeline/sync");
              setTimeout(refresh, 1500);
            }}
          >
            Sync now
          </button>
        }
      />
      {loading && !data && <Spinner />}
      {error && <ErrorBox error={error} onRetry={refresh} />}
      {data && data.length === 0 && <Empty title="No proposals yet">Approve a draft in the proposal studio to start your pipeline.</Empty>}
      {data && data.length > 0 && (
        <div className="-mx-4 overflow-x-auto px-4" role="region" aria-label="Pipeline board" tabIndex={0}>
          <div className="grid min-w-[980px] grid-cols-7 gap-3">
            {STAGES.map((s) => {
              const cards = data.filter((c) => c.stage === s);
              return (
                <section key={s} aria-labelledby={`col-${s}`} className="rounded-xl bg-line/30 p-2" data-testid={`col-${s}`}>
                  <h2 id={`col-${s}`} className="mb-2 flex justify-between px-1 text-xs font-medium uppercase tracking-wide text-muted">
                    {s} <span>{cards.length}</span>
                  </h2>
                  <ul className="space-y-2">
                    {cards.map((c) => (
                      <li key={c.proposal_id} className="rounded-lg border border-line bg-surface p-2 text-xs">
                        <Link
                          href={s === "drafted" && c.thread_id ? `/studio/${c.thread_id}` : c.conversation_id ? `/messages?c=${c.conversation_id}` : `/jobs/${c.job_id}`}
                          className="line-clamp-2 font-medium hover:text-brand"
                        >
                          {c.title ?? c.job_id}
                        </Link>
                        <p className="mt-1 text-muted">
                          {c.category} · {c.strategy ?? "default"}
                        </p>
                        <p className="text-muted">
                          {c.connects_spent} Connects · {when(c.updated_at)}
                        </p>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
