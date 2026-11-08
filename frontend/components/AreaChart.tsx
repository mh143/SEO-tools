"use client";
import { useMemo, useRef, useState } from "react";

type Point = { x: string; y: number };

// Single-series area chart with a crosshair tooltip. One axis only; the caller switches metrics.
export function AreaChart({ data, format = (v) => v.toLocaleString(), invert = false, height = 220, label }: {
  data: Point[]; format?: (v: number) => string; invert?: boolean; height?: number; label: string;
}) {
  const W = 720, H = height, P = { l: 44, r: 12, t: 12, b: 26 };
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const { pts, ticks, min, max } = useMemo(() => {
    const ys = data.map((d) => d.y);
    let lo = Math.min(...ys, invert ? Infinity : 0), hi = Math.max(...ys, 1);
    if (invert) { lo = Math.max(0, Math.floor(lo - 1)); hi = Math.ceil(hi + 1); }
    const span = hi - lo || 1;
    const sx = (i: number) => P.l + (data.length <= 1 ? 0 : (i / (data.length - 1)) * (W - P.l - P.r));
    const sy = (v: number) => {
      const t = (v - lo) / span;
      return invert ? P.t + t * (H - P.t - P.b) : H - P.b - t * (H - P.t - P.b);
    };
    const ticks = [0, 0.5, 1].map((t) => { const v = lo + t * span; return { v, y: sy(v) }; });
    return { pts: data.map((d, i) => ({ ...d, cx: sx(i), cy: sy(d.y) })), ticks, min: lo, max: hi };
  }, [data, invert, H]);
  if (!data.length) return <div className="grid h-40 place-items-center text-sm text-ink-500">No data for this period.</div>;
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p.cx.toFixed(1)},${p.cy.toFixed(1)}`).join(" ");
  const base = invert ? P.t : H - P.b;
  const area = `${line} L${pts[pts.length - 1].cx},${base} L${pts[0].cx},${base} Z`;
  const step = Math.max(1, Math.ceil(pts.length / 6));
  const h = hover !== null ? pts[hover] : null;

  function move(e: React.MouseEvent<SVGSVGElement>) {
    const r = ref.current!.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W;
    let best = 0;
    pts.forEach((p, i) => { if (Math.abs(p.cx - x) < Math.abs(pts[best].cx - x)) best = i; });
    setHover(best);
  }

  return (
    <div className="relative">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="h-auto w-full touch-none" role="img"
        aria-label={`${label} over time, from ${format(min)} to ${format(max)}`} onMouseMove={move} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="ac-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#625cf7" stopOpacity={invert ? 0.04 : 0.22} />
            <stop offset="1" stopColor="#625cf7" stopOpacity={invert ? 0.22 : 0.02} />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t.v}>
            <line x1={P.l} x2={W - P.r} y1={t.y} y2={t.y} stroke="#eef0f5" />
            <text x={P.l - 8} y={t.y + 4} textAnchor="end" className="fill-ink-400 text-[11px] tabular-nums">{format(t.v)}</text>
          </g>
        ))}
        <path d={area} fill="url(#ac-fill)" />
        <path d={line} fill="none" stroke="#523deb" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {pts.map((p, i) => i % step === 0 && (
          <text key={p.x} x={p.cx} y={H - 6} textAnchor="middle" className="fill-ink-400 text-[11px]">
            {new Date(p.x + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })}
          </text>
        ))}
        {h && (
          <g pointerEvents="none">
            <line x1={h.cx} x2={h.cx} y1={P.t} y2={H - P.b} stroke="#9aa3b5" strokeDasharray="3 3" />
            <circle cx={h.cx} cy={h.cy} r={5} fill="#523deb" stroke="#fff" strokeWidth={2} />
          </g>
        )}
      </svg>
      {h && (
        <div className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-lg bg-ink-900 px-2.5 py-1.5 text-xs text-white shadow-lift"
          style={{ left: `${(h.cx / W) * 100}%` }}>
          <div className="text-ink-300">{new Date(h.x + "T00:00:00").toLocaleDateString(undefined, { dateStyle: "medium" })}</div>
          <div className="font-semibold tabular-nums">{label}: {format(h.y)}</div>
        </div>
      )}
    </div>
  );
}
