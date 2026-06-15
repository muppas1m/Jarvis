/** Orb / agent visible states. 4.0 ships idle + thinking + responding; 4.2
 *  lights up listening. Colours map in components/Orb.tsx. */
export type AgentState = "idle" | "listening" | "thinking" | "responding";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

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
  | { type: "approval_required"; thread_id: string; content: Record<string, unknown> }
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
