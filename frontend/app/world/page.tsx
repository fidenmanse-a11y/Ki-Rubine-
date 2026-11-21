"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { BuildingSheet, AgentInspector } from "@/components/world2/Inspector";
import { MapView } from "@/components/world2/MapView";
import { ControlPanel, EconomyPanel, Feed, HistoryPanel, SocietyPanel } from "@/components/world2/Panels";
import { Notice, Spinner } from "@/components/ui";
import { api, useEventStream } from "@/lib/api";
import { SPEEDS, type W2Building, type W2Event, type W2Map, type W2Settlement, type W2Site, type W2State } from "@/lib/world2";

const TABS = ["Feed", "Gesellschaft", "Wirtschaft", "Geschichte", "Steuerung"] as const;
const WEATHER_ICON: Record<string, string> = { sonnig: "☀️", bewoelkt: "☁️", regen: "🌧", starkregen: "⛈", sturm: "🌪", schnee: "❄️", hitze: "🔥" };

export default function World2Page() {
  const [map, setMap] = useState<W2Map | null>(null);
  const [state, setState] = useState<W2State | null>(null);
  const [structs, setStructs] = useState<{ buildings: W2Building[]; sites: W2Site[]; settlements: W2Settlement[] }>({ buildings: [], sites: [], settlements: [] });
  const [events, setEvents] = useState<W2Event[]>([]);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Feed");
  const [agentSel, setAgentSel] = useState<string | null>(null);
  const [bldSel, setBldSel] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [vh, setVh] = useState(420);
  const mapVersion = useRef(-1);

  useEffect(() => {
    const f = () => setVh(Math.max(300, Math.min(560, Math.round(window.innerHeight * 0.5))));
    f();
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);

  const loadMap = useCallback(() => api<W2Map>("/api/world2/map").then((m) => {
    setMap(m); mapVersion.current = m.map_version;
    setStructs({ buildings: m.buildings, sites: m.sites, settlements: m.settlements });
  }).catch((e) => setErr(e.message)), []);

  useEffect(() => {
    loadMap();
    api<W2State>("/api/world2/state").then((s) => { setState(s); setEvents(s.events ?? []); }).catch((e) => setErr(e.message));
  }, [loadMap]);

  const onState = useCallback((s: W2State) => {
    setState(s);
    if (s.buildings) setStructs({ buildings: s.buildings, sites: s.sites ?? [], settlements: s.settlements ?? [] });
    if (s.events?.length) setEvents((ev) => [...s.events!.slice().reverse(), ...ev].slice(0, 200));
    if (s.map_version !== mapVersion.current && mapVersion.current >= 0) { mapVersion.current = s.map_version; loadMap(); }
  }, [loadMap]);
  const connected = useEventStream<W2State>("/api/world2/stream", "state", onState);

  async function setSpeed(speed: number) {
    try { await api("/api/world2/control", { method: "POST", json: speed === 0 ? { action: "pause" } : { action: "speed", speed } }); }
    catch (e) { setErr((e as Error).message); }
  }

  const names = Object.fromEntries((state?.agents ?? []).map((a) => [a.id, a.name]));
  const wx = state ? Object.entries(state.weather) : [];
  const temps = wx.map(([, v]) => v.temp);
  const mainWx = wx.length ? wx.reduce((acc, [, v]) => { acc[v.type] = (acc[v.type] ?? 0) + 1; return acc; }, {} as Record<string, number>) : {};
  const topWx = Object.entries(mainWx).sort((a, b) => b[1] - a[1])[0]?.[0];

  return (
    <main className="mx-auto max-w-3xl px-4 pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 96px)" }}>
      <header className="flex items-start justify-between gap-2 pb-2 pt-2">
        <div className="min-w-0">
          <h1 className="text-[28px] font-bold tracking-tight">Rubine World</h1>
          <p className="truncate text-[13px] text-fg-3">
            {state ? `${state.calendar.label} · ${state.population} Bewohner` : "…"}
            {topWx ? ` · ${WEATHER_ICON[topWx] ?? ""} ${Math.min(...temps).toFixed(0)}–${Math.max(...temps).toFixed(0)} °C` : ""}
            {!connected && state ? " · verbinde …" : ""}
          </p>
        </div>
        <Link href="/world/classic/" className="shrink-0 pt-2 text-[12px] text-fg-3">v0.1-Welt</Link>
      </header>

      <div className="glass mb-3 flex items-center gap-1 rounded-2xl p-1" role="group" aria-label="Simulationsgeschwindigkeit">
        {SPEEDS.map((sp) => {
          const active = state ? (sp === 0 ? !state.running : state.running && state.speed === sp) : false;
          return (
            <button key={sp} onClick={() => setSpeed(sp)} className={`tap flex-1 rounded-xl text-[14px] font-semibold ${active ? "bg-white text-black" : "text-fg-2"}`}>
              {sp === 0 ? "⏸" : `${sp}×`}
            </button>
          );
        })}
      </div>

      {err && <div className="mb-3"><Notice tone="bad">{err}</Notice></div>}
      {state?.paused_reason && <div className="mb-3"><Notice tone="bad">{state.paused_reason}</Notice></div>}

      {map && state ? (
        <MapView map={map} state={state} buildings={structs.buildings} sites={structs.sites} settlements={structs.settlements}
          height={vh} selected={agentSel ?? bldSel} onPick={(p) => (p.kind === "agent" ? setAgentSel(p.id) : setBldSel(p.id))} />
      ) : <div className="grid place-items-center rounded-[22px] border border-white/8" style={{ height: vh }}><Spinner /></div>}

      <p className="mt-2 text-[12px] leading-snug text-fg-3">
        Alle Bewohner sind simulierte Agenten. Karte, Gebäude und Ereignisse zeigen ausschließlich den echten Simulationszustand.
        Violetter Ring = wägt gerade mit dem Sprachmodell ab · roter Punkt = erkrankt.
      </p>

      <div className="scroll-smooth-ios sticky top-0 z-20 -mx-4 mt-3 flex gap-1.5 overflow-x-auto bg-black/80 px-4 py-2 backdrop-blur-xl">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`tap shrink-0 rounded-full px-4 text-[14px] font-medium ${tab === t ? "bg-white text-black" : "bg-white/8 text-fg-2"}`}>{t}</button>
        ))}
      </div>
      <div className="mt-2">
        {tab === "Feed" && <Feed live={events} regions={map?.regions ?? []} onActor={setAgentSel} names={names} />}
        {tab === "Gesellschaft" && <SocietyPanel />}
        {tab === "Wirtschaft" && <EconomyPanel onSelect={setAgentSel} />}
        {tab === "Geschichte" && <HistoryPanel onSelect={setAgentSel} />}
        {tab === "Steuerung" && <ControlPanel />}
      </div>

      <AgentInspector id={agentSel} onClose={() => setAgentSel(null)} onSelect={(id) => setAgentSel(id)} />
      <BuildingSheet id={bldSel} onClose={() => setBldSel(null)} />
    </main>
  );
}
