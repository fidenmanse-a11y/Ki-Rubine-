"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { AgentInspector, BuildingSheet } from "@/components/world2/Inspector";
import { MapView } from "@/components/world2/MapView";
import { ControlPanel, Feed } from "@/components/world2/Panels";
import { Notice, Spinner } from "@/components/ui";
import { api, useEventStream } from "@/lib/api";
import { SPEEDS, type W2Building, type W2Event, type W2Map, type W2Settlement, type W2Site, type W2State } from "@/lib/world2";

const WEATHER_ICON: Record<string, string> = { sonnig: "☀️", bewoelkt: "☁️", regen: "🌧", starkregen: "⛈", sturm: "🌪", schnee: "❄️", hitze: "🔥" };
const SHEETS = ["Ereignisse", "Steuerung"] as const;

export default function WorldPage() {
  const [map, setMap] = useState<W2Map | null>(null);
  const [state, setState] = useState<W2State | null>(null);
  const [structs, setStructs] = useState<{ buildings: W2Building[]; sites: W2Site[]; settlements: W2Settlement[] }>({ buildings: [], sites: [], settlements: [] });
  const [events, setEvents] = useState<W2Event[]>([]);
  const [tab, setTab] = useState<(typeof SHEETS)[number]>("Ereignisse");
  const [agentSel, setAgentSel] = useState<string | null>(null);
  const [bldSel, setBldSel] = useState<string | null>(null);
  const [track, setTrack] = useState<string | null>(null);
  const [traffic, setTraffic] = useState(false);
  const [followed, setFollowed] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [vh, setVh] = useState(480);
  const mapVersion = useRef(-1);

  useEffect(() => {
    const f = () => setVh(Math.max(320, Math.round(window.innerHeight - 190)));
    f();
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);

  useEffect(() => {
    // deep link from the people list: /world/?track=A0001
    const t = new URLSearchParams(location.search).get("track");
    if (t) setTrack(t);
    try { setTraffic(localStorage.getItem("rubine.traffic") === "1"); } catch { /* private mode */ }
  }, []);

  const loadMap = useCallback(() => api<W2Map>("/api/world2/map").then((m) => {
    setMap(m); mapVersion.current = m.map_version;
    setStructs({ buildings: m.buildings, sites: m.sites, settlements: m.settlements });
  }).catch((e) => setErr(e.message)), []);

  useEffect(() => {
    loadMap();
    api<W2State>("/api/world2/state").then((s) => { setState(s); setEvents(s.events ?? []); }).catch((e) => setErr(e.message));
    const lf = () => api<{ follow: { id: string }[] }>("/api/world2/follow").then((r) => setFollowed(r.follow.map((f) => f.id))).catch(() => undefined);
    lf();
    const t = setInterval(lf, 15000);
    // traffic changes slowly; refresh the layer every minute while visible
    const tm = setInterval(() => { if (document.visibilityState === "visible") loadMap(); }, 60000);
    return () => { clearInterval(t); clearInterval(tm); };
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
  function toggleTraffic() {
    setTraffic((v) => { try { localStorage.setItem("rubine.traffic", v ? "0" : "1"); } catch { /* ignore */ } return !v; });
  }

  const names = Object.fromEntries((state?.agents ?? []).map((a) => [a.id, a.name]));
  const wx = state ? Object.values(state.weather) : [];
  const temps = wx.map((v) => v.temp);
  const counts = wx.reduce((acc, v) => { acc[v.type] = (acc[v.type] ?? 0) + 1; return acc; }, {} as Record<string, number>);
  const topWx = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0];
  const ticker = events.filter((e) => e.public).slice(0, 1)[0];
  const tracked = track ? state?.agents.find((a) => a.id === track) : null;

  return (
    <main className="mx-auto max-w-3xl pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 96px)" }}>
      <div className="relative">
        {map && state ? (
          <MapView map={map} state={state} buildings={structs.buildings} sites={structs.sites} settlements={structs.settlements}
            height={vh} selected={agentSel ?? bldSel} traffic={traffic} followed={followed} trackId={track} rounded={false}
            onPick={(p) => (p.kind === "agent" ? setAgentSel(p.id) : setBldSel(p.id))} />
        ) : <div className="grid place-items-center" style={{ height: vh }}><Spinner /></div>}

        {/* top overlay: time, weather, population */}
        <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-2 p-3">
          <div className="glass-strong pointer-events-auto min-w-0 rounded-2xl px-3.5 py-2">
            <div className="text-[15px] font-semibold leading-tight">{state ? state.calendar.label : "…"}</div>
            <div className="truncate text-[12px] text-fg-3">
              {state ? `${state.population} Bewohner` : ""}
              {topWx ? ` · ${WEATHER_ICON[topWx] ?? ""} ${Math.min(...temps).toFixed(0)}–${Math.max(...temps).toFixed(0)} °C` : ""}
              {!connected && state ? " · verbinde …" : ""}
            </div>
          </div>
          <div className="pointer-events-auto flex gap-1.5">
            <button onClick={toggleTraffic} aria-pressed={traffic}
              className={`tap glass-strong grid h-11 min-w-11 place-items-center rounded-2xl px-3 text-[13px] font-medium ${traffic ? "text-[#fbbf24]" : "text-fg-2"}`}>Wege</button>
            <Link href="/world/classic/" className="tap glass-strong grid h-11 place-items-center rounded-2xl px-3 text-[12px] text-fg-3">v0.1</Link>
          </div>
        </div>

        {/* tracking chip */}
        {tracked && (
          <div className="absolute left-3 top-[76px]">
            <button onClick={() => setTrack(null)} className="tap glass-strong rounded-2xl px-3.5 text-[13px] font-medium text-[#fbbf24]">
              Folge {tracked.name} · {tracked.activity} ✕
            </button>
          </div>
        )}

        {/* bottom overlay: speed + live ticker */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 space-y-2 p-3">
          {ticker && (
            <button onClick={() => ticker.actors[0] && setAgentSel(ticker.actors[0])}
              className="glass-strong pointer-events-auto block max-w-[calc(100%-110px)] truncate rounded-2xl px-3.5 py-2 text-left text-[13px] animate-fade" key={ticker.id}>
              {ticker.text}
            </button>
          )}
          <div className="glass-strong pointer-events-auto flex max-w-[calc(100%-110px)] items-center gap-1 rounded-2xl p-1" role="group" aria-label="Simulationsgeschwindigkeit">
            {SPEEDS.map((sp) => {
              const active = state ? (sp === 0 ? !state.running : state.running && state.speed === sp) : false;
              return (
                <button key={sp} onClick={() => setSpeed(sp)} aria-pressed={active}
                  className={`tap min-h-11 flex-1 rounded-xl text-[14px] font-semibold ${active ? "bg-white text-black" : "text-fg-2"}`}>
                  {sp === 0 ? "⏸" : `${sp}×`}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="px-4">
        {err && <div className="mt-3"><Notice tone="bad">{err}</Notice></div>}
        {state?.paused_reason && <div className="mt-3"><Notice tone="bad">{state.paused_reason}</Notice></div>}
        <p className="mt-2 text-[12px] leading-snug text-fg-3">
          Simulierte Agenten. Alles auf der Karte ist echter Simulationszustand: Ring violett = denkt mit dem Sprachmodell,
          gold = verfolgt, Gitter = in Haft, roter Punkt = krank, kleiner Punkt = Art der aktuellen Tätigkeit. „Wege“ zeigt, wo viel gelaufen wird.
        </p>
        <div className="mt-3 flex gap-1.5">
          {SHEETS.map((t) => (
            <button key={t} onClick={() => setTab(t)} className={`tap rounded-full px-4 text-[14px] font-medium ${tab === t ? "bg-white text-black" : "bg-white/8 text-fg-2"}`}>{t}</button>
          ))}
        </div>
        <div className="mt-2">
          {tab === "Ereignisse" && <Feed live={events} regions={map?.regions ?? []} onActor={setAgentSel} names={names} />}
          {tab === "Steuerung" && <ControlPanel />}
        </div>
      </div>

      <AgentInspector id={agentSel} onClose={() => setAgentSel(null)} onSelect={(id) => setAgentSel(id)} onTrack={(id) => setTrack(id)} />
      <BuildingSheet id={bldSel} onClose={() => setBldSel(null)} onSelect={(id) => { setBldSel(null); setAgentSel(id); }} />
    </main>
  );
}
