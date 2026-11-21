"use client";

import { useMemo, useRef, useState } from "react";

// Validated (dataviz validator, dark surface #0a0a0f): lightness band, chroma, CVD ΔE 19.9, contrast – all pass.
export const SERIES_A = "#8b5cf6";
export const SERIES_B = "#2f9e8f";

type Pt = { step: number; loss: number | null };

/** Single-series training-loss line with crosshair tooltip. */
export function LossChart({ points, height = 170 }: { points: Pt[]; height?: number }) {
  const data = useMemo(() => points.filter((p): p is { step: number; loss: number } => p.loss != null && Number.isFinite(p.loss)), [points]);
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const W = 600, H = height, padL = 40, padR = 12, padT = 10, padB = 24;
  if (data.length === 0) {
    return <div className="grid place-items-center text-[13px] text-fg-3" style={{ height }}>Noch keine Messpunkte</div>;
  }
  const xs = data.map((d) => d.step), ys = data.map((d) => d.loss);
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1);
  const yMax = Math.max(...ys) * 1.08, yMin = 0;
  const sx = (x: number) => padL + ((x - x0) / (x1 - x0)) * (W - padL - padR);
  const sy = (y: number) => padT + (1 - (y - yMin) / (yMax - yMin || 1)) * (H - padT - padB);
  const path = data.map((d, i) => `${i ? "L" : "M"}${sx(d.step).toFixed(1)},${sy(d.loss).toFixed(1)}`).join(" ");
  const ticks = [0, 0.5, 1].map((f) => yMin + f * (yMax - yMin));
  const h = hover != null ? data[hover] : null;

  function onMove(e: React.PointerEvent) {
    const r = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = 0, bd = Infinity;
    data.forEach((d, i) => { const dd = Math.abs(sx(d.step) - px); if (dd < bd) { bd = dd; best = i; } });
    setHover(best);
  }

  return (
    <div className="relative">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="w-full touch-none" style={{ height }} preserveAspectRatio="none"
        onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} role="img"
        aria-label={`Trainingsverlust über ${data.length} Schritte, zuletzt ${data[data.length - 1].loss.toFixed(4)}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={sy(t)} y2={sy(t)} stroke="rgba(255,255,255,0.07)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            <text x={padL - 6} y={sy(t)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill="rgba(235,235,245,0.38)">{t.toFixed(2)}</text>
          </g>
        ))}
        <text x={padL} y={H - 6} fontSize={11} fill="rgba(235,235,245,0.38)">Schritt {x0}</text>
        <text x={W - padR} y={H - 6} fontSize={11} textAnchor="end" fill="rgba(235,235,245,0.38)">{x1}</text>
        <path d={path} fill="none" stroke={SERIES_A} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {h && (
          <g>
            <line x1={sx(h.step)} x2={sx(h.step)} y1={padT} y2={H - padB} stroke="rgba(255,255,255,0.25)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            <circle cx={sx(h.step)} cy={sy(h.loss)} r={4.5} fill={SERIES_A} stroke="#0a0a0f" strokeWidth={2} vectorEffect="non-scaling-stroke" />
          </g>
        )}
      </svg>
      {h && (
        <div className="pointer-events-none absolute top-1 rounded-lg border border-white/10 bg-[#16161f]/95 px-2.5 py-1.5 text-[12px] shadow-lg"
          style={{ left: `clamp(0px, calc(${(sx(h.step) / W) * 100}% - 60px), calc(100% - 130px))` }}>
          <div className="text-fg-3">Schritt {h.step}</div>
          <div className="font-medium tabular-nums text-fg">Loss {h.loss.toFixed(4)}</div>
        </div>
      )}
    </div>
  );
}

type Fam = Record<string, { accuracy: number; correct: number; n: number }>;

/** Per-family accuracy as horizontal bars; one or two versions (legend + value labels). */
export function FamilyBars({ a, b, labelA, labelB }: { a: Fam; b?: Fam; labelA: string; labelB?: string }) {
  const fams = Object.keys({ ...a, ...(b ?? {}) }).sort();
  const [hover, setHover] = useState<string | null>(null);
  return (
    <div>
      {b && (
        <div className="mb-2 flex gap-4 text-[12px] text-fg-2">
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES_A }} />{labelA}</span>
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES_B }} />{labelB}</span>
        </div>
      )}
      <div className="space-y-2.5">
        {fams.map((f) => (
          <div key={f} onPointerEnter={() => setHover(f)} onPointerLeave={() => setHover(null)} className="rounded-lg">
            <div className="mb-1 flex justify-between text-[12px]">
              <span className="text-fg-2">{f}</span>
              {hover === f && <span className="text-fg-3">{a[f] ? `${a[f].correct}/${a[f].n}` : "—"}{b ? ` · ${b[f] ? `${b[f].correct}/${b[f].n}` : "—"}` : ""}</span>}
            </div>
            {[{ v: a[f], c: SERIES_A }, ...(b ? [{ v: b[f], c: SERIES_B }] : [])].map(({ v, c }, i) => (
              <div key={i} className="mb-[2px] flex items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/6">
                  <div className="h-full rounded-r-[4px] transition-[width] duration-700" style={{ width: `${(v?.accuracy ?? 0) * 100}%`, background: c }} />
                </div>
                <span className="w-10 text-right text-[11px] tabular-nums text-fg-2">{v ? `${Math.round(v.accuracy * 100)} %` : "—"}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

type Series = { name: string; color: string; points: { x: number; y: number | null }[] };

/** Generic line chart (1–2 series, one y-axis) with crosshair tooltip and legend for ≥2 series. */
export function LineChart({ series, height = 150, xLabel, yFormat = (v) => String(Math.round(v * 100) / 100), yMin }: {
  series: Series[]; height?: number; xLabel?: (x: number) => string; yFormat?: (v: number) => string; yMin?: number;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [hx, setHx] = useState<number | null>(null);
  const W = 600, H = height, padL = 44, padR = 10, padT = 10, padB = 22;
  const all = series.flatMap((s) => s.points.filter((p): p is { x: number; y: number } => p.y != null && Number.isFinite(p.y)));
  if (all.length < 2) return <div className="grid place-items-center text-[13px] text-fg-3" style={{ height }}>Noch zu wenige Messpunkte</div>;
  const x0 = Math.min(...all.map((p) => p.x)), x1 = Math.max(...all.map((p) => p.x), x0 + 1);
  const lo = yMin ?? Math.min(0, ...all.map((p) => p.y)), hi = Math.max(...all.map((p) => p.y)) * 1.08 || 1;
  const sx = (x: number) => padL + ((x - x0) / (x1 - x0)) * (W - padL - padR);
  const sy = (y: number) => padT + (1 - (y - lo) / (hi - lo || 1)) * (H - padT - padB);
  const xs = [...new Set(all.map((p) => p.x))].sort((a, b) => a - b);
  function onMove(e: React.PointerEvent) {
    const r = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = xs[0];
    for (const x of xs) if (Math.abs(sx(x) - px) < Math.abs(sx(best) - px)) best = x;
    setHx(best);
  }
  return (
    <div className="relative">
      {series.length > 1 && (
        <div className="mb-1.5 flex flex-wrap gap-3 text-[12px] text-fg-2">
          {series.map((s) => <span key={s.name} className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm" style={{ background: s.color }} />{s.name}</span>)}
        </div>
      )}
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full touch-none" style={{ height }}
        onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHx(null)} role="img">
        {[0, 0.5, 1].map((f) => {
          const y = lo + f * (hi - lo);
          return <g key={f}><line x1={padL} x2={W - padR} y1={sy(y)} y2={sy(y)} stroke="rgba(255,255,255,0.07)" vectorEffect="non-scaling-stroke" />
            <text x={padL - 6} y={sy(y)} fontSize={11} textAnchor="end" dominantBaseline="middle" fill="rgba(235,235,245,0.38)">{yFormat(y)}</text></g>;
        })}
        <text x={padL} y={H - 5} fontSize={11} fill="rgba(235,235,245,0.38)">{xLabel ? xLabel(x0) : x0}</text>
        <text x={W - padR} y={H - 5} fontSize={11} textAnchor="end" fill="rgba(235,235,245,0.38)">{xLabel ? xLabel(x1) : x1}</text>
        {series.map((s) => {
          const pts = s.points.filter((p) => p.y != null) as { x: number; y: number }[];
          return <path key={s.name} d={pts.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ")}
            fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />;
        })}
        {hx != null && <line x1={sx(hx)} x2={sx(hx)} y1={padT} y2={H - padB} stroke="rgba(255,255,255,0.25)" vectorEffect="non-scaling-stroke" />}
      </svg>
      {hx != null && (
        <div className="pointer-events-none absolute top-6 rounded-lg border border-white/10 bg-[#16161f]/95 px-2.5 py-1.5 text-[12px] shadow-lg"
          style={{ left: `clamp(0px, calc(${(sx(hx) / W) * 100}% - 60px), calc(100% - 140px))` }}>
          <div className="text-fg-3">{xLabel ? xLabel(hx) : hx}</div>
          {series.map((s) => {
            const p = s.points.find((q) => q.x === hx);
            return <div key={s.name} className="tabular-nums text-fg">{s.name}: {p?.y != null ? yFormat(p.y) : "—"}</div>;
          })}
        </div>
      )}
    </div>
  );
}
