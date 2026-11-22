"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, inputCls } from "@/components/ui";
import { api, pct } from "@/lib/api";
import type { ModelVersion } from "@/lib/types";

type BenchRow = {
  label: string; accuracy: number; chance: number; n: number; unparsed: number; sec_per_item: number; params?: number;
  per_category: Record<string, { n: number; accuracy: number; chance: number; rules_engine?: number }>; created?: number; items_sha256: string;
};
const CAT_LABEL: Record<string, string> = {
  bedarf: "Bedürfnisse", planung: "Planung", vertrauen: "Vertrauen", folgen: "Folgen abschätzen", ursache: "Ursachen",
  anpassung: "Anpassung*", normen: "Normen*",
};

export function AgentBenchCard({ versions, onMsg }: { versions: ModelVersion[]; onMsg: (t: string, tone: "ok" | "bad") => void }) {
  const [rows, setRows] = useState<BenchRow[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [sel, setSel] = useState("base");
  const load = useCallback(() => api<{ results: BenchRow[]; models: string[] }>("/api/lab/agent-bench")
    .then((r) => { setRows(r.results); setModels(r.models); }).catch(() => undefined), []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  async function start() {
    const body = sel.startsWith("hf:") ? { hf_model: sel.slice(3) } : { version_id: sel };
    try { await api("/api/lab/agent-bench", { method: "POST", json: body }); onMsg("Bewohner-Test gestartet (läuft als Job).", "ok"); }
    catch (e) { onMsg((e as Error).message, "bad"); }
  }
  const latest = new Map<string, BenchRow>();
  rows.forEach((r) => { if (!latest.has(r.label)) latest.set(r.label, r); });
  const list = [...latest.values()];
  const cats = Object.keys(list[0]?.per_category ?? {});

  return (
    <Card className="mt-4" title="Bewohner-Test (Entscheidungen der Agenten)">
      <p className="mb-2 text-[13px] text-fg-3">
        70 klare Entscheidungssituationen aus einer eigenen Prüfwelt im selben Format wie die Simulation („Wahl: Nummer“).
        Misst Entscheidungen, nicht Verständnis oder Bewusstsein. * = nicht im Trainingsdatensatz (Transfer-Test).
      </p>
      <div className="flex gap-2">
        <select className={inputCls} value={sel} onChange={(e) => setSel(e.target.value)} aria-label="Modell für den Bewohner-Test">
          {versions.filter((v) => v.id === "base" || v.status === "passed" || v.status === "failed_eval").map((v) => (
            <option key={v.id} value={v.id}>{v.id}{v.status !== "base" ? ` (${v.status})` : ""}</option>
          ))}
          {models.map((m) => <option key={m} value={`hf:${m}`}>{m} (größeres Basismodell)</option>)}
        </select>
        <Button onClick={start}>Testen</Button>
      </div>
      {list.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-fg-3">
                <th className="py-1 pr-2 font-medium">Kategorie</th>
                {list.map((r) => <th key={r.label} className="py-1 pr-2 font-medium">{r.label.replace("Qwen/", "")}</th>)}
                <th className="py-1 font-medium">Zufall</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-white/5 font-semibold">
                <td className="py-1 pr-2">Gesamt</td>
                {list.map((r) => <td key={r.label} className="py-1 pr-2 tabular-nums">{pct(r.accuracy)}</td>)}
                <td className="py-1 tabular-nums text-fg-3">{pct(list[0].chance)}</td>
              </tr>
              {cats.map((c) => (
                <tr key={c} className="border-t border-white/5">
                  <td className="py-1 pr-2 text-fg-2">{CAT_LABEL[c] ?? c}</td>
                  {list.map((r) => <td key={r.label} className="py-1 pr-2 tabular-nums">{r.per_category[c] ? pct(r.per_category[c].accuracy) : "—"}</td>)}
                  <td className="py-1 tabular-nums text-fg-3">{pct(list[0].per_category[c]?.chance)}{c === "bedarf" && list[0].per_category[c]?.rules_engine != null ? ` · Regeln ${pct(list[0].per_category[c].rules_engine)}` : ""}</td>
                </tr>
              ))}
              <tr className="border-t border-white/5 text-fg-3">
                <td className="py-1 pr-2">Sek./Entscheidung (CPU)</td>
                {list.map((r) => <td key={r.label} className="py-1 pr-2 tabular-nums">{r.sec_per_item}</td>)}
                <td />
              </tr>
            </tbody>
          </table>
          <div className="mt-2 flex flex-wrap gap-1">{list.map((r) => r.unparsed > 0 && <Badge key={r.label} tone="warn">{r.label}: {r.unparsed} ohne gültige Wahl</Badge>)}</div>
        </div>
      )}
    </Card>
  );
}
