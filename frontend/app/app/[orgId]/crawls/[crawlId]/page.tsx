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
      <PageHeader eyebrow="Audit" title="Audit results" subtitle={<span className="break-all">{crawl.start_url} · started {fmtDate(crawl.created_at)}</span>}
        back={crawl.website_id ? { href: `/app/${orgId}/websites/${crawl.website_id}`, label: "Website" } : undefined}
        actions={<>
          <StatusBadge s={crawl.status} />
          {RUNNING.includes(crawl.status) && hasRole(role, "editor") && (
            <Button size="sm" variant="secondary" onClick={async () => { await post(`${base}/cancel`); reload(); }}>Cancel</Button>
          )}
          {done && crawl.status !== "failed" && ["csv", "json", "md", "html"].map((f) => (
            <a key={f} className="inline-flex h-8 items-center rounded-lg border border-ink-200 bg-white px-3 text-xs font-medium text-ink-700 no-underline shadow-sm hover:bg-ink-50 hover:text-ink-900" href={`/api${base}/export?format=${f}`}>{f.toUpperCase()}</a>
          ))}
        </>} />

      {RUNNING.includes(crawl.status) && (
        <Card>
          <div className="flex items-center gap-3" data-testid="crawl-progress">
            <Spinner />
            <div>
              <div className="font-semibold text-ink-900">{crawl.status === "queued" ? "Waiting for a crawler…" : "Crawling and auditing…"}</div>
              <div className="text-sm text-ink-500">{crawl.pages_crawled} crawled · {crawl.pages_discovered} discovered · {crawl.pages_failed} failed · limit {crawl.settings.max_pages} pages, depth {crawl.settings.max_depth}</div>
            </div>
          </div>
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-ink-100"><div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-violet-500 transition-all" style={{ width: `${Math.min(100, (crawl.pages_crawled / Math.max(1, crawl.settings.max_pages)) * 100)}%` }} /></div>
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
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="scores">
            <ScoreTile label="Technical" value={sc.technical} /><ScoreTile label="Content" value={sc.content} />
            <ScoreTile label="AEO" value={sc.aeo} /><ScoreTile label="GEO readiness" value={sc.geo} />
            <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-card">
              <div className="text-xs font-semibold uppercase tracking-wider text-ink-500">Pages crawled</div>
              <div className="mt-2 text-3xl font-semibold tabular-nums text-ink-900">{crawl.pages_crawled}</div>
              {crawl.pages_rendered > 0 && <div className="text-xs text-ink-500">{crawl.pages_rendered} JS-rendered</div>}
            </div>
          </div>
          <p className="mt-3 text-xs text-ink-500">{sc.disclaimer}</p>
          <div className="my-6 flex flex-wrap items-center gap-3 text-sm">
            {Object.entries(crawl.summary?.by_type || {}).map(([k, v]) => <span key={k} className="inline-flex items-center gap-2 rounded-xl border border-ink-200/80 bg-white px-3 py-1.5 shadow-card"><TypeBadge t={k} /><b className="tabular-nums text-ink-900">{v as number}</b></span>)}
            {crawl.summary?.diff?.has_previous && <span className="text-ink-500">vs previous audit: <span className="text-rose-600">+{crawl.summary.diff.new} new</span>, <span className="text-emerald-600">{crawl.summary.diff.resolved} resolved</span>{crawl.summary.diff.regressed ? <>, <span className="text-amber-600">{crawl.summary.diff.regressed} regressed</span></> : ""}</span>}
          </div>
          <Tabs value={tab} onChange={setTab} tabs={[{ key: "issues", label: "Findings" }, { key: "pages", label: "Pages" }, { key: "site", label: "robots.txt & sitemaps" }]} />
          {issuesErr && <ErrorState error={issuesErr} />}
          {tab === "issues" && (
            <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
              <Card title="By check" className="lg:sticky lg:top-6 lg:self-start">
                <ul className="-mx-2 max-h-[640px] space-y-0.5 overflow-auto text-sm">
                  <li><button className={`w-full rounded-lg px-2.5 py-2 text-left font-medium ${!filters.rule_id ? "bg-brand-50 text-brand-700" : "text-ink-700 hover:bg-ink-50"}`} onClick={() => setF("rule_id", "")}>All checks</button></li>
                  {issues?.groups?.map((g: any) => (
                    <li key={g.rule_id}>
                      <button className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left ${filters.rule_id === g.rule_id ? "bg-brand-50 text-brand-800" : "text-ink-700 hover:bg-ink-50"}`} onClick={() => setF("rule_id", g.rule_id)}>
                        <SeverityBadge s={g.severity} /><span className="flex-1">{g.title}</span><span className="rounded-md bg-ink-100 px-1.5 text-xs font-semibold tabular-nums text-ink-600">{g.count}</span>
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
                    <div className="mt-4 flex items-center justify-between border-t border-ink-100 pt-4 text-sm text-ink-500">
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
                  <table className="table-clean">
                    <thead><tr><th>URL</th><th>Status</th><th>Title</th><th>Words</th><th>Indexable</th><th>Inlinks</th><th>Issues</th></tr></thead>
                    <tbody>{pages.items.map((p: any) => (
                      <tr key={p.id}>
                        <td className="max-w-xs break-all"><Link href={`/app/${orgId}/pages/${p.id}`}>{p.url}</Link>{p.error && <div className="text-xs text-red-600">{p.error}</div>}</td>
                        <td>{p.status_code ?? "–"}</td><td className="max-w-xs">{p.title || <span className="text-ink-400">–</span>}</td>
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
                <p className="mb-3 text-sm text-ink-500">HTTP {crawl.site_data?.robots?.status ?? "–"}{crawl.site_data?.robots?.error ? ` · ${crawl.site_data.robots.error}` : ""}</p>
                <pre className="mono max-h-96 overflow-auto rounded-xl bg-ink-50 p-4 text-xs leading-relaxed text-ink-700 ring-1 ring-ink-100">{crawl.site_data?.robots?.raw || "(empty or not found)"}</pre>
              </Card>
              <Card title="Sitemaps">
                <p className="mb-3 text-sm text-ink-500">{crawl.site_data?.sitemap_url_count ?? 0} URL(s) found in sitemaps.</p>
                <JsonBlock value={crawl.site_data?.sitemaps || []} />
              </Card>
            </div>
          )}
        </>
      )}
    </>
  );
}
