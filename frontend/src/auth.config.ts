import type { NextAuthConfig } from "next-auth";

/**
 * Edge-safe Auth.js config — no providers, no Node-only deps (crypto).
 * Shared by `proxy.ts` (the optimistic redirect gate) and `auth.ts` (which
 * adds the Credentials provider for the Node route-handler runtime).
 *
 * Single-master model: identity is always "master". The session is long-lived
 * so the dashboard (and, in 4.4, wake-word/voice) doesn't force re-auth mid-use.
 */
const PROTECTED_PREFIXES = ["/chat"];

export const authConfig = {
  trustHost: true,
  session: { strategy: "jwt", maxAge: 60 * 60 * 24 * 30 }, // 30 days
  pages: { signIn: "/login" },
  providers: [], // real provider added in auth.ts (Node runtime)
  callbacks: {
    // Optimistic gate consumed by the proxy. Return false on a protected
    // route when unauthenticated → Auth.js redirects to `pages.signIn`.
    authorized({ auth, request }) {
      const { pathname } = request.nextUrl;
      const isProtected =
        pathname === "/" ||
        PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
      if (!isProtected) return true;
      return !!auth?.user;
    },
    jwt({ token, user }) {
      if (user) token.sub = user.id ?? "master";
      return token;
    },
    session({ session, token }) {
      if (session.user && token.sub) session.user.id = token.sub;
      return session;
    },
  },
} satisfies NextAuthConfig;

export default authConfig;
