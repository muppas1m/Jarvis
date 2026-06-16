"use client";

import { Canvas } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";

import type { AgentState } from "@/lib/types";

import { Orb, type AmpFn } from "./Orb";

/**
 * Client-only Canvas wrapper (next/dynamic ssr:false). EffectComposer + Bloom
 * gives the neon glow. dpr capped at 2 for 60fps. `getAmplitude` is the audio
 * source — omitted in 4.0 (idle breathing); wired to the TTS FFT in 4.1.
 */
export default function OrbCanvas({
  state = "idle" as AgentState,
  getAmplitude,
}: {
  state?: AgentState;
  getAmplitude?: AmpFn;
}) {
  return (
    <Canvas
      camera={{ position: [0, 0, 13], fov: 45 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      style={{ width: "100%", height: "100%" }}
    >
      <Orb state={state} getAmplitude={getAmplitude} />
      <EffectComposer>
        <Bloom
          intensity={1.3}
          luminanceThreshold={0.35}
          luminanceSmoothing={0.9}
          radius={0.35}
          mipmapBlur
        />
      </EffectComposer>
    </Canvas>
  );
}
