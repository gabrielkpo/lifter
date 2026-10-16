import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import ServiceWorker from "@/components/ServiceWorker";
import Splash from "@/components/Splash";
import TabBar from "@/components/TabBar";
import "./globals.css";

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
        <main className="app">{children}</main>
        <TabBar />
        <ServiceWorker />
        <Splash />
      </body>
    </html>
  );
}
