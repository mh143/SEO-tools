"use client";
import Link from "next/link";
import { Card, Empty, ErrorState, fmtDate, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

export default function Reports() {
  const { orgId } = useSession();
  const { data, error, loading, reload } = useApi<any>(`/orgs/${orgId}/overview`);
  return (
    <>
      <PageHeader title="Reports" subtitle="Download audit reports (printable HTML → PDF via your browser), CSV, JSON or Markdown. Agency plans use your company name." />
      {loading && <Loading />}
      <ErrorState error={error} onRetry={reload} />
      {data && data.websites.length === 0 && <Empty title="No reports yet">Run an audit to generate a report.</Empty>}
      {data?.websites.map((w: any) => <SiteReports key={w.id} orgId={orgId} website={w} />)}
    </>
  );
}

function SiteReports({ orgId, website }: { orgId: string; website: any }) {
  const { data } = useApi<any[]>(`/orgs/${orgId}/websites/${website.id}/crawls`);
  const done = (data || []).filter((c) => ["completed", "partial"].includes(c.status));
  return (
    <Card title={website.name} className="mb-4">
      {!data ? <Loading /> : done.length === 0 ? <p className="text-sm text-slate-500">No completed audits.</p> : (
        <table className="w-full text-sm"><tbody>{done.map((c) => (
          <tr key={c.id} className="border-t border-slate-100"><td className="py-2"><Link href={`/app/${orgId}/crawls/${c.id}`}>{fmtDate(c.created_at)}</Link></td><td><StatusBadge s={c.status} /></td>
            <td className="space-x-3 text-right">{["html", "csv", "json", "md"].map((f) => <a key={f} href={`/api/orgs/${orgId}/crawls/${c.id}/export?format=${f}`}>{f.toUpperCase()}</a>)}</td></tr>))}</tbody></table>
      )}
    </Card>
  );
}
