"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { FamilyBars, LossChart } from "@/components/Charts";
import { AgentBenchCard } from "@/components/lab/AgentBench";
import { IconPause, IconPlay, IconStop, IconUpload } from "@/components/icons";
import { Badge, Button, Card, Field, inputCls, Notice, Progress, Sheet, Spinner, Stat, statusLabel, statusTone } from "@/components/ui";
import { api, pct, timeAgo, useEventStream } from "@/lib/api";
import type { EngineInfo, FamilyStats, Job, ModelVersion } from "@/lib/types";

type Overview = {
  active_version: ModelVersion | null;
  engine: EngineInfo;
  system: SystemStats;
  world: { agents: number; running: boolean; clock: string } | null;
  jobs_open: Job[];
  training_job: Job | null;
  training_last_loss: number | null;
  datasets: number;
  examples: Record<string, Record<string, number>>;
  examples_total_approved: number;
  examples_pending: number;
  eval: { accuracy: number; eval_loss: number; n: number; per_family: FamilyStats; created_at: string } | null;
  curriculum_stage: { name: string };
  failed_jobs: number;
};
type SystemStats = {
  cpu_percent: number; cpu_count: number; ram_total_gb: number; ram_used_gb: number; ram_percent: number;
  server_rss_gb: number; disk_free_gb?: number; gpus: { name: string; mem_total_gb: number; mem_used_gb: number }[];
};
type LabStream = { jobs: Job[]; train_metrics?: { job_id: string; points: { step: number; loss: number | null }[] }; system?: SystemStats; engine?: EngineInfo };
type Teacher = { name: string; label: string; available: boolean; detail: string };
type Dataset = { id: string; sha256: string; n_examples: number; counts: { by_source: Record<string, number>; by_family: Record<string, number>; excluded: Record<string, number> }; created_at: string };
type Example = { id: string; messages: { role: string; content: string }[]; response: string; source: string; family: string | null; verified: boolean; meta: Record<string, unknown> | null };

const SOURCE_LABEL: Record<string, string> = {
  synthetic_gold: "Synthetisch (verifiziert)", agent_verified: "Agenten (verifiziert)", teacher_local: "Lokaler Lehrer",
  teacher_api: "API-Lehrer", manual_import: "Manueller Import", user_chat: "Nutzer-Chats (mit Zustimmung)",
  sim_gold: "Simulation (verifiziert)", sim_agent: "Simulation: Agententexte (Prüfung nötig)",
};
const JOB_LABEL: Record<string, string> = {
  train: "Training", evaluate: "Evaluation", compare: "Modellvergleich", synthetic: "Synthetische Daten",
  build_dataset: "Datensatz bauen", teacher: "Lehrer-Daten", sim_export: "Simulationsdaten",
};

export default function LabPage() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [live, setLive] = useState<LabStream | null>(null);
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [trainOpen, setTrainOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  const [jobDetail, setJobDetail] = useState<string | null>(null);
  const [cmp, setCmp] = useState<{ a: string; b: string }>({ a: "base", b: "" });

  const refresh = useCallback(() => {
    api<Overview>("/api/lab/overview").then(setOv).catch((e) => setMsg({ tone: "bad", text: e.message }));
    api<{ versions: ModelVersion[] }>("/api/lab/versions").then((r) => setVersions(r.versions)).catch(() => undefined);
    api<Job[]>("/api/lab/jobs?limit=40").then(setJobs).catch(() => undefined);
    api<Dataset[]>("/api/lab/datasets").then(setDatasets).catch(() => undefined);
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const lastOpen = useRef<string>("");
  useEventStream<LabStream>("/api/lab/stream", "lab", (d) => {
    setLive(d);
    const sig = d.jobs.map((j) => `${j.id}:${j.status}`).join(",");
    if (sig !== lastOpen.current) { lastOpen.current = sig; refresh(); }
  });

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ tone: "ok", text: ok }); refresh(); }
    catch (e) { setMsg({ tone: "bad", text: (e as Error).message }); }
  }

  const sys = live?.system ?? ov?.system;
  const engine = live?.engine ?? ov?.engine;
  const train = live?.jobs.find((j) => j.type === "train") ?? ov?.training_job ?? null;
  const points = live?.train_metrics && train && live.train_metrics.job_id === train.id ? live.train_metrics.points : [];
  const lastLoss = points.length ? points[points.length - 1].loss : ov?.training_last_loss;
  const openJobs = (live?.jobs ?? ov?.jobs_open ?? []).filter((j) => j.type !== "train");
  const comparable = versions.filter((v) => v.id === "base" || ["passed", "failed_eval"].includes(v.status));
  const lastCompare = jobs.find((j) => j.type === "compare" && j.status === "completed");

  return (
    <main className="mx-auto max-w-3xl px-4 pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 96px)" }}>
      <header className="pb-3 pt-2">
        <div className="flex items-center justify-between">
          <h1 className="text-[30px] font-bold tracking-tight">AI Lab</h1>
          <Link href="/settings/" className="tap glass grid place-items-center rounded-2xl px-4 text-[14px] font-medium">Einstellungen</Link>
        </div>
        <p className="text-[14px] text-fg-3">
          {engine ? `${engine.base_model} · ${engine.device ?? "—"} · Modell ${engine.status}` : "…"}
        </p>
      </header>
      {msg && <div className="mb-3"><Notice tone={msg.tone}>{msg.text}</Notice></div>}

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        <Stat label="Aktive Version" value={ov?.active_version?.id ?? "—"} sub={ov?.active_version?.name} />
        <Stat label="Eval-Genauigkeit" value={pct(ov?.eval?.accuracy)} sub={ov?.eval ? `${ov.eval.n} Testaufgaben · Stufe ${ov.curriculum_stage.name}` : "noch nicht evaluiert"} />
        <Stat label="KI-Agenten" value={ov?.world?.agents ?? 0} sub={ov?.world ? (ov.world.running ? "Simulation läuft" : "pausiert") : "Simulation aus"} />
        <Stat label="Trainingsbeispiele" value={ov?.examples_total_approved ?? 0} sub={`${ov?.examples_pending ?? 0} warten auf Prüfung`} />
        <Stat label="Datensätze" value={ov?.datasets ?? 0} sub="versioniert, gehasht" />
        <Stat label="Fehlgeschlagene Jobs" value={ov?.failed_jobs ?? 0} sub="siehe Verlauf" />
      </div>

      {/* Training */}
      <Card className="mt-4" title="Trainingsrunde" action={train && <Badge tone={statusTone(train.status)}>{statusLabel[train.status] ?? train.status}</Badge>}>
        {train ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-[14px]">
              <span className="text-fg-2">{train.message}</span>
              <span className="tabular-nums text-fg-3">{Math.round(train.progress * 100)} %</span>
            </div>
            <Progress value={train.progress} />
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-[13px] font-medium text-fg-2">Trainingsverlust (Loss)</span>
                <span className="text-[13px] tabular-nums text-fg-2">{lastLoss != null ? lastLoss.toFixed(4) : "—"}</span>
              </div>
              <LossChart points={points} />
            </div>
            <div className="flex flex-wrap gap-2">
              {train.status === "running" && <Button size="sm" onClick={() => act(() => api(`/api/lab/jobs/${train.id}/pause`, { method: "POST" }), "Pause angefordert – Checkpoint wird gespeichert.")}><IconPause size={15} /> Pausieren</Button>}
              {train.status === "paused" && <Button size="sm" variant="primary" onClick={() => act(() => api(`/api/lab/jobs/${train.id}/resume`, { method: "POST" }), "Training wird fortgesetzt.")}><IconPlay size={15} /> Fortsetzen</Button>}
              {["running", "paused", "queued", "pausing"].includes(train.status) && <Button size="sm" variant="danger" onClick={() => act(() => api(`/api/lab/jobs/${train.id}/stop`, { method: "POST" }), "Stopp angefordert.")}><IconStop size={15} /> Stoppen</Button>}
              <Button size="sm" variant="ghost" onClick={() => setJobDetail(train.id)}>Details</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-[14px] text-fg-2">
              Keine aktive Trainingsrunde. Ein Training baut einen versionierten Datensatz aus freigegebenen Beispielen, trainiert einen
              LoRA-Adapter und prüft ihn auf dem unabhängigen Testdatensatz. Aktiviert wird nie automatisch.
            </p>
            {engine?.device === "cpu" && <Notice tone="info">CPU-Modus: Das Training ist echt, aber langsam (ca. 5–10 s pro Schritt bei 0,5 B Parametern).</Notice>}
            <Button variant="primary" onClick={() => setTrainOpen(true)} disabled={(ov?.examples_total_approved ?? 0) === 0}>Training starten</Button>
            {(ov?.examples_total_approved ?? 0) === 0 && <p className="text-[13px] text-fg-3">Zuerst Trainingsdaten erzeugen oder importieren.</p>}
          </div>
        )}
      </Card>

      {openJobs.length > 0 && (
        <Card className="mt-4" title="Weitere Jobs">
          <div className="space-y-3">
            {openJobs.map((j) => (
              <div key={j.id}>
                <div className="mb-1 flex justify-between text-[14px]"><span>{JOB_LABEL[j.type] ?? j.type}</span><Badge tone={statusTone(j.status)}>{statusLabel[j.status] ?? j.status}</Badge></div>
                <Progress value={j.progress} />
                <div className="mt-1 flex items-center justify-between text-[12px] text-fg-3">
                  <span>{j.message}</span>
                  {["running", "queued"].includes(j.status) && <button className="text-bad" onClick={() => act(() => api(`/api/lab/jobs/${j.id}/stop`, { method: "POST" }), "Stopp angefordert.")}>Stoppen</button>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* System */}
      <Card className="mt-4" title="Ressourcen">
        {sys ? (
          <div className="grid grid-cols-2 gap-3 text-[14px]">
            <Meter label={`CPU (${sys.cpu_count} Kerne)`} value={sys.cpu_percent / 100} text={`${sys.cpu_percent.toFixed(0)} %`} />
            <Meter label="Arbeitsspeicher" value={sys.ram_percent / 100} text={`${sys.ram_used_gb} / ${sys.ram_total_gb} GB`} />
            {sys.gpus.length ? sys.gpus.map((g) => (
              <Meter key={g.name} label={g.name} value={g.mem_used_gb / g.mem_total_gb} text={`${g.mem_used_gb} / ${g.mem_total_gb} GB VRAM`} />
            )) : <div className="col-span-2 text-[13px] text-fg-3">Keine CUDA-GPU erkannt – Berechnungen laufen auf der CPU.</div>}
            <div className="text-[12px] text-fg-3">Server-Prozess: {sys.server_rss_gb} GB</div>
            {sys.disk_free_gb != null && <div className="text-[12px] text-fg-3">Freier Speicher: {sys.disk_free_gb} GB</div>}
          </div>
        ) : <Spinner />}
      </Card>

      {/* Eval */}
      {ov?.eval && (
        <Card className="mt-4" title={`Evaluation · aktive Version (${ov.eval.n} Aufgaben)`}>
          <FamilyBars a={ov.eval.per_family} labelA={ov.active_version?.id ?? ""} />
          <p className="mt-3 text-[12px] text-fg-3">Eval-Loss {ov.eval.eval_loss?.toFixed(4)} · {timeAgo(ov.eval.created_at)}</p>
        </Card>
      )}

      {/* Data */}
      <Card className="mt-4" title="Trainingsdaten" action={<Button size="sm" onClick={() => setDataOpen(true)}>Daten hinzufügen</Button>}>
        <div className="space-y-1.5 text-[14px]">
          {ov && Object.keys(ov.examples).length === 0 && <p className="text-fg-3">Noch keine Beispiele.</p>}
          {ov && Object.entries(ov.examples).map(([src, st]) => (
            <div key={src} className="flex justify-between">
              <span className="text-fg-2">{SOURCE_LABEL[src] ?? src}</span>
              <span className="tabular-nums">{st.approved ?? 0}{st.pending ? <span className="text-warn"> +{st.pending} offen</span> : null}{st.rejected ? <span className="text-fg-3"> · {st.rejected} abgelehnt</span> : null}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[12px] leading-snug text-fg-3">
          Selbst erzeugte Agenten-Antworten zählen nur, wenn sie gegen die Musterlösung verifiziert wurden, und dürfen höchstens 50 % eines Datensatzes ausmachen.
          Aufgaben aus dem Testdatensatz werden automatisch ausgeschlossen.
        </p>
        {datasets.length > 0 && (
          <div className="mt-3 border-t border-white/6 pt-3">
            <div className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-fg-3">Datensätze</div>
            {datasets.slice(0, 5).map((d) => (
              <div key={d.id} className="flex justify-between py-0.5 text-[13px]">
                <span className="font-mono">{d.id}</span>
                <span className="text-fg-3">{d.n_examples} Beispiele · {d.sha256.slice(0, 10)}…</span>
              </div>
            ))}
          </div>
        )}
        {(ov?.examples_pending ?? 0) > 0 && <ReviewQueue onChange={refresh} />}
      </Card>

      {/* Versions */}
      <Card className="mt-4" title="Modellversionen" action={<Button size="sm" onClick={() => act(() => api("/api/lab/rollback", { method: "POST" }), "Rollback durchgeführt.")}>Rollback</Button>}>
        <div className="space-y-2.5">
          {versions.map((v) => <VersionRow key={v.id} v={v} onAct={act} />)}
        </div>
      </Card>

      {/* Compare */}
      <Card className="mt-4" title="Modelle vergleichen">
        <div className="grid grid-cols-2 gap-2">
          {(["a", "b"] as const).map((k) => (
            <select key={k} className={inputCls} value={cmp[k]} onChange={(e) => setCmp({ ...cmp, [k]: e.target.value })}>
              <option value="">Version wählen</option>
              {comparable.map((v) => <option key={v.id} value={v.id}>{v.id} – {statusLabel[v.status] ?? v.status}</option>)}
            </select>
          ))}
        </div>
        <Button className="mt-2.5 w-full" disabled={!cmp.a || !cmp.b || cmp.a === cmp.b}
          onClick={() => act(() => api("/api/lab/compare", { method: "POST", json: cmp }), "Vergleich gestartet – identische Testaufgaben für beide Versionen.")}>
          Auf identischen Testaufgaben vergleichen
        </Button>
        {lastCompare?.result && <CompareResult r={lastCompare.result as unknown as CompareRes} />}
      </Card>

      <AgentBenchCard versions={versions} onMsg={(text, tone) => setMsg({ text, tone })} />

      {/* History */}
      <Card className="mt-4" title="Verlauf">
        <div className="divide-y divide-white/5">
          {jobs.map((j) => (
            <button key={j.id} onClick={() => setJobDetail(j.id)} className="tap flex w-full items-center justify-between gap-2 py-2 text-left">
              <div className="min-w-0">
                <div className="text-[14px] font-medium">{JOB_LABEL[j.type] ?? j.type}</div>
                <div className="truncate text-[12px] text-fg-3">{timeAgo(j.created_at)} · {j.error ? j.error.split("\n")[0] : j.message}</div>
              </div>
              <Badge tone={statusTone(j.status)}>{statusLabel[j.status] ?? j.status}</Badge>
            </button>
          ))}
          {jobs.length === 0 && <p className="py-2 text-[14px] text-fg-3">Noch keine Jobs.</p>}
        </div>
      </Card>

      <TrainSheet open={trainOpen} onClose={() => setTrainOpen(false)} datasets={datasets} versions={versions}
        onStarted={() => { setTrainOpen(false); setMsg({ tone: "ok", text: "Training in die Warteschlange gestellt." }); refresh(); }} />
      <DataSheet open={dataOpen} onClose={() => setDataOpen(false)} onDone={(t) => { setMsg({ tone: "ok", text: t }); refresh(); }} />
      <JobSheet id={jobDetail} onClose={() => setJobDetail(null)} />
    </main>
  );
}

function Meter({ label, value, text }: { label: string; value: number; text: string }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-[12px]"><span className="text-fg-3">{label}</span><span className="tabular-nums text-fg-2">{text}</span></div>
      <Progress value={Math.max(0, Math.min(1, value))} />
    </div>
  );
}

function VersionRow({ v, onAct }: { v: ModelVersion; onAct: (fn: () => Promise<unknown>, ok: string) => void }) {
  const [open, setOpen] = useState(false);
  const ev = v.metrics?.eval, pe = v.metrics?.parent_eval, gate = v.metrics?.gate, tr = v.metrics?.train;
  return (
    <div className={`rounded-2xl border p-3 ${v.active ? "border-violet/50 bg-violet/8" : "border-white/6 bg-white/3"}`}>
      <button className="flex w-full items-center justify-between gap-2 text-left" onClick={() => setOpen(!open)}>
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-medium">{v.name} {v.active && <Badge tone="accent">aktiv</Badge>}</div>
          <div className="text-[12px] text-fg-3">{v.id}{v.parent_id ? ` ← ${v.parent_id}` : ""} · {timeAgo(v.created_at)}{ev ? ` · Eval ${pct(ev.accuracy)}` : ""}</div>
        </div>
        <Badge tone={statusTone(v.status)}>{statusLabel[v.status] ?? v.status}</Badge>
      </button>
      {open && (
        <div className="mt-3 space-y-3 text-[13px] animate-fade">
          {tr && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-fg-2">
              <span>Schritte: {String(tr.steps)}</span><span>Beispiele: {String(tr.examples)}</span>
              <span>Loss Anfang: {Number(tr.mean_loss_first10).toFixed(3)}</span><span>Loss Ende: {Number(tr.mean_loss_last10).toFixed(3)}</span>
              <span>Dauer: {String(tr.seconds)} s</span><span>Gerät: {String(tr.device)}</span>
              <span>Datensatz: {v.dataset_id}</span><span>LoRA-Parameter: {Number(tr.trainable_params).toLocaleString("de-DE")}</span>
            </div>
          )}
          {ev && pe && (
            <>
              <div className="text-fg-2">Genauigkeit {pct(ev.accuracy)} vs. Eltern {pct(pe.accuracy)} · Eval-Loss {ev.eval_loss.toFixed(3)} vs. {pe.eval_loss.toFixed(3)}</div>
              <FamilyBars a={ev.per_family} b={pe.per_family} labelA={v.id} labelB={v.parent_id ?? "Eltern"} />
            </>
          )}
          {gate && (
            <Notice tone={gate.passed ? "ok" : "warn"}>
              <div className="font-medium">{gate.passed ? "Tests bestanden – zur Aktivierung vorgeschlagen" : "Tests nicht bestanden"}</div>
              <ul className="mt-1 list-disc pl-4">{gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </Notice>
          )}
          <div className="flex flex-wrap gap-2">
            {!v.active && ["passed", "base"].includes(v.status) && (
              <Button size="sm" variant="primary" onClick={() => onAct(() => api(`/api/lab/versions/${v.id}/activate`, { method: "POST" }), `${v.id} ist jetzt aktiv.`)}>Aktivieren</Button>
            )}
            {(v.id === "base" || ["passed", "failed_eval"].includes(v.status)) && (
              <Button size="sm" onClick={() => onAct(() => api("/api/lab/evaluate", { method: "POST", json: { version_id: v.id, force: true } }), "Evaluation gestartet.")}>Neu evaluieren</Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

type CompareRes = {
  a: { version_id: string; accuracy: number; eval_loss: number; n: number; per_family: FamilyStats };
  b: { version_id: string; accuracy: number; eval_loss: number; n: number; per_family: FamilyStats };
  only_a_correct: number; only_b_correct: number;
  diffs: { prompt: string; family: string; expected: string; a: { extracted: string | null; correct: boolean }; b: { extracted: string | null; correct: boolean } }[];
};

function CompareResult({ r }: { r: CompareRes }) {
  return (
    <div className="mt-4 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <Stat label={r.a.version_id} value={pct(r.a.accuracy)} sub={`Eval-Loss ${r.a.eval_loss.toFixed(3)} · nur hier richtig: ${r.only_a_correct}`} />
        <Stat label={r.b.version_id} value={pct(r.b.accuracy)} sub={`Eval-Loss ${r.b.eval_loss.toFixed(3)} · nur hier richtig: ${r.only_b_correct}`} />
      </div>
      <FamilyBars a={r.a.per_family} b={r.b.per_family} labelA={r.a.version_id} labelB={r.b.version_id} />
      {r.diffs.length > 0 && (
        <details className="rounded-xl bg-white/3 p-3 text-[13px]">
          <summary className="cursor-pointer text-fg-2">{r.diffs.length} Aufgaben mit unterschiedlichem Ergebnis</summary>
          <ul className="mt-2 space-y-2">
            {r.diffs.map((d, i) => (
              <li key={i} className="border-t border-white/5 pt-2">
                <div className="text-fg-2">{d.prompt.replace(/ Denke kurz.*$/, "")}</div>
                <div className="mt-0.5 font-mono text-[12px]">
                  Soll: {d.expected} · {r.a.version_id}: {d.a.extracted ?? "—"} {d.a.correct ? "✓" : "✗"} · {r.b.version_id}: {d.b.extracted ?? "—"} {d.b.correct ? "✓" : "✗"}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function TrainSheet({ open, onClose, onStarted, datasets, versions }: { open: boolean; onClose: () => void; onStarted: () => void; datasets: Dataset[]; versions: ModelVersion[] }) {
  const [p, setP] = useState({ dataset_id: "", parent_id: "", max_steps: 60, learning_rate: 0.0002, lora_r: 8, batch_size: 4, seed: 42, epochs: 1 });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const num = (k: keyof typeof p) => (e: React.ChangeEvent<HTMLInputElement>) => setP({ ...p, [k]: Number(e.target.value) });
  async function start() {
    setBusy(true); setErr(null);
    try {
      await api("/api/lab/jobs/train", { method: "POST", json: { ...p, dataset_id: p.dataset_id || null, parent_id: p.parent_id || null } });
      onStarted();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <Sheet open={open} onClose={onClose} title="Training starten">
      <div className="space-y-3.5">
        <Field label="Datensatz" hint="Neu: Snapshot aller freigegebenen Beispiele (versioniert & gehasht).">
          <select className={inputCls} value={p.dataset_id} onChange={(e) => setP({ ...p, dataset_id: e.target.value })}>
            <option value="">Neuen Datensatz bauen</option>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.id} ({d.n_examples})</option>)}
          </select>
        </Field>
        <Field label="Ausgangsversion" hint="Standard: aktive Version. Ein vorhandener Adapter wird weitertrainiert.">
          <select className={inputCls} value={p.parent_id} onChange={(e) => setP({ ...p, parent_id: e.target.value })}>
            <option value="">Aktive Version</option>
            {versions.filter((v) => ["passed", "base"].includes(v.status)).map((v) => <option key={v.id} value={v.id}>{v.id}</option>)}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Max. Schritte"><input type="number" className={inputCls} value={p.max_steps} min={1} max={5000} onChange={num("max_steps")} /></Field>
          <Field label="Epochen"><input type="number" className={inputCls} value={p.epochs} min={0.1} max={20} step={0.1} onChange={num("epochs")} /></Field>
          <Field label="Lernrate"><input type="number" className={inputCls} value={p.learning_rate} step={0.00005} onChange={num("learning_rate")} /></Field>
          <Field label="LoRA-Rang r"><input type="number" className={inputCls} value={p.lora_r} min={1} max={128} onChange={num("lora_r")} /></Field>
          <Field label="Batchgröße"><input type="number" className={inputCls} value={p.batch_size} min={1} max={64} onChange={num("batch_size")} /></Field>
          <Field label="Seed"><input type="number" className={inputCls} value={p.seed} onChange={num("seed")} /></Field>
        </div>
        <Notice tone="info">Nach dem Training folgt automatisch die Evaluation gegen die Ausgangsversion. Bestandene Versionen werden nur vorgeschlagen – du aktivierst sie selbst.</Notice>
        {err && <Notice tone="bad">{err}</Notice>}
        <Button variant="primary" className="w-full" loading={busy} onClick={start}>Echte Trainingsrunde starten</Button>
      </div>
    </Sheet>
  );
}

function DataSheet({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (t: string) => void }) {
  const [n, setN] = useState(300);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [seeds, setSeeds] = useState<{ name: string; examples: number }[]>([]);
  const [tn, setTn] = useState(30);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    setErr(null);
    api<Teacher[]>("/api/lab/teachers").then(setTeachers).catch(() => undefined);
    api<{ name: string; examples: number }[]>("/api/lab/data/seeds").then(setSeeds).catch(() => undefined);
  }, [open]);
  async function run(fn: () => Promise<unknown>, text: string) {
    setErr(null);
    try { const r = await fn(); onDone(typeof r === "object" && r && "stats" in r ? `${text}: ${JSON.stringify((r as { stats: unknown }).stats)}` : text); onClose(); }
    catch (e) { setErr((e as Error).message); }
  }
  async function upload(f: File) {
    const fd = new FormData();
    fd.append("file", f);
    await run(() => api("/api/lab/data/import?approve=false", { method: "POST", body: fd }), "Import abgeschlossen (Beispiele warten auf Prüfung)");
  }
  return (
    <Sheet open={open} onClose={onClose} title="Trainingsdaten hinzufügen">
      <div className="space-y-4">
        {err && <Notice tone="bad">{err}</Notice>}
        <Card title="Synthetische Aufgaben">
          <p className="mb-2 text-[13px] text-fg-3">Per Code erzeugte Aufgaben mit Musterlösung – korrekt durch Konstruktion und automatisch geprüft.</p>
          <div className="flex gap-2">
            <input type="number" className={inputCls} value={n} min={1} max={20000} onChange={(e) => setN(Number(e.target.value))} />
            <Button onClick={() => run(() => api("/api/lab/data/synthetic", { method: "POST", json: { n } }), "Erzeugung gestartet")}>Erzeugen</Button>
          </div>
        </Card>
        <Card title="Aus Rubine World">
          <p className="mb-2 text-[13px] text-fg-3">Verifizierbare Aufgaben aus echten Simulationsereignissen (Tauschpreise, Abstimmungen, Vorräte,
            Behauptung vs. Beobachtung). Antworten berechnet die World Engine; Testaufgaben aus der separaten Evaluationswelt sind ausgeschlossen.</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => run(() => api("/api/lab/data/simulation", { method: "POST", json: { per_family: 60 } }), "Simulations-Export gestartet")}>Verifizierte Aufgaben exportieren</Button>
            <Button variant="ghost" onClick={() => run(() => api("/api/lab/data/simulation", { method: "POST", json: { per_family: 60, include_dialogs: true } }), "Export inkl. Dialoge gestartet (Dialoge warten auf Prüfung)")}>+ Dialoge zur Prüfung</Button>
            <Button variant="ghost" onClick={() => run(() => api("/api/lab/data/simulation", { method: "POST", json: { resident_decisions: true } }), "Bewohner-Entscheidungen werden aus separaten Trainingswelten erzeugt")}>+ Bewohner-Entscheidungen</Button>
          </div>
        </Card>
        <Card title="Seed-Daten (von Claude Code erstellt)">
          {seeds.length === 0 && <p className="text-[13px] text-fg-3">Keine Seed-Dateien gefunden.</p>}
          {seeds.map((s) => (
            <div key={s.name} className="flex items-center justify-between gap-2 py-1">
              <span className="truncate font-mono text-[13px]">{s.name} ({s.examples})</span>
              <Button size="sm" onClick={() => run(() => api("/api/lab/data/seeds/import", { method: "POST", json: { name: s.name, approve: true } }), `Seed ${s.name} importiert`)}>Importieren</Button>
            </div>
          ))}
        </Card>
        <Card title="Lehrer-Modelle">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[13px] text-fg-3">Aufgaben:</span>
            <input type="number" className={`${inputCls} w-24`} value={tn} min={1} max={2000} onChange={(e) => setTn(Number(e.target.value))} />
          </div>
          {teachers.filter((t) => t.name !== "manual_import").map((t) => (
            <div key={t.name} className="flex items-center justify-between gap-2 border-t border-white/5 py-2">
              <div className="min-w-0">
                <div className="text-[14px] font-medium">{t.label}</div>
                <div className="text-[12px] text-fg-3">{t.detail}</div>
              </div>
              <Button size="sm" disabled={!t.available} onClick={() => run(() => api("/api/lab/data/teacher", { method: "POST", json: { teacher: t.name, n: tn } }), `Lehrer-Job (${t.name}) gestartet`)}>Start</Button>
            </div>
          ))}
          <p className="mt-1 text-[12px] text-fg-3">Lehrer-Antworten auf Lernaufgaben werden gegen die Musterlösung geprüft; nur korrekte werden übernommen.</p>
        </Card>
        <Card title="JSONL importieren">
          <p className="mb-2 text-[13px] text-fg-3">Format: {"{\"messages\":[…]}"} oder {"{\"prompt\":…,\"response\":…}"}. Importierte Beispiele müssen anschließend freigegeben werden.</p>
          <input ref={fileRef} type="file" accept=".jsonl,application/jsonl,text/plain" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <Button onClick={() => fileRef.current?.click()}><IconUpload size={16} /> Datei wählen</Button>
        </Card>
        <Button className="w-full" onClick={() => run(() => api("/api/lab/datasets/build", { method: "POST", json: {} }), "Datensatz-Build gestartet")}>Nur Datensatz-Snapshot bauen</Button>
      </div>
    </Sheet>
  );
}

function ReviewQueue({ onChange }: { onChange: () => void }) {
  const [items, setItems] = useState<Example[]>([]);
  const load = useCallback(() => api<Example[]>("/api/lab/data/examples?status=pending&limit=20").then(setItems).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  async function review(id: string, action: "approve" | "reject") {
    await api(`/api/lab/data/examples/${id}/review`, { method: "POST", json: { action } });
    setItems((xs) => xs.filter((x) => x.id !== id));
    onChange();
  }
  return (
    <div className="mt-3 border-t border-white/6 pt-3">
      <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-fg-3">Prüfwarteschlange</div>
      <div className="space-y-2.5">
        {items.map((e) => (
          <div key={e.id} className="rounded-xl bg-white/4 p-3 text-[13px]">
            <div className="mb-1 flex gap-1.5"><Badge>{SOURCE_LABEL[e.source] ?? e.source}</Badge>{e.verified && <Badge tone="ok">verifiziert</Badge>}</div>
            <div className="text-fg-3">Frage</div>
            <div className="line-clamp-3 whitespace-pre-wrap">{e.messages[e.messages.length - 1]?.content}</div>
            <div className="mt-1 text-fg-3">Antwort</div>
            <div className="line-clamp-5 whitespace-pre-wrap">{e.response}</div>
            <div className="mt-2 flex gap-2">
              <Button size="sm" variant="primary" onClick={() => review(e.id, "approve")}>Freigeben</Button>
              <Button size="sm" variant="danger" onClick={() => review(e.id, "reject")}>Ablehnen</Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function JobSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const [j, setJ] = useState<Job | null>(null);
  useEffect(() => { setJ(null); if (id) api<Job>(`/api/lab/jobs/${id}`).then(setJ).catch(() => undefined); }, [id]);
  const pts = (j?.metrics ?? []).filter((m) => m.kind === "train").map((m) => ({ step: m.step, loss: m.loss }));
  return (
    <Sheet open={!!id} onClose={onClose} title={j ? `${JOB_LABEL[j.type] ?? j.type} · ${j.id}` : "Job"}>
      {!j ? <div className="grid h-40 place-items-center"><Spinner /></div> : (
        <div className="space-y-3 text-[13px]">
          <div className="flex items-center gap-2"><Badge tone={statusTone(j.status)}>{statusLabel[j.status] ?? j.status}</Badge><span className="text-fg-3">{j.message}</span></div>
          {pts.length > 0 && <LossChart points={pts} height={150} />}
          {j.error && <Notice tone="bad"><pre className="whitespace-pre-wrap font-mono text-[12px]">{j.error}</pre></Notice>}
          <details><summary className="cursor-pointer text-fg-2">Parameter</summary><pre className="mt-1 overflow-x-auto rounded-lg bg-white/4 p-2 font-mono text-[11px]">{JSON.stringify(j.params, null, 2)}</pre></details>
          {j.result && <details><summary className="cursor-pointer text-fg-2">Ergebnis</summary><pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-white/4 p-2 font-mono text-[11px]">{JSON.stringify({ ...j.result, diffs: undefined }, null, 2)}</pre></details>}
          {j.log_tail && <details><summary className="cursor-pointer text-fg-2">Protokoll</summary><pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-white/4 p-2 font-mono text-[11px]">{j.log_tail}</pre></details>}
        </div>
      )}
    </Sheet>
  );
}
