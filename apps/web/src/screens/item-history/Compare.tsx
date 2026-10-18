import { useId } from "react";

import { Button, Icon, ProblemError, Skeleton } from "../../components";
import type { IconName } from "../../components";
import { unifiedDiff } from "../agent-session/model";
import { DiffText } from "../agent-session/ToolCallCard";
import { folderDiff, shortHash, type FileChange } from "./model";
import { useItemVersion, type HistoryTarget, type ItemVersion } from "./queries";

/* Compare (S6, AC-295.30): any two versions, the older against the newer, through the Studio's
 * `unifiedDiff` and `DiffText`; a folder shows one diff per changed file. */

const STATUS: Record<FileChange["status"], { label: string; icon: IconName }> = {
  added: { label: "Added", icon: "file-plus" },
  removed: { label: "Removed", icon: "file-minus" },
  changed: { label: "Changed", icon: "file-pen" },
};

const bit = (on: boolean) => (on ? "on" : "off");

function Change({ change }: { change: FileChange }) {
  const look = STATUS[change.status];
  const binary =
    (change.older !== null && change.older.text === null) ||
    (change.newer !== null && change.newer.text === null);
  return (
    <div className="ah-stack ah-history-change">
      <p className="ah-history-change-head ah-small">
        <span className="ah-badge ah-badge-quiet">
          <Icon name={look.icon} />
          {look.label}
        </span>
        <span className="ah-mono">{change.path}</span>
      </p>
      {change.bitsChanged && change.older && change.newer && (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Executable bit: {bit(change.older.executable)} → {bit(change.newer.executable)}
        </p>
      )}
      {change.textChanged &&
        (binary ? (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            A binary file: its bytes differ, and it has no text to show.
          </p>
        ) : (
          <DiffText
            diff={unifiedDiff(change.path, change.older?.text ?? "", change.newer?.text ?? "")}
            label={`Changes to ${change.path}`}
          />
        ))}
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
  } else if (!before.data || !after.data) {
    body = (
      <div role="status" aria-label="Loading the versions" aria-busy="true">
        <Skeleton lines={4} />
      </div>
    );
  } else {
    const changes = folderDiff(before.data.files, after.data.files);
    body =
      changes.length === 0 ? (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          These two versions hold the same content.
        </p>
      ) : (
        changes.map((change) => <Change key={change.path} change={change} />)
      );
  }

  return (
    <section className="ah-stack ah-history-compare" aria-labelledby={`${id}-title`}>
      <div className="ah-history-tools">
        <h3 id={`${id}-title`} className="ah-h3 ah-grow" style={{ margin: 0 }}>
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
