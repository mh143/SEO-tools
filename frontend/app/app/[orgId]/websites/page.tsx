"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, CalendarClock, Globe, Link2 } from "lucide-react";
import { useState } from "react";
import { Button, Card, Empty, ErrorState, Field, Loading, Notice, PageHeader, timeAgo, useAction } from "@/components/ui";
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
      <PageHeader title="Websites" subtitle="Every site you audit, monitor and publish fixes to." />
      {hasRole(role, "editor") && (
        <Card title="Add a website" icon={Link2} subtitle="Only publicly accessible sites can be audited. We respect robots.txt and never log in to your site." className="mb-8">
          <form onSubmit={add} className="grid gap-3 md:grid-cols-[2fr_1fr_auto] md:items-end" data-testid="add-website">
            <Field label="Website URL"><input className="input h-11" required placeholder="https://example.com" value={url} onChange={(e) => setUrl(e.target.value)} name="url" inputMode="url" /></Field>
            <Field label="Name (optional)"><input className="input h-11" placeholder="Marketing site" value={name} onChange={(e) => setName(e.target.value)} name="name" /></Field>
            <Button type="submit" busy={act.busy} className="h-11">Add website</Button>
          </form>
          {act.error && <div className="mt-4"><Notice kind="error">{act.error}</Notice></div>}
        </Card>
      )}
      {loading && <Loading />}
      <ErrorState error={error} onRetry={reload} />
      {data && data.length === 0 && <Empty icon={Globe} title="No websites yet">Add a website above to start auditing.</Empty>}
      {data && data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((w) => (
            <Link key={w.id} href={`/app/${orgId}/websites/${w.id}`}
              className="group rounded-2xl border border-ink-200/80 bg-white p-5 no-underline shadow-card transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-lift">
              <div className="flex items-start justify-between">
                <span className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-brand-50 to-violet-50 text-brand-600 ring-1 ring-brand-100"><Globe className="h-5 w-5" /></span>
                <ArrowUpRight className="h-5 w-5 text-ink-300 transition group-hover:text-brand-600" />
              </div>
              <div className="mt-4 font-semibold text-ink-900">{w.name}</div>
              <div className="mt-0.5 truncate text-sm text-ink-500">{w.root_url}</div>
              <div className="mt-4 flex items-center gap-4 border-t border-ink-100 pt-4 text-xs text-ink-500">
                <span className="inline-flex items-center gap-1.5 capitalize"><CalendarClock className="h-3.5 w-3.5" />{w.schedule === "none" ? "Manual audits" : `${w.schedule} audits`}</span>
                {w.created_at && <span>Added {timeAgo(w.created_at)}</span>}
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
