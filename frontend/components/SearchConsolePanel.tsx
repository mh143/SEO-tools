"use client";
import { ArrowRight, BarChart3 } from "lucide-react";
import { useState } from "react";
import { AreaChart } from "./AreaChart";
import { ProviderMark } from "./Providers";
import { ButtonLink, Card, cx, ErrorState, Skeleton } from "./ui";
import { useApi } from "@/lib/hooks";

const METRICS = [
  { key: "clicks", label: "Clicks", fmt: (v: number) => Math.round(v).toLocaleString() },
  { key: "impressions", label: "Impressions", fmt: (v: number) => Math.round(v).toLocaleString() },
  { key: "ctr", label: "Avg. CTR", fmt: (v: number) => `${(v * 100).toFixed(1)}%` },
  { key: "position", label: "Avg. position", fmt: (v: number) => v.toFixed(1), invert: true },
] as const;

export function SearchConsolePanel({ orgId, websiteId }: { orgId: string; websiteId: string }) {
  const [days, setDays] = useState(28);
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>("clicks");
  const { data, error, loading, reload } = useApi<any>(`/orgs/${orgId}/websites/${websiteId}/search-console?days=${days}`);
  const m = METRICS.find((x) => x.key === metric)!;

  if (loading && !data) return <Card><Skeleton className="h-64" /></Card>;
  if (error) return <Card title="Search performance" icon={BarChart3}><ErrorState error={error} onRetry={reload} /></Card>;
  if (!data?.connected) return (
    <Card>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <ProviderMark provider="google_search_console" size="lg" />
        <div className="flex-1">
          <h2 className="text-[15px] font-semibold text-ink-900">See real search performance</h2>
          <p className="mt-1 text-sm text-ink-500">Connect Google Search Console to show clicks, impressions, CTR and average position for this site next to your audit.
            {!data?.configured && " (Your administrator must configure Google OAuth first.)"}</p>
        </div>
        <ButtonLink href={`/app/${orgId}/integrations`} variant="secondary">Connect <ArrowRight className="h-4 w-4" /></ButtonLink>
      </div>
    </Card>
  );

  const series = (data.by_date || []).map((r: any) => ({ x: r.date, y: r[metric] }));
  return (
    <Card title="Search performance" icon={BarChart3}
      subtitle={<>Google Search Console · {data.property} · {data.start_date} → {data.end_date}</>}
      actions={
        <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5 text-xs font-medium" role="group" aria-label="Date range">
          {[7, 28, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)} aria-pressed={days === d}
              className={cx("rounded-md px-2.5 py-1", days === d ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-ink-50")}>{d}d</button>
          ))}
        </div>}>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4" role="tablist" aria-label="Metric">
        {METRICS.map((x) => {
          const v = data.totals?.[x.key];
          return (
            <button key={x.key} role="tab" aria-selected={metric === x.key} onClick={() => setMetric(x.key)}
              className={cx("rounded-xl border p-3 text-left transition",
                metric === x.key ? "border-brand-300 bg-brand-50/60 ring-1 ring-brand-200" : "border-ink-200/80 hover:bg-ink-50")}>
              <div className="text-xs font-medium text-ink-500">{x.label}</div>
              <div className="mt-1 text-xl font-semibold tabular-nums text-ink-900">{v === null || v === undefined ? "–" : x.fmt(v)}</div>
            </button>
          );
        })}
      </div>
      <div className="mt-5"><AreaChart data={series} format={m.fmt} invert={"invert" in m && m.invert} label={m.label} /></div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {[["Top queries", "top_queries", "query"], ["Top pages", "top_pages", "page"]].map(([title, key, col]) => (
          <div key={key}>
            <h3 className="mb-2 text-sm font-semibold text-ink-900">{title}</h3>
            {(data[key] || []).length === 0 ? <p className="text-sm text-ink-500">No data yet.</p> : (
              <div className="overflow-x-auto rounded-xl border border-ink-100">
                <table className="table-clean">
                  <thead><tr><th>{col}</th><th className="text-right">Clicks</th><th className="text-right">Impr.</th><th className="text-right">Pos.</th></tr></thead>
                  <tbody>{data[key].slice(0, 10).map((r: any) => (
                    <tr key={r[col]}>
                      <td className="max-w-[16rem] truncate" title={r[col]}>{col === "page" ? r[col].replace(/^https?:\/\/[^/]+/, "") || "/" : r[col]}</td>
                      <td className="text-right tabular-nums">{r.clicks.toLocaleString()}</td>
                      <td className="text-right tabular-nums">{r.impressions.toLocaleString()}</td>
                      <td className="text-right tabular-nums">{r.position.toFixed(1)}</td>
                    </tr>))}</tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-ink-500">Measured data from Google. Search Console reports with a ~2 day delay.</p>
    </Card>
  );
}
