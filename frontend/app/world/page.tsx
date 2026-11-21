"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IconPause, IconPlay, IconSpark } from "@/components/icons";
import { Badge, Button, Card, Notice, Sheet, Spinner } from "@/components/ui";
import { api, useEventStream } from "@/lib/api";
import type { AgentView, WorldEvent, WorldMap, WorldState } from "@/lib/types";

type AgentDetail = {
  persona: { name: string; age: number; occupation: string; traits: string[]; goals: string[]; skills: string[]; background: string; color: string };
  state: { activity: string; status: string; plan: string | null; location: string | null; stats: Record<string, number> };
  memories: { id: number; kind: string; content: string; importance: number; clock: string }[];
};

const KIND_ICON: Record<string, string> = {
  home: "⌂", cafe: "☕", library: "📚", townhall: "🏛", school: "🎓", lab: "🧪", park: "🌳", market: "🧺", workshop: "🔧",
};
const EVENT_TONE: Record<string, string> = {
  speech: "text-fg-2", task: "text-violet-2", verification: "text-ok", reflection: "text-azure-2", security: "text-bad", system: "text-fg-3",
};
const MEM_LABEL: Record<string, string> = { observation: "Beobachtung", conversation: "Gespräch", reflection: "Reflexion", plan: "Plan", task: "Aufgabe" };

export default function WorldPage() {
  const [map, setMap] = useState<WorldMap | null>(null);
  const [state, setState] = useState<WorldState | null>(null);
  const [events, setEvents] = useState<WorldEvent[]>([]);
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const prev = useRef<Map<string, { x: number; y: number }>>(new Map());
  const target = useRef<Map<string, { x: number; y: number }>>(new Map());
  const lastUpdate = useRef(0);

  useEffect(() => {
    api<WorldState>("/api/world/state").then((s) => { setState(s); setEvents((s.events ?? []).slice().reverse()); }).catch((e) => setErr(e.message));
    api<WorldMap>("/api/world/map").then(setMap).catch(() => undefined);
  }, []);

  const onState = useCallback((s: WorldState) => {
    const now = performance.now();
    for (const a of s.agents) {
      const cur = target.current.get(a.id);
      prev.current.set(a.id, cur ?? { x: a.x, y: a.y });
      target.current.set(a.id, { x: a.x, y: a.y });
    }
    lastUpdate.current = now;
    setState(s);
    if (s.events?.length) setEvents((ev) => [...s.events!.slice().reverse(), ...ev].slice(0, 120));
  }, []);
  const connected = useEventStream<WorldState>("/api/world/stream", "state", onState);

  async function control(action: string, extra: Record<string, unknown> = {}) {
    try {
      setErr(null);
      await api("/api/world/control", { method: "POST", json: { action, ...extra } });
    } catch (e) { setErr((e as Error).message); }
  }

  const agentsById = useMemo(() => new Map((state?.agents ?? []).map((a) => [a.id, a])), [state]);

  return (
    <main className="mx-auto max-w-3xl px-4 pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 96px)" }}>
      <header className="flex items-end justify-between pb-3 pt-2">
        <div>
          <h1 className="text-[30px] font-bold tracking-tight">Rubine World</h1>
          <p className="text-[14px] text-fg-3">
            {state ? state.clock.label : "…"} · {state?.agents.length ?? 0} Agenten
            {connected ? "" : " · verbinde …"}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" onClick={() => control(state?.running ? "pause" : "resume")} aria-label={state?.running ? "Pausieren" : "Fortsetzen"}>
            {state?.running ? <IconPause size={16} /> : <IconPlay size={16} />}
          </Button>
          <Button size="sm" onClick={() => setZoom((z) => (z === 1 ? 2 : 1))}>{zoom === 1 ? "2×" : "1×"}</Button>
        </div>
      </header>

      {err && <div className="mb-3"><Notice tone="bad">{err}</Notice></div>}
      {state && !state.llm.available && (
        <div className="mb-3"><Notice tone="warn">Agenten bewegen sich, sprechen aber nicht: {state.llm.detail}. Es werden keine Texte erfunden.</Notice></div>
      )}

      <div className="card scroll-smooth-ios overflow-auto p-0">
        {map && state ? (
          <WorldCanvas map={map} agents={state.agents} zoom={zoom} prev={prev} target={target} lastUpdate={lastUpdate}
            tickSeconds={state.tick_seconds} onPick={setSelected} task={state.task} />
        ) : (
          <div className="grid aspect-[3/2] place-items-center"><Spinner /></div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-[13px] text-fg-3">Tempo</span>
        {[4, 2, 1].map((t) => (
          <Button key={t} size="sm" variant={state?.tick_seconds === t ? "primary" : "glass"} onClick={() => control("speed", { tick_seconds: t })}>
            {t === 4 ? "Langsam" : t === 2 ? "Normal" : "Schnell"}
          </Button>
        ))}
        <Button size="sm" onClick={() => control("task")} className="ml-auto"><IconSpark size={16} /> Aufgabe stellen</Button>
      </div>

      {state?.task && <TaskCard task={state.task} agents={agentsById} />}

      <Card className="mt-4" title="Live-Ereignisse" action={<Badge>{state?.queue ?? 0} Gedanken in Warteschlange</Badge>}>
        <ul className="max-h-[420px] space-y-2.5 overflow-y-auto scroll-smooth-ios">
          {events.length === 0 && <li className="text-[14px] text-fg-3">Noch keine Ereignisse.</li>}
          {events.map((e, i) => (
            <li key={`${e.id ?? i}-${i}`} className="animate-fade text-[14px] leading-snug">
              <span className="mr-2 font-mono text-[11px] text-fg-3">{e.clock.replace(/^Tag \d+, \w+ /, "")}</span>
              <span className={EVENT_TONE[e.kind] ?? "text-fg-2"}>{e.content}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="mt-4" title="Bewohner">
        <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
          {state?.agents.map((a) => (
            <button key={a.id} onClick={() => setSelected(a.id)} className="tap flex items-center gap-3 rounded-xl px-2 py-1.5 text-left hover:bg-white/5">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[12px] font-bold text-black" style={{ background: a.color }}>
                {a.name.split(" ").map((p) => p[0]).join("")}
              </span>
              <div className="min-w-0">
                <div className="truncate text-[14px] font-medium">{a.name}</div>
                <div className="truncate text-[12px] text-fg-3">{a.activity}</div>
              </div>
            </button>
          ))}
        </div>
      </Card>

      <AgentSheet id={selected} onClose={() => setSelected(null)} />
    </main>
  );
}

function WorldCanvas(props: {
  map: WorldMap; agents: AgentView[]; zoom: number; tickSeconds: number; task: WorldState["task"];
  prev: React.RefObject<Map<string, { x: number; y: number }>>; target: React.RefObject<Map<string, { x: number; y: number }>>;
  lastUpdate: React.RefObject<number>; onPick: (id: string) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(360);
  const agentsRef = useRef(props.agents);
  agentsRef.current = props.agents;
  const posRef = useRef<Map<string, { x: number; y: number }>>(new Map());

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const cssW = width * props.zoom;
  const scale = cssW / props.map.width;
  const cssH = props.map.height * scale;

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    cv.width = Math.round(cssW * dpr);
    cv.height = Math.round(cssH * dpr);
    const ctx = cv.getContext("2d")!;
    let raf = 0;
    const draw = () => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#07070c";
      ctx.fillRect(0, 0, cssW, cssH);
      // subtle grid
      ctx.strokeStyle = "rgba(255,255,255,0.035)";
      ctx.lineWidth = 1;
      for (let x = 0; x <= props.map.width; x += 2) { ctx.beginPath(); ctx.moveTo(x * scale, 0); ctx.lineTo(x * scale, cssH); ctx.stroke(); }
      for (let y = 0; y <= props.map.height; y += 2) { ctx.beginPath(); ctx.moveTo(0, y * scale); ctx.lineTo(cssW, y * scale); ctx.stroke(); }
      // locations
      for (const l of props.map.locations) {
        const x = l.x * scale, y = l.y * scale, w = l.w * scale, h = l.h * scale, r = Math.min(10, scale * 1.2);
        ctx.fillStyle = l.color + "cc";
        ctx.strokeStyle = "rgba(255,255,255,0.12)";
        ctx.beginPath(); ctx.roundRect(x, y, w, h, r); ctx.fill(); ctx.stroke();
        if (props.task && l.id === "rathaus") {
          ctx.strokeStyle = "rgba(167,139,250,0.9)"; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.roundRect(x - 2, y - 2, w + 4, h + 4, r + 2); ctx.stroke(); ctx.lineWidth = 1;
        }
        ctx.fillStyle = "rgba(255,255,255,0.75)";
        ctx.font = `600 ${Math.max(9, scale * 0.95)}px -apple-system, system-ui, sans-serif`;
        ctx.textBaseline = "top";
        const label = `${KIND_ICON[l.kind] ?? ""} ${l.name.replace(" (Aufgabenbrett)", "")}`;
        ctx.fillText(label, x + 4, y + 3, w - 6);
      }
      // agents (interpolated)
      const t = Math.min(1, (performance.now() - (props.lastUpdate.current ?? 0)) / (props.tickSeconds * 1000));
      const speechers: { a: AgentView; x: number; y: number }[] = [];
      for (const a of agentsRef.current) {
        const p0 = props.prev.current?.get(a.id) ?? { x: a.x, y: a.y };
        const p1 = props.target.current?.get(a.id) ?? { x: a.x, y: a.y };
        const x = (p0.x + (p1.x - p0.x) * t) * scale;
        const y = (p0.y + (p1.y - p0.y) * t) * scale;
        posRef.current.set(a.id, { x, y });
        const rad = Math.max(5, scale * 0.62);
        if (a.status === "talking" || a.status === "task") {
          ctx.fillStyle = a.status === "task" ? "rgba(167,139,250,0.25)" : "rgba(96,165,250,0.22)";
          ctx.beginPath(); ctx.arc(x, y, rad * (1.7 + 0.2 * Math.sin(performance.now() / 300)), 0, Math.PI * 2); ctx.fill();
        }
        ctx.globalAlpha = a.status === "sleeping" ? 0.45 : 1;
        ctx.fillStyle = a.color;
        ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,0.6)"; ctx.stroke();
        ctx.fillStyle = "#0b0b10";
        ctx.font = `700 ${Math.max(7, rad * 0.95)}px -apple-system, system-ui, sans-serif`;
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(a.name[0], x, y + 0.5);
        ctx.textAlign = "left";
        ctx.globalAlpha = 1;
        if (a.speech) speechers.push({ a, x, y });
      }
      for (const { a, x, y } of speechers.slice(-3)) {
        const txt = a.speech!.length > 48 ? a.speech!.slice(0, 47) + "…" : a.speech!;
        ctx.font = `500 ${Math.max(10, scale * 0.9)}px -apple-system, system-ui, sans-serif`;
        const w = Math.min(ctx.measureText(txt).width + 14, cssW * 0.6);
        const bx = Math.min(Math.max(4, x - w / 2), cssW - w - 4);
        const by = Math.max(4, y - scale * 2.6 - 18);
        ctx.fillStyle = "rgba(20,20,30,0.92)";
        ctx.strokeStyle = "rgba(255,255,255,0.15)";
        ctx.beginPath(); ctx.roundRect(bx, by, w, 22, 11); ctx.fill(); ctx.stroke();
        ctx.fillStyle = "#f5f5f7"; ctx.textBaseline = "middle";
        ctx.fillText(txt, bx + 7, by + 11, w - 12);
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [cssW, cssH, scale, props.map, props.tickSeconds, props.task, props.prev, props.target, props.lastUpdate]);

  function onClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    let best: string | null = null, bd = Infinity;
    posRef.current.forEach((p, id) => {
      const d = Math.hypot(p.x - px, p.y - py);
      if (d < bd) { bd = d; best = id; }
    });
    if (best && bd < Math.max(22, scale * 2)) props.onPick(best);
  }

  return (
    <div ref={wrap} className="w-full">
      <canvas ref={ref} onClick={onClick} style={{ width: cssW, height: cssH, display: "block", touchAction: "pan-x pan-y" }} aria-label="2D-Karte von Rubine World" />
    </div>
  );
}

function TaskCard({ task, agents }: { task: NonNullable<WorldState["task"]>; agents: Map<string, AgentView> }) {
  const name = (id: string) => agents.get(id)?.name.split(" ")[0] ?? id;
  const stage = { solving: "Team löst unabhängig", reviewing: "Prüfer vergleicht", done: "Im Prüflabor verifiziert" }[task.stage] ?? task.stage;
  return (
    <Card className="mt-4" title="Aufgabenbrett" action={<Badge tone={task.stage === "done" ? "ok" : "accent"}>{stage}</Badge>}>
      <p className="text-[15px] leading-snug">{task.prompt}</p>
      <div className="mt-3 space-y-1.5">
        {task.team.map((id) => {
          const p = task.proposals.find((x) => x.agent === id);
          return (
            <div key={id} className="flex items-center justify-between rounded-xl bg-white/4 px-3 py-2 text-[14px]">
              <span>{name(id)}</span>
              <span className="flex items-center gap-2">
                <span className="font-mono text-fg-2">{p ? p.answer ?? "keine Antwortzeile" : "denkt …"}</span>
                {p?.correct === true && <Badge tone="ok">korrekt</Badge>}
                {p?.correct === false && <Badge tone="bad">falsch</Badge>}
              </span>
            </div>
          );
        })}
        <div className="text-[13px] text-fg-3">Prüfer: {name(task.reviewer)} · Familie: {task.family}</div>
      </div>
      {task.outcome && (
        <div className="mt-3">
          <Notice tone={task.outcome.correct > 0 ? "ok" : "warn"}>
            {task.outcome.correct}/{task.outcome.total} korrekt (Lösung: {task.outcome.expected}). {task.outcome.examples_added} verifizierte
            Beispiele für das Training gespeichert.
          </Notice>
        </div>
      )}
    </Card>
  );
}

function AgentSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const [d, setD] = useState<AgentDetail | null>(null);
  useEffect(() => {
    setD(null);
    if (id) api<AgentDetail>(`/api/world/agents/${id}`).then(setD).catch(() => undefined);
  }, [id]);
  return (
    <Sheet open={!!id} onClose={onClose} title={d?.persona.name ?? "Agent"}>
      {!d ? <div className="grid h-40 place-items-center"><Spinner /></div> : (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="grid h-12 w-12 place-items-center rounded-full text-[16px] font-bold text-black" style={{ background: d.persona.color }}>
              {d.persona.name.split(" ").map((p) => p[0]).join("")}
            </span>
            <div>
              <div className="font-medium">{d.persona.occupation}, {d.persona.age}</div>
              <div className="text-[13px] text-fg-3">{d.state.activity}</div>
            </div>
          </div>
          <p className="text-[14px] text-fg-2">{d.persona.background}</p>
          <div className="flex flex-wrap gap-1.5">{d.persona.traits.map((t) => <Badge key={t}>{t}</Badge>)}</div>
          <Card title="Ziele"><ul className="list-disc space-y-1 pl-5 text-[14px]">{d.persona.goals.map((g) => <li key={g}>{g}</li>)}</ul></Card>
          <Card title="Tagesplan">
            <p className="text-[14px]">{d.state.plan ?? "Noch kein vom Modell formulierter Plan – folgt dem Grundtagesablauf."}</p>
          </Card>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[["Gespräche", d.state.stats.conversations], ["Aufgaben", `${d.state.stats.tasks_correct ?? 0}/${d.state.stats.tasks ?? 0}`], ["Reflexionen", d.state.stats.reflections]].map(([l, v]) => (
              <div key={String(l)} className="card p-2.5"><div className="text-[18px] font-semibold">{v ?? 0}</div><div className="text-[11px] text-fg-3">{l}</div></div>
            ))}
          </div>
          <Card title={`Gedächtnis (${d.memories.length} neueste)`}>
            <ul className="space-y-2.5">
              {d.memories.length === 0 && <li className="text-[14px] text-fg-3">Noch keine Erinnerungen.</li>}
              {d.memories.map((m) => (
                <li key={m.id} className="text-[14px] leading-snug">
                  <div className="mb-0.5 flex items-center gap-2 text-[11px] text-fg-3">
                    <Badge tone={m.kind === "reflection" ? "accent" : m.kind === "task" ? "ok" : "neutral"}>{MEM_LABEL[m.kind] ?? m.kind}</Badge>
                    {m.clock} · Wichtigkeit {m.importance}
                  </div>
                  {m.content}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}
    </Sheet>
  );
}
