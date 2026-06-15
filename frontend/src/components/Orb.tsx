"use client";

import { useMemo, useRef } from "react";

import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

import type { AgentState } from "@/lib/types";

/** Audio amplitude source, polled per-frame (0..1). 4.0 passes none → idle
 *  breathing only; 4.1 feeds the TTS FFT so the orb pulses to Jarvis's voice. */
export type AmpFn = () => number;

const CYAN = new THREE.Color("#00d4ff");
const AMBER = new THREE.Color("#ffb454");

/** Per-state visual config: colour, ring spin, core intensity, idle breath. */
const STATE_CFG: Record<
  AgentState,
  { color: THREE.Color; ringSpeed: number; intensity: number; breath: number }
> = {
  idle: { color: new THREE.Color("#00d4ff"), ringSpeed: 0.22, intensity: 1.0, breath: 0.03 },
  listening: { color: new THREE.Color("#7fe9ff"), ringSpeed: 0.5, intensity: 1.3, breath: 0.05 },
  thinking: { color: new THREE.Color("#9d7bff"), ringSpeed: 0.95, intensity: 1.2, breath: 0.055 },
  responding: { color: new THREE.Color("#00d4ff"), ringSpeed: 0.7, intensity: 1.7, breath: 0.09 },
};

// --------------------------------------------------------------------------- //
// Plexus core — Fibonacci-sphere nodes + near-neighbour lines                 //
// --------------------------------------------------------------------------- //
const N = 130;
const RADIUS = 1.05;
const EDGE_THRESHOLD = 0.34; // chord distance to link two nodes
const MAX_EDGES = 420;

function buildPlexus() {
  const base = new Float32Array(N * 3);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    base[i * 3] = Math.cos(theta) * r * RADIUS;
    base[i * 3 + 1] = y * RADIUS;
    base[i * 3 + 2] = Math.sin(theta) * r * RADIUS;
  }

  // Near-neighbour edges, capped at the closest MAX_EDGES.
  const cand: Array<[number, number, number]> = [];
  for (let i = 0; i < N; i++) {
    for (let j = i + 1; j < N; j++) {
      const dx = base[i * 3] - base[j * 3];
      const dy = base[i * 3 + 1] - base[j * 3 + 1];
      const dz = base[i * 3 + 2] - base[j * 3 + 2];
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (d < EDGE_THRESHOLD) cand.push([i, j, d]);
    }
  }
  cand.sort((a, b) => a[2] - b[2]);
  const kept = cand.slice(0, MAX_EDGES);
  const edges = new Uint16Array(kept.length * 2);
  kept.forEach(([a, b], k) => {
    edges[k * 2] = a;
    edges[k * 2 + 1] = b;
  });

  // Per-node random phase + amplitude factor for organic motion.
  const factor = new Float32Array(N);
  for (let i = 0; i < N; i++) factor[i] = 0.5 + ((i * 2654435761) % 1000) / 1000;

  return {
    base,
    edges,
    factor,
    pointPos: new Float32Array(N * 3),
    linePos: new Float32Array(edges.length * 3),
  };
}

function Plexus({
  color,
  breath,
  intensity,
  getAmp,
}: {
  color: THREE.Color;
  breath: number;
  intensity: number;
  getAmp: AmpFn;
}) {
  const geom = useMemo(buildPlexus, []);
  const pointAttr = useRef<THREE.BufferAttribute>(null);
  const lineAttr = useRef<THREE.BufferAttribute>(null);
  const pointMat = useRef<THREE.PointsMaterial>(null);
  const lineMat = useRef<THREE.LineBasicMaterial>(null);

  useFrame(() => {
    const t = performance.now() * 0.001;
    const amp = Math.min(1, Math.max(0, getAmp()));
    const { base, edges, factor, pointPos, linePos } = geom;

    for (let i = 0; i < N; i++) {
      const disp = 1 + breath * Math.sin(t * 0.9 + i * 0.6) + amp * 0.32 * factor[i];
      pointPos[i * 3] = base[i * 3] * disp;
      pointPos[i * 3 + 1] = base[i * 3 + 1] * disp;
      pointPos[i * 3 + 2] = base[i * 3 + 2] * disp;
    }
    for (let e = 0; e < edges.length / 2; e++) {
      const a = edges[e * 2];
      const b = edges[e * 2 + 1];
      linePos[e * 6] = pointPos[a * 3];
      linePos[e * 6 + 1] = pointPos[a * 3 + 1];
      linePos[e * 6 + 2] = pointPos[a * 3 + 2];
      linePos[e * 6 + 3] = pointPos[b * 3];
      linePos[e * 6 + 4] = pointPos[b * 3 + 1];
      linePos[e * 6 + 5] = pointPos[b * 3 + 2];
    }
    if (pointAttr.current) pointAttr.current.needsUpdate = true;
    if (lineAttr.current) lineAttr.current.needsUpdate = true;
    if (pointMat.current) {
      pointMat.current.color.copy(color).multiplyScalar(intensity);
      pointMat.current.opacity = 0.9;
    }
    if (lineMat.current) {
      lineMat.current.color.copy(color);
      lineMat.current.opacity = 0.16 + amp * 0.5;
    }
  });

  return (
    <group>
      <points>
        <bufferGeometry>
          <bufferAttribute ref={pointAttr} attach="attributes-position" args={[geom.pointPos, 3]} />
        </bufferGeometry>
        <pointsMaterial
          ref={pointMat}
          size={0.04}
          sizeAttenuation
          transparent
          depthWrite={false}
        />
      </points>
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute ref={lineAttr} attach="attributes-position" args={[geom.linePos, 3]} />
        </bufferGeometry>
        <lineBasicMaterial ref={lineMat} transparent opacity={0.16} depthWrite={false} />
      </lineSegments>
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Arc-reactor ring — segmented arcs (not a solid torus), with amber accents   //
// --------------------------------------------------------------------------- //
function ArcRing({
  radius,
  segments,
  thickness,
  color,
  accentEvery,
  speed,
  dir,
  tilt,
  z,
}: {
  radius: number;
  segments: number;
  thickness: number;
  color: THREE.Color;
  accentEvery: number;
  speed: number;
  dir: number;
  tilt: number;
  z: number;
}) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.z += dt * speed * dir;
  });
  const arcs = useMemo(() => {
    const seg = (Math.PI * 2) / segments;
    const gap = 0.22; // fraction of each slot left empty
    return Array.from({ length: segments }, (_, i) => ({
      start: i * seg + (seg * gap) / 2,
      len: seg * (1 - gap),
      accent: accentEvery > 0 && i % accentEvery === 0,
    }));
  }, [segments, accentEvery]);

  return (
    <group ref={ref} rotation={[tilt, 0, 0]} position={[0, 0, z]}>
      {arcs.map((a, i) => (
        <mesh key={i}>
          <ringGeometry args={[radius - thickness, radius + thickness, 24, 1, a.start, a.len]} />
          <meshBasicMaterial
            color={a.accent ? AMBER : color}
            transparent
            opacity={0.85}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  );
}

/** Radial instrument ticks around the outer ring. */
function Ticks({ radius, count, color }: { radius: number; count: number; color: THREE.Color }) {
  const items = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => {
        const a = (i / count) * Math.PI * 2;
        return { a, big: i % 5 === 0 };
      }),
    [count],
  );
  return (
    <group rotation={[Math.PI / 2, 0, 0]}>
      {items.map((t, i) => (
        <mesh
          key={i}
          position={[Math.cos(t.a) * radius, 0, Math.sin(t.a) * radius]}
          rotation={[0, -t.a, 0]}
        >
          <boxGeometry args={[t.big ? 0.1 : 0.05, 0.006, 0.006]} />
          <meshBasicMaterial color={color} transparent opacity={t.big ? 0.9 : 0.45} />
        </mesh>
      ))}
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Orb assembly                                                                //
// --------------------------------------------------------------------------- //
export function Orb({
  state = "idle",
  getAmplitude,
}: {
  state?: AgentState;
  getAmplitude?: AmpFn;
}) {
  const cfg = STATE_CFG[state];
  const group = useRef<THREE.Group>(null);
  const getAmp = getAmplitude ?? (() => 0);

  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * 0.06;
  });

  return (
    <group ref={group}>
      <ambientLight intensity={0.5} />
      <pointLight position={[3, 3, 5]} intensity={20} color={cfg.color} />

      <Plexus color={cfg.color} breath={cfg.breath} intensity={cfg.intensity} getAmp={getAmp} />

      <ArcRing radius={1.7} segments={6} thickness={0.02} color={cfg.color} accentEvery={3} speed={cfg.ringSpeed} dir={1} tilt={Math.PI / 2.4} z={0} />
      <ArcRing radius={2.05} segments={10} thickness={0.015} color={cfg.color} accentEvery={5} speed={cfg.ringSpeed * 0.7} dir={-1} tilt={Math.PI / 2.1} z={-0.1} />
      <ArcRing radius={2.42} segments={4} thickness={0.025} color={cfg.color} accentEvery={0} speed={cfg.ringSpeed * 0.45} dir={1} tilt={Math.PI / 1.9} z={0.12} />
      <Ticks radius={2.2} count={60} color={cfg.color} />
    </group>
  );
}
