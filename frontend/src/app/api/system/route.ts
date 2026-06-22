import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/** BFF: real VM stats for the dashboard (proxy to backend /api/system). */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/system");
  const data = await upstream.json().catch(() => ({}));
  return Response.json(data, { status: upstream.status });
}
