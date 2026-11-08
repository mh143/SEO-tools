"use client";
import { Fragment } from "react";
import { Card, ErrorState, JsonBlock, Loading, PageHeader } from "@/components/ui";
import { IssueList } from "@/components/IssueList";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

export default function PageDetail({ params }: { params: { pageId: string } }) {
  const { orgId } = useSession();
  const { data: p, error, loading, reload } = useApi<any>(`/orgs/${orgId}/pages/${params.pageId}`);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const ex = p.extracted || {};
  const rows: [string, any][] = [["Status", p.status_code], ["Final URL", p.final_url], ["Title", p.title], ["Meta description", p.meta_description],
    ["Canonical", p.canonical], ["H1", p.h1], ["Words", p.word_count], ["Indexable", String(p.indexable)], ["In sitemap", String(p.in_sitemap)],
    ["Internal links in", p.inbound_links], ["Response time", p.response_time_ms ? `${p.response_time_ms} ms` : "–"], ["Rendered with JS", String(p.rendered)],
    ["Schema types", (ex.schema_types || []).join(", ")], ["Language", ex.lang]];
  return (
    <>
      <PageHeader title={<span className="break-all">{p.url}</span>} back={{ href: `/app/${orgId}`, label: "Overview" }} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Page facts">
          <dl className="grid grid-cols-[140px_1fr] gap-x-3 gap-y-1 text-sm">
            {rows.map(([k, v]) => (<Fragment key={k}><dt className="text-ink-500">{k}</dt><dd className="break-all">{v ?? "–"}</dd></Fragment>))}
          </dl>
          {p.snapshot.available && <a className="mt-3 block text-sm" href={`/api/orgs/${orgId}/pages/${p.id}/snapshot`} target="_blank" rel="noreferrer">View stored HTML snapshot (JSON)</a>}
        </Card>
        <Card title={`Findings on this page (${p.issues.length})`}>
          <IssueList issues={p.issues} hrefFor={(i) => `/app/${orgId}/issues/${i.id}`} />
        </Card>
        <Card title="Headings"><ul className="space-y-1 text-sm">{(ex.headings || []).map((h: any, idx: number) => <li key={idx} style={{ paddingLeft: (h.level - 1) * 12 }}><span className="text-xs text-ink-400">H{h.level}</span> {h.text}</li>)}</ul></Card>
        <Card title="Structured data"><JsonBlock value={ex.json_ld || []} /></Card>
      </div>
    </>
  );
}
