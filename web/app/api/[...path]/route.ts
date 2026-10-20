import { type NextRequest, NextResponse } from "next/server";

// The app's server reads the Lifter API on behalf of the browser: the API's address, its
// token and the Vercel protection bypass stay on the server, never in the page.
// GET on the API's own endpoints; the one write forwarded is a message to the coach
// (POST /conversations, /conversations/{id}, /conversations/{id}/undo), from this app's own
// pages only.
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
  "conversation",
  "conversations",
]);
const SEGMENT = /^[A-Za-z0-9_-]{1,64}$/;

/** Where a message may go: a new conversation, one by its id, the Undo of a change in one, or
 * the first one (the route of the release before, for an app left open across the deployment). */
function messagePath(path: string[]): string | null {
  if (
    path.length === 1 &&
    (path[0] === "conversations" || path[0] === "conversation")
  ) {
    return path[0];
  }
  if (
    path.length === 2 &&
    path[0] === "conversations" &&
    SEGMENT.test(path[1])
  ) {
    return path.join("/");
  }
  // The Undo of a change, applied without the model.
  if (
    path.length === 3 &&
    path[0] === "conversations" &&
    SEGMENT.test(path[1]) &&
    path[2] === "undo"
  ) {
    return path.join("/");
  }
  return null;
}

export const dynamic = "force-dynamic";
// A coach's turn makes 1 to 8 model calls: the longest a function may run on Vercel's plan.
export const maxDuration = 60;

const MAX_BODY = 8_000;

function upstreamHeaders(): Record<string, string> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (API_TOKEN) headers.authorization = `Bearer ${API_TOKEN}`;
  if (BYPASS) headers["x-vercel-protection-bypass"] = BYPASS;
  return headers;
}

async function forward(url: string, init: RequestInit): Promise<NextResponse> {
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      ...init,
      cache: "no-store",
      // A wrong protection bypass answers with a redirect to Vercel's login: never follow it.
      redirect: "manual",
    });
  } catch {
    return NextResponse.json(
      { detail: "Lifter API unreachable" },
      { status: 504 },
    );
  }
  // Errors other than "not found", "invalid input" and the coach's own (a newer message,
  // its model or the database unavailable) are not passed through in detail, but a refusal
  // (wrong token or protection bypass) stays distinct from a failure.
  if (
    upstream.status === 401 ||
    upstream.status === 403 ||
    (upstream.status >= 300 && upstream.status < 400)
  ) {
    return NextResponse.json(
      { detail: "Lifter API refused the request" },
      { status: 503 },
    );
  }
  if (!upstream.ok && ![404, 409, 422, 502, 503].includes(upstream.status)) {
    return NextResponse.json({ detail: "Lifter API error" }, { status: 502 });
  }
  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: {
      "content-type": "application/json",
      "cache-control": "no-store",
    },
  });
}

/** A message to the coach. Only from this app's pages: the browser sends the page's origin,
 * which another site cannot forge, so a page elsewhere cannot write through the athlete's
 * signed-in browser. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const target = messagePath(path);
  if (target === null) {
    return NextResponse.json({ detail: "not found" }, { status: 404 });
  }
  if (request.headers.get("origin") !== request.nextUrl.origin) {
    return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  }
  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return NextResponse.json({ detail: "expected JSON" }, { status: 415 });
  }
  const body = await request.text();
  if (body.length > MAX_BODY) {
    return NextResponse.json({ detail: "message too long" }, { status: 413 });
  }
  return forward(`${API_URL}/${target}`, {
    method: "POST",
    headers: { ...upstreamHeaders(), "content-type": "application/json" },
    body,
  });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  if (
    !ENDPOINTS.has(path[0]) ||
    path.length > 2 ||
    !path.every((s) => SEGMENT.test(s))
  ) {
    return NextResponse.json({ detail: "not found" }, { status: 404 });
  }
  return forward(`${API_URL}/${path.join("/")}${request.nextUrl.search}`, {
    headers: upstreamHeaders(),
  });
}
