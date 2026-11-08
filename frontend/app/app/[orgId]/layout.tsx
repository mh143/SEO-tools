"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ChevronsUpDown, CreditCard, FileText, Globe, History, KeyRound, LayoutDashboard, LogOut, Menu,
  Plug, Settings, Shield, Sparkles, Users, Wand2, X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ButtonLink, cx, ErrorState, Logo, Spinner } from "@/components/ui";
import { api, post } from "@/lib/api";
import { Me, SessionContext } from "@/lib/session";

const NAV: { group: string; items: [string, string, any][] }[] = [
  { group: "Workspace", items: [["", "Overview", LayoutDashboard], ["/websites", "Websites", Globe], ["/fixes", "Fix queue", Wand2], ["/changes", "Change history", History]] },
  { group: "Insights", items: [["/keywords", "Keywords", KeyRound], ["/reports", "Reports", FileText]] },
  { group: "Manage", items: [["/integrations", "Integrations", Plug], ["/team", "Team", Users], ["/billing", "Billing & usage", CreditCard], ["/settings", "Settings", Settings]] },
];

function initials(s: string) {
  const p = s.split(/[\s@._-]+/).filter(Boolean);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || "")).toUpperCase() || "U";
}

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
  useEffect(() => setMenu(false), [pathname]);

  if (error) return <div className="p-8"><ErrorState error={error} /></div>;
  if (!me) return <div className="grid min-h-screen place-items-center"><div className="flex items-center gap-3 text-sm text-ink-500"><Spinner /> Loading your workspace…</div></div>;
  const org = me.organizations.find((o) => o.id === params.orgId);
  if (!org) return (
    <div className="grid min-h-screen place-items-center p-6">
      <div className="w-full max-w-md space-y-4 text-center">
        <Logo />
        <ErrorState error="Workspace not found or you do not have access." />
        <ButtonLink href="/app" variant="secondary">Go to my workspace</ButtonLink>
      </div>
    </div>
  );
  const base = `/app/${params.orgId}`;

  async function logout() {
    await post("/auth/logout");
    router.replace("/login");
  }

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center justify-between px-5">
        <Link href={base} className="link-plain"><Logo /></Link>
        <button className="rounded-lg p-1.5 text-ink-500 hover:bg-ink-100 md:hidden" onClick={() => setMenu(false)} aria-label="Close menu"><X className="h-5 w-5" /></button>
      </div>
      <div className="px-3">
        <label className="relative block">
          <span className="sr-only">Workspace</span>
          <span className="pointer-events-none absolute left-2.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-violet-500 text-xs font-semibold text-white">{initials(org.name)}</span>
          <select className="h-12 w-full cursor-pointer appearance-none rounded-xl border border-ink-200 bg-white pl-12 pr-9 text-sm font-semibold text-ink-900 shadow-sm hover:border-ink-300 focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-100"
            value={params.orgId} aria-label="Workspace" onChange={(e) => router.push(`/app/${e.target.value}`)}>
            {me.organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <ChevronsUpDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
        </label>
        <div className="mt-2 flex items-center gap-2 px-1 text-xs text-ink-500">
          <span className="capitalize">{org.role}</span><span className="h-1 w-1 rounded-full bg-ink-300" />
          <span className="rounded-full bg-brand-50 px-2 py-0.5 font-medium capitalize text-brand-700">{org.plan_key} plan</span>
        </div>
      </div>
      <nav className="mt-6 flex-1 space-y-6 overflow-y-auto px-3 pb-6">
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-400">{g.group}</div>
            <div className="space-y-0.5">
              {g.items.map(([p, label, Icon]) => {
                const href = base + p;
                const active = p === "" ? pathname === base : pathname.startsWith(href);
                return (
                  <Link key={p} href={href} aria-current={active ? "page" : undefined}
                    className={cx("group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium no-underline transition",
                      active ? "bg-white text-ink-900 shadow-card ring-1 ring-ink-200/80" : "text-ink-600 hover:bg-white/70 hover:text-ink-900")}>
                    <Icon className={cx("h-[18px] w-[18px]", active ? "text-brand-600" : "text-ink-400 group-hover:text-ink-600")} />
                    {label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
        {me.is_platform_admin && (
          <Link href="/admin" className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-ink-600 no-underline hover:bg-white/70 hover:text-ink-900">
            <Shield className="h-[18px] w-[18px] text-ink-400" /> Admin
          </Link>
        )}
      </nav>
      {org.plan_key === "free" && (
        <div className="mx-3 mb-3 rounded-xl bg-gradient-to-br from-brand-600 to-violet-600 p-4 text-white shadow-glow">
          <div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4" /> Unlock publishing</div>
          <p className="mt-1 text-xs leading-relaxed text-brand-100">Publish verified fixes to WordPress, Shopify & Wix and monitor your sites.</p>
          <Link href={`${base}/billing`} className="mt-3 inline-flex rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-brand-700 no-underline hover:bg-brand-50">Upgrade plan</Link>
        </div>
      )}
      <div className="border-t border-ink-200/70 p-3">
        <div className="flex items-center gap-3 rounded-lg px-2 py-2">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink-900 text-xs font-semibold text-white">{initials(me.name || me.email)}</span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-ink-900">{me.name || me.email.split("@")[0]}</div>
            <div className="truncate text-xs text-ink-500">{me.email}</div>
          </div>
          <button className="rounded-lg p-2 text-ink-400 hover:bg-ink-100 hover:text-ink-900" onClick={logout} data-testid="logout" title="Log out" aria-label="Log out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <SessionContext.Provider value={{ me, orgId: params.orgId, role: org.role, refresh }}>
      <div className="min-h-screen bg-ink-50">
        <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-ink-200/70 bg-ink-50 md:block">{sidebar}</aside>
        {menu && (
          <div className="fixed inset-0 z-50 md:hidden">
            <div className="absolute inset-0 bg-ink-950/40 backdrop-blur-sm" onClick={() => setMenu(false)} />
            <aside className="absolute inset-y-0 left-0 w-72 animate-fade-up bg-ink-50 shadow-lift">{sidebar}</aside>
          </div>
        )}
        <div className="md:pl-64">
          <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-ink-200/70 bg-white/80 px-4 backdrop-blur-xl md:hidden">
            <button className="rounded-lg p-2 text-ink-700 hover:bg-ink-100" onClick={() => setMenu(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
            <Link href={base} className="link-plain"><Logo /></Link>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 md:py-10 lg:px-10">{children}</main>
        </div>
      </div>
    </SessionContext.Provider>
  );
}

