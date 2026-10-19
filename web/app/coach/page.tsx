"use client";

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import ApiStatus from "@/components/ApiStatus";
import TopBar from "@/components/TopBar";
import { ApiError, getJson, postJson } from "@/lib/api";
import { label } from "@/lib/format";
import type {
  ConversationChange,
  ConversationMessage,
  ConversationReply,
} from "@/lib/types";

const THREAD = "/conversation?limit=50";
/** The input grows with the text up to this height, then scrolls. */
const INPUT_MAX = 160;
/** Closer to the end than this, the thread counts as read to the end. */
const NEAR_END = 120;

/** What the athlete reads when a message could not be answered. */
function failure(error: unknown): string {
  const status = error instanceof ApiError ? error.status : null;
  switch (status) {
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

/** **bold** inside a line, as text: the model writes Markdown, nothing of it is HTML. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((piece, i) =>
    piece.startsWith("**") && piece.endsWith("**") && piece.length > 4 ? (
      <strong key={i}>{piece.slice(2, -2)}</strong>
    ) : (
      piece
    ),
  );
}

/** A reply's text: paragraphs, "- " or "* " lists and **bold**; anything else as written. */
function MessageText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let items: string[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) {
      blocks.push(<p key={blocks.length}>{inline(paragraph.join("\n"))}</p>);
      paragraph = [];
    }
    if (items.length) {
      blocks.push(
        <ul key={blocks.length}>
          {items.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      items = [];
    }
  };
  for (const line of text.split("\n")) {
    const item = /^\s*[-*]\s+(.*)$/.exec(line);
    if (item) {
      if (paragraph.length) flush();
      items.push(item[1]);
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
 * The conversation with the coach (ADR 0002): saying it is deciding it. An instruction is applied
 * at once and shown under the reply with an undo; the coach's own ideas come back as numbered
 * suggestions, accepted by answering "ok pour N".
 */
export default function CoachPage() {
  const [messages, setMessages] = useState<ConversationMessage[] | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [atEnd, setAtEnd] = useState(true);
  const [inputHeight, setInputHeight] = useState(64);
  const form = useRef<HTMLFormElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const newReply = useRef<HTMLDivElement>(null);
  // Where to go once the thread renders: its end on load, a new reply's first line after it.
  const pendingScroll = useRef<"end" | "reply" | null>("end");

  async function reload() {
    try {
      setMessages(await getJson<ConversationMessage[]>(THREAD));
      setLoadError(null);
    } catch (error) {
      setLoadError(error);
    }
  }

  useEffect(() => {
    let live = true;
    getJson<ConversationMessage[]>(THREAD)
      .then((thread) => live && setMessages(thread))
      .catch((error: unknown) => live && setLoadError(error));
    return () => {
      live = false;
    };
  }, []);

  // The page's own bottom: the thread's padding keeps its end above the input.
  const toEnd = useCallback((smooth: boolean) => {
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
  }, []);

  const loaded = messages !== null;
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
  }, [loaded]);

  // The input grows with what is typed, up to INPUT_MAX, then scrolls inside.
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, INPUT_MAX)}px`;
  }, [draft]);

  useEffect(() => {
    const onScroll = () => {
      const left = document.documentElement.scrollHeight - (window.scrollY + window.innerHeight);
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
    const said = text.trim();
    if (!said || sending) return;
    setSending(said);
    setNotice(null);
    try {
      const reply = await postJson<ConversationReply>("/conversation", { text: said });
      pendingScroll.current = "reply";
      setMessages((before) => [...(before ?? []), reply.athlete, reply.coach]);
      setDraft("");
    } catch (error) {
      setNotice(failure(error));
      pendingScroll.current = "end";
      await reload(); // the message, or a reply about a crash, may be stored all the same
    } finally {
      setSending(null);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  if (messages === null) {
    return (
      <>
        <TopBar title="Coach" />
        {loadError ? (
          <p className="empty">{failure(loadError)}</p>
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
    changesFor.set(next?.role === "coach" ? next.id : message.id, message.changes);
  });
  const lastCoach = [...messages].reverse().find((m) => m.role === "coach")?.id;

  return (
    <>
      <TopBar title="Coach" />
      <div className="chat" style={{ paddingBottom: inputHeight + 16 }}>
        {messages.length === 0 && !sending && (
          <p className="empty">
            Talk to your coach: “move Thursday to Friday”, “my right knee hurts”, “why RIR 3?”.
            What you ask is applied at once and can be undone; its own ideas wait for your “ok”.
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
                  {change.undone && " · undone"}
                </span>
                {!change.undone && (
                  <button
                    type="button"
                    className="chip"
                    disabled={sending !== null}
                    onClick={() => void send(`annule le changement ${change.change_id}`)}
                  >
                    Undo
                  </button>
                )}
              </div>
            ))}
            {message.suggestions.map((suggestion) => (
              <div key={suggestion.id} className="chat-change">
                <span>
                  <strong>{suggestion.id}</strong> · {label(suggestion.operation)} ·{" "}
                  {suggestion.rationale}
                  {suggestion.status !== "pending" && ` · ${suggestion.status}`}
                </span>
                {suggestion.status === "pending" && message.id === lastCoach && (
                  <button
                    type="button"
                    className="chip"
                    disabled={sending !== null}
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
          style={{ bottom: `calc(var(--chat-input-bottom) + ${inputHeight + 12}px)` }}
          onClick={() => toEnd(true)}
          aria-label="Go to the latest message"
        >
          ↓
        </button>
      )}
      {/* An opaque floor under the input and the tab bar: the thread never shows through. */}
      <div
        className="chat-floor"
        style={{ height: `calc(var(--chat-input-bottom) + ${inputHeight + 8}px)` }}
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
        <button type="submit" className="pill" aria-pressed disabled={!draft.trim() || !!sending}>
          Send
        </button>
      </form>
    </>
  );
}
