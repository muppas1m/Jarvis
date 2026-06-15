import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/** BFF: list pending approvals (proxy to backend /api/approvals/pending). */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/approvals/pending");
  const data = await upstream.json().catch(() => []);
  return Response.json(data, { status: upstream.status });
}
