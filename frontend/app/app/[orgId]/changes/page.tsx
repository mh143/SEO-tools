"use client";
import Link from "next/link";
import { Card, Empty, ErrorState, fmtDate, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

export default function Changes() {
  const { orgId } = useSession();
  const { data, error, loading, reload } = useApi<any[]>(`/orgs/${orgId}/changes`);
  return (
    <>
      <PageHeader title="Change history" subtitle="Every fix state change, with who did it and when." />
      {loading && <Loading />}
      <ErrorState error={error} onRetry={reload} />
      {data && data.length === 0 && <Empty title="No changes yet" />}
      {data && data.length > 0 && (
        <Card>
          <table className="w-full text-sm"><thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-2">When</th><th>Fix</th><th>Change</th><th>Message</th><th>Actor</th></tr></thead>
            <tbody>{data.map((c) => (
              <tr key={c.id} className="border-t border-slate-100 align-top">
                <td className="whitespace-nowrap py-2 text-xs">{fmtDate(c.created_at)}</td>
                <td><Link href={`/app/${orgId}/fixes/${c.fix_id}`}>{c.fix_type}</Link><div className="max-w-xs break-all text-xs text-slate-500">{c.url}</div></td>
                <td className="whitespace-nowrap">{c.from_status ? <><StatusBadge s={c.from_status} /> → </> : null}<StatusBadge s={c.to_status} /></td>
                <td className="text-slate-600">{c.message}</td><td className="text-xs text-slate-500">{c.actor_user_id ? "user" : "system"}</td>
              </tr>))}</tbody></table>
        </Card>
      )}
    </>
  );
}
