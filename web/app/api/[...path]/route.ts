import { type NextRequest, NextResponse } from "next/server";
import { fromThisApp } from "@/lib/origin";
import { messagePath, readPath, replacement } from "@/lib/proxy";

// The app's server reads the Lifter API on behalf of the browser: the API's address, its
// token and the Vercel protection bypass stay on the server, never in the page.
// GET on the API's own endpoints; the one write forwarded is a message to the coach
// (POST /conversations, /conversations/{id}, /conversations/{id}/undo), from this app's own
// pages only.
const API_URL = process.env.LIFTER_API_URL ?? "http://127.0.0.1:8000";
const API_TOKEN = process.env.LIFTER_API_TOKEN;
const BYPASS = process.env.LIFTER_API_BYPASS;

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
  // Only the answers the app knows are passed through (lib/proxy).
  const instead = replacement(upstream.status);
  if (instead) {
    return NextResponse.json({ detail: instead.detail }, { status: instead.status });
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
  if (!fromThisApp(request)) {
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
  const target = readPath(path);
  if (target === null) {
    return NextResponse.json({ detail: "not found" }, { status: 404 });
  }
  return forward(`${API_URL}/${target}${request.nextUrl.search}`, {
    headers: upstreamHeaders(),
  });
}
