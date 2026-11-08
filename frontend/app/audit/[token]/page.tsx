"use client";
import { Download, FileText, Globe, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { IssueList } from "@/components/IssueList";
import { Footer, PublicNav } from "@/components/PublicNav";
import { ButtonLink, Card, ErrorState, Loading, Notice, ScoreRing, Spinner, StatusBadge, Tabs } from "@/components/ui";
import { useApi } from "@/lib/hooks";

const RUNNING = ["queued", "running"];
const SCORES = [["technical", "Technical"], ["content", "Content"], ["aeo", "AEO"], ["geo", "GEO readiness"]] as const;

export default function PublicAudit({ params }: { params: { token: string } }) {
  const { data, error, loading, reload } = useApi<any>(`/public/audits/${params.token}`, {
    pollMs: 2000, pollWhile: (d) => RUNNING.includes(d.status),
  });
  const [cat, setCat] = useState("all");
  const all = data?.issues || [];
  const issues = useMemo(() => all.filter((i: any) => cat === "all" || i.category === cat), [all, cat]);
  const count = (c: string) => all.filter((i: any) => c === "all" || i.category === c).length;
  const ready = data && !RUNNING.includes(data.status) && data.status !== "failed";

  return (
    <div className="min-h-screen bg-ink-50">
      <PublicNav />
      <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        {loading && <Loading label="Loading audit…" />}
        <ErrorState error={error} onRetry={reload} />
        {data && (
          <>
            <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
              <div className="flex min-w-0 items-center gap-4">
                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-white text-brand-600 shadow-card ring-1 ring-ink-200/80"><Globe className="h-6 w-6" /></span>
                <div className="min-w-0">
                  <div className="text-xs font-semibold uppercase tracking-wider text-brand-600">Free quick audit</div>
                  <h1 className="break-all text-xl font-semibold tracking-tight text-ink-900 sm:text-2xl">{data.start_url}</h1>
                  <div className="mt-1 flex items-center gap-2 text-sm text-ink-500"><StatusBadge s={data.status} /> {data.pages_crawled} page(s) crawled · max 10 pages</div>
                </div>
              </div>
              {ready && (
                <div className="flex gap-2">
                  <ButtonLink external href={`/api/public/audits/${params.token}/export?format=csv`} variant="secondary" size="sm" icon={Download}>CSV</ButtonLink>
                  <ButtonLink external href={`/api/public/audits/${params.token}/export?format=html`} variant="secondary" size="sm" icon={FileText}>HTML report</ButtonLink>
                </div>
              )}
            </div>
            {RUNNING.includes(data.status) && (
              <Card>
                <div className="flex items-center gap-4" data-testid="audit-progress">
                  <span className="grid h-12 w-12 place-items-center rounded-2xl bg-brand-50"><Spinner /></span>
                  <div><div className="font-semibold text-ink-900">Crawling your site…</div><div className="text-sm text-ink-500">{data.pages_crawled} page(s) so far. This usually takes under a minute.</div></div>
                </div>
                <div className="mt-5 h-1.5 overflow-hidden rounded-full bg-ink-100"><div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-violet-500 transition-all" style={{ width: `${Math.max(8, data.pages_crawled * 10)}%` }} /></div>
              </Card>
            )}
            {data.status === "failed" && <Notice kind="error">The audit could not run: {data.error || "unknown error"}</Notice>}
            {data.status === "partial" && data.error && <div className="mb-4"><Notice kind="warning">{data.error}</Notice></div>}
            {ready && (
              <>
                <Card>
                  <div className="grid grid-cols-2 gap-6 sm:grid-cols-4" data-testid="scores">
                    {SCORES.map(([k, l]) => (
                      <div key={k} className="flex flex-col items-center gap-2">
                        <ScoreRing value={data.summary?.scores?.[k]} size={92} stroke={8} label={l} />
                        <span className="text-xs font-semibold uppercase tracking-wider text-ink-500">{l}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-5 border-t border-ink-100 pt-4 text-center text-xs text-ink-500">{data.summary?.scores?.disclaimer}</p>
                </Card>
                <div className="my-6 flex flex-col items-start gap-4 rounded-2xl bg-gradient-to-r from-brand-600 to-violet-600 p-6 text-white shadow-glow sm:flex-row sm:items-center">
                  <Sparkles className="h-6 w-6 shrink-0" />
                  <div className="flex-1"><div className="font-semibold">Fix these issues automatically</div>
                    <div className="text-sm text-brand-100">Create a free account for AI-drafted fixes, monitoring and verified publishing to WordPress, Shopify and Wix.</div></div>
                  <ButtonLink href="/signup" variant="secondary" className="border-white">Create free account</ButtonLink>
                </div>
                <Tabs value={cat} onChange={setCat} tabs={[["all", "All"], ["technical", "Technical"], ["content", "Content"], ["aeo", "AEO"], ["geo", "GEO"]].map(([k, l]) => ({ key: k, label: <>{l} <span className="ml-1 opacity-60">{count(k)}</span></> }))} />
                <Card title={`Findings (${issues.length})`} subtitle="Click a finding to see why it matters and the evidence we found.">
                  {issues.length ? <IssueList issues={issues} /> : <p className="text-sm text-ink-500">No findings in this category.</p>}
                </Card>
                <p className="mt-4 text-center text-xs text-ink-500">This audit link expires {data.expires_at ? new Date(data.expires_at).toLocaleDateString() : "soon"}.</p>
              </>
            )}
          </>
        )}
      </main>
      <Footer />
    </div>
  );
}
