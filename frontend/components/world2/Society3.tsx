"use client";

import { useEffect, useState } from "react";
import { LineChart, SERIES_A, SERIES_B } from "@/components/Charts";
import { Badge, Card, Progress, Spinner, Stat } from "@/components/ui";
import { api } from "@/lib/api";

export type Society3 = {
  justice: {
    cases: { id: string; type: string; accuser: string; accused: string; accused_id: string; phase: string; opened: string; witnesses: number;
      exculpatory: number; statement: string | null; score: number | null; threshold: number | null; sanction: string | null; summary: string | null;
      log: [string, string][]; appeal: { status: string; filed: string; judge: string | null; exposed_false_witnesses: number } | null;
      developer_truth: { true_offender: string | null; verdict_matches_truth: boolean | null; false_testimony: number } }[];
    phases: Record<string, number>;
    prisons: { id: string; name: string; region: string; condition: number; inmates: { id: string; name: string; until: string; case: string }[] }[];
    totals: { verdicts: number; wrongful_convictions: number; overturned_wrongful: number; imprisonments: number; appeals: number };
  };
  alliances: { id: string; name: string; purpose: string; active: boolean; members: string[]; founded: string }[];
  feuds: { a: string; b: string; since: string; active: boolean; intensity: number; causes: string[] }[];
  promises: Record<string, number>;
  rumors: { total: number; exposed: number; developer_view: { origin: string; about: string; text: string; reach: number; exposed: boolean; false: boolean }[] };
  friendships: number;
  education: { schools: { id: string; name: string; region: string; taught_today: boolean }[]; children: number; school_children: number; literate_adults: number };
  settlements: { id: string; name: string; active: boolean; founded: string; founder: string | null; population: number; peak: number; homes: number;
    buildings: Record<string, number>; region: string }[];
};

const PHASE_LABEL: Record<string, string> = {
  behauptung: "Vorwurf", ermittlung: "Ermittlung", anklage: "Anklage", schuldig: "Schuldig", freigesprochen: "Freispruch",
  eingestellt: "Eingestellt", aufgehoben: "Aufgehoben", ungeklaert: "Ungeklärt",
};
const PHASE_TONE: Record<string, "ok" | "warn" | "bad" | "neutral" | "accent"> = {
  behauptung: "warn", ermittlung: "accent", anklage: "accent", schuldig: "bad", freigesprochen: "ok", eingestellt: "neutral", aufgehoben: "ok",
};

export function useSociety3() {
  const [d, setD] = useState<Society3 | null>(null);
  useEffect(() => {
    const load = () => api<Society3>("/api/world2/society3").then(setD).catch(() => undefined);
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);
  return d;
}

export function JusticePanel({ d, onSelect }: { d: Society3; onSelect: (id: string) => void }) {
  const j = d.justice;
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        <Stat label="Urteile" value={j.totals.verdicts} sub={`${j.totals.appeals} Berufungen`} />
        <Stat label="Fehlurteile" value={j.totals.wrongful_convictions} sub={`${j.totals.overturned_wrongful} aufgehoben`} />
        <Stat label="Haftstrafen" value={j.totals.imprisonments} sub={`${j.prisons.reduce((a, p) => a + p.inmates.length, 0)} derzeit in Haft`} />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(j.phases).map(([k, n]) => <Badge key={k} tone={PHASE_TONE[k] ?? "neutral"}>{PHASE_LABEL[k] ?? k}: {n}</Badge>)}
      </div>
      {j.prisons.length > 0 ? j.prisons.map((p) => (
        <Card key={p.id} title={`${p.name} · ${p.region}`}>
          <div className="mb-2 flex items-center gap-2 text-[12px] text-fg-3">Zustand<div className="flex-1"><Progress value={p.condition} /></div></div>
          {p.inmates.length === 0 ? <p className="text-[13px] text-fg-3">Keine Insassen.</p> : p.inmates.map((x) => (
            <button key={x.id} onClick={() => onSelect(x.id)} className="tap block w-full text-left text-[14px]">{x.name} <span className="text-[12px] text-fg-3">bis {x.until}</span></button>
          ))}
        </Card>
      )) : <p className="text-[13px] text-fg-3">Noch kein Gefängnis – Haftstrafen sind erst möglich, wenn die Bewohner eines bauen.</p>}
      <Card title="Verfahren">
        {j.cases.length === 0 && <p className="text-[13px] text-fg-3">Noch keine Verfahren.</p>}
        <ul className="divide-y divide-white/5">
          {j.cases.map((c) => (
            <li key={c.id} className="py-2">
              <button onClick={() => setOpen(open === c.id ? null : c.id)} className="tap block w-full text-left">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[14px] font-medium">{c.type}: {c.accuser} gegen {c.accused}</span>
                  <Badge tone={PHASE_TONE[c.phase] ?? "neutral"}>{PHASE_LABEL[c.phase] ?? c.phase}</Badge>
                </div>
                <div className="text-[12px] text-fg-3">{c.opened} · {c.witnesses} Zeugen{c.exculpatory ? ` · ${c.exculpatory} entlastend` : ""}{c.appeal ? ` · Berufung ${c.appeal.status}` : ""}</div>
              </button>
              {open === c.id && (
                <div className="mt-2 space-y-1.5 rounded-xl bg-white/5 p-3 text-[13px]">
                  {c.summary && <div>{c.summary}</div>}
                  {c.log.map(([t, x], i) => <div key={i} className="text-fg-3">{t}: {x}</div>)}
                  {c.score != null && <div className="text-fg-2">Beweiswert {c.score} (nötig {c.threshold}) · Aussage: {c.statement}</div>}
                  {c.appeal && <div className="text-fg-2">Berufung: {c.appeal.status}{c.appeal.judge ? ` (${c.appeal.judge})` : ""}{c.appeal.exposed_false_witnesses ? ` · ${c.appeal.exposed_false_witnesses} Falschaussage(n) aufgedeckt` : ""}</div>}
                  <div className="rounded-lg border border-white/10 p-2 text-[12px] text-fg-3">
                    Entwickler-Wahrheit: tatsächlich: {c.developer_truth.true_offender ?? "unbekannt / keine Tat"} ·
                    Urteil {c.developer_truth.verdict_matches_truth == null ? "offen" : c.developer_truth.verdict_matches_truth ? "korrekt" : "falsch"}
                    {c.developer_truth.false_testimony ? ` · ${c.developer_truth.false_testimony} Falschaussage(n)` : ""}
                  </div>
                  <button className="text-[13px] underline" onClick={() => onSelect(c.accused_id)}>Beschuldigte Person öffnen</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

export function SocialPanel({ d }: { d: Society3 }) {
  const pr = d.promises;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        <Stat label="Freundschaften" value={d.friendships} />
        <Stat label="Versprechen" value={(pr.gehalten ?? 0) + (pr.gebrochen ?? 0) + (pr.offen ?? 0)} sub={`${pr.gehalten ?? 0} gehalten · ${pr.gebrochen ?? 0} gebrochen`} />
        <Stat label="Gerüchte" value={d.rumors.total} sub={`${d.rumors.exposed} als Lüge entlarvt`} />
      </div>
      <Card title="Bündnisse">
        {d.alliances.length === 0 ? <p className="text-[13px] text-fg-3">Noch keine.</p> : d.alliances.map((a) => (
          <div key={a.id} className="mb-2 text-[14px]">
            <div className="flex items-center justify-between"><b>{a.name}</b>{!a.active && <Badge>aufgelöst</Badge>}</div>
            <div className="text-[12px] text-fg-3">{a.purpose} · seit {a.founded} · {a.members.join(", ")}</div>
          </div>
        ))}
      </Card>
      <Card title="Konflikte & Fehden">
        {d.feuds.length === 0 ? <p className="text-[13px] text-fg-3">Keine anhaltenden Konflikte.</p> : d.feuds.map((f, i) => (
          <div key={i} className="mb-2 text-[14px]">
            <div className="flex items-center justify-between"><span>{f.a} ↔ {f.b}</span><Badge tone={f.active ? "bad" : "ok"}>{f.active ? "aktiv" : "beigelegt"}</Badge></div>
            <div className="text-[12px] text-fg-3">seit {f.since}{f.causes.length ? ` · ${f.causes.join(", ")}` : ""}</div>
          </div>
        ))}
      </Card>
      <Card title="Gerüchte (Entwickleransicht)">
        {d.rumors.developer_view.length === 0 ? <p className="text-[13px] text-fg-3">Keine.</p> : d.rumors.developer_view.map((r, i) => (
          <div key={i} className="mb-2 text-[13px]">
            <div>„{r.text}“</div>
            <div className="text-[12px] text-fg-3">erfunden von {r.origin} über {r.about} · erreichte {r.reach} Person(en) · {r.exposed ? "entlarvt" : "nicht entlarvt"}</div>
          </div>
        ))}
        <p className="mt-1 text-[11px] text-fg-3">Gerüchte sind abstrakte Falschbehauptungen innerhalb der Simulation.</p>
      </Card>
    </div>
  );
}

type Stats = { day: number; adults: number; children: number; prisoners?: number; friendships?: number; goals_reached?: number; goals_abandoned?: number;
  avg_mood_anger?: number; avg_mood_joy?: number; avg_techs: number };

export function PopulationPanel({ d }: { d: Society3 }) {
  const [stats, setStats] = useState<Stats[] | null>(null);
  useEffect(() => { api<{ stats: Stats[] }>("/api/world2/history?limit_stats=400").then((h) => setStats(h.stats)).catch(() => undefined); }, []);
  const e = d.education;
  const day = (x: number) => `Tag ${x + 1}`;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        <Stat label="Kinder" value={e.children} sub={`${e.school_children} mit Schulbesuch`} />
        <Stat label="Schulen" value={e.schools.length} sub={`${e.schools.filter((s) => s.taught_today).length} heute mit Unterricht`} />
        <Stat label="Schriftkundige" value={e.literate_adults} sub="Erwachsene" />
      </div>
      {!stats ? <Spinner /> : (
        <>
          <Card title="Bevölkerung"><LineChart xLabel={day} yMin={0} series={[
            { name: "Erwachsene", color: SERIES_A, points: stats.map((x) => ({ x: x.day, y: x.adults })) },
            { name: "Kinder", color: SERIES_B, points: stats.map((x) => ({ x: x.day, y: x.children })) }]} /></Card>
          {stats.some((x) => x.goals_reached != null) && (
            <Card title="Erreichte vs. aufgegebene Ziele (kumuliert)"><LineChart xLabel={day} yMin={0} series={[
              { name: "erreicht", color: SERIES_A, points: stats.map((x) => ({ x: x.day, y: x.goals_reached ?? null })) },
              { name: "aufgegeben", color: SERIES_B, points: stats.map((x) => ({ x: x.day, y: x.goals_abandoned ?? null })) }]} /></Card>
          )}
          {stats.some((x) => x.avg_mood_joy != null) && (
            <Card title="Stimmung (Durchschnitt, simuliert)"><LineChart xLabel={day} yMin={0} yFormat={(v) => `${Math.round(v * 100)}`} series={[
              { name: "Freude", color: SERIES_A, points: stats.map((x) => ({ x: x.day, y: x.avg_mood_joy ?? null })) },
              { name: "Ärger", color: SERIES_B, points: stats.map((x) => ({ x: x.day, y: x.avg_mood_anger ?? null })) }]} /></Card>
          )}
          <Card title="Wissen (Ø Techniken pro Person)"><LineChart xLabel={day} yMin={0} series={[
            { name: "Techniken", color: SERIES_A, points: stats.map((x) => ({ x: x.day, y: x.avg_techs })) }]} /></Card>
        </>
      )}
      <Card title="Schulen">
        {e.schools.length === 0 ? <p className="text-[13px] text-fg-3">Noch keine Schule gebaut.</p> : e.schools.map((s) => (
          <div key={s.id} className="flex justify-between text-[14px]"><span>{s.name} · {s.region}</span><Badge tone={s.taught_today ? "ok" : "neutral"}>{s.taught_today ? "Unterricht heute" : "kein Unterricht heute"}</Badge></div>
        ))}
      </Card>
    </div>
  );
}

export function CitiesPanel({ d }: { d: Society3 }) {
  return (
    <div className="space-y-3">
      {d.settlements.length === 0 && <p className="text-[14px] text-fg-3">Noch keine Siedlung (mindestens 3 Wohngebäude nahe beieinander).</p>}
      {d.settlements.map((s) => (
        <Card key={s.id} title={s.name} action={<Badge tone={s.active ? "ok" : "neutral"}>{s.active ? "bewohnt" : "aufgegeben"}</Badge>}>
          <div className="text-[14px]">{s.population} Einwohner (Höchststand {s.peak}) · {s.homes} Wohngebäude · {s.region}</div>
          <div className="mt-1 text-[12px] text-fg-3">gegründet {s.founded}{s.founder ? ` von ${s.founder}` : ""}</div>
          <div className="mt-2 flex flex-wrap gap-1">{Object.entries(s.buildings).sort((a, b) => b[1] - a[1]).map(([k, n]) => <Badge key={k}>{n}× {k}</Badge>)}</div>
        </Card>
      ))}
    </div>
  );
}
