"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IconCheck, IconChevron, IconCopy, IconEdit, IconMenu, IconPlus, IconRefresh, IconSearch, IconSend, IconStop,
  IconThumbDown, IconThumbUp, IconTrash, RubineGem,
} from "@/components/icons";
import { Markdown } from "@/components/Markdown";
import { Badge, Button, inputCls, Notice, Sheet, Spinner } from "@/components/ui";
import { api, copyText, haptic, postStream, timeAgo } from "@/lib/api";
import type { Conversation, EngineInfo, Message, VersionInfo } from "@/lib/types";

type ModelsResp = { active: string; engine: EngineInfo; versions: VersionInfo[] };

const SUGGESTIONS = [
  "Erkläre mir, wie LoRA-Fine-Tuning funktioniert.",
  "Schreibe eine Python-Funktion, die Primzahlen prüft.",
  "Berechne 17 · 23 Schritt für Schritt.",
  "Gib mir drei Ideen für ein Wochenende in Berlin.",
];

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <Chat />
    </Suspense>
  );
}

function Chat() {
  const router = useRouter();
  const params = useSearchParams();
  const activeId = params.get("c");

  const [convs, setConvs] = useState<Conversation[]>([]);
  const [conv, setConv] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [models, setModels] = useState<ModelsResp | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [modelSheet, setModelSheet] = useState(false);
  const [convSheet, setConvSheet] = useState(false);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const loadConvs = useCallback(() => api<Conversation[]>("/api/chat/conversations").then(setConvs).catch(() => undefined), []);
  const loadModels = useCallback(() => api<ModelsResp>("/api/models").then(setModels).catch(() => undefined), []);

  useEffect(() => { loadConvs(); loadModels(); }, [loadConvs, loadModels]);

  // poll while the model is loading
  useEffect(() => {
    if (models && models.engine.status !== "loading") return;
    const t = setInterval(loadModels, 3000);
    return () => clearInterval(t);
  }, [models, loadModels]);

  useEffect(() => {
    setError(null);
    setEditing(null);
    if (!activeId) { setConv(null); setMessages([]); return; }
    if (streaming) return; // keep optimistic state while streaming into a fresh chat
    api<Conversation & { messages: Message[] }>(`/api/chat/conversations/${activeId}`)
      .then((c) => { setConv(c); setMessages(c.messages); stick.current = true; })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // auto-scroll while near the bottom
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stick.current) el.scrollTo({ top: el.scrollHeight, behavior: streaming ? "auto" : "smooth" });
  }, [messages, streaming]);

  const selectedVersion = conv?.model_version_id ?? models?.active ?? "base";
  const versionName = models?.versions.find((v) => v.id === selectedVersion)?.name ?? selectedVersion;
  const engine = models?.engine;

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }

  async function runStream(path: string, body: Record<string, unknown>, base: Message[]) {
    const placeholder: Message = {
      id: "pending-assistant", role: "assistant", content: "", status: "streaming", seq: 1e9,
      model_version_id: selectedVersion, feedback: 0, stats: null, created_at: new Date().toISOString(),
    };
    setMessages([...base, placeholder]);
    setStreaming(true);
    setError(null);
    stick.current = true;
    const ac = new AbortController();
    abortRef.current = ac;
    let aid = "pending-assistant";
    try {
      await postStream(path, body, (ev, data) => {
        const d = data as Record<string, unknown>;
        if (ev === "meta") {
          aid = String(d.assistant_message_id);
          const uid = d.user_message_id ? String(d.user_message_id) : null;
          setMessages((ms) => ms.map((m) => (m.id === "pending-assistant" ? { ...m, id: aid } : m.id === "pending-user" && uid ? { ...m, id: uid } : m)));
        } else if (ev === "token") {
          const t = String(d.t ?? "");
          setMessages((ms) => ms.map((m) => (m.id === aid ? { ...m, content: m.content + t } : m)));
        } else if (ev === "done") {
          setMessages((ms) => ms.map((m) => (m.id === aid ? { ...m, status: (d.status as Message["status"]) ?? "complete", stats: (d.stats as Message["stats"]) ?? null } : m)));
        } else if (ev === "error") {
          setMessages((ms) => ms.map((m) => (m.id === aid ? { ...m, status: "error", stats: { error: String(d.message) } } : m)));
          setError(String(d.message));
        }
      }, ac.signal);
      if (ac.signal.aborted) {
        setMessages((ms) => ms.map((m) => (m.id === aid ? { ...m, status: "stopped" } : m)));
      }
    } catch (e) {
      setMessages(base);
      setError((e as Error).message);
    } finally {
      setStreaming(false);
      abortRef.current = null;
      loadConvs();
      const cid = path.match(/conversations\/([^/]+)/)?.[1] ?? null;
      if (cid) api<Conversation>(`/api/chat/conversations/${cid}`).then((c) => setConv(c)).catch(() => undefined);
    }
  }

  async function send(textArg?: string) {
    const text = (textArg ?? input).trim();
    if (!text || streaming) return;
    haptic();
    let cid = activeId;
    let base = messages;
    if (!cid) {
      try {
        const c = await api<Conversation>("/api/chat/conversations", { method: "POST", json: {} });
        cid = c.id;
        setConv(c);
        base = [];
        setStreaming(true); // prevents reload effect from wiping the optimistic state
        router.replace(`/?c=${c.id}`);
      } catch (e) {
        setError((e as Error).message);
        return;
      }
    }
    const userMsg: Message = {
      id: "pending-user", role: "user", content: text, status: "complete", seq: 1e9 - 1,
      model_version_id: null, feedback: 0, stats: null, created_at: new Date().toISOString(),
    };
    setInput("");
    if (taRef.current) taRef.current.style.height = "";
    await runStream(`/api/chat/conversations/${cid}/messages`, { content: text, model_version_id: selectedVersion }, [...base, userMsg]);
  }

  function stop() {
    abortRef.current?.abort();
  }

  async function regenerate() {
    if (!activeId || streaming) return;
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    const base = messages.slice(0, messages.indexOf(lastUser) + 1);
    await runStream(`/api/chat/conversations/${activeId}/regenerate`, { model_version_id: selectedVersion }, base);
  }

  async function submitEdit() {
    if (!editing || streaming) return;
    const idx = messages.findIndex((m) => m.id === editing.id);
    if (idx < 0) return;
    const edited = { ...messages[idx], content: editing.text };
    const base = [...messages.slice(0, idx), edited];
    setEditing(null);
    await runStream(`/api/chat/messages/${edited.id}/edit`, { content: edited.content, model_version_id: selectedVersion }, base);
  }

  async function feedback(m: Message, value: number) {
    const v = m.feedback === value ? 0 : value;
    setMessages((ms) => ms.map((x) => (x.id === m.id ? { ...x, feedback: v } : x)));
    try {
      const r = await api<{ proposed_for_training: boolean }>(`/api/chat/messages/${m.id}/feedback`, { method: "POST", json: { value: v } });
      if (r.proposed_for_training) setError(null);
    } catch (e) { setError((e as Error).message); }
  }

  async function setVersion(vid: string) {
    setModelSheet(false);
    if (conv) {
      const c = await api<Conversation>(`/api/chat/conversations/${conv.id}`, { method: "PATCH", json: { model_version_id: vid } });
      setConv(c);
    } else {
      const c = await api<Conversation>("/api/chat/conversations", { method: "POST", json: { model_version_id: vid } });
      setConv(c);
      router.replace(`/?c=${c.id}`);
      loadConvs();
    }
  }

  const lastAssistantId = useMemo(() => [...messages].reverse().find((m) => m.role === "assistant")?.id, [messages]);

  return (
    <div className="flex h-dvh flex-col">
      {/* Header */}
      <header className="glass-strong fixed inset-x-0 top-0 z-30 rounded-b-[22px] border-t-0 pt-safe">
        <div className="mx-auto flex max-w-3xl items-center gap-1 px-2 pb-2">
          <button aria-label="Unterhaltungen" onClick={() => setDrawer(true)} className="tap grid place-items-center rounded-full text-fg">
            <IconMenu />
          </button>
          <button onClick={() => conv && setConvSheet(true)} className="tap min-w-0 flex-1 rounded-xl px-1 text-left">
            <div className="truncate text-[16px] font-semibold">{conv?.title ?? "Rubine"}</div>
          </button>
          <button onClick={() => setModelSheet(true)} className="tap flex max-w-[45%] items-center gap-1 rounded-full bg-white/8 px-3 text-[13px] font-medium text-fg-2">
            <span className={`h-2 w-2 shrink-0 rounded-full ${engine?.status === "ready" ? "bg-ok" : engine?.status === "loading" ? "bg-warn animate-pulse-soft" : "bg-bad"}`} />
            <span className="truncate">{versionName}</span>
          </button>
          <button aria-label="Neuer Chat" onClick={() => { router.push("/"); setInput(""); taRef.current?.focus(); }} className="tap grid place-items-center rounded-full text-fg">
            <IconPlus />
          </button>
        </div>
      </header>

      {/* Messages */}
      <div ref={scrollRef} onScroll={onScroll} className="scroll-smooth-ios flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4" style={{ paddingTop: "calc(max(var(--sat),12px) + 64px)", paddingBottom: "calc(max(var(--sab),10px) + 170px)" }}>
          {engine && engine.status !== "ready" && (
            <div className="mb-4">
              <Notice tone={engine.status === "loading" ? "info" : "bad"}>
                {engine.status === "loading" ? "Das Sprachmodell wird geladen …" : `Sprachmodell nicht verfügbar: ${engine.error ?? engine.status}`}
              </Notice>
            </div>
          )}
          {messages.length === 0 && !activeId && (
            <div className="flex flex-col items-center pt-[12vh] text-center animate-rise">
              <RubineGem size={64} className="drop-shadow-[0_12px_40px_rgba(139,92,246,0.5)]" />
              <h1 className="mt-5 text-[26px] font-semibold tracking-tight">Wie kann ich helfen?</h1>
              <p className="mt-1.5 max-w-xs text-[14px] text-fg-3">Antworten erzeugt dein lokales Modell <span className="text-fg-2">{versionName}</span>.</p>
              <div className="mt-8 grid w-full max-w-md gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => send(s)} disabled={engine?.status !== "ready"} className="tap card px-4 py-3 text-left text-[15px] text-fg-2 disabled:opacity-40">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="space-y-5">
            {messages.map((m) => (
              <MessageRow
                key={m.id}
                m={m}
                isLast={m.id === lastAssistantId}
                streaming={streaming}
                editing={editing?.id === m.id ? editing.text : null}
                onEditStart={() => setEditing({ id: m.id, text: m.content })}
                onEditChange={(t) => setEditing({ id: m.id, text: t })}
                onEditCancel={() => setEditing(null)}
                onEditSubmit={submitEdit}
                onRegenerate={regenerate}
                onFeedback={(v) => feedback(m, v)}
              />
            ))}
          </div>
          {error && <div className="mt-4"><Notice tone="bad">{error}</Notice></div>}
        </div>
      </div>

      {/* Composer */}
      <div className="fixed inset-x-0 z-30 px-3" style={{ bottom: "calc(max(var(--sab),10px) + 72px)" }}>
        <div className="glass-strong mx-auto flex max-w-3xl items-end gap-2 rounded-[26px] p-1.5 pl-4">
          <textarea
            ref={taRef}
            rows={1}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !("ontouchstart" in window)) { e.preventDefault(); send(); }
            }}
            placeholder="Nachricht an Rubine"
            className="max-h-40 flex-1 resize-none bg-transparent py-2.5 text-[16px] leading-6 outline-none placeholder:text-fg-3"
            enterKeyHint="send"
          />
          {streaming ? (
            <button aria-label="Stopp" onClick={stop} className="tap grid h-11 w-11 place-items-center rounded-full bg-white text-black">
              <IconStop size={18} />
            </button>
          ) : (
            <button
              aria-label="Senden"
              onClick={() => send()}
              disabled={!input.trim() || engine?.status !== "ready"}
              className="tap grid h-11 w-11 place-items-center rounded-full accent-gradient text-white disabled:opacity-30"
            >
              <IconSend size={20} />
            </button>
          )}
        </div>
      </div>

      <ConversationDrawer
        open={drawer}
        onClose={() => setDrawer(false)}
        convs={convs}
        activeId={activeId}
        onSelect={(id) => { setDrawer(false); router.push(`/?c=${id}`); }}
        onChanged={loadConvs}
        onDeleted={(id) => { loadConvs(); if (id === activeId) router.replace("/"); }}
      />

      <Sheet open={modelSheet} onClose={() => setModelSheet(false)} title="Modellversion">
        <p className="mb-3 text-[13px] text-fg-3">
          Basis: {engine?.base_model} ({engine?.license}) · Gerät: {engine?.device ?? "—"}. Nur getestete Versionen sind wählbar.
        </p>
        <div className="space-y-2">
          {models?.versions.filter((v) => v.chat_allowed).map((v) => (
            <button key={v.id} onClick={() => setVersion(v.id)} className={`tap card flex w-full items-center justify-between px-4 py-3 text-left ${v.id === selectedVersion ? "ring-1 ring-violet/60" : ""}`}>
              <div>
                <div className="font-medium">{v.name}</div>
                <div className="text-[12px] text-fg-3">{v.id}{v.accuracy != null ? ` · Eval ${(v.accuracy * 100).toFixed(1)} %` : ""}</div>
              </div>
              <div className="flex items-center gap-2">
                {v.active && <Badge tone="accent">aktiv</Badge>}
                {v.id === selectedVersion && <IconCheck size={18} className="text-violet-2" />}
              </div>
            </button>
          ))}
        </div>
      </Sheet>

      <ConversationSheet
        open={convSheet}
        conv={conv}
        onClose={() => setConvSheet(false)}
        onUpdated={(c) => { setConv(c); loadConvs(); }}
        onDeleted={() => { setConvSheet(false); loadConvs(); router.replace("/"); }}
      />
    </div>
  );
}

function MessageRow(props: {
  m: Message; isLast: boolean; streaming: boolean; editing: string | null;
  onEditStart: () => void; onEditChange: (t: string) => void; onEditCancel: () => void; onEditSubmit: () => void;
  onRegenerate: () => void; onFeedback: (v: number) => void;
}) {
  const { m, isLast, streaming, editing } = props;
  const [copied, setCopied] = useState(false);
  if (m.role === "user") {
    if (editing !== null) {
      return (
        <div className="animate-fade">
          <textarea value={editing} onChange={(e) => props.onEditChange(e.target.value)} className={`${inputCls} min-h-24`} autoFocus />
          <div className="mt-2 flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={props.onEditCancel}>Abbrechen</Button>
            <Button size="sm" variant="primary" onClick={props.onEditSubmit} disabled={!editing.trim()}>Senden</Button>
          </div>
        </div>
      );
    }
    return (
      <div className="group flex flex-col items-end animate-rise">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-[22px] rounded-br-md accent-gradient px-4 py-2.5 text-[16px] leading-relaxed text-white shadow-[0_6px_24px_-10px_rgba(99,102,241,0.8)]">
          {m.content}
        </div>
        {!streaming && !m.id.startsWith("pending") && (
          <button onClick={props.onEditStart} className="tap mt-0.5 flex items-center gap-1 rounded-lg px-2 text-[12px] text-fg-3" aria-label="Bearbeiten">
            <IconEdit size={14} /> Bearbeiten
          </button>
        )}
      </div>
    );
  }
  const isStreaming = m.status === "streaming";
  return (
    <div className="animate-rise">
      <div className="mb-1.5 flex items-center gap-2">
        <RubineGem size={18} />
        <span className="text-[13px] font-medium text-fg-2">Rubine</span>
        {m.model_version_id && m.model_version_id !== "base" && <Badge>{m.model_version_id}</Badge>}
      </div>
      {m.content ? (
        <Markdown text={m.content} />
      ) : isStreaming ? (
        <div className="flex h-6 items-center gap-1.5"><span className="dot" /><span className="dot" /><span className="dot" /></div>
      ) : null}
      {m.status === "error" && <div className="mt-2"><Notice tone="bad">{m.stats?.error ?? "Fehler bei der Generierung"}</Notice></div>}
      {m.status === "stopped" && <div className="mt-1 text-[12px] text-fg-3">Generierung gestoppt</div>}
      {!isStreaming && m.status !== "error" && (
        <div className="mt-1.5 flex items-center gap-0.5 text-fg-3">
          <button className="tap grid place-items-center rounded-full" aria-label="Kopieren"
            onClick={async () => { if (await copyText(m.content)) { haptic(); setCopied(true); setTimeout(() => setCopied(false), 1500); } }}>
            {copied ? <IconCheck size={17} /> : <IconCopy size={17} />}
          </button>
          <button className={`tap grid place-items-center rounded-full ${m.feedback === 1 ? "text-ok" : ""}`} aria-label="Gute Antwort" onClick={() => props.onFeedback(1)}>
            <IconThumbUp size={17} />
          </button>
          <button className={`tap grid place-items-center rounded-full ${m.feedback === -1 ? "text-bad" : ""}`} aria-label="Schlechte Antwort" onClick={() => props.onFeedback(-1)}>
            <IconThumbDown size={17} />
          </button>
          {isLast && !streaming && (
            <button className="tap grid place-items-center rounded-full" aria-label="Neu generieren" onClick={props.onRegenerate}>
              <IconRefresh size={17} />
            </button>
          )}
          {m.stats?.tok_per_s ? <span className="ml-2 text-[11px] tabular-nums">{m.stats.tokens} Tokens · {m.stats.tok_per_s} tok/s</span> : null}
        </div>
      )}
    </div>
  );
}

function ConversationDrawer(props: {
  open: boolean; onClose: () => void; convs: Conversation[]; activeId: string | null;
  onSelect: (id: string) => void; onChanged: () => void; onDeleted: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Conversation[] | null>(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (q.trim().length < 2) { setResults(null); return; }
    setSearching(true);
    const t = setTimeout(() => {
      api<Conversation[]>(`/api/chat/search?q=${encodeURIComponent(q.trim())}`)
        .then(setResults).catch(() => setResults([])).finally(() => setSearching(false));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const list = results ?? props.convs;
  return (
    <div className={`fixed inset-0 z-50 ${props.open ? "" : "pointer-events-none"}`} aria-hidden={!props.open}>
      <div className={`absolute inset-0 bg-black/60 transition-opacity duration-300 ${props.open ? "opacity-100" : "opacity-0"}`} onClick={props.onClose} />
      <aside
        className={`glass-strong absolute inset-y-0 left-0 flex w-[86%] max-w-sm flex-col rounded-r-[28px] pt-safe transition-transform duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${props.open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="flex items-center gap-2 px-4 pb-3">
          <RubineGem size={26} />
          <h2 className="text-[20px] font-semibold">Chats</h2>
        </div>
        <div className="px-4 pb-3">
          <div className="flex items-center gap-2 rounded-xl bg-white/6 px-3">
            <IconSearch size={18} className="text-fg-3" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chats durchsuchen" className="h-10 flex-1 bg-transparent text-[16px] outline-none placeholder:text-fg-3" />
            {searching && <Spinner />}
          </div>
        </div>
        <div className="scroll-smooth-ios flex-1 overflow-y-auto px-2 pb-safe">
          {list.length === 0 && <p className="px-4 py-8 text-center text-[14px] text-fg-3">{results ? "Keine Treffer" : "Noch keine Unterhaltungen"}</p>}
          {list.map((c) => (
            <button key={c.id} onClick={() => props.onSelect(c.id)}
              className={`tap flex w-full items-center gap-2 rounded-2xl px-3 py-2.5 text-left ${c.id === props.activeId ? "bg-white/10" : ""}`}>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[15px] font-medium">{c.title}</div>
                <div className="truncate text-[12px] text-fg-3">{c.preview || timeAgo(c.updated_at)}</div>
              </div>
              <IconChevron size={16} className="text-fg-3" />
            </button>
          ))}
        </div>
      </aside>
    </div>
  );
}

function ConversationSheet(props: { open: boolean; conv: Conversation | null; onClose: () => void; onUpdated: (c: Conversation) => void; onDeleted: () => void }) {
  const { conv } = props;
  const [title, setTitle] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setTitle(conv?.title ?? ""); setConfirm(false); setErr(null); }, [conv, props.open]);
  if (!conv) return null;
  async function patch(body: Record<string, unknown>) {
    try {
      const c = await api<Conversation>(`/api/chat/conversations/${conv!.id}`, { method: "PATCH", json: body });
      props.onUpdated(c);
    } catch (e) { setErr((e as Error).message); }
  }
  return (
    <Sheet open={props.open} onClose={props.onClose} title="Unterhaltung">
      <div className="space-y-4">
        <div>
          <label className="mb-1.5 block text-[13px] text-fg-2">Name</label>
          <div className="flex gap-2">
            <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
            <Button onClick={() => patch({ title })} disabled={!title.trim() || title === conv.title}>Speichern</Button>
          </div>
        </div>
        <div className="card flex items-start justify-between gap-3 p-4">
          <div>
            <div className="font-medium">Für Training freigeben</div>
            <p className="mt-0.5 text-[13px] leading-snug text-fg-3">
              Nur mit deiner Zustimmung dürfen positiv bewertete Antworten (👍) dieses Chats als Trainingsvorschläge
              gespeichert werden. Sie müssen im AI Lab zusätzlich manuell freigegeben werden. Widerruf löscht die Vorschläge.
            </p>
          </div>
          <button
            role="switch"
            aria-checked={conv.training_consent}
            onClick={() => patch({ training_consent: !conv.training_consent })}
            className={`tap relative h-8 w-[52px] shrink-0 rounded-full transition-colors ${conv.training_consent ? "bg-ok" : "bg-white/15"}`}
          >
            <span className={`absolute top-1 h-6 w-6 rounded-full bg-white shadow transition-all ${conv.training_consent ? "left-[24px]" : "left-1"}`} />
          </button>
        </div>
        {err && <Notice tone="bad">{err}</Notice>}
        {!confirm ? (
          <Button variant="danger" className="w-full" onClick={() => setConfirm(true)}><IconTrash size={18} /> Chat löschen</Button>
        ) : (
          <div className="flex gap-2">
            <Button className="flex-1" onClick={() => setConfirm(false)}>Abbrechen</Button>
            <Button variant="danger" className="flex-1" onClick={async () => {
              await api(`/api/chat/conversations/${conv.id}`, { method: "DELETE" });
              props.onDeleted();
            }}>Endgültig löschen</Button>
          </div>
        )}
      </div>
    </Sheet>
  );
}
