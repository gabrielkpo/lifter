import { type NextRequest, NextResponse } from "next/server";
import { allowedHosts, isAllowedHost } from "./lib/hosts";

// Each variable is named in full: Next only provides the ones written as process.env.NAME to
// the proxy bundle, so passing the whole process.env object would read nothing on Vercel.
const ALLOWED = allowedHosts({
  VERCEL_URL: process.env.VERCEL_URL,
  VERCEL_BRANCH_URL: process.env.VERCEL_BRANCH_URL,
  VERCEL_PROJECT_PRODUCTION_URL: process.env.VERCEL_PROJECT_PRODUCTION_URL,
  LIFTER_WEB_HOSTS: process.env.LIFTER_WEB_HOSTS,
});

/** Refuse any request whose Host is not this app's (DNS rebinding, LAN access). */
export function proxy(request: NextRequest) {
  if (!isAllowedHost(request.headers.get("host"), ALLOWED)) {
    return new NextResponse("Unknown host", { status: 400 });
  }
  return NextResponse.next();
}
