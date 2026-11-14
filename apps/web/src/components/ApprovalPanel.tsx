"use client";
import { useState } from "react";
import { api } from "@/lib/api/client";

type Any = Record<string, unknown>;

/** Approve / edit / reject a paused LangGraph thread. The dry-run preview shows exactly what will
 *  be sent and what it costs; nothing reaches the marketplace without this approval. */
export function ApprovalPanel({
  threadId,
  dryRun,
  editedText,
  dirty,
  onDone,
  kind = "proposal",
}: {
  threadId: string;
  dryRun: Any;
  editedText: string;
  dirty: boolean;
  onDone: (action: string) => void;
  kind?: "proposal" | "message";
}) {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function send(action: "approve" | "edit" | "reject") {
    setBusy(true);
    setError(undefined);
    const body =
      action === "edit" ? { action, edited_text: editedText } : action === "reject" ? { action, reason } : { action };
    const r = await api.POST("/api/approvals/{thread_id}", { params: { path: { thread_id: threadId } }, body });
    setBusy(false);
    if (r.error) {
      const d = (r.error as { detail?: unknown }).detail;
      setError(typeof d === "string" ? d : "Could not send your decision.");
      return;
    }
    onDone(action);
  }

  const cost = dryRun?.connects_cost as number | undefined;
  return (
    <section className="card space-y-3" aria-labelledby="approve-h">
      <h2 id="approve-h" className="font-medium">
        Your decision
      </h2>
      <div className="rounded-lg bg-line/40 p-3 text-sm" data-testid="dry-run">
        <p className="label mb-1">Dry run: what will happen</p>
        {kind === "proposal" ? (
          <>
            <p>
              Submit proposal to job <strong>{String((dryRun?.payload as Any)?.job_id ?? "")}</strong> for{" "}
              <strong>${String((dryRun?.payload as Any)?.bid_amount ?? "?")}</strong>
            </p>
            <p>
              Costs <strong>{cost ?? "?"} Connects</strong> · balance {String(dryRun?.connects_balance ?? "?")} →{" "}
              {String(dryRun?.connects_balance_after ?? "?")}
            </p>
          </>
        ) : (
          <p>Send this reply in the client conversation{dryRun?.also ? `; ${String(dryRun.also)}` : ""}.</p>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}
      {!rejecting ? (
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary" disabled={busy} onClick={() => send(dirty ? "edit" : "approve")} data-testid="approve">
            {dirty ? "Approve my edited version" : "Approve and send"}
          </button>
          <button className="btn-danger" disabled={busy} onClick={() => setRejecting(true)} data-testid="reject">
            Reject
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <label className="block space-y-1">
            <span className="label">Why are you rejecting it?</span>
            <input
              className="input"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. too generic, wrong project, not worth the Connects"
              data-testid="reject-reason"
            />
          </label>
          <div className="flex gap-2">
            <button className="btn-danger" disabled={busy || !reason.trim()} onClick={() => send("reject")} data-testid="confirm-reject">
              Confirm reject
            </button>
            <button className="btn-ghost" onClick={() => setRejecting(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      <p className="text-xs text-muted">Edits are re-checked by the Compliance Guard and remembered as style preferences.</p>
    </section>
  );
}
