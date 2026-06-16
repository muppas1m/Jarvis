"use client";

import { useMemo, useRef } from "react";

import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

import type { AgentState } from "@/lib/types";

/** Audio amplitude source, polled per-frame (0..1) — the TTS FFT drives the
 *  RESPONDING pulse; idle passes none. */
export type AmpFn = () => number;

const AMBER = new THREE.Color("#ffdbad");
const CYAN = new THREE.Color("#1edaff");

// HDR glow: materials render ABOVE 1.0 so the mipmap bloom reliably catches the
// thin rings/core. The glow scales with per-state brightness but is FLOORED so
// idle keeps a soft halo (never drops below the bloom threshold → no flat lines).
const HDR_RING = 2.6;
const GLOW_FLOOR_RING = 1.55;
const HDR_CORE = 2.3;
const GLOW_FLOOR_CORE = 1.45;
const DIR_FLIP_SECONDS = 2; // direction reverses this often while responding

/** Per-state visual TARGETS. `anim` lerps toward these every frame (no snaps).
 *  brightness scales the HDR glow (idle = soft, responding = bright); ringScale
 *  blooms the rings outward when speaking. */
const STATE_CFG: Record<
  AgentState,
  { color: THREE.Color; ringSpeed: number; breath: number; brightness: number; ringScale: number }
> = {
  idle: { color: new THREE.Color("#00d4ff"), ringSpeed: 0.35, breath: 0.03, brightness: 0.72, ringScale: 1.0 },
  listening: { color: new THREE.Color("#7fe9ff"), ringSpeed: 0.6, breath: 0.05, brightness: 0.85, ringScale: 1.03 },
  thinking: { color: new THREE.Color("#b8a1ff"), ringSpeed: 1.1, breath: 0.055, brightness: 0.88, ringScale: 1.07 },
  responding: { color: new THREE.Color("#00d4ff"), ringSpeed: 0.85, breath: 0.09, brightness: 1.0, ringScale: 1.07 },
};

interface Anim {
  color: THREE.Color;
  ringSpeed: number;
  brightness: number;
  ringScale: number;
  dirSign: number;
  breath: number;
}

// Reusable temp colours (avoid per-frame allocation in the paint loop).
const _gc = new THREE.Color();
const _ga = new THREE.Color();

/** Paint every child mesh carrying a `baseOpacity` userData with an HDR colour
 *  (so it blooms) + its base opacity (kept crisp — the dimming is in the glow). */
function paintGroup(group: THREE.Group, brightness: number, color: THREE.Color) {
  const glow = Math.max(GLOW_FLOOR_RING, HDR_RING * brightness);
  _gc.copy(color).multiplyScalar(glow);
  _ga.copy(AMBER).multiplyScalar(glow);
  group.traverse((o) => {
    const mesh = o as THREE.Mesh;
    const base = mesh.userData?.baseOpacity as number | undefined;
    if (base === undefined) return;
    const m = mesh.material as THREE.MeshBasicMaterial;
    m.opacity = base;
    m.color.copy(mesh.userData.amber ? _ga : _gc);
  });
}

// --------------------------------------------------------------------------- //
// Plexus core — the 3D particle-network sphere inside the arc reactor          //
// --------------------------------------------------------------------------- //
const N = 120;
const RADIUS = 0.92;
const EDGE_THRESHOLD = 0.31;
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
  return { base, edges, factor, pointPos: new Float32Array(N * 3), linePos: new Float32Array(edges.length * 3) };
}

function Plexus({ anim, getAmp }: { anim: Anim; getAmp: AmpFn }) {
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
      const disp = 1 + anim.breath * Math.sin(t * 0.9 + i * 0.6) + amp * 0.34 * factor[i];
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
    const coreGlow = Math.max(GLOW_FLOOR_CORE, HDR_CORE * anim.brightness);
    if (pointMat.current) {
      pointMat.current.color.copy(anim.color).multiplyScalar(coreGlow);
      pointMat.current.opacity = 0.95;
    }
    if (lineMat.current) {
      lineMat.current.color.copy(anim.color).multiplyScalar(Math.max(1.15, 1.6 * anim.brightness));
      lineMat.current.opacity = 0.22 + amp * 0.5;
    }
  });

  return (
    <group ref={group}>
      <points>
        <bufferGeometry>
          <bufferAttribute ref={pointAttr} attach="attributes-position" args={[geom.pointPos, 3]} />
        </bufferGeometry>
        <pointsMaterial ref={pointMat} size={0.04} sizeAttenuation transparent depthWrite={false} color={CYAN} />
      </points>
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute ref={lineAttr} attach="attributes-position" args={[geom.linePos, 3]} />
        </bufferGeometry>
        <lineBasicMaterial ref={lineMat} transparent opacity={0.22} depthWrite={false} color={CYAN} />
      </lineSegments>
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Arc-reactor ring — HEAD-ON dial (faces camera, spins on z).                  //
// --------------------------------------------------------------------------- //
function ArcRing({
  radius,
  segments,
  thickness,
  accentEvery,
  baseDir,
  speedMul,
  anim,
}: {
  radius: number;
  segments: number;
  thickness: number;
  accentEvery: number;
  baseDir: number;
  speedMul: number;
  anim: Anim;
}) {
  const ref = useRef<THREE.Group>(null);
  const arcs = useMemo(() => {
    const seg = (Math.PI * 2) / segments;
    const gap = 0.22;
    return Array.from({ length: segments }, (_, i) => ({
      start: i * seg + (seg * gap) / 2,
      len: seg * (1 - gap),
      accent: accentEvery > 0 && i % accentEvery === 0,
    }));
  }, [segments, accentEvery]);

  useFrame((_, dt) => {
    const g = ref.current;
    if (!g) return;
    g.rotation.z += dt * anim.ringSpeed * speedMul * baseDir * anim.dirSign;
    g.scale.setScalar(anim.ringScale);
    paintGroup(g, anim.brightness, anim.color);
  });

  return (
    <group ref={ref}>
      <mesh userData={{ baseOpacity: 0.18 }}>
        <ringGeometry args={[radius - thickness * 0.35, radius + thickness * 0.35, 96]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.18} side={THREE.DoubleSide} />
      </mesh>
      {arcs.map((a, i) => (
        <mesh key={i} userData={{ baseOpacity: 0.95, amber: a.accent }}>
          <ringGeometry args={[radius - thickness, radius + thickness, 48, 1, a.start, a.len]} />
          <meshBasicMaterial color={CYAN} transparent opacity={0.95} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Outer ring — radial tick bezel + boundary hairline, revolving as the         //
// outermost member of the alternating-direction pattern.                       //
// --------------------------------------------------------------------------- //
function OuterRing({
  radius,
  count,
  baseDir,
  speedMul,
  anim,
}: {
  radius: number;
  count: number;
  baseDir: number;
  speedMul: number;
  anim: Anim;
}) {
  const ref = useRef<THREE.Group>(null);
  const items = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => {
        const a = (i / count) * Math.PI * 2;
        return { a, big: i % 5 === 0 };
      }),
    [count],
  );

  useFrame((_, dt) => {
    const g = ref.current;
    if (!g) return;
    g.rotation.z += dt * anim.ringSpeed * speedMul * baseDir * anim.dirSign;
    g.scale.setScalar(anim.ringScale);
    paintGroup(g, anim.brightness, anim.color);
  });

  return (
    <group ref={ref}>
      <mesh userData={{ baseOpacity: 0.32 }}>
        <ringGeometry args={[radius + 0.06, radius + 0.1, 128]} />
        <meshBasicMaterial color={CYAN} transparent opacity={0.32} side={THREE.DoubleSide} />
      </mesh>
      {items.map((t, i) => (
        <mesh
          key={i}
          position={[Math.cos(t.a) * radius, Math.sin(t.a) * radius, 0]}
          rotation={[0, 0, t.a]}
          userData={{ baseOpacity: t.big ? 0.95 : 0.45 }}
        >
          <boxGeometry args={[t.big ? 0.18 : 0.09, t.big ? 0.022 : 0.014, 0.01]} />
          <meshBasicMaterial color={CYAN} transparent opacity={t.big ? 0.95 : 0.45} />
        </mesh>
      ))}
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Orb assembly — owns the shared `anim`, lerps it toward the state target, and //
// runs the 1 s global direction-flip clock (responding only).                 //
// --------------------------------------------------------------------------- //
export function Orb({
  state = "idle",
  getAmplitude,
}: {
  state?: AgentState;
  getAmplitude?: AmpFn;
}) {
  const target = STATE_CFG[state];
  const getAmp = getAmplitude ?? (() => 0);

  const anim = useRef<Anim>({
    color: new THREE.Color("#00d4ff"),
    ringSpeed: 0.35,
    brightness: 0.72,
    ringScale: 1.0,
    dirSign: 1,
    breath: 0.03,
  }).current;
  const dirClock = useRef(0);
  const light = useRef<THREE.PointLight>(null);

  useFrame((_, dt) => {
    const k = 1 - Math.exp(-dt * 5); // ~0.2s time constant, framerate-independent
    anim.color.lerp(target.color, k);
    anim.ringSpeed += (target.ringSpeed - anim.ringSpeed) * k;
    anim.brightness += (target.brightness - anim.brightness) * k;
    anim.ringScale += (target.ringScale - anim.ringScale) * k;
    anim.breath += (target.breath - anim.breath) * k;

    // Global direction sign: flip every DIR_FLIP_SECONDS while responding; steady
    // +1 otherwise (all rings share this one clock → they reverse in unison).
    if (state === "responding") {
      dirClock.current += dt;
      if (dirClock.current >= DIR_FLIP_SECONDS) {
        dirClock.current -= DIR_FLIP_SECONDS;
        anim.dirSign = -anim.dirSign;
      }
    } else {
      dirClock.current = 0;
      anim.dirSign = 1;
    }

    if (light.current) {
      light.current.color.copy(anim.color);
      light.current.intensity = 18 * anim.brightness;
    }
  });

  return (
    <group>
      <ambientLight intensity={0.55} />
      <pointLight ref={light} position={[0, 0, 4]} intensity={18} color={CYAN} />

      {/* 3D plexus core + bright centre */}
      <Plexus anim={anim} getAmp={getAmp} />
      <mesh>
        <sphereGeometry args={[0.06, 16, 16]} />
        <meshBasicMaterial color="#eaffff" />
      </mesh>

      {/* concentric head-on dials — wider spacing; alternating base direction */}
      <ArcRing radius={1.4} segments={3} thickness={0.07} accentEvery={3} baseDir={1} speedMul={1.15} anim={anim} />
      <ArcRing radius={2.05} segments={6} thickness={0.05} accentEvery={4} baseDir={-1} speedMul={0.85} anim={anim} />
      <ArcRing radius={2.7} segments={10} thickness={0.055} accentEvery={5} baseDir={1} speedMul={0.6} anim={anim} />
      <ArcRing radius={3.35} segments={4} thickness={0.04} accentEvery={2} baseDir={-1} speedMul={0.45} anim={anim} />
      <OuterRing radius={3.75} count={60} baseDir={1} speedMul={0.35} anim={anim} />
    </group>
  );
}
