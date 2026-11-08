"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, Eye, EyeOff, Quote } from "lucide-react";
import { ReactNode, useState } from "react";
import { Button, Field, Logo, Notice, ScoreRing } from "./ui";
import { post } from "@/lib/api";

const PAID = ["starter", "pro", "agency"];

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen bg-white lg:grid-cols-[1fr_1.05fr]">
      <div className="flex flex-col px-5 py-6 sm:px-10">
        <Link href="/" className="link-plain w-fit" aria-label="RankLens home"><Logo /></Link>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">{children}</div>
        <p className="text-xs text-ink-400">© {new Date().getFullYear()} RankLens</p>
      </div>
      <aside className="relative hidden overflow-hidden bg-ink-950 lg:block">
        <div className="absolute -right-32 -top-32 h-[32rem] w-[32rem] rounded-full bg-brand-600/40 blur-3xl" />
        <div className="absolute -bottom-40 -left-20 h-[28rem] w-[28rem] rounded-full bg-fuchsia-500/20 blur-3xl" />
        <div className="grid-bg absolute inset-0 opacity-30 [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]" />
        <div className="relative flex h-full flex-col justify-center px-14 py-16 text-white">
          <div className="max-w-md">
            <h2 className="text-3xl font-semibold leading-tight tracking-tight">Every finding backed by evidence. Every fix verified live.</h2>
            <ul className="mt-8 space-y-3 text-ink-300">
              {["Technical SEO, AEO and GEO checks in one audit", "AI-drafted fixes you review before anything changes",
                "Publish to WordPress, Shopify and Wix — then verify", "Google Search Console data next to your audit"].map((t) => (
                <li key={t} className="flex gap-3"><CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-brand-300" />{t}</li>
              ))}
            </ul>
            <div className="mt-12 rounded-2xl border border-white/10 bg-white/[0.04] p-6 backdrop-blur">
              <div className="flex items-center gap-5">
                <div className="rounded-full bg-white p-1"><ScoreRing value={91} size={72} stroke={7} label="Technical" /></div>
                <div>
                  <div className="text-sm font-semibold">Technical score after fixes</div>
                  <div className="mt-1 text-sm text-ink-400">Example: 14 fixes approved, published and verified.</div>
                </div>
              </div>
              <div className="mt-5 flex gap-3 border-t border-white/10 pt-5 text-sm text-ink-300">
                <Quote className="h-5 w-5 shrink-0 text-brand-300" />
                Nothing is changed on your site until someone on your team approves it.
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}

export function AuthForm({ mode, inviteToken }: { mode: "login" | "signup"; inviteToken?: string }) {
  const router = useRouter();
  const plan = useSearchParams().get("plan");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [name, setName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<any>(`/auth/${mode}`, mode === "login" ? { email, password } :
        { email, password, name, org_name: orgName, invite_token: inviteToken });
      const orgs = r.user.organizations;
      if (!orgs.length) return router.push("/app");
      router.push(plan && PAID.includes(plan) && !inviteToken ? `/app/${orgs[0].id}/billing?plan=${plan}` : `/app/${orgs[0].id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const q = plan ? `?plan=${encodeURIComponent(plan)}` : "";
  return (
    <div className="animate-fade-up">
      <h1 className="text-2xl font-semibold tracking-tight text-ink-900 sm:text-3xl">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
      <p className="mt-2 text-sm text-ink-500">
        {mode === "login" ? "Log in to your RankLens workspace." : plan && PAID.includes(plan)
          ? `Start with a free account, then confirm the ${plan[0].toUpperCase() + plan.slice(1)} plan.`
          : "Free forever for one website. No credit card required."}
      </p>
      <form onSubmit={submit} className="mt-8 space-y-4" data-testid={`${mode}-form`}>
        {mode === "signup" && (
          <Field label="Your name"><input className="input h-11" value={name} onChange={(e) => setName(e.target.value)} name="name" autoComplete="name" placeholder="Jordan Lee" /></Field>
        )}
        <Field label="Email"><input className="input h-11" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} name="email" autoComplete="email" placeholder="you@company.com" /></Field>
        <Field label="Password" hint={mode === "signup" ? "At least 10 characters." : undefined}>
          <div className="relative">
            <input className="input h-11 pr-11" type={show ? "text" : "password"} required value={password} onChange={(e) => setPassword(e.target.value)} name="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder="••••••••••" />
            <button type="button" onClick={() => setShow(!show)} className="absolute inset-y-0 right-0 grid w-11 place-items-center text-ink-400 hover:text-ink-700" aria-label={show ? "Hide password" : "Show password"}>
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </Field>
        {mode === "signup" && !inviteToken && (
          <Field label="Workspace name" hint="Usually your company or agency name.">
            <input className="input h-11" value={orgName} onChange={(e) => setOrgName(e.target.value)} name="org" placeholder="Acme Inc." />
          </Field>
        )}
        {error && <Notice kind="error">{error}</Notice>}
        <Button type="submit" busy={busy} testId={`${mode}-submit`} size="lg" className="w-full">{mode === "login" ? "Log in" : "Create account"}</Button>
      </form>
      <p className="mt-8 text-center text-sm text-ink-500">
        {mode === "login"
          ? <>New to RankLens? <Link href={`/signup${q}`} className="font-medium">Create an account</Link></>
          : <>Already have an account? <Link href={`/login${q}`} className="font-medium">Log in</Link></>}
      </p>
      {mode === "signup" && <p className="mt-4 text-center text-xs text-ink-400">By creating an account you agree to use RankLens only on sites you own or are authorized to audit.</p>}
    </div>
  );
}
