import { type NextRequest, NextResponse } from "next/server";
import { allowedHosts, isAllowedHost } from "./lib/hosts";

const ALLOWED = allowedHosts(process.env);

/** Refuse any request whose Host is not this app's (DNS rebinding, LAN access). */
export function proxy(request: NextRequest) {
  if (!isAllowedHost(request.headers.get("host"), ALLOWED)) {
    return new NextResponse("Unknown host", { status: 400 });
  }
  return NextResponse.next();
}
