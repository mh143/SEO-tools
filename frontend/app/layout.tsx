import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "RankLens — Technical SEO, AEO & GEO audits",
  description: "Audit any website for technical SEO, answer-engine and generative-search readiness, with evidence and reviewable fixes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
