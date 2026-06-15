"use client";

import { useMemo, useRef } from "react";

import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

import type { AgentState } from "@/lib/types";

/** State → orb colour. 4.1 will modulate intensity from the TTS FFT; for 4.0
 *  this is the static-shell palette (idle cyan). */
const STATE_COLOR: Record<AgentState, number> = {
  idle: 0x00d4ff,
  listening: 0x7fe9ff,
  thinking: 0x9d7bff,
  responding: 0x00d4ff,
};

/**
 * Arc-reactor orb shell: glowing icosahedron core, wireframe shell, an orbital
 * ring, and a particle halo. Gentle autonomous motion (no audio yet). Kept
 * lightweight (800 particles, capped dpr in the Canvas) to hold 60fps.
 */
export function Orb({ state = "idle" }: { state?: AgentState }) {
  const group = useRef<THREE.Group>(null);
  const core = useRef<THREE.Mesh>(null);
  const shell = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);
  const halo = useRef<THREE.Points>(null);

  const particles = useMemo(() => {
    const N = 800;
    const arr = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      const r = 1.8 + Math.random() * 0.9;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      arr[i * 3 + 2] = r * Math.cos(phi);
    }
    return arr;
  }, []);

  const color = STATE_COLOR[state];

  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * 0.15;
    if (shell.current) shell.current.rotation.x += dt * 0.08;
    if (ring.current) ring.current.rotation.z += dt * 0.3;
    if (halo.current) halo.current.rotation.y -= dt * 0.05;
    if (core.current) {
      const s = 1 + Math.sin(performance.now() * 0.0015) * 0.04;
      core.current.scale.setScalar(s);
    }
  });

  return (
    <group ref={group}>
      <ambientLight intensity={0.4} />
      <pointLight position={[4, 4, 4]} intensity={40} color={color} />

      <mesh ref={core}>
        <icosahedronGeometry args={[1, 4]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={1.4}
          roughness={0.25}
          metalness={0.6}
        />
      </mesh>

      <mesh ref={shell}>
        <icosahedronGeometry args={[1.5, 1]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.22} />
      </mesh>

      <mesh ref={ring} rotation={[Math.PI / 2.2, 0, 0]}>
        <torusGeometry args={[2.1, 0.012, 12, 120]} />
        <meshBasicMaterial color={color} transparent opacity={0.5} />
      </mesh>

      <points ref={halo}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[particles, 3]} />
        </bufferGeometry>
        <pointsMaterial size={0.02} color={color} transparent opacity={0.7} sizeAttenuation />
      </points>
    </group>
  );
}
