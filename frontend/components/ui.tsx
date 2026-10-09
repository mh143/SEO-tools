"use client";
import Link from "next/link";
import { ReactNode, useState } from "react";
import { ApiError } from "@/lib/api";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function Button({
  children, onClick, variant = "primary", disabled, type = "button", size = "md", busy, title, testId,
}: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean; type?: "button" | "submit"; size?: "sm" | "md"; busy?: boolean; title?: string; testId?: string;
}) {
  const styles = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 border-transparent",
    secondary: "bg-white text-slate-800 border-slate-300 hover:bg-slate-50",
    danger: "bg-red-600 text-white hover:bg-red-700 border-transparent",
    ghost: "bg-transparent text-slate-700 border-transparent hover:bg-slate-100",
  }[variant];
  return (
    <button
      type={type} onClick={onClick} disabled={disabled || busy} title={title} data-testid={testId}
      className={cx("inline-flex items-center gap-2 rounded-md border font-medium shadow-sm transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-4 py-2 text-sm", styles)}
    >
      {busy && <Spinner small />}
      {children}
    </button>
  );
}

export function Card({ children, className, title, actions }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={cx("rounded-lg border border-slate-200 bg-white p-5 shadow-sm", className)}>
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Spinner({ small }: { small?: boolean }) {
  return (
    <span
      aria-label="Loading"
      className={cx("inline-block animate-spin rounded-full border-2 border-current border-t-transparent", small ? "h-3 w-3" : "h-5 w-5")}
    />
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 p-8 text-slate-500" role="status">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError | Error | string | null; onRetry?: () => void }) {
  if (!error) return null;
  const msg = typeof error === "string" ? error : error.message;
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <div className="font-medium">Something went wrong</div>
      <div className="mt-1">{msg}</div>
      {onRetry && (
        <button className="mt-2 text-sm font-medium underline" onClick={onRetry}>Try again</button>
      )}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center">
      <div className="font-medium text-slate-800">{title}</div>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function Notice({ kind = "info", children, testId }: { kind?: "info" | "warning" | "success" | "error"; children: ReactNode; testId?: string }) {
  const s = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
    error: "border-red-200 bg-red-50 text-red-900",
  }[kind];
  return <div data-testid={testId} className={cx("rounded-md border p-3 text-sm", s)}>{children}</div>;
}

const SEV: Record<string, string> = {
  critical: "bg-red-100 text-red-800", high: "bg-orange-100 text-orange-800", medium: "bg-yellow-100 text-yellow-800",
  low: "bg-sky-100 text-sky-800", info: "bg-slate-100 text-slate-700",
};
const TYPE: Record<string, string> = {
  error: "bg-red-50 text-red-700 ring-1 ring-red-200", warning: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
  recommendation: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200", info: "bg-slate-50 text-slate-600 ring-1 ring-slate-200",
};
const STATUS: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-800", verified: "bg-emerald-100 text-emerald-800", connected: "bg-emerald-100 text-emerald-800",
  partial: "bg-amber-100 text-amber-800", running: "bg-sky-100 text-sky-800", queued: "bg-slate-100 text-slate-700",
  failed: "bg-red-100 text-red-800", cancelled: "bg-slate-200 text-slate-700", error: "bg-red-100 text-red-800",
  drafted: "bg-indigo-100 text-indigo-800", awaiting_approval: "bg-amber-100 text-amber-800", approved: "bg-teal-100 text-teal-800",
  applying: "bg-sky-100 text-sky-800", verifying: "bg-sky-100 text-sky-800", rejected: "bg-slate-200 text-slate-700",
  rolled_back: "bg-slate-200 text-slate-700", externally_applied_unverified: "bg-amber-100 text-amber-800",
  detected: "bg-slate-100 text-slate-700", analyzed: "bg-slate-100 text-slate-700", open: "bg-slate-100 text-slate-700",
  ignored: "bg-slate-200 text-slate-600", fixed: "bg-emerald-100 text-emerald-800", regressed: "bg-red-100 text-red-800",
  pending: "bg-slate-100 text-slate-700", disconnected: "bg-slate-200 text-slate-600", active: "bg-emerald-100 text-emerald-800",
  past_due: "bg-red-100 text-red-800", canceled: "bg-slate-200 text-slate-700",
};

export function Badge({ children, tone, className }: { children: ReactNode; tone?: string; className?: string }) {
  return (
    <span className={cx("inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium", tone || "bg-slate-100 text-slate-700", className)}>
      {children}
    </span>
  );
}

export const SeverityBadge = ({ s }: { s: string }) => <Badge tone={SEV[s]}>{s}</Badge>;
export const TypeBadge = ({ t }: { t: string }) => <Badge tone={TYPE[t]}>{t}</Badge>;
export const StatusBadge = ({ s }: { s: string }) => <Badge tone={STATUS[s]}>{s.replace(/_/g, " ")}</Badge>;

export function ScoreTile({ label, value, hint }: { label: string; value: number | undefined; hint?: string }) {
  const v = typeof value === "number" ? value : null;
  const color = v === null ? "text-slate-400" : v >= 85 ? "text-emerald-600" : v >= 60 ? "text-amber-600" : "text-red-600";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4" title={hint}>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={cx("mt-1 text-3xl font-semibold tabular-nums", color)}>{v ?? "–"}</div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { key: string; label: ReactNode }[]; value: string; onChange: (k: string) => void }) {
  return (
    <div className="mb-4 flex gap-1 border-b border-slate-200" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.key} role="tab" aria-selected={value === t.key} onClick={() => onChange(t.key)}
          className={cx("-mb-px border-b-2 px-3 py-2 text-sm font-medium",
            value === t.key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800")}
        >
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

export function PageHeader({ title, subtitle, actions, back }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; back?: { href: string; label: string } }) {
  return (
    <div className="mb-6">
      {back && <Link href={back.href} className="text-sm text-slate-500">← {back.label}</Link>}
      <div className="mt-1 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="break-words text-2xl font-semibold text-slate-900">{title}</h1>
          {subtitle && <div className="mt-1 text-sm text-slate-500">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function fmtDate(s?: string | null) {
  if (!s) return "–";
  return new Date(s).toLocaleString();
}

export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="mono max-h-96 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
