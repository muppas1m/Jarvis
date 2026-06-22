import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/** BFF: 24h activity summary + feed (proxy to backend /api/activity). */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/activity");
  const data = await upstream.json().catch(() => ({}));
  return Response.json(data, { status: upstream.status });
}
