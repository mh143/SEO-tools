"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Card, Empty, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

const GROUPS: Record<string, string> = {
  "": "All", "drafted,analyzed": "Drafts", awaiting_approval: "Awaiting approval", approved: "Approved",
  "applying,verifying,externally_applied_unverified": "In progress", verified: "Verified", "failed,rejected,rolled_back": "Failed / rejected / rolled back",
};

export default function FixQueue() {
  const { orgId } = useSession();
  const website = useSearchParams().get("website");
  const [status, setStatus] = useState("");
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  if (website) qs.set("website_id", website);
  const { data, error, loading, reload } = useApi<any[]>(`/orgs/${orgId}/fixes?${qs}`);
  return (
    <>
      <PageHeader title="Fix queue" subtitle="Draft → approve → publish (or apply yourself) → verified on the live site."
        actions={<><a className="text-sm" href={`/api/orgs/${orgId}/fixes-export?format=json${website ? `&website_id=${website}` : ""}`}>Export JSON</a>
          <a className="text-sm" href={`/api/orgs/${orgId}/fixes-export?format=csv${website ? `&website_id=${website}` : ""}`}>Export CSV</a></>} />
      <div className="mb-4 flex flex-wrap gap-2">
        {Object.entries(GROUPS).map(([k, v]) => (
          <button key={k} onClick={() => setStatus(k)} className={`rounded-full border px-3 py-1 text-sm ${status === k ? "border-brand-500 bg-brand-50 text-brand-700" : "border-ink-300 bg-white"}`}>{v}</button>
        ))}
      </div>
      {loading && <Loading />}
      <ErrorState error={error} onRetry={reload} />
      {data && data.length === 0 && <Empty title="No fixes here">Open a finding from an audit and click “Generate fix”.</Empty>}
      {data && data.length > 0 && (
        <Card>
          <table className="table-clean">
            <thead><tr><th>Fix</th><th>URL</th><th>Status</th><th>Publishing</th><th>Updated</th></tr></thead>
            <tbody>{data.map((f) => (
              <tr key={f.id}>
                <td><Link href={`/app/${orgId}/fixes/${f.id}`}>{f.fix_type.replace(/_/g, " ")}</Link><div className="text-xs text-ink-500">{f.generator} · risk {f.risk_level}</div></td>
                <td className="max-w-xs break-all text-ink-600">{f.url}</td><td><StatusBadge s={f.status} /></td>
                <td className="text-xs">{f.direct_apply_supported ? "direct" : "manual / export"}</td>
                <td className="text-xs text-ink-500">{new Date(f.updated_at).toLocaleString()}</td>
              </tr>))}</tbody>
          </table>
        </Card>
      )}
    </>
  );
}
