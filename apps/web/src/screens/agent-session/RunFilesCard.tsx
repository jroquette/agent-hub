import { Icon } from "../../components";
import { cx } from "../../lib/cx";
import { KindBadge, Stats } from "./FilesPanel";
import type { ChangedFile } from "./model";

/** A file one run changed: the session's file (status, review mark) and this run's lines. */
export interface RunFile {
  file: ChangedFile;
  added: number;
  removed: number;
}

/** Rows shown before "+N more". */
export const RUN_FILES_SHOWN = 4;

/** The files a run's calls changed (its subagents' too), with the lines of the applied changes. */
export function runFilesOf(files: readonly ChangedFile[], toolIds: ReadonlySet<string>): RunFile[] {
  return files.flatMap((file) => {
    const changes = file.changes.filter((change) => toolIds.has(change.tool.id));
    if (changes.length === 0) return [];
    const applied = changes.filter((c) => c.state !== "error" && c.state !== "denied");
    return [
      {
        file,
        added: applied.reduce((sum, change) => sum + change.added, 0),
        removed: applied.reduce((sum, change) => sum + change.removed, 0),
      },
    ];
  });
}

/** Equal when the same files moved by the same lines: a delta elsewhere keeps the run's memo. */
export function sameRunFiles(a: readonly RunFile[], b: readonly RunFile[]): boolean {
  return (
    a.length === b.length &&
    a.every((one, i) => {
      const other = b[i];
      return (
        other?.file.path === one.file.path &&
        other.file.lastChangeId === one.file.lastChangeId &&
        other.added === one.added &&
        other.removed === one.removed
      );
    })
  );
}

export interface RunFilesCardProps {
  files: readonly RunFile[];
  /** The change each file was marked viewed at, by path. */
  reviewed: Readonly<Record<string, string>>;
  /** Opens the Changed files drawer on a file, or on the list (null). */
  onOpenFile: (path: string | null) => void;
}

const nameOf = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/**
 * What a turn did to the files, in the conversation: "Edited 3 files +40 −12" and a row per file
 * (status, name, lines, viewed), like Claude's own apps. A row opens that file for review in the
 * Changed files drawer; the full trace (commands, thoughts) stays in Activity.
 */
export function RunFilesCard({ files, reviewed, onOpenFile }: RunFilesCardProps) {
  const added = files.reduce((sum, one) => sum + one.added, 0);
  const removed = files.reduce((sum, one) => sum + one.removed, 0);
  const created = files.every((one) => one.file.created);
  const shown = files.slice(0, RUN_FILES_SHOWN);
  const more = files.length - shown.length;
  const verb = created ? "Created" : "Edited";
  return (
    <section className="as-run-files" aria-label="Files edited in this turn">
      <header className="as-run-files-head">
        <Icon name="git-compare" size="sm" />
        <span>
          {verb} {files.length} {files.length === 1 ? "file" : "files"}
        </span>
        <Stats added={added} removed={removed} />
        <span className="ah-grow" />
        <button
          type="button"
          className="as-run-files-review"
          onClick={() => {
            onOpenFile(null);
          }}
        >
          Review
          <Icon name="chevron-right" size="sm" />
        </button>
      </header>
      <ul>
        {shown.map(({ file, added: lineAdds, removed: lineDels }) => {
          const viewed = reviewed[file.path] === file.lastChangeId;
          return (
            <li key={file.path}>
              <button
                type="button"
                className={cx("as-run-files-row", viewed && "as-run-files-row-viewed")}
                data-file-path={file.path}
                title={file.path}
                aria-label={`Open ${file.path}, ${file.created ? "new" : "modified"}, +${String(lineAdds)} −${String(lineDels)}, ${viewed ? "viewed" : "not viewed"}`}
                onClick={() => {
                  onOpenFile(file.path);
                }}
              >
                <KindBadge created={file.created} />
                <span className="as-run-files-name">{nameOf(file.path)}</span>
                <span className="as-run-files-dir">
                  {file.path.slice(0, file.path.lastIndexOf("/"))}
                </span>
                <Stats added={lineAdds} removed={lineDels} />
                {viewed ? (
                  <Icon name="check" size="sm" className="as-run-files-check" />
                ) : (
                  <span className="as-run-files-dot" aria-hidden="true" />
                )}
              </button>
            </li>
          );
        })}
      </ul>
      {more > 0 && (
        <button
          type="button"
          className="as-run-files-more"
          onClick={() => {
            onOpenFile(null);
          }}
        >
          +{more} more {more === 1 ? "file" : "files"}
        </button>
      )}
    </section>
  );
}
