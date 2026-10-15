import { type NextRequest, NextResponse } from "next/server";
import { isAllowedHost } from "./lib/hosts";

/** Refuse any request whose Host is not this machine (DNS rebinding, LAN access). */
export function proxy(request: NextRequest) {
  if (!isAllowedHost(request.headers.get("host"))) {
    return new NextResponse("Unknown host", { status: 400 });
  }
  return NextResponse.next();
}
