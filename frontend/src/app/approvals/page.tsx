"use client";

import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import type { ApprovalView } from "@/lib/types";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<ApprovalView[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/approvals", { cache: "no-store" });
      const data = res.ok ? ((await res.json()) as ApprovalView[]) : [];
      setApprovals(Array.isArray(data) ? data : []);
    } catch {
      setApprovals([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000); // poll while open
    return () => clearInterval(t);
  }, [load]);

  async function decide(id: string, approved: boolean) {
    setBusyId(id);
    try {
      await fetch(`/api/approvals/${id}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
      await load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="mx-auto min-h-screen max-w-3xl p-5">
      <header className="glass mb-4 flex items-center justify-between rounded-xl px-4 py-2">
        <h1 className="font-mono text-lg tracking-[0.3em] text-cyan glow">APPROVALS</h1>
        <Link
          href="/chat"
          className="text-xs uppercase tracking-widest text-ink-dim transition hover:text-cyan"
        >
          ← Back
        </Link>
      </header>

      {loading ? (
        <p className="p-6 text-center text-sm text-ink-dim">Loading…</p>
      ) : approvals.length === 0 ? (
        <p className="glass rounded-xl p-8 text-center text-sm text-ink-dim">
          Nothing awaiting your approval, Sir.
        </p>
      ) : (
        <div className="space-y-3">
          {approvals.map((a) => (
            <div key={a.id} className="glass rounded-xl p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="rounded border border-amber/40 bg-amber/10 px-2 py-0.5 font-mono text-xs uppercase tracking-wider text-amber">
                  {a.action_type}
                </span>
                <span className="text-xs text-ink-dim">
                  {new Date(a.created_at).toLocaleString()}
                </span>
              </div>
              <pre className="mb-3 whitespace-pre-wrap break-words font-mono text-xs text-ink">
                {a.description}
              </pre>
              <div className="flex gap-2">
                <button
                  disabled={busyId === a.id}
                  onClick={() => decide(a.id, true)}
                  className="rounded-lg border border-ok/50 bg-ok/10 px-4 py-1.5 font-mono text-sm uppercase tracking-widest text-ok transition hover:bg-ok/20 disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  disabled={busyId === a.id}
                  onClick={() => decide(a.id, false)}
                  className="rounded-lg border border-danger/50 bg-danger/10 px-4 py-1.5 font-mono text-sm uppercase tracking-widest text-danger transition hover:bg-danger/20 disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
