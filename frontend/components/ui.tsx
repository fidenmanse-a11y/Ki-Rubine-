"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { IconClose } from "./icons";

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-white/80 ${className}`} />
  );
}

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "glass" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({ variant = "glass", size = "md", loading, className = "", children, disabled, ...p }: BtnProps) {
  const v = {
    primary: "accent-gradient text-white shadow-[0_8px_30px_-8px_rgba(139,92,246,0.7)]",
    glass: "glass text-fg",
    ghost: "bg-transparent text-fg-2 hover:bg-white/5",
    danger: "bg-bad/15 text-bad border border-bad/25",
  }[variant];
  const s = size === "sm" ? "h-9 px-3.5 text-[14px] rounded-xl" : "h-11 px-5 text-[15px] rounded-2xl";
  return (
    <button
      className={`tap inline-flex items-center justify-center gap-2 font-medium disabled:opacity-40 disabled:pointer-events-none ${v} ${s} ${className}`}
      disabled={disabled || loading}
      {...p}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "bad" | "accent" }) {
  const t = {
    neutral: "bg-white/8 text-fg-2",
    ok: "bg-ok/15 text-ok",
    warn: "bg-warn/15 text-warn",
    bad: "bg-bad/15 text-bad",
    accent: "bg-violet/20 text-violet-2",
  }[tone];
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-medium ${t}`}>{children}</span>;
}

export function Card({ children, className = "", title, action }: { children: ReactNode; className?: string; title?: ReactNode; action?: ReactNode }) {
  return (
    <section className={`card p-4 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold uppercase tracking-wide text-fg-3">{title}</h3>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: ReactNode; children: ReactNode }) {
  // On touch devices the browser fires a synthetic "click" right after the tap that opened the sheet; it would land on
  // the backdrop and close the sheet immediately ("ghost click"). Ignore backdrop clicks shortly after opening.
  const openedAt = useRef(0);
  useEffect(() => { if (open) openedAt.current = performance.now(); }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal>
      <div className="absolute inset-0 bg-black/60 animate-fade" onClick={() => { if (performance.now() - openedAt.current > 400) onClose(); }} />
      <div className="glass-strong relative max-h-[88dvh] w-full max-w-xl overflow-hidden rounded-t-[28px] sm:rounded-[28px] animate-sheet">
        <div className="mx-auto mt-2 h-1.5 w-10 rounded-full bg-white/20 sm:hidden" />
        <div className="flex items-center justify-between px-5 pb-2 pt-3">
          <h2 className="text-[17px] font-semibold">{title}</h2>
          <button aria-label="Schließen" onClick={onClose} className="tap -mr-2 grid place-items-center rounded-full text-fg-2">
            <IconClose size={20} />
          </button>
        </div>
        <div className="scroll-smooth-ios max-h-[calc(88dvh-60px)] overflow-y-auto px-5 pb-safe pb-6">{children}</div>
      </div>
    </div>
  );
}

export function Notice({ tone = "warn", children }: { tone?: "warn" | "bad" | "ok" | "info"; children: ReactNode }) {
  const t = {
    warn: "border-warn/25 bg-warn/10 text-warn",
    bad: "border-bad/25 bg-bad/10 text-[#ff8a80]",
    ok: "border-ok/25 bg-ok/10 text-ok",
    info: "border-azure/25 bg-azure/10 text-azure-2",
  }[tone];
  return <div className={`rounded-2xl border px-4 py-3 text-[14px] leading-snug ${t}`}>{children}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-fg-2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[12px] text-fg-3">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded-xl border border-white/10 bg-white/5 px-3.5 py-2.5 text-[16px] text-fg outline-none placeholder:text-fg-3 focus:border-violet/60 focus:bg-white/8 transition";

export function Progress({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/8">
      <div className="h-full accent-gradient transition-[width] duration-700" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card p-3.5">
      <div className="text-[12px] font-medium text-fg-3">{label}</div>
      <div className="mt-1 text-[22px] font-semibold tracking-tight tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-fg-3">{sub}</div>}
    </div>
  );
}

export function statusTone(s: string): "ok" | "warn" | "bad" | "neutral" | "accent" {
  if (["completed", "passed", "base", "ready"].includes(s)) return "ok";
  if (["running", "training", "evaluating", "queued", "pausing", "stopping", "loading"].includes(s)) return "accent";
  if (["paused", "stopped", "cancelled", "pending"].includes(s)) return "warn";
  if (["failed", "failed_eval", "error", "rejected"].includes(s)) return "bad";
  return "neutral";
}

export const statusLabel: Record<string, string> = {
  queued: "Wartet", running: "Läuft", pausing: "Pausiert …", paused: "Pausiert", stopping: "Stoppt …",
  stopped: "Gestoppt", completed: "Fertig", failed: "Fehlgeschlagen", cancelled: "Abgebrochen",
  base: "Basis", training: "Training", evaluating: "Evaluierung", passed: "Bestanden", failed_eval: "Test nicht bestanden",
  pending: "Prüfen", approved: "Freigegeben", rejected: "Abgelehnt",
};
