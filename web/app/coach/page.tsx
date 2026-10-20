"use client";

import { useRouter, useSearchParams } from "next/navigation";
import {
  type FormEvent,
  type ReactNode,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import ApiStatus from "@/components/ApiStatus";
import ConversationDrawer from "@/components/ConversationDrawer";
import { HistoryIcon, NewChatIcon } from "@/components/icons";
import TopBar from "@/components/TopBar";
import { ApiError, getJson, postJson } from "@/lib/api";
import { label } from "@/lib/format";
import type {
  ConversationChange,
  ConversationMessage,
  ConversationReply,
  ConversationThread,
} from "@/lib/types";

/** A conversation's latest messages; a new conversation has none to load. */
const threadOf = (id: string) =>
  `/conversations/${encodeURIComponent(id)}?limit=50`;
const NONE: ConversationMessage[] = [];

/** The conversation last on screen while the app stays open: coming back to the tab resumes it;
 * a new one starts when the app opens again, or on "New conversation". */
let remembered: string | null = null;

/** A conversation on screen: null for a new one, not opened yet. */
type Loaded = {
  id: string | null;
  messages: ConversationMessage[];
  title: string | null;
};
/** Something that happened in one conversation, shown in that one only. */
type Tagged<T> = { id: string | null; value: T };
/** The input grows with the text up to this height, then scrolls. */
const INPUT_MAX = 160;
/** Closer to the end than this, the thread counts as read to the end. */
const NEAR_END = 120;

/** What the athlete reads when a message could not be answered. */
function failure(error: unknown): string {
  const status = error instanceof ApiError ? error.status : null;
  switch (status) {
    case 404:
      return "This conversation does not exist. Start a new one.";
    case 409:
      return "A newer message was waiting: the conversation is up to date again.";
    case 502:
      return "The coach's model did not answer. Your message is kept; try again.";
    case 503:
      return "The coach is unavailable right now (database or settings).";
    case 504:
      return "Cannot reach the Lifter API right now.";
    default:
      return "The coach failed to answer. Try again in a moment.";
  }
}

/** **bold**, *italic* and `code` inside a line, as text: the model writes Markdown, nothing
 * of it is HTML. */
function inline(text: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g)
    .map((piece, i) => {
      if (piece.length > 4 && piece.startsWith("**") && piece.endsWith("**")) {
        return <strong key={i}>{piece.slice(2, -2)}</strong>;
      }
      if (piece.length > 2 && piece.startsWith("*") && piece.endsWith("*")) {
        return <em key={i}>{piece.slice(1, -1)}</em>;
      }
      if (piece.length > 2 && piece.startsWith("`") && piece.endsWith("`")) {
        return <code key={i}>{piece.slice(1, -1)}</code>;
      }
      return piece;
    });
}

type Item = { text: string; children: string[] };

/** A reply's text: paragraphs, "#" titles, "- " and "1. " lists (one level of items under an
 * item, indented), **bold**, *italic* and `code`; anything else as written. */
function MessageText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let items: Item[] = [];
  let ordered = false;
  const flush = () => {
    if (paragraph.length) {
      blocks.push(<p key={blocks.length}>{inline(paragraph.join("\n"))}</p>);
      paragraph = [];
    }
    if (items.length) {
      const List = ordered ? "ol" : "ul";
      blocks.push(
        <List key={blocks.length}>
          {items.map((item, i) => (
            <li key={i}>
              {inline(item.text)}
              {item.children.length > 0 && (
                <ul>
                  {item.children.map((child, j) => (
                    <li key={j}>{inline(child)}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </List>,
      );
      items = [];
    }
  };
  for (const line of text.split("\n")) {
    const title = /^\s*#{1,6}\s+(.*)$/.exec(line);
    const item = /^(\s*)(?:([-*•])|(\d+)[.)])\s+(.*)$/.exec(line);
    if (title) {
      flush();
      blocks.push(
        <p key={blocks.length} className="chat-heading">
          <strong>{inline(title[1])}</strong>
        </p>,
      );
    } else if (item) {
      const [, indent, , number, words] = item;
      if (indent.length >= 2 && items.length) {
        items[items.length - 1].children.push(words);
        continue;
      }
      if (
        paragraph.length ||
        (items.length && ordered !== (number !== undefined))
      )
        flush();
      ordered = number !== undefined;
      items.push({ text: words, children: [] });
    } else if (!line.trim()) {
      flush();
    } else {
      if (items.length) flush();
      paragraph.push(line);
    }
  }
  flush();
  return <>{blocks}</>;
}

/**
 * The conversations with the coach (ADR 0002): saying it is deciding it. An instruction is
 * applied at once and shown under the reply with an undo; the coach's own ideas come back as
 * numbered suggestions, accepted by answering "ok pour N". The tab opens on a new conversation;
 * the history panel resumes any earlier one, named in the address (?c=).
 */
export default function CoachPage() {
  // The conversation comes from the address, read on the client only.
  return (
    <Suspense fallback={<TopBar title="Coach" />}>
      <Coach />
    </Suspense>
  );
}

function Coach() {
  const router = useRouter();
  const current = useSearchParams().get("c");
  const [drawer, setDrawer] = useState(false);
  // The conversation last loaded or opened, and what happened to the one on screen: each says
  // which conversation it belongs to, so another one never shows it.
  const [loaded, setLoaded] = useState<Loaded>({
    id: null,
    messages: NONE,
    title: null,
  });
  const [loadError, setLoadError] = useState<Tagged<unknown> | null>(null);
  const [draft, setDraft] = useState("");
  const [turn, setTurn] = useState<Tagged<string> | null>(null);
  const [said, setSaid] = useState<Tagged<string> | null>(null);
  const [atEnd, setAtEnd] = useState(true);
  const [inputHeight, setInputHeight] = useState(64);
  const form = useRef<HTMLFormElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const newReply = useRef<HTMLDivElement>(null);
  // Where to go once the thread renders: its end on load, a new reply's first line after it.
  const pendingScroll = useRef<"end" | "reply" | null>("end");
  // The conversation on screen when a reply comes back: the athlete may have moved on since.
  const here = useRef(current);
  useEffect(() => {
    here.current = current;
  }, [current]);

  const mine = <T,>(tagged: Tagged<T> | null) =>
    tagged?.id === current ? tagged.value : null;
  // On the tab without a conversation named (back from another tab, or its icon tapped): the
  // one left open, until "New conversation" forgets it.
  const resuming = current === null && remembered !== null;
  const messages =
    loaded.id === current
      ? loaded.messages
      : current === null && !resuming
        ? NONE
        : null;
  const title = loaded.id === current ? loaded.title : null;
  const sending = mine(turn);
  const notice = mine(said);
  const error = mine(loadError);

  async function reload(id: string) {
    try {
      const thread = await getJson<ConversationThread>(threadOf(id));
      setLoaded({
        id,
        messages: thread.messages,
        title: thread.conversation.title,
      });
    } catch (failed) {
      setLoadError({ id, value: failed });
    }
  }

  useEffect(() => {
    if (current !== null) remembered = current;
    else if (remembered !== null) {
      router.replace(`/coach?c=${encodeURIComponent(remembered)}`, {
        scroll: false,
      });
    }
  }, [current, router]);

  // An earlier conversation: its thread, from its end.
  useEffect(() => {
    if (current === null || loaded.id === current) return;
    let live = true;
    getJson<ConversationThread>(threadOf(current))
      .then((thread) => {
        if (!live) return;
        pendingScroll.current = "end";
        setLoaded({
          id: current,
          messages: thread.messages,
          title: thread.conversation.title,
        });
      })
      .catch(
        (failed: unknown) =>
          live && setLoadError({ id: current, value: failed }),
      );
    return () => {
      live = false;
    };
  }, [current, loaded.id]);

  const pick = useCallback(
    (id: string | null) => {
      setDrawer(false);
      if (id === null) remembered = null;
      if (id === current) return;
      pendingScroll.current = "end";
      router.push(
        id === null ? "/coach" : `/coach?c=${encodeURIComponent(id)}`,
        {
          scroll: false,
        },
      );
    },
    [current, router],
  );
  const closeDrawer = useCallback(() => setDrawer(false), []);

  // The page's own bottom: the thread's padding keeps its end above the input.
  const toEnd = useCallback((smooth: boolean) => {
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
  }, []);

  const shown = messages !== null;
  // The thread always ends above the input: its padding follows the input's height.
  useLayoutEffect(() => {
    const element = form.current;
    if (!element) return;
    // A hidden page measures 0: keep the last real height then.
    const observer = new ResizeObserver(() => {
      const height = element.getBoundingClientRect().height;
      if (height > 0) setInputHeight(height);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [shown]);

  // The input grows with what is typed, up to INPUT_MAX, then scrolls inside.
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, INPUT_MAX)}px`;
  }, [draft]);

  // With the keyboard open (a phone), the input sits right above it and the tab bar steps
  // aside: the visual viewport says how much of the screen the keyboard takes.
  useEffect(() => {
    const view = window.visualViewport;
    if (!view) return;
    let wasOpen = false;
    const onChange = () => {
      const keyboard = Math.max(
        0,
        window.innerHeight - view.height - view.offsetTop,
      );
      const open = keyboard > 80;
      document.documentElement.style.setProperty(
        "--keyboard",
        `${open ? keyboard : 0}px`,
      );
      document.body.classList.toggle("keyboard-open", open);
      // To the end once, as it opens: scrolling up to reread stays possible while typing.
      if (open && !wasOpen)
        window.scrollTo({ top: document.documentElement.scrollHeight });
      wasOpen = open;
    };
    onChange();
    view.addEventListener("resize", onChange);
    view.addEventListener("scroll", onChange);
    return () => {
      view.removeEventListener("resize", onChange);
      view.removeEventListener("scroll", onChange);
      document.body.classList.remove("keyboard-open");
      document.documentElement.style.removeProperty("--keyboard");
    };
  }, []);

  useEffect(() => {
    const onScroll = () => {
      const left =
        document.documentElement.scrollHeight -
        (window.scrollY + window.innerHeight);
      setAtEnd(left < NEAR_END);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [messages, sending]);

  useEffect(() => {
    if (messages === null) return; // the thread is not there yet: keep where to go
    if (pendingScroll.current === "reply" && newReply.current) {
      // A long reply is read from its first line, under the page's title.
      newReply.current.scrollIntoView({ block: "start", behavior: "smooth" });
    } else if (pendingScroll.current === "end" || sending) {
      toEnd(pendingScroll.current !== "end");
    }
    pendingScroll.current = null;
  }, [messages, sending, toEnd]);

  async function send(text: string) {
    const words = text.trim();
    const where = current;
    if (!words || turn) return;
    setTurn({ id: where, value: words });
    setSaid(null);
    setDraft(""); // sent: the input is free at once, the message shows in the thread
    try {
      const reply = await postJson<ConversationReply>(
        where === null
          ? "/conversations"
          : `/conversations/${encodeURIComponent(where)}`,
        { text: words },
      );
      if (here.current === where) pendingScroll.current = "reply";
      if (where === null) {
        // Opened by this message: shown, and named in the address, if still on screen; the
        // history panel has it otherwise.
        if (here.current !== null) return;
        setLoaded({
          id: reply.conversation_id,
          messages: [reply.athlete, reply.coach],
          title: words,
        });
        router.replace(
          `/coach?c=${encodeURIComponent(reply.conversation_id)}`,
          { scroll: false },
        );
      } else {
        setLoaded((before) =>
          before.id === where
            ? {
                ...before,
                messages: [...before.messages, reply.athlete, reply.coach],
              }
            : before,
        );
      }
    } catch (failed) {
      setDraft((now) => now || words); // not answered: the words come back to send again
      pendingScroll.current = "end";
      // The message, or a reply about a crash, may be stored all the same: in this
      // conversation, or in the one this message opened.
      const stored =
        where ?? (failed instanceof ApiError ? failed.conversationId : null);
      setSaid({ id: stored, value: failure(failed) });
      if (stored !== null && here.current === where) {
        await reload(stored);
        if (where === null) {
          router.replace(`/coach?c=${encodeURIComponent(stored)}`, {
            scroll: false,
          });
        }
      }
    } finally {
      setTurn(null);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  // The history on the left, a new conversation on the right, the conversation's name under.
  const header = (
    <>
      <TopBar
        title="Coach"
        leading={
          <button
            type="button"
            className="icon-button"
            onClick={() => setDrawer(true)}
            aria-label="Conversations"
            aria-expanded={drawer}
          >
            <HistoryIcon />
          </button>
        }
        actions={
          current !== null && (
            <button
              type="button"
              className="icon-button"
              onClick={() => pick(null)}
              aria-label="New conversation"
            >
              <NewChatIcon />
            </button>
          )
        }
      />
      <p className="chat-title">
        {current === null ? "New conversation" : (title ?? "")}
      </p>
      <ConversationDrawer
        open={drawer}
        current={current}
        onClose={closeDrawer}
        onPick={pick}
      />
    </>
  );

  if (messages === null) {
    return (
      <>
        {header}
        {error ? (
          <p className="empty">{failure(error)}</p>
        ) : (
          <ApiStatus state={{ status: "loading" }} />
        )}
      </>
    );
  }

  // The changes an athlete's message authorised are shown under the coach's reply to it, or
  // under the message itself when no reply followed (a turn that failed after applying them).
  const changesFor = new Map<number, ConversationChange[]>();
  messages.forEach((message, i) => {
    if (message.role !== "athlete" || message.changes.length === 0) return;
    const next = messages[i + 1];
    changesFor.set(
      next?.role === "coach" ? next.id : message.id,
      message.changes,
    );
  });
  const lastCoach = [...messages].reverse().find((m) => m.role === "coach")?.id;

  return (
    <>
      {header}
      <div
        className="chat"
        style={{
          paddingBottom: `calc(${inputHeight + 16}px + var(--keyboard, 0px))`,
        }}
      >
        {messages.length === 0 && !sending && (
          <p className="empty">
            Talk to your coach: “move Thursday to Friday”, “my right knee
            hurts”, “why RIR 3?”. What you ask is applied at once and can be
            undone; its own ideas wait for your “ok”.
          </p>
        )}
        {messages.map((message) => (
          <div
            key={message.id}
            ref={message.id === lastCoach ? newReply : undefined}
            className="bubble"
            data-role={message.role}
          >
            {message.role === "coach" ? (
              <MessageText text={message.text} />
            ) : (
              <p>{message.text}</p>
            )}
            {(changesFor.get(message.id) ?? []).map((change) => (
              <div key={change.change_id} className="chat-change">
                <span>
                  {label(change.operation)}
                  {change.subject && (
                    <>
                      {" · "}
                      <strong>{change.subject}</strong>
                    </>
                  )}
                  {change.detail && (
                    <span className="chat-change-detail">{change.detail}</span>
                  )}
                  {change.undone && " · undone"}
                </span>
                {!change.undone && (
                  <button
                    type="button"
                    className="chip"
                    disabled={turn !== null}
                    onClick={() =>
                      void send(`annule le changement ${change.change_id}`)
                    }
                  >
                    Undo
                  </button>
                )}
              </div>
            ))}
            {message.suggestions.map((suggestion) => (
              <div key={suggestion.id} className="chat-change">
                <span>
                  <strong>{suggestion.id}</strong> ·{" "}
                  {label(suggestion.operation)} · {suggestion.rationale}
                  {suggestion.status !== "pending" && ` · ${suggestion.status}`}
                </span>
                {suggestion.status === "pending" &&
                  message.id === lastCoach && (
                    <button
                      type="button"
                      className="chip"
                      disabled={turn !== null}
                      onClick={() => void send(`ok pour la ${suggestion.id}`)}
                    >
                      OK
                    </button>
                  )}
              </div>
            ))}
          </div>
        ))}
        {sending && (
          <>
            <div className="bubble" data-role="athlete">
              <p>{sending}</p>
            </div>
            <div className="bubble" data-role="coach" aria-live="polite">
              <p className="muted">The coach is thinking…</p>
            </div>
          </>
        )}
        {notice && (
          <p className="small muted" role="status">
            {notice}
          </p>
        )}
      </div>
      {!atEnd && (
        <button
          type="button"
          className="chat-to-end"
          style={{
            bottom: `calc(var(--chat-input-bottom) + ${inputHeight + 12}px)`,
          }}
          onClick={() => toEnd(true)}
          aria-label="Go to the latest message"
        >
          ↓
        </button>
      )}
      {/* An opaque floor under the input and the tab bar: the thread never shows through. */}
      <div
        className="chat-floor"
        style={{
          height: `calc(var(--chat-input-bottom) + ${inputHeight + 8}px)`,
        }}
        aria-hidden
      />
      <form ref={form} className="chat-input" onSubmit={submit}>
        <textarea
          ref={input}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send(draft);
            }
          }}
          placeholder="Message to your coach"
          maxLength={2000}
          rows={1}
          aria-label="Message to your coach"
        />
        <button
          type="submit"
          className="pill"
          aria-pressed
          disabled={!draft.trim() || turn !== null}
        >
          Send
        </button>
      </form>
    </>
  );
}
