"use client";
import Link from "next/link";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { cx, JsonBlock, SeverityBadge, StatusBadge, TypeBadge } from "./ui";

export type Issue = {
  id: string; rule_id: string; category: string; severity: string; finding_type: string; confidence: string;
  title: string; url: string | null; description: string; status?: string; fix_type?: string | null;
  why_it_matters?: string; recommendation?: string; evidence?: any;
};

const CAT: Record<string, string> = { technical: "Technical", content: "Content", aeo: "AEO", geo: "GEO" };

export function IssueRow({ issue, href }: { issue: Issue; href?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="group -mx-2 rounded-xl px-2 py-3.5 transition hover:bg-ink-50/70" data-testid="issue-row">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <SeverityBadge s={issue.severity} />
            <TypeBadge t={issue.finding_type} />
            <span className="rounded-md bg-ink-100 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">{CAT[issue.category] || issue.category}</span>
            {issue.status && issue.status !== "open" && <StatusBadge s={issue.status} />}
          </div>
          <div className="mt-2">
            {href ? (
              <Link href={href} className="font-semibold text-ink-900 no-underline hover:text-brand-700">{issue.title}</Link>
            ) : (
              <button className="inline-flex items-center gap-1 text-left font-semibold text-ink-900 hover:text-brand-700" onClick={() => setOpen(!open)} aria-expanded={open}>
                {issue.title}
              </button>
            )}
          </div>
          <div className="mt-0.5 break-all text-xs text-ink-500">{issue.url || "Site-wide"}</div>
          <div className="mt-1.5 text-sm text-ink-600">{issue.description}</div>
          {open && (
            <div className="mt-4 space-y-3 rounded-xl border border-ink-200/80 bg-white p-4 text-sm">
              {issue.why_it_matters && <div><div className="text-xs font-semibold uppercase tracking-wider text-ink-400">Why it matters</div><p className="mt-1 text-ink-700">{issue.why_it_matters}</p></div>}
              {issue.recommendation && <div><div className="text-xs font-semibold uppercase tracking-wider text-ink-400">Recommendation</div><p className="mt-1 text-ink-700">{issue.recommendation}</p></div>}
              <p className="text-xs text-ink-500">Confidence: {issue.confidence}</p>
              {issue.evidence && Object.keys(issue.evidence).length > 0 && <JsonBlock value={issue.evidence} />}
            </div>
          )}
        </div>
        {href ? <ChevronRight className="mt-1 h-5 w-5 shrink-0 text-ink-300 group-hover:text-ink-500" />
          : <button onClick={() => setOpen(!open)} aria-label={open ? "Collapse" : "Expand"} className="rounded-md p-1 text-ink-300 hover:text-ink-600">
            <ChevronDown className={cx("h-5 w-5 transition", open && "rotate-180")} />
          </button>}
      </div>
    </li>
  );
}

export function IssueList({ issues, hrefFor }: { issues: Issue[]; hrefFor?: (i: Issue) => string }) {
  return (
    <ul className="divide-y divide-ink-100">
      {issues.map((i) => <IssueRow key={i.id} issue={i} href={hrefFor?.(i)} />)}
    </ul>
  );
}
