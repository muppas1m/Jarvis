import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/** BFF: current weather (proxy to backend /api/weather). */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/weather");
  const data = await upstream.json().catch(() => ({}));
  return Response.json(data, { status: upstream.status });
}
