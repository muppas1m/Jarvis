import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

/**
 * BFF: approve/reject an approval (proxy to backend
 * /api/approvals/{id}/decide). Backend body shape is {approved: bool, reason?}.
 * Note: Next 16 route params are async — `await ctx.params`.
 */
export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const { id } = await ctx.params;
  const body = await req.text();
  const upstream = await backendFetch(
    `/api/approvals/${encodeURIComponent(id)}/decide`,
    { method: "POST", body },
  );
  const data = await upstream.json().catch(() => ({}));
  return Response.json(data, { status: upstream.status });
}
