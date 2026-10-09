"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, Empty, ErrorState, Field, Loading, Notice, PageHeader, useAction } from "@/components/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

export default function Websites() {
  const { orgId, role } = useSession();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<any[]>(`/orgs/${orgId}/websites`);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const act = useAction();

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const w = await act.run(() => post<any>(`/orgs/${orgId}/websites`, { url, name: name || undefined }));
    if (w) router.push(`/app/${orgId}/websites/${w.id}`);
  }

  return (
    <>
      <PageHeader title="Websites" />
      {hasRole(role, "editor") && (
        <Card title="Add a website" className="mb-6">
          <form onSubmit={add} className="grid gap-3 md:grid-cols-[2fr_1fr_auto] md:items-end" data-testid="add-website">
            <Field label="Website URL"><input className="input" required placeholder="https://example.com" value={url} onChange={(e) => setUrl(e.target.value)} name="url" /></Field>
            <Field label="Name (optional)"><input className="input" value={name} onChange={(e) => setName(e.target.value)} name="name" /></Field>
            <Button type="submit" busy={act.busy}>Add website</Button>
          </form>
          {act.error && <div className="mt-3"><Notice kind="error">{act.error}</Notice></div>}
          <p className="mt-2 text-xs text-slate-500">Only publicly accessible sites can be audited. We respect robots.txt and never log in to your site.</p>
        </Card>
      )}
      {loading && <Loading />}
      <ErrorState error={error} onRetry={reload} />
      {data && data.length === 0 && <Empty title="No websites yet">Add a website above to start auditing.</Empty>}
      {data && data.length > 0 && (
        <Card>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-2">Name</th><th>URL</th><th>Schedule</th></tr></thead>
            <tbody>
              {data.map((w) => (
                <tr key={w.id} className="border-t border-slate-100">
                  <td className="py-2"><Link href={`/app/${orgId}/websites/${w.id}`}>{w.name}</Link></td>
                  <td className="break-all text-slate-600">{w.root_url}</td><td>{w.schedule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
