"use client";
import { useSearchParams } from "next/navigation";
import { Button, Card, ErrorState, fmtDate, Loading, Notice, PageHeader, StatusBadge, useAction } from "@/components/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

const LABELS: Record<string, string> = {
  crawl_runs: "Audits", crawled_pages: "Pages crawled", rendered_pages: "JS-rendered pages", ai_requests: "AI requests",
  ai_tokens: "AI tokens", keyword_requests: "Keyword data requests", publish_ops: "Publishing operations", websites: "Websites", team_seats: "Team seats",
};

export default function Billing() {
  const { orgId, refresh } = useSession();
  const checkout = useSearchParams().get("checkout");
  const { data, error, loading, reload } = useApi<any>(`/orgs/${orgId}/billing`);
  const act = useAction();
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const sub = data.subscription;
  const dev = data.billing_mode === "dev";

  async function choose(plan: string) {
    const r = await act.run(() => post<any>(`/orgs/${orgId}/billing/checkout`, { plan_key: plan }));
    if (r?.url) window.location.href = r.url;
    else { reload(); refresh(); }
  }

  return (
    <>
      <PageHeader title="Billing & usage" />
      {dev && <div className="mb-4"><Notice kind="warning" testId="dev-billing">Development billing mode: plan changes are simulated. No payment is collected and no real transaction occurs.</Notice></div>}
      {checkout === "success" && <div className="mb-4"><Notice kind="success">Checkout complete. Your plan updates as soon as Stripe confirms the payment.</Notice></div>}
      {sub.status === "past_due" && <div className="mb-4"><Notice kind="error">Payment failed: {sub.last_payment_error || "please update your payment method"}. Paid features are paused until the invoice is paid.</Notice></div>}
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Current plan" className="lg:col-span-1">
          <div className="text-2xl font-semibold capitalize">{sub.plan_key}</div>
          <div className="mt-1 flex items-center gap-2 text-sm"><StatusBadge s={sub.status} />{sub.is_simulated && <span className="text-xs text-amber-700">simulated</span>}</div>
          {sub.current_period_end && <p className="mt-2 text-sm text-slate-500">{sub.cancel_at_period_end ? "Ends" : "Renews"} {fmtDate(sub.current_period_end)}</p>}
          {data.can_manage && (
            <div className="mt-4 flex flex-col gap-2">
              {!dev && sub.has_stripe_customer && <Button variant="secondary" busy={act.busy} onClick={async () => { const r = await act.run(() => post<any>(`/orgs/${orgId}/billing/portal`)); if (r?.url) window.location.href = r.url; }}>Manage payment & invoices</Button>}
              {sub.plan_key !== "free" && !sub.cancel_at_period_end && <Button variant="ghost" busy={act.busy} onClick={() => confirm("Cancel at the end of the billing period?") && act.run(async () => { await post(`/orgs/${orgId}/billing/cancel`); reload(); })}>Cancel subscription</Button>}
              {dev && sub.plan_key !== "free" && <Button variant="ghost" size="sm" onClick={() => act.run(async () => { await post(`/orgs/${orgId}/billing/dev/simulate-payment-failure`); reload(); })}>Simulate failed payment (dev)</Button>}
            </div>
          )}
          {!data.can_manage && <p className="mt-4 text-xs text-slate-500">Only owners can change billing.</p>}
        </Card>
        <Card title="Usage this period" className="lg:col-span-2">
          <table className="w-full text-sm"><tbody>{Object.entries(data.usage.metrics).map(([k, v]: [string, any]) => (
            <tr key={k} className="border-t border-slate-100"><td className="py-1.5">{LABELS[k] || k}</td><td className="text-right tabular-nums">{v.used}{v.limit !== null && v.limit !== undefined ? ` / ${v.limit}` : ""}</td></tr>))}</tbody></table>
          <p className="mt-2 text-xs text-slate-500">Period started {fmtDate(data.usage.period_start)}. Limits are enforced on our servers.</p>
        </Card>
      </div>
      <h2 className="mb-3 mt-8 text-lg font-semibold">Plans (CAD / month)</h2>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {data.plans.map((p: any) => (
          <div key={p.key} className={`rounded-lg border bg-white p-5 ${p.key === sub.plan_key ? "border-brand-500 ring-2 ring-brand-100" : "border-slate-200"}`}>
            <div className="font-semibold">{p.name}</div><div className="text-2xl font-bold">${p.price_cad_month}</div>
            <ul className="mt-2 space-y-1 text-xs text-slate-600">{p.features.map((f: string) => <li key={f}>✓ {f}</li>)}</ul>
            {data.can_manage && p.key !== sub.plan_key && p.key !== "free" && (
              <div className="mt-3"><Button size="sm" busy={act.busy} onClick={() => choose(p.key)} testId={`choose-${p.key}`}>{dev ? `Switch (simulated)` : `Upgrade to ${p.name}`}</Button></div>)}
          </div>
        ))}
      </div>
    </>
  );
}
