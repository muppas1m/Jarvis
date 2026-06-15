"use client";

import { useState } from "react";

import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";

import { markBootPending } from "@/lib/boot";

export default function LoginPage() {
  const [passkey, setPasskey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await signIn("credentials", { passkey, redirect: false });
    setBusy(false);
    if (res?.error) {
      setError("Passkey not recognised, Sir.");
      return;
    }
    markBootPending(); // play the boot sequence on this login
    router.push("/chat");
    router.refresh();
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="glass-strong glow-box w-full max-w-sm rounded-2xl p-8"
      >
        <div className="mb-1 text-center font-mono text-2xl tracking-[0.3em] text-cyan glow">
          J.A.R.V.I.S.
        </div>
        <p className="mb-6 text-center text-xs text-ink-dim">
          Just A Rather Very Intelligent System
        </p>

        <label className="mb-2 block text-xs uppercase tracking-widest text-ink-dim">
          Passkey
        </label>
        <input
          type="password"
          autoFocus
          value={passkey}
          onChange={(e) => setPasskey(e.target.value)}
          placeholder="••••••••••••"
          className="mb-4 w-full rounded-lg border border-cyan/30 bg-black/30 px-4 py-3 font-mono text-ink outline-none focus:border-cyan focus:ring-1 focus:ring-cyan/50"
        />

        {error && <p className="mb-4 text-sm text-danger">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg border border-cyan/50 bg-cyan/10 py-3 font-mono uppercase tracking-widest text-cyan transition hover:bg-cyan/20 disabled:opacity-50"
        >
          {busy ? "Authenticating…" : "Authenticate"}
        </button>
      </form>
    </main>
  );
}
