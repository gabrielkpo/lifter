import type { ApiState } from "@/lib/api";

/** What to show while a call is loading or after it failed; null once the data is there. */
export default function ApiStatus<T>({ state }: { state: ApiState<T> }) {
  if (state.status === "loading") return <p className="empty">Loading…</p>;
  if (state.status === "error") return <p className="empty">{state.message}</p>;
  return null;
}
