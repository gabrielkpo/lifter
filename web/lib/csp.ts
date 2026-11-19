// The Content-Security-Policy of every response (proxy.ts): the browser runs only this app's
// scripts, the ones Next.js marks with the request's nonce, and loads nothing from elsewhere.
// The app has no third-party script, font or image; the coach's words are rendered as text
// (lib/markdown), so this is a second barrier, not the first.

/** A fresh nonce for one request: 16 random bytes, base64. */
export function newNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes));
}

/** The policy for one response. `dev` adds what Next's dev server needs (eval for React's
 * refresh, its websocket); never in production. */
export function contentSecurityPolicy(nonce: string, dev = false): string {
  const directives: [string, ...string[]][] = [
    ["default-src", "'self'"],
    ["script-src", "'self'", `'nonce-${nonce}'`, "'strict-dynamic'", ...(dev ? ["'unsafe-eval'"] : [])],
    // Style attributes (style={...}) are part of the app's layout; no stylesheet comes from
    // elsewhere.
    ["style-src", "'self'", "'unsafe-inline'"],
    ["img-src", "'self'", "data:", "blob:"],
    ["font-src", "'self'"],
    ["connect-src", "'self'", ...(dev ? ["ws:"] : [])],
    ["manifest-src", "'self'"],
    ["worker-src", "'self'"],
    ["object-src", "'none'"],
    ["base-uri", "'none'"],
    ["form-action", "'self'"],
    ["frame-ancestors", "'none'"],
  ];
  return directives.map((d) => d.join(" ")).join("; ");
}

/** Browser features the app never uses, turned off for it and anything it might embed. */
export const PERMISSIONS_POLICY = [
  "camera=()",
  "microphone=()",
  "geolocation=()",
  "payment=()",
  "usb=()",
  "bluetooth=()",
  "serial=()",
  "hid=()",
  "browsing-topics=()",
].join(", ");
