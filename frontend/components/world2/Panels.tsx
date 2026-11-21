"use client";

import { useCallback, useEffect, useState } from "react";
import { LineChart, SERIES_A, SERIES_B } from "@/components/Charts";
import { Badge, Button, Card, Field, inputCls, Notice, Progress, Spinner, statusTone } from "@/components/ui";
import { api } from "@/lib/api";
import { CAT_LABEL, itemLabel, type W2Event } from "@/lib/world2";

// ------------------------------------------------------------------ feed
export function Feed({ live, regions, onActor, names }: { live: W2Event[]; regions: string[]; onActor: (id: string) => void; names: Record<string, string> }) {
  const [cat, setCat] = useState<string | null>(null);
  const [region, setRegion] = useState<string>("");
  const [older, setOlder] = useState<W2Event[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => { setOlder([]); }, [cat, region]);
  const filt = (e: W2Event) => (!cat || e.cat === cat) && (region === "" || String(e.region) === region);
  const items = [...live.filter(filt), ...older.filter((o) => !live.some((l) => l.id === o.id))];
  async function loadMore() {
    setLoading(true);
    const before = items.length ? items[items.length - 1].id : undefined;
    const q = new URLSearchParams({ limit: "40" });
    if (before) q.set("before", String(before));
    if (cat) q.set("cat", cat);
    if (region !== "") q.set("region", region);
    const r = await api<W2Event[]>(`/api/world2/events?${q}`).catch(() => []);
    setOlder((o) => [...o, ...r]);
    setLoading(false);
  }
  return (
    <div className="space-y-3">
      <div className="scroll-smooth-ios -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
        <Chip on={!cat} onClick={() => setCat(null)}>Alle</Chip>
        {Object.entries(CAT_LABEL).map(([k, l]) => <Chip key={k} on={cat === k} onClick={() => setCat(k)}>{l}</Chip>)}
      </div>
      <select className={inputCls} value={region} onChange={(e) => setRegion(e.target.value)}>
        <option value="">Alle Regionen</option>
        {regions.map((r, i) => <option key={r} value={i}>{r}</option>)}
      </select>
      <ul className="space-y-2">
        {items.length === 0 && <li className="text-[14px] text-fg-3">Noch keine Ereignisse in dieser Auswahl.</li>}
        {items.map((e) => (
          <li key={e.id} className="card animate-fade p-3">
            <div className="mb-0.5 flex items-center gap-2 text-[11px] text-fg-3">
              <Badge tone={e.cat === "justiz" ? "bad" : e.cat === "politik" ? "accent" : e.cat === "leben" ? "warn" : "neutral"}>{CAT_LABEL[e.cat] ?? e.cat}</Badge>
              <span>{e.calendar ?? `Tick ${e.tick}`}</span>
              {!e.public && <span title="Nicht öffentlich – nur in der Entwickleransicht sichtbar">🔒 objektiv, nicht öffentlich</span>}
              {typeof e.data?.generated_by === "string" && <Badge tone="accent">{String(e.data.generated_by)}</Badge>}
            </div>
            <div className="text-[14px] leading-snug">{e.text}</div>
            {e.actors.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-2">{e.actors.filter(Boolean).slice(0, 4).map((a) => (
                <button key={a} onClick={() => onActor(a)} className="text-[12px] text-violet-2 underline">{names[a] ?? a}</button>))}</div>
            )}
          </li>
        ))}
      </ul>
      <Button className="w-full" onClick={loadMore} loading={loading}>Ältere Ereignisse laden</Button>
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button onClick={onClick} className={`tap shrink-0 rounded-full px-3.5 text-[13px] font-medium ${on ? "bg-white text-black" : "bg-white/8 text-fg-2"}`}>{children}</button>;
}

// ------------------------------------------------------------------ society
type Society = {
  governments: { id: string; name: string; form_label: string; region: string; active: boolean; legitimacy: number; leaders: string[];
    founded: string; dissolved: string | null; protests: number; history: [number, string][]; treasury: Record<string, number>; vacant: boolean; members: number }[];
  institutions: { id: string; name: string; type: string; region: string; active: boolean; members: number; founder: string; founded: string }[];
  laws: { id: string; title: string; text: string; region: string; status: string; effect: string; params: Record<string, unknown>; adopted: string; repealed: string | null; proposer: string }[];
  proposals: { id: string; title: string; text: string; proposer: string; status: string; rule: string; created: string; votes: Record<string, number>;
    result: Record<string, unknown> | null; decided_by: string }[];
  cases: { id: string; type: string; accuser: string; accused: string; status: string; evidence: number; summary: string; opened: string;
    developer_truth: { offender: string | null; verdict_matches_truth: boolean | null } }[];
  currencies: { id: string; name: string; region: string; minted: number; rule: string }[];
  traditions: { id: string; name: string; status: string; held: number }[];
  artworks: { title: string; kind: string; author: string; calendar: string; titled_by: string }[];
  regions: { index: number; name: string; government: string | null }[];
};

export function SocietyPanel() {
  const [d, setD] = useState<Society | null>(null);
  const [truth, setTruth] = useState(false);
  const load = useCallback(() => api<Society>("/api/world2/society").then(setD).catch(() => undefined), []);
  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, [load]);
  if (!d) return <Spinner />;
  return (
    <div className="space-y-3">
      <Card title="Regionen & Regierungen">
        <div className="space-y-1 text-[14px]">
          {d.regions.map((r) => <div key={r.index} className="flex justify-between"><span>{r.name}</span><span className="text-fg-3">{r.government ?? "keine Regierung"}</span></div>)}
        </div>
      </Card>
      {d.governments.length === 0 && <Notice tone="info">Noch hat sich keine Regierung gebildet. Ob, wann und welche entsteht, entscheiden die Bewohner.</Notice>}
      {d.governments.map((g) => (
        <Card key={g.id} title={g.active ? "Regierung" : "Frühere Regierung"} action={<Badge tone={g.active ? "ok" : "neutral"}>{g.active ? "aktiv" : `bis ${g.dissolved}`}</Badge>}>
          <div className="font-medium">{g.name}</div>
          <div className="text-[13px] text-fg-3">{g.form_label} · {g.region} · gegründet {g.founded}</div>
          <div className="mt-2 text-[13px]">Legitimität {Math.round((g.legitimacy ?? 0) * 100)} %</div>
          <Progress value={g.legitimacy ?? 0} />
          <div className="mt-2 text-[13px] text-fg-2">Leitung: {g.leaders.join(", ") || (g.vacant ? "vakant" : "—")} · Proteste: {g.protests}</div>
          {Object.keys(g.treasury).length > 0 && <div className="text-[13px] text-fg-3">Kasse: {Object.entries(g.treasury).map(([k, n]) => `${n} ${itemLabel(k)}`).join(", ")}</div>}
          {g.history.length > 0 && <ul className="mt-2 space-y-0.5 text-[12px] text-fg-3">{g.history.map(([t, h], i) => <li key={i}>T{t}: {h}</li>)}</ul>}
        </Card>
      ))}
      <Card title={`Gesetze (${d.laws.filter((l) => l.status === "aktiv").length} aktiv)`}>
        {d.laws.length === 0 && <p className="text-[14px] text-fg-3">Keine Gesetze.</p>}
        <ul className="space-y-2">
          {d.laws.map((l) => (
            <li key={l.id} className="text-[14px]">
              <div className="flex items-center justify-between gap-2"><b>„{l.title}“</b><Badge tone={l.status === "aktiv" ? "ok" : "neutral"}>{l.status}</Badge></div>
              <div className="text-[12px] text-fg-3">{l.effect}{Object.keys(l.params).length ? ` (${Object.entries(l.params).map(([k, v]) => `${k}: ${v}`).join(", ")})` : ""} · {l.region} · seit {l.adopted} · von {l.proposer}</div>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Vorschläge & Abstimmungen">
        <ul className="space-y-2">
          {d.proposals.length === 0 && <li className="text-[14px] text-fg-3">Noch keine.</li>}
          {d.proposals.map((p) => (
            <li key={p.id} className="text-[14px]">
              <div className="flex items-center justify-between gap-2"><span>{p.title}</span><Badge tone={p.status === "angenommen" || p.status === "abgeschlossen" ? "ok" : p.status === "offen" ? "accent" : "neutral"}>{p.status}</Badge></div>
              <div className="text-[12px] text-fg-3">von {p.proposer} · {p.created} · {p.votes.ja} Ja / {p.votes.nein} Nein / {p.votes.enthaltung} Enth. · {p.rule}{p.decided_by && p.decided_by !== "regeln" ? ` · formuliert: ${p.decided_by}` : ""}</div>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Justiz: Behauptungen, Ermittlungen, Urteile" action={<button className="text-[12px] text-violet-2" onClick={() => setTruth(!truth)}>{truth ? "Wahrheit ausblenden" : "Objektive Wahrheit (Entwickler)"}</button>}>
        {d.cases.length === 0 && <p className="text-[14px] text-fg-3">Keine Fälle.</p>}
        <ul className="space-y-2">
          {d.cases.map((c) => (
            <li key={c.id} className="text-[14px]">
              <div className="flex items-center justify-between gap-2"><span>{c.accuser} beschuldigt {c.accused} ({c.type})</span><Badge tone={statusTone(c.status === "schuldig" ? "failed" : c.status === "freigesprochen" ? "completed" : "pending")}>{c.status}</Badge></div>
              <div className="text-[12px] text-fg-3">{c.opened} · Zeugen: {c.evidence}{c.summary ? ` · ${c.summary}` : ""}</div>
              {truth && <div className="text-[12px] text-warn">Objektiv: Täter/in laut Ereignislog: {c.developer_truth.offender ?? "keine Tat belegt"}; Urteil {c.developer_truth.verdict_matches_truth == null ? "offen" : c.developer_truth.verdict_matches_truth ? "stimmt mit der Wahrheit überein" : "stimmt NICHT mit der Wahrheit überein"}</div>}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Institutionen & Organisationen">
        {d.institutions.length === 0 && <p className="text-[14px] text-fg-3">Noch keine.</p>}
        <ul className="space-y-1 text-[14px]">{d.institutions.map((i) => <li key={i.id}>{i.name} <span className="text-[12px] text-fg-3">· {i.members} Mitglieder · gegründet {i.founded} von {i.founder}{i.active ? "" : " · aufgelöst"}</span></li>)}</ul>
      </Card>
      {(d.currencies.length > 0 || d.traditions.length > 0) && (
        <Card title="Währungen & Traditionen">
          <ul className="space-y-1 text-[14px]">
            {d.currencies.map((c) => <li key={c.id}>{c.name} ({c.region}): {c.minted} Münzen – {c.rule}</li>)}
            {d.traditions.map((t) => <li key={t.id}>{t.name} – {t.status}, {t.held}× gefeiert</li>)}
          </ul>
        </Card>
      )}
      <Card title="Kultur: neueste Werke">
        <ul className="space-y-1 text-[14px]">{d.artworks.map((a, i) => <li key={i}>„{a.title}“ <span className="text-[12px] text-fg-3">({a.kind}, {a.author}, {a.calendar}; Titel: {a.titled_by})</span></li>)}</ul>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ economy
type Economy = {
  wealth: { id: string; name: string; wealth: number }[]; gini: number; markets: Record<string, Record<string, { price: number; n: number }>>;
  contracts: { id: string; type: string; status: string; employer?: string; worker?: string; lender?: string; borrower?: string; wage?: number; wage_item?: string }[];
  contracts_total: number; ledger: { produced: Record<string, number>; consumed: Record<string, number>; initial: Record<string, number> };
  holdings: Record<string, number>; audit: { ok: boolean }; natural_resources: Record<string, { remaining: number; capacity: number | null }>;
};

export function EconomyPanel({ onSelect }: { onSelect: (id: string) => void }) {
  const [d, setD] = useState<Economy | null>(null);
  useEffect(() => { const load = () => api<Economy>("/api/world2/economy").then(setD).catch(() => undefined); load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, []);
  if (!d) return <Spinner />;
  const max = Math.max(1, ...d.wealth.map((x) => x.wealth));
  return (
    <div className="space-y-3">
      <Card title="Vermögensverteilung" action={<Badge>Gini {d.gini}</Badge>}>
        <div className="space-y-1.5">
          {d.wealth.map((x) => (
            <button key={x.id} onClick={() => onSelect(x.id)} className="flex w-full items-center gap-2 text-left text-[13px]">
              <span className="w-20 shrink-0 truncate">{x.name}</span>
              <span className="h-2 flex-1 overflow-hidden rounded-full bg-white/6"><span className="block h-full rounded-r-[4px]" style={{ width: `${(x.wealth / max) * 100}%`, background: SERIES_A }} /></span>
              <span className="w-12 text-right tabular-nums text-fg-2">{Math.round(x.wealth)}</span>
            </button>
          ))}
        </div>
        <p className="mt-2 text-[12px] text-fg-3">Vermögen in Nahrungseinheiten (Inventar, Gebäude, Münzen zum Marktkurs).</p>
      </Card>
      <Card title="Marktpreise (aus echten Tauschgeschäften)">
        {Object.keys(d.markets).length === 0 && <p className="text-[14px] text-fg-3">Noch keine Tauschgeschäfte.</p>}
        {Object.entries(d.markets).map(([region, items]) => (
          <div key={region} className="mb-2">
            <div className="text-[13px] font-medium">{region}</div>
            <div className="mt-1 flex flex-wrap gap-1.5">{Object.entries(items).map(([k, v]) => <Badge key={k}>{k.includes("@") ? `${itemLabel(k.split("@")[0])} in Münzen` : itemLabel(k)}: {v.price} ({v.n}×)</Badge>)}</div>
          </div>
        ))}
        <p className="text-[12px] text-fg-3">Preise ohne Währung in Nahrungseinheiten; gleitender Durchschnitt.</p>
      </Card>
      <Card title="Natürliche Ressourcen (verbleibend / Kapazität)">
        <div className="space-y-2">
          {Object.entries(d.natural_resources).map(([k, v]) => (
            <div key={k}><div className="mb-0.5 flex justify-between text-[12px]"><span className="text-fg-3">{k === "forage" ? "Sammelgut" : k === "fish" ? "Fisch" : itemLabel(k)}</span><span className="tabular-nums text-fg-2">{v.remaining}{v.capacity ? ` / ${v.capacity}` : ""}</span></div>
              {v.capacity ? <Progress value={v.remaining / v.capacity} /> : null}</div>
          ))}
        </div>
      </Card>
      <Card title="Verträge" action={<Badge>{d.contracts_total} insgesamt</Badge>}>
        <ul className="space-y-1 text-[13px]">
          {d.contracts.length === 0 && <li className="text-fg-3">Keine aktiven Verträge.</li>}
          {d.contracts.map((c) => <li key={c.id}>{c.type === "arbeit" ? `Arbeit: ${c.worker} bei ${c.employer} (${c.wage} ${itemLabel(c.wage_item ?? "")}/Tag)` : `Kredit: ${c.lender} → ${c.borrower}`}</li>)}
        </ul>
      </Card>
      <Card title="Stoffbilanz" action={<Badge tone={d.audit.ok ? "ok" : "bad"}>{d.audit.ok ? "ausgeglichen" : "Abweichung!"}</Badge>}>
        <table className="w-full text-[12px]">
          <thead className="text-fg-3"><tr><th className="text-left font-normal">Gut</th><th className="text-right font-normal">Start</th><th className="text-right font-normal">erzeugt</th><th className="text-right font-normal">verbraucht</th><th className="text-right font-normal">vorhanden</th></tr></thead>
          <tbody>
            {Object.keys(d.holdings).concat(Object.keys(d.ledger.produced)).filter((v, i, a) => a.indexOf(v) === i).map((k) => (
              <tr key={k} className="tabular-nums"><td>{itemLabel(k)}</td><td className="text-right">{d.ledger.initial[k] ?? 0}</td><td className="text-right">{d.ledger.produced[k] ?? 0}</td><td className="text-right">{d.ledger.consumed[k] ?? 0}</td><td className="text-right">{d.holdings[k] ?? 0}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-[12px] text-fg-3">Jedes Gut entsteht nur aus einer dokumentierten Quelle (Natur, Herstellung, Münzprägung durch eine Institution).</p>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ history
type Stat = Record<string, unknown> & { day: number; population: number; adults: number; children: number; avg_health: number; avg_satisfaction: number; gini: number; food_total: number; avg_stress: number };
type History = { stats: Stat[]; timeline: W2Event[]; deceased: { id: string; name: string; age: number; cause: string; died: string; bio: [number, string][] }[];
  notable: { id: string; name: string; alive: boolean; bio: [number, string][] }[]; governments_history: { name: string; form: string; founded: string; dissolved: string | null; history: [number, string][] }[] };

export function HistoryPanel({ onSelect }: { onSelect: (id: string) => void }) {
  const [d, setD] = useState<History | null>(null);
  useEffect(() => { const load = () => api<History>("/api/world2/history").then(setD).catch(() => undefined); load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);
  if (!d) return <Spinner />;
  const s = d.stats;
  const day = (x: number) => `Tag ${x + 1}`;
  return (
    <div className="space-y-3">
      <Card title="Bevölkerung"><LineChart xLabel={day} yMin={0} series={[
        { name: "Erwachsene", color: SERIES_A, points: s.map((x) => ({ x: x.day, y: x.adults })) },
        { name: "Kinder", color: SERIES_B, points: s.map((x) => ({ x: x.day, y: x.children })) }]} /></Card>
      <Card title="Durchschnittliche Gesundheit"><LineChart xLabel={day} yMin={0} yFormat={(v) => `${Math.round(v * 100)} %`} series={[{ name: "Gesundheit", color: SERIES_A, points: s.map((x) => ({ x: x.day, y: x.avg_health })) }]} /></Card>
      <Card title="Zufriedenheit (Erwachsene)"><LineChart xLabel={day} yMin={0} yFormat={(v) => `${Math.round(v * 100)} %`} series={[{ name: "Zufriedenheit", color: SERIES_A, points: s.map((x) => ({ x: x.day, y: x.avg_satisfaction })) }]} /></Card>
      <Card title="Ungleichheit (Gini)"><LineChart xLabel={day} yMin={0} series={[{ name: "Gini", color: SERIES_A, points: s.map((x) => ({ x: x.day, y: x.gini })) }]} /></Card>
      <Card title="Nahrungsvorräte gesamt"><LineChart xLabel={day} yMin={0} series={[{ name: "Nahrung", color: SERIES_A, points: s.map((x) => ({ x: x.day, y: x.food_total })) }]} /></Card>
      <Card title="Chronik">
        <ul className="space-y-2">
          {d.timeline.map((e) => <li key={e.id} className="text-[14px] leading-snug"><span className="mr-2 text-[11px] text-fg-3">{e.calendar}</span>{e.text}</li>)}
        </ul>
      </Card>
      {d.governments_history.length > 0 && (
        <Card title="Regierungsgeschichte">
          {d.governments_history.map((g, i) => <div key={i} className="mb-2 text-[14px]"><b>{g.name}</b> <span className="text-fg-3">({g.form}) {g.founded} – {g.dissolved ?? "heute"}</span>
            <ul className="text-[12px] text-fg-3">{g.history.map(([t, h], j) => <li key={j}>T{t}: {h}</li>)}</ul></div>)}
        </Card>
      )}
      <Card title="Biografien prägender Bewohner">
        {d.notable.map((n) => (
          <button key={n.id} onClick={() => onSelect(n.id)} className="mb-2 block w-full text-left">
            <div className="text-[14px] font-medium">{n.name} {n.alive ? "" : "†"}</div>
            <div className="text-[12px] text-fg-3">{n.bio.slice(-4).map((b) => b[1]).join(" · ")}</div>
          </button>
        ))}
      </Card>
      <Card title={`Verstorbene (${d.deceased.length})`}>
        {d.deceased.length === 0 && <p className="text-[14px] text-fg-3">Noch niemand.</p>}
        {d.deceased.map((x) => <button key={x.id} onClick={() => onSelect(x.id)} className="block w-full py-1 text-left text-[14px]">{x.name} <span className="text-[12px] text-fg-3">– {x.age} J., {x.cause}, {x.died}</span></button>)}
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ control
type Control = {
  world: { id: string; name: string; seed: number; tick: number } | null; running: boolean; stopped: boolean; speed: number; tick_rate: number;
  target_tick_rate: number; paused_reason: string | null; last_checkpoint: Record<string, number> | null; last_checkpoint_age_s: number;
  worlds: { id: string; name: string; seed: number }[]; active: string;
  mind: Record<string, number | boolean | string | null>; config: { max_population: number; max_memories: number; llm: { enabled: boolean; mode: string; calls_per_agent_day: number; timeout_ticks: number }; model: { default: string; canary: { version: string; agents: string[] } | null } };
  store: Record<string, number>; model_usage: { model: string; by: string; count: number }[];
  errors_recent: { tick: number; where: string; error: string }[]; agents: { id: string; name: string }[];
};

export function ControlPanel() {
  const [d, setD] = useState<Control | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; t: string } | null>(null);
  const [versions, setVersions] = useState<{ id: string; name: string; chat_allowed: boolean }[]>([]);
  const [nw, setNw] = useState({ name: "", seed: "" });
  const [canary, setCanary] = useState<{ version: string; agents: string[] }>({ version: "", agents: [] });
  const load = useCallback(() => api<Control>("/api/world2/control").then(setD).catch(() => undefined), []);
  useEffect(() => { load(); api<{ versions: { id: string; name: string; chat_allowed: boolean }[] }>("/api/models").then((r) => setVersions(r.versions)).catch(() => undefined); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);
  async function act(body: Record<string, unknown>, ok: string) {
    setMsg(null);
    try { const r = await api<Record<string, unknown>>("/api/world2/control", { method: "POST", json: body }); setMsg({ tone: "ok", t: ok + (r.backup ? `: ${r.backup}` : "") }); load(); }
    catch (e) { setMsg({ tone: "bad", t: (e as Error).message }); }
  }
  if (!d) return <Spinner />;
  const allowed = versions.filter((v) => v.chat_allowed);
  return (
    <div className="space-y-3">
      {msg && <Notice tone={msg.tone}>{msg.t}</Notice>}
      {d.paused_reason && <Notice tone="bad">{d.paused_reason}</Notice>}
      <Card title="Simulation">
        <div className="text-[14px]">{d.world?.name} <span className="text-fg-3">(Seed {d.world?.seed}, Tick {d.world?.tick})</span></div>
        <div className="mt-1 text-[13px] text-fg-3">Status: {d.running ? "läuft" : d.stopped ? "gestoppt" : "pausiert"} · {d.tick_rate} Ticks/s (Ziel {d.target_tick_rate}) · letzter Speicherstand vor {d.last_checkpoint_age_s} s</div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="primary" onClick={() => act({ action: "start" }, "Gestartet")}>Start</Button>
          <Button size="sm" onClick={() => act({ action: "pause" }, "Pausiert und gespeichert")}>Pause</Button>
          <Button size="sm" variant="danger" onClick={() => act({ action: "stop" }, "Gestoppt und gespeichert")}>Stopp</Button>
          <Button size="sm" onClick={() => act({ action: "save" }, "Gespeichert")}>Speichern</Button>
          <Button size="sm" onClick={() => act({ action: "backup" }, "Backup erstellt")}>Backup</Button>
        </div>
        <div className="mt-2 text-[12px] text-fg-3">Speicher: {Object.entries(d.store).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>
      </Card>
      <Card title="Sprachmodell der Bewohner">
        <div className="text-[13px] text-fg-2">Verfügbar: {d.mind.available ? "ja" : "nein"} · Anfragen {String(d.mind.requests ?? 0)} · beantwortet {String(d.mind.answered ?? 0)} · ungültig {String(d.mind.invalid ?? 0)} · zu spät {String((Number(d.mind.timeouts ?? 0) + Number(d.mind.stale ?? 0)))} · Warteschlange {String(d.mind.queue ?? 0)}</div>
        <p className="mt-1 text-[12px] text-fg-3">Bei hoher Geschwindigkeit reicht die Rechenzeit oft nicht; dann entscheiden Regeln (im Protokoll sichtbar). Modus „blockierend“ lässt die Welt auf das Modell warten.</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Field label="Modellnutzung"><select className={inputCls} value={d.config.llm.enabled ? "1" : "0"} onChange={(e) => act({ action: "limits", llm_enabled: e.target.value === "1" }, "Gespeichert")}><option value="1">an</option><option value="0">aus (nur Regeln)</option></select></Field>
          <Field label="Modus"><select className={inputCls} value={d.config.llm.mode} onChange={(e) => act({ action: "limits", llm_mode: e.target.value }, "Gespeichert")}><option value="async">asynchron</option><option value="blocking">blockierend</option></select></Field>
          <Field label="Anfragen/Agent/Tag"><input className={inputCls} type="number" defaultValue={d.config.llm.calls_per_agent_day} onBlur={(e) => act({ action: "limits", calls_per_agent_day: Number(e.target.value) }, "Gespeichert")} /></Field>
          <Field label="Max. Bevölkerung"><input className={inputCls} type="number" defaultValue={d.config.max_population} onBlur={(e) => act({ action: "limits", max_population: Number(e.target.value) }, "Gespeichert")} /></Field>
        </div>
      </Card>
      <Card title="Modellversionen kontrollieren">
        <Field label="Standardmodell für alle Bewohner" hint="Nur getestete Versionen (Basis oder bestanden) sind wählbar.">
          <select className={inputCls} value={d.config.model.default} onChange={(e) => act({ action: "model_policy", default_model: e.target.value }, "Modellrichtlinie gespeichert")}>
            {allowed.map((v) => <option key={v.id} value={v.id}>{v.id} – {v.name}</option>)}
          </select>
        </Field>
        <div className="mt-3 text-[13px] text-fg-2">Testgruppe (schrittweise Einführung): {d.config.model.canary ? `${d.config.model.canary.version} für ${d.config.model.canary.agents.length} Bewohner` : "keine"}</div>
        <div className="mt-2 grid gap-2">
          <select className={inputCls} value={canary.version} onChange={(e) => setCanary({ ...canary, version: e.target.value })}>
            <option value="">Version für Testgruppe wählen</option>
            {allowed.map((v) => <option key={v.id} value={v.id}>{v.id}</option>)}
          </select>
          <div className="flex flex-wrap gap-1.5">
            {d.agents.map((a) => {
              const on = canary.agents.includes(a.id);
              return <button key={a.id} onClick={() => setCanary({ ...canary, agents: on ? canary.agents.filter((x) => x !== a.id) : [...canary.agents, a.id].slice(0, 8) })}
                className={`tap rounded-full px-3 text-[12px] ${on ? "bg-violet text-white" : "bg-white/8 text-fg-2"}`}>{a.name}</button>;
            })}
          </div>
          <Button size="sm" disabled={!canary.version || !canary.agents.length} onClick={() => act({ action: "model_policy", default_model: d.config.model.default, canary_model: canary.version, canary_agents: canary.agents }, "Testgruppe gesetzt")}>Testgruppe übernehmen</Button>
        </div>
        <table className="mt-3 w-full text-[12px]">
          <thead className="text-fg-3"><tr><th className="text-left font-normal">Entscheider</th><th className="text-right font-normal">Entscheidungen</th></tr></thead>
          <tbody>{d.model_usage.map((m, i) => <tr key={i}><td>{m.by}</td><td className="text-right tabular-nums">{m.count}</td></tr>)}</tbody>
        </table>
      </Card>
      <Card title="Neue, getrennte Welt">
        <div className="grid grid-cols-2 gap-2">
          <input className={inputCls} placeholder="Name" value={nw.name} onChange={(e) => setNw({ ...nw, name: e.target.value })} />
          <input className={inputCls} placeholder="Seed (optional)" value={nw.seed} onChange={(e) => setNw({ ...nw, seed: e.target.value })} />
        </div>
        <Button className="mt-2 w-full" onClick={() => act({ action: "new_world", name: nw.name || "Neue Welt", seed: nw.seed ? Number(nw.seed) : undefined }, "Neue Welt erstellt (pausiert)")}>Neue Welt erstellen</Button>
        <div className="mt-3 space-y-1">
          {d.worlds.map((x) => (
            <div key={x.id} className="flex items-center justify-between text-[13px]">
              <span>{x.name} <span className="text-fg-3">({x.id})</span></span>
              {x.id === d.active ? <Badge tone="ok">aktiv</Badge> : <button className="text-violet-2" onClick={() => act({ action: "switch_world", world_id: x.id }, "Welt gewechselt")}>wechseln</button>}
            </div>
          ))}
        </div>
      </Card>
      <Card title="Fehlerprotokoll">
        {d.errors_recent.length === 0 ? <p className="text-[14px] text-fg-3">Keine Fehler.</p> : (
          <ul className="space-y-1 font-mono text-[11px]">{d.errors_recent.map((e, i) => <li key={i}>T{e.tick} {e.where}: {e.error}</li>)}</ul>
        )}
      </Card>
      <Notice tone="info">Die Simulation kann keine echten Aktionen ausführen (keine Zahlungen, E-Mails, Befehle oder Netzwerkzugriffe). Simulierte Gesetze haben keinen Einfluss auf diese Steuerung.</Notice>
    </div>
  );
}

