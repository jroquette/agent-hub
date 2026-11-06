/* The triage batch: how many learnings are marked, and the dialog that lists them and opens one
 * hub pull request per project with all of them. */
import { useEffect, useId, useRef, useState } from "react";

import { Button, IconButton, StatusBadge } from "../../components";
import { displayTitle, PullRequestLink } from "./LearningDetail";
import {
  MAX_BATCH,
  unstageDecisions,
  useSendStaged,
  useStagedDecisions,
  type LearningBatchResult,
  type StagedDecision,
} from "./staged";

/** A mark as a badge: "Marked: accept" or "Marked: reject". */
export function StagedBadge({ decision }: { decision: StagedDecision }) {
  return decision.action === "accept" ? (
    <StatusBadge status="done" label="Marked: accept" />
  ) : (
    <StatusBadge status="failed" label="Marked: reject" />
  );
}

function byProject(staged: Readonly<Record<string, StagedDecision>>) {
  const groups = new Map<string, [string, StagedDecision][]>();
  for (const entry of Object.entries(staged)) {
    const project = entry[1].project;
    groups.set(project, [...(groups.get(project) ?? []), entry]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

function counts(entries: readonly [string, StagedDecision][]): string {
  const accepted = entries.filter(([, d]) => d.action === "accept").length;
  const rejected = entries.length - accepted;
  return [
    accepted > 0 && `${String(accepted)} accept`,
    rejected > 0 && `${String(rejected)} reject`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The bar above the queue while learnings are marked. */
export function TriageBatchBar({ onSelect }: { onSelect: (id: string) => void }) {
  const staged = useStagedDecisions();
  const [open, setOpen] = useState(false);
  const entries = Object.entries(staged);
  if (entries.length === 0 && !open) return null;
  return (
    <>
      {entries.length > 0 && (
        <section
          aria-label="Marked learnings"
          className="ah-row ah-wrap"
          style={{
            gap: 8,
            alignItems: "center",
            padding: "8px 12px",
            borderRadius: 8,
            border: "1px solid var(--accent)",
            borderLeft: "3px solid var(--accent)",
            background: "var(--surface)",
          }}
        >
          <b style={{ fontWeight: 600 }} role="status">
            {entries.length} marked
          </b>
          <span className="ah-small ah-muted ah-grow">{counts(entries)}</span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              unstageDecisions(entries.map(([id]) => id));
            }}
          >
            Clear
          </Button>
          <Button
            size="sm"
            variant="primary"
            icon="git-pull-request"
            onClick={() => {
              setOpen(true);
            }}
          >
            Review and open PR
          </Button>
        </section>
      )}
      {open && (
        <TriageBatchDialog
          onSelect={(id) => {
            setOpen(false);
            onSelect(id);
          }}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

function ProjectBatch({
  project,
  entries,
  onSelect,
  onSent,
}: {
  project: string;
  entries: readonly [string, StagedDecision][];
  onSelect: (id: string) => void;
  onSent: (project: string, result: LearningBatchResult) => void;
}) {
  const send = useSendStaged();
  const ids = entries.map(([id]) => id);
  const tooMany = ids.length > MAX_BATCH;
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div className="ah-row" style={{ gap: 8, alignItems: "center" }}>
        <b style={{ fontWeight: 600 }} className="ah-grow">
          {project} <span className="ah-small ah-muted">· {counts(entries)}</span>
        </b>
        <Button
          size="sm"
          variant="primary"
          disabled={send.isPending || tooMany}
          title={tooMany ? `At most ${String(MAX_BATCH)} per pull request` : undefined}
          onClick={() => {
            // The sent marks are cleared on success, which unmounts this block: the promise (not
            // a per-call callback, dropped on unmount) hands the result to the dialog.
            send.mutateAsync(ids).then(
              (result) => {
                onSent(project, result);
              },
              () => undefined, // The error shows below from the mutation's state.
            );
          }}
        >
          {send.isPending ? "Opening pull request…" : "Open pull request"}
        </Button>
      </div>
      <ul className="ah-stack" style={{ gap: 6, margin: 0, padding: 0, listStyle: "none" }}>
        {entries.map(([id, d]) => (
          <li
            key={id}
            className="ah-row"
            style={{
              gap: 8,
              alignItems: "flex-start",
              padding: "6px 8px",
              border: "1px solid var(--border)",
              borderRadius: 6,
            }}
          >
            <StagedBadge decision={d} />
            <span className="ah-stack ah-grow" style={{ gap: 2, minWidth: 0 }}>
              <button
                type="button"
                style={{
                  background: "none",
                  border: 0,
                  padding: 0,
                  color: "var(--text)",
                  cursor: "pointer",
                  font: "inherit",
                  textAlign: "left",
                  fontWeight: 500,
                }}
                onClick={() => {
                  onSelect(id);
                }}
              >
                {displayTitle(d.title)}
              </button>
              <span className="ah-small ah-muted" style={{ overflowWrap: "anywhere" }}>
                {d.action === "accept" ? (
                  <>
                    to <span className="ah-mono">brain/{d.target}</span>
                  </>
                ) : (
                  d.reason
                )}
              </span>
            </span>
            <IconButton
              icon="x"
              size="sm"
              label="Unmark"
              disabled={send.isPending}
              onClick={() => {
                unstageDecisions([id]);
              }}
            />
          </li>
        ))}
      </ul>
      {send.error && (
        <div
          role="alert"
          className="ah-small"
          style={{
            border: "1px solid var(--failed)",
            borderLeft: "3px solid var(--failed)",
            borderRadius: "var(--radius-md)",
            padding: "8px 12px",
          }}
        >
          <b style={{ fontWeight: 600 }}>Could not open the pull request.</b>{" "}
          {send.error.detail ?? send.error.title} Nothing was pushed; fix or unmark that learning
          and try again.
        </div>
      )}
    </div>
  );
}

/** Lists every marked learning by project, each project with its "Open pull request". */
export function TriageBatchDialog({
  onSelect,
  onClose,
}: {
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const staged = useStagedDecisions();
  const [opened, setOpened] = useState<[string, LearningBatchResult][]>([]);
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const groups = byProject(staged);

  useEffect(() => {
    const before = document.activeElement;
    dialog.current?.querySelector<HTMLElement>("button.ah-btn-primary, button")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      if (before instanceof HTMLElement) before.focus();
    };
  }, [onClose]);

  return (
    <div className="ah-scrim">
      <div
        ref={dialog}
        className="ah-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        style={{ width: "min(720px, 92vw)" }}
      >
        <div
          className="ah-dialog-body ah-stack"
          style={{ gap: 14, maxHeight: "70vh", overflowY: "auto" }}
        >
          <h2 id={titleId} className="ah-h3">
            Open the triage pull request
          </h2>
          <p style={{ margin: 0 }}>
            Every marked learning of a project goes into one pull request in its hub, in one commit.
            Nothing changes in the brain until you merge it.
          </p>
          {opened.map(([project, result]) => (
            <div key={result.pr_url} role="status" className="ah-stack" style={{ gap: 2 }}>
              <b style={{ fontWeight: 600 }}>
                Pull request opened for {project} · {result.decided.length}{" "}
                {result.decided.length === 1 ? "learning" : "learnings"}
              </b>
              <PullRequestLink url={result.pr_url} />
            </div>
          ))}
          {groups.map(([project, entries]) => (
            <ProjectBatch
              key={project}
              project={project}
              entries={entries}
              onSelect={onSelect}
              onSent={(p, result) => {
                setOpened((current) => [...current, [p, result]]);
              }}
            />
          ))}
          {groups.length === 0 && opened.length === 0 && (
            <span className="ah-muted">Nothing is marked.</span>
          )}
        </div>
        <div className="ah-dialog-foot">
          <Button onClick={onClose}>{groups.length === 0 ? "Done" : "Close"}</Button>
        </div>
      </div>
    </div>
  );
}
