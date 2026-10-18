import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { Button, Icon, SegmentedControl } from "../../components";
import { cx } from "../../lib/cx";
import { readStored, writeStored } from "../../lib/storage";
import { useDrawerWidth } from "./DrawerResize";
import { ReviewCommentsContext, ReviewDiff, type ReviewComments } from "./ReviewDiff";
import { DiffText, TOOL_STATE } from "./ToolCallCard";
import { commonDir, type ChangedFile, type FileChange } from "./model";

/** The DOM id of the files drawer, for the header button's `aria-controls`. */
export const FILES_PANEL_ID = "as-files-panel";

export const reviewedKey = (sessionId: string) => `ah.chat.reviewed.${sessionId}`;

/** The change each file was marked viewed at, by path. */
type Reviewed = Record<string, string>;

function readReviewed(sessionId: string): Reviewed {
  try {
    const value: unknown = JSON.parse(readStored(reviewedKey(sessionId)) ?? "{}");
    if (!value || typeof value !== "object") return {};
    return Object.fromEntries(
      Object.entries(value).filter((pair): pair is [string, string] => typeof pair[1] === "string"),
    );
  } catch {
    return {};
  }
}

/**
 * Which files you marked viewed, kept in this browser per session. A mark holds the file's latest
 * change at the time: a newer change reads as not viewed again, like a code review.
 */
export function useReviewed(sessionId: string) {
  const [reviewed, setReviewed] = useState<Reviewed>(() => readReviewed(sessionId));
  const toggle = useCallback(
    (file: ChangedFile) => {
      setReviewed((before) => {
        const next =
          before[file.path] === file.lastChangeId
            ? Object.fromEntries(Object.entries(before).filter(([path]) => path !== file.path))
            : { ...before, [file.path]: file.lastChangeId };
        writeStored(reviewedKey(sessionId), JSON.stringify(next));
        return next;
      });
    },
    [sessionId],
  );
  return { reviewed, toggle };
}

const CHANGE_VERB: Record<string, string> = {
  Edit: "Edited",
  MultiEdit: "Edited",
  Write: "Wrote the file",
  NotebookEdit: "Edited the notebook",
};

/** Lines added and removed, in the diff colours. */
export function Stats({ added, removed }: { added: number; removed: number }) {
  return (
    <span className="as-files-stats">
      <span className="as-files-add">+{added}</span>
      <span className="as-files-del">−{removed}</span>
    </span>
  );
}

function ChangeBlock({
  change,
  index,
  total,
  path,
  filePath,
}: {
  change: FileChange;
  index: number;
  total: number;
  /** The name shown (relative to the drawer's root). */
  path: string;
  /** The file's full path, as Claude knows it: review comments anchor to it. */
  filePath: string;
}) {
  const { icon, text } = TOOL_STATE[change.state];
  const applied = change.state !== "error" && change.state !== "denied";
  const comments = useContext(ReviewCommentsContext);
  const threads =
    comments?.threads.filter(
      (thread) => thread.anchor.path === filePath && thread.anchor.change === index + 1,
    ) ?? [];
  return (
    <div className={cx("as-files-change", !applied && "as-files-change-skipped")}>
      <div className="as-files-change-head ah-small">
        <span>
          {total > 1 && <b>{`${String(index + 1)}/${String(total)} · `}</b>}
          {CHANGE_VERB[change.tool.name] ?? change.tool.name}
        </span>
        <Stats added={change.added} removed={change.removed} />
        <span className="ah-grow" />
        <span className={cx("as-files-state", `as-files-state-${change.state}`)}>
          <Icon name={icon} size="sm" />
          {applied ? text : `${text}: not applied`}
        </span>
      </div>
      {comments ? (
        <ReviewDiff
          diff={change.diff}
          label={`Change ${String(index + 1)} to ${path}`}
          numbered={change.numbered}
          path={filePath}
          change={index + 1}
          threads={threads}
          resolved={comments.resolved}
          onComment={applied ? comments.onComment : undefined}
        />
      ) : (
        <DiffText
          diff={change.diff}
          label={`Change ${String(index + 1)} to ${path}`}
          numbered={change.numbered}
        />
      )}
    </div>
  );
}

/** A file's final diff: what all its changes add up to, open to review comments (change 0). */
function NetBlock({ file, path }: { file: ChangedFile; path: string }) {
  const comments = useContext(ReviewCommentsContext);
  const net = file.net;
  if (!net) return null;
  const label = `Final diff of ${path}`;
  if (net.added === 0 && net.removed === 0) {
    return <p className="ah-small ah-muted">The changes cancel out: the file ends as it began.</p>;
  }
  const threads =
    comments?.threads.filter(
      (thread) => thread.anchor.path === file.path && thread.anchor.change === 0,
    ) ?? [];
  return (
    <div className="as-files-change">
      {comments ? (
        <ReviewDiff
          diff={net.diff}
          label={label}
          numbered={net.numbered}
          path={file.path}
          change={0}
          threads={threads}
          resolved={comments.resolved}
          onComment={comments.onComment}
        />
      ) : (
        <DiffText diff={net.diff} label={label} numbered={net.numbered} />
      )}
    </div>
  );
}

type DetailView = "final" | "changes";

/** How many review threads on a file are still open, as a small speech-bubble count. */
function OpenThreads({ path }: { path: string }) {
  const comments = useContext(ReviewCommentsContext);
  if (!comments) return null;
  const open = comments.threads.filter(
    (thread) => thread.anchor.path === path && !comments.resolved.resolved.has(thread.key),
  ).length;
  if (open === 0) return null;
  return (
    <span className="as-files-threads" title={`${String(open)} open review comments`}>
      <Icon name="message-square" size="sm" />
      {open}
    </span>
  );
}

/** The drawer is wide enough for the list beside the file (px). */
export const SPLIT_MIN = 720;

/** Whether `element` is at least `min` px wide, followed as it resizes (false without a
 * ResizeObserver: the narrow, one-pane layout). */
function useWiderThan(element: HTMLElement | null, min: number): boolean {
  const [wider, setWider] = useState(false);
  useEffect(() => {
    if (!element || typeof ResizeObserver !== "function") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWider(entry.contentRect.width >= min);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [element, min]);
  return wider;
}

/** A file's status letter: A (new) or M (modified). */
export function KindBadge({ created }: { created: boolean }) {
  return (
    <span
      className={cx("as-files-kind", created ? "as-files-kind-a" : "as-files-kind-m")}
      title={created ? "New file" : "Modified"}
    >
      {created ? "A" : "M"}
    </span>
  );
}

function ViewedToggle({
  viewed,
  stale,
  onToggle,
  compact = false,
}: {
  viewed: boolean;
  stale: boolean;
  onToggle: () => void;
  compact?: boolean;
}) {
  const text = stale ? "Changed since viewed" : "Viewed";
  return (
    <label
      className={cx(
        "as-files-viewed",
        viewed && "as-files-viewed-on",
        stale && "as-files-viewed-stale",
        compact && "as-files-viewed-compact",
      )}
      title={text}
    >
      <input type="checkbox" checked={viewed} onChange={onToggle} aria-label={text} />
      {!compact && text}
    </label>
  );
}

/** Files by folder, folders in the order their first file changed. */
function byFolder(files: readonly ChangedFile[], nameOf: (path: string) => string) {
  const folders = new Map<string, ChangedFile[]>();
  for (const file of files) {
    const name = nameOf(file.path);
    const folder = name.slice(0, name.lastIndexOf("/") + 1);
    folders.set(folder, [...(folders.get(folder) ?? []), file]);
  }
  return [...folders.entries()];
}

export interface ReviewState {
  reviewed: Record<string, string>;
  toggle: (file: ChangedFile) => void;
}

/** Whether `file` is marked viewed at its latest change. */
export const isViewed = (review: ReviewState, file: ChangedFile) =>
  review.reviewed[file.path] === file.lastChangeId;

/** The changed files as a list, like a source-control view: by folder, each with its status,
 * lines added and removed, and whether you viewed it. */
function FileList({
  files,
  nameOf,
  base,
  selected,
  review,
  onSelect,
}: {
  files: readonly ChangedFile[];
  nameOf: (path: string) => string;
  base: string;
  selected: string | null;
  review: ReviewState;
  onSelect: (path: string) => void;
}) {
  const viewedCount = files.filter(
    (file) => review.reviewed[file.path] === file.lastChangeId,
  ).length;
  return (
    <nav className="as-files-nav" aria-label="Files">
      <div className="as-files-progress ah-small">
        <span>
          {viewedCount} of {files.length} viewed
        </span>
        <span className="as-files-meter" aria-hidden="true">
          <span style={{ width: `${String((viewedCount / files.length) * 100)}%` }} />
        </span>
      </div>
      {base && (
        <p className="as-files-root ah-small ah-subtle" title={base}>
          {base}
        </p>
      )}
      {byFolder(files, nameOf).map(([folder, inFolder]) => (
        <div key={folder} className="as-files-group">
          {folder && (
            <div className="as-files-folder ah-small" title={base + folder}>
              <Icon name="folder" size="sm" />
              <span>{folder.slice(0, -1)}</span>
            </div>
          )}
          <ul>
            {inFolder.map((file) => {
              const mark = review.reviewed[file.path];
              const viewed = mark === file.lastChangeId;
              const name = nameOf(file.path);
              return (
                <li
                  key={file.path}
                  className={cx(
                    "as-files-row",
                    selected === file.path && "as-files-row-selected",
                    viewed && "as-files-row-viewed",
                  )}
                >
                  <button
                    type="button"
                    className="as-files-row-open"
                    title={file.path}
                    data-file-path={file.path}
                    aria-current={selected === file.path ? "true" : undefined}
                    onClick={() => {
                      onSelect(file.path);
                    }}
                  >
                    <KindBadge created={file.created} />
                    <span className="as-files-nav-name">
                      {name.slice(name.lastIndexOf("/") + 1)}
                    </span>
                    <OpenThreads path={file.path} />
                    <Stats added={file.added} removed={file.removed} />
                  </button>
                  <ViewedToggle
                    compact
                    viewed={viewed}
                    stale={mark !== undefined && !viewed}
                    onToggle={() => {
                      review.toggle(file);
                    }}
                  />
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** One file under review: its path and status, then every change to it as a diff, in order. */
function FileDetail({
  file,
  name,
  position,
  total,
  review,
  onBack,
  onStep,
  focusRequest = null,
}: {
  file: ChangedFile;
  name: string;
  position: number;
  total: number;
  review: ReviewState;
  onBack: (() => void) | null;
  onStep: (by: -1 | 1) => void;
  /** A card in the conversation opened this file: each new value moves the keyboard here. */
  focusRequest?: number | null;
}) {
  const mark = review.reviewed[file.path];
  const viewed = mark === file.lastChangeId;
  const slash = name.lastIndexOf("/");
  const body = useRef<HTMLDivElement>(null);
  const section = useRef<HTMLElement>(null);
  const takesFocus = onBack !== null;
  // The final result first; "Each change" stays picked as you step through the files.
  const [view, setView] = useState<DetailView>("final");
  const showNet = file.net !== null && view === "final";
  useEffect(() => {
    if (body.current) body.current.scrollTop = 0;
  }, [file.path]);
  useEffect(() => {
    // Narrow, the list (and the row you pressed) is gone; opened from a card, the file is what
    // you asked for: either way the keyboard moves to the file.
    if (takesFocus || focusRequest !== null) section.current?.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest]);
  return (
    <section ref={section} className="as-files-detail" aria-label={name} tabIndex={-1}>
      <header className="as-files-detail-head">
        {onBack && (
          <Button size="sm" variant="ghost" icon="chevron-left" onClick={onBack}>
            All files
          </Button>
        )}
        <div className="as-files-detail-title">
          <KindBadge created={file.created} />
          <span className="as-files-name" title={file.path}>
            {slash >= 0 && <span className="ah-muted">{name.slice(0, slash + 1)}</span>}
            <b>{name.slice(slash + 1)}</b>
          </span>
          <Stats added={file.added} removed={file.removed} />
        </div>
        <span className="ah-grow" />
        <ViewedToggle
          viewed={viewed}
          stale={mark !== undefined && !viewed}
          onToggle={() => {
            review.toggle(file);
          }}
        />
        <div className="as-files-stepper">
          <Button
            size="sm"
            variant="ghost"
            icon="chevron-up"
            aria-label="Previous file"
            disabled={position === 0}
            onClick={() => {
              onStep(-1);
            }}
          />
          <span className="ah-small ah-muted">
            {position + 1}/{total}
          </span>
          <Button
            size="sm"
            variant="ghost"
            icon="chevron-down"
            aria-label="Next file"
            disabled={position === total - 1}
            onClick={() => {
              onStep(1);
            }}
          />
        </div>
      </header>
      <div className="as-files-detail-body" ref={body}>
        {file.net ? (
          <div className="as-files-summary ah-row">
            <SegmentedControl
              label="Show"
              value={showNet ? "final" : "changes"}
              onChange={(id) => {
                setView(id as DetailView);
              }}
              options={[
                { id: "final", label: "Final result" },
                { id: "changes", label: `Each change (${String(file.changes.length)})` },
              ]}
            />
            <span className="ah-small ah-muted">
              {showNet
                ? `All ${String(file.changes.length)} changes in this session, as one diff`
                : "Oldest first"}
            </span>
          </div>
        ) : (
          <p className="as-files-summary ah-small ah-muted">
            {file.changes.length === 1
              ? "1 change in this session"
              : `${String(file.changes.length)} changes in this session, oldest first`}
          </p>
        )}
        {showNet && <NetBlock file={file} path={name} />}
        {!showNet &&
          file.changes.map((change, index) => (
            <ChangeBlock
              key={change.tool.id}
              change={change}
              index={index}
              total={file.changes.length}
              path={name}
              filePath={file.path}
            />
          ))}
      </div>
    </section>
  );
}

export interface FilesPanelProps {
  files: readonly ChangedFile[];
  sessionId: string;
  onClose: () => void;
  /** The page's review marks, shared with its header chip; without it the drawer keeps its own. */
  review?: ReviewState | undefined;
  /** Open this file (a card in the conversation was pressed); `pickNonce` re-opens it. */
  initialPath?: string | null | undefined;
  pickNonce?: number | undefined;
  /** Review comments on the diffs, sent to the session's Claude (absent: read-only diffs). */
  comments?: ReviewComments | undefined;
}

/**
 * The files Claude changed in this session, for review beside the chat, apart from the rest of
 * its activity. The list reads like source control (by folder, status, lines, viewed); a file
 * opens on its own with its final diff (every change added up), or every change to it in turn. Wide, the list stays beside the open file;
 * narrow, the file takes the drawer and "All files" goes back. Marks are kept per session.
 */
export function FilesPanel({
  files,
  sessionId,
  onClose,
  review: shared,
  initialPath = null,
  pickNonce = 0,
  comments,
}: FilesPanelProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [panel, setPanel] = useState<HTMLElement | null>(null);
  const wide = useWiderThan(panel, SPLIT_MIN);
  const drawer = useDrawerWidth();
  const own = useReviewed(sessionId);
  const review = shared ?? own;
  const [picked, setPicked] = useState<string | null>(initialPath);
  // Opened on a file, the keyboard goes to that file; else to the drawer's heading.
  const [focusFile, setFocusFile] = useState(initialPath !== null);
  useEffect(() => {
    if (initialPath === null) heading.current?.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Another card pressed while the drawer is open: switch to its file.
  const lastNonce = useRef(pickNonce);
  useEffect(() => {
    if (lastNonce.current === pickNonce) return;
    lastNonce.current = pickNonce;
    setPicked(initialPath);
    setFocusFile(initialPath !== null);
  }, [pickNonce, initialPath]);

  const root = useMemo(() => commonDir(files.map((file) => file.path)), [files]);
  // One file alone keeps its folder in view: the root is then its parent's parent.
  const base =
    files.length === 1 ? root.slice(0, root.lastIndexOf("/", root.length - 2) + 1) : root;
  const nameOf = (path: string) => path.slice(base.length);
  const added = files.reduce((sum, file) => sum + file.added, 0);
  const removed = files.reduce((sum, file) => sum + file.removed, 0);

  // Wide, a file is always open (the first by default); narrow, only the one you picked.
  const known = files.some((file) => file.path === picked) ? picked : null;
  const selected = known ?? (wide ? (files[0]?.path ?? null) : null);
  const position = files.findIndex((file) => file.path === selected);
  const open = position >= 0 ? files[position] : undefined;

  // Back to the list, with the keyboard on the row of the file you left.
  const backToList = () => {
    const left = known;
    setPicked(null);
    requestAnimationFrame(() => {
      Array.from(panel?.querySelectorAll<HTMLElement>("[data-file-path]") ?? [])
        .find((row) => row.dataset.filePath === left)
        ?.focus({ preventScroll: true });
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || event.shiftKey) return;
    event.preventDefault();
    event.stopPropagation();
    if (!wide && known !== null) backToList();
    else onClose();
  };

  return (
    // Esc goes back to the list, then closes, from anywhere inside.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <aside
      ref={setPanel}
      id={FILES_PANEL_ID}
      className="as-drawer as-files-panel"
      style={drawer.style}
      aria-labelledby={`${FILES_PANEL_ID}-title`}
      onKeyDown={onKeyDown}
    >
      <div {...drawer.handle} />
      <div className="as-activity-panel-head">
        <Icon name="git-compare" size="sm" />
        <h2
          ref={heading}
          id={`${FILES_PANEL_ID}-title`}
          tabIndex={-1}
          className="ah-h3"
          style={{ margin: 0 }}
        >
          Changed files
        </h2>
        <span className="ah-small ah-muted">
          {files.length} {files.length === 1 ? "file" : "files"} ·{" "}
          <Stats added={added} removed={removed} />
        </span>
        <span className="ah-grow" />
        <Button
          size="sm"
          variant="ghost"
          icon="maximize-2"
          aria-pressed={drawer.wide}
          onClick={drawer.toggleWide}
        >
          {drawer.wide ? "Narrow" : "Widen"}
        </Button>
        <Button size="sm" variant="ghost" icon="x" onClick={onClose}>
          Close
        </Button>
      </div>
      {files.length === 0 ? (
        <p className="ah-muted as-files-empty">Claude has not changed any file yet.</p>
      ) : (
        <ReviewCommentsContext.Provider value={comments ?? null}>
          <div className={cx("as-files-body", wide && "as-files-split")}>
            {(wide || !open) && (
              <FileList
                files={files}
                nameOf={nameOf}
                base={base}
                selected={selected}
                review={review}
                onSelect={setPicked}
              />
            )}
            {open && (
              <FileDetail
                file={open}
                name={nameOf(open.path)}
                position={position}
                total={files.length}
                review={review}
                onBack={wide ? null : backToList}
                focusRequest={focusFile ? pickNonce : null}
                onStep={(by) => {
                  setPicked(files[position + by]?.path ?? selected);
                }}
              />
            )}
          </div>
        </ReviewCommentsContext.Provider>
      )}
    </aside>
  );
}

export interface ChangedFilesChipProps {
  files: readonly ChangedFile[];
  review: ReviewState;
  open: boolean;
  onToggle: () => void;
}

/**
 * The header's way into the review: "5 files +120 −30 · 3 to review", tinted while files wait
 * for review and quiet once all are viewed (a check). Pressed while the drawer is open.
 */
export function ChangedFilesChip({ files, review, open, onToggle }: ChangedFilesChipProps) {
  const added = files.reduce((sum, file) => sum + file.added, 0);
  const removed = files.reduce((sum, file) => sum + file.removed, 0);
  const due = files.filter((file) => !isViewed(review, file)).length;
  const count = `${String(files.length)} ${files.length === 1 ? "file" : "files"}`;
  return (
    <button
      type="button"
      className={cx("as-files-chip", due > 0 && "as-files-chip-due", open && "as-files-chip-open")}
      aria-expanded={open}
      aria-controls={open ? FILES_PANEL_ID : undefined}
      aria-label={`Review changes: ${count}, ${String(added)} lines added, ${String(removed)} removed, ${due > 0 ? `${String(due)} to review` : "all reviewed"}`}
      title={open ? "Close the changed files" : "Open the changed files"}
      onClick={onToggle}
    >
      <Icon name="git-compare" size="sm" />
      <span className="as-files-chip-label">Review changes</span>
      <span className="as-files-chip-count">{count}</span>
      <Stats added={added} removed={removed} />
      {due > 0 ? (
        <span className="as-files-chip-due-count">{due} to review</span>
      ) : (
        <Icon name="circle-check" size="sm" className="as-files-chip-done" />
      )}
    </button>
  );
}
