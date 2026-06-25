import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/**
 * BFF: the unified approval QUEUE — inbound email replies AND chat-queued
 * APPROVE-tier tool calls, oldest-first, both origins (proxy to backend
 * /api/approvals/queue). Returns {approvals: UnifiedApprovalCard[], count}. The
 * HUD polls this, dedups by approval_id against the timeline, and presents one
 * card at a time.
 */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/approvals/queue");
  const data = await upstream.json().catch(() => ({}));
  return Response.json(data, { status: upstream.status });
}
