"use client";

import type { UploadItem } from "@/lib/types";

/** Inline document-upload status (A3). Sync endpoint → one in-flight state then a
 *  terminal one: Indexing… → Indexed N chunks / Already indexed / Re-indexed /
 *  an inline error (unsupported type, too large, ingestion failure). */
export function UploadChip({ upload }: { upload: UploadItem }) {
  const { name, status, chunks, dedup, replaced, error } = upload;
  const busy = status === "uploading";
  const isError = status === "error";

  const detail = isError
    ? (error ?? "Upload failed")
    : busy
      ? "Indexing…"
      : dedup
        ? "Already indexed"
        : replaced
          ? `Re-indexed — ${chunks ?? 0} chunks (latest pipeline)`
          : `Indexed — ${chunks ?? 0} chunks`;

  return (
    <div
      className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-sm ${
        isError
          ? "border-danger/40 bg-danger/5 text-danger"
          : "border-cyan/25 bg-cyan/5 text-ink"
      }`}
    >
      <span className={busy ? "animate-pulse" : ""}>📎</span>
      <span className="truncate font-medium">{name}</span>
      <span
        className={`ml-auto whitespace-nowrap text-xs ${
          isError ? "text-danger" : busy ? "animate-pulse text-cyan" : "text-ink-dim"
        }`}
      >
        {detail}
      </span>
    </div>
  );
}
