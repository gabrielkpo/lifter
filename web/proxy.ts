import { type NextRequest, NextResponse } from "next/server";
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

/** Refuse any request whose Host is not this app's (DNS rebinding, LAN access), then any
 * request without a session signed by this server: a page sends to the sign-in, an /api call
 * gets 401. */
export async function proxy(request: NextRequest) {
  if (!isAllowedHost(request.headers.get("host"), ALLOWED)) {
    return new NextResponse("Unknown host", { status: 400 });
  }
  const { pathname, search, protocol } = request.nextUrl;
  if (isPublicPath(pathname)) return NextResponse.next();
  const token = request.cookies.get(cookieName(protocol === "https:"))?.value;
  if (await verifySession(await SECRETS, token, Date.now())) return NextResponse.next();
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "sign in first" }, { status: 401 });
  }
  const login = new URL(LOGIN_PATH, request.nextUrl);
  if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(login, 303);
}
