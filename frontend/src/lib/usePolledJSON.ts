"use client";

import { useEffect, useRef, useState } from "react";

export interface PolledState<T> {
  /** Last successful payload, or null before the first success. */
  data: T | null;
  /** The most recent poll failed (network/HTTP) — widgets show a clean offline
   *  state rather than a stale lie. */
  error: boolean;
  /** True until the first response settles (success or failure). */
  loading: boolean;
}

/**
 * The one shared polling hook for the dashboard's fetch-backed widgets (4.C.2).
 * Polls `url` every `intervalMs`, JSON-decoded, with graceful degradation:
 * a failed poll flips `error` true (and never throws) so each widget can render
 * "—"/offline. No fetch during SSR (effect is client-only). Self-cleaning on
 * unmount + on url/interval change.
 */
export function usePolledJSON<T>(url: string, intervalMs: number): PolledState<T> {
  const [state, setState] = useState<PolledState<T>>({
    data: null,
    error: false,
    loading: true,
  });
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let alive = true;

    const tick = async () => {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const json = (await res.json()) as T;
        if (alive) setState({ data: json, error: false, loading: false });
      } catch {
        // Keep last-good in state, but flag error so widgets render offline —
        // never present stale data as live.
        if (alive) setState((s) => ({ data: s.data, error: true, loading: false }));
      } finally {
        if (alive) timer.current = setTimeout(tick, intervalMs);
      }
    };

    tick();
    return () => {
      alive = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [url, intervalMs]);

  return state;
}
