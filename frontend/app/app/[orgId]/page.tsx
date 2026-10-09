"use client";
import Link from "next/link";
import { Button, Card, Empty, ErrorState, fmtDate, Loading, PageHeader, ScoreTile, StatusBadge } from "@/components/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

function Meter({ label, used, limit }: { label: string; used: number; limit: number | null }) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-600"><span>{label}</span><span>{used}{limit !== null ? ` / ${limit}` : ""}</span></div>
      {limit !== null && <div className="mt-1 h-1.5 rounded bg-slate-100"><div className={`h-1.5 rounded ${pct > 90 ? "bg-red-500" : "bg-brand-500"}`} style={{ width: `${pct}%` }} /></div>}
    </div>
  );
}

export default function Overview() {
  const { orgId } = useSession();
  const { data, error, loading, reload } = useApi<any>(`/orgs/${orgId}/overview`);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const m = data.usage.metrics;
  const unread = data.notifications.filter((n: any) => !n.read);
  return (
    <>
      <PageHeader title={data.org.name} subtitle={`${data.usage.plan.name} plan`}
        actions={<Link href={`/app/${orgId}/websites`} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white no-underline hover:no-underline">Add website</Link>} />
      {unread.length > 0 && (
        <Card className="mb-6" title={`Alerts (${unread.length})`} actions={<Button size="sm" variant="secondary" onClick={async () => { await post(`/orgs/${orgId}/notifications/read`); reload(); }}>Mark all read</Button>}>
          <ul className="space-y-2 text-sm">
            {unread.map((n: any) => (
              <li key={n.id} className="rounded border border-amber-200 bg-amber-50 p-2"><b>{n.title}</b>{n.body && <div className="text-slate-600">{n.body}</div>}<div className="text-xs text-slate-500">{fmtDate(n.created_at)}</div></li>
            ))}
          </ul>
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {data.websites.length === 0 && (
            <Empty title="No websites yet" action={<Link href={`/app/${orgId}/websites`}>Add your first website</Link>}>
              Add a website to run your first audit.
            </Empty>
          )}
          {data.websites.map((w: any) => (
            <Card key={w.id} title={<Link href={`/app/${orgId}/websites/${w.id}`}>{w.name}</Link>}
              actions={w.last_crawl && <StatusBadge s={w.last_crawl.status} />}>
              <div className="break-all text-sm text-slate-500">{w.root_url} · schedule: {w.schedule}</div>
              {w.last_crawl?.summary?.scores ? (
                <div className="mt-3 grid grid-cols-4 gap-2">
                  {["technical", "content", "aeo", "geo"].map((k) => <ScoreTile key={k} label={k} value={w.last_crawl.summary.scores[k]} />)}
                </div>
              ) : <p className="mt-3 text-sm text-slate-500">No completed audit yet.</p>}
              {w.last_crawl && <div className="mt-2 text-xs"><Link href={`/app/${orgId}/crawls/${w.last_crawl.id}`}>View latest audit ({fmtDate(w.last_crawl.created_at)})</Link></div>}
            </Card>
          ))}
        </div>
        <div className="space-y-4">
          <Card title="Fix pipeline">
            {Object.keys(data.fixes).length === 0 ? <p className="text-sm text-slate-500">No fixes yet. Open an issue to generate one.</p> : (
              <ul className="space-y-1 text-sm">{Object.entries(data.fixes).map(([k, v]) => <li key={k} className="flex justify-between"><StatusBadge s={k} /><span>{v as number}</span></li>)}</ul>
            )}
            <Link href={`/app/${orgId}/fixes`} className="mt-3 block text-sm">Open fix queue →</Link>
          </Card>
          <Card title="Usage this period">
            <div className="space-y-3">
              <Meter label="Websites" used={m.websites.used} limit={m.websites.limit} />
              <Meter label="Audits" used={m.crawl_runs.used} limit={m.crawl_runs.limit} />
              <Meter label="Pages crawled" used={m.crawled_pages.used} limit={null} />
              <Meter label="AI requests" used={m.ai_requests.used} limit={m.ai_requests.limit} />
              <Meter label="Publishing operations" used={m.publish_ops.used} limit={m.publish_ops.limit} />
            </div>
            <Link href={`/app/${orgId}/billing`} className="mt-3 block text-sm">Billing & usage →</Link>
          </Card>
        </div>
      </div>
    </>
  );
}
