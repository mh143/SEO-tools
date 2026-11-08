"use client";
import Link from "next/link";
import { ArrowRight, Bell, CheckCircle2, Globe, Plus, ShieldCheck, Wand2, AlertTriangle } from "lucide-react";
import {
  Button, ButtonLink, Card, Empty, ErrorState, Loading, Meter, PageHeader, ScoreRing, StatCard, StatusBadge, timeAgo,
} from "@/components/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

const SCORE_KEYS = [["technical", "Technical"], ["content", "Content"], ["aeo", "AEO"], ["geo", "GEO"]] as const;
const PIPE = ["drafted", "awaiting_approval", "approved", "verifying", "verified", "failed"];

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function Overview() {
  const { orgId, me } = useSession();
  const { data, error, loading, reload } = useApi<any>(`/orgs/${orgId}/overview`);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const m = data.usage.metrics;
  const unread = data.notifications.filter((n: any) => !n.read);
  const fixes: Record<string, number> = data.fixes || {};
  const totalFixes = Object.values(fixes).reduce((a, b) => a + (b as number), 0);
  const audited = data.websites.filter((w: any) => w.last_crawl?.summary?.scores);
  const avg = (k: string) => audited.length ? Math.round(audited.reduce((a: number, w: any) => a + (w.last_crawl.summary.scores[k] || 0), 0) / audited.length) : null;
  const openIssues = data.websites.reduce((a: number, w: any) => a + (w.last_crawl?.summary?.issue_count || 0), 0);

  return (
    <>
      <PageHeader eyebrow={data.org.name} title={`${greeting()}, ${(me.name || me.email.split("@")[0]).split(" ")[0]}`}
        subtitle={`Here’s what’s happening across your websites · ${data.usage.plan.name} plan`}
        actions={<ButtonLink href={`/app/${orgId}/websites`} icon={Plus}>Add website</ButtonLink>} />

      {unread.length > 0 && (
        <Card className="mb-6 border-amber-200 bg-amber-50/40" icon={Bell} title={`Alerts (${unread.length})`}
          actions={<Button size="sm" variant="secondary" onClick={async () => { await post(`/orgs/${orgId}/notifications/read`); reload(); }}>Mark all read</Button>}>
          <ul className="space-y-2 text-sm">
            {unread.map((n: any) => (
              <li key={n.id} className="flex gap-3 rounded-xl border border-amber-200 bg-white p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                <div className="min-w-0 flex-1"><div className="font-medium text-ink-900">{n.title}</div>{n.body && <div className="text-ink-600">{n.body}</div>}</div>
                <span className="shrink-0 text-xs text-ink-400">{timeAgo(n.created_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <StatCard label="Websites" value={data.websites.length} icon={Globe} hint={m.websites.limit !== null ? `${m.websites.limit} on your plan` : undefined} />
        <StatCard label="Average technical score" value={avg("technical") ?? "–"} icon={ShieldCheck} tone="emerald" hint={audited.length ? `Across ${audited.length} audited site${audited.length > 1 ? "s" : ""}` : "Run an audit to see scores"} />
        <StatCard label="Findings in latest audits" value={openIssues.toLocaleString()} icon={AlertTriangle} tone="amber" hint="Errors, warnings & recommendations" />
        <StatCard label="Fixes verified" value={fixes.verified || 0} icon={CheckCircle2} tone="sky" hint={`${totalFixes} fixes in total`} />
      </div>

      <div className="mt-8 grid gap-6 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-ink-900">Your websites</h2>
            <Link href={`/app/${orgId}/websites`} className="inline-flex items-center gap-1 text-sm font-medium no-underline">View all <ArrowRight className="h-4 w-4" /></Link>
          </div>
          {data.websites.length === 0 && (
            <Empty icon={Globe} title="Add your first website" action={<ButtonLink href={`/app/${orgId}/websites`} icon={Plus}>Add website</ButtonLink>}>
              Add a website to run your first audit. It takes about a minute for small sites.
            </Empty>
          )}
          {data.websites.map((w: any) => (
            <Card key={w.id} className="transition hover:shadow-lift">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-ink-100 text-ink-600"><Globe className="h-5 w-5" /></span>
                  <div className="min-w-0">
                    <Link href={`/app/${orgId}/websites/${w.id}`} className="font-semibold text-ink-900 no-underline hover:text-brand-700">{w.name}</Link>
                    <div className="truncate text-sm text-ink-500">{w.root_url}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {w.schedule !== "none" && <span className="rounded-full bg-ink-100 px-2 py-0.5 text-xs font-medium capitalize text-ink-600">{w.schedule}</span>}
                  {w.last_crawl && <StatusBadge s={w.last_crawl.status} />}
                </div>
              </div>
              {w.last_crawl?.summary?.scores ? (
                <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {SCORE_KEYS.map(([k, l]) => (
                    <div key={k} className="flex items-center gap-3 rounded-xl bg-ink-50/80 p-3">
                      <ScoreRing value={w.last_crawl.summary.scores[k]} size={44} stroke={5} label={l} />
                      <span className="text-xs font-semibold uppercase tracking-wider text-ink-500">{l}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="mt-4 rounded-xl bg-ink-50/80 p-3 text-sm text-ink-500">No completed audit yet.</p>}
              {w.last_crawl && (
                <div className="mt-4 flex items-center justify-between border-t border-ink-100 pt-4 text-sm">
                  <span className="text-ink-500">Last audit {timeAgo(w.last_crawl.created_at)}</span>
                  <Link href={`/app/${orgId}/crawls/${w.last_crawl.id}`} className="inline-flex items-center gap-1 font-medium no-underline">View latest audit <ArrowRight className="h-4 w-4" /></Link>
                </div>
              )}
            </Card>
          ))}
        </div>

        <div className="space-y-6">
          <Card title="Fix pipeline" icon={Wand2} subtitle="From draft to verified on your live site">
            {totalFixes === 0 ? <p className="text-sm text-ink-500">No fixes yet. Open a finding in an audit to generate one.</p> : (
              <div className="space-y-2.5">
                {PIPE.filter((k) => fixes[k]).concat(Object.keys(fixes).filter((k) => !PIPE.includes(k))).map((k) => (
                  <div key={k} className="flex items-center gap-3">
                    <div className="w-36 shrink-0"><StatusBadge s={k} /></div>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-100">
                      <div className="h-full rounded-full bg-brand-500" style={{ width: `${(fixes[k] / totalFixes) * 100}%` }} />
                    </div>
                    <span className="w-8 text-right text-sm font-semibold tabular-nums text-ink-900">{fixes[k]}</span>
                  </div>
                ))}
              </div>
            )}
            <Link href={`/app/${orgId}/fixes`} className="mt-5 inline-flex items-center gap-1 text-sm font-medium no-underline">Open fix queue <ArrowRight className="h-4 w-4" /></Link>
          </Card>
          <Card title="Usage this period" subtitle={`${data.usage.plan.name} plan`}>
            <div className="space-y-4">
              <Meter label="Websites" used={m.websites.used} limit={m.websites.limit} />
              <Meter label="Audits" used={m.crawl_runs.used} limit={m.crawl_runs.limit} />
              <Meter label="Pages crawled" used={m.crawled_pages.used} limit={null} />
              <Meter label="AI requests" used={m.ai_requests.used} limit={m.ai_requests.limit} />
              <Meter label="Publishing operations" used={m.publish_ops.used} limit={m.publish_ops.limit} />
            </div>
            <Link href={`/app/${orgId}/billing`} className="mt-5 inline-flex items-center gap-1 text-sm font-medium no-underline">Billing & usage <ArrowRight className="h-4 w-4" /></Link>
          </Card>
        </div>
      </div>
    </>
  );
}
