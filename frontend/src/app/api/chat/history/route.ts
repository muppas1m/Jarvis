import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/** BFF: replay a thread's persisted history (proxy to backend /api/chat/history).
 *  The browser never sees the backend URL or its API key. */
export async function GET(req: Request): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  // thread_id is optional — when absent the backend resolves the master's
  // canonical (server-authoritative) thread. Forward it only if explicitly given.
  const threadId = new URL(req.url).searchParams.get("thread_id");
  const qs = threadId ? `?thread_id=${encodeURIComponent(threadId)}` : "";
  const upstream = await backendFetch(`/api/chat/history${qs}`);
  const data = await upstream.json().catch(() => ({ messages: [] }));
  return Response.json(data, { status: upstream.status });
}
