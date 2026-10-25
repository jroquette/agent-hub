import { useEffect, useRef } from "react";

import { Banner, Button, Dialog } from "../../../components";
import { useMigrateScenario } from "../queries";

/* Migrate: a graph scenario (`version: 1`) stays editable in the builder, and this writes it
 * again as stages of blocks (`version: 2`), as `hub scenario migrate` does. It checks first and
 * shows the blocks, or each step a tree cannot hold and why; nothing is written until the person
 * migrates, and only over the file the check read (its hash): a file changed since is refused,
 * and the dialog checks it again. */

export function MigrateDialog({
  project,
  name,
  contentHash,
  unsaved,
  onClose,
}: {
  project: string;
  name: string;
  /** The hash of the file as the builder reads it now (the next check is made with it). */
  contentHash: string | null;
  /** The draft holds changes: Migrate rewrites the file on disk, so they are saved first. */
  unsaved: boolean;
  onClose: () => void;
}) {
  const check = useMigrateScenario(project, name);
  const write = useMigrateScenario(project, name);
  const { mutate: checkFile } = check;
  // The hash the last check was sent with: the write goes over the very file it read.
  const sent = useRef<string | null>(null);
  const asked = useRef(false);
  useEffect(() => {
    if (unsaved || asked.current) return;
    asked.current = true;
    sent.current = contentHash;
    checkFile({ check: true, base_content_hash: contentHash });
  }, [unsaved, checkFile, contentHash]);
  const checkAgain = () => {
    write.reset();
    sent.current = contentHash;
    checkFile({ check: true, base_content_hash: contentHash });
  };
  const checked = check.data ?? null;
  const wrote = write.data ?? null;
  const written = wrote?.written === true;
  // What could not be migrated: the write's own answer once it wrote nothing, else the check's.
  const refused = wrote !== null && !written ? wrote.problems : (checked?.problems ?? []);
  const problem = write.error ?? check.error;
  const canWrite =
    checked !== null &&
    checked.yaml !== null &&
    checked.problems.length === 0 &&
    wrote === null &&
    write.error === null;
  // A write refused (the file changed since the check, or into one blocks cannot hold), or a
  // check that failed: the next check reads the file as it is now.
  const again = !check.isPending && (problem !== null || (wrote !== null && !written));
  return (
    <Dialog
      title="Migrate to stages of blocks"
      size="lg"
      pending={write.isPending}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{written ? "Close" : "Cancel"}</Button>
          {again && !unsaved && <Button onClick={checkAgain}>Check again</Button>}
          {canWrite && (
            <Button
              variant="primary"
              icon="milestone"
              disabled={write.isPending}
              onClick={() => {
                write.mutate({
                  check: false,
                  base_content_hash: checked.content_hash ?? sent.current,
                });
              }}
            >
              {write.isPending ? "Migrating…" : "Migrate"}
            </Button>
          )}
        </>
      }
    >
      <div className="ah-stack" style={{ gap: 10 }}>
        <span className="ah-small ah-muted">
          This scenario is a graph (version 1). Migrate writes it again as stages of blocks (version
          2), as <span className="ah-mono">./hub scenario migrate</span> does: one stage named after
          the scenario, each step a block in the order it runs, the same steps and conditions. The
          builder then edits its stages. Comments in the file are not kept.
        </span>
        {unsaved && (
          <Banner tone="warning" live={false}>
            Save your changes first: Migrate rewrites the file as it is saved.
          </Banner>
        )}
        {!unsaved && check.isPending && <span className="ah-small">Checking…</span>}
        {problem && (
          <Banner tone="error" live={false}>
            {problem.detail ?? problem.title}
          </Banner>
        )}
        {refused.length > 0 && (
          <>
            <span className="ah-small">
              It cannot be written as blocks yet. Nothing was written. Change these steps, then
              check again:
            </span>
            <ul className="sb-migrate-problems" aria-label="What blocks cannot hold">
              {refused.map((item, index) => (
                <li key={index}>
                  {item.node && <b className="ah-mono">{item.node}: </b>}
                  <span>{item.message}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {written && (
          <Banner tone="info" live={false}>
            Migrated: {name} is now written as blocks (version 2). The builder reads its stages.
          </Banner>
        )}
        {canWrite && (
          <>
            <span className="ah-small">
              Nothing is written until you migrate. The file will read:
            </span>
            {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrollable region */}
            <pre className="ah-json sb-yaml-text" tabIndex={0} aria-label="The scenario as blocks">
              {checked.yaml}
            </pre>
          </>
        )}
      </div>
    </Dialog>
  );
}
