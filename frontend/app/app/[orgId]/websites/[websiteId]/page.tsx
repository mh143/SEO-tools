"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, Empty, ErrorState, Field, fmtDate, Loading, Notice, PageHeader, StatusBadge, useAction } from "@/components/ui";
import { del, patch, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

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
  const canEdit = hasRole(role, "editor");

  return (
    <>
      <PageHeader title={data.name} subtitle={data.root_url} back={{ href: `/app/${orgId}/websites`, label: "Websites" }}
        actions={canEdit && (
          <Button testId="start-crawl" busy={act.busy} disabled={!!running}
            onClick={() => act.run(async () => { const r = await post(`${path}/crawls`, {}); router.push(`/app/${orgId}/crawls/${r.id}`); })}>
            {running ? "Audit running…" : "Run audit"}
          </Button>
        )} />
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Audit history">
            {data.crawls.length === 0 ? <Empty title="No audits yet">Run the first audit to see results.</Empty> : (
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-2">Started</th><th>Status</th><th>Trigger</th><th>Pages</th><th>Issues</th><th>Δ</th></tr></thead>
                <tbody>
                  {data.crawls.map((c: any) => (
                    <tr key={c.id} className="border-t border-slate-100">
                      <td className="py-2"><Link href={`/app/${orgId}/crawls/${c.id}`}>{fmtDate(c.created_at)}</Link></td>
                      <td><StatusBadge s={c.status} /></td><td>{c.trigger}</td><td>{c.pages_crawled}</td>
                      <td>{c.summary?.issue_count ?? "–"}</td>
                      <td className="text-xs text-slate-500">{c.summary?.diff?.has_previous ? `+${c.summary.diff.new} / −${c.summary.diff.resolved}${c.summary.diff.regressed ? ` / ${c.summary.diff.regressed} regressed` : ""}` : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Monitoring & crawl settings">
            <div className="space-y-3">
              <Field label="Scheduled audits" hint={`Your plan allows: ${data.plan_limits.schedules.join(", ")}`}>
                <select className="input" value={schedule} onChange={(e) => setSchedule(e.target.value)} disabled={!canEdit} name="schedule">
                  {["none", "monthly", "weekly", "daily"].map((s) => <option key={s} value={s} disabled={!data.plan_limits.schedules.includes(s)}>{s}</option>)}
                </select>
              </Field>
              <Field label="Max pages per audit" hint={`Plan limit: ${data.plan_limits.max_pages}`}>
                <input className="input" type="number" min={1} max={data.plan_limits.max_pages} value={maxPages}
                  onChange={(e) => setMaxPages(e.target.value ? Number(e.target.value) : "")} disabled={!canEdit} />
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={renderJs} disabled={!canEdit || !data.plan_limits.js_rendering} onChange={(e) => setRenderJs(e.target.checked)} />
                Render JavaScript pages {!data.plan_limits.js_rendering && <span className="text-xs text-slate-500">(Pro plan)</span>}
              </label>
              {canEdit && (
                <Button variant="secondary" busy={act.busy} onClick={() => act.run(async () => {
                  await patch(path, { schedule, crawl_settings: { max_pages: maxPages || undefined, render_js: renderJs } });
                  reload();
                })}>Save settings</Button>
              )}
              {data.next_scheduled_at && <p className="text-xs text-slate-500">Next scheduled audit: {fmtDate(data.next_scheduled_at)}</p>}
            </div>
          </Card>
          <Card title="Publishing integration">
            {data.integrations.filter((i: any) => i.status === "connected").length ? (
              data.integrations.filter((i: any) => i.status === "connected").map((i: any) => (
                <div key={i.id} className="text-sm"><StatusBadge s={i.status} /> {i.provider} · {i.external_account}</div>
              ))
            ) : <p className="text-sm text-slate-500">Not connected. Fixes can still be copied or exported.</p>}
            <Link href={`/app/${orgId}/integrations`} className="mt-2 block text-sm">Manage integrations →</Link>
          </Card>
          <Card title="More">
            <div className="space-y-1 text-sm">
              <Link href={`/app/${orgId}/keywords?website=${data.id}`} className="block">Keyword opportunities →</Link>
              <Link href={`/app/${orgId}/fixes?website=${data.id}`} className="block">Fixes for this site →</Link>
            </div>
            {hasRole(role, "admin") && (
              <div className="mt-4 border-t pt-4">
                <Button variant="danger" size="sm" onClick={() => act.run(async () => {
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
