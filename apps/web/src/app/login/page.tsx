"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api/client";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    const r =
      mode === "login"
        ? await api.POST("/api/auth/login", { body: { email, password } })
        : await api.POST("/api/auth/register", { body: { email, password, name } });
    setBusy(false);
    if (!r.data) {
      const d = (r.error as { detail?: unknown })?.detail;
      setError(typeof d === "string" ? d : "Please check the form and try again.");
      return;
    }
    router.replace(r.data.onboarded ? (params.get("next") ?? "/inbox") : "/onboarding");
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4" aria-labelledby="login-title">
        <div>
          <h1 id="login-title" className="text-xl font-semibold">
            Gig<span className="text-brand">Bid</span>
          </h1>
          <p className="text-sm text-muted">Find good jobs, write proposals you can prove, stay in control.</p>
        </div>
        {mode === "register" && (
          <label className="block space-y-1">
            <span className="label">Name</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
          </label>
        )}
        <label className="block space-y-1">
          <span className="label">Email</span>
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label className="block space-y-1">
          <span className="label">Password</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-bad">
            {error}
          </p>
        )}
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button type="button" className="w-full text-sm text-brand" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
