"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Field, Notice } from "./ui";
import { post } from "@/lib/api";

export function AuthForm({ mode, inviteToken }: { mode: "login" | "signup"; inviteToken?: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      router.push(orgs.length ? `/app/${orgs[0].id}` : "/app");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-md rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
      <h1 className="text-2xl font-semibold">{mode === "login" ? "Log in" : "Create your account"}</h1>
      <form onSubmit={submit} className="mt-6 space-y-4" data-testid={`${mode}-form`}>
        {mode === "signup" && (
          <Field label="Your name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} name="name" /></Field>
        )}
        <Field label="Email"><input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} name="email" autoComplete="email" /></Field>
        <Field label="Password" hint={mode === "signup" ? "At least 10 characters." : undefined}>
          <input className="input" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} name="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </Field>
        {mode === "signup" && !inviteToken && (
          <Field label="Workspace name" hint="Usually your company or agency name.">
            <input className="input" value={orgName} onChange={(e) => setOrgName(e.target.value)} name="org" />
          </Field>
        )}
        {error && <Notice kind="error">{error}</Notice>}
        <Button type="submit" busy={busy} testId={`${mode}-submit`}>{mode === "login" ? "Log in" : "Create account"}</Button>
      </form>
      <p className="mt-6 text-sm text-slate-500">
        {mode === "login" ? <>No account? <Link href="/signup">Sign up free</Link></> : <>Already have an account? <Link href="/login">Log in</Link></>}
      </p>
    </div>
  );
}
