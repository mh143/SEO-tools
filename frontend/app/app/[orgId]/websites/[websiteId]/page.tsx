"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, CalendarClock, ExternalLink, KeyRound, Play, Plug, Trash2, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ProviderMark, providerLabel } from "@/components/Providers";
import { SearchConsolePanel } from "@/components/SearchConsolePanel";
import { Button, Card, Empty, ErrorState, Field, fmtDate, Loading, Notice, PageHeader, ScoreRing, StatusBadge, timeAgo, useAction } from "@/components/ui";
import { del, patch, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

const SCORE_KEYS = [["technical", "Technical"], ["content", "Content"], ["aeo", "AEO"], ["geo", "GEO readiness"]] as const;

export default function WebsiteDetail({ params }: { params: { websiteId: string } }) {
  const { orgId, role } = useSession();
  const router = useRouter();
  const path = `/orgs/${orgId}/websites/${params.websiteId}`;
  const { data, error, loading, reload } = useApi<any>(path, {
    pollMs: 3000, pollWhile: (d) => d.crawls.some((c: any) => ["queued", "running"].includes(c.status)),
  });
  const act = useAction();
  const [schedule, setSchedule] = useState("none");
  const [maxPages, setMaxPages] = useState<number | "">("");
  const [renderJs, setRenderJs] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (data) {
      setSchedule(data.schedule);
      setMaxPages(data.crawl_settings.max_pages ?? "");
      setRenderJs(!!data.crawl_settings.render_js);
    }
  }, [data?.id]);

  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const running = data.crawls.find((c: any) => ["queued", "running"].includes(c.status));
  const latest = data.crawls.find((c: any) => c.summary?.scores);
  const canEdit = hasRole(role, "editor");
  const publishing = data.integrations.filter((i: any) => i.status === "connected" && i.provider !== "google_search_console");

  return (
    <>
      <PageHeader title={data.name} back={{ href: `/app/${orgId}/websites`, label: "Websites" }}
        subtitle={<a href={data.root_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-ink-500 no-underline hover:text-brand-700">{data.root_url} <ExternalLink className="h-3.5 w-3.5" /></a>}
        actions={canEdit && (
          <Button testId="start-crawl" busy={act.busy} disabled={!!running} icon={Play}
            onClick={() => act.run(async () => { const r = await post(`${path}/crawls`, {}); router.push(`/app/${orgId}/crawls/${r.id}`); })}>
            {running ? "Audit running…" : "Run audit"}
          </Button>
        )} />
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}

      {latest && (
        <Card className="mb-6">
          <div className="flex flex-wrap items-center justify-between gap-6">
            <div className="flex flex-wrap gap-6 sm:gap-10">
              {SCORE_KEYS.map(([k, l]) => (
                <div key={k} className="flex flex-col items-center gap-2">
                  <ScoreRing value={latest.summary.scores[k]} size={72} stroke={7} label={l} />
                  <span className="text-xs font-semibold uppercase tracking-wider text-ink-500">{l}</span>
                </div>
              ))}
            </div>
            <div className="text-sm text-ink-500">
              <div>Latest audit {timeAgo(latest.created_at)} · {latest.pages_crawled} pages · {latest.summary.issue_count ?? 0} findings</div>
              <Link href={`/app/${orgId}/crawls/${latest.id}`} className="mt-2 inline-flex items-center gap-1 font-medium no-underline">Open results <ArrowRight className="h-4 w-4" /></Link>
            </div>
          </div>
        </Card>
      )}

      <div className="mb-6"><SearchConsolePanel orgId={orgId} websiteId={data.id} /></div>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Card title="Audit history" padded={false}>
            {data.crawls.length === 0 ? <div className="p-6"><Empty title="No audits yet">Run the first audit to see results.</Empty></div> : (
              <div className="overflow-x-auto">
                <table className="table-clean">
                  <thead><tr><th>Started</th><th>Status</th><th>Trigger</th><th>Pages</th><th>Findings</th><th>Change</th></tr></thead>
                  <tbody>
                    {data.crawls.map((c: any) => (
                      <tr key={c.id}>
                        <td><Link href={`/app/${orgId}/crawls/${c.id}`} className="font-medium no-underline">{fmtDate(c.created_at)}</Link></td>
                        <td><StatusBadge s={c.status} /></td><td className="capitalize">{c.trigger}</td><td className="tabular-nums">{c.pages_crawled}</td>
                        <td className="tabular-nums">{c.summary?.issue_count ?? "–"}</td>
                        <td className="text-xs">{c.summary?.diff?.has_previous ? (
                          <span className="inline-flex gap-2"><span className="text-rose-600">+{c.summary.diff.new}</span><span className="text-emerald-600">−{c.summary.diff.resolved}</span>{c.summary.diff.regressed ? <span className="text-amber-600">{c.summary.diff.regressed} regressed</span> : null}</span>
                        ) : <span className="text-ink-400">–</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
        <div className="space-y-6">
          <Card title="Monitoring & crawl settings" icon={CalendarClock}>
            <div className="space-y-4">
              <Field label="Scheduled audits" hint={`Your plan allows: ${data.plan_limits.schedules.join(", ")}`}>
                <select className="input capitalize" value={schedule} onChange={(e) => setSchedule(e.target.value)} disabled={!canEdit} name="schedule">
                  {["none", "monthly", "weekly", "daily"].map((s) => <option key={s} value={s} disabled={!data.plan_limits.schedules.includes(s)}>{s}</option>)}
                </select>
              </Field>
              <Field label="Max pages per audit" hint={`Plan limit: ${data.plan_limits.max_pages}`}>
                <input className="input" type="number" min={1} max={data.plan_limits.max_pages} value={maxPages}
                  onChange={(e) => setMaxPages(e.target.value ? Number(e.target.value) : "")} disabled={!canEdit} />
              </Field>
              <label className="flex items-start gap-3 rounded-xl border border-ink-200/80 p-3 text-sm">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-600" checked={renderJs} disabled={!canEdit || !data.plan_limits.js_rendering} onChange={(e) => setRenderJs(e.target.checked)} />
                <span><span className="font-medium text-ink-800">Render JavaScript</span><span className="block text-xs text-ink-500">For single-page apps. {!data.plan_limits.js_rendering && "Available on Pro and Agency."}</span></span>
              </label>
              {canEdit && (
                <Button variant="secondary" busy={act.busy} className="w-full" onClick={() => act.run(async () => {
                  await patch(path, { schedule, crawl_settings: { max_pages: maxPages || undefined, render_js: renderJs } });
                  setSaved(true); setTimeout(() => setSaved(false), 2500);
                  reload();
                })}>{saved ? "Saved ✓" : "Save settings"}</Button>
              )}
              {data.next_scheduled_at && <p className="text-xs text-ink-500">Next scheduled audit: {fmtDate(data.next_scheduled_at)}</p>}
            </div>
          </Card>
          <Card title="Publishing" icon={Plug}>
            {publishing.length ? (
              <div className="space-y-3">
                {publishing.map((i: any) => (
                  <div key={i.id} className="flex items-center gap-3">
                    <ProviderMark provider={i.provider} size="sm" />
                    <div className="min-w-0 flex-1 text-sm"><div className="font-medium text-ink-900">{providerLabel(i.provider)}</div><div className="truncate text-xs text-ink-500">{i.external_account}</div></div>
                    <StatusBadge s={i.status} />
                  </div>
                ))}
              </div>
            ) : <p className="text-sm text-ink-500">Not connected. Fixes can still be copied or exported.</p>}
            <Link href={`/app/${orgId}/integrations`} className="mt-4 inline-flex items-center gap-1 text-sm font-medium no-underline">Manage integrations <ArrowRight className="h-4 w-4" /></Link>
          </Card>
          <Card title="Shortcuts">
            <div className="space-y-1">
              <Link href={`/app/${orgId}/keywords?website=${data.id}`} className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm font-medium text-ink-700 no-underline hover:bg-ink-50"><KeyRound className="h-4 w-4 text-ink-400" /> Keyword opportunities</Link>
              <Link href={`/app/${orgId}/fixes?website=${data.id}`} className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm font-medium text-ink-700 no-underline hover:bg-ink-50"><Wand2 className="h-4 w-4 text-ink-400" /> Fixes for this site</Link>
            </div>
            {hasRole(role, "admin") && (
              <div className="mt-4 border-t border-ink-100 pt-4">
                <Button variant="ghost" size="sm" icon={Trash2} className="text-rose-600 hover:bg-rose-50 hover:text-rose-700" onClick={() => act.run(async () => {
                  if (!confirm("Delete this website and all its audits, fixes and credentials? This cannot be undone.")) return;
                  await del(path);
                  router.push(`/app/${orgId}/websites`);
                })}>Delete website & data</Button>
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
