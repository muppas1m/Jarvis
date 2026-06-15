"use client";

import { Canvas } from "@react-three/fiber";

import type { AgentState } from "@/lib/types";

import { Orb } from "./Orb";

/**
 * Client-only Canvas wrapper. Imported via next/dynamic({ ssr: false }) from the
 * chat page so Three.js never runs during SSR. dpr capped at 2 for perf.
 */
export default function OrbCanvas({ state = "idle" as AgentState }: { state?: AgentState }) {
  return (
    <Canvas
      camera={{ position: [0, 0, 6], fov: 45 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      style={{ width: "100%", height: "100%" }}
    >
      <Orb state={state} />
    </Canvas>
  );
}
