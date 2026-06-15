"use client";

import { useEffect, useState } from "react";

import { consumeBootPending } from "@/lib/boot";

const LINES = [
  "INITIALISING  J.A.R.V.I.S.",
  "▸ core systems ............ ONLINE",
  "▸ memory matrix ........... ONLINE",
  "▸ language cortex ......... ONLINE",
  "▸ safety governor ......... ARMED",
  "▸ secure uplink ........... ESTABLISHED",
  "WELCOME BACK, SIR.",
];

/**
 * Stark-style boot overlay. Plays once per *login* (login sets a boot_pending
 * flag that this consumes on mount), then fades. A plain page reload does not
 * set the flag, so it does not replay. Purely cosmetic.
 */
export function BootSequence() {
  const [shown, setShown] = useState(0);
  // "check" until the mount effect decides; renders null on server + first
  // client render (no hydration mismatch), then flips to playing/done.
  const [phase, setPhase] = useState<"check" | "playing" | "done">("check");

  useEffect(() => {
    setPhase(consumeBootPending() ? "playing" : "done");
  }, []);

  useEffect(() => {
    if (phase !== "playing") return;
    if (shown < LINES.length) {
      const t = setTimeout(() => setShown((n) => n + 1), shown === 0 ? 220 : 260);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setPhase("done"), 750);
    return () => clearTimeout(t);
  }, [phase, shown]);

  if (phase !== "playing") return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#070b18]">
      <div className="font-mono text-sm text-cyan glow space-y-1">
        {LINES.slice(0, shown).map((l, i) => (
          <div key={i} className={i === LINES.length - 1 ? "mt-3 text-base" : ""}>
            {l}
          </div>
        ))}
        <span className="caret" />
      </div>
    </div>
  );
}
