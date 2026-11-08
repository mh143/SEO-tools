"use client";
import { useSearchParams } from "next/navigation";
import { Check, ExternalLink, Minus, RefreshCw, Unplug } from "lucide-react";
import { ReactNode, Suspense, useState } from "react";
import { ProviderMark, providerLabel } from "@/components/Providers";
import { Badge, Button, ButtonLink, Card, cx, ErrorState, Field, Loading, Modal, Notice, PageHeader, StatusBadge, timeAgo, useAction } from "@/components/ui";
import { del, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

const OP_LABEL: Record<string, string> = {
  set_title: "Titles & H1", set_meta_description: "Meta descriptions", set_image_alt: "Image alt text",
  content_insert_after_heading: "Answer below a heading", content_append: "Append FAQ / content",
  content_replace_href: "Update link targets", content_link_phrase: "Add internal links", add_json_ld: "Structured data (JSON-LD)",
  set_canonical: "Canonical tags", create_redirect: "Redirects", set_robots: "Robots directives",
};

function Steps({ items }: { items: ReactNode[] }) {
  return (
    <ol className="space-y-2 text-sm text-ink-600">
      {items.map((s, i) => (
        <li key={i} className="flex gap-3"><span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-50 text-[11px] font-semibold text-brand-700">{i + 1}</span><span>{s}</span></li>
      ))}
    </ol>
  );
}

function ConnectModal({ provider, sites, onClose, onDone }: { provider: string; sites: any[]; onClose: () => void; onDone: () => void }) {
  const { orgId } = useSession();
  const act = useAction();
  const [site, setSite] = useState(sites[0]?.id || "");
  const [f, setF] = useState<Record<string, string>>({});
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const done = () => { onDone(); onClose(); };

  const siteField = (
    <Field label="Website">
      <select className="input" value={site} onChange={(e) => setSite(e.target.value)}>{sites.map((s) => <option key={s.id} value={s.id}>{s.name} — {s.root_url}</option>)}</select>
    </Field>
  );

  let body: ReactNode = null;
  if (provider === "wordpress") body = (
    <div className="space-y-5">
      {siteField}
      <Button busy={act.busy} className="w-full" onClick={() => act.run(async () => {
        const r = await post<any>(`/orgs/${orgId}/integrations/wordpress/start`, { website_id: site });
        window.location.href = r.authorization_url;
      })}>Authorize with WordPress</Button>
      <p className="text-xs text-ink-500">You approve access on your own WordPress site (WordPress 5.6+ over HTTPS). We store an application password encrypted; revoke it any time in WordPress.</p>
      <details className="rounded-xl border border-ink-200/80 p-4 text-sm" open={!!f.username}>
        <summary className="cursor-pointer font-medium text-ink-800">Or paste an application password</summary>
        <div className="mt-4 space-y-3">
          <Field label="WordPress username"><input className="input" value={f.username || ""} onChange={set("username")} autoComplete="off" /></Field>
          <Field label="Application password" hint="Create one under Users → Profile → Application Passwords.">
            <input className="input" type="password" value={f.app || ""} onChange={set("app")} autoComplete="off" />
          </Field>
          <Button variant="secondary" busy={act.busy} onClick={() => act.run(async () => {
            await post(`/orgs/${orgId}/integrations/wordpress/manual`, { website_id: site, username: f.username, application_password: f.app });
            done();
          })}>Connect</Button>
        </div>
      </details>
    </div>
  );
  if (provider === "shopify") body = (
    <div className="space-y-5">
      <Steps items={[
        <>In Shopify admin, open <b>Settings → Apps and sales channels → Develop apps</b> and create an app.</>,
        <>Grant Admin API scopes <code className="mono text-xs">write_products</code>, <code className="mono text-xs">write_content</code> and (for redirects) <code className="mono text-xs">write_online_store_navigation</code>.</>,
        <>Install the app and copy the <b>Admin API access token</b> (starts with <code className="mono text-xs">shpat_</code>).</>,
      ]} />
      {siteField}
      <Field label="Store domain" hint="Your myshopify.com address — see Settings → Domains.">
        <input className="input" placeholder="your-store.myshopify.com" value={f.shop || ""} onChange={set("shop")} autoComplete="off" />
      </Field>
      <Field label="Admin API access token"><input className="input" type="password" placeholder="shpat_…" value={f.token || ""} onChange={set("token")} autoComplete="off" /></Field>
      <Button busy={act.busy} className="w-full" onClick={() => act.run(async () => {
        await post(`/orgs/${orgId}/integrations/shopify`, { website_id: site, shop: f.shop, access_token: f.token });
        done();
      })}>Connect Shopify store</Button>
    </div>
  );
  if (provider === "wix") body = (
    <div className="space-y-5">
      <Steps items={[
        <>Open the <b>API Keys Manager</b> in your Wix account settings and create a key.</>,
        <>Give it <b>Wix Blog</b> and/or <b>Wix Stores</b> permissions for this site.</>,
        <>Copy the key and your <b>Site ID</b> (from the dashboard URL: <code className="mono text-xs">/dashboard/&lt;site-id&gt;/</code>).</>,
      ]} />
      {siteField}
      <Field label="Site ID"><input className="input" placeholder="1a2b3c4d-…" value={f.site_id || ""} onChange={set("site_id")} autoComplete="off" /></Field>
      <Field label="API key"><input className="input" type="password" value={f.key || ""} onChange={set("key")} autoComplete="off" /></Field>
      <Button busy={act.busy} className="w-full" onClick={() => act.run(async () => {
        await post(`/orgs/${orgId}/integrations/wix`, { website_id: site, site_id: f.site_id, api_key: f.key });
        done();
      })}>Connect Wix site</Button>
    </div>
  );
  if (provider === "google_search_console") body = (
    <div className="space-y-5">
      <p className="text-sm text-ink-600">You’ll sign in with Google and grant <b>read-only</b> access to Search Console. We pick the verified property that matches the website (you can switch later).</p>
      {siteField}
      <Button busy={act.busy} className="w-full" onClick={() => act.run(async () => {
        const r = await post<any>(`/orgs/${orgId}/integrations/google/start`, { website_id: site });
        window.location.href = r.authorization_url;
      })}>Continue with Google</Button>
    </div>
  );

  return (
    <Modal open onClose={onClose} title={<span className="flex items-center gap-3"><ProviderMark provider={provider} size="sm" /> Connect {providerLabel(provider)}</span>}>
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      {body}
    </Modal>
  );
}

function IntegrationCard({ i, sites, isAdmin, reload }: { i: any; sites: any[]; isAdmin: boolean; reload: () => void }) {
  const { orgId } = useSession();
  const act = useAction();
  const site = sites.find((s) => s.id === i.website_id);
  const caps = Object.entries(i.capabilities || {})
    .filter(([k, v]) => !k.startsWith("_") && typeof v === "object" && v && "supported" in (v as any))
    .sort((a: any, b: any) => Number(b[1].supported) - Number(a[1].supported));
  const gsc = i.provider === "google_search_console";
  const run = act.run;
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <ProviderMark provider={i.provider} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-ink-900">{i.display_name || providerLabel(i.provider)}</h3><StatusBadge s={i.status} /></div>
            <div className="mt-0.5 truncate text-sm text-ink-500">{providerLabel(i.provider)} · {site?.name || "website"}{i.external_account ? ` · ${i.external_account}` : ""} · checked {timeAgo(i.last_verified_at)}</div>
          </div>
        </div>
        {isAdmin && i.status === "connected" && (
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" icon={RefreshCw} busy={act.busy} onClick={() => run(async () => { await post(`/orgs/${orgId}/integrations/${i.id}/refresh`); reload(); })}>Re-check</Button>
            <Button size="sm" variant="ghost" icon={Unplug} className="text-rose-600 hover:bg-rose-50 hover:text-rose-700" onClick={() => run(async () => { if (confirm("Disconnect and delete stored credentials?")) { await del(`/orgs/${orgId}/integrations/${i.id}`); reload(); } })}>Disconnect</Button>
          </div>
        )}
      </div>
      {i.error_message && <div className="mt-4"><Notice kind="error">{i.error_message}</Notice></div>}
      {act.error && <div className="mt-4"><Notice kind="error" onClose={() => act.setError(null)}>{act.error}</Notice></div>}
      {gsc && i.status === "connected" && (
        <div className="mt-5 max-w-md">
          <Field label="Search Console property" hint="Only verified properties that cover this website are listed.">
            <select className="input" value={i.external_site_url || ""} disabled={!isAdmin || act.busy}
              onChange={(e) => run(async () => { await post(`/orgs/${orgId}/integrations/${i.id}/property`, { property: e.target.value }); reload(); })}>
              {(i.capabilities?.properties || []).map((p: string) => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
        </div>
      )}
      {!gsc && i.status === "connected" && caps.length > 0 && (
        <div className="mt-5 overflow-x-auto rounded-xl border border-ink-100">
          <table className="table-clean">
            <thead><tr><th>What it can change</th><th className="text-center">Supported</th><th className="text-center">Rollback</th><th>Notes</th></tr></thead>
            <tbody>{caps.map(([k, c]: [string, any]) => (
              <tr key={k}>
                <td><div className="font-medium text-ink-800">{OP_LABEL[k] || k}</div><div className="mono text-[11px] text-ink-400">{k}</div></td>
                <td className="text-center">{c.supported ? <Check className="mx-auto h-4 w-4 text-emerald-600" aria-label="yes" /> : <Minus className="mx-auto h-4 w-4 text-ink-300" aria-label="no" />}</td>
                <td className="text-center">{c.rollback ? <Check className="mx-auto h-4 w-4 text-emerald-600" aria-label="yes" /> : <Minus className="mx-auto h-4 w-4 text-ink-300" aria-label="no" />}</td>
                <td className="max-w-md text-xs text-ink-500">{c.supported ? c.notes : c.reason}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function IntegrationsInner() {
  const { orgId, role } = useSession();
  const result = useSearchParams().get("result");
  const { data, error, loading, reload } = useApi<any[]>(`/orgs/${orgId}/integrations`);
  const { data: sites } = useApi<any[]>(`/orgs/${orgId}/websites`);
  const { data: providers } = useApi<any[]>(`/integrations/providers`);
  const [open, setOpen] = useState<string | null>(null);
  const isAdmin = hasRole(role, "admin");
  const visible = (data || []).filter((i) => i.status !== "disconnected" && i.status !== "pending");

  return (
    <>
      <PageHeader title="Integrations" subtitle="Connect your CMS to publish approved fixes, and Google to measure results. No plugins required." />
      {result === "connected" && <div className="mb-4"><Notice kind="success">Integration connected.</Notice></div>}
      {result === "rejected" && <div className="mb-4"><Notice kind="warning">Authorization was declined.</Notice></div>}
      {result === "error" && <div className="mb-4"><Notice kind="error">The connection could not be completed. See the integration error below.</Notice></div>}

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-ink-500">Available platforms</h2>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {(providers || []).map((p) => {
          const ready = p.status === "available";
          const count = visible.filter((i) => i.provider === p.provider && i.status === "connected").length;
          return (
            <div key={p.provider} className={cx("flex flex-col rounded-2xl border bg-white p-5 shadow-card", ready ? "border-ink-200/80" : "border-dashed border-ink-200")}>
              <div className="flex items-start justify-between">
                <ProviderMark provider={p.provider} />
                {count > 0 ? <Badge tone="bg-emerald-50 text-emerald-700 ring-emerald-200" dot="bg-emerald-500">{count} connected</Badge>
                  : <Badge>{p.kind === "data" ? "Data source" : "Publishing"}</Badge>}
              </div>
              <h3 className="mt-4 font-semibold text-ink-900">{p.name}</h3>
              <p className="mt-1 flex-1 text-sm text-ink-500">{p.description}</p>
              {p.supports && <div className="mt-3 flex flex-wrap gap-1.5">{p.supports.map((s: string) => <span key={s} className="rounded-md bg-ink-50 px-2 py-0.5 text-[11px] font-medium text-ink-600">{s}</span>)}</div>}
              <div className="mt-5">
                {p.status === "not_implemented" ? <Badge>Coming soon</Badge>
                  : p.status === "needs_configuration" ? <p className="text-xs text-amber-700">{p.configuration_note}</p>
                  : !isAdmin ? <p className="text-xs text-ink-500">Ask an admin to connect.</p>
                  : !sites?.length ? <ButtonLink href={`/app/${orgId}/websites`} variant="secondary" size="sm">Add a website first</ButtonLink>
                  : <Button variant="secondary" size="sm" className="w-full" onClick={() => setOpen(p.provider)}>Connect {p.name}</Button>}
              </div>
            </div>
          );
        })}
      </div>

      <h2 className="mb-3 mt-10 text-sm font-semibold uppercase tracking-wider text-ink-500">Your connections</h2>
      {loading && <Loading />}
      <ErrorState error={error} onRetry={reload} />
      {data && visible.length === 0 && (
        <div className="rounded-2xl border border-dashed border-ink-300 bg-white/60 p-8 text-center text-sm text-ink-500">
          No integrations yet. Without one you can still copy and export every fix.
        </div>
      )}
      <div className="space-y-4">
        {visible.map((i) => <IntegrationCard key={i.id} i={i} sites={sites || []} isAdmin={isAdmin} reload={reload} />)}
      </div>
      <p className="mt-6 flex items-center gap-1.5 text-xs text-ink-500"><ExternalLink className="h-3.5 w-3.5" /> Credentials are encrypted at rest and deleted immediately when you disconnect.</p>
      {open && sites && <ConnectModal provider={open} sites={sites} onClose={() => setOpen(null)} onDone={reload} />}
    </>
  );
}

export default function Integrations() {
  return <Suspense><IntegrationsInner /></Suspense>;
}
