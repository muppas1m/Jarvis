import { timingSafeEqual } from "crypto";

import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

import { authConfig } from "./auth.config";

/** Constant-time string compare (avoids leaking the passkey via timing). */
function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a, "utf8");
  const bb = Buffer.from(b, "utf8");
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  ...authConfig,
  providers: [
    Credentials({
      name: "passkey",
      credentials: { passkey: { label: "Passkey", type: "password" } },
      authorize(credentials) {
        const expected = process.env.MASTER_PASSKEY ?? "";
        const presented =
          typeof credentials?.passkey === "string" ? credentials.passkey : "";
        if (!expected || !presented || !safeEqual(presented, expected)) {
          return null;
        }
        return { id: "master", name: "Master" };
      },
    }),
  ],
});
