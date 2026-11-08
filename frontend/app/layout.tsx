import "@fontsource-variable/inter";
import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: { default: "RankLens — Technical SEO, AEO & GEO audits", template: "%s · RankLens" },
  description: "Audit any website for technical SEO, answer-engine and generative-search readiness, with evidence, reviewable fixes and verified publishing to WordPress, Shopify and Wix.",
};

export const viewport: Viewport = { themeColor: "#523deb" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
