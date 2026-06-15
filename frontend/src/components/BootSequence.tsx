"use client";

import { useEffect, useState } from "react";

const LINES = [
  "INITIALISING  J.A.R.V.I.S.",
  "▸ core systems ............ ONLINE",
  "▸ memory matrix ........... ONLINE",
  "▸ language cortex ......... ONLINE",
  "▸ safety governor ......... ARMED",
  "▸ secure uplink ........... ESTABLISHED",
  "WELCOME BACK, SIR.",
];

/** Stark-style boot overlay. Plays once per browser session (sessionStorage
 *  gate), then fades. Purely cosmetic — never blocks interaction for long. */
export function BootSequence() {
  const [shown, setShown] = useState(0);
  const [done, setDone] = useState(false);
  const [skip, setSkip] = useState(true);

  useEffect(() => {
    if (sessionStorage.getItem("jarvis_booted") === "1") {
      setDone(true);
      return;
    }
    setSkip(false);
  }, []);

  useEffect(() => {
    if (skip || done) return;
    if (shown < LINES.length) {
      const t = setTimeout(() => setShown((n) => n + 1), shown === 0 ? 220 : 260);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => {
      sessionStorage.setItem("jarvis_booted", "1");
      setDone(true);
    }, 750);
    return () => clearTimeout(t);
  }, [shown, skip, done]);

  if (done || skip) return null;

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
