"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Footer, PublicNav } from "@/components/PublicNav";
import { Button, Notice } from "@/components/ui";
import { post } from "@/lib/api";

const FEATURES = [
  ["Technical SEO", "Broken links, redirect chains, canonicals, robots & indexability, sitemaps, headings, structured data — each with evidence."],
  ["Answer Engine Optimization", "Question coverage, direct answers, content structure and FAQ opportunities grounded in your page."],
  ["Generative Engine readiness", "Authorship, freshness, sourcing of claims, entity signals and AI crawler access — clearly labelled heuristics."],
  ["Reviewable AI fixes", "Validated suggestions with before/after diffs. AI never invents prices, reviews, awards or facts."],
  ["Authorized publishing", "Connect WordPress with core Application Passwords — no plugin. Every change requires approval by default."],
  ["Independent verification", "We re-fetch your live page to confirm each change. API acceptance alone never counts as success."],
];

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
    <>
      <PublicNav />
      <main>
        <section className="bg-gradient-to-b from-white to-slate-50">
          <div className="mx-auto max-w-4xl px-4 py-20 text-center">
            <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
              See what&apos;s holding your website back — in search and in AI answers.
            </h1>
            <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600">
              Enter any public URL. We crawl it safely, show evidence for every issue, and draft fixes you can review,
              export, or publish to WordPress.
            </p>
            <form onSubmit={start} className="mx-auto mt-8 flex max-w-xl flex-col gap-3 sm:flex-row" data-testid="audit-form">
              <input
                className="input flex-1 py-3 text-base" placeholder="https://example.com" value={url} required
                onChange={(e) => setUrl(e.target.value)} aria-label="Website URL" data-testid="audit-url"
              />
              <Button type="submit" busy={busy} testId="audit-submit">Run free audit</Button>
            </form>
            {error && <div className="mx-auto mt-4 max-w-xl"><Notice kind="error">{error}</Notice></div>}
            <p className="mt-3 text-xs text-slate-500">
              Free audits check up to 10 pages, respect robots.txt and never access private or login-protected pages.
            </p>
          </div>
        </section>
        <section className="mx-auto grid max-w-6xl gap-4 px-4 py-12 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(([t, d]) => (
            <div key={t} className="rounded-lg border border-slate-200 bg-white p-5">
              <h3 className="font-semibold text-slate-900">{t}</h3>
              <p className="mt-2 text-sm text-slate-600">{d}</p>
            </div>
          ))}
        </section>
      </main>
      <Footer />
    </>
  );
}
