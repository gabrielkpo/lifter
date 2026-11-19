import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import FreshnessBanner from "@/components/FreshnessBanner";
import ServiceWorker from "@/components/ServiceWorker";
import SignedIn from "@/components/SignedIn";
import Splash from "@/components/Splash";
import TabBar from "@/components/TabBar";
import "./globals.css";

// Rendered for each request, so the scripts carry that request's CSP nonce (proxy.ts, lib/csp):
// a page prerendered at build time would have none, and the policy would block it.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Lifter",
  description: "CrossFit coaching: the week, the sessions, PRs and recovery.",
  applicationName: "Lifter",
  appleWebApp: { capable: true, title: "Lifter", statusBarStyle: "black-translucent" },
  // A personal app: never indexed.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#121212",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <main className="app">
          <SignedIn>
            <FreshnessBanner />
          </SignedIn>
          {children}
        </main>
        <SignedIn>
          <TabBar />
          <Splash />
        </SignedIn>
        <ServiceWorker />
      </body>
    </html>
  );
}
