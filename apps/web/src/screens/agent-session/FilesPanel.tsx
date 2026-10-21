import {
  Fragment,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import {
  Button,
  CopyButton,
  FitText,
  Icon,
  Markdown,
  SegmentedControl,
  StatusBadge,
  Tabs,
} from "../../components";
import { cx } from "../../lib/cx";
import { fmtInt } from "../../lib/format";
import { githubPullHref } from "../../lib/safeHref";
import { readStored, writeStored } from "../../lib/storage";
import { useDrawerWidth, useListWidth } from "./DrawerResize";
import { ReviewCommentsContext, ReviewDiff, type ReviewComments } from "./ReviewDiff";
import { canExpand, useExpandableNet, type DiffExpansion } from "./DiffExpand";
import { DiffText, TOOL_STATE } from "./ToolCallCard";
import {
  FILE_KINDS,
  KIND_TAB,
  fileKind,
  isMarkdown,
  isReviewable,
  isTestFile,
  type FileKind,
} from "./fileKind";
import { commonDir, type ChangedFile, type FileChange } from "./model";
import { useRepoCommitDiff } from "./queries";
import { writtenText } from "./netDiff";
import { isDiscarded, repoState, type FileCommit, type RepoChanges } from "./repoChanges";
import { shortSha } from "../feature-detail/acEvidence";

/** The drawer's tabs: one per kind of file, then the files that ended as they began. */
type FilesTab = FileKind | "discarded";

const DISCARDED_TAB = {
  label: "Discarded",
  icon: "file-x",
  hint: "touched, then put back: none of it goes in the pull request",
} as const;

/** A file you review: code that goes in the pull request (a discarded file does not). */
const needsReview = (file: ChangedFile) => isReviewable(file.path) && !isDiscarded(file);

/** What each tab says about its files, under the tabs. */
const KIND_NOTE: Record<FilesTab, string> = {
  discarded:
    "Files this session created or changed, then deleted or put back: they end as they are on the base, so none of it goes in the pull request. Kept here so you can see what was tried.",
  code: "The files of your repo this session changed: what goes in the pull request.",
  plan: "The plans Claude wrote for this work. They stay on this machine.",
  feature:
    "What the workflow keeps on the feature in the brain: its spec and quality reviews, the spec, plan, research and evals. Not part of your pull request.",
  learning:
    "Notes for the brain: what Claude proposes to remember, and the brain's own notes it changed.",
  scratch:
    "Notes Claude wrote for itself (temporary folders, its own settings). Nothing to review.",
};

/** The DOM id of the files drawer, for the header button's `aria-controls`. */
export const FILES_PANEL_ID = "as-files-panel";

/** How the code tab splits its files: all together, the code apart, or the tests apart. Kept in
 * this browser for every session. */
type CodeSplit = "all" | "source" | "tests";
export const CODE_SPLIT_KEY = "ah.chat.codeSplit";
const readCodeSplit = (): CodeSplit => {
  const value = readStored(CODE_SPLIT_KEY);
  return value === "source" || value === "tests" ? value : "all";
};

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
      <span className="as-files-add">+{fmtInt(added)}</span>
      <span className="as-files-del">−{fmtInt(removed)}</span>
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
          path={filePath}
        />
      )}
    </div>
  );
}

/** A file's final diff: what all its changes add up to, open to review comments (change 0). */
function NetBlock({
  file,
  path,
  sessionId,
}: {
  file: ChangedFile;
  path: string;
  sessionId: string;
}) {
  const net = file.net;
  const repo = file.repo;
  if (!net) {
    if (repo?.binary) return <p className="ah-small ah-muted">A binary file: no diff to show.</p>;
    if (repo?.tooBig) return <p className="ah-small ah-muted">Too big a diff to show here.</p>;
    return null;
  }
  const label = `Final diff of ${path}`;
  if (net.added === 0 && net.removed === 0) {
    return (
      <p className="ah-small ah-muted">
        {repo?.unchanged
          ? `The file ends as it is on ${repo.base}: none of it goes in the pull request.`
          : repo
            ? "Renamed, its content unchanged."
            : "The changes cancel out: the file ends as it began."}
      </p>
    );
  }
  // Git's diff against the base opens wider around its hunks, as on GitHub.
  return canExpand(file) ? (
    <ExpandableNetDiff sessionId={sessionId} file={file} label={label} />
  ) : (
    <NetDiff file={file} diff={net.diff} label={label} />
  );
}

function ExpandableNetDiff({
  sessionId,
  file,
  label,
}: {
  sessionId: string;
  file: ChangedFile;
  label: string;
}) {
  const shown = useExpandableNet(sessionId, file);
  if (shown.diff === null) return null;
  return <NetDiff file={file} diff={shown.diff} label={label} expansion={shown.expansion} />;
}

/** The final diff, open to review comments when the drawer takes them. */
function NetDiff({
  file,
  diff,
  label,
  expansion,
}: {
  file: ChangedFile;
  diff: string;
  label: string;
  expansion?: DiffExpansion | undefined;
}) {
  const comments = useContext(ReviewCommentsContext);
  const numbered = file.net?.numbered ?? false;
  const threads =
    comments?.threads.filter(
      (thread) => thread.anchor.path === file.path && thread.anchor.change === 0,
    ) ?? [];
  return (
    <div className="as-files-change">
      {comments ? (
        <ReviewDiff
          diff={diff}
          label={label}
          numbered={numbered}
          path={file.path}
          change={0}
          threads={threads}
          resolved={comments.resolved}
          onComment={comments.onComment}
          expansion={expansion}
        />
      ) : (
        <DiffText
          diff={diff}
          label={label}
          numbered={numbered}
          path={file.path}
          expansion={expansion}
        />
      )}
    </div>
  );
}

type DetailView = "preview" | "final" | "changes" | "commits";

const isApplied = (change: FileChange) => change.state !== "error" && change.state !== "denied";

/** The markdown a file ends with, when the session wrote it whole; null otherwise. */
function markdownText(file: ChangedFile): string | null {
  if (!isMarkdown(file.path)) return null;
  return writtenText(
    file.changes.filter(isApplied).map((change) => ({
      name: change.tool.name,
      input: change.tool.input,
      diff: change.diff,
      numbered: change.numbered,
    })),
  );
}

/** A leading `---` YAML block, apart from the body it heads. */
function splitFrontmatter(text: string): { frontmatter: string | null; body: string } {
  const match = /^---\n([\s\S]*?)\n---\n?/.exec(text);
  return match
    ? { frontmatter: match[1] ?? "", body: text.slice(match[0].length) }
    : { frontmatter: null, body: text };
}

/** A markdown file as it reads: its frontmatter as fields, its body rendered. */
function PreviewBlock({ text }: { text: string }) {
  const { frontmatter, body } = splitFrontmatter(text);
  return (
    <div className="as-files-preview">
      {frontmatter !== null && (
        <pre className="as-files-frontmatter ah-mono ah-small" aria-label="Frontmatter">
          {frontmatter}
        </pre>
      )}
      <Markdown source={body} />
    </div>
  );
}

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
/** Below this width the file list wraps its names and folders instead of cutting them (px). */
export const LIST_COMPACT = 360;

/** How wide `element` is, followed as it resizes (0 without a ResizeObserver: the narrow,
 * one-pane layout). */
function useWidth(element: HTMLElement | null): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element || typeof ResizeObserver !== "function") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [element]);
  return width;
}

/** A folder on one narrow line: its own name first, then where it sits, dimmed and cut at its
 * end; the whole path on hover. */
function FolderLine({ folder }: { folder: string }) {
  const at = folder.lastIndexOf("/");
  return (
    <span className="as-files-folder-line" title={folder}>
      <span className="as-files-folder-leaf as-files-cut">{folder.slice(at + 1)}</span>
      {at > 0 && <span className="as-files-folder-parent as-files-cut">{folder.slice(0, at)}</span>}
    </span>
  );
}

/** A path or name that wraps after its separators (`/ _ - .`) instead of being cut: in the
 * review the name is the content, so all of it shows. */
function Breakable({ text }: { text: string }) {
  const parts = text.split(/(?<=[/_.-])/);
  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {part}
          {index < parts.length - 1 && <wbr />}
        </Fragment>
      ))}
    </>
  );
}

/** How much of a file name stays whole: its extension and the few characters before it. */
const nameTail = (name: string) => {
  const dot = name.lastIndexOf(".");
  return Math.min(name.length, (dot > 0 ? name.length - dot : 0) + 6);
};
/** How much of a folder stays whole: its last name (at most 28 characters). */
const folderTail = (folder: string) =>
  Math.min(folder.length, Math.min(28, folder.length - folder.lastIndexOf("/")));

const WORKTREE = /^(.*\/)?([^/]+)\/\.claude\/worktrees\/([^/]+)(\/.*)?$/;
const HOME = /^(?:\/Users\/[^/]+|\/home\/[^/]+)(?=\/|$)/;

/** The folder every listed file is under, on one line: a worktree as its repo and its name (the
 * branch's folder, in bold), else the session's folder in bold when the root is inside it, else
 * the path with the home folder as `~`. The full path on hover and one click away. */
function RootLine({
  base,
  workdirLabel,
  compact = false,
}: {
  base: string;
  workdirLabel: string | undefined;
  compact?: boolean;
}) {
  const path = base.slice(0, -1);
  if (compact) {
    // Narrow: only the folder's own name (the branch's, in a worktree), cut at its end.
    const worktree = WORKTREE.exec(path);
    const lead = worktree?.[3] ?? path.slice(path.lastIndexOf("/") + 1);
    return (
      <div className="as-files-root ah-small" title={path}>
        <Icon name={worktree ? "git-branch" : "folder"} size="sm" />
        <span className="as-files-root-lead as-files-cut">{lead}</span>
        <CopyButton text={path} label="Copy folder path" className="as-files-copy" compact />
      </div>
    );
  }
  const worktree = WORKTREE.exec(path);
  let body;
  if (worktree) {
    const [, , repo = "", name = "", rest = ""] = worktree;
    body = (
      <>
        <span className="as-files-root-repo">{repo}</span>
        <Icon name="git-branch" size="sm" />
        <FitText text={name} tail={Math.min(name.length, 12)} className="as-files-root-lead" />
        {rest && <FitText text={rest} tail={folderTail(rest)} className="as-files-root-rest" />}
      </>
    );
  } else {
    const marker = workdirLabel ? `/${workdirLabel}/` : null;
    const at = marker ? `${path}/`.indexOf(marker) : -1;
    if (marker && workdirLabel && at >= 0) {
      const rest = path.slice(at + marker.length - 1);
      body = (
        <>
          <FitText text={workdirLabel} tail={12} className="as-files-root-lead" />
          {rest && <FitText text={rest} tail={folderTail(rest)} className="as-files-root-rest" />}
        </>
      );
    } else {
      const shown = path.replace(HOME, "~");
      body = <FitText text={shown} tail={folderTail(shown)} className="as-files-root-rest" />;
    }
  }
  return (
    <div className="as-files-root ah-small" title={path}>
      <span className="ah-subtle">In</span>
      {body}
      <CopyButton text={path} label="Copy folder path" className="as-files-copy" compact />
    </div>
  );
}

const STATUS_BADGE = {
  added: { letter: "A", title: "New file", tone: "a" },
  modified: { letter: "M", title: "Modified", tone: "m" },
  deleted: { letter: "D", title: "Deleted", tone: "d" },
  renamed: { letter: "R", title: "Renamed", tone: "m" },
} as const;

/** A file's status letter: A (new), M (modified), D (deleted) or R (renamed); without git's
 * status, A or M from whether the session wrote it whole. */
export function KindBadge({
  created,
  status,
}: {
  created: boolean;
  status?: keyof typeof STATUS_BADGE | undefined;
}) {
  const badge = STATUS_BADGE[status ?? (created ? "added" : "modified")];
  return (
    <span className={cx("as-files-kind", `as-files-kind-${badge.tone}`)} title={badge.title}>
      {badge.letter}
    </span>
  );
}

function commitWhen(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime())
    ? iso
    : when.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** What one commit changed in the file, read from git when its row opens. */
function CommitDiff({
  sessionId,
  path,
  oldPath,
  commit,
}: {
  sessionId: string;
  path: string;
  oldPath: string | null;
  commit: FileCommit;
}) {
  const query = useRepoCommitDiff(sessionId, { path, oldPath, sha: commit.sha });
  if (query.isPending) return <p className="ah-small ah-muted">Reading the commit…</p>;
  if (query.isError) return <p className="ah-small ah-muted">Git could not read this commit.</p>;
  const { diff, binary } = query.data;
  if (binary) return <p className="ah-small ah-muted">A binary file: no diff to show.</p>;
  if (diff === null || diff === undefined)
    return <p className="ah-small ah-muted">Too big a diff to show here.</p>;
  if (diff === "")
    return <p className="ah-small ah-muted">This commit changed the file under another name.</p>;
  return (
    <DiffText
      diff={diff}
      label={`Commit ${shortSha(commit.sha)} to ${path}`}
      numbered
      path={path}
    />
  );
}

/** A file's history on its branch: the commits that touched it, newest first, each opening on
 * what it changed in the file, and its changes not committed yet. */
function CommitsBlock({
  sessionId,
  path,
  oldPath,
  commits,
  uncommitted,
}: {
  sessionId: string;
  path: string;
  oldPath: string | null;
  commits: FileCommit[];
  uncommitted: boolean;
}) {
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (sha: string) => {
    setOpen((before) => {
      const next = new Set(before);
      if (next.has(sha)) next.delete(sha);
      else next.add(sha);
      return next;
    });
  };
  return (
    <ol className="as-files-commits" aria-label="Commits that changed this file">
      {uncommitted && (
        <li className="as-files-commit">
          <div className="as-files-commit-head">
            <Icon name="pencil" size="sm" />
            <span className="as-files-commit-subject">Uncommitted changes</span>
            <span className="ah-small ah-muted">in the working tree</span>
          </div>
        </li>
      )}
      {commits.map((commit) => {
        const expanded = open.has(commit.sha);
        return (
          <li key={commit.sha} className="as-files-commit">
            <button
              type="button"
              className="as-files-commit-head as-files-commit-open"
              aria-expanded={expanded}
              title={expanded ? "Hide what this commit changed" : "Show what this commit changed"}
              onClick={() => {
                toggle(commit.sha);
              }}
            >
              <Icon name={expanded ? "chevron-down" : "chevron-right"} size="sm" />
              <code className="as-files-commit-sha ah-mono ah-small" title={commit.sha}>
                {shortSha(commit.sha)}
              </code>
              <span className="as-files-commit-subject">{commit.subject}</span>
              <Stats added={commit.added} removed={commit.removed} />
              <span className="as-files-commit-meta ah-small ah-muted">
                {commit.author} · {commitWhen(commit.authoredAt)}
              </span>
            </button>
            {expanded && (
              <div className="as-files-commit-diff">
                <CommitDiff sessionId={sessionId} path={path} oldPath={oldPath} commit={commit} />
              </div>
            )}
          </li>
        );
      })}
    </ol>
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
  workdirLabel,
}: {
  files: readonly ChangedFile[];
  nameOf: (path: string) => string;
  base: string;
  workdirLabel: string | undefined;
  selected: string | null;
  review: ReviewState;
  onSelect: (path: string) => void;
}) {
  // Narrow, every line stays one line and is cut at its end, never over its neighbour: a folder
  // leads with its own name, a file drops its line counts (they are on the open file).
  const [nav, setNav] = useState<HTMLElement | null>(null);
  const navWidth = useWidth(nav);
  const compact = navWidth > 0 && navWidth < LIST_COMPACT;
  // Only the code is reviewed: Claude's own files carry no viewed mark and no progress.
  const reviewable = files.filter(needsReview);
  const viewedCount = reviewable.filter(
    (file) => review.reviewed[file.path] === file.lastChangeId,
  ).length;
  return (
    <nav
      ref={setNav}
      className={cx("as-files-nav", compact && "as-files-nav-compact")}
      aria-label="Files"
    >
      {reviewable.length > 0 && (
        <div className="as-files-progress ah-small">
          <span>
            {viewedCount} of {reviewable.length} viewed
          </span>
          <span className="as-files-meter" aria-hidden="true">
            <span style={{ width: `${String((viewedCount / reviewable.length) * 100)}%` }} />
          </span>
        </div>
      )}
      {base && <RootLine base={base} workdirLabel={workdirLabel} compact={compact} />}
      {byFolder(files, nameOf).map(([folder, inFolder]) => (
        <div key={folder} className="as-files-group">
          {folder && (
            <div className="as-files-folder ah-small">
              <Icon name="folder" size="sm" />
              {compact ? (
                <FolderLine folder={folder.slice(0, -1)} />
              ) : (
                <FitText text={folder.slice(0, -1)} tail={folderTail(folder.slice(0, -1))} />
              )}
            </div>
          )}
          <ul aria-label={folder ? `Folder ${folder.slice(0, -1)}` : undefined}>
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
                    <KindBadge created={file.created} status={file.repo?.status} />
                    {compact ? (
                      <>
                        <span className="as-files-nav-name as-files-cut">
                          {name.slice(name.lastIndexOf("/") + 1)}
                        </span>
                        <OpenThreads path={file.path} />
                      </>
                    ) : (
                      <>
                        <FitText
                          text={name.slice(name.lastIndexOf("/") + 1)}
                          tail={nameTail(name.slice(name.lastIndexOf("/") + 1))}
                          className="as-files-nav-name"
                        />
                        <OpenThreads path={file.path} />
                        <Stats added={file.added} removed={file.removed} />
                      </>
                    )}
                  </button>
                  {needsReview(file) && (
                    <ViewedToggle
                      compact
                      viewed={viewed}
                      stale={mark !== undefined && !viewed}
                      onToggle={() => {
                        review.toggle(file);
                      }}
                    />
                  )}
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
  sessionId,
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
  /** The session, whose repositories a commit's diff is read from. */
  sessionId: string;
}) {
  const mark = review.reviewed[file.path];
  const viewed = mark === file.lastChangeId;
  const slash = name.lastIndexOf("/");
  const body = useRef<HTMLDivElement>(null);
  const section = useRef<HTMLElement>(null);
  const takesFocus = onBack !== null;
  // Markdown reads rendered first, other files as their final result. The drawer keeps one
  // choice for markdown and one for code, so stepping from a diff to a note still renders it.
  const text = markdownText(file);
  const [proseView, setProseView] = useState<DetailView>("preview");
  const [codeView, setCodeView] = useState<DetailView>("final");
  const view = text !== null ? proseView : codeView;
  const setView = text !== null ? setProseView : setCodeView;
  const repo = file.repo;
  const history = repo ? repo.commits.length + (repo.uncommitted ? 1 : 0) : 0;
  const hasChanges = file.changes.length > 0;
  // A file git read always has its final result (a note when there is no diff to show).
  const hasNet = file.net !== null || repo !== undefined;
  const views = [
    ...(text !== null ? [{ id: "preview", label: "Preview" }] : []),
    ...(hasNet ? [{ id: "final", label: "Final result" }] : []),
    ...(hasChanges && (text !== null || hasNet)
      ? [{ id: "changes", label: `Each change (${String(file.changes.length)})` }]
      : []),
    ...(history > 0 ? [{ id: "commits", label: `Commits (${String(history)})` }] : []),
  ];
  const offered = (id: DetailView) => views.some((option) => option.id === id);
  const current: DetailView = offered(view)
    ? view
    : text !== null
      ? "preview"
      : hasNet
        ? "final"
        : "changes";
  const showPreview = current === "preview" && text !== null;
  const showNet = current === "final";
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
          {slash >= 0 && (
            <span className="as-files-detail-dir ah-small">
              <Breakable text={name.slice(0, slash + 1)} />
            </span>
          )}
          <span className="as-files-detail-file">
            <KindBadge created={file.created} status={file.repo?.status} />
            <b className="as-files-name">
              <Breakable text={name.slice(slash + 1)} />
            </b>
            <Stats added={file.added} removed={file.removed} />
          </span>
        </div>
        <CopyButton text={file.path} label="Copy file path" className="as-files-copy" />
        {needsReview(file) && (
          <ViewedToggle
            viewed={viewed}
            stale={mark !== undefined && !viewed}
            onToggle={() => {
              review.toggle(file);
            }}
          />
        )}
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
        {views.length > 1 ? (
          <div className="as-files-summary ah-row">
            <SegmentedControl
              label="Show"
              value={current}
              onChange={(id) => {
                setView(id as DetailView);
              }}
              options={views}
            />
            <span className="ah-small ah-muted">
              {showPreview
                ? "The file as it ends, rendered"
                : showNet
                  ? repo
                    ? `Against ${repo.base}: every commit and uncommitted change, as the pull request shows it`
                    : `All ${String(file.changes.length)} changes in this session, as one diff`
                  : current === "commits"
                    ? "Newest first"
                    : "Oldest first, as Claude made them in this session"}
            </span>
          </div>
        ) : (
          <p className="as-files-summary ah-small ah-muted">
            {repo && !hasChanges
              ? `Against ${repo.base}, as the pull request shows it`
              : file.changes.length === 1
                ? "1 change in this session"
                : `${String(file.changes.length)} changes in this session, oldest first`}
          </p>
        )}
        {showPreview && <PreviewBlock text={text} />}
        {showNet && <NetBlock file={file} path={name} sessionId={sessionId} />}
        {current === "commits" && repo && (
          <CommitsBlock
            sessionId={sessionId}
            path={file.path}
            oldPath={repo.oldPath}
            commits={repo.commits}
            uncommitted={repo.uncommitted}
          />
        )}
        {current === "changes" &&
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
  /** The session's folder (its worktree or branch), shown in bold where the files' root has it. */
  workdirLabel?: string | undefined;
  /** The branch and base git compared the code with (`repoSummary`), when it read the repos. */
  repoNote?: string | null | undefined;
  /** The repositories git read for the review: each shows its branch, base, pull request and
   * where it stands against it. */
  repos?: readonly RepoChanges[] | undefined;
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
  workdirLabel,
  repoNote,
  repos,
}: FilesPanelProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [panel, setPanel] = useState<HTMLElement | null>(null);
  const panelWidth = useWidth(panel);
  const wide = panelWidth >= SPLIT_MIN;
  const list = useListWidth(panelWidth);
  const drawer = useDrawerWidth();
  const own = useReviewed(sessionId);
  const review = shared ?? own;
  const [picked, setPicked] = useState<string | null>(initialPath);
  const [tab, setTab] = useState<FilesTab | null>(null);
  const [split, setSplit] = useState<CodeSplit>(readCodeSplit);
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

  // One tab per kind of file the session changed: the code first, Claude's scratch last.
  // The files that ended as they began have a tab of their own, after the code.
  const kinds = useMemo(() => {
    const kept = files.filter((file) => !isDiscarded(file));
    const groups: { kind: FilesTab; files: ChangedFile[] }[] = FILE_KINDS.map((kind) => ({
      kind,
      files: kept.filter((file) => fileKind(file.path) === kind),
    }));
    groups.splice(1, 0, { kind: "discarded", files: files.filter(isDiscarded) });
    return groups.filter((group) => group.files.length > 0);
  }, [files]);
  // A file picked (from a card in the conversation, too) shows in its own tab.
  const pickedFile = picked === null ? undefined : files.find((file) => file.path === picked);
  const pickedKind: FilesTab | null = pickedFile
    ? isDiscarded(pickedFile)
      ? "discarded"
      : fileKind(pickedFile.path)
    : null;
  const kind = kinds.find((group) => group.kind === (pickedKind ?? tab)) ?? kinds[0];
  // The code tab can show its tests apart: only when it has both tests and other code.
  const testCount = kind?.kind === "code" ? kind.files.filter((f) => isTestFile(f.path)).length : 0;
  const sourceCount = kind?.kind === "code" ? kind.files.length - testCount : 0;
  const canSplit = testCount > 0 && sourceCount > 0;
  // A picked file (a card in the conversation) shows even when the split hides its side.
  const pickedSide: CodeSplit | null =
    canSplit && picked !== null && kind?.files.some((file) => file.path === picked)
      ? isTestFile(picked)
        ? "tests"
        : "source"
      : null;
  const side: CodeSplit = !canSplit
    ? "all"
    : split !== "all" && pickedSide !== null && pickedSide !== split
      ? pickedSide
      : split;
  const shown = useMemo(() => {
    const all = kind?.files ?? [];
    if (side === "all") return all;
    return all.filter((file) => isTestFile(file.path) === (side === "tests"));
  }, [kind, side]);

  const root = useMemo(() => commonDir(shown.map((file) => file.path)), [shown]);
  // One file alone keeps its folder in view: the root is then its parent's parent.
  const base =
    shown.length === 1 ? root.slice(0, root.lastIndexOf("/", root.length - 2) + 1) : root;
  const nameOf = (path: string) => path.slice(base.length);
  const totals = codeTotals(files);

  // Wide, a file is always open (the first by default); narrow, only the one you picked.
  const known = shown.some((file) => file.path === picked) ? picked : null;
  const selected = known ?? (wide ? (shown[0]?.path ?? null) : null);
  const position = shown.findIndex((file) => file.path === selected);
  const open = position >= 0 ? shown[position] : undefined;

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
          {totals.files > 0 ? (
            <>
              {plural(totals.files, "code file")} ·{" "}
              <Stats added={totals.added} removed={totals.removed} />
            </>
          ) : (
            "No code changes"
          )}
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
          {kinds.length > 1 && kind && (
            <div className="as-files-tabs">
              <Tabs
                label="Kind of file"
                value={kind.kind}
                onChange={(id) => {
                  setTab(id as FilesTab);
                  setPicked(null);
                }}
                tabs={kinds.map((group) => ({
                  id: group.kind,
                  label: tabOf(group.kind).label,
                  icon: tabOf(group.kind).icon,
                  count: group.files.length,
                }))}
              />
              <p className="ah-small ah-muted">
                {kind.kind === "code" && repoNote
                  ? `What the pull request has, whoever changed it (${repoNote}).`
                  : KIND_NOTE[kind.kind]}
              </p>
            </div>
          )}
          {(kind?.kind ?? "code") === "code" && repos && repos.length > 0 && (
            <RepoList repos={repos} />
          )}
          {canSplit && (
            <div className="as-files-codesplit ah-small">
              <SegmentedControl
                label="Show the code and its tests"
                value={side}
                onChange={(id) => {
                  const next = id as CodeSplit;
                  setSplit(next);
                  writeStored(CODE_SPLIT_KEY, next);
                  setPicked(null);
                }}
                options={[
                  {
                    id: "all",
                    label: `All ${String(sourceCount + testCount)}`,
                    title: "Code and tests together",
                  },
                  {
                    id: "source",
                    label: `Code ${String(sourceCount)}`,
                    title: "The code, without its tests",
                  },
                  {
                    id: "tests",
                    label: `Tests ${String(testCount)}`,
                    title: "Only the test files",
                  },
                ]}
              />
            </div>
          )}
          <div
            className={cx("as-files-body", wide && "as-files-split")}
            style={wide ? list.style : undefined}
          >
            {(wide || !open) && (
              <FileList
                files={shown}
                nameOf={nameOf}
                base={base}
                workdirLabel={workdirLabel}
                selected={selected}
                review={review}
                onSelect={setPicked}
              />
            )}
            {wide && <div {...list.handle} />}
            {open && (
              <FileDetail
                file={open}
                name={nameOf(open.path)}
                position={position}
                total={shown.length}
                review={review}
                onBack={wide ? null : backToList}
                focusRequest={focusFile ? pickNonce : null}
                sessionId={sessionId}
                onStep={(by) => {
                  setPicked(shown[position + by]?.path ?? selected);
                }}
              />
            )}
          </div>
        </ReviewCommentsContext.Provider>
      )}
    </aside>
  );
}

const REPO_TONE = { done: "done", waiting: "waiting", muted: "ended" } as const;

/** One line per repository of the review: its folder, branch and base, its pull request (a
 * link) and where it stands against it. */
function RepoList({ repos }: { repos: readonly RepoChanges[] }) {
  return (
    <ul className="as-files-repos ah-small" aria-label="Repositories">
      {repos.map((repo) => {
        const state = repoState(repo);
        const pull = repo.pull_request;
        const href = pull ? githubPullHref(pull.url) : null;
        const count = repo.commits.length;
        return (
          <li key={repo.root} className="as-files-repo">
            <Icon name="git-branch" size="sm" />
            <span className="as-files-repo-name" title={repo.root}>
              <b>{repo.branch ?? repo.label}</b>
              {repo.base && <span className="ah-subtle"> → {repo.base}</span>}
              <span className="ah-subtle">
                {" "}
                · {String(count)}
                {repo.truncated ? "+" : ""} {count === 1 ? "commit" : "commits"}
              </span>
            </span>
            {pull &&
              (href ? (
                <a href={href} target="_blank" rel="noopener noreferrer">
                  PR #{pull.number} <span className="ah-sr">(opens in a new tab)</span>
                </a>
              ) : (
                <span>PR #{pull.number}</span>
              ))}
            <StatusBadge status={REPO_TONE[state.tone]} label={state.text} quiet />
          </li>
        );
      })}
    </ul>
  );
}

/** What the review totals: the code that goes in the pull request (git's files and the repo
 * files Claude changed), never Claude's plans, feature records, brain notes or scratch. */
const tabOf = (tab: FilesTab) => (tab === "discarded" ? DISCARDED_TAB : KIND_TAB[tab]);

export function codeTotals(files: readonly ChangedFile[]) {
  const code = files.filter(needsReview);
  return {
    files: code.length,
    added: code.reduce((sum, file) => sum + file.added, 0),
    removed: code.reduce((sum, file) => sum + file.removed, 0),
  };
}

const plural = (n: number, word: string) => `${String(n)} ${word}${n === 1 ? "" : "s"}`;

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
  // Only the code counts and waits on you: Claude's own files are in their tabs, not the total.
  const { files: codeFiles, added, removed } = codeTotals(files);
  const due = files.filter((file) => needsReview(file) && !isViewed(review, file)).length;
  const count = codeFiles > 0 ? plural(codeFiles, "file") : "No code";
  const left =
    due === 0
      ? null
      : due >= codeFiles
        ? `${fmtInt(due)} to review`
        : `${fmtInt(due)} of ${fmtInt(codeFiles)} to review`;
  return (
    <button
      type="button"
      className={cx(
        "ah-btn ah-btn-sm as-review-btn",
        due === 0 && "ah-btn-ghost",
        open && "as-review-open",
      )}
      aria-expanded={open}
      aria-controls={open ? FILES_PANEL_ID : undefined}
      aria-label={`Review changes: ${count}, ${String(added)} lines added, ${String(removed)} removed, ${due > 0 ? `${String(due)} to review` : "all reviewed"}`}
      title={open ? "Close the changed files" : "Open the changed files"}
      onClick={onToggle}
    >
      <Icon name="git-compare" size="sm" />
      Review changes
      {codeFiles > 0 && <Stats added={added} removed={removed} />}
      {codeFiles === 0 ? (
        <span className="ah-subtle">· No code changes</span>
      ) : left ? (
        <span>
          <span className="ah-subtle">· </span>
          <span className="as-review-due">{left}</span>
        </span>
      ) : (
        <span className="ah-row" style={{ gap: 4 }}>
          <span className="ah-subtle">· {count}</span>
          <Icon name="circle-check" size="sm" className="as-files-chip-done" />
        </span>
      )}
    </button>
  );
}
