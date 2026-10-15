import "./agent-session.css";

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { Icon, Markdown, type IconName } from "../../components";
import { cx } from "../../lib/cx";
import { JumpToLatest } from "./JumpToLatest";
import { RequestCard, type PermissionAnswer } from "./PermissionCard";
import { StoredCopyLabel } from "./SessionStatus";
import { ToolCallCard } from "./ToolCallCard";
import { ToolGroup, type GroupItem } from "./ToolGroup";
import {
  pendingPermissions,
  type NoticeTone,
  type PermissionView,
  type ToolView,
  type TranscriptEntry,
  type TranscriptState,
} from "./transcript";
import { isEditable, type StickToBottom } from "./useStickToBottom";

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

/** The first render shows the latest entries only, from the oldest pending card at the latest;
 * the earlier ones follow a frame later (run budget: 2,000 entries render in under a second). */
export const FIRST_ENTRIES = 300;

/** The requests whose card shows under their tool call (matched by `tool_use_id`, AC-234.24). */
function attachedRequests(entries: readonly TranscriptEntry[]): Set<string> {
  const calls = new Set(entries.flatMap((entry) => (entry.kind === "tool" ? [entry.toolId] : [])));
  return new Set(
    entries.flatMap((entry) =>
      entry.kind === "permission" && calls.has(entry.requestId) ? [entry.requestId] : [],
    ),
  );
}

type ToolEntry = Extract<TranscriptEntry, { kind: "tool" }>;
type Row =
  { kind: "entry"; entry: TranscriptEntry } | { kind: "group"; key: string; entries: ToolEntry[] };

/** What the log shows: attached cards leave their place, and consecutive tool calls with no
 * text between them become one group (AC-234.24). */
function rowsOf(entries: readonly TranscriptEntry[], attached: Set<string>): Row[] {
  const rows: Row[] = [];
  let run: ToolEntry[] = [];
  const flush = () => {
    const [first] = run;
    if (first && run.length > 1) rows.push({ kind: "group", key: `g-${first.key}`, entries: run });
    else if (first) rows.push({ kind: "entry", entry: first });
    run = [];
  };
  for (const entry of entries) {
    if (entry.kind === "permission" && attached.has(entry.requestId)) continue;
    if (entry.kind === "tool") {
      run.push(entry);
      continue;
    }
    flush();
    rows.push({ kind: "entry", entry });
  }
  flush();
  return rows;
}

function firstShown(state: TranscriptState): number {
  const oldest = pendingPermissions(state)[0];
  const attached = oldest !== undefined && attachedRequests(state.entries).has(oldest);
  // An attached card shows with its tool call, so the first render starts there.
  const card = state.entries.findIndex((entry) =>
    attached
      ? entry.kind === "tool" && entry.toolId === oldest
      : entry.kind === "permission" && entry.requestId === oldest,
  );
  const tail = state.entries.length - FIRST_ENTRIES;
  return Math.max(0, card >= 0 ? Math.min(card, tail) : tail);
}

/** The tool a running turn waits on: the latest call without a result. */
function activeTool(state: TranscriptState): string | null {
  const running = Object.values(state.tools).filter((tool) => tool.result === null);
  return running.at(-1)?.name ?? null;
}

/** Space left above a permission card the chat opens on. */
const OPEN_MARGIN_PX = 16;

const NOTICE_ICON: Record<NoticeTone, IconName> = {
  info: "info",
  warning: "triangle-alert",
  error: "circle-alert",
};

type AssistantEntry = Extract<TranscriptEntry, { kind: "assistant" }>;

/** Claude's text; the parse is memoised by text, so only a changed bubble parses again. */
function AssistantText({ entry }: { entry: AssistantEntry }) {
  const body = useMemo(() => <Markdown source={entry.text} className="as-md" />, [entry.text]);
  return (
    <article
      className={cx("as-msg as-msg-assistant", entry.streaming && "as-streaming")}
      aria-label="Claude"
    >
      {body}
      {entry.streaming && <span className="as-caret" aria-hidden="true" />}
      {entry.redacted && <StoredCopyLabel />}
    </article>
  );
}

interface EntryProps {
  entry: TranscriptEntry;
  /** Only what this entry shows, so a delta elsewhere leaves its props equal (memo). A tool
   * call's `request` is the permission asked for it, shown under its card. */
  tool?: ToolView | undefined;
  tools?: TranscriptState["tools"] | undefined;
  calls?: TranscriptState["children"] | undefined;
  request?: PermissionView | undefined;
  onAnswerPermission: TranscriptProps["onAnswerPermission"];
}

/** One of your messages; `note` says where it stands (sending, queued). */
function UserMessage({
  text,
  note,
  redacted = false,
}: {
  text: string;
  note?: string | null;
  redacted?: boolean;
}) {
  return (
    <div className={cx("as-msg as-msg-user", note && "as-msg-pending")}>
      <span className="ah-sr">You: </span>
      <div className="as-bubble">{text}</div>
      {note && <span className="ah-small ah-muted">{note}</span>}
      {redacted && <StoredCopyLabel />}
    </div>
  );
}

function EntryBody({ entry, tool, tools, calls, request, onAnswerPermission }: EntryProps) {
  switch (entry.kind) {
    case "user":
      return (
        <UserMessage
          text={entry.text}
          note={entry.queued ? "Queued: Claude reads it after this turn" : null}
          redacted={entry.redacted}
        />
      );
    case "assistant":
      return <AssistantText entry={entry} />;
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
    case "tool":
      return tool && tools && calls ? (
        <>
          <ToolCallCard tool={tool} tools={tools} calls={calls} request={request} />
          {request && <RequestCard request={request} onAnswerPermission={onAnswerPermission} />}
        </>
      ) : null;
    case "permission":
      return request ? (
        <RequestCard request={request} onAnswerPermission={onAnswerPermission} />
      ) : null;
    case "notice":
      return (
        <p className={cx("as-notice", `as-notice-${entry.tone}`)}>
          <Icon name={NOTICE_ICON[entry.tone]} size="sm" />
          {entry.text}
        </p>
      );
  }
}

/** One entry; a settled one lets the browser skip its layout while off screen. */
const Entry = memo(function Entry(props: EntryProps) {
  const streaming = props.entry.kind === "assistant" && props.entry.streaming;
  return (
    <div className={cx("as-entry", !streaming && "as-settled")}>
      <EntryBody {...props} />
    </div>
  );
});

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
  const attached = useMemo(() => attachedRequests(state.entries), [state.entries]);
  const attachedTo = (toolId: string) =>
    attached.has(toolId) ? state.permissions[toolId] : undefined;
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

  // The earlier entries, a frame after the first render; what was in view stays in view (the
  // browser's scroll anchoring does it too, and then the position is already right).
  const [start, setStart] = useState(() => firstShown(state));
  const before = useRef<{ top: number; height: number } | null>(null);
  useEffect(() => {
    if (start === 0) return undefined;
    const frame = requestAnimationFrame(() => {
      const element = scroller.current;
      before.current = element && { top: element.scrollTop, height: element.scrollHeight };
      setStart(0);
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [start]);
  useLayoutEffect(() => {
    const element = scroller.current;
    const was = before.current;
    before.current = null;
    if (start !== 0 || !element || !was) return;
    element.scrollTop = was.top + element.scrollHeight - was.height;
  }, [start]);

  // Entries that arrived while the reader was away from the bottom (AC-234.19).
  const count = state.entries.length;
  const atBottom = follow?.atBottom ?? true;
  const [seen, setSeen] = useState(count);
  if (atBottom && seen !== count) setSeen(count);
  const unseen = atBottom ? 0 : Math.max(0, count - seen);

  const working = state.status === "running" && !state.streaming;

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
          aria-busy={state.streaming || start > 0}
          aria-label="Conversation"
        >
          {state.entries.length === 0 && (
            <p className="ah-muted as-empty">No messages yet. Write the first one below.</p>
          )}
          {rowsOf(state.entries.slice(start), attached).map((row) => {
            if (row.kind === "group") {
              const items = row.entries.flatMap(({ toolId }): GroupItem[] => {
                const tool = state.tools[toolId];
                return tool ? [{ tool, request: attachedTo(toolId) }] : [];
              });
              return (
                <div key={row.key} className="as-entry">
                  <ToolGroup
                    items={items}
                    tools={state.tools}
                    calls={state.children}
                    onAnswerPermission={onAnswerPermission}
                  />
                </div>
              );
            }
            const { entry } = row;
            return (
              <Entry
                key={entry.key}
                entry={entry}
                {...(entry.kind === "tool" && {
                  tool: state.tools[entry.toolId],
                  tools: state.tools,
                  calls: state.children,
                  request: attachedTo(entry.toolId),
                })}
                {...(entry.kind === "permission" && {
                  request: state.permissions[entry.requestId],
                })}
                onAnswerPermission={onAnswerPermission}
              />
            );
          })}
          {state.sending.map((send) => (
            <div key={send.key} className="as-entry">
              <UserMessage text={send.text} note="Sending…" />
            </div>
          ))}
        </div>
        {/* One live region stays mounted while the session lives, so its text changes are announced. */}
        {state.status !== "ended" && state.status !== "failed" && (
          <p
            className={cx("as-working as-column ah-small ah-muted", !working && "as-working-idle")}
            role="status"
          >
            {working ? ["Claude is working", activeTool(state)].filter(Boolean).join(" · ") : ""}
          </p>
        )}
      </div>
      {follow && !atBottom && (
        <JumpToLatest
          unseen={unseen}
          onJump={() => {
            // The button goes away once pinned: keep keyboard focus in the chat, not on <body>.
            scroller.current?.focus({ preventScroll: true });
            follow.pin("smooth");
          }}
        />
      )}
    </div>
  );
}
