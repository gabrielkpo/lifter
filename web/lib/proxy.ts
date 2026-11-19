// What the app's server (app/api/[...path]/route.ts) lets through to the Lifter API, and how it
// passes the API's answers back: plain functions, tested in proxy.test.ts.

/** The API's endpoints the app reads. */
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
  "conversations",
]);
const SEGMENT = /^[A-Za-z0-9_-]{1,64}$/;

/** The API path a GET reads: one of its endpoints, then at most one id; null otherwise. */
export function readPath(path: string[]): string | null {
  if (!ENDPOINTS.has(path[0]) || path.length > 2 || !path.every((s) => SEGMENT.test(s))) {
    return null;
  }
  return path.join("/");
}

/** Where a message may go: a new conversation, one by its id, or the Undo of a change in one. */
export function messagePath(path: string[]): string | null {
  if (path.length === 1 && path[0] === "conversations") {
    return path[0];
  }
  if (path.length === 2 && path[0] === "conversations" && SEGMENT.test(path[1])) {
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

/** The API's answers passed through as they are: success, "not found", "invalid input" and the
 * coach's own (a newer message, its budget or pace reached, its model or the database
 * unavailable). */
const PASSED = new Set([404, 409, 422, 429, 502, 503]);

/** What the browser gets for the API's status: null passes the answer through; otherwise the
 * status and detail to send instead. A refusal (wrong token or protection bypass, which answers
 * with a redirect to Vercel's login) stays distinct from a failure. */
export function replacement(status: number): { status: number; detail: string } | null {
  if (status === 401 || status === 403 || (status >= 300 && status < 400)) {
    return { status: 503, detail: "Lifter API refused the request" };
  }
  if ((status >= 200 && status < 300) || PASSED.has(status)) return null;
  return { status: 502, detail: "Lifter API error" };
}
