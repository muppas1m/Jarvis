"use client";

/**
 * Low-prominence HUD controls (4.C.1), snugged bottom-right: wake-word, voice,
 * sign-out. Deliberately understated — a dim translucent pill that's barely
 * noticeable at a glance and lifts to full opacity on hover/focus, so the orb
 * and widgets stay the focus. (Approvals are resolved inline in chat now, so
 * there's no approvals tab here.)
 */
export function HudControls({
  wakeOn,
  onToggleWake,
  voiceEnabled,
  onToggleVoice,
  onSignOut,
}: {
  wakeOn: boolean;
  onToggleWake: () => void;
  voiceEnabled: boolean;
  onToggleVoice: () => void;
  onSignOut: () => void;
}) {
  return (
    <div className="fixed bottom-3 right-3 z-30 flex items-center gap-1 rounded-full border border-cyan/10 bg-space/40 px-2 py-1 opacity-40 backdrop-blur-md transition-opacity duration-300 hover:opacity-100 focus-within:opacity-100">
      <button
        onClick={onToggleWake}
        title='Continuous wake-word — say "Hey Jarvis…"'
        className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition ${
          wakeOn ? "bg-cyan/20 text-cyan glow" : "text-ink-dim hover:text-cyan"
        }`}
      >
        🎙 {wakeOn ? "wake on" : "wake"}
      </button>
      <button
        onClick={onToggleVoice}
        title="Speak responses aloud"
        className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition ${
          voiceEnabled ? "bg-cyan/20 text-cyan glow" : "text-ink-dim hover:text-cyan"
        }`}
      >
        {voiceEnabled ? "🔊 voice" : "🔈 voice"}
      </button>
      <span className="h-3 w-px bg-cyan/15" />
      <button
        onClick={onSignOut}
        title="Sign out"
        className="rounded-full px-2 py-0.5 font-mono text-[11px] text-ink-dim transition hover:text-danger"
      >
        ⏻
      </button>
    </div>
  );
}
