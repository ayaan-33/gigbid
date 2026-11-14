"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Schemas } from "@/lib/api/client";
import { Spinner } from "./ui";

type User = Schemas["UserOut"];
const UserCtx = createContext<User | null>(null);
export const useUser = () => useContext(UserCtx);

const NAV = [
  { href: "/inbox", label: "Inbox" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/messages", label: "Messages" },
  { href: "/runs", label: "Agent runs" },
  { href: "/analytics", label: "Analytics" },
  { href: "/settings", label: "Settings" },
];
const PUBLIC = ["/login", "/panel"];

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname() ?? "/";
  const router = useRouter();
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [menu, setMenu] = useState(false);
  const isPublic = PUBLIC.some((p) => path.startsWith(p));

  useEffect(() => {
    if (isPublic) return;
    api.GET("/api/auth/me").then((r) => {
      if (!r.data) {
        router.replace(`/login?next=${encodeURIComponent(path)}`);
        return;
      }
      setUser(r.data);
      if (!r.data.onboarded && !path.startsWith("/onboarding")) router.replace("/onboarding");
    });
  }, [path, isPublic, router]);

  if (isPublic) return <>{children}</>;
  if (!user)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Signing you in" />
      </div>
    );

  return (
    <UserCtx.Provider value={user}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 btn-primary">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
          <Link href="/inbox" className="font-semibold tracking-tight">
            Gig<span className="text-brand">Bid</span>
          </Link>
          <nav aria-label="Main" className="hidden flex-1 gap-1 md:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={path.startsWith(n.href) ? "page" : undefined}
                className={`rounded-lg px-3 py-1.5 text-sm ${path.startsWith(n.href) ? "bg-brand/10 text-brand" : "text-muted hover:text-ink"}`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-xs text-muted sm:inline">{user.name}</span>
            <button
              className="btn-ghost"
              onClick={async () => {
                await api.POST("/api/auth/logout");
                router.replace("/login");
              }}
            >
              Sign out
            </button>
            <button className="btn-ghost md:hidden" aria-expanded={menu} aria-controls="mobile-nav" onClick={() => setMenu(!menu)}>
              Menu
            </button>
          </div>
        </div>
        {menu && (
          <nav id="mobile-nav" aria-label="Main" className="border-t border-line px-4 py-2 md:hidden">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} onClick={() => setMenu(false)} className="block rounded-lg px-3 py-2 text-sm">
                {n.label}
              </Link>
            ))}
          </nav>
        )}
      </header>
      <StatusBanner />
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        {children}
      </main>
    </UserCtx.Provider>
  );
}

/** Degraded-mode banner: shown while the marketplace MCP server / GigSim is unavailable. */
export function StatusBanner() {
  const [st, setSt] = useState<Schemas["StatusOut"] | null>(null);
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const r = await api.GET("/api/status");
      if (alive) setSt(r.data ?? { marketplace: "unavailable", marketplace_mode: "?", queued_threads: 0, circuit: {}, message: "API unreachable" });
    };
    void poll();
    const t = setInterval(poll, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  if (!st || st.marketplace === "ok") return null;
  return (
    <div role="alert" data-testid="degraded-banner" className="border-b border-warn/40 bg-warn/10">
      <div className="mx-auto max-w-6xl px-4 py-2 text-sm">
        <strong className="text-warn">Marketplace unavailable.</strong>{" "}
        {st.message ?? "Work is queued and will resume automatically."}
        {st.queued_threads ? ` ${st.queued_threads} run(s) queued.` : ""}
      </div>
    </div>
  );
}
