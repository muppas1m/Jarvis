import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/**
 * BFF: synthesize Jarvis reading a freshly-surfaced inbound approval card aloud
 * (proxy to backend /api/voice/announce-approval). Body {approval_id, first?};
 * returns {text, audio(b64), mime} for the client to play through the same audio
 * path as the voice stream's `audio` events.
 */
export async function POST(req: Request): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const body = await req.text();
  const upstream = await backendFetch("/api/voice/announce-approval", {
    method: "POST",
    body,
  });
  const data = await upstream.json().catch(() => ({}));
  return Response.json(data, { status: upstream.status });
}
