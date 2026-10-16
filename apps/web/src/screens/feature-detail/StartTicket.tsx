import { useNavigate } from "react-router";

import type { components } from "../../api/schema";
import { Button, Tooltip } from "../../components";
import { agentSessionHref } from "../sessions-list/control";
import { useCreateAgentSession, useHubSessionStart } from "../sessions-list/queries";

type TicketRow = components["schemas"]["TicketRow"];

/** Whether a ticket shows the Start button: created in the tracker and free to pick up now. */
export function canStartTicket(row: TicketRow): row is TicketRow & { id: string } {
  return row.id != null && row.readiness === "can_start";
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
  const blockers = row.blocked_by.map((edge) => {
    const blocker = rows.find((r) => r.ref === edge.ref);
    return blocker?.id ?? edge.ref;
  });
  const context = [
    `I am the owner of the agent-hub project "${project}", starting this ticket from the Tickets tab of the agent-hub web app.`,
    `Ticket: ${row.id}${row.title ? ` · ${row.title}` : ""}${row.url ? ` (${row.url})` : ""}.`,
    `Feature: \`${slug}\`; its record is in \`brain/features/${slug}/\` (spec.md, research.md, plan.md, features.json, issues.md). Read it first.`,
    row.repo ? `Repo: ${row.repo}.` : "",
    row.acs.length ? `Acceptance criteria this ticket owns: ${row.acs.join(", ")}.` : "",
    blockers.length ? `Its blockers are done: ${blockers.join(", ")}.` : "It has no blockers.",
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
  const label = `Start ${row.id}`;

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
          Start
        </Button>
      </Tooltip>
    );
  }
  return (
    <Tooltip
      label={
        failed
          ? `Could not start: ${failed}`
          : `Start a Claude session that works ${row.id} with /feature`
      }
    >
      <Button
        size="sm"
        variant="primary"
        icon="play"
        aria-label={label}
        disabled={create.isPending}
        onClick={() => void begin()}
      >
        {create.isPending ? "Starting…" : failed ? "Retry" : "Start"}
      </Button>
    </Tooltip>
  );
}
