import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/**
 * BFF: the single next inbound (auto-drafted email reply) approval to present,
 * or {approval: null} (proxy to backend /api/approvals/inbound/next). The HUD
 * polls this and surfaces one card at a time.
 */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/approvals/inbound/next");
  const data = await upstream.json().catch(() => ({}));
  return Response.json(data, { status: upstream.status });
}
