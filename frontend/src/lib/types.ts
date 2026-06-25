/** Orb / agent visible states. 4.0 ships idle + thinking + responding; 4.2
 *  lights up listening. Colours map in components/Orb.tsx. */
export type AgentState = "idle" | "listening" | "thinking" | "responding";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

/** A live approval the master must decide, rendered as an inline card in the
 *  chat (A2). Normalized from the `approval_required` stream event (interrupt
 *  payload). `tool_args` is the REAL structured action — rendered field-by-field
 *  so the card shows exactly what will execute, never an LLM re-summary. */
export type ApprovalStatus =
  | "pending"
  | "resolving"
  | "approved"
  | "rejected"
  | "discarded" // superseded by an edit — kept in the stream, greyed
  | "skipped"; // deferred "not now" (session-local, DB-inert) — greyed; reappears on reload

/** Which origin a card came from. "email" = an inbound auto-drafted reply;
 *  "tool" = a chat-queued APPROVE-tier tool call. The backend's UnifiedApprovalCard
 *  carries this (the SAME discriminator dispatch uses); the card renders off it. */
export type ApprovalKind = "email" | "tool";

export interface ApprovalRequest {
  approval_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  description?: string;
  status: ApprovalStatus;
  kind?: ApprovalKind; // present for queue/poll-surfaced cards; inferred otherwise
}

/** An in-chat document upload (A3), shown live in the timeline. Transient
 *  (client-side) — the backend appends a persistent "📎 Indexed …" marker that
 *  re-renders as a message on reload. Sync endpoint, so status = request
 *  lifecycle (no polling). */
export interface UploadItem {
  name: string;
  status: "uploading" | "done" | "error";
  chunks?: number;
  dedup?: boolean;
  replaced?: boolean;
  error?: string;
}

/** Context-meter snapshot (4.B.3): the thread's token usage vs the compaction
 *  threshold, tiered recent-verbatim + rolling-summary. `compacted` is the live
 *  "just compacted" signal — true only in a turn's done event, never on reload. */
export interface ContextMeter {
  used_tokens: number;
  threshold_tokens: number;
  recent_tokens: number;
  summary_tokens: number;
  compacted: boolean;
}

/** One row of the chat timeline: a message bubble, a decision card, a document
 *  upload, or a compaction divider. The whole conversation (incl.
 *  resolved/discarded cards) is an ordered StreamItem[] so a reload re-renders
 *  everything in conversation position. The divider is live-only (not persisted). */
export type StreamItem =
  | { type: "message"; id: string; role: "user" | "assistant"; content: string }
  | { type: "decision"; id: string; approval: ApprovalRequest }
  | { type: "upload"; id: string; upload: UploadItem }
  | { type: "divider"; id: string; label: string };

/** SSE event contract — mirrors app.agent.runner.stream_turn exactly. */
export type StreamEvent =
  | { type: "thread_id"; content: string }
  | { type: "token"; content: string }
  | { type: "tool"; content: string }
  | { type: "audio"; content: { text: string; audio: string; mime: string; filler: boolean } }
  | { type: "approval_required"; thread_id: string; content: Record<string, unknown> }
  | {
      type: "decision_resolved";
      thread_id: string;
      content: { approval_id: string; status: string };
    }
  | {
      type: "done";
      content: {
        status: string;
        stop_reason?: string;
        response: string;
        usage?: unknown;
        thread_id: string;
        context?: ContextMeter;
      };
    }
  | { type: "error"; content: string; stop_reason?: string };

/** Real VM telemetry (4.C.2) — mirrors backend app.api.system.SystemStats.
 *  /proc-backed; `null` fields = that read failed (widget shows "—"). */
export interface SystemStats {
  cpu_pct: number | null;
  cpu_count: number;
  mem_used_mb: number | null;
  mem_total_mb: number | null;
  disk_used_gb: number | null;
  disk_total_gb: number | null;
  load_1m: number | null;
  load_5m: number | null;
  load_15m: number | null;
  uptime_s: number;
  session_turns: number;
  today_turns: number;
}

export type SubsystemStatus = "ok" | "degraded" | "down" | "skipped";

/** Grouped subsystem health (4.C.2) — mirrors backend health_groups(). The ring
 *  reads `status` per group; the expand lists `members`. */
export interface HealthGroup {
  status: SubsystemStatus;
  members: { name: string; status: SubsystemStatus }[];
}
export interface GroupedHealth {
  status: "ok" | "degraded";
  groups: Record<string, HealthGroup>;
}

/** Current weather (4.C.3) — mirrors backend app.api.weather.WeatherResponse. */
export interface Weather {
  location: string;
  temp: number | null;
  temp_unit: string;
  condition: string;
  glyph: string;
  humidity: number | null;
  wind: number | null;
  wind_unit: string;
}

/** 24h activity (4.C.3) — mirrors backend app.api.activity.ActivityResponse.
 *  Master-facing phrasing already applied server-side. */
export interface ActivityItem {
  glyph: string;
  text: string;
  when: string; // ISO-8601
  kind: string; // action | email | memory
}
export interface ActivitySummaryRow {
  glyph: string;
  label: string;
  count: number;
}
export interface Activity {
  summary: ActivitySummaryRow[];
  feed: ActivityItem[];
}
