"use client";
import { useState } from "react";
import { api, ok } from "@/lib/api/client";
import { useData } from "@/lib/hooks";
import { ErrorBox, Spinner } from "@/components/ui";

/** Public blind pairwise panel: which proposal would you, as the client, reply to? */
export default function Panel() {
  const pairs = useData(async () => ok(await api.GET("/api/panel/pairs")), []);
  const [voter, setVoter] = useState("");
  const [started, setStarted] = useState(false);
  const [i, setI] = useState(0);
  const [busy, setBusy] = useState(false);

  if (pairs.error) return <ErrorBox error={pairs.error} />;
  if (!pairs.data) return <Spinner label="Loading pairs" />;
  const list = pairs.data;
  const cur = list[i];

  async function vote(choice: "left" | "right" | "tie") {
    if (!cur) return;
    setBusy(true);
    await api.POST("/api/panel/vote", { body: { voter, pair_id: cur.pair_id, choice } });
    setBusy(false);
    setI(i + 1);
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-xl font-semibold">GigBid proposal panel</h1>
      <p className="mt-1 text-sm text-muted">
        Read the job, then pick the proposal you would reply to as the client. Proposals are anonymised and shown in random order.
      </p>
      {!started ? (
        <form
          className="card mt-6 max-w-sm space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            setStarted(true);
          }}
        >
          <label className="block space-y-1">
            <span className="label">Nickname (no real name needed)</span>
            <input className="input" value={voter} onChange={(e) => setVoter(e.target.value)} minLength={2} required />
          </label>
          <button className="btn-primary">Start ({list.length} pairs)</button>
        </form>
      ) : !cur ? (
        <div className="card mt-6 text-center">
          <p className="font-medium">Thank you! All {list.length} pairs rated.</p>
        </div>
      ) : (
        <div className="mt-6 space-y-4">
          <p className="text-sm text-muted">
            Pair {i + 1} of {list.length}
          </p>
          <section className="card">
            <h2 className="font-medium">{cur.job_title}</h2>
            <p className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-sm text-muted">{cur.job_description}</p>
          </section>
          <div className="grid gap-4 md:grid-cols-2">
            {(["left", "right"] as const).map((side) => (
              <section key={side} className="card flex flex-col">
                <h3 className="label mb-2">Proposal {side === "left" ? "1" : "2"}</h3>
                <p className="flex-1 whitespace-pre-wrap text-sm">{side === "left" ? cur.left : cur.right}</p>
                <button className="btn-primary mt-3" disabled={busy} onClick={() => vote(side)}>
                  I would reply to proposal {side === "left" ? "1" : "2"}
                </button>
              </section>
            ))}
          </div>
          <button className="btn-ghost" disabled={busy} onClick={() => vote("tie")}>
            No clear preference
          </button>
        </div>
      )}
    </main>
  );
}
