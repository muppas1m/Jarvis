import { SignJWT } from "jose";

import { auth } from "@/auth";

export const dynamic = "force-dynamic";

/**
 * Mints a short-lived ticket for the wake-word WebSocket. A browser WS can't
 * carry the server-side X-API-Key, so the (session-verified) browser fetches
 * this and connects with `?ticket=`. The ticket is an HS256 JWT signed with the
 * shared AUTH_SECRET — the backend validates it with the same `_verify_jwt` its
 * HTTP auth uses. 60s expiry, sub="master"; no long-lived secret in the browser.
 */
export async function GET(): Promise<Response> {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const secret = new TextEncoder().encode(process.env.AUTH_SECRET ?? "");
  const ticket = await new SignJWT({})
    .setProtectedHeader({ alg: "HS256" })
    .setSubject("master")
    .setIssuedAt()
    .setExpirationTime("60s")
    .sign(secret);
  return Response.json({ ticket });
}
