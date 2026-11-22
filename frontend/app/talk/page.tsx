"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { IconSend, IconStop } from "@/components/icons";
import { Badge, inputCls, Notice, Spinner } from "@/components/ui";
import { api, postStream } from "@/lib/api";
import { ORIGIN_COLOR } from "@/lib/world2";

type Person = { id: string; name: string; family: string; age: number; activity: string; origin: string; alive: boolean; followed: boolean; mood: string | null };
type Msg = { role: "user" | "assistant"; content: string; remembered?: boolean };

function TalkInner() {
  const [id, setId] = useState<string | null>(null);
  const [people, setPeople] = useState<Person[] | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [engine, setEngine] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setId(new URLSearchParams(location.search).get("id")); }, []);
  useEffect(() => {
    api<{ people: Person[] }>("/api/world2/people").then((r) => setPeople(r.people.filter((p) => p.alive))).catch((e) => setErr(e.message));
    api<{ engine: { status: string } }>("/api/models").then((r) => setEngine(r.engine.status)).catch(() => setEngine(null));
  }, []);
  useEffect(() => {
    if (!id) return;
    try { setMsgs(JSON.parse(sessionStorage.getItem(`rubine.talk.${id}`) ?? "[]")); } catch { setMsgs([]); }
  }, [id]);
  useEffect(() => {
    if (id) try { sessionStorage.setItem(`rubine.talk.${id}`, JSON.stringify(msgs.slice(-30))); } catch { /* ignore */ }
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, id]);

  const person = people?.find((p) => p.id === id);

  async function send() {
    const text = input.trim();
    if (!text || !id || busy) return;
    setErr(null);
    setInput("");
    const history = msgs.map(({ role, content }) => ({ role, content }));
    setMsgs((m) => [...m, { role: "user", content: text }, { role: "assistant", content: "" }]);
    setBusy(true);
    abort.current = new AbortController();
    try {
      await postStream(`/api/world2/agents/${id}/chat`, { message: text, history, remember }, (ev, data) => {
        const d = data as { t?: string; message?: string; remembered?: boolean };
        if (ev === "token" && d.t) setMsgs((m) => { const c = [...m]; c[c.length - 1] = { ...c[c.length - 1], content: c[c.length - 1].content + d.t }; return c; });
        if (ev === "error") setErr(d.message ?? "Fehler");
        if (ev === "done" && d.remembered) setMsgs((m) => { const c = [...m]; c[c.length - 1] = { ...c[c.length - 1], remembered: true }; return c; });
      }, abort.current.signal);
    } catch (e) {
      setErr((e as Error).message);
      setMsgs((m) => (m[m.length - 1]?.content ? m : m.slice(0, -1)));
    } finally {
      setBusy(false);
    }
  }

  if (!id) {
    return (
      <main className="mx-auto max-w-3xl px-4 pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 96px)" }}>
        <header className="pb-3 pt-2">
          <h1 className="text-[30px] font-bold tracking-tight">Mit Bewohnern sprechen</h1>
          <p className="text-[14px] text-fg-3">Wähle eine Person. Antworten erzeugt das Sprachmodell aus ihrem echten Simulationszustand.</p>
        </header>
        <Link href="/" className="tap mb-3 inline-grid h-11 place-items-center rounded-2xl glass px-4 text-[14px] font-medium">← Rubine-Chat</Link>
        {err && <Notice tone="bad">{err}</Notice>}
        {!people ? <Spinner /> : (
          <ul className="space-y-2">
            {people.map((p) => (
              <li key={p.id}>
                <button onClick={() => { setId(p.id); history.replaceState(null, "", `/talk/?id=${p.id}`); }} className="tap card flex w-full items-center gap-3 p-3 text-left">
                  <span className="h-9 w-9 shrink-0 rounded-full" style={{ background: ORIGIN_COLOR[p.origin] ?? "#ddd" }} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-semibold">{p.followed ? "★ " : ""}{p.name} {p.family}</span>
                    <span className="block truncate text-[13px] text-fg-3">{p.age} J. · {p.activity}{p.mood ? ` · ${p.mood}` : ""}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-3xl flex-col px-4 pt-safe" style={{ paddingBottom: "calc(max(var(--sab),10px) + 168px)" }}>
      <header className="flex items-center gap-2 pb-2 pt-2">
        <button onClick={() => { setId(null); history.replaceState(null, "", "/talk/"); }} className="tap grid h-11 w-11 place-items-center rounded-full glass" aria-label="Zurück">←</button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[17px] font-semibold">{person ? `${person.name} ${person.family}` : id}</div>
          <div className="truncate text-[12px] text-fg-3">{person ? `${person.activity}${person.mood ? ` · ${person.mood}` : ""}` : ""}</div>
        </div>
        <Badge tone="accent">Simuliert</Badge>
      </header>
      <p className="text-[12px] leading-snug text-fg-3">
        Die Antworten erzeugt das Sprachmodell, das diesem Bewohner zugeordnet ist, aus Persönlichkeit, Zielen und Erinnerungen.
        Das Gespräch verändert die Welt nicht – außer du speicherst es ausdrücklich als Erinnerung (Entwickler-Eingriff).
      </p>
      {engine && engine !== "ready" && <div className="mt-2"><Notice tone="warn">Sprachmodell nicht bereit ({engine}). Ohne Modell gibt es keine Antworten.</Notice></div>}
      <div className="mt-3 flex-1 space-y-3">
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={`max-w-[85%] rounded-[20px] px-4 py-2.5 text-[15px] leading-snug ${m.role === "user" ? "bg-white/12" : "glass"}`}>
              {m.content || (busy && i === msgs.length - 1 ? <Spinner /> : "")}
              {m.remembered && <div className="mt-1 text-[11px] text-warn">als Erinnerung gespeichert (Entwickler-Eingriff)</div>}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      {err && <div className="mt-2"><Notice tone="bad">{err}</Notice></div>}
      <div className="fixed inset-x-0 z-30 px-4" style={{ bottom: "calc(max(var(--sab),10px) + 76px)" }}>
        <div className="glass-strong mx-auto max-w-3xl rounded-[24px] p-2">
          <label className="flex min-h-11 items-center gap-2 px-2 text-[13px] text-fg-2">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-5 w-5 accent-violet-500" />
            Als Erinnerung speichern (Entwickler-Eingriff, verändert die Welt)
          </label>
          <div className="flex items-end gap-2">
            <input className={inputCls} value={input} onChange={(e) => setInput(e.target.value)} placeholder="Frage stellen …"
              onKeyDown={(e) => { if (e.key === "Enter") send(); }} aria-label="Nachricht" maxLength={1000} />
            {busy ? (
              <button onClick={() => abort.current?.abort()} className="tap grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white/15" aria-label="Stoppen"><IconStop /></button>
            ) : (
              <button onClick={send} disabled={!input.trim()} className="tap accent-gradient grid h-11 w-11 shrink-0 place-items-center rounded-full disabled:opacity-40" aria-label="Senden"><IconSend /></button>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

export default function TalkPage() {
  return <Suspense fallback={<div className="grid min-h-dvh place-items-center"><Spinner /></div>}><TalkInner /></Suspense>;
}
