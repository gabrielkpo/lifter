import { type NextRequest, NextResponse } from "next/server";

// The app's server reads the Lifter API on behalf of the browser: the API's address, its
// token and the Vercel protection bypass stay on the server, never in the page.
// Read-only: GET on the API's own endpoints, nothing else is forwarded.
const API_URL = process.env.LIFTER_API_URL ?? "http://127.0.0.1:8000";
const API_TOKEN = process.env.LIFTER_API_TOKEN;
const BYPASS = process.env.LIFTER_API_BYPASS;

const ENDPOINTS = new Set([
  "program",
  "weeks",
  "blocks",
  "calendar",
  "sessions",
  "health",
  "goals",
  "profile",
  "status",
  "bests",
  "history",
  "proposals",
]);
const SEGMENT = /^[A-Za-z0-9_-]+$/;

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (!ENDPOINTS.has(path[0]) || path.length > 2 || !path.every((s) => SEGMENT.test(s))) {
    return NextResponse.json({ detail: "not found" }, { status: 404 });
  }
  const headers: Record<string, string> = { accept: "application/json" };
  if (API_TOKEN) headers.authorization = `Bearer ${API_TOKEN}`;
  if (BYPASS) headers["x-vercel-protection-bypass"] = BYPASS;

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/${path.join("/")}${request.nextUrl.search}`, {
      headers,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "Lifter API unreachable" }, { status: 504 });
  }
  // Errors other than "not found" and "invalid input" are not passed through in detail, but
  // a refusal (wrong token or protection bypass) stays distinct from a failure.
  if (upstream.status === 401 || upstream.status === 403) {
    return NextResponse.json({ detail: "Lifter API refused the request" }, { status: 503 });
  }
  if (!upstream.ok && upstream.status !== 404 && upstream.status !== 422) {
    return NextResponse.json({ detail: "Lifter API error" }, { status: 502 });
  }
  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}
