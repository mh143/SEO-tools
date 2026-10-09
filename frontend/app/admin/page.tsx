"use client";
import Link from "next/link";
import { useState } from "react";
import { Button, Card, ErrorState, Loading, PageHeader, StatusBadge, Tabs } from "@/components/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export default function Admin() {
  const { data, error, loading } = useApi<any>("/admin/overview");
  const [tab, setTab] = useState("orgs");
  if (loading) return <Loading />;
  if (error) return <div className="p-8"><ErrorState error={error.status === 404 ? "Not found." : error} /></div>;
  return (
    <main className="mx-auto max-w-6xl p-6">
      <PageHeader title="Platform admin" back={{ href: "/app", label: "App" }} />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        {[["Users", data.users], ["Organizations", data.organizations], ["Websites", data.websites], ["Running crawls", data.running_crawls], ["Failed webhooks", data.failed_webhooks]].map(([k, v]) => (
          <div key={k as string} className="rounded-lg border bg-white p-4"><div className="text-xs uppercase text-slate-500">{k}</div><div className="text-2xl font-semibold">{v}</div></div>))}
      </div>
      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <Card title="Crawls (24h)"><ul className="text-sm">{Object.entries(data.crawls_24h).map(([k, v]) => <li key={k} className="flex justify-between"><StatusBadge s={k} />{v as number}</li>)}</ul><p className="mt-2 text-xs text-slate-500">Public audits (24h): {data.public_audits_24h}</p></Card>
        <Card title="Subscriptions"><ul className="text-sm">{data.subscriptions.map((s: any, i: number) => <li key={i} className="flex justify-between"><span>{s.plan_key} · {s.status}{s.simulated ? " (sim)" : ""}</span>{s.count}</li>)}</ul></Card>
        <Card title="Usage this month"><ul className="text-sm">{Object.entries(data.usage_this_month).map(([k, v]) => <li key={k} className="flex justify-between"><span>{k}</span>{v as number}</li>)}</ul></Card>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[{ key: "orgs", label: "Organizations" }, { key: "users", label: "Users" }, { key: "crawls", label: "Failed crawls" }, { key: "webhooks", label: "Webhooks" }, { key: "audit", label: "Audit log" }]} />
      {tab === "orgs" && <Table path="/admin/organizations" cols={["name", "plan_key", "subscription_status", "members", "websites", "created_at"]} />}
      {tab === "users" && <Users />}
      {tab === "crawls" && <Table path="/admin/crawls?status=failed" cols={["start_url", "status", "trigger", "error", "created_at"]} />}
      {tab === "webhooks" && <Table path="/admin/webhooks" cols={["id", "type", "status", "error", "received_at"]} />}
      {tab === "audit" && <Table path="/admin/audit-logs" cols={["action", "org_id", "actor_user_id", "ip", "created_at"]} />}
    </main>
  );
}

function Table({ path, cols }: { path: string; cols: string[] }) {
  const { data, error, loading } = useApi<any[]>(path);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} />;
  return (
    <Card><div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="text-left uppercase text-slate-500">{cols.map((c) => <th key={c} className="py-2 pr-3">{c}</th>)}</tr></thead>
      <tbody>{data!.map((r, i) => <tr key={i} className="border-t border-slate-100">{cols.map((c) => <td key={c} className="max-w-xs break-all py-1.5 pr-3">{String(r[c] ?? "–")}</td>)}</tr>)}</tbody></table></div></Card>
  );
}

function Users() {
  const { data, reload } = useApi<any[]>("/admin/users");
  return (
    <Card><table className="w-full text-sm"><tbody>{data?.map((u) => (
      <tr key={u.id} className="border-t border-slate-100"><td className="py-1.5">{u.email}{u.is_platform_admin && " (admin)"}</td><td>{u.is_active ? "active" : "deactivated"}</td>
        <td className="text-right"><Button size="sm" variant="secondary" onClick={async () => { await post(`/admin/users/${u.id}/active?active=${!u.is_active}`); reload(); }}>{u.is_active ? "Deactivate" : "Reactivate"}</Button></td></tr>))}</tbody></table>
      <p className="mt-2 text-xs text-slate-500"><Link href="/app">Back to app</Link></p></Card>
  );
}
