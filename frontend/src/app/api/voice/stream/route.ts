import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * BFF streaming proxy for the voice turn. Verifies the session, then pipes the
 * backend's SSE (token + per-sentence audio events) straight through. Same
 * boundary as /api/chat/stream — no secret in the browser.
 */
export async function POST(req: Request): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return new Response("unauthorized", { status: 401 });
  }

  const body = await req.text();
  const upstream = await backendFetch("/api/voice/stream", { method: "POST", body });

  if (!upstream.ok || !upstream.body) {
    return new Response(`backend error: ${upstream.status}`, { status: 502 });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
