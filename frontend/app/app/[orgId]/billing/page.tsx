"use client";
import { useSearchParams } from "next/navigation";
import { Check, CreditCard, Sparkles } from "lucide-react";
import { Suspense } from "react";
import { Button, Card, cx, ErrorState, fmtDate, Loading, Meter, Notice, PageHeader, StatusBadge, useAction } from "@/components/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

const LABELS: Record<string, string> = {
  crawl_runs: "Audits", crawled_pages: "Pages crawled", rendered_pages: "JS-rendered pages", ai_requests: "AI requests",
  ai_tokens: "AI tokens", keyword_requests: "Keyword data requests", publish_ops: "Publishing operations", websites: "Websites", team_seats: "Team seats",
};
const ORDER = ["free", "starter", "pro", "agency"];

function BillingInner() {
  const { orgId, refresh } = useSession();
  const sp = useSearchParams();
  const checkout = sp.get("checkout");
  const wanted = sp.get("plan");
  const { data, error, loading, reload } = useApi<any>(`/orgs/${orgId}/billing`);
  const act = useAction();
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const sub = data.subscription;
  const dev = data.billing_mode === "dev";
  const current = data.plans.find((p: any) => p.key === sub.plan_key);

  async function choose(plan: string) {
    const r = await act.run(() => post<any>(`/orgs/${orgId}/billing/checkout`, { plan_key: plan }));
    if (r?.url) window.location.href = r.url;
    else { reload(); refresh(); }
  }

  return (
    <>
      <PageHeader title="Billing & usage" subtitle="Manage your plan, payment method and see what you’ve used this period." />
      <div className="mb-6 space-y-3 empty:hidden">
        {dev && <Notice kind="warning" testId="dev-billing">Development billing mode: plan changes are simulated. No payment is collected and no real transaction occurs.</Notice>}
        {checkout === "success" && <Notice kind="success">Checkout complete. Your plan updates as soon as Stripe confirms the payment.</Notice>}
        {wanted && wanted !== sub.plan_key && data.can_manage && <Notice kind="info">You selected the <b className="capitalize">{wanted}</b> plan. Confirm it below to upgrade.</Notice>}
        {sub.status === "past_due" && <Notice kind="error">Payment failed: {sub.last_payment_error || "please update your payment method"}. Paid features are paused until the invoice is paid.</Notice>}
        {act.error && <Notice kind="error">{act.error}</Notice>}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="relative overflow-hidden">
          <div className="absolute -right-16 -top-16 h-40 w-40 rounded-full bg-brand-100/60 blur-2xl" />
          <div className="relative">
            <div className="text-sm font-medium text-ink-500">Current plan</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-3xl font-semibold capitalize tracking-tight text-ink-900">{sub.plan_key}</span>
              {current && <span className="text-sm text-ink-500">${current.price_cad_month} CAD / mo</span>}
            </div>
            <div className="mt-2 flex items-center gap-2 text-sm"><StatusBadge s={sub.status} />{sub.is_simulated && <span className="text-xs font-medium text-amber-700">simulated</span>}</div>
            {sub.current_period_end && <p className="mt-3 text-sm text-ink-500">{sub.cancel_at_period_end ? "Ends" : "Renews"} {fmtDate(sub.current_period_end)}</p>}
            {data.can_manage && (
              <div className="mt-5 flex flex-col gap-2">
                {!dev && sub.has_stripe_customer && <Button variant="secondary" icon={CreditCard} busy={act.busy} onClick={async () => { const r = await act.run(() => post<any>(`/orgs/${orgId}/billing/portal`)); if (r?.url) window.location.href = r.url; }}>Manage payment & invoices</Button>}
                {sub.plan_key !== "free" && !sub.cancel_at_period_end && <Button variant="ghost" busy={act.busy} onClick={() => confirm("Cancel at the end of the billing period?") && act.run(async () => { await post(`/orgs/${orgId}/billing/cancel`); reload(); })}>Cancel subscription</Button>}
                {dev && sub.plan_key !== "free" && <Button variant="ghost" size="sm" onClick={() => act.run(async () => { await post(`/orgs/${orgId}/billing/dev/simulate-payment-failure`); reload(); })}>Simulate failed payment (dev)</Button>}
              </div>
            )}
            {!data.can_manage && <p className="mt-5 text-xs text-ink-500">Only owners can change billing.</p>}
          </div>
        </Card>
        <Card title="Usage this period" className="lg:col-span-2" subtitle={`Period started ${fmtDate(data.usage.period_start)} · limits are enforced on our servers`}>
          <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
            {Object.entries(data.usage.metrics).map(([k, v]: [string, any]) => <Meter key={k} label={LABELS[k] || k} used={v.used} limit={v.limit} />)}
          </div>
        </Card>
      </div>

      <h2 className="mb-4 mt-10 text-base font-semibold text-ink-900">Plans <span className="font-normal text-ink-500">· CAD per month</span></h2>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {data.plans.map((p: any) => {
          const isCurrent = p.key === sub.plan_key;
          const highlight = wanted ? p.key === wanted : p.key === "pro";
          const up = ORDER.indexOf(p.key) > ORDER.indexOf(sub.plan_key);
          return (
            <div key={p.key} className={cx("relative flex flex-col rounded-2xl border bg-white p-6 shadow-card",
              isCurrent ? "border-emerald-300 ring-1 ring-emerald-200" : highlight ? "border-brand-400 shadow-glow" : "border-ink-200/80")}>
              {isCurrent && <span className="absolute right-4 top-4 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200">Current</span>}
              {!isCurrent && highlight && <span className="absolute right-4 top-4 inline-flex items-center gap-1 rounded-full bg-brand-600 px-2 py-0.5 text-[11px] font-semibold text-white"><Sparkles className="h-3 w-3" />{wanted ? "Selected" : "Popular"}</span>}
              <div className="font-semibold text-ink-900">{p.name}</div>
              <div className="mt-2 flex items-baseline gap-1"><span className="text-3xl font-semibold tracking-tight">${p.price_cad_month}</span><span className="text-sm text-ink-500">/mo</span></div>
              <ul className="mt-4 flex-1 space-y-2 text-sm text-ink-600">{p.features.map((f: string) => <li key={f} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />{f}</li>)}</ul>
              {data.can_manage && !isCurrent && p.key !== "free" && (
                <div className="mt-5"><Button className="w-full" variant={highlight ? "primary" : "secondary"} busy={act.busy} onClick={() => choose(p.key)} testId={`choose-${p.key}`}>
                  {dev ? "Switch (simulated)" : up ? `Upgrade to ${p.name}` : `Switch to ${p.name}`}
                </Button></div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

export default function Billing() {
  return <Suspense><BillingInner /></Suspense>;
}
