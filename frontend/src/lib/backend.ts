import "server-only";

/**
 * Server-only fetch to the FastAPI backend. Attaches the backend's X-API-Key
 * (kept server-side — never NEXT_PUBLIC, never shipped to the browser). The
 * `server-only` import makes any accidental client import a build error, so the
 * key can't leak into a client bundle.
 *
 * Callers are the BFF route handlers, which verify the dashboard session first.
 */
const BASE = process.env.JARVIS_BACKEND_URL ?? "http://localhost:8000";
const KEY = process.env.JARVIS_API_KEY ?? "";

export function backendFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("X-API-Key", KEY);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store" });
}
