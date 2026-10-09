"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { IssueList } from "@/components/IssueList";
import { Button, Card, Empty, ErrorState, fmtDate, JsonBlock, Loading, Notice, PageHeader, ScoreTile, SeverityBadge, Spinner, StatusBadge, Tabs, TypeBadge } from "@/components/ui";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

const RUNNING = ["queued", "running"];
const PAGE = 50;

export default function CrawlDashboard({ params }: { params: { crawlId: string } }) {
  const { orgId, role } = useSession();
  const base = `/orgs/${orgId}/crawls/${params.crawlId}`;
  const { data: crawl, error, loading, reload } = useApi<any>(base, { pollMs: 2000, pollWhile: (d) => RUNNING.includes(d.status) });
  const [tab, setTab] = useState("issues");
  const [filters, setFilters] = useState({ category: "", severity: "", finding_type: "", status: "", rule_id: "", q: "" });
  const [offset, setOffset] = useState(0);
  const [issues, setIssues] = useState<any>(null);
  const [issuesErr, setIssuesErr] = useState<string | null>(null);
  const [pages, setPages] = useState<any>(null);
  const done = crawl && !RUNNING.includes(crawl.status);

  useEffect(() => {
    if (!done) return;
    const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    Object.entries(filters).forEach(([k, v]) => v && qs.set(k, v));
    setIssues(null);
    api(`${base}/issues?${qs}`).then(setIssues).catch((e) => setIssuesErr(e.message));
  }, [done, filters, offset]);
  useEffect(() => {
    if (done && tab === "pages" && !pages) api(`${base}/pages?limit=500`).then(setPages).catch((e) => setIssuesErr(e.message));
  }, [done, tab]);

  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const sc = crawl.summary?.scores || {};
  const setF = (k: string, v: string) => { setOffset(0); setFilters({ ...filters, [k]: v }); };

  return (
    <>
      <PageHeader title="Audit results" subtitle={<span className="break-all">{crawl.start_url} · started {fmtDate(crawl.created_at)}</span>}
        back={crawl.website_id ? { href: `/app/${orgId}/websites/${crawl.website_id}`, label: "Website" } : undefined}
        actions={<>
          <StatusBadge s={crawl.status} />
          {RUNNING.includes(crawl.status) && hasRole(role, "editor") && (
            <Button size="sm" variant="secondary" onClick={async () => { await post(`${base}/cancel`); reload(); }}>Cancel</Button>
          )}
          {done && crawl.status !== "failed" && ["csv", "json", "md", "html"].map((f) => (
            <a key={f} className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs no-underline hover:bg-slate-50 hover:no-underline" href={`/api${base}/export?format=${f}`}>{f.toUpperCase()}</a>
          ))}
        </>} />

      {RUNNING.includes(crawl.status) && (
        <Card>
          <div className="flex items-center gap-3" data-testid="crawl-progress">
            <Spinner />
            <div>
              <div className="font-medium">{crawl.status === "queued" ? "Waiting for a crawler…" : "Crawling and auditing…"}</div>
              <div className="text-sm text-slate-500">{crawl.pages_crawled} crawled · {crawl.pages_discovered} discovered · {crawl.pages_failed} failed · limit {crawl.settings.max_pages} pages, depth {crawl.settings.max_depth}</div>
            </div>
          </div>
          <div className="mt-3 h-2 rounded bg-slate-100"><div className="h-2 rounded bg-brand-500 transition-all" style={{ width: `${Math.min(100, (crawl.pages_crawled / Math.max(1, crawl.settings.max_pages)) * 100)}%` }} /></div>
        </Card>
      )}
      {crawl.status === "failed" && <Notice kind="error">This audit failed: {crawl.error || "unknown error"}</Notice>}
      {crawl.status === "cancelled" && <Notice kind="warning">This audit was cancelled.</Notice>}
      {crawl.status === "partial" && (
        <div className="mb-4"><Notice kind="warning" testId="partial-notice">
          Partial results: {crawl.summary?.limit_reached ? "the page limit was reached; " : ""}{crawl.pages_failed ? `${crawl.pages_failed} URL(s) returned errors or could not be fetched; ` : ""}{crawl.error || ""}
          Findings below cover the pages that were crawled.
        </Notice></div>
      )}
      {done && crawl.status !== "failed" && crawl.status !== "cancelled" && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5" data-testid="scores">
            <ScoreTile label="Technical" value={sc.technical} /><ScoreTile label="Content" value={sc.content} />
            <ScoreTile label="AEO" value={sc.aeo} /><ScoreTile label="GEO readiness" value={sc.geo} />
            <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
              <div className="text-xs font-medium uppercase text-slate-500">Pages</div>
              <div className="mt-1 text-3xl font-semibold">{crawl.pages_crawled}</div>
              {crawl.pages_rendered > 0 && <div className="text-xs text-slate-500">{crawl.pages_rendered} JS-rendered</div>}
            </div>
          </div>
          <p className="mt-2 text-xs text-slate-500">{sc.disclaimer}</p>
          <div className="my-4 flex flex-wrap gap-4 text-sm">
            {Object.entries(crawl.summary?.by_type || {}).map(([k, v]) => <span key={k}><TypeBadge t={k} /> {v as number}</span>)}
            {crawl.summary?.diff?.has_previous && <span className="text-slate-500">vs previous audit: +{crawl.summary.diff.new} new, {crawl.summary.diff.resolved} resolved{crawl.summary.diff.regressed ? `, ${crawl.summary.diff.regressed} regressed` : ""}</span>}
          </div>
          <Tabs value={tab} onChange={setTab} tabs={[{ key: "issues", label: "Findings" }, { key: "pages", label: "Pages" }, { key: "site", label: "robots.txt & sitemaps" }]} />
          {issuesErr && <ErrorState error={issuesErr} />}
          {tab === "issues" && (
            <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
              <Card title="By check">
                <ul className="max-h-[600px] space-y-1 overflow-auto text-sm">
                  <li><button className={`w-full rounded px-2 py-1 text-left ${!filters.rule_id ? "bg-brand-50" : ""}`} onClick={() => setF("rule_id", "")}>All checks</button></li>
                  {issues?.groups?.map((g: any) => (
                    <li key={g.rule_id}>
                      <button className={`flex w-full items-start gap-2 rounded px-2 py-1 text-left hover:bg-slate-50 ${filters.rule_id === g.rule_id ? "bg-brand-50" : ""}`} onClick={() => setF("rule_id", g.rule_id)}>
                        <SeverityBadge s={g.severity} /><span className="flex-1">{g.title}</span><span className="text-slate-500">{g.count}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
              <Card>
                <div className="mb-3 grid gap-2 md:grid-cols-5">
                  <input className="input md:col-span-2" placeholder="Search title or URL…" value={filters.q} onChange={(e) => setF("q", e.target.value)} aria-label="Search" />
                  <select className="input" value={filters.category} onChange={(e) => setF("category", e.target.value)} aria-label="Category">
                    <option value="">All categories</option><option value="technical">Technical</option><option value="content">Content</option><option value="aeo">AEO</option><option value="geo">GEO</option>
                  </select>
                  <select className="input" value={filters.finding_type} onChange={(e) => setF("finding_type", e.target.value)} aria-label="Type">
                    <option value="">All types</option><option value="error">Errors</option><option value="warning">Warnings</option><option value="recommendation">Recommendations</option><option value="info">Info</option>
                  </select>
                  <select className="input" value={filters.status} onChange={(e) => setF("status", e.target.value)} aria-label="Status">
                    <option value="">Any status</option><option value="open">Open</option><option value="regressed">Regressed</option><option value="ignored">Ignored</option><option value="fixed">Fixed</option>
                  </select>
                </div>
                {!issues && <Loading />}
                {issues && issues.items.length === 0 && <Empty title="No findings match these filters" />}
                {issues && issues.items.length > 0 && (
                  <>
                    <IssueList issues={issues.items} hrefFor={(i) => `/app/${orgId}/issues/${i.id}`} />
                    <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
                      <span>{offset + 1}–{Math.min(offset + PAGE, issues.total)} of {issues.total}</span>
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</Button>
                        <Button size="sm" variant="secondary" disabled={offset + PAGE >= issues.total} onClick={() => setOffset(offset + PAGE)}>Next</Button>
                      </div>
                    </div>
                  </>
                )}
              </Card>
            </div>
          )}
          {tab === "pages" && (
            <Card>
              {!pages ? <Loading /> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-2">URL</th><th>Status</th><th>Title</th><th>Words</th><th>Indexable</th><th>Inlinks</th><th>Issues</th></tr></thead>
                    <tbody>{pages.items.map((p: any) => (
                      <tr key={p.id} className="border-t border-slate-100 align-top">
                        <td className="max-w-xs break-all py-2"><Link href={`/app/${orgId}/pages/${p.id}`}>{p.url}</Link>{p.error && <div className="text-xs text-red-600">{p.error}</div>}</td>
                        <td>{p.status_code ?? "–"}</td><td className="max-w-xs">{p.title || <span className="text-slate-400">–</span>}</td>
                        <td>{p.word_count ?? "–"}</td><td>{p.indexable === null ? "–" : p.indexable ? "yes" : "no"}</td>
                        <td>{p.inbound_links}</td><td>{p.issue_count}</td>
                      </tr>))}</tbody>
                  </table>
                </div>
              )}
            </Card>
          )}
          {tab === "site" && (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title="robots.txt">
                <p className="mb-2 text-sm text-slate-500">HTTP {crawl.site_data?.robots?.status ?? "–"}{crawl.site_data?.robots?.error ? ` · ${crawl.site_data.robots.error}` : ""}</p>
                <pre className="mono max-h-96 overflow-auto rounded bg-slate-50 p-3 text-xs">{crawl.site_data?.robots?.raw || "(empty or not found)"}</pre>
              </Card>
              <Card title="Sitemaps">
                <p className="mb-2 text-sm text-slate-500">{crawl.site_data?.sitemap_url_count ?? 0} URL(s) found in sitemaps.</p>
                <JsonBlock value={crawl.site_data?.sitemaps || []} />
              </Card>
            </div>
          )}
        </>
      )}
    </>
  );
}
