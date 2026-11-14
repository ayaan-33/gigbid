"use client";
import type { ReactNode } from "react";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-brand" aria-hidden />
      {label}…
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="card border-bad/40 text-sm">
      <p className="font-medium text-bad">Something went wrong</p>
      <p className="mt-1 text-muted">{error}</p>
      {onRetry && (
        <button className="btn-ghost mt-3" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-0.5 text-sm text-muted">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const statusTone: Record<string, string> = {
  submitted: "bg-ok/15 text-ok",
  approved: "bg-ok/15 text-ok",
  hired: "bg-ok/15 text-ok",
  awaiting_approval: "bg-brand/15 text-brand",
  drafting: "bg-brand/15 text-brand",
  analysing: "bg-brand/15 text-brand",
  resuming: "bg-brand/15 text-brand",
  new: "bg-brand/10 text-brand",
  watch: "bg-warn/15 text-warn",
  needs_attention: "bg-warn/15 text-warn",
  queued_degraded: "bg-warn/15 text-warn",
  skipped: "bg-line text-muted",
  duplicate: "bg-line text-muted",
  rejected: "bg-bad/15 text-bad",
  blocked: "bg-bad/15 text-bad",
  dead_letter: "bg-bad/15 text-bad",
  lost: "bg-bad/15 text-bad",
};

export function StatusBadge({ status }: { status?: string | null }) {
  const s = status ?? "new";
  return <span className={`badge ${statusTone[s] ?? "bg-line text-muted"}`}>{s.replace(/_/g, " ")}</span>;
}

export function RiskBadge({ risk, scam, injection }: { risk?: number | null; scam?: boolean; injection?: boolean }) {
  if (scam)
    return (
      <span className="badge bg-bad/15 text-bad" title="Likely scam">
        ⚠ scam
      </span>
    );
  const r = risk ?? null;
  return (
    <span className="flex flex-wrap gap-1">
      {r !== null && (
        <span
          className={`badge ${r >= 0.6 ? "bg-bad/15 text-bad" : r >= 0.35 ? "bg-warn/15 text-warn" : "bg-ok/15 text-ok"}`}
          title={`Risk score ${r.toFixed(2)}`}
        >
          risk {r.toFixed(2)}
        </span>
      )}
      {injection && (
        <span className="badge bg-warn/15 text-warn" title="Job post contains instructions aimed at AI systems; they were ignored">
          injection ignored
        </span>
      )}
    </span>
  );
}

export function FitBar({ fit }: { fit?: number | null }) {
  const v = Math.max(0, Math.min(1, fit ?? 0));
  const known = fit !== null && fit !== undefined;
  return (
    <div className="flex items-center gap-2" aria-label={`Fit ${known ? Math.round(v * 100) + "%" : "unknown"}`}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-line">
        <div className={`h-full ${v >= 0.55 ? "bg-ok" : v >= 0.4 ? "bg-warn" : "bg-bad/70"}`} style={{ width: `${v * 100}%` }} />
      </div>
      <span className="text-xs tabular-nums text-muted">{known ? Math.round(v * 100) : "—"}</span>
    </div>
  );
}
