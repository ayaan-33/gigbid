"use client";
import { Fragment, useId, useState } from "react";

type Claim = { text: string; label: string; evidence_ids?: string[]; reason?: string; action?: string };
const CITE = /\[([a-z_]+:[a-z_]+:[\w\-.]+)\]/g;

/** Renders proposal text; every [evidence_id] citation becomes a focusable chip that shows the
 *  evidence behind the claim on hover / keyboard focus. */
export function EvidenceText({ text, evidence, claims }: { text: string; evidence: Record<string, string>; claims: Claim[] }) {
  return (
    <div className="space-y-3 text-[15px] leading-relaxed">
      {text.split(/\n{2,}/).map((para, i) => (
        <p key={i}>
          {para.split(CITE).map((part, j) =>
            j % 2 === 1 ? (
              <Chip key={j} id={part} snippet={evidence[part]} claim={claims.find((c) => c.evidence_ids?.includes(part) || c.text.includes(part))} />
            ) : (
              <Fragment key={j}>{part}</Fragment>
            ),
          )}
        </p>
      ))}
    </div>
  );
}

function Chip({ id, snippet, claim }: { id: string; snippet?: string; claim?: Claim }) {
  const [open, setOpen] = useState(false);
  const tip = useId();
  const kind = id.split(":")[1];
  const tone =
    claim?.label === "supported" ? "border-ok/50 text-ok" : claim?.label === "partly_supported" ? "border-warn/50 text-warn" : "border-brand/40 text-brand";
  return (
    <span className="relative inline-block">
      <button
        type="button"
        aria-describedby={tip}
        className={`mx-0.5 rounded border px-1 text-[11px] font-medium ${tone}`}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        data-testid="evidence-chip"
      >
        {kind}
      </button>
      <span
        role="tooltip"
        id={tip}
        className={`${open ? "block" : "hidden"} absolute left-0 top-6 z-20 w-80 rounded-lg border border-line bg-surface p-3 text-xs shadow-lg`}
      >
        <span className="block font-medium">{id}</span>
        {claim && (
          <span className="mt-1 block text-muted">
            Claim check: <strong>{claim.label.replace("_", " ")}</strong>
            {claim.reason ? ` — ${claim.reason}` : ""}
          </span>
        )}
        <span className="mt-1 block whitespace-pre-wrap text-ink">{snippet ? snippet.slice(0, 600) : "Evidence text not loaded."}</span>
      </span>
    </span>
  );
}
