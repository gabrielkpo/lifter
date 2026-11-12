import { type NextRequest, NextResponse } from "next/server";
import {
  cookieName,
  issueSession,
  LOGIN_PATH,
  passphraseMatches,
  SESSION_SECONDS,
  safeNext,
  sessionSecrets,
} from "@/lib/session";

const SECRETS = sessionSecrets(process.env);
/** The form holds a passphrase and a path: anything longer is refused before it is read. */
const MAX_FORM = 2_048;
/** A wrong passphrase waits this long before its answer, which slows guessing down. */
const WRONG_DELAY_MS = 1_000;

export const dynamic = "force-dynamic";

/** The sign-in form (app/login): the right passphrase gets a session cookie for
 * SESSION_SECONDS, then the page asked for; a wrong one goes back to the form. */
export async function POST(request: NextRequest) {
  // Only from this app's own sign-in page.
  if (request.headers.get("origin") !== request.nextUrl.origin) {
    return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  }
  if (
    !request.headers.get("content-type")?.startsWith("application/x-www-form-urlencoded")
  ) {
    return NextResponse.json({ detail: "expected a form" }, { status: 415 });
  }
  const length = Number(request.headers.get("content-length") ?? NaN);
  if (!Number.isFinite(length) || length > MAX_FORM) {
    return NextResponse.json({ detail: "form too long" }, { status: 413 });
  }
  const body = await request.text();
  if (new TextEncoder().encode(body).length > MAX_FORM) {
    return NextResponse.json({ detail: "form too long" }, { status: 413 });
  }
  const form = new URLSearchParams(body);
  const next = safeNext(form.get("next"));
  const secrets = await SECRETS;
  const back = (error: string) => {
    const url = new URL(LOGIN_PATH, request.nextUrl);
    url.searchParams.set("error", error);
    if (next !== "/") url.searchParams.set("next", next);
    return NextResponse.redirect(url, 303);
  };
  if (!secrets) return back("closed");
  if (!(await passphraseMatches(secrets, form.get("passphrase") ?? ""))) {
    await new Promise((resolve) => setTimeout(resolve, WRONG_DELAY_MS));
    return back("wrong");
  }
  const secure = request.nextUrl.protocol === "https:";
  const response = NextResponse.redirect(new URL(next, request.nextUrl), 303);
  response.cookies.set(cookieName(secure), await issueSession(secrets, Date.now()), {
    httpOnly: true,
    secure,
    sameSite: "strict",
    path: "/",
    maxAge: SESSION_SECONDS,
  });
  return response;
}
