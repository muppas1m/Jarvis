"use client";

import { useState } from "react";

import { briefSummary, relTime, urgencyLevel } from "@/lib/briefingFormat";
import type { Brief } from "@/lib/types";

/** Chip classes per semantic urgency level (mapping lives here so the pure
 *  urgencyLevel() stays free of Tailwind strings). */
const LEVEL_CLS: Record<string, string> = {
  danger: "border-danger/40 bg-danger/10 text-danger",
  warn: "border-amber/40 bg-amber/10 text-amber",
  info: "border-cyan/40 bg-cyan/10 text-cyan-soft",
};

/**
 * The proactive morning brief, surfaced at the top of the conversation
 * (persist-then-poll; the brief is Celery-driven with no active stream). Shows the
 * SAME digest the 7am Telegram push sends, rendered as structured HUD UI.
 *
 * SECURITY: every email-derived field (title / source / preview) is UNTRUSTED
 * (attacker-influenceable subjects/snippets), so each is an ESCAPED React text
 * child — never markdown, never raw HTML. The brief's structure (urgency chips,
 * day sections) is native JSX, so there is no injection surface at all (strictly
 * safer than routing subjects through a markdown renderer). Empty / multi-day /
 * urgency are handled natively; collapsible to stay out of the way.
 */
export function BriefingCard({ brief }: { brief: Brief }) {
  const [open, setOpen] = useState(true);
  const multi = brief.days.length > 1;
  const hasItems = !brief.empty && brief.total > 0 && !brief.error;

  return (
    <div className="rounded-xl border border-cyan/25 bg-cyan/5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="text-base" aria-hidden>
          ☀️
        </span>
        <span className="font-mono text-xs uppercase tracking-[0.2em] text-cyan glow">
          Morning Brief
        </span>
        <span className="truncate text-[11px] text-ink-dim">· {briefSummary(brief)}</span>
        <span className="ml-auto shrink-0 font-mono text-[10px] text-ink-dim">
          {relTime(brief.created_at)}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-cyan/60" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="space-y-2 border-t border-cyan/10 px-3 py-2">
          {brief.error ? (
            <p className="text-xs text-amber">
              I couldn&apos;t build your digest this time, Sir — I&apos;ll have it next time.
            </p>
          ) : !hasItems ? (
            <p className="text-xs text-ink-dim">Nothing new this morning, Sir.</p>
          ) : (
            brief.days.map((d) => (
              <div key={d.day} className="space-y-1">
                {multi && (
                  <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim">
                    {d.day}
                  </div>
                )}
                {d.items.map((it, i) => {
                  const lvl = urgencyLevel(it.urgency);
                  return (
                    <div key={i} className="flex items-start gap-2 text-[12px]">
                      <span className="mt-0.5 shrink-0 opacity-70" aria-hidden>
                        ✉
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          {lvl && (
                            <span
                              className={`shrink-0 rounded border px-1 font-mono text-[9px] uppercase leading-tight ${LEVEL_CLS[lvl]}`}
                            >
                              {it.urgency}
                            </span>
                          )}
                          {/* UNTRUSTED email subject → escaped text, never markdown/HTML */}
                          <span className="min-w-0 flex-1 truncate text-ink" title={it.title}>
                            {it.title || "(no subject)"}
                          </span>
                        </div>
                        {it.source && (
                          <div className="truncate text-[11px] text-ink-dim" title={it.source}>
                            {it.source}
                          </div>
                        )}
                        {it.preview && (
                          <div className="line-clamp-2 text-[11px] text-ink-dim/80">
                            {it.preview}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
