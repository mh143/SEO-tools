"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Field, Loading, Notice, PageHeader, useAction } from "@/components/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

const SRC: Record<string, [string, string]> = {
  measured: ["Measured", "bg-emerald-100 text-emerald-800"], ai_idea: ["AI idea · not measured", "bg-violet-100 text-violet-800"],
  on_page: ["On your site", "bg-ink-100 text-ink-700"],
};

export default function Keywords() {
  const { orgId, role } = useSession();
  const { data: sites } = useApi<any[]>(`/orgs/${orgId}/websites`);
  const pre = useSearchParams().get("website");
  const [chosen, setChosen] = useState<string | null>(pre);
  const websiteId = chosen || sites?.[0]?.id || null;
  const { data, error, loading, reload } = useApi<any>(websiteId ? `/orgs/${orgId}/websites/${websiteId}/keywords` : null);
  const [seeds, setSeeds] = useState("");
  const [location, setLocation] = useState("Canada");
  const act = useAction();
  const canEdit = hasRole(role, "editor");

  if (sites && sites.length === 0) return <><PageHeader title="Keyword opportunities" /><Empty title="Add a website first" action={<Link href={`/app/${orgId}/websites`}>Add website</Link>} /></>;
  return (
    <>
      <PageHeader title="Keyword opportunities" subtitle="Measured data comes only from a named provider. AI ideas are labelled and carry no metrics."
        actions={sites && <select className="input w-56" value={websiteId || ""} onChange={(e) => setChosen(e.target.value)} aria-label="Website">{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>} />
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      {loading && <Loading />}
      <ErrorState error={error} onRetry={reload} />
      {data && (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <Card title={`Keywords (${data.keywords.length})`}>
              {data.keywords.length === 0 ? <Empty title="No keyword data yet">Extract terms from your site, ask for AI ideas, or fetch measured data.</Empty> : (
                <table className="table-clean"><thead><tr><th>Keyword</th><th>Source</th><th>Volume</th><th>Difficulty</th><th>Intent</th><th>Best page</th></tr></thead>
                  <tbody>{data.keywords.map((k: any) => (
                    <tr key={k.id}>
                      <td className="py-2 font-medium">{k.keyword}{k.notes && <div className="text-xs font-normal text-ink-500">{k.notes}</div>}</td>
                      <td><Badge tone={SRC[k.source]?.[1]}>{SRC[k.source]?.[0] || k.source}</Badge>{k.data_provider && <div className="text-xs text-ink-500">{k.data_provider}</div>}</td>
                      <td className="tabular-nums">{k.search_volume ?? "—"}</td><td className="tabular-nums">{k.difficulty ?? "—"}</td><td>{k.intent || "—"}</td>
                      <td className="max-w-[200px] break-all text-xs">{k.related_url ? <a href={k.related_url} target="_blank" rel="noreferrer noopener">{k.related_url}</a> : <span className="text-amber-700">content gap</span>}</td>
                    </tr>))}</tbody></table>
              )}
            </Card>
          </div>
          {canEdit && (
            <div className="space-y-4">
              <Card title="Measured search data">
                {!data.providers.measured.configured ? <Notice kind="info">No keyword data provider is configured. Set DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD to enable search volumes and difficulty.</Notice> : (
                  <div className="space-y-2">
                    <Field label="Seed keywords (comma separated)"><input className="input" value={seeds} onChange={(e) => setSeeds(e.target.value)} /></Field>
                    <Field label="Location"><input className="input" value={location} onChange={(e) => setLocation(e.target.value)} /></Field>
                    <Button busy={act.busy} onClick={() => act.run(async () => { await post(`/orgs/${orgId}/websites/${websiteId}/keywords/research`, { seeds: seeds.split(",").map((s) => s.trim()).filter(Boolean), location }); reload(); })}>Fetch data</Button>
                    <p className="text-xs text-ink-500">Source: {data.providers.measured.name}</p>
                  </div>
                )}
              </Card>
              <Card title="Ideas">
                <div className="flex flex-col gap-2">
                  <Button variant="secondary" busy={act.busy} onClick={() => act.run(async () => { await post(`/orgs/${orgId}/websites/${websiteId}/keywords/on-page`); reload(); })}>Extract terms from my site</Button>
                  <Button variant="secondary" busy={act.busy} disabled={!data.providers.ai.configured} onClick={() => act.run(async () => { await post(`/orgs/${orgId}/websites/${websiteId}/keywords/ideas`); reload(); })}>Suggest AI ideas</Button>
                  {!data.providers.ai.configured && <p className="text-xs text-ink-500">AI provider not configured.</p>}
                  <p className="text-xs text-ink-500">AI ideas are hypotheses to validate with measured data — not demand estimates.</p>
                </div>
              </Card>
            </div>
          )}
        </div>
      )}
    </>
  );
}
