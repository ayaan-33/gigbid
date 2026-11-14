"use client";
import { useState } from "react";
import { api, ok, type Schemas } from "@/lib/api/client";
import { useData, when } from "@/lib/hooks";
import { ErrorBox, PageHeader, Spinner } from "@/components/ui";

type Settings = Schemas["SettingsOut"];

export default function SettingsPage() {
  const s = useData(async () => ok(await api.GET("/api/settings")), []);
  const searches = useData(async () => ok(await api.GET("/api/searches")), []);
  const memory = useData(async () => ok(await api.GET("/api/memory")), []);
  const upwork = useData(async () => (await api.GET("/api/auth/upwork/status")).data as { connected?: boolean } | undefined, []);
  const [saved, setSaved] = useState<string>();
  const [newSearch, setNewSearch] = useState({ name: "", query: "" });
  const [uploadMsg, setUploadMsg] = useState<string>();

  if (s.error) return <ErrorBox error={s.error} onRetry={s.refresh} />;
  if (!s.data) return <Spinner label="Loading settings" />;
  const cur = s.data;

  async function patch(v: Partial<Settings>) {
    const r = await api.PATCH("/api/settings", { body: v as never });
    if (r.data) {
      s.setData(r.data);
      setSaved("Saved");
      setTimeout(() => setSaved(undefined), 1500);
    }
  }

  return (
    <>
      <PageHeader title="Settings" sub={saved ?? "Autonomy, budgets, searches, accounts and what GigBid has learned."} />
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card space-y-3" aria-labelledby="auto-h">
          <h2 id="auto-h" className="font-medium">
            Autonomy and budgets
          </h2>
          <fieldset className="space-y-2 text-sm">
            <legend className="label mb-1">Autonomy</legend>
            <label className="flex gap-2">
              <input type="radio" checked={cur.autonomy === "suggest"} onChange={() => patch({ autonomy: "suggest" })} />
              Suggest only: I confirm every skip and every send
            </label>
            <label className="flex gap-2">
              <input type="radio" checked={cur.autonomy === "auto_skip"} onChange={() => patch({ autonomy: "auto_skip" })} />
              Auto-skip low-fit jobs (sending always needs my approval)
            </label>
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1">
              <span className="label">Weekly Connects</span>
              <input
                className="input"
                type="number"
                defaultValue={cur.weekly_connects_budget}
                onBlur={(e) => patch({ weekly_connects_budget: +e.target.value })}
              />
            </label>
            <label className="space-y-1">
              <span className="label">Hourly rate</span>
              <input className="input" type="number" defaultValue={cur.hourly_rate ?? ""} onBlur={(e) => patch({ hourly_rate: +e.target.value })} />
            </label>
            <label className="space-y-1">
              <span className="label">Fixed floor</span>
              <input className="input" type="number" defaultValue={cur.fixed_floor ?? ""} onBlur={(e) => patch({ fixed_floor: +e.target.value })} />
            </label>
          </div>
          <p className="text-xs text-muted">{cur.connects_spent_this_week} Connects spent in the last 7 days.</p>
          <label className="block space-y-1">
            <span className="label">Proposal strategy</span>
            <select className="input" value={cur.strategy_mode} onChange={(e) => patch({ strategy_mode: e.target.value as Settings["strategy_mode"] })}>
              <option value="ab_test">A/B test (evidence-first vs question-led)</option>
              <option value="evidence_first">Evidence first</option>
              <option value="question_led">Question led</option>
              <option value="default">Default</option>
            </select>
          </label>
        </section>

        <section className="card space-y-3" aria-labelledby="acct-h">
          <h2 id="acct-h" className="font-medium">
            Connected accounts
          </h2>
          <div className="flex items-center justify-between text-sm">
            <span>GigSim (simulator)</span>
            <span className="badge bg-ok/15 text-ok">connected</span>
          </div>
          <div className="flex items-center justify-between gap-2 text-sm">
            <span>Upwork (official MCP, drafts only)</span>
            {upwork.data?.connected ? (
              <button
                className="btn-ghost"
                onClick={async () => {
                  await api.POST("/api/auth/upwork/disconnect");
                  upwork.refresh();
                }}
              >
                Disconnect
              </button>
            ) : (
              <button
                className="btn-primary"
                onClick={async () => {
                  const r = await api.POST("/api/auth/upwork/start");
                  const url = (r.data as { authorization_url?: string } | undefined)?.authorization_url;
                  if (url) window.location.href = url;
                }}
              >
                Connect Upwork
              </button>
            )}
          </div>
          <p className="text-xs text-muted">Active marketplace: {cur.marketplace_mode}</p>
          <label className="block space-y-1 border-t border-line pt-3">
            <span className="label">Add portfolio work (re-indexed instantly)</span>
            <input
              type="file"
              accept=".pdf,.md,.txt"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                const fd = new FormData();
                fd.append("file", f);
                const r = await fetch(`/api/portfolio/upload?kind=${f.name.endsWith(".pdf") ? "cv" : "case_study"}`, {
                  method: "POST",
                  body: fd,
                  credentials: "include",
                });
                const j = await r.json();
                setUploadMsg(r.ok ? `Indexed ${j.indexed_chunks} chunks.` : String(j.detail ?? "Upload failed"));
              }}
            />
          </label>
          {uploadMsg && <p className="text-xs text-muted">{uploadMsg}</p>}
        </section>

        <section className="card space-y-3" aria-labelledby="search-h">
          <h2 id="search-h" className="font-medium">
            Saved searches
          </h2>
          <ul className="space-y-1 text-sm">
            {searches.data?.map((x) => (
              <li key={x.id} className="flex items-center justify-between gap-2">
                <span>
                  {x.name} <span className="text-xs text-muted">“{x.query}” · every {x.interval_minutes} min · last {when(x.last_run_at)}</span>
                </span>
                <button
                  className="text-xs text-bad"
                  aria-label={`Delete search ${x.name}`}
                  onClick={async () => {
                    await api.DELETE("/api/searches/{sid}", { params: { path: { sid: x.id } } });
                    searches.refresh();
                  }}
                >
                  delete
                </button>
              </li>
            ))}
          </ul>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              await api.POST("/api/searches", {
                body: { name: newSearch.name || newSearch.query, query: newSearch.query, category: null, skills: [], interval_minutes: 30, enabled: true },
              });
              setNewSearch({ name: "", query: "" });
              searches.refresh();
            }}
          >
            <input className="input flex-1" placeholder="Keywords" aria-label="Search keywords" value={newSearch.query} onChange={(e) => setNewSearch({ ...newSearch, query: e.target.value })} required />
            <button className="btn-ghost">Add</button>
          </form>
        </section>

        <section className="card space-y-3" aria-labelledby="mem-h">
          <h2 id="mem-h" className="font-medium">
            What GigBid has learned
          </h2>
          <p className="text-xs text-muted">Only patterns that pass the promotion rules are remembered. Delete anything you disagree with.</p>
          <ul className="space-y-2 text-sm" data-testid="memory-list">
            {memory.data?.map((m) => (
              <li key={`${m.kind}:${m.key}`} className="flex items-start justify-between gap-2 rounded border border-line p-2">
                <span>
                  <span className="badge mr-1 bg-line">{m.kind}</span>
                  {m.rule}
                  {m.support ? <span className="text-xs text-muted"> (seen in {m.support} of your last {m.window} edits)</span> : null}
                </span>
                <button
                  className="text-xs text-bad"
                  onClick={async () => {
                    await api.DELETE("/api/memory/{kind}/{key}", { params: { path: { kind: m.kind, key: m.key } } });
                    memory.refresh();
                  }}
                >
                  forget
                </button>
              </li>
            ))}
            {memory.data?.length === 0 && <li className="text-muted">Nothing learned yet. Edit a few drafts and GigBid picks up your style.</li>}
          </ul>
        </section>
      </div>
    </>
  );
}
