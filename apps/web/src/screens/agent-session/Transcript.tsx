import "./agent-session.css";

import {
  memo,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Icon, Markdown, ScreenshotThumb, type IconName } from "../../components";
import { cx } from "../../lib/cx";
import { JumpToLatest } from "./JumpToLatest";
import { MessageMeta } from "./MessageMeta";
import { RequestCard, type PermissionAnswer } from "./PermissionCard";
import { OpenReviewFileContext, ReviewBubble } from "./ReviewDiff";
import { parseReview } from "./review";
import { runFilesOf } from "./RunFilesCard";
import { StoredCopyLabel } from "./SessionStatus";
import { ActivityPanel, ActivityRun, ThinkingBlock, type ActivityStep } from "./ActivityRun";
import {
  pendingPermissions,
  type ChangedFile,
  type NoticeTone,
  type PermissionView,
  type TranscriptEntry,
  type TranscriptState,
} from "./model";
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
  /** The screenshot this browser sent with the first prompt (memory only); else the marker's label. */
  screenshotUrl?: string | undefined;
  /** The images this browser sent with later messages, by the message's seq. */
  messageScreenshots?: Readonly<Record<number, readonly string[]>> | undefined;
  /** The files the session changed: each run that changed some shows them as a card. */
  files?: readonly ChangedFile[] | undefined;
  /** The change each file was marked viewed at, by path. */
  reviewed?: Readonly<Record<string, string>> | undefined;
  /** Opens the Changed files drawer on a file (null: on its list). */
  onOpenFile?: ((path: string | null) => void) | undefined;
  /** Another drawer the page opened (Changed files): it takes the side panel's place. */
  sidePanel?: ReactNode;
  /** A run line opened the activity drawer: the page closes its own. */
  onActivityOpen?: (() => void) | undefined;
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

type RunEntry = Extract<TranscriptEntry, { kind: "tool" | "thinking" }>;
type Row =
  { kind: "entry"; entry: TranscriptEntry } | { kind: "run"; key: string; entries: RunEntry[] };

/** What the log shows from `start` on: attached cards leave their place, and what Claude does
 * between two messages (its calls and the thoughts between them) becomes one run. A run is keyed
 * by its first entry in the whole list, so it keeps its node as it grows or as earlier entries
 * join it a frame later (AC-234.24). Thoughts with no call among them stay plain entries. */
function rowsOf(entries: readonly TranscriptEntry[], attached: Set<string>, start: number): Row[] {
  const rows: Row[] = [];
  let key: string | null = null;
  let run: RunEntry[] = [];
  let hasCall = false;
  const flush = () => {
    if (key !== null && run.length > 0) {
      if (hasCall) rows.push({ kind: "run", key, entries: run });
      else rows.push(...run.map((entry): Row => ({ kind: "entry", entry })));
    }
    key = null;
    run = [];
    hasCall = false;
  };
  entries.forEach((entry, index) => {
    if (entry.kind === "permission" && attached.has(entry.requestId)) return;
    if (entry.kind === "tool" || entry.kind === "thinking") {
      key ??= entry.key;
      if (entry.kind === "tool") hasCall = true;
      if (index >= start) run.push(entry);
      return;
    }
    flush();
    if (index >= start) rows.push({ kind: "entry", entry });
  });
  flush();
  return rows;
}

function firstShown(state: TranscriptState): number {
  const { entries } = state;
  const oldest = pendingPermissions(state)[0];
  const attached = oldest !== undefined && attachedRequests(entries).has(oldest);
  // An attached card shows with its tool call, so the first render starts there.
  const card = entries.findIndex((entry) =>
    attached
      ? entry.kind === "tool" && entry.toolId === oldest
      : entry.kind === "permission" && entry.requestId === oldest,
  );
  const tail = entries.length - FIRST_ENTRIES;
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

/** Claude's text; the parse is memoised by text, so only a changed bubble parses again. A code
 * block still streaming stays plain; it is highlighted once its fence closes or the text ends. */
function AssistantText({ entry }: { entry: AssistantEntry }) {
  const body = useMemo(
    () => <Markdown source={entry.text} streaming={entry.streaming} className="as-md" />,
    [entry.text, entry.streaming],
  );
  return (
    <article
      className={cx("as-msg as-msg-assistant", entry.streaming && "as-streaming")}
      aria-label="Claude"
    >
      {body}
      {entry.streaming && <span className="as-caret" aria-hidden="true" />}
      {entry.redacted && <StoredCopyLabel />}
      {!entry.streaming && <MessageMeta at={entry.at} text={entry.text} />}
    </article>
  );
}

interface EntryProps {
  entry: TranscriptEntry;
  /** Only what this entry shows, so a delta elsewhere leaves its props equal (memo). */
  request?: PermissionView | undefined;
  onAnswerPermission: TranscriptProps["onAnswerPermission"];
  /** Set only on a user message with the screenshot marker: the images this browser kept for
   * it (memo: the same array while nothing changes). */
  screenshotUrls?: readonly string[] | undefined;
}

/** One of your messages; `note` says where it stands (sending, queued). A recorded one (`at`)
 * has the action row; one still sending does not. */
function UserMessage({
  text,
  note,
  at,
  redacted = false,
  screenshotCount = 0,
  screenshotUrls = [],
}: {
  text: string;
  note?: string | null;
  at?: string;
  redacted?: boolean;
  /** How many images went with it (the record's markers). */
  screenshotCount?: number;
  screenshotUrls?: readonly string[] | undefined;
}) {
  const many = Math.max(screenshotCount, screenshotUrls.length) > 1;
  return (
    <div className={cx("as-msg as-msg-user", note && "as-msg-pending")}>
      <span className="ah-sr">You: </span>
      {screenshotUrls.length > 0 ? (
        <div className="as-shots">
          {screenshotUrls.map((url, index) => (
            <ScreenshotThumb
              key={index}
              className="as-shot"
              src={url}
              alt={
                many
                  ? `Image ${String(index + 1)} sent with this message`
                  : "Screenshot sent with this message"
              }
            />
          ))}
        </div>
      ) : (
        screenshotCount > 0 && (
          <span className="ah-small ah-muted">
            {many ? `${String(screenshotCount)} images attached` : "Screenshot attached"}
          </span>
        )
      )}
      {parseReview(text) ? <ReviewBubble text={text} /> : <div className="as-bubble">{text}</div>}
      {note && <span className="ah-small ah-muted">{note}</span>}
      {redacted && <StoredCopyLabel />}
      {at !== undefined && <MessageMeta at={at} text={text} />}
    </div>
  );
}

function EntryBody({ entry, request, onAnswerPermission, screenshotUrls }: EntryProps) {
  switch (entry.kind) {
    case "user":
      return (
        <UserMessage
          text={entry.text}
          note={entry.queued ? "Queued: Claude reads it after this turn" : null}
          at={entry.at}
          redacted={entry.redacted}
          screenshotCount={entry.screenshotCount}
          screenshotUrls={screenshotUrls}
        />
      );
    case "assistant":
      return <AssistantText entry={entry} />;
    case "thinking":
      return <ThinkingBlock entry={entry} />;
    case "tool":
      // A call shows in its run (ActivityRun).
      return null;
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
export function Transcript({
  state,
  onAnswerPermission,
  scrollerRef,
  follow,
  screenshotUrl,
  messageScreenshots,
  files,
  reviewed,
  onOpenFile,
  sidePanel,
  onActivityOpen,
}: TranscriptProps) {
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
  const headingId = useId();
  // The first prompt's screenshot is the session's; a later message's images are by its seq.
  const firstUserSeq = state.entries.find((entry) => entry.kind === "user")?.seq;
  const sessionShots = useMemo(
    () => (screenshotUrl ? [screenshotUrl] : undefined),
    [screenshotUrl],
  );
  const shotsOf = (seq: number) =>
    messageScreenshots?.[seq] ?? (seq === firstUserSeq ? sessionShots : undefined);

  // The run the side panel shows; closing gives focus back to its line.
  const [panelRun, setPanelRun] = useState<string | null>(null);
  // Kept stable for the memoised run lines: the latest callback is read when a line is pressed.
  const sideOpen = Boolean(sidePanel);
  const activityOpened = useRef(onActivityOpen);
  useEffect(() => {
    activityOpened.current = onActivityOpen;
  });
  const toggleRun = useCallback(
    (runKey: string) => {
      activityOpened.current?.();
      setPanelRun((current) => (current === runKey && !sideOpen ? null : runKey));
    },
    [sideOpen],
  );
  const closePanel = useCallback(() => {
    const key = panelRun;
    setPanelRun(null);
    const line = Array.from(
      scroller.current?.querySelectorAll<HTMLElement>("[data-run-key]") ?? [],
    ).find((element) => element.dataset.runKey === key);
    line?.focus({ preventScroll: true });
  }, [panelRun]);

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

  const stepsOf = (runEntries: readonly RunEntry[]): ActivityStep[] =>
    runEntries.flatMap((entry): ActivityStep[] => {
      if (entry.kind === "thinking") return [{ kind: "thinking", key: entry.key, entry }];
      const tool = state.tools[entry.toolId];
      return tool
        ? [{ kind: "tool", key: entry.key, tool, request: attachedTo(entry.toolId) }]
        : [];
    });
  const rows = rowsOf(state.entries, attached, start);
  // A run's calls and, under a subagent's call, the calls it made, at any depth.
  const runToolIds = (runEntries: readonly RunEntry[]): Set<string> => {
    const ids = new Set<string>();
    const add = (id: string) => {
      if (ids.has(id)) return;
      ids.add(id);
      for (const child of state.children[id] ?? []) add(child);
    };
    for (const entry of runEntries) if (entry.kind === "tool") add(entry.toolId);
    return ids;
  };
  const shownRun =
    panelRun === null ? undefined : rows.find((row) => row.kind === "run" && row.key === panelRun);
  const panelSteps = shownRun?.kind === "run" && !sidePanel ? stepsOf(shownRun.entries) : null;

  return (
    <OpenReviewFileContext.Provider value={onOpenFile ?? null}>
      <div className={cx("as-body", (panelSteps !== null || sideOpen) && "as-body-panel")}>
        {/* A scroll container takes focus so the keyboard can scroll it and press End. */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex, jsx-a11y/no-static-element-interactions */}
        <div className="as-scroll" ref={attach} tabIndex={0} onKeyDown={onKeyDown}>
          {/* Screen-reader users reach the log by heading (AC-234.30). */}
          <h2 id={headingId} className="ah-sr">
            Conversation
          </h2>
          <div
            className="as-transcript as-column"
            role="log"
            aria-live="polite"
            aria-relevant="additions text"
            aria-busy={state.streaming || start > 0}
            aria-labelledby={headingId}
          >
            {state.entries.length === 0 && (
              <p className="ah-muted as-empty">No messages yet. Write the first one below.</p>
            )}
            {rows.map((row) => {
              if (row.kind === "run") {
                return (
                  <div key={row.key} className="as-entry as-settled">
                    <ActivityRun
                      runKey={row.key}
                      steps={stepsOf(row.entries)}
                      selected={row.key === panelRun && !sidePanel}
                      live={state.status === "running"}
                      onToggle={toggleRun}
                      onAnswerPermission={onAnswerPermission}
                      files={files && runFilesOf(files, runToolIds(row.entries))}
                      reviewed={reviewed}
                      onOpenFile={onOpenFile}
                    />
                  </div>
                );
              }
              const { entry } = row;
              return (
                <Entry
                  key={entry.key}
                  entry={entry}
                  {...(entry.kind === "permission" && {
                    request: state.permissions[entry.requestId],
                  })}
                  {...(entry.kind === "user" &&
                    entry.screenshot && { screenshotUrls: shotsOf(entry.seq) })}
                  onAnswerPermission={onAnswerPermission}
                />
              );
            })}
          </div>
          {/* Outside the live log: only the echoed record is announced, not its Sending… copy too. */}
          <div className="as-pending as-column">
            {state.sending.map((send) => (
              <div key={send.key} className="as-entry">
                <UserMessage
                  text={send.text}
                  note="Sending…"
                  screenshotCount={send.screenshots?.length ?? 0}
                  screenshotUrls={send.screenshots}
                />
              </div>
            ))}
          </div>
          {/* One live region stays mounted while the session lives, so its text changes are announced. */}
          {state.status !== "ended" && state.status !== "failed" && (
            <p
              className={cx(
                "as-working as-column ah-small ah-muted",
                !working && "as-working-idle",
              )}
              role="status"
            >
              {working ? ["Claude is working", activeTool(state)].filter(Boolean).join(" · ") : ""}
            </p>
          )}
        </div>
        {sidePanel}
        {panelSteps && (
          <ActivityPanel
            steps={panelSteps}
            tools={state.tools}
            calls={state.children}
            requests={state.permissions}
            onClose={closePanel}
          />
        )}
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
    </OpenReviewFileContext.Provider>
  );
}
