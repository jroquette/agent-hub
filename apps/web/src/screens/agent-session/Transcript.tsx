import "./agent-session.css";

import { Icon, Markdown, type IconName } from "../../components";
import { cx } from "../../lib/cx";
import { PermissionCard, type PermissionAnswer } from "./PermissionCard";
import { StoredCopyLabel } from "./SessionStatus";
import { ToolCallCard } from "./ToolCallCard";
import type { NoticeTone, TranscriptEntry, TranscriptState } from "./transcript";

export interface TranscriptProps {
  state: TranscriptState;
  /** Posts a permission answer; without it the cards are read-only. */
  onAnswerPermission?:
    ((requestId: string, answer: PermissionAnswer) => Promise<unknown> | undefined) | undefined;
}

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
export function Transcript({ state, onAnswerPermission }: TranscriptProps) {
  return (
    <div
      className="as-transcript"
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
  );
}
