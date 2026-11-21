"use client";

import { useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? "").join("; ");
  }
  return fallback;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(path, {
      credentials: "same-origin",
      ...rest,
      headers: { ...(json !== undefined ? { "content-type": "application/json" } : {}), ...headers },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "Rubine-Server nicht erreichbar. Läuft der PC und bist du im selben WLAN?");
  }
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth")) {
    window.location.href = "/login/";
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailOf(body, `Fehler ${res.status}`));
  return body as T;
}

export type SSEHandler = (event: string, data: unknown) => void;

/** POST a request and consume a text/event-stream response (fetch-based, supports abort). */
export async function postStream(path: string, json: unknown, onEvent: SSEHandler, signal?: AbortSignal) {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify(json),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError(0, "Rubine-Server nicht erreichbar.");
  }
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    if (res.status === 401) window.location.href = "/login/";
    throw new ApiError(res.status, detailOf(body, `Fehler ${res.status}`));
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let ev = "message";
        const data: string[] = [];
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
        }
        if (data.length) {
          try { onEvent(ev, JSON.parse(data.join("\n"))); } catch { /* ignore malformed */ }
        }
      }
    }
  } catch (e) {
    if ((e as Error).name !== "AbortError") throw e;
  }
}

/** Subscribe to a GET SSE endpoint with automatic reconnect. */
export function useEventStream<T>(path: string | null, event: string, onData: (d: T) => void) {
  const cb = useRef(onData);
  cb.current = onData;
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!path) return;
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    const open = () => {
      es = new EventSource(path, { withCredentials: true });
      es.addEventListener(event, (e) => {
        setConnected(true);
        try { cb.current(JSON.parse((e as MessageEvent).data)); } catch { /* ignore */ }
      });
      es.onopen = () => setConnected(true);
      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!closed) retry = setTimeout(open, 3000);
      };
    };
    open();
    return () => { closed = true; clearTimeout(retry); es?.close(); };
  }, [path, event]);
  return connected;
}

export async function copyText(text: string): Promise<boolean> {
  // navigator.clipboard needs a secure context (HTTPS/localhost); fall back for LAN http.
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through */ }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  document.body.removeChild(ta);
  return ok;
}

export function haptic() {
  try { navigator.vibrate?.(8); } catch { /* iOS ignores */ }
}

export function timeAgo(iso: string): string {
  const d = new Date(iso).getTime();
  const s = Math.max(0, (Date.now() - d) / 1000);
  if (s < 60) return "gerade eben";
  if (s < 3600) return `vor ${Math.floor(s / 60)} Min.`;
  if (s < 86400) return `vor ${Math.floor(s / 3600)} Std.`;
  return new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "short" });
}

export const pct = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : `${(x * 100).toFixed(digits)} %`;
