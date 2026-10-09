"use client";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Field, fmtDate, Loading, Notice, PageHeader, StatusBadge, useAction } from "@/components/ui";
import { del, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

export default function Integrations() {
  const { orgId, role } = useSession();
  const result = useSearchParams().get("result");
  const { data, error, loading, reload } = useApi<any[]>(`/orgs/${orgId}/integrations`);
  const { data: sites } = useApi<any[]>(`/orgs/${orgId}/websites`);
  const { data: providers } = useApi<any[]>(`/integrations/providers`);
  const [websiteId, setWebsiteId] = useState("");
  const [username, setUsername] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const act = useAction();
  const isAdmin = hasRole(role, "admin");
  const site = websiteId || sites?.[0]?.id || "";

  return (
    <>
      <PageHeader title="Integrations" subtitle="Connect a site through its official authorization flow to publish approved fixes. No plugin required." />
      {result === "connected" && <div className="mb-4"><Notice kind="success">WordPress connected.</Notice></div>}
      {result === "rejected" && <div className="mb-4"><Notice kind="warning">Authorization was declined on the WordPress site.</Notice></div>}
      {result === "error" && <div className="mb-4"><Notice kind="error">The connection could not be completed. See the integration error below.</Notice></div>}
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {loading && <Loading />}
          <ErrorState error={error} onRetry={reload} />
          {data && data.length === 0 && <Empty title="No integrations yet">Connect WordPress to publish fixes directly. Without an integration you can still copy and export every fix.</Empty>}
          {data?.map((i) => (
            <Card key={i.id} title={<span className="flex items-center gap-2">{i.display_name || i.provider} <StatusBadge s={i.status} /></span>}
              actions={isAdmin && i.status === "connected" && <>
                <Button size="sm" variant="secondary" onClick={() => act.run(async () => { await post(`/orgs/${orgId}/integrations/${i.id}/refresh`); reload(); })}>Re-check</Button>
                <Button size="sm" variant="danger" onClick={() => act.run(async () => { if (confirm("Disconnect and delete stored credentials?")) { await del(`/orgs/${orgId}/integrations/${i.id}`); reload(); } })}>Disconnect</Button>
              </>}>
              <div className="text-sm text-slate-600">{i.provider} · {i.external_site_url} · account {i.external_account || "–"} · checked {fmtDate(i.last_verified_at)}</div>
              {i.error_message && <div className="mt-2"><Notice kind="error">{i.error_message}</Notice></div>}
              {i.status === "connected" && (
                <table className="mt-3 w-full text-sm"><thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-1">Operation</th><th>Supported</th><th>Rollback</th><th>Notes</th></tr></thead>
                  <tbody>{Object.entries(i.capabilities).filter(([k]) => !k.startsWith("_")).map(([k, c]: [string, any]) => (
                    <tr key={k} className="border-t align-top"><td className="py-1 mono text-xs">{k}</td><td>{c.supported ? <Badge tone="bg-emerald-100 text-emerald-800">yes</Badge> : <Badge>no</Badge>}</td>
                      <td>{c.rollback ? "yes" : "–"}</td><td className="text-xs text-slate-500">{c.supported ? c.notes : c.reason}</td></tr>))}</tbody></table>
              )}
            </Card>
          ))}
        </div>
        <div className="space-y-4">
          {isAdmin && sites && sites.length > 0 && (
            <Card title="Connect WordPress">
              <div className="space-y-3">
                <Field label="Website"><select className="input" value={site} onChange={(e) => setWebsiteId(e.target.value)}>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
                <Button busy={act.busy} onClick={() => act.run(async () => {
                  const r = await post<any>(`/orgs/${orgId}/integrations/wordpress/start`, { website_id: site });
                  window.location.href = r.authorization_url;
                })}>Authorize with WordPress</Button>
                <p className="text-xs text-slate-500">You will approve access on your own WordPress site (WordPress 5.6+, HTTPS). We store an application password encrypted; you can revoke it any time in WordPress.</p>
                <details className="text-sm">
                  <summary className="cursor-pointer text-slate-700">Or paste an application password</summary>
                  <div className="mt-2 space-y-2">
                    <Field label="WordPress username"><input className="input" value={username} onChange={(e) => setUsername(e.target.value)} /></Field>
                    <Field label="Application password" hint="Create one under Users → Profile → Application Passwords."><input className="input" type="password" value={appPassword} onChange={(e) => setAppPassword(e.target.value)} autoComplete="off" /></Field>
                    <Button variant="secondary" busy={act.busy} onClick={() => act.run(async () => {
                      await post(`/orgs/${orgId}/integrations/wordpress/manual`, { website_id: site, username, application_password: appPassword });
                      setAppPassword(""); reload();
                    })}>Connect</Button>
                  </div>
                </details>
              </div>
            </Card>
          )}
          <Card title="Platforms">
            <ul className="space-y-2 text-sm">{providers?.map((p) => (
              <li key={p.provider} className="flex justify-between gap-2"><span>{p.name}</span>{p.status === "available" ? <Badge tone="bg-emerald-100 text-emerald-800">available</Badge> : <Badge>not yet implemented</Badge>}</li>))}</ul>
            <p className="mt-3 text-xs text-slate-500">WordPress core cannot edit meta descriptions, canonicals, redirects or head structured data without a plugin; those fixes are provided for copy/export instead.</p>
          </Card>
        </div>
      </div>
    </>
  );
}
