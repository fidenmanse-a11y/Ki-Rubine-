"use client";

import { useState } from "react";
import { AgentInspector } from "@/components/world2/Inspector";
import { EconomyPanel, HistoryPanel, SocietyPanel } from "@/components/world2/Panels";
import { CitiesPanel, JusticePanel, PopulationPanel, SocialPanel, useSociety3 } from "@/components/world2/Society3";
import { Spinner } from "@/components/ui";

const TABS = ["Politik", "Justiz", "Soziales", "Wirtschaft", "Bevölkerung", "Städte", "Chronik"] as const;

export default function SocietyPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Politik");
  const [sel, setSel] = useState<string | null>(null);
  const d = useSociety3();
  const needs3 = ["Justiz", "Soziales", "Bevölkerung", "Städte"].includes(tab);
  return (
    <main className="mx-auto max-w-3xl px-4 pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 96px)" }}>
      <header className="pb-2 pt-2">
        <h1 className="text-[30px] font-bold tracking-tight">Gesellschaft</h1>
        <p className="text-[14px] text-fg-3">Von den Bewohnern selbst geschaffen – nichts davon ist vorgegeben.</p>
      </header>
      <div className="scroll-smooth-ios sticky top-0 z-20 -mx-4 flex gap-1.5 overflow-x-auto bg-black/80 px-4 py-2 backdrop-blur-xl">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`tap shrink-0 rounded-full px-4 text-[14px] font-medium ${tab === t ? "bg-white text-black" : "bg-white/8 text-fg-2"}`}>{t}</button>
        ))}
      </div>
      <div className="mt-2">
        {tab === "Politik" && <SocietyPanel />}
        {tab === "Wirtschaft" && <EconomyPanel onSelect={setSel} />}
        {tab === "Chronik" && <HistoryPanel onSelect={setSel} />}
        {needs3 && !d && <div className="grid h-40 place-items-center"><Spinner /></div>}
        {d && tab === "Justiz" && <JusticePanel d={d} onSelect={setSel} />}
        {d && tab === "Soziales" && <SocialPanel d={d} />}
        {d && tab === "Bevölkerung" && <PopulationPanel d={d} />}
        {d && tab === "Städte" && <CitiesPanel d={d} />}
      </div>
      <AgentInspector id={sel} onClose={() => setSel(null)} onSelect={setSel} />
    </main>
  );
}
