import { auth } from "@/auth";
import { backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * BFF: stream a multipart document upload to the backend /api/documents/upload
 * (X-API-Key attached server-side). The browser's request body is piped straight
 * through — never buffered — matching the backend's OOM-safe block read. The
 * multipart Content-Type (with its boundary) and the optional `thread_id` form
 * field are forwarded as-is.
 */
export async function POST(req: Request): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const upstream = await backendFetch("/api/documents/upload", {
    method: "POST",
    body: req.body,
    headers: { "Content-Type": req.headers.get("content-type") ?? "" },
    // @ts-expect-error duplex is required to stream a request body (Node/undici fetch)
    duplex: "half",
  });
  const data = await upstream.json().catch(() => ({ detail: "upload failed" }));
  return Response.json(data, { status: upstream.status });
}
