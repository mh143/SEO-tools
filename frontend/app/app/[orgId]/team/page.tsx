"use client";
import { useState } from "react";
import { Button, Card, ErrorState, Field, Loading, Notice, PageHeader, useAction } from "@/components/ui";
import { del, patch, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

const ROLES = ["viewer", "editor", "admin", "owner"];

export default function Team() {
  const { orgId, role, me } = useSession();
  const { data, error, loading, reload } = useApi<any>(`/orgs/${orgId}/members`);
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState("editor");
  const [link, setLink] = useState<string | null>(null);
  const act = useAction();
  const isAdmin = hasRole(role, "admin");
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  return (
    <>
      <PageHeader title="Team" subtitle={`${data.members.length} of ${data.seat_limit} seats used`} />
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Members">
          <table className="w-full text-sm"><thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-2">Member</th><th>Role</th><th /></tr></thead>
            <tbody>{data.members.map((m: any) => (
              <tr key={m.id} className="border-t border-slate-100">
                <td className="py-2">{m.name || m.email}<div className="text-xs text-slate-500">{m.email}</div></td>
                <td>{isAdmin && m.user_id !== me.id ? (
                  <select className="input w-32" value={m.role} onChange={(e) => act.run(async () => { await patch(`/orgs/${orgId}/members/${m.id}`, { role: e.target.value }); reload(); })}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select>) : m.role}</td>
                <td className="text-right">{(isAdmin || m.user_id === me.id) && (
                  <Button size="sm" variant="ghost" onClick={() => act.run(async () => { if (confirm(m.user_id === me.id ? "Leave this workspace?" : "Remove this member?")) { await del(`/orgs/${orgId}/members/${m.id}`); reload(); } })}>
                    {m.user_id === me.id ? "Leave" : "Remove"}</Button>)}</td>
              </tr>))}</tbody></table>
          {data.invitations.length > 0 && (<><h3 className="mt-6 text-sm font-semibold">Pending invitations</h3>
            <ul className="mt-2 space-y-1 text-sm">{data.invitations.map((i: any) => (
              <li key={i.id} className="flex justify-between">{i.email} · {i.role}{isAdmin && <button className="text-xs text-red-600" onClick={() => act.run(async () => { await del(`/orgs/${orgId}/invitations/${i.id}`); reload(); })}>Revoke</button>}</li>))}</ul></>)}
        </Card>
        {isAdmin && (
          <Card title="Invite a teammate">
            <div className="space-y-3">
              <Field label="Email"><input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
              <Field label="Role" hint="Viewers read; editors run audits and draft fixes; admins approve, publish and manage integrations; owners manage billing.">
                <select className="input" value={newRole} onChange={(e) => setNewRole(e.target.value)}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></Field>
              <Button busy={act.busy} onClick={() => act.run(async () => { const r = await post<any>(`/orgs/${orgId}/invitations`, { email, role: newRole }); setLink(r.invite_url); setEmail(""); reload(); })}>Create invitation</Button>
              {link && <Notice kind="success">Share this link with your teammate (valid 7 days):<div className="mono mt-1 break-all text-xs">{link}</div></Notice>}
            </div>
          </Card>
        )}
      </div>
    </>
  );
}
