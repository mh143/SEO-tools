"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge, Button, Card, ErrorState, JsonBlock, Loading, Notice, PageHeader, SeverityBadge, StatusBadge, TypeBadge, useAction } from "@/components/ui";
import { patch, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

export default function IssueDetail({ params }: { params: { issueId: string } }) {
  const { orgId, role } = useSession();
  const router = useRouter();
  const path = `/orgs/${orgId}/issues/${params.issueId}`;
  const { data: i, error, loading, reload } = useApi<any>(path);
  const act = useAction();
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const fs = i.fix_support;

  return (
    <>
      <PageHeader title={i.title} back={{ href: `/app/${orgId}/crawls/${i.crawl_run_id}`, label: "Audit results" }}
        subtitle={<span className="flex flex-wrap items-center gap-2"><SeverityBadge s={i.severity} /><TypeBadge t={i.finding_type} />
          <Badge>{i.category}</Badge><Badge>confidence: {i.confidence}</Badge><StatusBadge s={i.status} /><span className="mono text-xs">{i.rule_id}</span></span>}
        actions={hasRole(role, "editor") && (i.status === "ignored"
          ? <Button variant="secondary" onClick={() => act.run(async () => { await patch(path, { status: "open" }); reload(); })}>Reopen</Button>
          : <Button variant="secondary" onClick={() => act.run(async () => { await patch(path, { status: "ignored" }); reload(); })}>Ignore</Button>)} />
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="What we found">
            <p className="break-all text-sm text-slate-500">{i.url || "Site-wide"}{i.page && <> · <Link href={`/app/${orgId}/pages/${i.page.id}`}>page details</Link></>}</p>
            <p className="mt-2">{i.description}</p>
            <h3 className="mt-4 text-sm font-semibold">Why it matters</h3><p className="text-sm text-slate-700">{i.why_it_matters}</p>
            <h3 className="mt-4 text-sm font-semibold">Recommendation</h3><p className="text-sm text-slate-700">{i.recommendation}</p>
          </Card>
          <Card title="Evidence"><JsonBlock value={i.evidence} /></Card>
          <Card title="History across audits">
            <ul className="space-y-1 text-sm">{i.history.map((h: any) => (
              <li key={h.issue_id} className="flex justify-between"><Link href={`/app/${orgId}/crawls/${h.crawl_run_id}`}>{new Date(h.crawled_at).toLocaleString()}</Link><StatusBadge s={h.status} /></li>))}</ul>
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Fix">
            {!fs.fix_type ? <p className="text-sm text-slate-600">{fs.reason}</p> : (
              <div className="space-y-3 text-sm">
                <div><b>{fs.label}</b> · {fs.generator === "ai" ? "AI-drafted" : fs.generator === "rule" ? "rule-based" : "advisory"} · risk {fs.risk}</div>
                {fs.ai?.warning && fs.generator === "ai" && <Notice kind="warning">{fs.ai.warning}</Notice>}
                {fs.direct_apply && (fs.direct_apply.supported
                  ? <Notice kind="success">Can be published directly via {fs.direct_apply.provider} after approval.{fs.direct_apply.notes ? ` ${fs.direct_apply.notes}` : ""}</Notice>
                  : <Notice kind="info">Direct publishing: not available. {fs.direct_apply.reason}</Notice>)}
                {!fs.available && <Notice kind="warning">{fs.reason}</Notice>}
                {hasRole(role, "editor") && fs.available && (
                  <Button testId="generate-fix" busy={act.busy} onClick={() => act.run(async () => {
                    const f = await post<any>(`${path}/fixes`);
                    router.push(`/app/${orgId}/fixes/${f.id}`);
                  })}>Generate fix</Button>
                )}
              </div>
            )}
          </Card>
          {i.fixes.length > 0 && (
            <Card title="Fixes for this finding">
              <ul className="space-y-2 text-sm">{i.fixes.map((f: any) => (
                <li key={f.id} className="flex items-center justify-between gap-2"><Link href={`/app/${orgId}/fixes/${f.id}`}>{f.fix_type} · {new Date(f.created_at).toLocaleDateString()}</Link><StatusBadge s={f.status} /></li>))}</ul>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
