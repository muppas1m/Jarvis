"use client";

import { useCallback, useRef } from "react";

/**
 * Command capture via the browser Web Speech API (the 4.2 "to start" STT — it
 * does VAD + transcription in one: captures a single utterance, auto-ends on
 * silence, returns the transcript). Chrome-only; faster-whisper local is the
 * upgrade path (4.3). Audio only flows here AFTER the "Jarvis" wake-word fires.
 */

// Minimal typing — the DOM lib doesn't ship SpeechRecognition types.
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  abort: () => void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  onend: (() => void) | null;
}
type SRCtor = new () => SpeechRecognitionLike;

function getCtor(): SRCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useSpeechInput() {
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const supported = getCtor() !== null;

  /** Capture one spoken command; resolves with the transcript ("" if silent). */
  const capture = useCallback((): Promise<string> => {
    return new Promise((resolve, reject) => {
      const Ctor = getCtor();
      if (!Ctor) {
        reject(new Error("speech-recognition-unsupported"));
        return;
      }
      const rec = new Ctor();
      rec.lang = "en-GB";
      rec.continuous = false;
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      recRef.current = rec;

      let settled = false;
      rec.onresult = (e) => {
        settled = true;
        resolve(e.results[0]?.[0]?.transcript ?? "");
      };
      rec.onerror = (e) => {
        if (!settled) {
          settled = true;
          // "no-speech"/"aborted" are benign — resolve empty rather than throw.
          if (e.error === "no-speech" || e.error === "aborted") resolve("");
          else reject(new Error(e.error ?? "speech-error"));
        }
      };
      rec.onend = () => {
        if (!settled) {
          settled = true;
          resolve("");
        }
      };
      rec.start();
    });
  }, []);

  const abort = useCallback(() => {
    try {
      recRef.current?.abort();
    } catch {
      /* already stopped */
    }
  }, []);

  return { supported, capture, abort };
}
