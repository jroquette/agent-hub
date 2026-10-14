import "./agent-session.css";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Icon, Markdown, type IconName } from "../../components";
import { cx } from "../../lib/cx";
import { JumpToLatest } from "./JumpToLatest";
import { PermissionCard, type PermissionAnswer } from "./PermissionCard";
import { StoredCopyLabel } from "./SessionStatus";
import { ToolCallCard } from "./ToolCallCard";
import {
  pendingPermissions,
  type NoticeTone,
  type TranscriptEntry,
  type TranscriptState,
} from "./transcript";
import type { StickToBottom } from "./useStickToBottom";

export interface TranscriptProps {
  state: TranscriptState;
  /** Posts a permission answer; without it the cards are read-only. */
  onAnswerPermission?:
    ((requestId: string, answer: PermissionAnswer) => Promise<unknown> | undefined) | undefined;
  /** Receives the scroll container, for the chat's `useStickToBottom`. */
  scrollerRef?: ((element: HTMLDivElement | null) => void) | undefined;
  /** The chat's stick-to-bottom state; without it the transcript only renders. */
  follow?: StickToBottom | undefined;
}

const isEditable = (target: EventTarget) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/** Space left above a permission card the chat opens on. */
const OPEN_MARGIN_PX = 16;

const NOTICE_ICON: Record<NoticeTone, IconName> = {
  info: "info",
  warning: "triangle-alert",
  error: "circle-alert",
};

function Entry({
  entry,
  state,
  onAnswerPermission,
}: {
  entry: TranscriptEntry;
  state: TranscriptState;
  onAnswerPermission: TranscriptProps["onAnswerPermission"];
}) {
  switch (entry.kind) {
    case "user":
      return (
        <div className="as-msg as-msg-user">
          <span className="ah-sr">You: </span>
          <div className="as-bubble">{entry.text}</div>
          {entry.redacted && <StoredCopyLabel />}
        </div>
      );
    case "assistant":
      return (
        <article
          className={cx("as-msg as-msg-assistant", entry.streaming && "as-streaming")}
          aria-label="Claude"
        >
          <Markdown source={entry.text} className="as-md" />
          {entry.streaming && <span className="as-caret" aria-hidden="true" />}
          {entry.redacted && <StoredCopyLabel />}
        </article>
      );
    case "thinking":
      return (
        <details className="as-thinking">
          <summary>
            <Icon name="lightbulb" size="sm" /> Thinking
            {entry.redacted && <StoredCopyLabel />}
          </summary>
          <div className="as-thinking-text">{entry.text}</div>
        </details>
      );
    case "tool": {
      const tool = state.tools[entry.toolId];
      return tool ? <ToolCallCard tool={tool} tools={state.tools} calls={state.children} /> : null;
    }
    case "permission": {
      const request = state.permissions[entry.requestId];
      if (!request) return null;
      return (
        <PermissionCard
          request={request}
          onAnswer={
            onAnswerPermission ? (answer) => onAnswerPermission(entry.requestId, answer) : undefined
          }
        />
      );
    }
    case "notice":
      return (
        <p className={cx("as-notice", `as-notice-${entry.tone}`)}>
          <Icon name={NOTICE_ICON[entry.tone]} size="sm" />
          {entry.text}
        </p>
      );
  }
}

/**
 * The conversation of an agent session (D10, AC-165.43): user messages, streamed assistant text
 * through the safe Markdown renderer, thinking collapsed, tool calls collapsed, permission cards
 * and notices. The region is `aria-live="polite"` and `aria-busy` while a block streams, so screen
 * readers announce a block once it completes instead of every delta.
 */
export function Transcript({ state, onAnswerPermission, scrollerRef, follow }: TranscriptProps) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const opened = useRef(false);
  const attach = useCallback(
    (element: HTMLDivElement | null) => {
      scroller.current = element;
      scrollerRef?.(element);
    },
    [scrollerRef],
  );
  const oldestPending = pendingPermissions(state)[0];
  const release = follow?.release;

  // Opens once, on the loaded transcript (AC-234.17): at the oldest pending permission card,
  // else at the latest entry (the stick-to-bottom hook starts pinned).
  useEffect(() => {
    if (opened.current || !release) return;
    opened.current = true;
    if (oldestPending === undefined) return;
    const element = scroller.current;
    const card = Array.from(element?.querySelectorAll<HTMLElement>("[data-request-id]") ?? []).find(
      (candidate) => candidate.dataset.requestId === oldestPending,
    );
    if (!element || !card) return;
    release();
    // `.as-scroll` is positioned, so the card's offset is from the scroller's top.
    element.scrollTop = Math.max(0, card.offsetTop - OPEN_MARGIN_PX);
  }, [oldestPending, release]);

  // Entries that arrived while the reader was away from the bottom (AC-234.19).
  const count = state.entries.length;
  const atBottom = follow?.atBottom ?? true;
  const [seen, setSeen] = useState(count);
  if (atBottom && seen !== count) setSeen(count);
  const unseen = atBottom ? 0 : Math.max(0, count - seen);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "End" || !follow || isEditable(event.target)) return;
    event.preventDefault();
    follow.pin("smooth");
  };

  return (
    <div className="as-body">
      {/* A scroll container takes focus so the keyboard can scroll it and press End. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex, jsx-a11y/no-static-element-interactions */}
      <div className="as-scroll" ref={attach} tabIndex={0} onKeyDown={onKeyDown}>
        <div
          className="as-transcript as-column"
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          aria-busy={state.streaming}
          aria-label="Conversation"
        >
          {state.entries.length === 0 && (
            <p className="ah-muted as-empty">No messages yet. Write the first one below.</p>
          )}
          {state.entries.map((entry) => (
            <Entry
              key={entry.key}
              entry={entry}
              state={state}
              onAnswerPermission={onAnswerPermission}
            />
          ))}
        </div>
      </div>
      {follow && !atBottom && (
        <JumpToLatest
          unseen={unseen}
          onJump={() => {
            follow.pin("smooth");
          }}
        />
      )}
    </div>
  );
}
