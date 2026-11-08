"use client";
import { Check, ChevronDown, Minus, Sparkles } from "lucide-react";
import { Footer, PublicNav } from "@/components/PublicNav";
import { ButtonLink, cx, ErrorState, Notice, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/hooks";

const TAGLINE: Record<string, string> = {
  free: "Try RankLens on one site.",
  starter: "For a single business website.",
  pro: "For growing teams and multiple sites.",
  agency: "For agencies managing many clients.",
};

type Row = [string, (p: any) => string | boolean];
const ROWS: [string, Row[]][] = [
  ["Audits", [
    ["Websites", (p) => String(p.max_websites)],
    ["Pages per audit", (p) => p.max_pages_per_crawl.toLocaleString()],
    ["Crawl depth", (p) => String(p.max_depth)],
    ["Audits per month", (p) => String(p.crawls_per_month)],
    ["Scheduled monitoring", (p) => p.schedules.filter((s: string) => s !== "none").join(", ") || false],
    ["JavaScript rendering", (p) => (p.js_rendering ? `${p.rendered_pages_per_month.toLocaleString()} pages / mo` : false)],
  ]],
  ["Fixes & publishing", [
    ["AI fix drafts per month", (p) => p.ai_requests_per_month.toLocaleString()],
    ["Publish to WordPress, Shopify & Wix", (p) => (p.publish_ops_per_month ? `${p.publish_ops_per_month.toLocaleString()} ops / mo` : false)],
    ["Verification & rollback", (p) => p.publish_ops_per_month > 0],
    ["Keyword data requests", (p) => (p.keyword_requests_per_month ? p.keyword_requests_per_month.toLocaleString() : false)],
  ]],
  ["Team & reporting", [
    ["Team seats", (p) => String(p.team_seats)],
    ["CSV, JSON, Markdown & HTML exports", () => true],
    ["Google Search Console data", () => true],
    ["White-label reports", (p) => p.reports_white_label],
  ]],
];

const FAQ = [
  ["Can I change plans later?", "Yes — upgrade or downgrade any time from Billing. Upgrades apply immediately; cancellations take effect at the end of the billing period."],
  ["What counts as a publishing operation?", "Each change applied to your site (and each rollback) is one operation. Drafting, editing and exporting fixes never count."],
  ["Which currency do you bill in?", "Prices are in Canadian dollars (CAD), billed monthly through Stripe. Taxes may apply depending on your location."],
  ["Do you guarantee rankings?", "No one honestly can. We show evidence, draft careful fixes and verify they are live — scores are internal heuristics, not ranking predictions."],
];

function Cell({ v }: { v: string | boolean }) {
  if (v === true) return <Check className="mx-auto h-5 w-5 text-brand-600" aria-label="Included" />;
  if (v === false) return <Minus className="mx-auto h-4 w-4 text-ink-300" aria-label="Not included" />;
  return <span className="text-sm text-ink-700">{v}</span>;
}

export default function Pricing() {
  const { data, error, loading, reload } = useApi<any>("/public/plans");
  const plans: any[] = data?.plans || [];
  return (
    <div className="bg-white">
      <div className="relative overflow-hidden">
        <div className="grid-bg absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_top,black_25%,transparent_65%)]" />
        <div className="absolute left-1/2 top-[-12rem] -z-10 h-[30rem] w-[50rem] -translate-x-1/2 rounded-full bg-gradient-to-tr from-brand-300/40 via-violet-200/40 to-fuchsia-200/30 blur-3xl" />
        <PublicNav />
        <section className="mx-auto max-w-6xl px-4 pb-10 pt-14 text-center sm:px-6">
          <div className="text-sm font-semibold text-brand-600">Pricing</div>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight text-ink-900 sm:text-5xl">Simple plans that grow with you</h1>
          <p className="mx-auto mt-4 max-w-xl text-lg text-ink-600">Start free. Upgrade when you need more pages, monitoring and direct publishing. Cancel any time.</p>
          {data?.billing_mode === "dev" && (
            <div className="mx-auto mt-6 max-w-xl text-left"><Notice kind="warning">Development billing mode: upgrades are simulated and no payment is taken.</Notice></div>
          )}
        </section>
      </div>

      <section className="mx-auto max-w-6xl px-4 sm:px-6">
        <ErrorState error={error} onRetry={reload} />
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-4">
          {loading && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[30rem] rounded-2xl" />)}
          {plans.map((p) => {
            const hot = p.key === "pro";
            return (
              <div key={p.key} className={cx("relative flex flex-col rounded-2xl border bg-white p-7 transition",
                hot ? "border-brand-500 shadow-glow lg:-my-3 lg:py-10" : "border-ink-200/80 shadow-card hover:shadow-lift")}>
                {hot && <span className="absolute -top-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full bg-brand-600 px-3 py-1 text-xs font-semibold text-white shadow-sm"><Sparkles className="h-3 w-3" /> Most popular</span>}
                <h2 className="text-lg font-semibold text-ink-900">{p.name}</h2>
                <p className="mt-1 min-h-[2.5rem] text-sm text-ink-500">{TAGLINE[p.key] || ""}</p>
                <div className="mt-5 flex items-baseline gap-1">
                  <span className="text-4xl font-semibold tracking-tight text-ink-900">${p.price_cad_month}</span>
                  <span className="text-sm text-ink-500">CAD / month</span>
                </div>
                <ButtonLink href={`/signup?plan=${p.key}`} variant={hot ? "primary" : "secondary"} className="mt-6 w-full">
                  {p.price_cad_month === 0 ? "Start free" : `Get ${p.name}`}
                </ButtonLink>
                <ul className="mt-7 space-y-3 text-sm text-ink-700">
                  {p.features.map((f: string) => (
                    <li key={f} className="flex gap-2.5"><Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />{f}</li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
        {data && <p className="mt-8 text-center text-xs text-ink-500">{data.note} Plan limits are enforced on our servers; usage is shown on your billing page.</p>}
      </section>

      {plans.length > 0 && (
        <section className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
          <h2 className="text-center text-2xl font-semibold tracking-tight text-ink-900 sm:text-3xl">Compare plans</h2>
          <div className="mt-10 overflow-x-auto rounded-2xl border border-ink-200/80 bg-white shadow-card">
            <table className="w-full min-w-[720px] text-left">
              <thead>
                <tr className="border-b border-ink-100">
                  <th className="w-1/3 px-6 py-5 text-sm font-medium text-ink-500">Features</th>
                  {plans.map((p) => (
                    <th key={p.key} className={cx("px-4 py-5 text-center", p.key === "pro" && "bg-brand-50/50")}>
                      <div className="font-semibold text-ink-900">{p.name}</div>
                      <div className="text-xs font-normal text-ink-500">${p.price_cad_month}/mo</div>
                    </th>
                  ))}
                </tr>
              </thead>
              {ROWS.map(([group, rows]) => (
                <tbody key={group}>
                  <tr><td colSpan={plans.length + 1} className="bg-ink-50/70 px-6 py-2.5 text-xs font-semibold uppercase tracking-wider text-ink-500">{group}</td></tr>
                  {rows.map(([label, fn]) => (
                    <tr key={label} className="border-t border-ink-100">
                      <td className="px-6 py-3.5 text-sm text-ink-700">{label}</td>
                      {plans.map((p) => <td key={p.key} className={cx("px-4 py-3.5 text-center capitalize", p.key === "pro" && "bg-brand-50/50")}><Cell v={fn(p)} /></td>)}
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          </div>
        </section>
      )}

      <section className="mx-auto max-w-3xl px-4 pb-24 sm:px-6">
        <h2 className="text-center text-2xl font-semibold tracking-tight text-ink-900 sm:text-3xl">Questions about billing</h2>
        <div className="mt-8 divide-y divide-ink-100 rounded-2xl border border-ink-200/80 bg-white shadow-card">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group px-6 py-5">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium text-ink-900">
                {q}<ChevronDown className="h-5 w-5 shrink-0 text-ink-400 transition group-open:rotate-180" />
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-ink-600">{a}</p>
            </details>
          ))}
        </div>
      </section>
      <Footer />
    </div>
  );
}
