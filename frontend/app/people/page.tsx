"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AgentInspector } from "@/components/world2/Inspector";
import { Badge, inputCls, Notice, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { ORIGIN_COLOR } from "@/lib/world2";

type Person = {
  id: string; name: string; family: string; age: number; activity: string; origin: string; alive: boolean; child: boolean; ill: boolean;
  prisoner: boolean; official: boolean; homeless: boolean; followed: boolean; mood: string | null; top_goal: string | null;
  friends: number; convictions: number; wealth: number; generation: number; status: string[];
};
const FILTERS: [string, string][] = [
  ["", "Alle"], ["verfolgt", "Verfolgt"], ["amt", "Ämter"], ["gefangen", "In Haft"], ["krank", "Krank"], ["obdachlos", "Ohne Zuhause"],
  ["kind", "Kinder"], ["verstorben", "Verstorben"],
];
const SORTS: [string, string][] = [["name", "Name"], ["age", "Alter"], ["wealth", "Vermögen"], ["friends", "Freunde"]];

export default function PeoplePage() {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState("name");
  const [rows, setRows] = useState<Person[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    const p = new URLSearchParams({ sort });
    if (q.trim()) p.set("q", q.trim());
    if (filter) p.set("filter", filter);
    api<{ people: Person[] }>(`/api/world2/people?${p}`).then((r) => { setRows(r.people); setErr(null); }).catch((e) => setErr(e.message));
  }, [q, filter, sort]);
  useEffect(() => {
    const t = setTimeout(load, 200);
    const iv = setInterval(load, 8000);
    return () => { clearTimeout(t); clearInterval(iv); };
  }, [load]);

  async function toggleFollow(p: Person) {
    await api("/api/world2/follow", { method: "POST", json: { agent_id: p.id, follow: !p.followed } }).catch(() => undefined);
    load();
  }

  return (
    <main className="mx-auto max-w-3xl px-4 pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 96px)" }}>
      <header className="pb-3 pt-2">
        <h1 className="text-[30px] font-bold tracking-tight">Menschen</h1>
        <p className="text-[14px] text-fg-3">{rows ? `${rows.length} Bewohner` : "…"} · simulierte Agenten</p>
      </header>
      <input className={inputCls} placeholder="Name suchen" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Bewohner suchen" type="search" />
      <div className="scroll-smooth-ios -mx-4 mt-2 flex gap-1.5 overflow-x-auto px-4 pb-1">
        {FILTERS.map(([k, label]) => (
          <button key={k} onClick={() => setFilter(k)} className={`tap shrink-0 rounded-full px-4 text-[14px] font-medium ${filter === k ? "bg-white text-black" : "bg-white/8 text-fg-2"}`}>{label}</button>
        ))}
      </div>
      <div className="mt-1 flex items-center gap-2 text-[13px] text-fg-3">
        Sortieren:
        {SORTS.map(([k, label]) => (
          <button key={k} onClick={() => setSort(k)} className={`tap px-1 ${sort === k ? "font-semibold text-fg" : ""}`}>{label}</button>
        ))}
      </div>
      {err && <div className="mt-3"><Notice tone="bad">{err}</Notice></div>}
      {!rows ? <div className="grid h-40 place-items-center"><Spinner /></div> : (
        <ul className="mt-2 space-y-2">
          {rows.length === 0 && <li className="py-8 text-center text-[14px] text-fg-3">Niemand passt zu diesem Filter.</li>}
          {rows.map((p) => (
            <li key={p.id} className="card flex items-stretch gap-1 p-0">
              <button onClick={() => setSel(p.id)} className="tap flex min-w-0 flex-1 items-center gap-3 p-3 text-left">
                <span className="h-9 w-9 shrink-0 rounded-full border border-black/40" style={{ background: ORIGIN_COLOR[p.origin] ?? "#ddd", opacity: p.alive ? 1 : 0.35 }} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-[15px] font-semibold">{p.name} {p.family}</span>
                    <span className="shrink-0 text-[12px] text-fg-3">{p.age} J.</span>
                  </span>
                  <span className="block truncate text-[13px] text-fg-2">{p.alive ? p.activity : "verstorben"}</span>
                  {p.top_goal && <span className="block truncate text-[12px] text-fg-3">Ziel: {p.top_goal}</span>}
                  <span className="mt-1 flex flex-wrap gap-1">
                    {p.official && <Badge tone="accent">Amt</Badge>}
                    {p.prisoner && <Badge tone="bad">Haft</Badge>}
                    {p.ill && <Badge tone="warn">krank</Badge>}
                    {p.homeless && !p.child && p.alive && <Badge tone="warn">ohne Zuhause</Badge>}
                    {p.mood && p.alive && <Badge>{p.mood}</Badge>}
                    {p.friends > 0 && <Badge>{p.friends} Freund{p.friends > 1 ? "e" : ""}</Badge>}
                  </span>
                </span>
              </button>
              {p.alive && (
                <div className="flex flex-col justify-center gap-1 pr-2">
                  <button onClick={() => toggleFollow(p)} aria-label={p.followed ? "Nicht mehr verfolgen" : "Verfolgen"}
                    className={`tap grid h-11 w-11 place-items-center rounded-xl text-[20px] ${p.followed ? "text-[#fbbf24]" : "text-fg-3"}`}>{p.followed ? "★" : "☆"}</button>
                  <Link href={`/world/?track=${p.id}`} aria-label="Auf Karte zeigen" className="tap grid h-11 w-11 place-items-center rounded-xl text-[13px] text-fg-3">Karte</Link>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <AgentInspector id={sel} onClose={() => { setSel(null); load(); }} onSelect={setSel} />
    </main>
  );
}
