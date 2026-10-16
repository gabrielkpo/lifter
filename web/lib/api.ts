"use client";

import { useEffect, useState } from "react";
import { API_URL } from "./config";

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
    if (!response.ok) {
      throw new ApiError(response.status, `${response.status} ${response.statusText}`);
    }
    return (await response.json()) as T;
  } finally {
    track(-1);
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Fetch `path` once per change of `path`; null skips the call. */
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
        const message =
          error instanceof ApiError && error.status === 502
            ? "Cannot reach the Lifter API right now."
            : error instanceof ApiError
              ? error.message
              : "No connection.";
        const notFound = error instanceof ApiError && error.status === 404;
        setState({ path, value: { status: "error", message, notFound } });
      });
    return () => controller.abort();
  }, [path]);

  // A stale answer for a previous path is never shown for the new one.
  return state.path === path ? state.value : { status: "loading" };
}
