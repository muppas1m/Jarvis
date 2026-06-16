"use client";

import { useEffect, useRef } from "react";

import { BuiltInKeyword } from "@picovoice/porcupine-web";
import { usePorcupine } from "@picovoice/porcupine-react";

/**
 * On-device wake-word on the name **"Jarvis"** (Porcupine built-in keyword,
 * WASM in-browser — fires on the name in any phrasing). Audio never leaves the
 * machine until "Jarvis" is heard. Gated by `enabled` (the master's toggle) and
 * the access key being present; only runs on the authenticated chat page.
 *
 * Cycle: on detection the hook STOPS itself (frees the mic), awaits `onWake`
 * (the capture+respond flow), then resumes listening — so Porcupine and the
 * command STT never fight over the mic.
 */
const ACCESS_KEY = process.env.NEXT_PUBLIC_PICOVOICE_ACCESS_KEY ?? "";

export function useWakeWord({
  enabled,
  onWake,
}: {
  enabled: boolean;
  onWake: () => Promise<void>;
}) {
  const { keywordDetection, isLoaded, isListening, error, init, start, stop, release } =
    usePorcupine();
  const onWakeRef = useRef(onWake);
  onWakeRef.current = onWake;
  const busyRef = useRef(false);

  // Load + start when enabled and configured; release on disable/unmount.
  useEffect(() => {
    if (!enabled || !ACCESS_KEY) return;
    let cancelled = false;
    (async () => {
      try {
        await init(ACCESS_KEY, BuiltInKeyword.Jarvis, { publicPath: "/porcupine_params.pv" });
        if (!cancelled) await start();
      } catch {
        /* surfaced via `error` */
      }
    })();
    return () => {
      cancelled = true;
      void release();
    };
    // init/start/release are stable from the SDK hook.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // On "Jarvis": pause (free the mic) → run the capture flow → resume.
  useEffect(() => {
    if (keywordDetection === null || busyRef.current || !enabled) return;
    busyRef.current = true;
    (async () => {
      try {
        await stop();
        await onWakeRef.current();
      } catch {
        /* ignore — keep listening */
      } finally {
        busyRef.current = false;
        if (enabled) {
          try {
            await start();
          } catch {
            /* ignore */
          }
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keywordDetection]);

  return {
    configured: !!ACCESS_KEY,
    isLoaded,
    isListening,
    error,
  };
}
