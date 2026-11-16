import { useState } from "react";
import { useNavigate } from "react-router";

import type { components } from "../../api/schema";
import { Button, ConfirmDialog, Tooltip } from "../../components";
import { agentSessionHref } from "../sessions-list/control";
import { useCreateAgentSession, useHubSessionStart } from "../sessions-list/queries";
import { stackedOn } from "./PlanningView";

type TicketRow = components["schemas"]["TicketRow"];

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

/**
 * The worktree name a stacked ticket's command gives `hub worktree`: the ticket's id in lowercase
 * (`AGH-3` → `agh-3`), the issue shape it takes (`<team>-<n>[-<desc>]`).
 */
function stackedName(row: TicketRow & { id: string }): string {
  return row.id.toLowerCase();
}

/** What the session is told about the blockers, and how to build on one still in review. */
function blockerLines(row: TicketRow & { id: string }, rows: readonly TicketRow[]): string[] {
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
  const repo = base.repo ?? "the pull request's repo";
  return [
    ...lines,
    `Its blocker ${base.id} is not merged yet: it is in review in ${base.pr_url}. Build this ticket on top of it (a stacked branch) instead of waiting for the merge.`,
    `For the workspace, create the worktrees with exactly \`./hub worktree ${stackedName(row)} --stack-on ${base.pr_url}\`, with no --only and no --base: it starts ${repo}'s worktree from that pull request's branch and every other repo from its default branch.`,
    `Open this ticket's pull request against ${base.id}'s branch, not the default branch, and say in its body that it is stacked on ${base.pr_url}. If ${base.id} changes in review, rebase onto its branch; once it merges, rebase onto the default branch and retarget the pull request.`,
  ];
}

/**
 * The first message of a ticket's session: the hub's `/implement` skill, which this one session
 * conducts start to finish (ADR 0050). It records the ticket's context brief and preflight, opens
 * the worktree, and runs the ticket plan, the implementation, the review rounds and the eval as
 * its own subagents, reporting each in its chat, then asks before the pull request; no workflow
 * run or other session starts. A ticket stacked on a blocker in review takes the same flow, told
 * how to start its worktree from the blocker's branch.
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
    `Feature: \`${slug}\`; its record is in \`brain/features/${slug}/\` (spec.md, research.md, plan.md, features.json, issues.md).`,
    repoLine(row),
    ...blockerLines(row, rows),
    "Set the ticket to In Progress in the tracker when you start. Conduct the whole ticket in this session: run each stage as a subagent and tell me its result here. Work on no other ticket. Ask me before you push or open the pull request.",
  ].filter(Boolean);
  return [`/implement ${row.id}`, "", ...context].join("\n");
}

/** The ticket's repo, or every repo of a ticket that owns several in their merge order. */
function repoLine(row: TicketRow): string {
  const repos = row.repos;
  if (repos.length > 1) {
    return `Repos, in the order their pull requests merge: ${repos.join(", then ")}.`;
  }
  return row.repo ? `Repo: ${row.repo}.` : "";
}

/**
 * Starts a Claude session in the hub folder that works the ticket (`ticketPrompt`), then opens its
 * chat. Disabled, with the reason, when this machine cannot drive Claude or the hub has no folder.
 */
export function StartTicketButton({
  project,
  slug,
  row,
  rows,
  quiet = false,
}: {
  project: string;
  slug: string;
  row: TicketRow & { id: string };
  rows: readonly TicketRow[];
  /** Not the view's primary: a plan change request waits for the owner first (U7). */
  quiet?: boolean;
}) {
  const start = useHubSessionStart(project);
  const create = useCreateAgentSession();
  const navigate = useNavigate();
  const base = stackedOn(row, rows);
  const [asking, setAsking] = useState(false);
  const label = base
    ? `Start ${row.id} on ${base.id}'s branch (${base.id} is in review, not merged)`
    : `Start ${row.id}`;
  const variant = base || quiet ? "default" : "primary";

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
          variant={variant}
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
    <>
      <Tooltip
        label={
          failed
            ? `Could not start: ${failed}`
            : base
              ? `${base.id} is in review, not merged. Start one Claude session that conducts ${row.id} on its branch: context, preflight, build, review and eval as its own subagents, each reported in its chat. It asks you before a stacked pull request.`
              : `Start one Claude session that conducts ${row.id}: context, preflight, build, review and eval as its own subagents, each reported in its chat. It asks you before the pull request.`
        }
      >
        <Button
          size="sm"
          variant={variant}
          icon="play"
          aria-label={label}
          disabled={create.isPending}
          onClick={() => {
            if (base) setAsking(true);
            else void begin();
          }}
        >
          {create.isPending ? "Starting…" : failed ? "Retry" : "Start"}
        </Button>
      </Tooltip>
      {base && asking && (
        <ConfirmDialog
          title={`Start ${row.id} on ${base.id}'s branch?`}
          tone="primary"
          consequences={[
            `${base.id} is in review and not merged: its code may still change.`,
            `The worktree starts from ${base.id}'s pull request branch, and ${row.id}'s pull request targets that branch.`,
            `If ${base.id} changes, the session rebases onto it; once it merges, rebase onto the default branch and retarget.`,
          ]}
          confirmLabel={create.isPending ? "Starting…" : `Start ${row.id}`}
          pending={create.isPending}
          onCancel={() => {
            setAsking(false);
          }}
          onConfirm={() => {
            void begin().finally(() => {
              setAsking(false);
            });
          }}
        />
      )}
    </>
  );
}
