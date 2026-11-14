"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/** Load data with loading/error state and optional polling. */
export function useData<T>(load: () => Promise<T>, deps: unknown[] = [], pollMs?: number) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });
  const refresh = useCallback(async () => {
    try {
      setData(await loadRef.current());
      setError(undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    if (!pollMs) return;
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, refresh, setData };
}

export function fmtMoney(n?: number | null, unit?: string | null) {
  if (n === undefined || n === null) return "—";
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}${unit === "hourly" ? "/hr" : ""}`;
}

export function pct(n?: number | null) {
  return n === undefined || n === null ? "—" : `${Math.round(n * 100)}%`;
}

export function when(d?: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
