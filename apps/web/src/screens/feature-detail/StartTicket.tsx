import { useNavigate } from "react-router";

import type { components } from "../../api/schema";
import { Button, Tooltip } from "../../components";
import { agentSessionHref } from "../sessions-list/control";
import { useCreateAgentSession, useHubSessionStart } from "../sessions-list/queries";

type TicketRow = components["schemas"]["TicketRow"];

type InReview = TicketRow & { id: string; pr_url: string };

/**
 * The blocker a waiting ticket can be stacked on: its only blocker not done, a ticket of this
 * feature already started with a pull request open (in review, not merged). Working on top of its
 * branch saves waiting for the merge. Null when the ticket waits on anything else.
 */
export function stackedOn(row: TicketRow, rows: readonly TicketRow[]): InReview | null {
  if (row.id == null || row.readiness !== "waiting" || row.waiting_on.length !== 1) return null;
  const blocker = rows.find((r) => r.ref === row.waiting_on[0]);
  if (blocker?.id == null || blocker.pr_url == null || blocker.readiness !== "in_progress") {
    return null;
  }
  return blocker as InReview;
}

/**
 * Whether a ticket shows the Start button: created in the tracker and free to pick up now, or
 * waiting only on a blocker in review, to start on top of its branch (`stackedOn`).
 */
export function canStartTicket(
  row: TicketRow,
  rows: readonly TicketRow[],
): row is TicketRow & { id: string } {
  return row.id != null && (row.readiness === "can_start" || stackedOn(row, rows) != null);
}

/** What the session is told about the blockers, and how to build on one still in review. */
function blockerLines(row: TicketRow, rows: readonly TicketRow[]): string[] {
  const idOf = (ref: string) => rows.find((r) => r.ref === ref)?.id ?? ref;
  const base = stackedOn(row, rows);
  const done = row.blocked_by.map((edge) => edge.ref).filter((ref) => ref !== base?.ref);
  const lines = [
    done.length
      ? `Its blockers are done: ${done.map(idOf).join(", ")}.`
      : base
        ? ""
        : "It has no blockers.",
  ];
  if (!base) return lines;
  const repo = base.repo ?? "<the PR's repo>";
  return [
    ...lines,
    `Its blocker ${base.id} is not merged yet: it is in review in ${base.pr_url}. Build this ticket on top of it (a stacked branch) instead of waiting for the merge.`,
    `For step 5, read that pull request's branch with \`gh pr view ${base.pr_url} --json headRefName -q .headRefName\`, then create the worktree in ${repo} from it: \`./hub worktree <name> --only ${repo} --base <that branch>\`. Any other repo starts from its default branch as usual.`,
    `Open this ticket's pull request against ${base.id}'s branch, not the default branch, and say in its body that it is stacked on ${base.pr_url}. If ${base.id} changes in review, rebase onto its branch; once it merges, rebase onto the default branch and retarget the pull request.`,
  ];
}

/**
 * The first message of a ticket's session: the hub's `/feature` skill on this one ticket, starting
 * at its workspace step, since the feature's spec, plan and tickets already exist.
 */
export function ticketPrompt(
  project: string,
  slug: string,
  row: TicketRow & { id: string },
  rows: readonly TicketRow[],
): string {
  const context = [
    `I am the owner of the agent-hub project "${project}", starting this ticket from the Tickets tab of the agent-hub web app.`,
    `Ticket: ${row.id}${row.title ? ` · ${row.title}` : ""}${row.url ? ` (${row.url})` : ""}.`,
    `Feature: \`${slug}\`; its record is in \`brain/features/${slug}/\` (spec.md, research.md, plan.md, features.json, issues.md). Read it first.`,
    row.repo ? `Repo: ${row.repo}.` : "",
    row.acs.length ? `Acceptance criteria this ticket owns: ${row.acs.join(", ")}.` : "",
    ...blockerLines(row, rows),
    "The spec, plan and tickets of this feature are already approved and created, so skip steps 0 to 4 of /feature and begin at step 5 (Workspace), for this ticket only.",
    "Set the ticket to In Progress in the tracker when you start. Then implement it (step 6), review it (step 7) and verify it with the evaluator scoped to this ticket (step 8).",
    "Work on no other ticket. Ask me before you push or open the pull request.",
  ].filter(Boolean);
  return [`/feature ${row.id}`, "", ...context].join("\n");
}

/**
 * Starts a Claude session in the hub folder that works the ticket with `/feature`, then opens its
 * chat. Disabled, with the reason, when this machine cannot drive Claude or the hub has no folder.
 */
export function StartTicketButton({
  project,
  slug,
  row,
  rows,
}: {
  project: string;
  slug: string;
  row: TicketRow & { id: string };
  rows: readonly TicketRow[];
}) {
  const start = useHubSessionStart(project);
  const create = useCreateAgentSession();
  const navigate = useNavigate();
  const base = stackedOn(row, rows);
  const label = base ? `Start ${row.id} on ${base.id}` : `Start ${row.id}`;
  const text = base ? `Start on ${base.id}` : "Start";

  const begin = async () => {
    if (!start.hubWorkdirId) return;
    const created = await create.mutateAsync({
      project,
      workdir_id: start.hubWorkdirId,
      mode: "acceptEdits",
      fork: false,
      prompt: ticketPrompt(project, slug, row, rows),
    });
    void navigate(agentSessionHref(created.id));
  };

  const blocked = start.reason;
  const failed = create.error ? (create.error.detail ?? create.error.title) : null;
  if (blocked) {
    return (
      <Tooltip label={blocked}>
        <Button
          size="sm"
          variant="primary"
          icon="play"
          disabled
          aria-label={`${label}. ${blocked}`}
        >
          {text}
        </Button>
      </Tooltip>
    );
  }
  return (
    <Tooltip
      label={
        failed
          ? `Could not start: ${failed}`
          : base
            ? `${base.id} is in review, not merged: start a Claude session that works ${row.id} with /feature on top of its branch`
            : `Start a Claude session that works ${row.id} with /feature`
      }
    >
      <Button
        size="sm"
        variant={base ? "default" : "primary"}
        icon={base ? "git-branch" : "play"}
        aria-label={label}
        disabled={create.isPending}
        onClick={() => void begin()}
      >
        {create.isPending ? "Starting…" : failed ? "Retry" : text}
      </Button>
    </Tooltip>
  );
}
