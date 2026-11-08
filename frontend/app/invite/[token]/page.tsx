"use client";
import { useRouter } from "next/navigation";
import { MailCheck } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { AuthForm, AuthShell } from "@/components/AuthForm";
import { Button, Notice, Spinner } from "@/components/ui";
import { api, post } from "@/lib/api";

export default function Invite({ params }: { params: { token: string } }) {
  const router = useRouter();
  const [me, setMe] = useState<any>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/auth/me").then(setMe).catch(() => setMe(null)); }, []);
  async function accept() {
    setBusy(true);
    try {
      const r = await post<{ org_id: string }>("/auth/invitations/accept", { token: params.token });
      router.push(`/app/${r.org_id}`);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }
  return (
    <AuthShell>
      {me === undefined && <div className="flex items-center gap-3 text-ink-500"><Spinner /> Checking your session…</div>}
      {me === null && (
        <>
          <Notice kind="info">You have been invited to a workspace. Create an account with the invited email address.</Notice>
          <div className="mt-8"><Suspense><AuthForm mode="signup" inviteToken={params.token} /></Suspense></div>
        </>
      )}
      {me && (
        <div className="animate-fade-up">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-brand-50 text-brand-600"><MailCheck className="h-6 w-6" /></span>
          <h1 className="mt-6 text-2xl font-semibold tracking-tight">Join the workspace</h1>
          <p className="mt-2 text-sm text-ink-500">Signed in as <b className="text-ink-800">{me.user.email}</b>. Accept the invitation to get access.</p>
          {error && <div className="mt-4"><Notice kind="error">{error}</Notice></div>}
          <Button onClick={accept} busy={busy} size="lg" className="mt-6 w-full">Accept invitation</Button>
        </div>
      )}
    </AuthShell>
  );
}
