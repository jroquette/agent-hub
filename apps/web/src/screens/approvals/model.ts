import type { IconName, Status } from "../../components";
import { fmtDuration } from "../../lib/format";
import type { Approval, ApprovalKind } from "./queries";

/* View models of Approvals (spec 15): kind chips, verbs, waits and the Phase 2 guidance. */

export const KIND: Record<ApprovalKind, { label: string; icon: IconName; verb: string }> = {
  plan: { label: "Plan", icon: "list-checks", verb: "Approve plan" },
  spec: { label: "Spec", icon: "file-text", verb: "Approve spec" },
  human_gate: { label: "Human gate", icon: "stamp", verb: "Pass gate" },
  guard_ask: { label: "Guard ask", icon: "shield-alert", verb: "Allow this edit" },
  permission: { label: "Permission", icon: "shield-check", verb: "Allow this call" },
};

export const KIND_ORDER: readonly ApprovalKind[] = [
  "plan",
  "spec",
  "human_gate",
  "guard_ask",
  "permission",
];

/** True for kinds answered at a permission prompt (yes or no), not a typed reply. */
export function isPrompt(kind: ApprovalKind): boolean {
  return kind === "guard_ask" || kind === "permission";
}

/** Oldest request first: the one blocking longest (spec 15). */
export function oldestFirst(items: readonly Approval[]): Approval[] {
  return [...items].sort((a, b) => Date.parse(a.requested_at) - Date.parse(b.requested_at));
}

/** Seconds an approval has waited (until its decision when decided). */
export function waitedSeconds(approval: Approval, now: number): number {
  const end = approval.decided_at ? Date.parse(approval.decided_at) : now;
  return Math.max(0, (end - Date.parse(approval.requested_at)) / 1000);
}

/** "6 min", "2 h 14 min": whole minutes, at least one. */
export function waitText(seconds: number): string {
  return fmtDuration(Math.max(60, Math.floor(seconds / 60) * 60));
}

/** Amber after an hour; never red, waiting is not failure. */
export const LONG_WAIT_S = 3600;

export function shortId(id: string): string {
  return id.replace(/-/g, "").slice(0, 8);
}

/** The terminal command that answers it: the API's, else built from the hub path and session. */
export function decideCommand(approval: Approval): string | null {
  if (approval.how_to_decide) return approval.how_to_decide;
  if (!approval.hub_path) return null;
  return `cd ${approval.hub_path} && claude --resume ${approval.session_id}`;
}

export const DECISION: Record<Approval["status"], { status: Status; label: string }> = {
  open: { status: "waiting", label: "Waiting" },
  approved: { status: "done", label: "Approved" },
  declined: { status: "failed", label: "Declined" },
  changes_requested: { status: "waiting", label: "Changes requested" },
  rejected: { status: "failed", label: "Rejected" },
};

/** What a yes does, by kind: the process facts that hold for every request of that kind. */
export function consequences(approval: Approval): { icon: IconName; text: string }[] {
  const nothingPushed: { icon: IconName; text: string } = {
    icon: "git-pull-request",
    text: "Nothing is pushed or merged now. A PR is opened after Verify, and you merge it.",
  };
  switch (approval.kind) {
    case "guard_ask":
      return [
        {
          icon: "file-pen",
          text: approval.path
            ? `Allows the pending edit of ${approval.path}.`
            : "Allows the pending edit of a protected path.",
        },
        {
          icon: "shield-check",
          text: "Allows this one edit only. Later edits of protected paths ask again.",
        },
      ];
    case "permission":
      return [
        { icon: "shield-check", text: "Allows this one tool call. The next one asks again." },
      ];
    case "plan":
      return [
        {
          icon: "arrow-right",
          text: "The session continues past plan approval and starts implementing the plan.",
        },
        nothingPushed,
        {
          icon: "circle-x",
          text: "If rejected instead: the work stops at plan approval and the agent gets your reason.",
        },
      ];
    case "spec":
      return [
        {
          icon: "arrow-right",
          text: "The session continues to research and planning with this spec as the target.",
        },
        nothingPushed,
      ];
    case "human_gate":
      return [{ icon: "arrow-right", text: "The run continues past this gate." }, nothingPushed];
  }
}
