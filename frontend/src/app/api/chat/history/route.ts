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
  const threadId = new URL(req.url).searchParams.get("thread_id");
  if (!threadId) {
    return Response.json({ error: "thread_id required" }, { status: 400 });
  }
  const upstream = await backendFetch(
    `/api/chat/history?thread_id=${encodeURIComponent(threadId)}`,
  );
  const data = await upstream
    .json()
    .catch(() => ({ thread_id: threadId, messages: [] }));
  return Response.json(data, { status: upstream.status });
}
