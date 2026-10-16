import { describe, expect, it } from "vitest";

import {
  aLiveTile,
  aPermissionRequest,
  aSession,
  aSessionLabel,
  anAgentSession,
  anId,
  at,
} from "../../testing/builders";
import { groupWithin, sortTiles, tileOf, tileOfDriven, troubled, waitingLink } from "./tiles";

const NOW = Date.parse(at(660));
const NO_PROBLEMS = { by_you: 0, handled: 0, needs_you: 0, open: 0 };

describe("tileOf (grid tiles from sessions)", () => {
  it("carries the tile fields of a waiting session: reason, last action, problems, stats, sparkline", () => {
    const tile = tileOf(
      aSession({
        status: "waiting",
        waiting_reason: "Guard ask",
        last_action: "Edit migrations/0007.py",
        last_tool: "Edit",
        last_activity_at: at(600),
        problems: { ...NO_PROBLEMS, needs_you: 1 },
        needs_you_problem: "Needs you: command_exit in make check",
        failing_notice: "make check failed 2 times",
        sparkline_60s: [0, 2, 1],
        guard_denials: 2,
      }),
      NOW,
    );

    expect(tile).toMatchObject({
      status: "waiting",
      reason: "Waiting · Guard ask",
      title: "AGH-48 · /feature",
      detail: "agent-hub · dev/agh-48-live-tiles",
      lastAction: "Waiting 1 min · a guard ask has no timeout",
      lastIcon: "file-pen",
      notice: "make check failed 2 times",
      link: { href: "/approvals", label: "Open approval" },
      problems: "Needs you: command_exit in make check",
      needsYou: true,
      elapsed: 660,
      turns: 5,
      tokens: 6400,
      files: 3,
      cost: 1.25,
      denials: 2,
      activity: [0, 2, 1],
      chat: false,
    });
  });

  it("shows the last action of a live session and no sparkline once it ended", () => {
    const live = tileOf(aSession({ last_action: "make check-fast", sparkline_60s: [1] }), NOW);
    const ended = tileOf(
      aSession({ status: "ended", outcome: "error", ended_at: at(300), sparkline_60s: null }),
      NOW,
    );

    expect(live).toMatchObject({ lastAction: "make check-fast", lastAgo: "1 min ago", link: null });
    expect(ended).toMatchObject({ status: "ended", outcome: "error", elapsed: 300 });
    expect(ended.activity).toBeUndefined();
  });

  it("marks a session hub web drives with the Chat badge and sends its wait to the chat", () => {
    const tile = tileOf(
      aSession({ status: "waiting", agent_session_id: anId(7, "0192aaaa"), tokens: null }),
      NOW,
    );

    expect(tile).toMatchObject({
      chat: true,
      tokens: 0,
      link: { href: `/agent-sessions/${anId(7, "0192aaaa")}`, label: "Open chat" },
    });
  });
});

describe("tileOfDriven (grid tiles from driven sessions without a twin)", () => {
  it.each([
    ["running", "live"],
    ["idle", "idle"],
    ["waiting_permission", "waiting"],
    ["ended", "ended"],
    ["failed", "ended"],
  ] as const)("shows a %s driven session as %s", (status, shown) => {
    expect(tileOfDriven(anAgentSession({ status }), NOW).status).toBe(shown);
  });

  it("asks for the permission in the chat, with blanks for what it does not know", () => {
    const tile = tileOfDriven(
      anAgentSession({
        status: "waiting_permission",
        open_permission: aPermissionRequest({ tool: "Bash", summary: "git status" }),
        updated_at: at(600),
      }),
      NOW,
    );

    expect(tile).toMatchObject({
      title: "Run the tests",
      detail: "agent-hub-hub",
      reason: "Waiting · Bash: git status",
      lastAction: "Asks to run Bash",
      lastAgo: "1 min ago",
      link: { href: `/agent-sessions/${anId(1, "0192a5e5")}`, label: "Open chat" },
      elapsed: 660,
      turns: null,
      files: null,
      tokens: 17,
      cost: 0.0012,
      needsYou: false,
      chat: true,
    });
  });

  it("labels a failed one by its outcome and an untitled one as such", () => {
    const failed = tileOfDriven(
      anAgentSession({ status: "failed", title: null, ended_at: at(120), end_reason: "failed" }),
      NOW,
    );
    const closed = tileOfDriven(
      anAgentSession({ status: "ended", end_reason: "idle_timeout" }),
      NOW,
    );

    expect(failed).toMatchObject({
      title: "Untitled session",
      outcome: "failed",
      outcomeLabel: "failed",
      elapsed: 120,
      link: null,
    });
    expect(closed).toMatchObject({ outcome: "done", outcomeLabel: "idle timeout" });
  });
});

describe("troubled and sorting", () => {
  it("edges a tile in red only when a problem needs the owner", () => {
    expect(troubled(aSession({ problems: { ...NO_PROBLEMS, needs_you: 1 } }))).toBe(true);
    expect(troubled(aSession({ problems: { ...NO_PROBLEMS, handled: 3, open: 1 } }))).toBe(false);
  });

  it("puts idle last, troubled first, then the oldest start first", () => {
    const idle = aSession({ id: anId(1), status: "idle", started_at: at(0) });
    const old = aSession({ id: anId(2), started_at: at(10) });
    const young = aSession({ id: anId(3), started_at: at(20) });
    const sick = aSession({
      id: anId(4),
      started_at: at(30),
      problems: { ...NO_PROBLEMS, needs_you: 1 },
    });

    expect(sortTiles([idle, young, sick, old]).map((s) => s.id)).toEqual([
      anId(4),
      anId(2),
      anId(3),
      anId(1),
    ]);
  });
});

describe("waitingLink", () => {
  it("links a permission prompt of a session hub web drives to its chat", () => {
    const tile = aLiveTile({
      group: "waiting",
      status: "waiting",
      waiting_reason: "Permission prompt",
      agent_session_id: anId(7, "0192aaaa"),
    });

    expect(waitingLink(tile)).toEqual({
      href: `/agent-sessions/${anId(7, "0192aaaa")}`,
      label: "Open chat",
    });
  });

  it("links a hook-observed permission prompt and any other wait to the approvals", () => {
    const prompt = aLiveTile({ status: "waiting", waiting_reason: "Permission prompt" });
    const plan = aLiveTile({ status: "waiting", waiting_reason: "Plan approval" });

    expect(waitingLink(prompt)).toEqual({ href: "/approvals", label: "Open approval" });
    expect(waitingLink(plan)).toEqual({ href: "/approvals", label: "Open approval" });
  });
});

describe("groupWithin (grid sub-groups)", () => {
  const observed = aSession({ id: anId(1), label: aSessionLabel({ workflow: "/feature" }) });
  const driven = anAgentSession({ id: anId(2), workdir_label: "agent-hub-hub" });
  const labels = (within: "repo" | "run" | "workflow") =>
    groupWithin([driven, observed], within).map((group) => [group.label, group.rows.length]);

  it("puts a driven session under its working folder, and with no run or workflow last", () => {
    expect(labels("repo")).toEqual([
      ["agent-hub › agent-hub-hub", 1],
      ["agent-hub › agent-hub", 1],
    ]);
    expect(labels("run")).toEqual([["Not in a run", 2]]);
    expect(labels("workflow")).toEqual([
      ["/feature", 1],
      ["No workflow", 1],
    ]);
  });
});
