import type { NextRequest } from "next/server";

/** True when a POST comes from this app's own pages: the browser sends the page's origin, which
 * another site cannot forge (a form posts it too, under the same-origin referrer policy of
 * next.config.ts). */
export function fromThisApp(request: NextRequest): boolean {
  return request.headers.get("origin") === request.nextUrl.origin;
}
