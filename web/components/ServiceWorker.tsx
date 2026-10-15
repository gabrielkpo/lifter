"use client";

import { useEffect } from "react";

/** Registers public/sw.js in production builds (a service worker gets in the way of dev). */
export default function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return null;
}
