"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import ApiStatus from "@/components/ApiStatus";
import { BackIcon } from "@/components/icons";
import SessionView from "@/components/SessionView";
import { useApi } from "@/lib/api";
import type { SessionDetail } from "@/lib/types";

/** A session on its own page (linked from the calendar and the health tab). */
export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const state = useApi<SessionDetail>(/^\d+$/.test(id) ? `/sessions/${id}` : null);

  return (
    <>
      <header className="topbar">
        <Link href="/wod" className="avatar" aria-label="Back to the week">
          <BackIcon />
        </Link>
      </header>
      {state.status === "ok" ? <SessionView session={state.data} mode="done" /> : <ApiStatus state={state} />}
    </>
  );
}
