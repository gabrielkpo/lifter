"use client";

import { useEffect, useRef, useState } from "react";
import { getJson } from "@/lib/api";
import type { Conversation } from "@/lib/types";
import { NewChatIcon } from "./icons";

const PAGE = 50;

/** Today, Yesterday, Previous 7 days, Older: where a conversation last moved. */
function group(lastMessageAt: string, now: Date): string {
  const day = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round(
    (day(now) - day(new Date(lastMessageAt))) / 86_400_000,
  );
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Previous 7 days";
  return "Older";
}

/**
 * The conversations with the coach, in a panel that slides in from the left: a new one on top,
 * then every earlier one, the most recently active first. Read again each time it opens.
 */
export default function ConversationDrawer({
  open,
  current,
  onClose,
  onPick,
}: {
  open: boolean;
  /** The conversation on screen; null for a new one. */
  current: string | null;
  onClose: () => void;
  /** null starts a new conversation. */
  onPick: (id: string | null) => void;
}) {
  const [list, setList] = useState<Conversation[] | null>(null);
  const [more, setMore] = useState(false);
  const [failed, setFailed] = useState(false);
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    getJson<Conversation[]>(`/conversations?limit=${PAGE}`)
      .then((page) => {
        if (!live) return;
        setList(page);
        setMore(page.length === PAGE);
        setFailed(false);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [open]);

  // Open: the page behind stays still, Escape closes, the keyboard starts in the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.classList.add("drawer-open");
    panel.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.classList.remove("drawer-open");
    };
  }, [open, onClose]);

  async function loadMore() {
    const last = list?.at(-1);
    if (!last) return;
    try {
      const page = await getJson<Conversation[]>(
        `/conversations?limit=${PAGE}&before=${encodeURIComponent(last.id)}`,
      );
      setList((before) => [...(before ?? []), ...page]);
      setMore(page.length === PAGE);
    } catch {
      setFailed(true);
    }
  }

  const now = new Date();
  const groups: [string, Conversation[]][] = [];
  for (const conversation of list ?? []) {
    const name = group(conversation.last_message_at, now);
    const last = groups.at(-1);
    if (last?.[0] === name) last[1].push(conversation);
    else groups.push([name, [conversation]]);
  }

  return (
    <div className="drawer" data-open={open} aria-hidden={!open} inert={!open}>
      <div className="drawer-backdrop" onClick={onClose} />
      <nav
        ref={panel}
        className="drawer-panel"
        aria-label="Conversations with the coach"
        tabIndex={-1}
      >
        <button
          type="button"
          className="drawer-new"
          onClick={() => onPick(null)}
        >
          <NewChatIcon />
          New conversation
        </button>
        {failed && (
          <p className="small muted">The conversations could not be loaded.</p>
        )}
        {list === null && !failed && <p className="small muted">Loading…</p>}
        {list?.length === 0 && (
          <p className="small muted">No earlier conversation yet.</p>
        )}
        {groups.map(([name, items]) => (
          <section key={name}>
            <h2 className="drawer-group">{name}</h2>
            <ul>
              {items.map((conversation) => (
                <li key={conversation.id}>
                  <button
                    type="button"
                    className="drawer-item"
                    aria-current={
                      conversation.id === current ? "page" : undefined
                    }
                    onClick={() => onPick(conversation.id)}
                  >
                    {conversation.title}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {more && (
          <button
            type="button"
            className="chip"
            onClick={() => void loadMore()}
          >
            Earlier conversations
          </button>
        )}
      </nav>
    </div>
  );
}
