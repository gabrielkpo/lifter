import { type NextRequest, NextResponse } from "next/server";
import { cookieName, LOGIN_PATH } from "@/lib/session";

export const dynamic = "force-dynamic";

/** Sign this device out (the profile page): its session cookie is dropped. */
export async function POST(request: NextRequest) {
  if (request.headers.get("origin") !== request.nextUrl.origin) {
    return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  }
  const secure = request.nextUrl.protocol === "https:";
  const response = NextResponse.redirect(new URL(LOGIN_PATH, request.nextUrl), 303);
  response.cookies.set(cookieName(secure), "", {
    httpOnly: true,
    secure,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
  return response;
}
