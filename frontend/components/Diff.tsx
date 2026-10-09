"use client";
import { diffWords } from "diff";

export function DiffView({ before, after }: { before: string; after: string }) {
  const parts = diffWords(before || "", after || "");
  return (
    <div className="whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-white p-3 text-sm" data-testid="diff">
      {parts.map((p, i) => (
        <span key={i} className={p.added ? "bg-emerald-100 text-emerald-900" : p.removed ? "bg-red-100 text-red-800 line-through" : ""}>
          {p.value}
        </span>
      ))}
    </div>
  );
}

export function BeforeAfter({ before, after, label }: { before: string; after: string; label: string }) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium text-slate-700">{label}</div>
      <div className="grid gap-3 md:grid-cols-2">
        <div><div className="mb-1 text-xs uppercase text-slate-500">Before</div>
          <div className="min-h-[2.5rem] whitespace-pre-wrap break-words rounded-md border border-red-200 bg-red-50 p-3 text-sm">{before || <span className="text-slate-400">(empty)</span>}</div></div>
        <div><div className="mb-1 text-xs uppercase text-slate-500">After</div>
          <div className="min-h-[2.5rem] whitespace-pre-wrap break-words rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm">{after || <span className="text-slate-400">(empty)</span>}</div></div>
      </div>
      <div className="text-xs uppercase text-slate-500">Changes</div>
      <DiffView before={before} after={after} />
    </div>
  );
}
