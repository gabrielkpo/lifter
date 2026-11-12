"use client";

import { useEffect, useState } from "react";
import { API_URL } from "./config";
import { LOGIN_PATH } from "./session";

export type ApiState<T> =
  | { status: "loading" }
  | { status: "error"; message: string; notFound: boolean }
  | { status: "ok"; data: T };

// Calls in flight, so the launch screen knows when the first page has its data.
let inFlight = 0;
let started = 0;
const listeners = new Set<() => void>();

/** Calls in flight and calls started since launch; `listener` runs on every change. */
export function apiActivity(): { inFlight: number; started: number } {
  return { inFlight, started };
}

export function onApiActivity(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function track(delta: 1 | -1) {
  inFlight += delta;
  if (delta === 1) started += 1;
  listeners.forEach((listener) => listener());
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  track(1);
  try {
    const response = await fetch(`${API_URL}${path}`, { signal, cache: "no-store" });
    if (response.status === 401) signInAgain();
    if (!response.ok) {
      throw new ApiError(response.status, `${response.status} ${response.statusText}`);
    }
    return (await response.json()) as T;
  } finally {
    track(-1);
  }
}

/** POST `body` as JSON to `path` (the app's server only forwards a message to the coach). */
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  track(1);
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (response.status === 401) signInAgain();
    if (!response.ok) {
      throw new ApiError(
        response.status,
        `${response.status} ${response.statusText}`,
        ...(await explained(response)),
      );
    }
    return (await response.json()) as T;
  } finally {
    track(-1);
  }
}

/** The session expired or was dropped (proxy.ts answers 401): back to the sign-in page, which
 * returns here once signed in. */
function signInAgain() {
  const here = `${window.location.pathname}${window.location.search}`;
  // A full load, not a client-side push: the server (proxy.ts) decides what a signed-out
  // browser may see, and the page's state is left behind.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`${LOGIN_PATH}?next=${encodeURIComponent(here)}`);
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** A conversation the failed call opened all the same (POST /conversations). */
    readonly conversationId: string | null = null,
    /** The API's own words for a refusal, when it gives some (the coach's budget or pace). */
    readonly detail: string | null = null,
  ) {
    super(message);
  }
}

/** What a failed message's error says: the conversation it opened all the same, or the API's
 * sentence for a refusal. */
async function explained(response: Response): Promise<[string | null, string | null]> {
  try {
    const body = (await response.json()) as {
      detail?: string | { conversation_id?: unknown };
    };
    const detail = body.detail;
    if (typeof detail === "string") return [null, detail.slice(0, 300)];
    const opened = detail?.conversation_id;
    return [typeof opened === "string" ? opened : null, null];
  } catch {
    return [null, null];
  }
}

/** An invalid address (a page id that is not a number): shown like a 404, without a call. */
export const NOT_FOUND: ApiState<never> = {
  status: "error",
  message: errorMessage(404),
  notFound: true,
};

/** What the athlete reads for each kind of failure (app/api/[...path]/route.ts sets them). */
function errorMessage(status: number | null): string {
  switch (status) {
    case null:
      return "No connection.";
    case 401:
      return "Signed out: sign in again.";
    case 404:
      return "Not found.";
    case 422:
      return "This address is not valid.";
    case 503:
      return "The Lifter API refused the app's request: its token or settings need a look.";
    case 504:
      return "Cannot reach the Lifter API right now.";
    default:
      return "The Lifter API failed. Try again in a moment.";
  }
}

/** Fetch `path` once per change of `path`; null waits (no call yet, still loading). */
export function useApi<T>(path: string | null): ApiState<T> {
  const [state, setState] = useState<{ path: string | null; value: ApiState<T> }>({
    path,
    value: { status: "loading" },
  });

  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    getJson<T>(path, controller.signal)
      .then((data) => setState({ path, value: { status: "ok", data } }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status = error instanceof ApiError ? error.status : null;
        setState({
          path,
          value: { status: "error", message: errorMessage(status), notFound: status === 404 },
        });
      });
    return () => controller.abort();
  }, [path]);

  // A stale answer for a previous path is never shown for the new one.
  return state.path === path ? state.value : { status: "loading" };
}
