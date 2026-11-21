"use client";

import { useEffect, useState } from "react";
import { Badge, Card, Notice, Progress, Sheet, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { itemLabel, NEED_LABEL, PERS_LABEL, VALUE_LABEL } from "@/lib/world2";

type Detail = {
  notice: string; id: string; name: string; family: string; age: number; origin: string; generation: number; alive: boolean;
  death_cause: string | null; death_calendar: string | null; partner: string | null;
  parents: { id: string; name: string }[]; children: { id: string; name: string }[]; occupation: string;
  personality: Record<string, number>; values: Record<string, number>; interests: string[]; skills: Record<string, number>;
  techs: string[]; research: Record<string, number>; needs: Record<string, number>; health: number; exposure: number;
  status: string[]; illness: { name: string; severity: number } | null; satisfaction: number; inventory: Record<string, number>;
  wealth: number; currency: { name: string; value_in_food: number } | null;
  home: { label: string; condition: number; storage: Record<string, number> } | null; owned: { id: string; label: string; condition: number }[];
  contracts: Record<string, unknown>[]; debts: number; goals: { type: string; text: string }[];
  intention: { focus: string; text: string; by: string } | null; plans: string[]; action: string | null;
  thinking: { options: string[] } | null;
  relations: { id: string; name: string; trust: number; affection: number; respect: number; familiarity: number; partner: boolean; family: boolean; history: [number, string, number | null][] }[];
  memories: { t: number; k: string; x: string; imp: number; s: number }[]; recent: { k: string; x: string }[];
  knowledge: { k: string; x: string; src: string; conf: number }[]; bio: [number, string][];
  decisions: { t: number; by: string; model: string | null; chosen: string; why: string; options: { label: string; u: number }[] }[];
  model: { assigned: string; last_used: string | null }; stats: Record<string, number>;
};

const TABS = ["Überblick", "Beziehungen", "Gedächtnis", "Entscheidungen", "Biografie"] as const;
const SKILL_LABEL: Record<string, string> = {
  farming: "Ackerbau", gathering: "Sammeln", woodcutting: "Holzfällen", masonry: "Steinbruch", building: "Bauen", crafting: "Handwerk",
  healing: "Heilkunde", trading: "Handel", teaching: "Lehren", research: "Forschen", leadership: "Führung", art: "Kunst",
};
const FOCUS_LABEL: Record<string, string> = {
  vorraete: "Vorräte anlegen", bauen: "Bauen", handel: "Handel & Arbeit", politik: "Gemeinschaft & Politik", wissen: "Wissen & Kultur",
  familie: "Familie & Freunde", erholung: "Erholung", gemeinschaft: "Anderen helfen",
};

export function AgentInspector({ id, onClose, onSelect }: { id: string | null; onClose: () => void; onSelect: (id: string) => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Überblick");
  useEffect(() => {
    setD(null);
    if (!id) return;
    let alive = true;
    const load = () => api<Detail>(`/api/world2/agents/${id}`).then((x) => alive && setD(x)).catch(() => undefined);
    load();
    const t = setInterval(load, 4000);
    return () => { alive = false; clearInterval(t); };
  }, [id]);

  return (
    <Sheet open={!!id} onClose={onClose} title={d ? `${d.name} ${d.family}` : "Bewohner"}>
      {!d ? <div className="grid h-48 place-items-center"><Spinner /></div> : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="accent">Simulierter Agent</Badge>
            {d.status.map((s) => <Badge key={s} tone={s === "gesund" ? "ok" : s === "verstorben" ? "neutral" : "warn"}>{s}</Badge>)}
            <span className="text-[13px] text-fg-3">{d.age.toFixed(0)} J. · {d.origin} · Gen. {d.generation}</span>
          </div>
          <p className="text-[12px] leading-snug text-fg-3">{d.notice}</p>
          {!d.alive && <Notice tone="info">Verstorben {d.death_calendar} ({d.death_cause}). Die Person bleibt Teil der Geschichte.</Notice>}
          <div className="scroll-smooth-ios -mx-1 flex gap-1 overflow-x-auto px-1">
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)} className={`tap shrink-0 rounded-full px-3.5 text-[13px] font-medium ${tab === t ? "bg-white text-black" : "bg-white/8 text-fg-2"}`}>{t}</button>
            ))}
          </div>
          {tab === "Überblick" && <Overview d={d} />}
          {tab === "Beziehungen" && <Relations d={d} onSelect={onSelect} />}
          {tab === "Gedächtnis" && <Memory d={d} />}
          {tab === "Entscheidungen" && <Decisions d={d} />}
          {tab === "Biografie" && (
            <Card title="Lebenslauf">
              <ul className="space-y-1.5 text-[14px]">
                {d.bio.map(([t, txt], i) => <li key={i}><span className="mr-2 font-mono text-[11px] text-fg-3">T{t}</span>{txt}</li>)}
              </ul>
              {(d.parents.length > 0 || d.children.length > 0 || d.partner) && (
                <div className="mt-3 space-y-1 text-[13px] text-fg-2">
                  {d.partner && <div>Partner/in: {d.partner}</div>}
                  {d.parents.length > 0 && <div>Eltern: {d.parents.map((p) => <button key={p.id} className="mr-2 underline" onClick={() => onSelect(p.id)}>{p.name}</button>)}</div>}
                  {d.children.length > 0 && <div>Kinder: {d.children.map((p) => <button key={p.id} className="mr-2 underline" onClick={() => onSelect(p.id)}>{p.name}</button>)}</div>}
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </Sheet>
  );
}

function Bar({ label, v, invert }: { label: string; v: number; invert?: boolean }) {
  return (
    <div>
      <div className="mb-0.5 flex justify-between text-[12px]"><span className="text-fg-3">{label}</span><span className="tabular-nums text-fg-2">{Math.round(v * 100)} %</span></div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/8">
        <div className="h-full rounded-full" style={{ width: `${v * 100}%`, background: (invert ? 1 - v : v) > 0.66 ? "#ff8a80" : (invert ? 1 - v : v) > 0.4 ? "#fcd34d" : "#8b5cf6" }} />
      </div>
    </div>
  );
}

function Overview({ d }: { d: Detail }) {
  return (
    <div className="space-y-3">
      <Card title="Jetzt">
        <div className="text-[15px]">{d.action ?? "—"}</div>
        <div className="mt-1 text-[13px] text-fg-3">{d.occupation}</div>
        {d.thinking && <div className="mt-2 text-[13px] text-violet-2">Überlegt gerade zwischen: {d.thinking.options.join(" · ")}</div>}
        {d.intention && (
          <div className="mt-2 text-[13px] text-fg-2">
            Tagesabsicht: <b>{FOCUS_LABEL[d.intention.focus] ?? d.intention.focus}</b>{d.intention.text ? ` – „${d.intention.text}“` : ""}
            <span className="ml-1 text-fg-3">({d.intention.by})</span>
          </div>
        )}
      </Card>
      <Card title="Zustand (simuliert)">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          <Bar label="Gesundheit" v={d.health} invert />
          {Object.entries(d.needs).map(([k, v]) => <Bar key={k} label={NEED_LABEL[k] ?? k} v={v} invert={k === "energy"} />)}
          <Bar label="Kälte" v={d.exposure} />
          <Bar label="Zufriedenheit" v={d.satisfaction ?? 0} invert />
        </div>
        {d.illness && <div className="mt-2 text-[13px] text-[#ff8a80]">Erkrankt: {d.illness.name} (Schwere {Math.round(d.illness.severity * 100)} %)</div>}
      </Card>
      <Card title="Besitz">
        <div className="text-[14px]">Vermögen ≈ <b className="tabular-nums">{d.wealth}</b> Nahrungseinheiten{d.debts ? ` · ${d.debts} offene Schuld(en)` : ""}</div>
        <div className="mt-1 flex flex-wrap gap-1.5">{Object.entries(d.inventory).map(([k, n]) => <Badge key={k}>{n} {itemLabel(k)}</Badge>)}</div>
        <div className="mt-2 text-[13px] text-fg-2">Zuhause: {d.home ? `${d.home.label} (Zustand ${Math.round(d.home.condition * 100)} %)` : "keines"}</div>
        {d.owned.length > 0 && <div className="mt-1 text-[13px] text-fg-3">Eigentum: {d.owned.map((o) => o.label).join(", ")}</div>}
        {d.currency && <div className="mt-1 text-[13px] text-fg-3">Währung: {d.currency.name} (1 Münze ≈ {d.currency.value_in_food} Nahrung)</div>}
      </Card>
      <Card title="Ziele & Pläne">
        <ul className="list-disc space-y-1 pl-5 text-[14px]">{d.goals.map((g) => <li key={g.type}>{g.text}</li>)}</ul>
        {d.plans.length > 0 && <div className="mt-2 text-[13px] text-fg-2">Langfristige Überlegung (modellgeneriert): „{d.plans[0]}“</div>}
      </Card>
      <Card title="Persönlichkeit & Werte">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {Object.entries(d.personality).map(([k, v]) => <Bar key={k} label={PERS_LABEL[k] ?? k} v={v} />)}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.entries(d.values).sort((a, b) => b[1] - a[1]).map(([k, v]) => <Badge key={k} tone={v > 0.6 ? "accent" : "neutral"}>{VALUE_LABEL[k]} {Math.round(v * 100)}</Badge>)}
        </div>
        <div className="mt-2 text-[13px] text-fg-3">Interessen: {d.interests.join(", ")}</div>
      </Card>
      <Card title="Fähigkeiten & Wissen">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {Object.entries(d.skills).slice(0, 6).map(([k, v]) => <Bar key={k} label={SKILL_LABEL[k] ?? k} v={v} />)}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">{d.techs.map((t) => <Badge key={t}>{t}</Badge>)}</div>
        {Object.keys(d.research).length > 0 && <div className="mt-2 text-[13px] text-fg-3">Forscht an: {Object.entries(d.research).map(([k, v]) => `${k} (${Math.round(v * 100)} %)`).join(", ")}</div>}
      </Card>
      <div className="text-[12px] text-fg-3">Denkt mit: {d.model.assigned}{d.model.last_used ? ` · zuletzt verwendet: ${d.model.last_used}` : ""}</div>
    </div>
  );
}

function Relations({ d, onSelect }: { d: Detail; onSelect: (id: string) => void }) {
  return (
    <div className="space-y-2">
      {d.relations.length === 0 && <p className="text-[14px] text-fg-3">Noch keine engeren Beziehungen.</p>}
      {d.relations.map((r) => (
        <button key={r.id} onClick={() => onSelect(r.id)} className="tap card block w-full p-3 text-left">
          <div className="flex items-center justify-between">
            <span className="font-medium">{r.name}</span>
            <span className="flex gap-1">{r.partner && <Badge tone="accent">Partner/in</Badge>}{r.family && <Badge>Familie</Badge>}</span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-fg-3">
            <div>Vertrauen<Progress value={r.trust} /></div>
            <div>Zuneigung<Progress value={r.affection} /></div>
            <div>Respekt<Progress value={r.respect} /></div>
          </div>
          {r.history.length > 0 && <div className="mt-1.5 text-[12px] text-fg-3">Zuletzt: {r.history.slice(-3).map((h) => h[1]).join(" · ")}</div>}
        </button>
      ))}
    </div>
  );
}

function Memory({ d }: { d: Detail }) {
  return (
    <div className="space-y-3">
      <Card title="Wichtige Erinnerungen (Langzeit)">
        <ul className="space-y-2">
          {d.memories.map((m, i) => (
            <li key={i} className="text-[14px] leading-snug">
              <div className="text-[11px] text-fg-3">{m.k} · Wichtigkeit {m.imp} · Präsenz {m.s.toFixed(1)}</div>{m.x}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Kurzzeitgedächtnis">
        <ul className="space-y-1.5 text-[13px] text-fg-2">{d.recent.map((m, i) => <li key={i}>{m.x}</li>)}</ul>
      </Card>
      <Card title="Wissen über die Welt (mit Quelle)">
        <ul className="space-y-1.5">
          {d.knowledge.map((f, i) => (
            <li key={i} className="text-[13px] leading-snug">
              <Badge tone={f.src === "beobachtet" ? "ok" : f.src === "Gerücht" ? "warn" : "neutral"}>{f.src}</Badge> <span className="text-fg-2">{f.x}</span>
              <span className="ml-1 text-[11px] text-fg-3">({Math.round(f.conf * 100)} % sicher)</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function Decisions({ d }: { d: Detail }) {
  return (
    <div className="space-y-2">
      <p className="text-[12px] text-fg-3">Begründungen sind Ausgaben von Regeln oder des Sprachmodells – simulierte Zustände, keine nachweisbaren Gedanken.</p>
      {d.decisions.length === 0 && <p className="text-[14px] text-fg-3">Noch keine protokollierten Entscheidungen.</p>}
      {d.decisions.map((x, i) => (
        <div key={i} className="card p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[14px] font-medium">{x.chosen}</span>
            <Badge tone={x.model ? "accent" : "neutral"}>{x.model ? `Modell ${x.model}` : "Regeln"}</Badge>
          </div>
          {x.why && <div className="mt-1 text-[13px] text-fg-2">{x.why}</div>}
          {x.options.length > 0 && <div className="mt-1 text-[11px] text-fg-3">Optionen: {x.options.slice(0, 4).map((o) => `${o.label} (${o.u})`).join(" · ")}</div>}
          <div className="mt-0.5 font-mono text-[11px] text-fg-3">Tick {x.t}</div>
        </div>
      ))}
    </div>
  );
}

export function BuildingSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const [b, setB] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { setB(null); if (id) api<Record<string, unknown>>(`/api/world2/buildings/${id}`).then(setB).catch(() => undefined); }, [id]);
  return (
    <Sheet open={!!id} onClose={onClose} title={(b?.label as string) ?? "Gebäude"}>
      {!b ? <div className="grid h-32 place-items-center"><Spinner /></div> : b.site ? (
        <div className="space-y-2 text-[14px]">
          <Badge tone="warn">Baustelle</Badge>
          <div>Bauherr/in: {String(b.owner)}</div>
          <div>Arbeit: {Number(b.labor_done).toFixed(1)} / {String(b.labor_needed)} Stunden</div>
          <Progress value={Number(b.labor_done) / Number(b.labor_needed)} />
          <div>Material benötigt: {Object.entries(b.need as Record<string, number>).map(([k, n]) => `${n} ${itemLabel(k)}`).join(", ")}</div>
          <div>Geliefert: {Object.entries(b.inv as Record<string, number>).map(([k, n]) => `${n} ${itemLabel(k)}`).join(", ") || "nichts"}</div>
          <div className="text-fg-3">Helfende: {(b.workers as string[]).join(", ") || "—"}</div>
        </div>
      ) : (
        <div className="space-y-2 text-[14px]">
          <div>Eigentum: {String(b.owner ?? "herrenlos")} · {String(b.region)}</div>
          <div>Zustand {Math.round(Number(b.condition) * 100)} %</div><Progress value={Number(b.condition)} />
          <div className="text-fg-2">Gebaut: {String(b.built)} von {(b.builders as string[]).join(", ") || "—"}</div>
          {(b.residents as string[]).length > 0 && <div>Bewohnt von: {(b.residents as string[]).join(", ")}</div>}
          {Object.keys(b.storage as object).length > 0 && <div>Lager: {Object.entries(b.storage as Record<string, number>).map(([k, n]) => `${n} ${itemLabel(k)}`).join(", ")}</div>}
          {(b.documents as string[]).length > 0 && <div>Schriften: {(b.documents as string[]).join(", ")}</div>}
        </div>
      )}
    </Sheet>
  );
}
