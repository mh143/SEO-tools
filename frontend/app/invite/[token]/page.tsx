"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthForm } from "@/components/AuthForm";
import { PublicNav } from "@/components/PublicNav";
import { Button, Loading, Notice } from "@/components/ui";
import { api, post } from "@/lib/api";

export default function Invite({ params }: { params: { token: string } }) {
  const router = useRouter();
  const [me, setMe] = useState<any>(undefined);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api("/auth/me").then(setMe).catch(() => setMe(null)); }, []);
  async function accept() {
    try {
      const r = await post<{ org_id: string }>("/auth/invitations/accept", { token: params.token });
      router.push(`/app/${r.org_id}`);
    } catch (e) { setError((e as Error).message); }
  }
  return (
    <>
      <PublicNav />
      {me === undefined && <Loading />}
      {me === null && (<><p className="mt-8 text-center text-slate-600">You have been invited to a workspace. Create an account with the invited email address.</p>
        <AuthForm mode="signup" inviteToken={params.token} /></>)}
      {me && (
        <div className="mx-auto mt-16 max-w-md space-y-4 rounded-lg border bg-white p-8">
          <p>Signed in as <b>{me.user.email}</b>. Accept the invitation?</p>
          {error && <Notice kind="error">{error}</Notice>}
          <Button onClick={accept}>Accept invitation</Button>
        </div>
      )}
    </>
  );
}
