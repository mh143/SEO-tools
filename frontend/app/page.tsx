"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight, Bot, CheckCircle2, ChevronDown, FileSearch, GitPullRequestArrow, Globe2, LineChart, Lock,
  MessageSquareQuote, RotateCcw, ScanSearch, ShieldCheck, Sparkles, Wand2, Zap,
} from "lucide-react";
import { useState } from "react";
import { Footer, PublicNav } from "@/components/PublicNav";
import { ProviderMark } from "@/components/Providers";
import { Button, ButtonLink, cx, Notice, ScoreRing } from "@/components/ui";
import { post } from "@/lib/api";

const PILLARS = [
  { icon: ScanSearch, tone: "from-brand-500 to-violet-500", title: "Technical SEO",
    body: "Crawl like a search engine and catch what blocks indexing and ranking.",
    checks: ["Broken links & redirect chains", "Canonicals, robots & indexability", "Titles, headings & meta", "Sitemaps & structured data"] },
  { icon: MessageSquareQuote, tone: "from-sky-500 to-cyan-500", title: "Answer Engine Optimization",
    body: "Make your pages the clearest, most quotable answer to real questions.",
    checks: ["Question coverage", "Direct answers under headings", "FAQ opportunities", "Scannable content structure"] },
  { icon: Bot, tone: "from-fuchsia-500 to-rose-500", title: "Generative Engine readiness",
    body: "Give AI assistants the signals they need to understand and trust you.",
    checks: ["AI crawler access & llms.txt", "Authorship & freshness", "Sourced, specific claims", "Entity & organization signals"] },
];

const STEPS = [
  { icon: FileSearch, title: "Audit", body: "Enter a URL. We crawl safely, respect robots.txt and record evidence for every finding." },
  { icon: Wand2, title: "Draft fixes", body: "Rule-based and AI-drafted fixes with before/after diffs. AI never invents facts, prices or reviews." },
  { icon: GitPullRequestArrow, title: "Approve & publish", body: "Approve changes and publish to WordPress, Shopify or Wix — or copy and export them." },
  { icon: ShieldCheck, title: "Verify", body: "We re-fetch your live page to confirm each change, and roll back in one click if needed." },
];

const FEATURES = [
  { icon: Sparkles, title: "Reviewable AI fixes", body: "Validated titles, descriptions, answers, FAQs and JSON-LD — each with a diff you can edit before approving." },
  { icon: ShieldCheck, title: "Independent verification", body: "An API saying “OK” never counts. A fix is verified only when the live page shows the change." },
  { icon: RotateCcw, title: "One-click rollback", body: "Every published change stores the original. Conflicts with later edits are detected, never overwritten." },
  { icon: LineChart, title: "Search Console data", body: "See real clicks, impressions, CTR and position next to your audit, straight from Google." },
  { icon: Zap, title: "Monitoring & alerts", body: "Scheduled audits catch regressions — like a fixed issue coming back — and alert your team." },
  { icon: Lock, title: "Secure by design", body: "SSRF-safe crawler, encrypted credentials, role-based access, audit log and per-org data isolation." },
];

const INTEGRATIONS = [
  { p: "wordpress", name: "WordPress", kind: "Publish", items: ["Titles & H1", "Image alt text", "Answers & FAQ sections", "Internal links"] },
  { p: "shopify", name: "Shopify", kind: "Publish", items: ["SEO titles & meta descriptions", "Products, collections, pages, blogs", "Body content & alt text", "URL redirects"] },
  { p: "wix", name: "Wix", kind: "Publish", items: ["SEO titles", "Meta descriptions", "Blog posts", "Store products"] },
  { p: "google_search_console", name: "Search Console", kind: "Measure", items: ["Clicks & impressions", "CTR & average position", "Top queries", "Top pages"] },
];

const FAQ = [
  ["What is AEO and GEO?", "Answer Engine Optimization (AEO) structures content so it can be lifted as a direct answer — in featured snippets, voice assistants and AI answers. Generative Engine Optimization (GEO) covers the signals AI systems use to understand and trust a source: crawler access, authorship, freshness, sourcing and entities. Our GEO score is an internal heuristic, not a ranking prediction."],
  ["Do I need to install a plugin?", "No. WordPress connects with core Application Passwords, Shopify with a custom app token, and Wix with an API key. Credentials are encrypted and you can disconnect at any time."],
  ["Will you change my site without asking?", "Never. Every fix is a draft until someone with the right role approves it. After publishing we verify the live page and keep the original so you can roll back."],
  ["What can’t be published automatically?", "Each platform is honest about its limits — for example WordPress core has no meta description field, and canonical tags on Shopify come from the theme. Those fixes are ready to copy or export instead."],
  ["Is the free audit really free?", "Yes. The quick audit checks up to 10 pages without an account. The Free plan gives you 1 website with 25 pages per audit and 10 AI fix drafts a month."],
];

function HeroPreview() {
  const scores = [["Technical", 92], ["Content", 78], ["AEO", 64], ["GEO", 71]] as const;
  const rows = [
    ["high", "Broken internal link to a 404 page", "/blog/coffee-guide"],
    ["medium", "Question heading without a direct answer", "/faq"],
    ["low", "Very short title", "/about"],
  ];
  return (
    <div className="relative mx-auto mt-16 max-w-5xl animate-fade-up [animation-delay:150ms]">
      <div className="absolute -inset-x-8 -top-8 bottom-0 -z-10 rounded-[2.5rem] bg-gradient-to-b from-brand-200/50 via-violet-100/40 to-transparent blur-2xl" />
      <div className="overflow-hidden rounded-2xl border border-ink-200/80 bg-white shadow-glow">
        <div className="flex items-center gap-2 border-b border-ink-100 bg-ink-50/70 px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-rose-300" /><span className="h-2.5 w-2.5 rounded-full bg-amber-300" /><span className="h-2.5 w-2.5 rounded-full bg-emerald-300" />
          <span className="ml-3 truncate rounded-md bg-white px-3 py-1 text-xs text-ink-500 ring-1 ring-ink-200">app.ranklens.example / audits / bean-there.example</span>
          <span className="ml-auto hidden rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700 sm:inline">Example report</span>
        </div>
        <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[1fr_1.3fr]">
          <div className="grid grid-cols-2 gap-3">
            {scores.map(([l, v]) => (
              <div key={l} className="flex flex-col items-center rounded-xl border border-ink-100 bg-white p-4">
                <ScoreRing value={v} size={76} stroke={7} label={l} />
                <div className="mt-2 text-xs font-semibold uppercase tracking-wider text-ink-500">{l}</div>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-ink-100">
            <div className="flex items-center justify-between border-b border-ink-100 px-4 py-3">
              <span className="text-sm font-semibold">Top findings</span>
              <span className="text-xs text-ink-500">38 pages · 2 min ago</span>
            </div>
            <ul className="divide-y divide-ink-100">
              {rows.map(([s, t, u]) => (
                <li key={t} className="flex items-center gap-3 px-4 py-3">
                  <span className={cx("h-2 w-2 shrink-0 rounded-full", s === "high" ? "bg-orange-500" : s === "medium" ? "bg-amber-500" : "bg-sky-500")} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-ink-900">{t}</div>
                    <div className="truncate text-xs text-ink-500">{u}</div>
                  </div>
                  <span className="hidden items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700 sm:inline-flex"><Wand2 className="h-3 w-3" /> Fix ready</span>
                </li>
              ))}
            </ul>
            <div className="flex items-center gap-2 border-t border-ink-100 bg-emerald-50/60 px-4 py-3 text-xs text-emerald-800">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" /> Title fix published to Shopify and verified on the live page
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Landing() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const r = await post<{ token: string }>("/public/audits", { url });
      router.push(`/audit/${r.token}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="bg-white">
      <div className="relative overflow-hidden">
        <div className="grid-bg absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_70%)]" />
        <div className="absolute left-1/2 top-[-10rem] -z-10 h-[36rem] w-[60rem] -translate-x-1/2 rounded-full bg-gradient-to-tr from-brand-300/40 via-violet-200/40 to-fuchsia-200/30 blur-3xl" />
        <PublicNav />
        <section className="mx-auto max-w-6xl px-4 pb-20 pt-14 sm:px-6 sm:pt-20">
          <div className="mx-auto max-w-3xl text-center animate-fade-up">
            <Link href="#integrations" className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white/80 py-1 pl-1 pr-3 text-xs font-medium text-brand-700 no-underline shadow-sm backdrop-blur hover:border-brand-300">
              <span className="rounded-full bg-brand-600 px-2 py-0.5 text-[11px] font-semibold text-white">New</span>
              Shopify, Wix & Google Search Console <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <h1 className="mt-6 text-4xl font-semibold leading-[1.08] tracking-tight text-ink-900 sm:text-6xl">
              Get found on Google —<br className="hidden sm:block" /> <span className="text-gradient">and in AI answers.</span>
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-ink-600">
              RankLens audits your site for technical SEO, answer-engine and generative-search readiness, drafts fixes you can review,
              publishes them to your CMS and verifies every change on the live page.
            </p>
            <form onSubmit={start} className="mx-auto mt-9 max-w-xl" data-testid="audit-form">
              <div className="flex flex-col gap-2 rounded-2xl border border-ink-200 bg-white p-2 shadow-lift sm:flex-row sm:items-center">
                <div className="flex flex-1 items-center gap-2 px-2">
                  <Globe2 className="h-5 w-5 shrink-0 text-ink-400" aria-hidden />
                  <input className="h-11 w-full bg-transparent text-base text-ink-900 placeholder:text-ink-400 focus:outline-none"
                    placeholder="https://yourwebsite.com" value={url} required onChange={(e) => setUrl(e.target.value)}
                    aria-label="Website URL" data-testid="audit-url" inputMode="url" />
                </div>
                <Button type="submit" size="lg" busy={busy} testId="audit-submit" className="h-11">Run free audit <ArrowRight className="h-4 w-4" /></Button>
              </div>
            </form>
            {error && <div className="mx-auto mt-4 max-w-xl text-left"><Notice kind="error">{error}</Notice></div>}
            <div className="mt-5 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-sm text-ink-500">
              {["No account needed", "Up to 10 pages free", "Respects robots.txt"].map((t) => (
                <span key={t} className="inline-flex items-center gap-1.5"><CheckCircle2 className="h-4 w-4 text-emerald-500" /> {t}</span>
              ))}
            </div>
          </div>
          <HeroPreview />
        </section>
      </div>

      <section className="border-y border-ink-100 bg-ink-50/60">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-4 py-8 sm:px-6 md:flex-row md:justify-between">
          <span className="text-sm font-medium text-ink-500">Publish fixes to your platform, measure with Google</span>
          <div className="flex flex-wrap items-center justify-center gap-6">
            {INTEGRATIONS.map((i) => (
              <span key={i.p} className="inline-flex items-center gap-2 text-sm font-semibold text-ink-700"><ProviderMark provider={i.p} size="sm" /> {i.name}</span>
            ))}
          </div>
        </div>
      </section>

      <main>
        <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-24 sm:px-6">
          <div className="mx-auto max-w-2xl text-center">
            <div className="text-sm font-semibold text-brand-600">One audit, three lenses</div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight text-ink-900 sm:text-4xl">Search is changing. Your audit should too.</h2>
            <p className="mt-4 text-lg text-ink-600">Classic SEO still matters — but people now also get answers from AI assistants. RankLens checks both, with evidence for every finding.</p>
          </div>
          <div className="mt-14 grid gap-5 md:grid-cols-3">
            {PILLARS.map((p) => (
              <div key={p.title} className="group relative overflow-hidden rounded-2xl border border-ink-200/80 bg-white p-7 shadow-card transition hover:-translate-y-0.5 hover:shadow-lift">
                <span className={cx("grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br text-white shadow-sm", p.tone)}><p.icon className="h-5 w-5" /></span>
                <h3 className="mt-5 text-lg font-semibold text-ink-900">{p.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-600">{p.body}</p>
                <ul className="mt-5 space-y-2.5">
                  {p.checks.map((c) => <li key={c} className="flex items-center gap-2 text-sm text-ink-700"><CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />{c}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section id="how" className="scroll-mt-20 bg-ink-950 py-24 text-white">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <div className="max-w-2xl">
              <div className="text-sm font-semibold text-brand-300">How it works</div>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">From finding to verified fix in minutes.</h2>
              <p className="mt-4 text-lg text-ink-300">No spreadsheets, no guesswork. Every step is reviewable, every change is reversible.</p>
            </div>
            <ol className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((s, i) => (
                <li key={s.title} className="relative rounded-2xl border border-white/10 bg-white/[0.03] p-6">
                  <div className="flex items-center justify-between">
                    <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500/15 text-brand-300 ring-1 ring-brand-400/30"><s.icon className="h-5 w-5" /></span>
                    <span className="text-sm font-semibold tabular-nums text-ink-500">0{i + 1}</span>
                  </div>
                  <h3 className="mt-5 font-semibold">{s.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink-400">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
          <div className="grid gap-x-10 gap-y-12 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title}>
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-50 text-brand-600 ring-1 ring-brand-100"><f.icon className="h-5 w-5" /></span>
                <h3 className="mt-4 font-semibold text-ink-900">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-600">{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="integrations" className="scroll-mt-20 border-t border-ink-100 bg-gradient-to-b from-ink-50/80 to-white py-24">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <div className="mx-auto max-w-2xl text-center">
              <div className="text-sm font-semibold text-brand-600">Integrations</div>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight text-ink-900 sm:text-4xl">Works where your site lives.</h2>
              <p className="mt-4 text-lg text-ink-600">Connect with each platform’s official authorization — no plugins. We tell you exactly what each one can and can’t change.</p>
            </div>
            <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {INTEGRATIONS.map((i) => (
                <div key={i.p} className="rounded-2xl border border-ink-200/80 bg-white p-6 shadow-card">
                  <div className="flex items-center justify-between">
                    <ProviderMark provider={i.p} />
                    <span className={cx("rounded-full px-2 py-0.5 text-[11px] font-semibold", i.kind === "Publish" ? "bg-brand-50 text-brand-700" : "bg-sky-50 text-sky-700")}>{i.kind}</span>
                  </div>
                  <h3 className="mt-4 font-semibold text-ink-900">{i.name}</h3>
                  <ul className="mt-3 space-y-2">
                    {i.items.map((x) => <li key={x} className="flex items-start gap-2 text-sm text-ink-600"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />{x}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="faq" className="mx-auto max-w-3xl scroll-mt-20 px-4 py-24 sm:px-6">
          <h2 className="text-center text-3xl font-semibold tracking-tight text-ink-900">Frequently asked questions</h2>
          <div className="mt-10 divide-y divide-ink-100 rounded-2xl border border-ink-200/80 bg-white shadow-card">
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

        <section className="px-4 pb-24 sm:px-6">
          <div className="relative mx-auto max-w-6xl overflow-hidden rounded-3xl bg-gradient-to-br from-brand-700 via-brand-600 to-violet-600 px-6 py-16 text-center text-white shadow-glow sm:px-16">
            <div className="grid-bg absolute inset-0 opacity-20 [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]" />
            <h2 className="relative text-3xl font-semibold tracking-tight sm:text-4xl">See what’s holding your site back.</h2>
            <p className="relative mx-auto mt-4 max-w-xl text-brand-100">Start with a free audit, or create an account to monitor your site and publish verified fixes.</p>
            <div className="relative mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              <ButtonLink href="/signup" size="lg" variant="secondary" className="border-white">Create free account</ButtonLink>
              <ButtonLink href="/pricing" size="lg" variant="ghost" className="text-white hover:bg-white/10 hover:text-white">View pricing <ArrowRight className="h-4 w-4" /></ButtonLink>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
