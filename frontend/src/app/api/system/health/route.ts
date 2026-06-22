import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/** BFF: grouped subsystem health for the HUD ring + status pill
 *  (proxy to backend /api/system/health). */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/system/health");
  const data = await upstream.json().catch(() => ({}));
  return Response.json(data, { status: upstream.status });
}
