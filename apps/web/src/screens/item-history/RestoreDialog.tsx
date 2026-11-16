import { useState } from "react";

import { Banner, ConfirmDialog } from "../../components";
import type { ApiProblem } from "../../lib/api";
import { shortHash, writeProblemWords } from "./model";
import {
  useRestoreVersion,
  type HistoryTarget,
  type ItemVersion,
  type ItemVersionPage,
  type ItemWriteResult,
} from "./queries";

/* The Restore dialog (S9, AC-295.22, .23): nothing is sent until its verb is pressed; a unit
 * hub.lock manages warns first and sends `confirm_managed: true` only from "Restore anyway". */

/** S9's warning, word for word. */
export const MANAGED_WARNING =
  "This file is managed by hub.lock: the next hub sync rewrites it. Restore anyway?";

/** What the panel says once the dialog closes; `warning` when something was not recorded. */
export interface RestoreOutcome {
  text: string;
  warning: boolean;
}

/** What a finished restore did, in words, for the panel's status line. */
export function restoredWords(version: ItemVersion, result: ItemWriteResult): string {
  const hash = shortHash(version.content_hash);
  if (!result.changed) return `The item already holds ${hash}: nothing was written.`;
  if (!result.versioned) {
    const why = result.reason === "too_large" ? "too large" : "secret";
    return `Restored ${hash}, but not versioned: ${why}.`;
  }
  return `Restored ${hash}: a new version records it.`;
}

/** A restore that wrote the unit but could not record its version (503, API.md Errors). */
export function unrecordedWords(version: ItemVersion, problem: ApiProblem): string {
  const advice =
    problem.detail ??
    "The next read records it as changed outside the app. Reload the history before trying again.";
  return `Wrote ${shortHash(version.content_hash)}, but its version was not recorded. ${advice}`;
}

function whatIsWritten(page: ItemVersionPage) {
  const path = <span className="ah-mono">{page.unit_path}</span>;
  if (page.unit_kind === "hook") {
    const hooks = `${String(page.shared_by)} ${page.shared_by === 1 ? "hook" : "hooks"} today`;
    return (
      <>
        Restores the whole file {path}: every hook in it ({hooks}).
      </>
    );
  }
  return <>Writes this version back into {path}.</>;
}

export function RestoreDialog({
  target,
  version,
  page,
  onClose,
  onRestored,
}: {
  target: HistoryTarget;
  version: ItemVersion;
  page: ItemVersionPage;
  onClose: () => void;
  onRestored: (outcome: RestoreOutcome) => void;
}) {
  const restore = useRestoreVersion(target);
  // The server may know the unit is managed when the list did not (hub.lock changed since).
  const [managed, setManaged] = useState(page.managed);
  const problem = restore.error;
  const asked = problem?.code === "managed_confirmation_required";
  const send = () => {
    restore.mutate(
      { versionId: version.id, confirmManaged: managed },
      {
        onSuccess: (result) => {
          onRestored({
            text: restoredWords(version, result),
            warning: result.changed && !result.versioned,
          });
        },
        onError: (error) => {
          if (error.code === "managed_confirmation_required") setManaged(true);
          // The unit was written (`written: true`): there is nothing left to confirm here.
          if (error.code === "written_not_recorded")
            onRestored({ text: unrecordedWords(version, error), warning: true });
        },
      },
    );
  };
  return (
    <ConfirmDialog
      title={`Restore ${shortHash(version.content_hash)}?`}
      tone="primary"
      confirmLabel={managed ? "Restore anyway" : "Restore"}
      onCancel={onClose}
      onConfirm={send}
      pending={restore.isPending}
      consequences={[
        "The current content is recorded first when it changed, so it stays restorable.",
        "git is not run: the change shows in the hub's working tree.",
      ]}
    >
      <p style={{ margin: 0 }}>{whatIsWritten(page)}</p>
      {managed && (
        <div style={{ marginTop: 12 }}>
          <Banner tone="warning" boxed>
            {MANAGED_WARNING}
          </Banner>
        </div>
      )}
      {problem && !asked && (
        <div style={{ marginTop: 12 }}>
          <Banner tone="error" boxed>
            {writeProblemWords(problem)}
          </Banner>
        </div>
      )}
    </ConfirmDialog>
  );
}
