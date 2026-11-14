"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api/client";

const PERSONAS = [
  { id: "ai_ml_engineer", title: "AI/ML engineer", desc: "LLM apps, retrieval, classical ML (synthetic demo portfolio)" },
  { id: "fullstack_dev", title: "Full-stack developer", desc: "React/Next.js, Node, Python backends (synthetic demo portfolio)" },
  { id: "data_analyst", title: "Data analyst", desc: "SQL, dashboards, reporting (synthetic demo portfolio)" },
  { id: "own_profile", title: "My own profile", desc: "Upload your CV and case studies; connect GitHub repos" },
] as const;

export default function Onboarding() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [persona, setPersona] = useState<(typeof PERSONAS)[number]["id"]>("ai_ml_engineer");
  const [rate, setRate] = useState(55);
  const [floor, setFloor] = useState(300);
  const [budget, setBudget] = useState(80);
  const [market, setMarket] = useState<"gigsim" | "upwork_live">("gigsim");
  const [search, setSearch] = useState("machine learning");
  const [files, setFiles] = useState<FileList | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>();

  async function finish() {
    setBusy(true);
    const r = await api.POST("/api/auth/onboarding", {
      body: {
        persona,
        hourly_rate: rate,
        fixed_floor: floor,
        weekly_connects_budget: budget,
        marketplace_mode: market,
        saved_search: search,
        category: null,
      },
    });
    if (!r.data) {
      setBusy(false);
      setMsg("Could not save your settings.");
      return;
    }
    if (files?.length) {
      for (const f of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", f);
        await fetch(`/api/portfolio/upload?kind=${f.name.endsWith(".pdf") ? "cv" : "case_study"}`, {
          method: "POST",
          body: fd,
          credentials: "include",
        });
      }
    }
    if (market === "upwork_live") {
      const u = await api.POST("/api/auth/upwork/start");
      const url = (u.data as { authorization_url?: string } | undefined)?.authorization_url;
      if (url) {
        window.location.href = url;
        return;
      }
    }
    await api.POST("/api/jobs/scout");
    router.replace("/inbox");
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-xl font-semibold">Set up GigBid</h1>
      <p className="mb-6 text-sm text-muted">Step {step} of 3 · GigBid drafts, you decide. Nothing is ever sent without your approval.</p>

      {step === 1 && (
        <fieldset className="space-y-3">
          <legend className="mb-2 font-medium">Whose portfolio should GigBid use?</legend>
          {PERSONAS.map((p) => (
            <label key={p.id} className={`card flex cursor-pointer gap-3 ${persona === p.id ? "border-brand" : ""}`}>
              <input type="radio" name="persona" value={p.id} checked={persona === p.id} onChange={() => setPersona(p.id)} />
              <span>
                <span className="block font-medium">{p.title}</span>
                <span className="text-sm text-muted">{p.desc}</span>
              </span>
            </label>
          ))}
          {persona === "own_profile" && (
            <label className="card block space-y-2">
              <span className="label">Upload CV (PDF) and case studies (Markdown)</span>
              <input type="file" multiple accept=".pdf,.md,.txt" onChange={(e) => setFiles(e.target.files)} />
            </label>
          )}
          <button className="btn-primary" onClick={() => setStep(2)}>
            Continue
          </button>
        </fieldset>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="space-y-1">
              <span className="label">Hourly rate (USD)</span>
              <input className="input" type="number" min={5} value={rate} onChange={(e) => setRate(+e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="label">Minimum fixed price</span>
              <input className="input" type="number" min={0} value={floor} onChange={(e) => setFloor(+e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="label">Weekly Connects budget</span>
              <input className="input" type="number" min={0} value={budget} onChange={(e) => setBudget(+e.target.value)} />
            </label>
          </div>
          <label className="block space-y-1">
            <span className="label">First saved search</span>
            <input className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="e.g. RAG chatbot" />
          </label>
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={() => setStep(1)}>
              Back
            </button>
            <button className="btn-primary" onClick={() => setStep(3)}>
              Continue
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <fieldset className="space-y-3">
            <legend className="mb-2 font-medium">Marketplace</legend>
            <label className={`card flex gap-3 ${market === "gigsim" ? "border-brand" : ""}`}>
              <input type="radio" checked={market === "gigsim"} onChange={() => setMarket("gigsim")} />
              <span>
                <span className="block font-medium">GigSim (simulator)</span>
                <span className="text-sm text-muted">Safe practice marketplace with simulated clients.</span>
              </span>
            </label>
            <label className={`card flex gap-3 ${market === "upwork_live" ? "border-brand" : ""}`}>
              <input type="radio" checked={market === "upwork_live"} onChange={() => setMarket("upwork_live")} />
              <span>
                <span className="block font-medium">Upwork (live)</span>
                <span className="text-sm text-muted">
                  Connect via Upwork&apos;s official MCP server (OAuth). GigBid only creates drafts you confirm on Upwork.
                </span>
              </span>
            </label>
          </fieldset>
          {msg && (
            <p role="alert" className="text-sm text-bad">
              {msg}
            </p>
          )}
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={() => setStep(2)}>
              Back
            </button>
            <button className="btn-primary" onClick={finish} disabled={busy} data-testid="finish-onboarding">
              {busy ? "Setting up…" : "Finish and find jobs"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
