"use client";
import Link from "next/link";
import { useState } from "react";
import { JsonBlock, SeverityBadge, StatusBadge, TypeBadge } from "./ui";

export type Issue = {
  id: string; rule_id: string; category: string; severity: string; finding_type: string; confidence: string;
  title: string; url: string | null; description: string; status?: string; fix_type?: string | null;
  why_it_matters?: string; recommendation?: string; evidence?: any;
};

export function IssueRow({ issue, href }: { issue: Issue; href?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-slate-100 py-3 last:border-0" data-testid="issue-row">
      <div className="flex flex-wrap items-start gap-2">
        <SeverityBadge s={issue.severity} />
        <TypeBadge t={issue.finding_type} />
        <span className="text-xs uppercase text-slate-400">{issue.category}</span>
        {issue.status && issue.status !== "open" && <StatusBadge s={issue.status} />}
        <div className="min-w-0 flex-1">
          {href ? (
            <Link href={href} className="font-medium text-slate-900">{issue.title}</Link>
          ) : (
            <button className="text-left font-medium text-slate-900 hover:underline" onClick={() => setOpen(!open)}>{issue.title}</button>
          )}
          <div className="mt-0.5 break-all text-xs text-slate-500">{issue.url || "Site-wide"}</div>
          <div className="mt-1 text-sm text-slate-600">{issue.description}</div>
          {open && (
            <div className="mt-3 space-y-2 text-sm">
              {issue.why_it_matters && <p><b>Why it matters:</b> {issue.why_it_matters}</p>}
              {issue.recommendation && <p><b>Recommendation:</b> {issue.recommendation}</p>}
              <p className="text-xs text-slate-500">Confidence: {issue.confidence}</p>
              {issue.evidence && Object.keys(issue.evidence).length > 0 && <JsonBlock value={issue.evidence} />}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

export function IssueList({ issues, hrefFor }: { issues: Issue[]; hrefFor?: (i: Issue) => string }) {
  return (
    <ul>
      {issues.map((i) => <IssueRow key={i.id} issue={i} href={hrefFor?.(i)} />)}
    </ul>
  );
}
