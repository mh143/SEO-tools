"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { IssueList } from "@/components/IssueList";
import { Footer, PublicNav } from "@/components/PublicNav";
import { Card, ErrorState, Loading, Notice, ScoreTile, Spinner, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/hooks";

const RUNNING = ["queued", "running"];

export default function PublicAudit({ params }: { params: { token: string } }) {
  const { data, error, loading, reload } = useApi<any>(`/public/audits/${params.token}`, {
    pollMs: 2000, pollWhile: (d) => RUNNING.includes(d.status),
  });
  const [cat, setCat] = useState("all");
  const issues = useMemo(() => (data?.issues || []).filter((i: any) => cat === "all" || i.category === cat), [data, cat]);

  return (
    <>
      <PublicNav />
      <main className="mx-auto max-w-5xl px-4 py-8">
        {loading && <Loading label="Loading audit…" />}
        <ErrorState error={error} onRetry={reload} />
        {data && (
          <>
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="break-all text-2xl font-semibold">{data.start_url}</h1>
                <div className="mt-1 flex items-center gap-2 text-sm text-slate-500">
                  <StatusBadge s={data.status} /> {data.pages_crawled} page(s) crawled · free quick audit (max 10 pages)
                </div>
              </div>
              {!RUNNING.includes(data.status) && data.status !== "failed" && (
                <div className="flex gap-2 text-sm">
                  <a href={`/api/public/audits/${params.token}/export?format=csv`}>Download CSV</a>
                  <a href={`/api/public/audits/${params.token}/export?format=html`}>HTML report</a>
                </div>
              )}
            </div>
            {RUNNING.includes(data.status) && (
              <Card><div className="flex items-center gap-3" data-testid="audit-progress"><Spinner /> Crawling… {data.pages_crawled} page(s) so far.</div></Card>
            )}
            {data.status === "failed" && <Notice kind="error">The audit could not run: {data.error || "unknown error"}</Notice>}
            {data.status === "partial" && data.error && <div className="mb-4"><Notice kind="warning">{data.error}</Notice></div>}
            {!RUNNING.includes(data.status) && data.status !== "failed" && (
              <>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="scores">
                  <ScoreTile label="Technical" value={data.summary?.scores?.technical} />
                  <ScoreTile label="Content" value={data.summary?.scores?.content} />
                  <ScoreTile label="AEO" value={data.summary?.scores?.aeo} />
                  <ScoreTile label="GEO readiness" value={data.summary?.scores?.geo} />
                </div>
                <p className="mt-2 text-xs text-slate-500">{data.summary?.scores?.disclaimer}</p>
                <div className="my-6">
                  <Notice kind="info">
                    Want AI-drafted fixes, scheduled monitoring and one-click publishing to WordPress?{" "}
                    <Link href="/signup">Create a free account</Link> and add this site.
                  </Notice>
                </div>
                <Card title={`Findings (${data.issues.length})`} actions={
                  <select className="input w-40" value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">
                    <option value="all">All categories</option><option value="technical">Technical</option>
                    <option value="content">Content</option><option value="aeo">AEO</option><option value="geo">GEO</option>
                  </select>}>
                  {issues.length ? <IssueList issues={issues} /> : <p className="text-sm text-slate-500">No findings in this category.</p>}
                </Card>
                <p className="mt-4 text-xs text-slate-500">This audit link expires {data.expires_at ? new Date(data.expires_at).toLocaleDateString() : "soon"}.</p>
              </>
            )}
          </>
        )}
      </main>
      <Footer />
    </>
  );
}
