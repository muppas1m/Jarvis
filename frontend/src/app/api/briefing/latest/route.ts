import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/** BFF: the latest proactive morning brief, if within the freshness window
 *  (proxy to backend /api/briefing/latest). `{ brief: null }` when none. */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/briefing/latest");
  const data = await upstream.json().catch(() => ({ brief: null }));
  return Response.json(data, { status: upstream.status });
}
