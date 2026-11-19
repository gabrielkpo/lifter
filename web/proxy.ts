import { type NextRequest, NextResponse } from "next/server";
import { contentSecurityPolicy, newNonce } from "./lib/csp";
import { allowedHosts, isAllowedHost } from "./lib/hosts";
import {
  cookieName,
  isPublicPath,
  LOGIN_PATH,
  sessionSecrets,
  verifySession,
} from "./lib/session";

const ALLOWED = allowedHosts(process.env);
const SECRETS = sessionSecrets(process.env);

const DEV = process.env.NODE_ENV === "development";

/** Refuse any request whose Host is not this app's (DNS rebinding, LAN access), then any
 * request without a session signed by this server: a page sends to the sign-in, an /api call
 * gets 401. Every answer carries the Content-Security-Policy with this request's nonce, which
 * Next.js reads from the request to mark its own scripts (lib/csp). */
export async function proxy(request: NextRequest) {
  if (!isAllowedHost(request.headers.get("host"), ALLOWED)) {
    return new NextResponse("Unknown host", { status: 400 });
  }
  const policy = contentSecurityPolicy(newNonce(), DEV);
  const secured = (response: NextResponse) => {
    response.headers.set("content-security-policy", policy);
    return response;
  };
  const pass = () => {
    const headers = new Headers(request.headers);
    headers.set("content-security-policy", policy);
    return secured(NextResponse.next({ request: { headers } }));
  };
  const { pathname, search, protocol } = request.nextUrl;
  if (isPublicPath(pathname)) return pass();
  const token = request.cookies.get(cookieName(protocol === "https:"))?.value;
  if (await verifySession(await SECRETS, token, Date.now())) return pass();
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    return secured(NextResponse.json({ detail: "sign in first" }, { status: 401 }));
  }
  const login = new URL(LOGIN_PATH, request.nextUrl);
  if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
  return secured(NextResponse.redirect(login, 303));
}
