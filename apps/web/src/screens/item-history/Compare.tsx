import { useEffect, useId, useMemo, useRef } from "react";

import { Button, Icon, ProblemError, Skeleton } from "../../components";
import type { IconName } from "../../components";
import { DiffText } from "../agent-session/ToolCallCard";
import {
  compareChanges,
  shortHash,
  unshownBinaries,
  type FileChange,
  type ShownChange,
} from "./model";
import { useItemVersion, type HistoryTarget, type ItemVersion } from "./queries";

/* Compare (S6, AC-295.30): any two versions, the older against the newer, through the Studio's
 * `unifiedDiff` and `DiffText`; a folder shows one diff per changed file. */

const STATUS: Record<FileChange["status"], { label: string; icon: IconName }> = {
  added: { label: "Added", icon: "file-plus" },
  removed: { label: "Removed", icon: "file-minus" },
  changed: { label: "Changed", icon: "file-pen" },
};

const bit = (on: boolean) => (on ? "on" : "off");

const lineCount = (n: number) => `${String(n)} more ${n === 1 ? "line" : "lines"}`;

function Change({ change }: { change: ShownChange }) {
  const look = STATUS[change.status];
  const note = (text: string) => (
    <p className="ah-small ah-muted" style={{ margin: 0 }}>
      {text}
    </p>
  );
  return (
    <div className="ah-stack ah-history-change">
      <p className="ah-history-change-head ah-small">
        <span className="ah-badge ah-badge-quiet">
          <Icon name={look.icon} />
          {look.label}
        </span>
        <span className="ah-mono">{change.path}</span>
      </p>
      {change.bitsChanged &&
        change.older &&
        change.newer &&
        note(`Executable bit: ${bit(change.older.executable)} → ${bit(change.newer.executable)}`)}
      {change.textChanged &&
        change.diff === null &&
        !change.skipped &&
        note("A binary file: its bytes differ, and it has no text to show.")}
      {change.diff !== null && <DiffText diff={change.diff} label={`Changes to ${change.path}`} />}
      {change.hiddenLines > 0 && note(`${lineCount(change.hiddenLines)} — too large to show here`)}
      {change.skipped && note("Diff not shown — too large to show here.")}
    </div>
  );
}

/** The two versions' differences; `older` and `newer` are already ordered by the panel. */
export function Compare({
  target,
  older,
  newer,
  onClose,
}: {
  target: HistoryTarget;
  older: ItemVersion;
  newer: ItemVersion;
  onClose: () => void;
}) {
  const before = useItemVersion(target, older.id);
  const after = useItemVersion(target, newer.id);
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  // Opening Compare moves focus to its heading, so a screen reader reads what it compares.
  useEffect(() => {
    heading.current?.focus();
  }, [older.id, newer.id]);
  // Computed once per pair of loaded versions, not on each render of the panel.
  const changes = useMemo(
    () => (before.data && after.data ? compareChanges(before.data.files, after.data.files) : null),
    [before.data, after.data],
  );
  const title = `From ${shortHash(older.content_hash)} to ${shortHash(newer.content_hash)}`;

  let body;
  const failed = before.error ?? after.error;
  if (failed) {
    body = (
      <ProblemError
        title="Could not load these versions"
        detail={failed.detail}
        status={failed.status}
        onRetry={() => {
          void before.refetch();
          void after.refetch();
        }}
        compact
      />
    );
  } else if (!changes || !before.data || !after.data) {
    body = (
      <div role="status" aria-label="Loading the versions" aria-busy="true">
        <Skeleton lines={4} />
      </div>
    );
  } else if (changes.length > 0) {
    body = changes.map((change) => <Change key={change.path} change={change} />);
  } else if (older.content_hash === newer.content_hash) {
    body = (
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        These two versions hold the same content.
      </p>
    );
  } else {
    // Different hashes and nothing the web can tell apart: a binary file of the same size.
    const binaries = unshownBinaries(before.data.files, after.data.files);
    body = (
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        These versions differ in bytes the app cannot show
        {binaries.length > 0 ? (
          <>
            , in {binaries.length === 1 ? "the binary file" : "one of the binary files"}{" "}
            <span className="ah-mono">{binaries.join(", ")}</span>.
          </>
        ) : (
          "."
        )}
      </p>
    );
  }

  return (
    <section className="ah-stack ah-history-compare" aria-labelledby={`${id}-title`}>
      <div className="ah-history-tools">
        <h3
          ref={heading}
          id={`${id}-title`}
          className="ah-h3 ah-grow"
          style={{ margin: 0 }}
          tabIndex={-1}
        >
          {title}
        </h3>
        <Button size="sm" variant="ghost" icon="x" onClick={onClose}>
          Close compare
        </Button>
      </div>
      {body}
    </section>
  );
}
