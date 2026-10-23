import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  Button,
  CodeBlock,
  Dialog,
  IssueLink,
  Markdown,
  PathText,
  ProvenanceBadge,
} from "../../components";
import type { ApiProblem } from "../../lib/api";
import {
  useFindingInbox,
  useFindingIssue,
  type FindingIssue,
  type ScenarioFinding,
  type ScenarioRunDetail,
} from "./queries";

/* A scenario run's findings (AC-350.27, E-14): each can become a tracker issue (a draft, then a
 * confirm, created once and never retried here) or an inbox note (never over another). */

function retryCommand(runId: string, findingId: string): string {
  return `./hub scenario findings ${runId} --issue ${findingId}`;
}

function IssueResult({
  run,
  finding,
  error,
  issue,
}: {
  run: ScenarioRunDetail;
  finding: ScenarioFinding;
  error: ApiProblem | null;
  issue: FindingIssue | undefined;
}) {
  if (issue?.created) {
    return (
      <span role="status" className="ah-stack ah-small" style={{ gap: 2 }}>
        <span>
          Created <IssueLink id={issue.created.id} href={issue.created.url} />.
        </span>
        {issue.recorded === false && (
          <b>{issue.created.id} was created but could not be recorded. Do not create it again.</b>
        )}
      </span>
    );
  }
  if (error === null) return null;
  let title: string;
  let detail: ReactNode;
  if (error.code === "issue_exists" && error.detail && /[A-Z][A-Z0-9]*-\d+/.test(error.detail)) {
    title = "This finding already has an issue";
    detail = error.detail;
  } else if (error.code === "issue_exists" && error.detail?.includes("running")) {
    title = "A create of this issue is running. Reload in a moment.";
    detail = null;
  } else if (error.code === "tracker_not_connected") {
    title = "No tracker key for hub web";
    detail = (
      <>
        This hub reaches its tracker through its API key, which hub web does not have. Create the
        issue from a terminal:
        <CodeBlock code={retryCommand(run.run_id, finding.finding_id)} />
      </>
    );
  } else if (error.code === "hub_local_invalid") {
    title =
      "hub.local.json cannot be read or conflicts with hub.json, so the tracker is unknown. Run ./hub doctor, fix the file, then create the issue.";
    detail = null;
  } else {
    title = "The issue may already exist in the tracker";
    detail = (
      <>
        The create failed or did not finish, so it is not retried here. Check the tracker first. To
        try again, run in a terminal:
        <CodeBlock code={retryCommand(run.run_id, finding.finding_id)} />
      </>
    );
  }
  return (
    <div role="alert" className="ah-stack ah-small" style={{ gap: 4 }}>
      <b style={{ fontWeight: 600 }}>{title}</b>
      {detail && <span>{detail}</span>}
    </div>
  );
}

function IssueDialog({
  run,
  finding,
  onClose,
}: {
  run: ScenarioRunDetail;
  finding: ScenarioFinding;
  onClose: () => void;
}) {
  const draft = useFindingIssue(run.run_id, finding.finding_id);
  const create = useFindingIssue(run.run_id, finding.finding_id);
  const asked = useRef(false);
  const { mutate } = draft;
  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    mutate({ confirm: false });
  }, [mutate]);
  const team = draft.data?.team ?? null;
  const label = team ? `Create issue in ${team}` : "Create issue";
  return (
    <Dialog
      title={`Create an issue for finding ${finding.finding_id}?`}
      onClose={create.isPending ? undefined : onClose}
      pending={create.isPending}
      initialFocus="[data-cancel]"
      footer={
        <>
          <Button data-cancel="" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            // One press only: a create is never retried from the screen (E-14).
            disabled={
              draft.data === undefined || create.isPending || create.isSuccess || create.isError
            }
            onClick={() => {
              create.mutate({ confirm: true });
            }}
          >
            {label}
          </Button>
        </>
      }
    >
      <div className="ah-stack" style={{ gap: 8 }}>
        {draft.isPending && <span className="ah-small">Drafting the issue…</span>}
        {draft.isError && (
          <IssueResult run={run} finding={finding} error={draft.error} issue={undefined} />
        )}
        {draft.data && (
          <>
            <b>{draft.data.title}</b>
            <Markdown source={draft.data.description} />
            {team && <span className="ah-small">Goes to team {team}.</span>}
            <span className="ah-small ah-muted">
              It is created once. If the create fails, it is not retried here.
            </span>
          </>
        )}
        {create.isPending && (
          <span role="status" className="ah-small">
            Creating the issue…
          </span>
        )}
        <IssueResult
          run={run}
          finding={finding}
          error={create.isError ? create.error : null}
          issue={create.data}
        />
      </div>
    </Dialog>
  );
}

function NoteResult({
  error,
  path,
  finding,
}: {
  error: ApiProblem | null;
  path: string | null;
  finding: string;
}) {
  if (path !== null) {
    return (
      <span role="status" className="ah-small">
        Wrote <PathText path={path} max={80} />.
      </span>
    );
  }
  if (error === null) return null;
  const text =
    error.code === "note_exists"
      ? `An inbox note for finding ${finding} already exists in brain/_inbox/. Nothing was written.`
      : error.code === "link_in_path"
        ? "brain/_inbox/ is reached through a link, so nothing was written."
        : (error.detail ?? error.title);
  return (
    <span role="alert" className="ah-small">
      {text}
    </span>
  );
}

function FindingItem({
  run,
  finding,
  actionsOff,
}: {
  run: ScenarioRunDetail;
  finding: ScenarioFinding;
  actionsOff: boolean;
}) {
  const [drafting, setDrafting] = useState(false);
  const inbox = useFindingInbox(run.run_id, finding.finding_id);
  return (
    <li
      className="ah-stack"
      style={{ gap: 4, padding: "8px 0", borderTop: "1px solid var(--border)" }}
    >
      <b>
        <span className="ah-mono">{finding.finding_id}</span> · {finding.title}
      </b>
      <span className="ah-small ah-muted">
        step <span className="ah-mono">{finding.step}</span> in {run.environment ?? "—"}
      </span>
      <span className="ah-small">{finding.text}</span>
      {finding.evidence && (
        <details className="ah-small">
          <summary style={{ cursor: "pointer" }}>Evidence</summary>
          <span>{finding.evidence}</span>
        </details>
      )}
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <Button
          size="sm"
          icon="pencil"
          disabled={actionsOff}
          onClick={() => {
            setDrafting(true);
          }}
        >
          Draft tracker issue
        </Button>
        <Button
          size="sm"
          icon="file-plus"
          disabled={actionsOff || inbox.isPending || inbox.isSuccess}
          onClick={() => {
            inbox.mutate();
          }}
        >
          Write inbox note
        </Button>
      </div>
      <NoteResult
        error={inbox.isError ? inbox.error : null}
        path={inbox.data?.path ?? null}
        finding={finding.finding_id}
      />
      {drafting && (
        <IssueDialog
          run={run}
          finding={finding}
          onClose={() => {
            setDrafting(false);
          }}
        />
      )}
    </li>
  );
}

/** The findings, from the agent and the system; hidden while a run that has none still runs. */
export function Findings({
  run,
  ended,
  actionsOff,
}: {
  run: ScenarioRunDetail;
  ended: boolean;
  actionsOff: boolean;
}) {
  if (run.findings.length === 0 && !ended) return null;
  return (
    <section aria-label="Findings" className="ah-card ah-card-body ah-stack" style={{ gap: 6 }}>
      <div className="ah-row" style={{ gap: 8 }}>
        <h2 className="ah-h3" style={{ margin: 0 }}>
          Findings ({run.findings.length})
        </h2>
        <span className="ah-small ah-muted">from the agent</span>
        <ProvenanceBadge provenance="agent-from-external" />
      </div>
      {run.findings.length === 0 ? (
        <span className="ah-small ah-muted">No findings recorded.</span>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {run.findings.map((finding) => (
            <FindingItem
              key={finding.finding_id}
              run={run}
              finding={finding}
              actionsOff={actionsOff}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
