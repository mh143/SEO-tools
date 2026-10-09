import Link from "next/link";

export function PublicNav() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <Link href="/" className="text-lg font-semibold text-slate-900 no-underline hover:no-underline">
          Rank<span className="text-brand-600">Lens</span>
        </Link>
        <nav className="flex items-center gap-5 text-sm">
          <Link href="/pricing" className="text-slate-700">Pricing</Link>
          <Link href="/login" className="text-slate-700">Log in</Link>
          <Link href="/signup" className="rounded-md bg-brand-600 px-3 py-1.5 text-white no-underline hover:bg-brand-700 hover:no-underline">
            Start free
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="mt-16 border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-6xl px-4 py-6 text-xs text-slate-500">
        RankLens audits are automated and should be reviewed by a person. We never promise rankings, traffic or AI
        citations. Scores are internal heuristics, not an industry standard.
      </div>
    </footer>
  );
}
