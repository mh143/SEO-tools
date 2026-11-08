import { BarChart3, Globe, ShoppingBag, Sparkles, Store } from "lucide-react";
import { cx } from "./ui";

// Neutral, generic marks for each platform (not the platforms' logos).
const MARKS: Record<string, { bg: string; icon: any; label: string }> = {
  wordpress: { bg: "bg-[#21759b]", icon: Globe, label: "WordPress" },
  shopify: { bg: "bg-[#5e8e3e]", icon: ShoppingBag, label: "Shopify" },
  wix: { bg: "bg-ink-900", icon: Sparkles, label: "Wix" },
  google_search_console: { bg: "bg-gradient-to-br from-sky-500 to-indigo-500", icon: BarChart3, label: "Search Console" },
  webflow: { bg: "bg-[#4353ff]", icon: Store, label: "Webflow" },
};

export function providerLabel(p: string) {
  return MARKS[p]?.label || p;
}

export function ProviderMark({ provider, size = "md" }: { provider: string; size?: "sm" | "md" | "lg" }) {
  const m = MARKS[provider] || { bg: "bg-ink-500", icon: Globe };
  const Icon = m.icon;
  const s = { sm: "h-7 w-7 rounded-lg", md: "h-10 w-10 rounded-xl", lg: "h-12 w-12 rounded-2xl" }[size];
  const i = { sm: "h-3.5 w-3.5", md: "h-5 w-5", lg: "h-6 w-6" }[size];
  return <span className={cx("grid shrink-0 place-items-center text-white shadow-sm", s, m.bg)}><Icon className={i} aria-hidden /></span>;
}
