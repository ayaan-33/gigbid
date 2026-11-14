"use client";
import Link from "next/link";
import { use, useState } from "react";
import { api, ok } from "@/lib/api/client";
import { fmtMoney, useData } from "@/lib/hooks";
import { ApprovalPanel } from "@/components/ApprovalPanel";
import { EvidenceText } from "@/components/EvidenceHover";
import { ErrorBox, PageHeader, Spinner, StatusBadge } from "@/components/ui";

type Any = Record<string, unknown>;
type Claim = { text: string; label: string; evidence_ids?: string[]; reason?: string; action?: string; rewritten?: string | null };

export default function Studio({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [done, setDone] = useState<string>();
  const { data, error, refresh } = useData(
    async () => ok(await api.GET("/api/approvals/{thread_id}", { params: { path: { thread_id: id } } })),
    [id],
  );
  const p = (data?.payload ?? {}) as Any;
  const draft = (p.draft ?? {}) as Any;
  const [override, setText] = useState<string | null>(null);
  const text = override ?? String(draft.cover_letter ?? "");
  const [editing, setEditing] = useState(false);
  const [regen, setRegen] = useState<number | null>(null);

  // after a decision, follow the run until it settles
  const run = useData(
    async () => (done ? ok(await api.GET("/api/runs/{thread_id}", { params: { path: { thread_id: id } } })) : null),
    [done],
    done ? 2000 : undefined,
  );

  if (done) {
    const st = (run.data as Any | null)?.status as string | undefined;
    return (
      <div className="card mx-auto max-w-xl space-y-3 text-center" data-testid="decision-result">
        <p className="text-lg font-medium">{done === "reject" ? "Rejected" : "Approved"}</p>
        <p className="text-sm text-muted">
          Status: <StatusBadge status={st ?? "resuming"} /> {(run.data as Any | null)?.status_reason as string}
        </p>
        <div className="flex justify-center gap-2">
          <Link className="btn-ghost" href={`/runs/${id}`}>
            View run
          </Link>
          <Link className="btn-primary" href="/inbox">
            Back to inbox
          </Link>
        </div>
      </div>
    );
  }
  if (error) return <ErrorBox error={error} onRetry={refresh} />;
  if (!data) return <Spinner label="Loading draft" />;
  if (p.kind !== "proposal") return <ErrorBox error="This thread is a message reply; open it from Messages." />;

  const claims = (p.claims as Claim[]) ?? [];
  const critiques = (p.critiques as Any[]) ?? [];
  const compliance = (p.compliance ?? {}) as Any;
  const price = (p.price_quote ?? {}) as Any;
  const job = (p.job ?? {}) as Any;
  const evidence = (p.evidence as Record<string, string>) ?? {};
  const paras = text.split(/\n{2,}/).filter((x) => x.trim());
  const dirty = text.trim() !== String(draft.cover_letter ?? "").trim();
  const words = text.split(/\s+/).filter(Boolean).length;

  async function regenerate(i: number) {
    setRegen(i);
    const r = await api.POST("/api/approvals/{thread_id}/regenerate", {
      params: { path: { thread_id: id } },
      body: { paragraph_index: i, instruction: null },
    });
    setRegen(null);
    if (r.data) {
      const next = [...paras];
      next[i] = (r.data as Any).paragraph as string;
      setText(next.join("\n\n"));
    }
  }

  return (
    <>
      <PageHeader
        title="Proposal studio"
        sub={`${job.title as string} · bid ${fmtMoney(price.amount as number, price.unit as string)} · ${String(price.connects_cost ?? "?")} Connects`}
        actions={
          <Link className="btn-ghost" href={`/jobs/${job.id as string}`}>
            Job detail
          </Link>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <section className="card lg:col-span-2" aria-labelledby="draft-h">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 id="draft-h" className="font-medium">
              Draft v{String(draft.version)} <span className="text-xs font-normal text-muted">· {words} words · strategy {String(draft.strategy)}</span>
            </h2>
            <button className="btn-ghost" onClick={() => setEditing(!editing)} data-testid="toggle-edit">
              {editing ? "Preview with evidence" : "Edit text"}
            </button>
          </div>
          {editing ? (
            <textarea
              aria-label="Proposal text"
              className="input min-h-[22rem] font-mono text-sm"
              value={text}
              onChange={(e) => setText(e.target.value)}
              data-testid="draft-editor"
            />
          ) : (
            <div data-testid="draft-preview">
              <EvidenceText text={text} evidence={evidence} claims={claims} />
            </div>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {paras.map((_, i) => (
              <button key={i} className="btn-ghost text-xs" disabled={regen !== null} onClick={() => regenerate(i)}>
                {regen === i ? "Rewriting…" : `Regenerate ¶${i + 1}`}
              </button>
            ))}
          </div>
          {((draft.screening_answers as Any[]) ?? []).length > 0 && (
            <div className="mt-5 space-y-2">
              <h3 className="label">Screening answers</h3>
              {(draft.screening_answers as Any[]).map((a, i) => (
                <div key={i} className="rounded-lg border border-line p-3 text-sm">
                  <p className="font-medium">{a.question as string}</p>
                  <EvidenceText text={a.answer as string} evidence={evidence} claims={claims} />
                </div>
              ))}
            </div>
          )}
        </section>

        <div className="space-y-4">
          <ApprovalPanel threadId={id} dryRun={(p.dry_run ?? {}) as Any} editedText={text} dirty={dirty} onDone={setDone} />

          <section className="card" aria-labelledby="claims-h">
            <h2 id="claims-h" className="mb-2 font-medium">
              Claim check
            </h2>
            <ul className="space-y-2 text-xs">
              {claims.map((c, i) => (
                <li key={i} className="rounded border border-line p-2">
                  <span
                    className={`badge mr-1 ${c.label === "supported" ? "bg-ok/15 text-ok" : c.label === "partly_supported" ? "bg-warn/15 text-warn" : "bg-bad/15 text-bad"}`}
                  >
                    {c.label.replace("_", " ")}
                  </span>
                  <span className="badge bg-line">{c.action}</span>
                  <p className={`mt-1 ${c.action === "removed" ? "line-through text-muted" : ""}`}>{c.text}</p>
                  {c.rewritten && <p className="mt-1 text-ok">→ {c.rewritten}</p>}
                </li>
              ))}
            </ul>
          </section>

          <section className="card" aria-labelledby="critic-h">
            <h2 id="critic-h" className="mb-2 font-medium">
              Critic
            </h2>
            {critiques.map((c, i) => (
              <div key={i} className="mb-2 text-xs">
                <p>
                  Round {i + 1}: {c.passed ? "passed" : "sent back"} · score {String(c.score)}
                </p>
                <ul className="list-disc pl-4 text-muted">
                  {((c.issues as Any[]) ?? []).map((x, j) => (
                    <li key={j}>
                      {String(x.kind)}: {String(x.detail)}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </section>

          <section className="card" aria-labelledby="comp-h">
            <h2 id="comp-h" className="mb-2 font-medium">
              Compliance Guard
            </h2>
            <p className="text-sm">{compliance.allowed ? "Allowed" : `Blocked: ${String(compliance.blocked_reason)}`}</p>
            <ul className="mt-1 list-disc pl-4 text-xs text-muted">
              {((compliance.violations as Any[]) ?? []).map((v, i) => (
                <li key={i}>
                  {String(v.rule)} — {String(v.fix)}: “{String(v.excerpt).slice(0, 80)}”
                </li>
              ))}
              {((compliance.violations as Any[]) ?? []).length === 0 && <li>No violations found.</li>}
            </ul>
          </section>
        </div>
      </div>
    </>
  );
}
