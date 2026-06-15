"use client";

import { useMemo, useRef } from "react";

import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

import type { AgentState } from "@/lib/types";

/** Audio amplitude source, polled per-frame (0..1). 4.0 passes none → idle
 *  breathing; 4.1 feeds the TTS FFT so the orb pulses to Jarvis's voice. */
export type AmpFn = () => number;

const AMBER = new THREE.Color("#ffb454");

/** Per-state visual config: colour, ring spin, core intensity, idle breath. */
const STATE_CFG: Record<
  AgentState,
  { color: THREE.Color; ringSpeed: number; intensity: number; breath: number }
> = {
  idle: { color: new THREE.Color("#00d4ff"), ringSpeed: 0.35, intensity: 1.0, breath: 0.03 },
  listening: { color: new THREE.Color("#7fe9ff"), ringSpeed: 0.6, intensity: 1.3, breath: 0.05 },
  thinking: { color: new THREE.Color("#9d7bff"), ringSpeed: 1.1, intensity: 1.2, breath: 0.055 },
  responding: { color: new THREE.Color("#00d4ff"), ringSpeed: 0.85, intensity: 1.7, breath: 0.09 },
};

// --------------------------------------------------------------------------- //
// Plexus core — the 3D particle-network sphere inside the arc reactor          //
// --------------------------------------------------------------------------- //
const N = 120;
const RADIUS = 0.78;
const EDGE_THRESHOLD = 0.26;
const MAX_EDGES = 360;

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
  const group = useRef<THREE.Group>(null);
  const pointAttr = useRef<THREE.BufferAttribute>(null);
  const lineAttr = useRef<THREE.BufferAttribute>(null);
  const pointMat = useRef<THREE.PointsMaterial>(null);
  const lineMat = useRef<THREE.LineBasicMaterial>(null);

  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * 0.12;
    const t = performance.now() * 0.001;
    const amp = Math.min(1, Math.max(0, getAmp()));
    const { base, edges, factor, pointPos, linePos } = geom;
    for (let i = 0; i < N; i++) {
      const disp = 1 + breath * Math.sin(t * 0.9 + i * 0.6) + amp * 0.34 * factor[i];
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
      lineMat.current.opacity = 0.18 + amp * 0.5;
    }
  });

  return (
    <group ref={group}>
      <points>
        <bufferGeometry>
          <bufferAttribute ref={pointAttr} attach="attributes-position" args={[geom.pointPos, 3]} />
        </bufferGeometry>
        <pointsMaterial ref={pointMat} size={0.035} sizeAttenuation transparent depthWrite={false} />
      </points>
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute ref={lineAttr} attach="attributes-position" args={[geom.linePos, 3]} />
        </bufferGeometry>
        <lineBasicMaterial ref={lineMat} transparent opacity={0.18} depthWrite={false} />
      </lineSegments>
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Arc-reactor ring — HEAD-ON (faces the camera, screen plane), spins on z      //
// = a concentric dial. Faint full ring + bold segmented arcs + amber accents.  //
// --------------------------------------------------------------------------- //
function ArcRing({
  radius,
  segments,
  thickness,
  color,
  accentEvery,
  speed,
  dir,
}: {
  radius: number;
  segments: number;
  thickness: number;
  color: THREE.Color;
  accentEvery: number;
  speed: number;
  dir: number;
}) {
  const ref = useRef<THREE.Group>(null);
  // No tilt — the ringGeometry lies in the XY plane (normal toward the camera),
  // so spinning on z reads as a dial spinning in the screen plane.
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.z += dt * speed * dir;
  });
  const arcs = useMemo(() => {
    const seg = (Math.PI * 2) / segments;
    const gap = 0.22;
    return Array.from({ length: segments }, (_, i) => ({
      start: i * seg + (seg * gap) / 2,
      len: seg * (1 - gap),
      accent: accentEvery > 0 && i % accentEvery === 0,
    }));
  }, [segments, accentEvery]);

  return (
    <group ref={ref}>
      {/* faint full ring for continuity */}
      <mesh>
        <ringGeometry args={[radius - thickness * 0.35, radius + thickness * 0.35, 96]} />
        <meshBasicMaterial color={color} transparent opacity={0.16} side={THREE.DoubleSide} />
      </mesh>
      {/* bold bright arc segments */}
      {arcs.map((a, i) => (
        <mesh key={i}>
          <ringGeometry args={[radius - thickness, radius + thickness, 48, 1, a.start, a.len]} />
          <meshBasicMaterial
            color={a.accent ? AMBER : color}
            transparent
            opacity={0.95}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  );
}

/** Crisp camera-facing radial ticks (in the screen plane), an instrument bezel. */
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
    <group>
      {items.map((t, i) => (
        <mesh
          key={i}
          position={[Math.cos(t.a) * radius, Math.sin(t.a) * radius, 0]}
          rotation={[0, 0, t.a]}
        >
          <boxGeometry args={[t.big ? 0.12 : 0.06, t.big ? 0.016 : 0.01, 0.01]} />
          <meshBasicMaterial color={color} transparent opacity={t.big ? 0.95 : 0.45} />
        </mesh>
      ))}
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Orb assembly — head-on arc reactor: flat spinning dials framing the 3D core  //
// --------------------------------------------------------------------------- //
export function Orb({
  state = "idle",
  getAmplitude,
}: {
  state?: AgentState;
  getAmplitude?: AmpFn;
}) {
  const cfg = STATE_CFG[state];
  const getAmp = getAmplitude ?? (() => 0);

  return (
    <group>
      <ambientLight intensity={0.55} />
      <pointLight position={[0, 0, 3]} intensity={16} color={cfg.color} />

      {/* 3D plexus core + bright centre */}
      <Plexus color={cfg.color} breath={cfg.breath} intensity={cfg.intensity} getAmp={getAmp} />
      <mesh>
        <sphereGeometry args={[0.05, 16, 16]} />
        <meshBasicMaterial color="#eaffff" />
      </mesh>

      {/* concentric head-on dials, independent speeds + directions */}
      <ArcRing radius={1.25} segments={3} thickness={0.05} color={cfg.color} accentEvery={3} speed={cfg.ringSpeed * 1.15} dir={1} />
      <ArcRing radius={1.6} segments={6} thickness={0.035} color={cfg.color} accentEvery={4} speed={cfg.ringSpeed * 0.85} dir={-1} />
      <ArcRing radius={1.95} segments={10} thickness={0.04} color={cfg.color} accentEvery={5} speed={cfg.ringSpeed * 0.6} dir={1} />
      <ArcRing radius={2.28} segments={4} thickness={0.028} color={cfg.color} accentEvery={2} speed={cfg.ringSpeed * 0.45} dir={-1} />

      <Ticks radius={2.5} count={60} color={cfg.color} />

      {/* outer boundary hairline */}
      <mesh>
        <ringGeometry args={[2.54, 2.57, 128]} />
        <meshBasicMaterial color={cfg.color} transparent opacity={0.3} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}
