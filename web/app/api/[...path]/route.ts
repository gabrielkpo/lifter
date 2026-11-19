import { type NextRequest, NextResponse } from "next/server";
import { fromThisApp } from "@/lib/origin";
import {
  bodyRefused,
  MESSAGE_TIMEOUT_MS,
  messagePath,
  READ_TIMEOUT_MS,
  readCapped,
  readPath,
  replacement,
} from "@/lib/proxy";

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

function upstreamHeaders(): Record<string, string> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (API_TOKEN) headers.authorization = `Bearer ${API_TOKEN}`;
  if (BYPASS) headers["x-vercel-protection-bypass"] = BYPASS;
  return headers;
}

async function forward(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<NextResponse> {
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      ...init,
      cache: "no-store",
      // A wrong protection bypass answers with a redirect to Vercel's login: never follow it.
      redirect: "manual",
      // A hung API ends here, with the 504 the app knows, not at the platform's limit.
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    const late = error instanceof DOMException && error.name === "TimeoutError";
    return NextResponse.json(
      { detail: late ? "Lifter API did not answer in time" : "Lifter API unreachable" },
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
  // Refused before it is read when it says it is too long; otherwise read up to the limit,
  // in bytes, and refused as soon as it passes it.
  if (bodyRefused(request.headers.get("content-length"))) {
    return NextResponse.json({ detail: "message too long" }, { status: 413 });
  }
  const body = await readCapped(request.body);
  if (body === null) {
    return NextResponse.json({ detail: "message too long" }, { status: 413 });
  }
  return forward(
    `${API_URL}/${target}`,
    {
      method: "POST",
      headers: { ...upstreamHeaders(), "content-type": "application/json" },
      body,
    },
    MESSAGE_TIMEOUT_MS,
  );
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
  return forward(
    `${API_URL}/${target}${request.nextUrl.search}`,
    { headers: upstreamHeaders() },
    READ_TIMEOUT_MS,
  );
}
