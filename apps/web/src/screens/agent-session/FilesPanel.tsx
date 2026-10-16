import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Button, Icon } from "../../components";
import { cx } from "../../lib/cx";
import { readStored, writeStored } from "../../lib/storage";
import { useDrawerWidth } from "./DrawerResize";
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

function Stats({ added, removed }: { added: number; removed: number }) {
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
}: {
  change: FileChange;
  index: number;
  total: number;
  path: string;
}) {
  const { icon, text } = TOOL_STATE[change.state];
  const applied = change.state !== "error" && change.state !== "denied";
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
      <DiffText diff={change.diff} label={`Change ${String(index + 1)} to ${path}`} />
    </div>
  );
}

function FileSection({
  file,
  name,
  viewed,
  stale,
  open,
  onToggleOpen,
  onToggleViewed,
}: {
  file: ChangedFile;
  name: string;
  viewed: boolean;
  stale: boolean;
  open: boolean;
  onToggleOpen: () => void;
  onToggleViewed: () => void;
}) {
  const slash = name.lastIndexOf("/");
  return (
    <section
      className={cx("as-files-file", viewed && "as-files-file-viewed")}
      data-file-path={file.path}
      aria-label={name}
    >
      <header className="as-files-file-head">
        <button
          type="button"
          className="as-files-file-toggle"
          aria-expanded={open}
          title={file.path}
          onClick={onToggleOpen}
        >
          <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
          <span
            className={cx("as-files-kind", file.created ? "as-files-kind-a" : "as-files-kind-m")}
            title={file.created ? "New file" : "Modified"}
          >
            {file.created ? "A" : "M"}
          </span>
          <span className="as-files-name">
            {slash >= 0 && <span className="ah-muted">{name.slice(0, slash + 1)}</span>}
            <b>{name.slice(slash + 1)}</b>
          </span>
        </button>
        <Stats added={file.added} removed={file.removed} />
        <label className={cx("as-files-viewed", viewed && "as-files-viewed-on")}>
          <input type="checkbox" checked={viewed} onChange={onToggleViewed} />
          {stale ? "Changed since viewed" : "Viewed"}
        </label>
      </header>
      {open && (
        <div className="as-files-file-body">
          {file.changes.map((change, index) => (
            <ChangeBlock
              key={change.tool.id}
              change={change}
              index={index}
              total={file.changes.length}
              path={name}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export interface FilesPanelProps {
  files: readonly ChangedFile[];
  sessionId: string;
  onClose: () => void;
}

/**
 * The files Claude changed in this session, for review beside the chat: a list of files with
 * the lines each added and removed, then every change to each as a diff, in order. Mark a file
 * Viewed to fold it away; a later change unfolds it again. The drawer can be resized or widened.
 */
export function FilesPanel({ files, sessionId, onClose }: FilesPanelProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const drawer = useDrawerWidth();
  const { reviewed, toggle } = useReviewed(sessionId);
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);

  const root = useMemo(() => commonDir(files.map((file) => file.path)), [files]);
  // One file alone keeps its folder in view: the root is then its parent's parent.
  const base =
    files.length === 1 ? root.slice(0, root.lastIndexOf("/", root.length - 2) + 1) : root;
  const nameOf = (path: string) => path.slice(base.length);
  const viewedCount = files.filter((file) => reviewed[file.path] === file.lastChangeId).length;
  const added = files.reduce((sum, file) => sum + file.added, 0);
  const removed = files.reduce((sum, file) => sum + file.removed, 0);

  const isOpen = (file: ChangedFile) =>
    closed[file.path] ?? reviewed[file.path] !== file.lastChangeId;
  const jump = (path: string) => {
    setClosed((before) => ({ ...before, [path]: false }));
    requestAnimationFrame(() => {
      const section = Array.from(
        list.current?.querySelectorAll<HTMLElement>("[data-file-path]") ?? [],
      ).find((element) => element.dataset.filePath === path);
      section?.scrollIntoView({ block: "start" });
      section?.querySelector<HTMLElement>("button")?.focus({ preventScroll: true });
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || event.shiftKey) return;
    event.preventDefault();
    event.stopPropagation();
    onClose();
  };

  return (
    // Esc closes it from anywhere inside.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <aside
      id={FILES_PANEL_ID}
      className="as-drawer as-files-panel"
      style={drawer.style}
      aria-labelledby={`${FILES_PANEL_ID}-title`}
      onKeyDown={onKeyDown}
    >
      <div {...drawer.handle} />
      <div className="as-activity-panel-head">
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
        <div className="as-files-body">
          <nav className="as-files-nav" aria-label="Files">
            <div className="as-files-progress ah-small">
              <span>
                {viewedCount} of {files.length} viewed
              </span>
              <span className="as-files-meter" aria-hidden="true">
                <span style={{ width: `${String((viewedCount / files.length) * 100)}%` }} />
              </span>
            </div>
            {root && (
              <p className="as-files-root ah-small ah-subtle" title={root}>
                {base || "/"}
              </p>
            )}
            <ul>
              {files.map((file) => {
                const viewed = reviewed[file.path] === file.lastChangeId;
                const name = nameOf(file.path);
                return (
                  <li key={file.path}>
                    <button
                      type="button"
                      className={cx("as-files-nav-item", viewed && "as-files-nav-viewed")}
                      title={file.path}
                      onClick={() => {
                        jump(file.path);
                      }}
                    >
                      <Icon
                        name={viewed ? "check" : file.created ? "file-plus" : "file-pen"}
                        size="sm"
                      />
                      <span className="as-files-nav-name">
                        {name.slice(name.lastIndexOf("/") + 1)}
                      </span>
                      <Stats added={file.added} removed={file.removed} />
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="as-files-list" ref={list}>
            {files.map((file) => {
              const mark = reviewed[file.path];
              const viewed = mark === file.lastChangeId;
              return (
                <FileSection
                  key={file.path}
                  file={file}
                  name={nameOf(file.path)}
                  viewed={viewed}
                  stale={mark !== undefined && !viewed}
                  open={isOpen(file)}
                  onToggleOpen={() => {
                    setClosed((before) => ({ ...before, [file.path]: isOpen(file) }));
                  }}
                  onToggleViewed={() => {
                    toggle(file);
                    // Marking viewed folds the file; unmarking opens it again.
                    setClosed((before) =>
                      Object.fromEntries(
                        Object.entries(before).filter(([path]) => path !== file.path),
                      ),
                    );
                  }}
                />
              );
            })}
          </div>
        </div>
      )}
    </aside>
  );
}
