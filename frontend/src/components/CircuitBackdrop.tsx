/**
 * The HUD's three-layer back-fill (4.C.1), fixed behind the whole dashboard:
 *   1. `.circuit-backdrop` — the blurred + upscaled circuit-board art (globals.css).
 *   2. a dim wash — a dark radial so the translucent widgets stay readable while
 *      the brighter upper-right of the art still glows through.
 *   3. (room for an optional animated drift later — not in v1.)
 *
 * Pure decoration: aria-hidden, pointer-events-none, pinned at -z-10 so every
 * grid widget floats above it and reveals it through their translucent fills.
 */
export function CircuitBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 circuit-backdrop" />
      {/* dim wash — darker bottom-left (where the art is sparse), lifting toward
          the top-right glow so the circuit reads without fighting the content */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(125% 125% at 72% 4%, rgba(7,11,24,0.5), rgba(7,11,24,0.88))",
        }}
      />
    </div>
  );
}
