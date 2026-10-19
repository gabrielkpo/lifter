"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
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
  const end = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages, sending]);

  async function send(text: string) {
    const said = text.trim();
    if (!said || sending) return;
    setSending(said);
    setNotice(null);
    try {
      const reply = await postJson<ConversationReply>("/conversation", { text: said });
      setMessages((before) => [...(before ?? []), reply.athlete, reply.coach]);
      setDraft("");
    } catch (error) {
      setNotice(failure(error));
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
      <div className="chat">
        {messages.length === 0 && !sending && (
          <p className="empty">
            Talk to your coach: “move Thursday to Friday”, “my right knee hurts”, “why RIR 3?”.
            What you ask is applied at once and can be undone; its own ideas wait for your “ok”.
          </p>
        )}
        {messages.map((message) => (
          <div key={message.id} className="bubble" data-role={message.role}>
            <p>{message.text}</p>
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
        <div ref={end} />
      </div>
      <form className="chat-input" onSubmit={submit}>
        <textarea
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
