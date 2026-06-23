"use client";

import Markdown from "markdown-to-jsx";

/**
 * Renders an assistant message's markdown as real, HUD-themed formatting
 * (cyan/glass, not stock) for the chat transcript — the READ surface. The spoken
 * path strips markdown separately on the backend, so this only governs display.
 *
 * Streaming/partial: markdown-to-jsx re-parses the whole string on each render,
 * so mid-stream an as-yet-unclosed `**` shows as literal text until its closer
 * arrives, then snaps to bold — the standard streaming-markdown behaviour. The
 * final render is always correct.
 *
 * markdown-to-jsx over react-markdown: a single, light dependency (no remark/
 * micromark tree), themeable per-element via `overrides`, safe by default (no
 * raw-HTML injection), React-version-agnostic (pure JSX — no React-19 risk).
 */
const OPTIONS = {
  // Force block rendering so a one-line answer still gets a <p> (consistent
  // spacing), and multi-paragraph answers lay out properly.
  forceBlock: true,
  overrides: {
    h1: {
      props: {
        className:
          "mb-1 mt-2 font-mono text-base font-semibold uppercase tracking-wide text-cyan glow",
      },
    },
    h2: {
      props: {
        className: "mb-1 mt-2 font-mono text-sm font-semibold uppercase tracking-wide text-cyan-soft",
      },
    },
    h3: { props: { className: "mb-1 mt-1.5 font-mono text-sm font-semibold text-cyan-soft" } },
    h4: { props: { className: "mb-1 mt-1.5 font-mono text-sm font-semibold text-cyan-soft" } },
    p: { props: { className: "my-1 leading-relaxed" } },
    strong: { props: { className: "font-semibold text-cyan-soft" } },
    em: { props: { className: "italic text-ink" } },
    a: {
      props: {
        className:
          "text-cyan underline decoration-cyan/40 underline-offset-2 transition hover:text-cyan-soft",
        target: "_blank",
        rel: "noopener noreferrer",
      },
    },
    ul: { props: { className: "my-1 ml-4 list-disc space-y-0.5 marker:text-cyan/60" } },
    ol: { props: { className: "my-1 ml-4 list-decimal space-y-0.5 marker:text-cyan/60" } },
    li: { props: { className: "pl-0.5" } },
    code: {
      props: {
        className: "rounded bg-cyan/10 px-1 py-0.5 font-mono text-[0.85em] text-cyan-soft",
      },
    },
    pre: {
      props: {
        className:
          "my-1.5 overflow-x-auto rounded-lg border border-cyan/15 bg-black/40 p-2 font-mono text-xs",
      },
    },
    blockquote: {
      props: { className: "my-1 border-l-2 border-cyan/40 pl-3 italic text-ink-dim" },
    },
    hr: { props: { className: "my-2 border-cyan/15" } },
    table: { props: { className: "my-1.5 w-full border-collapse text-xs" } },
    th: {
      props: { className: "border border-cyan/20 px-2 py-1 text-left font-semibold text-cyan-soft" },
    },
    td: { props: { className: "border border-cyan/15 px-2 py-1" } },
  },
};

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <Markdown options={OPTIONS}>{content}</Markdown>
    </div>
  );
}
