import NextAuth from "next-auth";

import { authConfig } from "./auth.config";

/**
 * Proxy = Next.js 16's renamed Middleware (same functionality). This is the
 * OPTIMISTIC auth gate only: it redirects unauthenticated browsers away from
 * protected pages to /login, using the session cookie. The authoritative
 * checks happen in the BFF route handlers (`src/app/api/**`) and Server
 * Components via `auth()`. Per the Next docs, proxy must not be the sole
 * authorization layer.
 *
 * Runs on page routes only — `/api/*` is excluded so the BFF handlers return
 * 401 JSON (not an HTML redirect), and `/api/auth/*` stays reachable for sign-in.
 */
export default NextAuth(authConfig).auth;

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|manifest.webmanifest|sw.js|icon.svg).*)",
  ],
};
