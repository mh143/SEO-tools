"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { useEffect, useState } from "react";
import { ButtonLink, cx, Logo } from "./ui";

const LINKS = [["/#features", "Features"], ["/#how", "How it works"], ["/#integrations", "Integrations"], ["/pricing", "Pricing"]];

export function PublicNav() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const path = usePathname();
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <header className={cx("sticky top-0 z-40 transition-all", scrolled ? "border-b border-ink-200/70 bg-white/80 backdrop-blur-xl" : "bg-transparent")}>
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="link-plain" aria-label="RankLens home"><Logo /></Link>
        <nav className="hidden items-center gap-1 md:flex">
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href} className={cx("rounded-lg px-3 py-2 text-sm font-medium no-underline transition",
              path === href ? "text-ink-900" : "text-ink-600 hover:bg-ink-100/70 hover:text-ink-900")}>{label}</Link>
          ))}
        </nav>
        <div className="hidden items-center gap-2 md:flex">
          <Link href="/login" className="rounded-lg px-3 py-2 text-sm font-medium text-ink-700 no-underline hover:text-ink-900">Log in</Link>
          <ButtonLink href="/signup" size="sm" className="h-9 px-4">Start free</ButtonLink>
        </div>
        <button className="rounded-lg p-2 text-ink-700 hover:bg-ink-100 md:hidden" onClick={() => setOpen(!open)} aria-label="Menu" aria-expanded={open}>
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>
      {open && (
        <div className="border-t border-ink-200/70 bg-white px-4 pb-4 pt-2 md:hidden">
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href} onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2.5 text-sm font-medium text-ink-700 no-underline hover:bg-ink-50">{label}</Link>
          ))}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <ButtonLink href="/login" variant="secondary">Log in</ButtonLink>
            <ButtonLink href="/signup">Start free</ButtonLink>
          </div>
        </div>
      )}
    </header>
  );
}

export function Footer() {
  const cols: [string, [string, string][]][] = [
    ["Product", [["/#features", "Features"], ["/pricing", "Pricing"], ["/#integrations", "Integrations"], ["/#faq", "FAQ"]]],
    ["Audits", [["/#features", "Technical SEO"], ["/#features", "Answer Engine (AEO)"], ["/#features", "Generative Engine (GEO)"], ["/", "Free quick audit"]]],
    ["Account", [["/signup", "Create account"], ["/login", "Log in"], ["/pricing", "Compare plans"]]],
  ];
  return (
    <footer className="border-t border-ink-200/70 bg-white">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div>
          <Logo />
          <p className="mt-4 max-w-xs text-sm leading-relaxed text-ink-500">
            Evidence-based audits for search engines and AI answer engines, with fixes you approve and changes we verify on your live site.
          </p>
        </div>
        {cols.map(([h, links]) => (
          <div key={h}>
            <div className="text-xs font-semibold uppercase tracking-wider text-ink-400">{h}</div>
            <ul className="mt-4 space-y-2.5">
              {links.map(([href, label]) => <li key={label}><Link href={href} className="text-sm text-ink-600 no-underline hover:text-ink-900">{label}</Link></li>)}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-ink-100">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-xs text-ink-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span>© {new Date().getFullYear()} RankLens. All rights reserved.</span>
          <span className="max-w-2xl sm:text-right">Audits are automated and should be reviewed by a person. We never promise rankings, traffic or AI citations; scores are internal heuristics.</span>
        </div>
      </div>
    </footer>
  );
}
