"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { W2Agent, W2Building, W2Map, W2Settlement, W2Site, W2State } from "@/lib/world2";
import { ORIGIN_COLOR } from "@/lib/world2";

const TILE = 12; // px per tile in the offscreen terrain layer
const TERRAIN_COLOR: Record<string, string> = {
  W: "#0b2440", R: "#1b4a78", M: "#4b4756", H: "#55543f", F: "#1d3a27", G: "#2c4527", A: "#3a5a2a", s: "#5a5034", t: "#465260", C: "#4a4a2c",
};
const FOREST_SHADE = ["#2c4527", "#24402a", "#1e3a26", "#173322"];

const BUILDING_COLOR: Record<string, string> = {
  huette: "#bfae8f", haus: "#d9c9a8", steinhaus: "#e5e1d8", bauernhof: "#a3c67a", werkstatt: "#c79a6b", lagerhaus: "#d6a76b",
  markt: "#fbbf24", versammlungshalle: "#a78bfa", schule: "#93c5fd", heilhaus: "#f87171", krankenhaus: "#fb7185",
  gericht: "#c4b5fd", bibliothek: "#818cf8", brunnen: "#60a5fa", strasse: "#9ca3af", bruecke: "#b08968", damm: "#a8a29e",
  wassermuehle: "#38bdf8", laden: "#f59e0b", wachhaus: "#60a5fa", gefaengnis: "#71717a",
};
const CAT_DOT: Record<string, string> = {
  vorraete: "#86efac", bauen: "#fbbf24", handel: "#f59e0b", politik: "#c4b5fd", wissen: "#93c5fd", gemeinschaft: "#f9a8d4",
  erholung: "#64748b", versorgung: "#5eead4", familie: "#fda4af",
};

type View = { s: number; ox: number; oy: number };
type Pick = { kind: "agent"; id: string } | { kind: "building"; id: string };

export function MapView(props: {
  map: W2Map; state: W2State; buildings: W2Building[]; sites: W2Site[]; settlements: W2Settlement[];
  onPick: (p: Pick) => void; selected?: string | null; height: number;
  traffic?: boolean; followed?: string[]; trackId?: string | null; rounded?: boolean;
}) {
  const { map, state } = props;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 360, h: props.height });
  const view = useRef<View>({ s: 1, ox: 0, oy: 0 });
  const fitted = useRef(false);
  const agentsRef = useRef<{ prev: Map<string, { x: number; y: number }>; cur: Map<string, { x: number; y: number }>; t: number; dur: number }>(
    { prev: new Map(), cur: new Map(), t: 0, dur: 1000 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ moved: number; pinchDist?: number; start?: View; mid?: { x: number; y: number } }>({ moved: 0 });
  const dataRef = useRef(props);
  dataRef.current = props;

  // offscreen terrain layer (re-rendered only when the map changes)
  const terrain = useMemo(() => {
    if (typeof document === "undefined") return null;
    const c = document.createElement("canvas");
    c.width = map.w * TILE;
    c.height = map.h * TILE;
    const g = c.getContext("2d")!;
    for (let y = 0; y < map.h; y++) {
      const row = map.terrain[y], wood = map.wood[y];
      for (let x = 0; x < map.w; x++) {
        const t = row[x];
        g.fillStyle = t === "F" ? FOREST_SHADE[Number(wood[x])] : TERRAIN_COLOR[t] ?? "#333";
        g.fillRect(x * TILE, y * TILE, TILE, TILE);
        if (t === "F" && wood[x] !== "0") {
          g.fillStyle = "rgba(20,60,35,0.9)";
          g.beginPath();
          g.arc(x * TILE + TILE / 2, y * TILE + TILE / 2, 2 + Number(wood[x]), 0, Math.PI * 2);
          g.fill();
        }
        if (t === "M") {
          g.fillStyle = "rgba(255,255,255,0.08)";
          g.beginPath();
          g.moveTo(x * TILE + 2, y * TILE + TILE - 2); g.lineTo(x * TILE + TILE / 2, y * TILE + 2); g.lineTo(x * TILE + TILE - 2, y * TILE + TILE - 2);
          g.fill();
        }
      }
    }
    // region borders (subtle)
    g.strokeStyle = "rgba(255,255,255,0.10)";
    g.lineWidth = 1;
    for (let y = 0; y < map.h; y++) {
      for (let x = 0; x < map.w; x++) {
        const r = map.region[y][x];
        if (x + 1 < map.w && map.region[y][x + 1] !== r) { g.beginPath(); g.moveTo((x + 1) * TILE, y * TILE); g.lineTo((x + 1) * TILE, (y + 1) * TILE); g.stroke(); }
        if (y + 1 < map.h && map.region[y + 1][x] !== r) { g.beginPath(); g.moveTo(x * TILE, (y + 1) * TILE); g.lineTo((x + 1) * TILE, (y + 1) * TILE); g.stroke(); }
      }
    }
    for (const [x, y] of map.roads) { g.fillStyle = "rgba(200,200,200,0.55)"; g.fillRect(x * TILE + 3, y * TILE + 3, TILE - 6, TILE - 6); }
    for (const [x, y] of map.bridges) { g.fillStyle = "#8b6b4a"; g.fillRect(x * TILE + 1, y * TILE + 3, TILE - 2, TILE - 6); }
    for (const [x, y] of map.flooded) { g.fillStyle = "rgba(59,130,246,0.45)"; g.fillRect(x * TILE, y * TILE, TILE, TILE); }
    return c;
  }, [map]);

  // traffic layer: how often residents walked over a tile (real counter kept by the simulation)
  const trafficLayer = useMemo(() => {
    if (typeof document === "undefined" || !map.traffic) return null;
    const c = document.createElement("canvas");
    c.width = map.w * TILE; c.height = map.h * TILE;
    const g = c.getContext("2d")!;
    const col = ["", "rgba(251,191,36,0.25)", "rgba(251,146,60,0.45)", "rgba(248,113,113,0.65)"];
    map.traffic.forEach((row, y) => {
      for (let x = 0; x < map.w; x++) {
        const v = Number(row[x]);
        if (v > 0) { g.fillStyle = col[v]; g.fillRect(x * TILE + 1, y * TILE + 1, TILE - 2, TILE - 2); }
      }
    });
    return c;
  }, [map]);

  // region centres for weather particles and labels
  const regionCentre = useMemo(() => {
    const acc: Record<string, { x: number; y: number; n: number }> = {};
    map.region.forEach((row, y) => [...row].forEach((ch, x) => {
      const k = String(ch.charCodeAt(0) - 65);
      (acc[k] ||= { x: 0, y: 0, n: 0 });
      acc[k].x += x; acc[k].y += y; acc[k].n += 1;
    }));
    return Object.fromEntries(Object.entries(acc).map(([k, v]) => [k, { x: v.x / v.n, y: v.y / v.n }]));
  }, [map]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: props.height }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: props.height });
    return () => ro.disconnect();
  }, [props.height]);

  // fit map initially (centre on the residents)
  useEffect(() => {
    if (fitted.current || !state.agents.length || size.w < 50) return;
    fitted.current = true;
    const s = Math.max(size.w / (map.w * TILE), size.h / (map.h * TILE)) * 1.6;
    const cx = state.agents.reduce((a, b) => a + b.x, 0) / state.agents.length;
    const cy = state.agents.reduce((a, b) => a + b.y, 0) / state.agents.length;
    view.current = clampView({ s, ox: size.w / 2 - (cx + 0.5) * TILE * s, oy: size.h / 2 - (cy + 0.5) * TILE * s }, size, map);
  }, [state.agents, size, map]);

  // agent interpolation buffers
  useEffect(() => {
    const ar = agentsRef.current;
    const now = performance.now();
    const next = new Map(state.agents.map((a) => [a.id, { x: a.x, y: a.y }]));
    const prev = new Map<string, { x: number; y: number }>();
    next.forEach((p, id) => {
      const k = Math.min(1, (now - ar.t) / ar.dur);
      const a0 = ar.prev.get(id), a1 = ar.cur.get(id);
      prev.set(id, a0 && a1 ? { x: a0.x + (a1.x - a0.x) * k, y: a0.y + (a1.y - a0.y) * k } : p);
    });
    ar.dur = Math.max(300, Math.min(3000, now - ar.t));
    ar.prev = prev; ar.cur = next; ar.t = now;
  }, [state.agents]);

  // render loop
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !terrain) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    cv.width = Math.round(size.w * dpr);
    cv.height = Math.round(size.h * dpr);
    const g = cv.getContext("2d")!;
    let raf = 0;
    let frames = 0, fpsT = performance.now();
    const particles = Array.from({ length: 140 }, () => ({ x: Math.random(), y: Math.random(), v: 0.4 + Math.random() * 0.6 }));
    const draw = () => {
      const { state: st, buildings, sites, settlements, selected, traffic, followed, trackId } = dataRef.current;
      // follow mode: keep the tracked resident centred (smoothly)
      if (trackId) {
        const ta = st.agents.find((a) => a.id === trackId);
        if (ta) {
          const cv0 = view.current, T0 = TILE * cv0.s;
          const tx = size.w / 2 - (ta.x + 0.5) * T0, ty = size.h / 2 - (ta.y + 0.5) * T0;
          view.current = clampView({ s: cv0.s, ox: cv0.ox + (tx - cv0.ox) * 0.08, oy: cv0.oy + (ty - cv0.oy) * 0.08 }, size, map);
        }
      }
      const v = view.current;
      const T = TILE * v.s;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.fillStyle = "#000";
      g.fillRect(0, 0, size.w, size.h);
      g.imageSmoothingEnabled = v.s < 1.5;
      g.drawImage(terrain, v.ox, v.oy, map.w * T, map.h * T);
      if (traffic && trafficLayer) g.drawImage(trafficLayer, v.ox, v.oy, map.w * T, map.h * T);
      // sites
      for (const s of sites) {
        const x = v.ox + s.x * T, y = v.oy + s.y * T;
        g.setLineDash([3, 3]); g.strokeStyle = "rgba(255,255,255,0.6)"; g.lineWidth = 1;
        g.strokeRect(x + 1, y + 1, T - 2, T - 2); g.setLineDash([]);
        g.fillStyle = "#a78bfa"; g.fillRect(x + 1, y + T - 3, (T - 2) * s.progress, 2);
      }
      // buildings
      for (const b of buildings) {
        const x = v.ox + b.x * T, y = v.oy + b.y * T;
        const c = BUILDING_COLOR[b.type] ?? "#ddd";
        g.globalAlpha = 0.45 + 0.55 * b.condition;
        if (b.type === "strasse" || b.type === "bruecke") { g.globalAlpha = 1; continue; }
        g.fillStyle = c;
        g.fillRect(x + T * 0.18, y + T * 0.38, T * 0.64, T * 0.5);
        g.beginPath(); g.moveTo(x + T * 0.1, y + T * 0.42); g.lineTo(x + T * 0.5, y + T * 0.1); g.lineTo(x + T * 0.9, y + T * 0.42); g.fill();
        g.globalAlpha = 1;
        if (b.id === selected) { g.strokeStyle = "#fff"; g.lineWidth = 2; g.strokeRect(x, y, T, T); }
      }
      // agents
      const ar = agentsRef.current;
      const k = Math.min(1, (performance.now() - ar.t) / ar.dur);
      const rad = Math.max(3, T * 0.36);
      // residents sharing a tile are spread in a small circle so each stays tappable and visible
      const groups = new Map<string, string[]>();
      for (const a of st.agents) { const key = `${a.x},${a.y}`; const g0 = groups.get(key); if (g0) g0.push(a.id); else groups.set(key, [a.id]); }
      for (const a of st.agents) {
        const p0 = ar.prev.get(a.id), p1 = ar.cur.get(a.id) ?? { x: a.x, y: a.y };
        const ax = p0 ? p0.x + (p1.x - p0.x) * k : p1.x, ay = p0 ? p0.y + (p1.y - p0.y) * k : p1.y;
        const grp = groups.get(`${a.x},${a.y}`)!;
        const gi = grp.indexOf(a.id), gn = grp.length;
        const spread = gn > 1 ? Math.min(0.42, 0.18 + 0.04 * gn) : 0;
        const ang = (gi / gn) * Math.PI * 2;
        const x = v.ox + (ax + 0.5 + Math.cos(ang) * spread) * T, y = v.oy + (ay + 0.5 + Math.sin(ang) * spread) * T;
        if (x < -20 || y < -20 || x > size.w + 20 || y > size.h + 20) continue;
        const r = a.child ? rad * 0.7 : rad;
        if (a.thinking) {
          g.strokeStyle = "rgba(167,139,250,0.9)"; g.lineWidth = 2;
          g.beginPath(); g.arc(x, y, r + 3 + Math.sin(performance.now() / 250) * 1.5, 0, Math.PI * 2); g.stroke();
        }
        g.globalAlpha = a.asleep ? 0.5 : 1;
        g.fillStyle = ORIGIN_COLOR[a.origin] ?? "#ddd";
        g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
        g.strokeStyle = a.id === selected ? "#fff" : followed?.includes(a.id) ? "#fbbf24" : "rgba(0,0,0,0.7)";
        g.lineWidth = a.id === selected || followed?.includes(a.id) ? 2.5 : 1; g.stroke();
        if (a.prisoner) { // bars: resident is in prison (real state)
          g.strokeStyle = "rgba(20,20,20,0.9)"; g.lineWidth = 1.2;
          for (let i = -1; i <= 1; i++) { g.beginPath(); g.moveTo(x + i * r * 0.5, y - r); g.lineTo(x + i * r * 0.5, y + r); g.stroke(); }
        }
        if (a.cat && !a.asleep && v.s > 1.1) { // activity category of the current real action
          g.fillStyle = CAT_DOT[a.cat] ?? "#e5e5e5";
          g.beginPath(); g.arc(x - r * 0.85, y + r * 0.85, Math.max(1.8, r * 0.3), 0, Math.PI * 2); g.fill();
        }
        if (a.ill) { g.fillStyle = "#ff453a"; g.beginPath(); g.arc(x + r * 0.8, y - r * 0.8, Math.max(2, r * 0.35), 0, Math.PI * 2); g.fill(); }
        g.globalAlpha = 1;
        const labelled = gi === 0 || a.id === selected || followed?.includes(a.id);
        if (v.s > 1.6 && labelled) {
          g.fillStyle = "rgba(255,255,255,0.9)"; g.font = `600 ${Math.max(9, T * 0.32)}px -apple-system, system-ui`;
          g.textAlign = "center"; g.fillText(gi === 0 && gn > 1 ? `${a.name} +${gn - 1}` : a.name, x, y - r - 3); g.textAlign = "left";
        }
      }
      // settlement labels
      g.font = `700 ${Math.max(11, Math.min(16, T * 0.5))}px -apple-system, system-ui`;
      for (const s of settlements) {
        if (!s.active) continue;
        const x = v.ox + (s.x + 0.5) * T, y = v.oy + s.y * T - T * 1.2;
        g.fillStyle = "rgba(0,0,0,0.55)";
        const tw = g.measureText(s.name).width;
        g.fillRect(x - tw / 2 - 6, y - 13, tw + 12, 18);
        g.fillStyle = "#f5f5f7"; g.textAlign = "center"; g.fillText(s.name, x, y); g.textAlign = "left";
      }
      // weather particles only where it is actually raining/snowing (real per-region state)
      const t = performance.now() / 1000;
      for (const p of particles) {
        const tx = Math.floor(p.x * map.w), ty = Math.floor(((p.y + t * 0.08 * p.v) % 1) * map.h);
        const reg = map.region[ty]?.[tx];
        if (!reg) continue;
        const wx = st.weather[String(reg.charCodeAt(0) - 65)];
        if (!wx || !["regen", "starkregen", "sturm", "schnee"].includes(wx.type)) continue;
        const x = v.ox + (p.x * map.w) * T, y = v.oy + (((p.y + t * 0.08 * p.v) % 1) * map.h) * T;
        if (wx.type === "schnee") { g.fillStyle = "rgba(255,255,255,0.75)"; g.beginPath(); g.arc(x, y, 1.6, 0, Math.PI * 2); g.fill(); }
        else { g.strokeStyle = "rgba(147,197,253,0.55)"; g.lineWidth = 1; g.beginPath(); g.moveTo(x, y); g.lineTo(x - 2, y + 7); g.stroke(); }
      }
      // day/night from the simulated clock
      const dark = (1 - st.daylight) * 0.55;
      if (dark > 0.01) { g.fillStyle = `rgba(5,8,30,${dark})`; g.fillRect(0, 0, size.w, size.h); }
      frames++;
      const now = performance.now();
      if (now - fpsT >= 1000) { (window as unknown as { __rubineFps?: number }).__rubineFps = Math.round(frames * 1000 / (now - fpsT)); frames = 0; fpsT = now; }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [terrain, trafficLayer, size, map, regionCentre]);

  // test hook: screen position (relative to the canvas) of a tile centre, used by scripts/mobile-test.js
  useEffect(() => {
    (window as unknown as { __rubineMap?: unknown }).__rubineMap = {
      toScreen: (tx: number, ty: number) => { const v = view.current; return { x: v.ox + (tx + 0.5) * TILE * v.s, y: v.oy + (ty + 0.5) * TILE * v.s }; },
    };
  }, []);

  const toWorld = useCallback((px: number, py: number) => {
    const v = view.current;
    return { x: (px - v.ox) / (TILE * v.s), y: (py - v.oy) / (TILE * v.s) };
  }, []);

  function pick(px: number, py: number) {
    const { state: st, buildings } = dataRef.current;
    const wpt = toWorld(px, py);
    let best: Pick | null = null, bd = 0.9;
    const groups = new Map<string, string[]>();
    for (const a of st.agents) { const key = `${a.x},${a.y}`; const g0 = groups.get(key); if (g0) g0.push(a.id); else groups.set(key, [a.id]); }
    for (const a of st.agents) {
      const grp = groups.get(`${a.x},${a.y}`)!, gi = grp.indexOf(a.id), gn = grp.length;
      const spread = gn > 1 ? Math.min(0.42, 0.18 + 0.04 * gn) : 0, ang = (gi / gn) * Math.PI * 2;
      const d = Math.hypot(a.x + 0.5 + Math.cos(ang) * spread - wpt.x, a.y + 0.5 + Math.sin(ang) * spread - wpt.y);
      if (d < bd) { bd = d; best = { kind: "agent", id: a.id }; }
    }
    if (!best) {
      const b = buildings.find((b) => Math.floor(wpt.x) === b.x && Math.floor(wpt.y) === b.y);
      if (b) best = { kind: "building", id: b.id };
      const s = dataRef.current.sites.find((s) => Math.floor(wpt.x) === s.x && Math.floor(wpt.y) === s.y);
      if (!best && s) best = { kind: "building", id: s.id };
    }
    if (best) props.onPick(best);
  }

  function zoomAt(px: number, py: number, factor: number) {
    const v = view.current;
    const s = Math.min(6, Math.max(0.35, v.s * factor));
    const k = s / v.s;
    view.current = clampView({ s, ox: px - (px - v.ox) * k, oy: py - (py - v.oy) * k }, size, map);
  }

  const onDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    gesture.current = { moved: 0, start: { ...view.current } };
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      gesture.current.pinchDist = Math.hypot(a.x - b.x, a.y - b.y);
      const r = (e.target as HTMLElement).getBoundingClientRect();
      gesture.current.mid = { x: (a.x + b.x) / 2 - r.left, y: (a.y + b.y) / 2 - r.top };
    }
  };
  const onMove = (e: React.PointerEvent) => {
    const prev = pointers.current.get(e.pointerId);
    if (!prev) return;
    const cur = { x: e.clientX, y: e.clientY };
    pointers.current.set(e.pointerId, cur);
    if (pointers.current.size === 2 && gesture.current.pinchDist && gesture.current.mid) {
      const [a, b] = [...pointers.current.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      const st = gesture.current.start!;
      const s = Math.min(6, Math.max(0.35, st.s * d / gesture.current.pinchDist));
      const m = gesture.current.mid, k = s / st.s;
      view.current = clampView({ s, ox: m.x - (m.x - st.ox) * k, oy: m.y - (m.y - st.oy) * k }, size, map);
      gesture.current.moved += 10;
      return;
    }
    const dx = cur.x - prev.x, dy = cur.y - prev.y;
    gesture.current.moved += Math.abs(dx) + Math.abs(dy);
    const v = view.current;
    view.current = clampView({ ...v, ox: v.ox + dx, oy: v.oy + dy }, size, map);
  };
  const onUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size === 0 && gesture.current.moved < 8) {
      const r = (e.target as HTMLElement).getBoundingClientRect();
      pick(e.clientX - r.left, e.clientY - r.top);
    }
  };

  return (
    <div ref={wrapRef} className={`relative w-full overflow-hidden ${props.rounded === false ? "" : "rounded-[22px] border border-white/8"}`} style={{ height: props.height }}>
      <canvas
        ref={canvasRef}
        style={{ width: size.w, height: size.h, touchAction: "none", display: "block" }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        onWheel={(e) => { const r = (e.target as HTMLElement).getBoundingClientRect(); zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.12 : 0.89); }}
        onDoubleClick={(e) => { const r = (e.target as HTMLElement).getBoundingClientRect(); zoomAt(e.clientX - r.left, e.clientY - r.top, 1.6); }}
        aria-label="Karte von Rubine World"
      />
      <div className="pointer-events-none absolute bottom-2 right-2 flex flex-col gap-1">
        <div className="pointer-events-auto flex gap-1">
          <button className="glass tap grid h-9 w-9 place-items-center rounded-xl text-lg" onClick={() => zoomAt(size.w / 2, size.h / 2, 1.3)} aria-label="Hineinzoomen">+</button>
          <button className="glass tap grid h-9 w-9 place-items-center rounded-xl text-lg" onClick={() => zoomAt(size.w / 2, size.h / 2, 0.77)} aria-label="Herauszoomen">−</button>
        </div>
      </div>
    </div>
  );
}

function clampView(v: View, size: { w: number; h: number }, map: { w: number; h: number }): View {
  const mw = map.w * TILE * v.s, mh = map.h * TILE * v.s;
  const minX = Math.min(0, size.w - mw) - 40, maxX = Math.max(0, size.w - mw) + 40;
  const minY = Math.min(0, size.h - mh) - 40, maxY = Math.max(0, size.h - mh) + 40;
  return { s: v.s, ox: Math.min(maxX, Math.max(minX, v.ox)), oy: Math.min(maxY, Math.max(minY, v.oy)) };
}
