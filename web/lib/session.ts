// The app's own sign-in, a second lock behind the platform's deployment protection: every page
// and every /api call needs a session cookie that only this server can sign (proxy.ts). The
// athlete signs in with a passphrase (app/auth/login). Without its two secrets the app opens
// for nobody, in any environment: there is no unlocked mode.
//
// A session is "v1.<expiry>.<signature>": the expiry in seconds since the epoch, signed with
// HMAC-SHA256 under a key derived from LIFTER_SESSION_KEY and the passphrase, so changing
// either signs every device out. Web Crypto only: the same code runs in the proxy, the route
// handlers and node:test.

export const LOGIN_PATH = "/login";
/** How long a device stays signed in. */
export const SESSION_SECONDS = 30 * 24 * 3600;
/** The shortest secrets accepted: shorter ones leave the app closed. */
export const MIN_PASSPHRASE = 12;
export const MIN_KEY = 32;

const VERSION = "v1";
const encoder = new TextEncoder();

export type SessionSecrets = { key: CryptoKey; passphrase: string };

/** The cookie's name: on https, `__Host-` makes the browser refuse it unless it is Secure,
 * host-only and for the whole site. */
export function cookieName(secure: boolean): string {
  return secure ? "__Host-lifter_session" : "lifter_session";
}

/** The signing key, or null when a secret is missing or too short (the app then stays closed). */
export async function sessionSecrets(
  env: Record<string, string | undefined>,
): Promise<SessionSecrets | null> {
  const passphrase = env.LIFTER_APP_PASSPHRASE ?? "";
  const secret = env.LIFTER_SESSION_KEY ?? "";
  if (passphrase.length < MIN_PASSPHRASE || secret.length < MIN_KEY) return null;
  const root = await hmacKey(encoder.encode(secret));
  // A key of its own for the sessions, tied to the passphrase.
  const derived = await crypto.subtle.sign("HMAC", root, encoder.encode(`session|${passphrase}`));
  return { key: await hmacKey(new Uint8Array(derived)), passphrase };
}

/** A new session, valid for SESSION_SECONDS from `now` (ms). */
export async function issueSession(secrets: SessionSecrets, now: number): Promise<string> {
  const expiry = Math.floor(now / 1000) + SESSION_SECONDS;
  const payload = `${VERSION}.${expiry}`;
  const signature = await crypto.subtle.sign("HMAC", secrets.key, encoder.encode(payload));
  return `${payload}.${base64url(new Uint8Array(signature))}`;
}

/** True when `token` was signed by this server and has not expired at `now` (ms). */
export async function verifySession(
  secrets: SessionSecrets | null,
  token: string | undefined,
  now: number,
): Promise<boolean> {
  if (!secrets || !token) return false;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== VERSION || !/^\d{1,12}$/.test(parts[1])) return false;
  const expiry = Number(parts[1]);
  const seconds = Math.floor(now / 1000);
  if (expiry <= seconds || expiry > seconds + SESSION_SECONDS) return false;
  const signature = fromBase64url(parts[2]);
  if (!signature) return false;
  // Compared by Web Crypto, in constant time.
  return crypto.subtle.verify(
    "HMAC",
    secrets.key,
    signature,
    encoder.encode(`${VERSION}.${parts[1]}`),
  );
}

/** True when `given` is the passphrase, compared in constant time (both are signed first, so
 * neither their length nor their first differing character shows in the timing). */
export async function passphraseMatches(secrets: SessionSecrets, given: string): Promise<boolean> {
  const label = (text: string) => encoder.encode(`passphrase|${text}`);
  const expected = await crypto.subtle.sign("HMAC", secrets.key, label(secrets.passphrase));
  return crypto.subtle.verify("HMAC", secrets.key, expected, label(given));
}

/** Where to go once signed in: a page of this app, never another site, the sign-in itself, an
 * /auth form target or an /api answer. Resolved the way the browser will (the URL parser drops
 * tabs and newlines and reads "\\" as "/"), then checked. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/")) return "/";
  const base = "http://app.invalid";
  let url: URL;
  try {
    url = new URL(next, base);
  } catch {
    return "/";
  }
  const path = url.pathname;
  if (
    url.origin !== base ||
    path === LOGIN_PATH ||
    path.startsWith("/auth/") ||
    path === "/api" ||
    path.startsWith("/api/")
  ) {
    return "/";
  }
  return `${path}${url.search}`;
}

/** Paths anyone may load: the sign-in page and what it needs, and the files a phone fetches to
 * install the app (no data in any of them). Everything else needs a session. */
export function isPublicPath(pathname: string): boolean {
  return (
    pathname === LOGIN_PATH ||
    pathname === "/auth/login" ||
    pathname.startsWith("/_next/static/") ||
    pathname === "/manifest.webmanifest" ||
    pathname === "/sw.js" ||
    pathname === "/icon.svg" ||
    pathname === "/apple-icon" ||
    pathname.startsWith("/icons/")
  );
}

async function hmacKey(raw: Uint8Array<ArrayBuffer>): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

function base64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function fromBase64url(text: string): Uint8Array<ArrayBuffer> | null {
  if (!/^[A-Za-z0-9_-]{43}$/.test(text)) return null; // a SHA-256 signature, 32 bytes
  const binary = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=");
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
}
