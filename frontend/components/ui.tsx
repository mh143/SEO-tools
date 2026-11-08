"use client";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";
import { ComponentType, ReactNode, useEffect, useId, useState } from "react";
import { ApiError } from "@/lib/api";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type IconT = ComponentType<{ className?: string }>;

/* ------------------------------------------------------------------ brand */
export function Logo({ className, dark }: { className?: string; dark?: boolean }) {
  const gid = `rl-g-${useId().replace(/:/g, "")}`;
  return (
    <span className={cx("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" aria-hidden>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#7c6cff" /><stop offset="1" stopColor="#4a2fd6" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="9" fill={`url(#${gid})`} />
        <circle cx="14.5" cy="14.5" r="6.2" fill="none" stroke="#fff" strokeWidth="2.6" />
        <path d="M19.2 19.2 24 24" stroke="#fff" strokeWidth="2.8" strokeLinecap="round" />
        <path d="M11.8 15.6l1.9 1.9 3.6-4" fill="none" stroke="#c7f9e0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className={cx("text-[1.05rem]", dark ? "text-white" : "text-ink-900")}>Rank<span className={dark ? "text-brand-300" : "text-brand-600"}>Lens</span></span>
    </span>
  );
}

/* ------------------------------------------------------------------ buttons */
const BTN_BASE = "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg border font-medium transition-all duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-50";
const BTN: Record<string, string> = {
  primary: "border-transparent bg-brand-600 text-white shadow-[inset_0_1px_0_rgba(255,255,255,.18),0_1px_2px_rgba(30,23,77,.25)] hover:bg-brand-700 hover:text-white",
  secondary: "border-ink-200 bg-white text-ink-800 shadow-sm hover:border-ink-300 hover:bg-ink-50 hover:text-ink-900",
  danger: "border-transparent bg-rose-600 text-white shadow-sm hover:bg-rose-700 hover:text-white",
  ghost: "border-transparent bg-transparent text-ink-600 hover:bg-ink-100 hover:text-ink-900",
  dark: "border-transparent bg-ink-900 text-white shadow-sm hover:bg-ink-800 hover:text-white",
};
const SIZE: Record<string, string> = { sm: "h-8 px-3 text-xs", md: "h-10 px-4 text-sm", lg: "h-12 px-6 text-[15px]" };

export function Button({
  children, onClick, variant = "primary", disabled, type = "button", size = "md", busy, title, testId, icon: Icon, className,
}: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "danger" | "ghost" | "dark";
  disabled?: boolean; type?: "button" | "submit"; size?: "sm" | "md" | "lg"; busy?: boolean; title?: string; testId?: string;
  icon?: IconT; className?: string;
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled || busy} title={title} data-testid={testId}
      className={cx(BTN_BASE, SIZE[size], BTN[variant], className)}>
      {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : Icon ? <Icon className="h-4 w-4" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function ButtonLink({ href, children, variant = "primary", size = "md", icon: Icon, className, external }: {
  href: string; children: ReactNode; variant?: keyof typeof BTN; size?: "sm" | "md" | "lg"; icon?: IconT; className?: string; external?: boolean;
}) {
  const cls = cx(BTN_BASE, SIZE[size], BTN[variant], "no-underline", className);
  const inner = <>{Icon && <Icon className="h-4 w-4" aria-hidden />}{children}</>;
  if (external) return <a href={href} className={cls}>{inner}</a>;
  return <Link href={href} className={cls}>{inner}</Link>;
}

/* ------------------------------------------------------------------ surfaces */
export function Card({ children, className, title, actions, subtitle, padded = true, icon: Icon }: {
  children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode; subtitle?: ReactNode; padded?: boolean; icon?: IconT;
}) {
  return (
    <section className={cx("rounded-2xl border border-ink-200/80 bg-white shadow-card", padded && "p-5 sm:p-6", className)}>
      {(title || actions) && (
        <div className={cx("mb-4 flex flex-wrap items-start justify-between gap-3", !padded && "px-5 pt-5 sm:px-6")}>
          <div className="flex min-w-0 items-start gap-3">
            {Icon && <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600"><Icon className="h-4 w-4" /></span>}
            <div className="min-w-0">
              {title && <h2 className="text-[15px] font-semibold text-ink-900">{title}</h2>}
              {subtitle && <div className="mt-0.5 text-sm text-ink-500">{subtitle}</div>}
            </div>
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Spinner({ small }: { small?: boolean }) {
  return <Loader2 aria-label="Loading" className={cx("animate-spin text-brand-600", small ? "h-3.5 w-3.5" : "h-5 w-5")} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("relative overflow-hidden rounded-lg bg-ink-100", className)}>
    <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/60 to-transparent" />
  </div>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="space-y-4 py-2" role="status" aria-label={label}>
      <div className="flex items-center gap-3 text-sm text-ink-500"><Spinner /> {label}</div>
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" />
      </div>
      <Skeleton className="h-48" />
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError | Error | string | null; onRetry?: () => void }) {
  if (!error) return null;
  const msg = typeof error === "string" ? error : error.message;
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-rose-200 bg-rose-50/80 p-4 text-sm text-rose-900">
      <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" aria-hidden />
      <div>
        <div className="font-semibold">Something went wrong</div>
        <div className="mt-0.5 text-rose-800">{msg}</div>
        {onRetry && <button className="mt-2 text-sm font-semibold text-rose-700 underline-offset-2 hover:underline" onClick={onRetry}>Try again</button>}
      </div>
    </div>
  );
}

export function Empty({ title, children, action, icon: Icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: IconT }) {
  return (
    <div className="rounded-2xl border border-dashed border-ink-300 bg-white/60 px-6 py-12 text-center">
      {Icon && <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-brand-50 text-brand-600"><Icon className="h-6 w-6" /></div>}
      <div className="font-semibold text-ink-900">{title}</div>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-ink-500">{children}</div>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

const NOTICE = {
  info: ["border-sky-200 bg-sky-50/80 text-sky-900", Info, "text-sky-500"],
  warning: ["border-amber-200 bg-amber-50/80 text-amber-900", AlertTriangle, "text-amber-500"],
  success: ["border-emerald-200 bg-emerald-50/80 text-emerald-900", CheckCircle2, "text-emerald-500"],
  error: ["border-rose-200 bg-rose-50/80 text-rose-900", XCircle, "text-rose-500"],
} as const;

export function Notice({ kind = "info", children, testId, onClose }: { kind?: "info" | "warning" | "success" | "error"; children: ReactNode; testId?: string; onClose?: () => void }) {
  const [cls, Icon, ic] = NOTICE[kind];
  return (
    <div data-testid={testId} className={cx("flex gap-3 rounded-xl border px-4 py-3 text-sm", cls)}>
      <Icon className={cx("mt-0.5 h-4 w-4 shrink-0", ic)} aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
      {onClose && <button onClick={onClose} aria-label="Dismiss" className="opacity-60 hover:opacity-100"><X className="h-4 w-4" /></button>}
    </div>
  );
}

/* ------------------------------------------------------------------ badges */
const SEV: Record<string, string> = {
  critical: "bg-rose-50 text-rose-700 ring-rose-200", high: "bg-orange-50 text-orange-700 ring-orange-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200", low: "bg-sky-50 text-sky-700 ring-sky-200", info: "bg-ink-50 text-ink-600 ring-ink-200",
};
const SEV_DOT: Record<string, string> = { critical: "bg-rose-500", high: "bg-orange-500", medium: "bg-amber-500", low: "bg-sky-500", info: "bg-ink-400" };
const TYPE: Record<string, string> = {
  error: "bg-rose-50 text-rose-700 ring-rose-200", warning: "bg-amber-50 text-amber-800 ring-amber-200",
  recommendation: "bg-brand-50 text-brand-700 ring-brand-200", info: "bg-ink-50 text-ink-600 ring-ink-200",
};
const GOOD = "bg-emerald-50 text-emerald-700 ring-emerald-200";
const WARN = "bg-amber-50 text-amber-800 ring-amber-200";
const BAD = "bg-rose-50 text-rose-700 ring-rose-200";
const BUSY = "bg-sky-50 text-sky-700 ring-sky-200";
const NEUTRAL = "bg-ink-50 text-ink-600 ring-ink-200";
const STATUS: Record<string, string> = {
  completed: GOOD, verified: GOOD, connected: GOOD, fixed: GOOD, active: GOOD, available: GOOD,
  partial: WARN, awaiting_approval: WARN, externally_applied_unverified: WARN, needs_configuration: WARN,
  running: BUSY, applying: BUSY, verifying: BUSY,
  failed: BAD, error: BAD, regressed: BAD, past_due: BAD,
  drafted: "bg-brand-50 text-brand-700 ring-brand-200", approved: "bg-teal-50 text-teal-700 ring-teal-200",
  queued: NEUTRAL, cancelled: NEUTRAL, rejected: NEUTRAL, rolled_back: NEUTRAL, detected: NEUTRAL, analyzed: NEUTRAL,
  open: NEUTRAL, ignored: NEUTRAL, pending: NEUTRAL, disconnected: NEUTRAL, canceled: NEUTRAL, not_implemented: NEUTRAL,
};
const STATUS_DOT: Record<string, string> = { [GOOD]: "bg-emerald-500", [WARN]: "bg-amber-500", [BAD]: "bg-rose-500", [BUSY]: "bg-sky-500 animate-pulse" };

export function Badge({ children, tone, className, dot }: { children: ReactNode; tone?: string; className?: string; dot?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
      tone || NEUTRAL, className)}>
      {dot && <span className={cx("h-1.5 w-1.5 rounded-full", dot)} aria-hidden />}
      {children}
    </span>
  );
}

export const SeverityBadge = ({ s }: { s: string }) => <Badge tone={SEV[s]} dot={SEV_DOT[s]}>{s}</Badge>;
export const TypeBadge = ({ t }: { t: string }) => <Badge tone={TYPE[t]}>{t}</Badge>;
export const StatusBadge = ({ s }: { s: string }) => <Badge tone={STATUS[s]} dot={STATUS_DOT[STATUS[s]] || "bg-ink-400"}>{s.replace(/_/g, " ")}</Badge>;

/* ------------------------------------------------------------------ scores & stats */
export function scoreColor(v: number | null | undefined) {
  if (typeof v !== "number") return { text: "text-ink-400", stroke: "#cfd4df", bg: "bg-ink-100", label: "No data" };
  if (v >= 85) return { text: "text-emerald-600", stroke: "#10b981", bg: "bg-emerald-500", label: "Good" };
  if (v >= 60) return { text: "text-amber-600", stroke: "#f59e0b", bg: "bg-amber-500", label: "Needs work" };
  return { text: "text-rose-600", stroke: "#f43f5e", bg: "bg-rose-500", label: "Poor" };
}

export function ScoreRing({ value, size = 88, stroke = 8, label }: { value: number | null | undefined; size?: number; stroke?: number; label?: string }) {
  const v = typeof value === "number" ? Math.max(0, Math.min(100, value)) : null;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const col = scoreColor(v);
  const [shown, setShown] = useState(0);
  useEffect(() => { const t = setTimeout(() => setShown(v ?? 0), 60); return () => clearTimeout(t); }, [v]);
  return (
    <div className="relative inline-grid place-items-center" style={{ width: size, height: size }} role="img" aria-label={`${label || "Score"}: ${v ?? "no data"}`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef0f5" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col.stroke} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c - (c * shown) / 100} style={{ transition: "stroke-dashoffset 900ms cubic-bezier(.2,.8,.2,1)" }} />
      </svg>
      <span className={cx("absolute font-semibold tracking-tight tabular-nums", col.text, size >= 80 ? "text-2xl" : size >= 60 ? "text-lg" : "text-[13px]")}>{v ?? "–"}</span>
    </div>
  );
}

export function ScoreTile({ label, value, hint }: { label: string; value: number | undefined; hint?: string }) {
  const col = scoreColor(value);
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-ink-200/80 bg-white p-4 shadow-card" title={hint}>
      <ScoreRing value={value} size={64} stroke={6} label={label} />
      <div className="min-w-0">
        <div className="text-xs font-semibold uppercase tracking-wider text-ink-500">{label}</div>
        <div className={cx("mt-1 text-sm font-medium", col.text)}>{col.label}</div>
      </div>
    </div>
  );
}

export function StatCard({ label, value, icon: Icon, hint, tone = "brand" }: { label: string; value: ReactNode; icon?: IconT; hint?: ReactNode; tone?: "brand" | "emerald" | "amber" | "rose" | "sky" }) {
  const tones = { brand: "bg-brand-50 text-brand-600", emerald: "bg-emerald-50 text-emerald-600", amber: "bg-amber-50 text-amber-600", rose: "bg-rose-50 text-rose-600", sky: "bg-sky-50 text-sky-600" };
  return (
    <div className="rounded-2xl border border-ink-200/80 bg-white p-5 shadow-card">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-ink-500">{label}</span>
        {Icon && <span className={cx("grid h-8 w-8 place-items-center rounded-lg", tones[tone])}><Icon className="h-4 w-4" /></span>}
      </div>
      <div className="mt-2 text-[28px] font-semibold leading-none tracking-tight tabular-nums text-ink-900">{value}</div>
      {hint && <div className="mt-2 text-xs text-ink-500">{hint}</div>}
    </div>
  );
}

export function Meter({ label, used, limit }: { label: string; used: number; limit: number | null | undefined }) {
  const has = limit !== null && limit !== undefined;
  const pct = has && limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm"><span className="text-ink-600">{label}</span>
        <span className="tabular-nums text-ink-500"><b className="font-semibold text-ink-900">{used.toLocaleString()}</b>{has ? ` / ${limit!.toLocaleString()}` : ""}</span></div>
      {has && <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-100">
        <div className={cx("h-full rounded-full transition-all", pct > 90 ? "bg-rose-500" : pct > 70 ? "bg-amber-500" : "bg-gradient-to-r from-brand-500 to-violet-500")} style={{ width: `${pct}%` }} />
      </div>}
    </div>
  );
}

/* ------------------------------------------------------------------ forms & nav */
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-ink-500">{hint}</span>}
    </label>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { key: string; label: ReactNode }[]; value: string; onChange: (k: string) => void }) {
  return (
    <div className="mb-5 inline-flex max-w-full gap-1 overflow-x-auto rounded-xl border border-ink-200/80 bg-white p-1 shadow-card" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={value === t.key} onClick={() => onChange(t.key)}
          className={cx("whitespace-nowrap rounded-lg px-3.5 py-1.5 text-sm font-medium transition",
            value === t.key ? "bg-ink-900 text-white shadow-sm" : "text-ink-500 hover:bg-ink-50 hover:text-ink-900")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, setError };
}

export function PageHeader({ title, subtitle, actions, back, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; back?: { href: string; label: string }; eyebrow?: ReactNode }) {
  return (
    <div className="mb-8 animate-fade-up">
      {back && (
        <Link href={back.href} className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-500 no-underline hover:text-ink-900">
          <ArrowLeft className="h-4 w-4" /> {back.label}
        </Link>
      )}
      <div className={cx("flex flex-wrap items-end justify-between gap-4", back && "mt-3")}>
        <div className="min-w-0">
          {eyebrow && <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-brand-600">{eyebrow}</div>}
          <h1 className="break-words text-2xl font-semibold tracking-tight text-ink-900 sm:text-[28px]">{title}</h1>
          {subtitle && <div className="mt-1.5 text-sm text-ink-500">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-ink-950/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative max-h-[92vh] w-full max-w-lg animate-fade-up overflow-auto rounded-t-2xl bg-white shadow-lift sm:rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-ink-100 px-6 py-4">
          <h3 className="text-base font-semibold text-ink-900">{title}</h3>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700"><X className="h-5 w-5" /></button>
        </div>
        <div className="px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-ink-100 bg-ink-50/60 px-6 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function fmtDate(s?: string | null) {
  if (!s) return "–";
  return new Date(s).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function timeAgo(s?: string | null) {
  if (!s) return "never";
  const d = (Date.now() - new Date(s).getTime()) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  if (d < 86400 * 30) return `${Math.floor(d / 86400)}d ago`;
  return new Date(s).toLocaleDateString();
}

export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="mono max-h-96 overflow-auto rounded-xl bg-ink-950 p-4 text-xs leading-relaxed text-ink-100">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
