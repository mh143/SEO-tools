"use client";
import Link from "next/link";
import { Footer, PublicNav } from "@/components/PublicNav";
import { ErrorState, Loading, Notice } from "@/components/ui";
import { useApi } from "@/lib/hooks";

export default function Pricing() {
  const { data, error, loading, reload } = useApi<any>("/public/plans");
  return (
    <>
      <PublicNav />
      <main className="mx-auto max-w-6xl px-4 py-12">
        <h1 className="text-center text-3xl font-bold">Simple pricing</h1>
        <p className="mt-2 text-center text-slate-600">Prices in CAD per month. Cancel any time.</p>
        {data?.billing_mode === "dev" && (
          <div className="mx-auto mt-4 max-w-2xl"><Notice kind="warning">Development billing mode: upgrades are simulated and no payment is taken.</Notice></div>
        )}
        {loading && <Loading />}
        <ErrorState error={error} onRetry={reload} />
        <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {data?.plans?.map((p: any) => (
            <div key={p.key} className={`rounded-lg border bg-white p-6 ${p.key === "pro" ? "border-brand-500 ring-2 ring-brand-100" : "border-slate-200"}`}>
              <h2 className="text-lg font-semibold">{p.name}</h2>
              <div className="mt-2 text-3xl font-bold">${p.price_cad_month}<span className="text-sm font-normal text-slate-500">/mo</span></div>
              <ul className="mt-4 space-y-2 text-sm text-slate-700">
                {p.features.map((f: string) => <li key={f}>✓ {f}</li>)}
              </ul>
              <Link href="/signup" className="mt-6 block rounded-md bg-brand-600 px-3 py-2 text-center text-sm font-medium text-white no-underline hover:bg-brand-700 hover:no-underline">
                {p.price_cad_month === 0 ? "Start free" : `Choose ${p.name}`}
              </Link>
            </div>
          ))}
        </div>
        {data && <p className="mt-6 text-center text-xs text-slate-500">{data.note} Plan limits are enforced on our servers; usage is shown in your billing page.</p>}
      </main>
      <Footer />
    </>
  );
}
