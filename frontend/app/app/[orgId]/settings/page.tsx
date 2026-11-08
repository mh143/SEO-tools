"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, Field, Notice, PageHeader, useAction } from "@/components/ui";
import { del, patch, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

export default function Settings() {
  const { orgId, role, refresh } = useSession();
  const router = useRouter();
  const { data: org, reload } = useApi<any>(`/orgs/${orgId}`);
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [color, setColor] = useState("#2563eb");
  const [pw, setPw] = useState({ current: "", next: "" });
  const [delPw, setDelPw] = useState("");
  const act = useAction();
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => { if (org) { setName(org.name); setCompany(org.branding.report_company_name || ""); setColor(org.branding.report_accent_color || "#2563eb"); } }, [org?.id]);

  return (
    <>
      <PageHeader title="Settings" />
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      {saved && <div className="mb-4"><Notice kind="success">{saved}</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-2">
        {hasRole(role, "admin") && (
          <Card title="Workspace & report branding">
            <div className="space-y-3">
              <Field label="Workspace name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <Field label="Company name on reports" hint="Shown instead of RankLens branding on Agency plans."><input className="input" value={company} onChange={(e) => setCompany(e.target.value)} /></Field>
              <Field label="Report accent colour"><input className="input h-10" type="color" value={color} onChange={(e) => setColor(e.target.value)} /></Field>
              <Button busy={act.busy} onClick={() => act.run(async () => { await patch(`/orgs/${orgId}`, { name, report_company_name: company, report_accent_color: color }); setSaved("Saved."); reload(); refresh(); })}>Save</Button>
            </div>
          </Card>
        )}
        <Card title="Change password">
          <div className="space-y-3">
            <Field label="Current password"><input className="input" type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" /></Field>
            <Field label="New password"><input className="input" type="password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" /></Field>
            <Button variant="secondary" busy={act.busy} onClick={() => act.run(async () => { await post(`/auth/password`, { current_password: pw.current, new_password: pw.next }); setPw({ current: "", next: "" }); setSaved("Password changed. Other sessions were signed out."); })}>Change password</Button>
          </div>
        </Card>
        <Card title="Data & deletion" className="border-red-200">
          <div className="space-y-4 text-sm">
            <p className="text-ink-600">Page snapshots are kept for a limited period and anonymous audits expire automatically. Deleting a website removes its audits, snapshots, fixes and integration credentials.</p>
            {role === "owner" && (
              <Button variant="danger" busy={act.busy} onClick={() => act.run(async () => {
                if (prompt(`Type the workspace name (${org?.name}) to permanently delete it and all its data`) !== org?.name) return;
                await del(`/orgs/${orgId}`); router.push("/app");
              })}>Delete workspace</Button>
            )}
            <div className="border-t pt-4">
              <Field label="Delete my account (confirm with password)"><input className="input" type="password" value={delPw} onChange={(e) => setDelPw(e.target.value)} /></Field>
              <p className="mt-1 text-xs text-ink-500">Workspaces where you are the only owner are deleted too.</p>
              <div className="mt-2"><Button variant="danger" size="sm" busy={act.busy} onClick={() => act.run(async () => { if (!confirm("Permanently delete your account?")) return; await post(`/auth/delete-account`, { password: delPw }); router.push("/"); })}>Delete account</Button></div>
            </div>
          </div>
        </Card>
        {hasRole(role, "admin") && <AuditLogCard orgId={orgId} />}
      </div>
    </>
  );
}

function AuditLogCard({ orgId }: { orgId: string }) {
  const { data } = useApi<any[]>(`/orgs/${orgId}/audit-logs?limit=50`);
  return (
    <Card title="Security audit log">
      <ul className="max-h-80 space-y-1 overflow-auto text-xs">{data?.map((l) => (
        <li key={l.id} className="flex justify-between gap-2 border-b border-ink-100 py-1"><span className="mono">{l.action}</span><span className="text-ink-500">{new Date(l.created_at).toLocaleString()} · {l.ip || ""}</span></li>))}</ul>
    </Card>
  );
}
