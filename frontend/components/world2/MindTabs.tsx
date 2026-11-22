"use client";

import { Badge, Card, Progress } from "@/components/ui";

export type Goal = {
  id: string; type: string; text: string; why: string; prio: number; status: string; created: string; chosen_by: string;
  motivation: string | null; replans: number; plan_log: [string, string][];
  plan: { current: number; visible: number; horizon: number | null; revisions: number; steps: { text: string; expect: string | null; done: boolean; known: boolean }[] };
};

export type Mind = {
  available: boolean; notice: string; reasoning: number; morals: Record<string, number>; emotions: Record<string, number>; mood: string;
  agenda: Goal[]; goal_history: { type: string; text: string; status: string; when: string; why: string; replans: number; chosen_by: string }[];
  beliefs: { key: string; text: string; confidence: number; evidence: number; developer_truth: boolean | null }[];
  opinions: { id: string; name: string; honesty_estimate: number; uncertainty: number; suspicion: number; notes: [string, string][]; anger: number; gratitude: number }[];
  lessons: Record<string, number>; lesson_log: [string, string, number, string][];
  development: { when: string; morals: Record<string, number>; skills: Record<string, number>; mood: string }[];
  friends: { id: string; name: string }[]; alliances: { id: string; name: string; purpose: string }[];
  feuds: { with: string; since: string; intensity: number }[];
  promises: { id: string; from: string; to: string; text: string; status: string; due: string }[];
  secrets: { developer_only: boolean; items: [string, string][] };
  prison: { building: string; since: string; until: string; case: string } | null; convictions: number; probation_until: string | null;
  replan_pending: string | null; decision_sources: Record<string, number>; separation: Record<string, string>;
};

export const EMO_LABEL: Record<string, string> = {
  freude: "Freude", aerger: "Ärger", angst: "Angst", trauer: "Trauer", stolz: "Stolz", scham: "Scham", dankbarkeit: "Dankbarkeit",
};
export const MORAL_LABEL: Record<string, string> = {
  fuersorge: "Fürsorge", fairness: "Fairness", loyalitaet: "Loyalität", autoritaet: "Autorität", freiheit: "Freiheit", ehrlichkeit: "Ehrlichkeit",
};
const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "neutral" | "accent"> = {
  aktiv: "accent", "zurückgestellt": "warn", erreicht: "ok", aufgegeben: "bad", "hinfällig": "neutral",
};
const LESSON_LABEL: Record<string, string> = {
  steal: "Stehlen", trade: "Handeln", build_start: "Bauen beginnen", propose: "Vorschläge machen", talk: "Gespräche", help: "Helfen",
  persuade: "Überzeugen", spread_rumor: "Gerüchte", lend: "Verleihen", hire: "Anstellen", candidate: "Kandidieren",
};
const lessonLabel = (k: string) => (k.startsWith("ziel:") ? `Ziel „${k.slice(5)}“` : LESSON_LABEL[k] ?? k);

function Meter({ label, v, color = "#8b5cf6" }: { label: string; v: number; color?: string }) {
  return (
    <div>
      <div className="mb-0.5 flex justify-between text-[12px]"><span className="text-fg-3">{label}</span><span className="tabular-nums text-fg-2">{Math.round(v * 100)}</span></div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/8"><div className="h-full rounded-full" style={{ width: `${Math.min(100, v * 100)}%`, background: color }} /></div>
    </div>
  );
}

export function GoalsTab({ m }: { m: Mind }) {
  const active = m.agenda.filter((g) => g.status === "aktiv" || g.status === "zurückgestellt");
  return (
    <div className="space-y-3">
      {m.replan_pending && <div className="text-[13px] text-warn">Plant gerade neu: {m.replan_pending}</div>}
      {active.length === 0 && <p className="text-[14px] text-fg-3">Zurzeit keine eigenen Ziele (z. B. Kind oder gerade alles erreicht).</p>}
      {active.map((g) => (
        <Card key={g.id} title={<span className="normal-case tracking-normal text-fg">{g.text}</span>}
          action={<Badge tone={STATUS_TONE[g.status] ?? "neutral"}>{g.status}</Badge>}>
          <div className="text-[13px] text-fg-2">Warum: {g.why}</div>
          {g.motivation && <div className="mt-1 text-[13px] text-violet-2">Begründung (Sprachmodell): „{g.motivation}“</div>}
          <div className="mt-2 flex items-center gap-2 text-[12px] text-fg-3">
            <span>Priorität</span><div className="flex-1"><Progress value={g.prio} /></div><span className="tabular-nums">{Math.round(g.prio * 100)}</span>
          </div>
          <ol className="mt-3 space-y-1.5">
            {g.plan.steps.map((s, i) => (
              <li key={i} className={`flex gap-2 text-[14px] ${!s.known ? "opacity-40" : ""}`}>
                <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold ${
                  s.done ? "bg-ok/20 text-ok" : i === g.plan.current ? "bg-violet/30 text-white" : "bg-white/8 text-fg-3"}`}>{s.done ? "✓" : i + 1}</span>
                <span className="min-w-0">
                  <span className={i === g.plan.current ? "font-medium" : ""}>{s.known ? s.text : "(noch nicht durchdacht)"}</span>
                  {s.known && s.expect && i >= g.plan.current && <span className="block text-[12px] text-fg-3">Erwartung: {s.expect}</span>}
                </span>
              </li>
            ))}
          </ol>
          <div className="mt-2 text-[11px] text-fg-3">
            Gewählt von: {g.chosen_by === "regeln" ? "Regeln" : g.chosen_by} · seit {g.created} · {g.replans} Neuplanung(en)
            {g.plan.horizon != null && ` · Planungshorizont ${g.plan.horizon} Schritte`}
          </div>
          {g.plan_log.length > 0 && <div className="mt-1 text-[12px] text-fg-3">Planänderungen: {g.plan_log.map(([t, r]) => `${t}: ${r}`).join(" · ")}</div>}
        </Card>
      ))}
      <Card title="Frühere Ziele">
        {m.goal_history.length === 0 ? <p className="text-[13px] text-fg-3">Noch keine abgeschlossenen Ziele.</p> : (
          <ul className="space-y-1.5">
            {m.goal_history.map((h, i) => (
              <li key={i} className="flex items-start justify-between gap-2 text-[13px]">
                <span className="min-w-0"><span className="text-fg">{h.text}</span><span className="block text-[11px] text-fg-3">{h.when} · {h.why}</span></span>
                <Badge tone={STATUS_TONE[h.status] ?? "neutral"}>{h.status}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export function InnerTab({ m }: { m: Mind }) {
  return (
    <div className="space-y-3">
      <p className="text-[12px] leading-snug text-fg-3">{m.notice}</p>
      <Card title={`Simulierte Emotionen · Stimmung: ${m.mood}`}>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {Object.entries(m.emotions).map(([k, v]) => <Meter key={k} label={EMO_LABEL[k] ?? k} v={v}
            color={["aerger", "angst", "trauer", "scham"].includes(k) ? "#f87171" : "#34d399"} />)}
        </div>
      </Card>
      <Card title="Moralische Überzeugungen">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {Object.entries(m.morals).map(([k, v]) => <Meter key={k} label={MORAL_LABEL[k] ?? k} v={v} />)}
        </div>
        <p className="mt-2 text-[12px] text-fg-3">Ändern sich langsam durch Freundschaften und Erfahrungen.</p>
      </Card>
      <Card title="Denkvermögen (Simulationsparameter)">
        <Meter label="Planungstiefe / Ursachenerkennung" v={m.reasoning} />
        <p className="mt-2 text-[12px] text-fg-3">Bestimmt, wie viele Planschritte vorausgedacht werden und wie oft Ursachen richtig erkannt werden.</p>
      </Card>
      <Card title="Beziehungsnetz">
        <div className="text-[13px] text-fg-2">Freunde: {m.friends.map((f) => f.name).join(", ") || "—"}</div>
        {m.alliances.length > 0 && <div className="mt-1 text-[13px] text-fg-2">Bündnisse: {m.alliances.map((a) => `${a.name} (${a.purpose})`).join(", ")}</div>}
        {m.feuds.length > 0 && <div className="mt-1 text-[13px] text-[#ff8a80]">Fehden: {m.feuds.map((f) => `${f.with} (seit ${f.since})`).join(", ")}</div>}
        {m.promises.length > 0 && (
          <ul className="mt-2 space-y-1 text-[12px] text-fg-3">
            {m.promises.map((p) => <li key={p.id}>{p.from} → {p.to}: {p.text} · <b className="text-fg-2">{p.status}</b></li>)}
          </ul>
        )}
      </Card>
      {(m.prison || m.convictions > 0 || m.probation_until) && (
        <Card title="Justiz">
          {m.prison && <div className="text-[14px]">In Haft ({m.prison.building}) seit {m.prison.since}, bis {m.prison.until}</div>}
          <div className="text-[13px] text-fg-2">Verurteilungen: {m.convictions}{m.probation_until ? ` · Bewährung bis ${m.probation_until}` : ""}</div>
        </Card>
      )}
      <Card title="Geheimnisse (nur Entwickleransicht)">
        {m.secrets.items.length === 0 ? <p className="text-[13px] text-fg-3">Keine.</p> : (
          <ul className="space-y-1 text-[13px] text-fg-2">{m.secrets.items.map(([t, x], i) => <li key={i}><span className="text-fg-3">{t}:</span> {x}</li>)}</ul>
        )}
        <p className="mt-2 text-[11px] text-fg-3">Andere Bewohner kennen diese Information nicht – sie ist nur hier für dich sichtbar.</p>
      </Card>
    </div>
  );
}

export function KnowledgeTab({ m }: { m: Mind }) {
  return (
    <div className="space-y-3">
      <Card title="Überzeugungen (für wahr gehalten)">
        {m.beliefs.length === 0 ? <p className="text-[13px] text-fg-3">Noch keine gefestigten Überzeugungen.</p> : (
          <ul className="space-y-2">
            {m.beliefs.map((b) => (
              <li key={b.key} className="text-[14px]">
                <div className="flex items-start justify-between gap-2">
                  <span>„{b.text}“</span>
                  {b.developer_truth != null && <Badge tone={b.developer_truth ? "ok" : "bad"}>{b.developer_truth ? "stimmt" : "Irrtum"}</Badge>}
                </div>
                <div className="mt-1 flex items-center gap-2 text-[11px] text-fg-3">
                  <span>Sicherheit</span><div className="flex-1"><Progress value={b.confidence} /></div><span>{Math.round(b.confidence * 100)} %</span>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-[11px] text-fg-3">„stimmt/Irrtum“ ist die Entwickler-Wahrheit der Simulation – die Person selbst weiß das nicht.</p>
      </Card>
      <Card title="Einschätzungen anderer">
        {m.opinions.length === 0 ? <p className="text-[13px] text-fg-3">Noch keine.</p> : (
          <ul className="space-y-2.5">
            {m.opinions.map((o) => (
              <li key={o.id} className="text-[13px]">
                <div className="flex justify-between"><span className="font-medium text-fg">{o.name}</span>
                  <span className="text-fg-3">Ehrlichkeit ≈ {Math.round(o.honesty_estimate * 100)} % ± {Math.round(o.uncertainty * 100)}</span></div>
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {o.suspicion > 0.05 && <Badge tone="warn">Verdacht {Math.round(o.suspicion * 100)}</Badge>}
                  {o.anger > 0.05 && <Badge tone="bad">Ärger {Math.round(o.anger * 100)}</Badge>}
                  {o.gratitude > 0.05 && <Badge tone="ok">Dankbarkeit {Math.round(o.gratitude * 100)}</Badge>}
                </div>
                {o.notes.length > 0 && <div className="mt-0.5 text-[12px] text-fg-3">{o.notes.map((n) => n[1]).join(" · ")}</div>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export function DevelopmentTab({ m }: { m: Mind }) {
  const lessons = Object.entries(m.lessons).filter(([, v]) => Math.abs(v) > 0.005);
  return (
    <div className="space-y-3">
      <Card title="Was gespeichert wird – und was nicht">
        <ul className="space-y-1.5 text-[13px] text-fg-2">
          {Object.entries(m.separation).map(([k, v]) => <li key={k}>• {v}</li>)}
        </ul>
      </Card>
      <Card title="Gelernte Lektionen (Erfahrungswerte)">
        {lessons.length === 0 ? <p className="text-[13px] text-fg-3">Noch keine.</p> : (
          <div className="flex flex-wrap gap-1.5">
            {lessons.map(([k, v]) => <Badge key={k} tone={v > 0 ? "ok" : "bad"}>{lessonLabel(k)} {v > 0 ? "+" : ""}{v.toFixed(2)}</Badge>)}
          </div>
        )}
        {m.lesson_log.length > 0 && (
          <ul className="mt-3 space-y-1 text-[12px] text-fg-3">
            {m.lesson_log.map(([t, , d, txt], i) => <li key={i}><span className="text-fg-2">{txt}</span> ({d > 0 ? "+" : ""}{d}) · {t}</li>)}
          </ul>
        )}
      </Card>
      <Card title="Persönliche Entwicklung (wöchentlich)">
        {m.development.length < 2 ? <p className="text-[13px] text-fg-3">Noch zu wenige Messpunkte (alle 7 Tage einer).</p> : (
          <div className="space-y-2 text-[12px]">
            {Object.keys(m.development[0].morals).map((k) => {
              const first = m.development[0].morals[k], last = m.development[m.development.length - 1].morals[k];
              const d = last - first;
              return (
                <div key={k} className="flex justify-between">
                  <span className="text-fg-3">{MORAL_LABEL[k] ?? k}</span>
                  <span className="tabular-nums text-fg-2">{Math.round(first * 100)} → {Math.round(last * 100)} <span className={d > 0.005 ? "text-ok" : d < -0.005 ? "text-[#ff8a80]" : "text-fg-3"}>({d >= 0 ? "+" : ""}{(d * 100).toFixed(1)})</span></span>
                </div>
              );
            })}
            <div className="pt-1 text-fg-3">Stimmungsverlauf: {m.development.map((d) => d.mood).join(" → ")}</div>
          </div>
        )}
      </Card>
      <Card title="Herkunft der Entscheidungen">
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(m.decision_sources).map(([k, n]) => <Badge key={k} tone={k === "regeln" ? "neutral" : "accent"}>{k === "regeln" ? "Regeln" : k}: {n}</Badge>)}
          {Object.keys(m.decision_sources).length === 0 && <span className="text-[13px] text-fg-3">Bisher nur regelbasierte Alltagsentscheidungen.</span>}
        </div>
      </Card>
    </div>
  );
}
