/** Orb / agent visible states. 4.0 ships idle + thinking + responding; 4.2
 *  lights up listening. Colours map in components/Orb.tsx. */
export type AgentState = "idle" | "listening" | "thinking" | "responding";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

/** A live approval the master must decide, rendered as an inline card in the
 *  chat (A2). Normalized from EITHER the `approval_required` stream event
 *  (interrupt payload) OR GET /api/approvals (a pending row). `tool_args` is the
 *  REAL structured action — rendered field-by-field so the card shows exactly
 *  what will execute, never an LLM re-summary. */
export type ApprovalStatus =
  | "pending"
  | "resolving"
  | "approved"
  | "rejected"
  | "discarded"; // superseded by an edit — kept in the stream, greyed

export interface ApprovalRequest {
  approval_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  description?: string;
  status: ApprovalStatus;
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

/** One row of the chat timeline: a message bubble, a decision card, or a
 *  document upload. The whole conversation (incl. resolved/discarded cards) is an
 *  ordered StreamItem[] so a reload re-renders everything in conversation
 *  position. */
export type StreamItem =
  | { type: "message"; id: string; role: "user" | "assistant"; content: string }
  | { type: "decision"; id: string; approval: ApprovalRequest }
  | { type: "upload"; id: string; upload: UploadItem };

/** Mirrors backend PendingApprovalView (app/api/approvals.py). */
export interface ApprovalView {
  id: string;
  thread_id: string;
  action_type: string;
  description: string;
  payload: Record<string, unknown>;
  created_at: string;
  expires_at: string;
}

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
      };
    }
  | { type: "error"; content: string; stop_reason?: string };
