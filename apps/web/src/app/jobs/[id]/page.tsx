"use client";
import Link from "next/link";
import { use } from "react";
import { api, ok } from "@/lib/api/client";
import { fmtMoney, pct, useData } from "@/lib/hooks";
import { ErrorBox, FitBar, PageHeader, RiskBadge, Spinner, StatusBadge } from "@/components/ui";

type Any = Record<string, unknown>;

export default function JobDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: j, error, refresh } = useData(
    async () => ok(await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })),
    [id],
    8000,
  );
  if (error) return <ErrorBox error={error} onRetry={refresh} />;
  if (!j) return <Spinner label="Loading job" />;
  const spec = (j.job_spec ?? {}) as Any;
  const risk = (j.risk_report ?? {}) as Any;
  const fit = (j.fit_report ?? {}) as Any;
  const dec = (j.decision ?? {}) as Any;
  const price = (j.price_quote ?? {}) as Any;
  const job = j.job as Any;
  const budget = (job.budget ?? {}) as Any;
  const matches = (fit.matches as Any[] | undefined) ?? [];

  return (
    <>
      <PageHeader
        title={j.title}
        sub={`${j.category ?? "other"} · budget ${fmtMoney(budget.min as number)}–${fmtMoney(budget.max as number, budget.type as string)} · ${j.connects_cost ?? job.connects_cost} Connects`}
        actions={
          <>
            {j.status === "awaiting_approval" && j.thread_id && (
              <Link className="btn-primary" href={`/studio/${j.thread_id}`}>
                Review proposal
              </Link>
            )}
            {j.thread_id && (
              <Link className="btn-ghost" href={`/runs/${j.thread_id}`}>
                Agent run
              </Link>
            )}
            <button
              className="btn-ghost"
              onClick={async () => {
                await api.POST("/api/jobs/{job_id}/analyse", { params: { path: { job_id: id } } });
                setTimeout(refresh, 1000);
              }}
            >
              {j.thread_id ? "Re-analyse" : "Analyse"}
            </button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StatusBadge status={j.status} />
        <RiskBadge risk={j.risk} scam={j.is_scam} injection={j.injection} />
        <FitBar fit={j.fit} />
        {j.status_reason && <span className="text-sm text-muted">{j.status_reason}</span>}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="card lg:col-span-2" aria-labelledby="req-h">
          <h2 id="req-h" className="mb-3 font-medium">
            Requirement → evidence
          </h2>
          {matches.length === 0 && <p className="text-sm text-muted">Not analysed yet.</p>}
          <div className="space-y-3">
            {matches.map((m) => (
              <div key={m.requirement_id as string} className="rounded-lg border border-line p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium">{m.requirement as string}</p>
                  <span
                    className={`badge ${m.strength === "strong" ? "bg-ok/15 text-ok" : m.strength === "partial" ? "bg-warn/15 text-warn" : "bg-bad/15 text-bad"}`}
                  >
                    {m.strength as string}
                  </span>
                </div>
                <ul className="mt-2 space-y-1">
                  {((m.evidence as Any[]) ?? []).map((e) => (
                    <li key={e.evidence_id as string} className="text-xs">
                      <span className="badge mr-1 bg-line">{e.type as string}</span>
                      <span className="font-medium">{e.title as string}</span>
                      <span className="text-muted"> · relevance {Number(e.score).toFixed(2)}</span>
                      <p className="mt-0.5 line-clamp-2 text-muted">{e.snippet as string}</p>
                    </li>
                  ))}
                  {((m.evidence as Any[]) ?? []).length === 0 && <li className="text-xs text-bad">No portfolio evidence: will not be claimed.</li>}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <div className="space-y-4">
          <section className="card" aria-labelledby="dec-h">
            <h2 id="dec-h" className="mb-2 font-medium">
              Recommendation: {(dec.action as string) ?? "—"}
            </h2>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
              {((dec.reasons as string[]) ?? []).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            {fit.reasons ? <p className="mt-2 text-xs text-muted">Fit: {(fit.reasons as string[]).join(" · ")}</p> : null}
          </section>
          <section className="card" aria-labelledby="price-h">
            <h2 id="price-h" className="mb-2 font-medium">
              Price
            </h2>
            <p className="text-2xl font-semibold">{fmtMoney(price.amount as number, price.unit as string)}</p>
            <p className="mt-1 text-sm text-muted">{(price.rationale as string) ?? "Priced after a bid decision."}</p>
            {price.expected_win_prob !== undefined && (
              <p className="mt-1 text-xs text-muted">Estimated win chance {pct(price.expected_win_prob as number)}</p>
            )}
          </section>
          <section className="card" aria-labelledby="risk-h">
            <h2 id="risk-h" className="mb-2 font-medium">
              Risk report
            </h2>
            <p className="text-sm">
              Score {risk.score !== undefined ? Number(risk.score).toFixed(2) : "—"} · client quality{" "}
              {risk.client_quality !== undefined ? Number(risk.client_quality).toFixed(2) : "—"}
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              {((risk.flags as string[]) ?? []).map((f) => (
                <span key={f} className="badge bg-warn/15 text-warn">
                  {f.replace(/_/g, " ")}
                </span>
              ))}
            </div>
            {risk.injected_text ? (
              <p className="mt-2 rounded bg-warn/10 p-2 text-xs">
                Ignored injected instruction: “{String(risk.injected_text).slice(0, 220)}”
              </p>
            ) : null}
            {risk.explanation ? <p className="mt-2 text-xs text-muted">{risk.explanation as string}</p> : null}
          </section>
        </div>

        <section className="card lg:col-span-2" aria-labelledby="spec-h">
          <h2 id="spec-h" className="mb-2 font-medium">
            JobSpec
          </h2>
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="label">Deliverables</dt>
              <dd>{((spec.deliverables as string[]) ?? []).join("; ") || "—"}</dd>
            </div>
            <div>
              <dt className="label">Skills</dt>
              <dd>{((spec.required_skills as string[]) ?? []).join(", ") || "—"}</dd>
            </div>
            <div>
              <dt className="label">Hidden needs</dt>
              <dd>{((spec.hidden_needs as string[]) ?? []).join("; ") || "—"}</dd>
            </div>
            <div>
              <dt className="label">Screening questions</dt>
              <dd>{((spec.screening_questions as string[]) ?? []).join(" / ") || "—"}</dd>
            </div>
          </dl>
        </section>
        <section className="card" aria-labelledby="post-h">
          <h2 id="post-h" className="mb-2 font-medium">
            Job post <span className="text-xs font-normal text-muted">(untrusted text)</span>
          </h2>
          <p className="max-h-80 overflow-auto whitespace-pre-wrap text-sm text-muted">{job.description as string}</p>
        </section>
      </div>
    </>
  );
}
