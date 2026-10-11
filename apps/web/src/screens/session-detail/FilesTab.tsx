import { useState } from "react";

import type { components } from "../../api/schema";
import {
  AppLink,
  EmptyState,
  FileTree,
  ProblemError,
  Skeleton,
  type FileNode,
  type FileStatus,
} from "../../components";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useSessionFiles } from "./queries";
import type { ApiEvent } from "./timeline";
import { DIFF_NOT_STORED } from "./TraceRow";

type FileChange = components["schemas"]["SessionFileChange"];

/** The strongest operation on a path: created, then edited (or written), else read. */
export function fileStatus(file: Pick<FileChange, "ops">): FileStatus {
  if (file.ops.includes("created")) return "created";
  if (file.ops.includes("edited") || file.ops.includes("written")) return "edited";
  return "read";
}

function treeOf(files: FileChange[]): FileNode[] {
  const repos = new Map<string, FileChange[]>();
  for (const file of files) {
    const repo = file.repo ?? "outside a repo";
    repos.set(repo, [...(repos.get(repo) ?? []), file]);
  }
  return [...repos.entries()].map(([repo, list]) => ({
    name: repo,
    repo: true,
    path: `repo:${repo}`,
    children: list.map((file) => {
      const status = fileStatus(file);
      return {
        name: file.path,
        path: file.path,
        status,
        plus: status === "read" ? undefined : file.added,
        minus: status === "read" ? undefined : file.removed,
      };
    }),
  }));
}

export interface FilesTabProps {
  sessionId: string;
  events: ApiEvent[];
  onJump: (eventId: string) => void;
}

/** Files and diffs: paths with op badges and +/−; no diff content is stored (AC-200.48). */
export function FilesTab({ sessionId, events, onJump }: FilesTabProps) {
  const { tz } = usePreferences();
  const files = useSessionFiles(sessionId, true);
  const [chosen, setChosen] = useState<string | null>(null);
  if (files.isPending) return <Skeleton lines={6} height={16} />;
  if (files.error) {
    return (
      <ProblemError
        title="Could not load the files"
        detail={files.error.detail}
        status={files.error.status}
        onRetry={() => {
          void files.refetch();
        }}
      />
    );
  }
  const list = files.data.items;
  if (list.length === 0) {
    return (
      <EmptyState icon="file-text" title="No files touched">
        This session has not read or changed a file yet.
      </EmptyState>
    );
  }
  const counts = { edited: 0, created: 0, read: 0, deleted: 0 };
  for (const file of list) counts[fileStatus(file)] += 1;
  const selected = list.find((file) => file.path === chosen) ?? list[0];
  const byId = new Map(events.map((event) => [event.event_id, event]));
  const status = selected ? fileStatus(selected) : "read";
  return (
    <div className="sd-files">
      <div className="ah-card" style={{ padding: 8 }}>
        <div className="ah-row ah-small ah-subtle" style={{ padding: "4px 8px 8px" }}>
          {list.length} {list.length === 1 ? "file" : "files"} · {counts.edited} edited ·{" "}
          {counts.created} created · {counts.read} read only
        </div>
        <FileTree
          nodes={treeOf(list)}
          selected={selected?.path}
          onSelect={setChosen}
          label="Files touched"
        />
      </div>
      {selected && (
        <div className="ah-stack" style={{ gap: 12 }}>
          <div className="ah-diff">
            <div className="ah-diff-head">
              <span className="ah-path">{selected.path}</span>
              <span className={`ah-fbadge ah-fbadge-${status}`}>{status}</span>
              <span className="ah-grow" />
              {status !== "read" && (
                <>
                  <span className="ah-plus">+{selected.added}</span>
                  <span className="ah-minus">−{selected.removed}</span>
                </>
              )}
            </div>
            <div className="ah-small ah-subtle" style={{ padding: "12px 16px" }}>
              {status === "read" ? "Read only · no changes" : DIFF_NOT_STORED}
            </div>
          </div>
          <div className="ah-card">
            <div className="ah-card-head">
              <b className="ah-small">
                Touched by {selected.event_ids.length}{" "}
                {selected.event_ids.length === 1 ? "event" : "events"}
              </b>
            </div>
            <ul className="ah-group-list" style={{ padding: 8 }}>
              {selected.event_ids.map((id) => {
                const event = byId.get(id);
                const tool = event?.payload.tool;
                return (
                  <li key={id}>
                    <span className="ah-mono ah-subtle">
                      {event ? fmtClock(event.timestamp, tz, true) : "—"}
                    </span>
                    <span>{typeof tool === "string" ? tool : (event?.type ?? "event")}</span>
                    {event?.agent && event.agent !== "main" && (
                      <span className="ah-mono">{event.agent}</span>
                    )}
                    <AppLink
                      href={`/sessions/${encodeURIComponent(sessionId)}?event=${encodeURIComponent(id)}`}
                      onClick={(click) => {
                        click.preventDefault();
                        onJump(id);
                      }}
                    >
                      Jump to timeline
                    </AppLink>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
