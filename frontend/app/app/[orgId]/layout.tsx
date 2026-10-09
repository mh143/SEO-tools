"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { cx, ErrorState, Loading } from "@/components/ui";
import { api, post } from "@/lib/api";
import { Me, SessionContext } from "@/lib/session";

const NAV = [
  ["", "Overview"], ["/websites", "Websites"], ["/fixes", "Fix queue"], ["/changes", "Change history"],
  ["/keywords", "Keywords"], ["/reports", "Reports"], ["/integrations", "Integrations"], ["/team", "Team"],
  ["/billing", "Billing & usage"], ["/settings", "Settings"],
];

export default function AppLayout({ children, params }: { children: React.ReactNode; params: { orgId: string } }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);

  const refresh = useCallback(() => {
    api<any>("/auth/me").then((r) => setMe(r.user)).catch((e) => {
      if (e.status === 401) router.replace("/login");
      else setError(e.message);
    });
  }, [router]);
  useEffect(refresh, [refresh]);

  if (error) return <div className="p-8"><ErrorState error={error} /></div>;
  if (!me) return <Loading />;
  const org = me.organizations.find((o) => o.id === params.orgId);
  if (!org) return <div className="p-8"><ErrorState error="Workspace not found or you do not have access." /></div>;
  const base = `/app/${params.orgId}`;

  async function logout() {
    await post("/auth/logout");
    router.replace("/login");
  }

  return (
    <SessionContext.Provider value={{ me, orgId: params.orgId, role: org.role, refresh }}>
      <div className="min-h-screen md:flex">
        <aside className={cx("border-r border-slate-200 bg-white md:block md:w-60 md:shrink-0", menu ? "block" : "hidden")}>
          <div className="px-4 py-4 text-lg font-semibold">
            <Link href={base} className="text-slate-900 no-underline hover:no-underline">Rank<span className="text-brand-600">Lens</span></Link>
          </div>
          <div className="px-3">
            <select
              className="input" value={params.orgId} aria-label="Workspace"
              onChange={(e) => router.push(`/app/${e.target.value}`)}
            >
              {me.organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
            <div className="mt-1 px-1 text-xs text-slate-500">{org.role} · {org.plan_key} plan</div>
          </div>
          <nav className="mt-4 space-y-0.5 px-2 pb-6" onClick={() => setMenu(false)}>
            {NAV.map(([p, label]) => {
              const href = base + p;
              const active = p === "" ? pathname === base : pathname.startsWith(href);
              return (
                <Link key={p} href={href}
                  className={cx("block rounded-md px-3 py-2 text-sm no-underline hover:no-underline",
                    active ? "bg-brand-50 font-medium text-brand-700" : "text-slate-700 hover:bg-slate-100")}>
                  {label}
                </Link>
              );
            })}
            {me.is_platform_admin && (
              <Link href="/admin" className="block rounded-md px-3 py-2 text-sm text-slate-700 no-underline hover:bg-slate-100 hover:no-underline">Admin</Link>
            )}
          </nav>
        </aside>
        <div className="min-w-0 flex-1">
          <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2">
            <button className="rounded border px-2 py-1 text-sm md:hidden" onClick={() => setMenu(!menu)}>Menu</button>
            <div className="ml-auto flex items-center gap-3 text-sm text-slate-600">
              <span>{me.email}</span>
              <button className="text-slate-500 hover:text-slate-900" onClick={logout} data-testid="logout">Log out</button>
            </div>
          </header>
          <main className="mx-auto max-w-6xl p-4 md:p-8">{children}</main>
        </div>
      </div>
    </SessionContext.Provider>
  );
}
