"use client";

/**
 * Boot-sequence trigger. The Stark boot overlay plays on every *login*, not on
 * plain page reloads: login sets a one-shot `boot_pending` flag, BootSequence
 * consumes+clears it on mount, and sign-out clears any stale flag.
 *
 * sessionStorage (per-tab, cleared on tab close) — a reload alone never sets the
 * flag, so the boot doesn't replay; a fresh sign-in always does.
 */
const BOOT_PENDING_KEY = "jarvis_boot_pending";

export function markBootPending(): void {
  try {
    sessionStorage.setItem(BOOT_PENDING_KEY, "1");
  } catch {
    /* SSR / storage unavailable — boot is cosmetic, ignore */
  }
}

export function clearBootPending(): void {
  try {
    sessionStorage.removeItem(BOOT_PENDING_KEY);
  } catch {
    /* ignore */
  }
}

/** True exactly once after a login; clears the flag so reloads don't replay. */
export function consumeBootPending(): boolean {
  try {
    if (sessionStorage.getItem(BOOT_PENDING_KEY) === "1") {
      sessionStorage.removeItem(BOOT_PENDING_KEY);
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}
