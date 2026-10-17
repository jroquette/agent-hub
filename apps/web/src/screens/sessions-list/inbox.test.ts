import { describe, expect, it } from "vitest";

import {
  aPermissionRequest,
  aSession,
  aSessionLabel,
  anAgentSession,
  anId,
  at,
} from "../../testing/builders";
import {
  commonRepoOf,
  filesToReview,
  orderRows,
  rowTitle,
  rowView,
  summaryOf,
  type ViewContext,
} from "./inbox";
import type { AgentSession, Session } from "./queries";
import type { SectionId, SectionRow } from "./sections";

const NEEDS = (n: number) => ({ by_you: 0, handled: 0, needs_you: n, open: n });
/** An observed terminal session (no driven twin) in the common repo, on a quiet branch. */
const observed = (overrides: Partial<Session> = {}) =>
  aSession({ label: aSessionLabel({ branch: "HEAD" }), ...overrides });
const ctx = (
  group: SectionId,
  drv: AgentSession | null = null,
  extra: Partial<ViewContext> = {},
): ViewContext => ({ group, drv, commonRepo: "agent-hub", showProject: false, ...extra });
const view = (row: SectionRow, group: SectionId, drv: AgentSession | null = null) =>
  rowView(row, ctx(group, drv));

describe("rowView: Needs you", () => {
  it("says what a driven session asks to use, with Answer, timed when it asked", () => {
    const ask = aPermissionRequest({ tool: "Bash", summary: "make playground-export" });
    const drv = anAgentSession({ status: "waiting_permission", open_permission: ask });
    expect(view(drv, "waiting", drv)).toMatchObject({
      lead: { icon: "hand", tone: "waiting" },
      line: "Asks to use Bash: make playground-export",
      action: "answer",
      time: ask.asked_at,
      timeTip: "Asked",
    });
  });

  it("says a driven session or a twin asks for a permission when the ask is not loaded", () => {
    const drv = anAgentSession({ status: "waiting_permission" });
    expect(view(drv, "waiting", drv).line).toBe("Asks for a permission");
    const twin = observed({ status: "waiting", agent_session_id: drv.id });
    expect(view(twin, "waiting", drv)).toMatchObject({
      line: "Asks for a permission",
      action: "answer",
    });
  });

  it.each([
    ["Guard ask", "shield-alert", "A guard asks you to confirm · no timeout"],
    ["Permission prompt", "hand", "Asks for a permission in the terminal"],
    ["Idle prompt", "hand", "Idle prompt"],
    [null, "hand", "Waiting for you in the terminal"],
  ])("reads an observed wait for %s", (reason, icon, line) => {
    const row = observed({ status: "waiting", waiting_reason: reason });
    expect(view(row, "waiting")).toMatchObject({
      lead: { icon, tone: "waiting" },
      line,
      action: "answer",
      time: row.last_activity_at,
    });
  });

  it("offers Review problem on an open session with a problem only the owner can fix", () => {
    const named = observed({
      status: "live",
      problems: NEEDS(1),
      needs_you_problem: "Needs you: Bash failed in make check",
    });
    expect(view(named, "waiting")).toMatchObject({
      lead: { icon: "circle-x", tone: "failed" },
      line: "Needs you: Bash failed in make check",
      lineTone: "failed",
      action: "review",
    });
    expect(view(observed({ status: "idle", problems: NEEDS(1) }), "waiting").line).toBe(
      "1 problem needs you",
    );
    expect(view(observed({ status: "idle", problems: NEEDS(3) }), "waiting").line).toBe(
      "3 problems need you",
    );
  });

  it("keeps Answer on a waiting session that also has a problem", () => {
    const row = observed({ status: "waiting", problems: NEEDS(1), waiting_reason: "Guard ask" });
    expect(view(row, "waiting").action).toBe("answer");
  });
});

describe("rowView: Working", () => {
  it("says the last action of an observed session, with the live pulse", () => {
    expect(view(observed({ last_action: "Ran make check" }), "live")).toMatchObject({
      lead: "pulse",
      line: "Ran make check",
      lineTone: null,
      action: null,
      timeTip: "Last activity",
    });
  });

  it("says a failing notice first, in the failed tone", () => {
    const row = observed({ last_action: "Ran make check", failing_notice: "3 tool errors" });
    expect(view(row, "live")).toMatchObject({
      lead: { icon: "circle-x", tone: "failed" },
      line: "3 tool errors",
      lineTone: "failed",
    });
  });

  it("says Starting before any tool, and Working on your message for a chat", () => {
    expect(view(observed({ last_action: null }), "live").line).toBe("Starting");
    const drv = anAgentSession({ status: "running" });
    expect(view(drv, "live", drv)).toMatchObject({
      lead: "pulse",
      line: "Working on your message",
    });
    const twin = observed({ last_action: null, agent_session_id: drv.id });
    expect(view(twin, "live", drv).line).toBe("Working on your message");
  });

  it("times a twin by its latest activity, observed or driven", () => {
    const drv = anAgentSession({ status: "running", updated_at: at(900) });
    const twin = observed({ agent_session_id: drv.id, last_activity_at: at(300) });
    expect(view(twin, "live", drv).time).toBe(at(900));
    expect(view(twin, "live", { ...drv, updated_at: at(100) }).time).toBe(at(300));
  });
});

describe("rowView: In progress", () => {
  it("says the last action of an observed session, or that no tool ran yet, with no lead", () => {
    expect(view(observed({ status: "idle", last_action: "Edited a.ts" }), "idle")).toMatchObject({
      lead: null,
      line: "Edited a.ts",
      action: null,
    });
    expect(view(observed({ status: "idle", last_action: null }), "idle").line).toBe(
      "No tool used yet",
    );
  });

  it("says a twinless chat's mode and model, the model left out when unknown", () => {
    const drv = anAgentSession({ status: "idle", mode: "plan", model: "opus" });
    expect(view(drv, "idle", drv).line).toBe("Plan mode · opus");
    const bare = anAgentSession({ status: "idle", mode: "default", model: null });
    expect(view(bare, "idle", bare).line).toBe("Ask before edits mode");
  });
});

describe("rowView: Finished", () => {
  const ended = (overrides: Partial<Session> = {}) =>
    observed({ status: "ended", ended_at: at(47), ...overrides });

  it.each([
    ["done", "Done · ran 47 s", "circle-check", "done"],
    ["stopped", "Stopped · ran 47 s", "octagon-x", "blocked"],
    ["blocked", "Blocked · Ran make check", "octagon-x", "blocked"],
    ["error", "Failed · Ran make check", "circle-x", "failed"],
  ] as const)("reads the outcome %s as a word, an icon and a fact", (outcome, line, icon, tone) => {
    const row = ended({ outcome, last_action: "Ran make check" });
    expect(view(row, "ended")).toMatchObject({
      lead: { icon, tone },
      line,
      time: at(47),
      timeTip: "Ended",
      action: null,
    });
  });

  it("says a failure's notice over its last action", () => {
    const row = ended({ outcome: "error", failing_notice: "3 tool errors in the last 5 min" });
    expect(view(row, "ended").line).toBe("Failed · 3 tool errors in the last 5 min");
  });

  it("says a pull request over the duration", () => {
    const row = ended({ outcome: "done", pr: { number: 212, state: "MERGED", url: "https://x" } });
    expect(view(row, "ended").line).toBe("Done · PR #212 merged");
  });

  it("says a problem that needs the owner, in the failed tone", () => {
    const row = ended({ outcome: "done", problems: NEEDS(2) });
    expect(view(row, "ended")).toMatchObject({
      lead: { icon: "circle-x", tone: "failed" },
      line: "Done · 2 problems need you",
      lineTone: "failed",
    });
  });

  it("says how a chat closed, its driven end reason winning over the observed outcome", () => {
    const twin = (end_reason: NonNullable<AgentSession["end_reason"]> | null) => {
      const drv = anAgentSession({ status: "ended", end_reason });
      return view(ended({ outcome: "done", agent_session_id: drv.id }), "ended", drv);
    };
    expect(twin("closed")).toMatchObject({
      line: "Closed by you · ran 47 s",
      lead: { icon: "circle-stop", tone: "subtle" },
    });
    expect(twin("idle_timeout").line).toBe("Closed automatically after a pause · ran 47 s");
    expect(twin("server_stopped").line).toBe("Closed when hub web stopped · ran 47 s");
    expect(twin("log_full").line).toBe("Closed: the conversation is full · ran 47 s");
    // No driven end reason: the observed outcome says it.
    expect(twin(null).line).toBe("Done · ran 47 s");
  });

  it("keeps an observed error as Failed over a driven close", () => {
    const drv = anAgentSession({ status: "ended", end_reason: "closed" });
    const row = ended({ outcome: "error", agent_session_id: drv.id });
    expect(view(row, "ended", drv).line).toBe("Failed · ran 47 s");
  });

  it("reads a failed driven session as Failed, and one with no reason as Closed", () => {
    const failed = anAgentSession({ status: "failed", ended_at: at(30) });
    expect(view(failed, "ended", failed)).toMatchObject({
      line: "Failed · ran 30 s",
      lead: { icon: "circle-x", tone: "failed" },
    });
    const closed = anAgentSession({ status: "ended" });
    expect(view(closed, "ended", closed).line).toBe("Closed");
  });

  it("says an assumed close with the dashed mark when no end signal arrived", () => {
    const row = ended({ outcome: null, end_inferred: true });
    expect(view(row, "ended")).toMatchObject({
      line: "Closed · ran 47 s",
      lead: { icon: "circle-dashed", tone: "subtle" },
      inferred: true,
    });
    expect(view(ended({ outcome: null }), "ended")).toMatchObject({
      line: "Closed · ran 47 s",
      inferred: false,
    });
  });

  it("says the word only without an end time, timed by the last activity", () => {
    const row = ended({ outcome: "done", ended_at: null });
    expect(view(row, "ended")).toMatchObject({ line: "Done", time: row.last_activity_at });
  });

  it("marks a finished chat resumable unless the log is full or it never got a Claude id", () => {
    const drv = anAgentSession({ status: "ended", end_reason: "closed" });
    expect(view(drv, "ended", drv).resumable).toBe(true);
    const full = anAgentSession({ status: "ended", end_reason: "log_full" });
    expect(view(full, "ended", full).resumable).toBe(false);
    const fresh = anAgentSession({ status: "failed", claude_session_id: null });
    expect(view(fresh, "ended", fresh).resumable).toBe(false);
    // A terminal session has no chat to resume.
    expect(view(ended({ outcome: "done" }), "ended").resumable).toBe(false);
  });
});

describe("rowView: tags", () => {
  it("tags a terminal session, and nothing on a chat in the common repo", () => {
    expect(view(observed(), "live").tags).toEqual(["Terminal"]);
    expect(view(observed({ agent_session_id: anId(9) }), "live").tags).toEqual([]);
  });

  it("tags a run by its issue, else its short id, with its step", () => {
    const run = observed({ run_id: "a1b2c3d4-e5f6-7890", issue: "AGH-9", step: "implement" });
    expect(view(run, "live").tags).toEqual(["Terminal", "Run AGH-9 · implement"]);
    const bare = observed({ run_id: "a1b2c3d4-e5f6-7890", issue: null, step: null });
    expect(view(bare, "live").tags).toEqual(["Terminal", "Run a1b2c3d4"]);
  });

  it("names a repo only when it differs from the common one, and a branch unless HEAD or main", () => {
    const tags = (repo: string, branch: string | null) =>
      view(observed({ agent_session_id: anId(9), label: aSessionLabel({ repo, branch }) }), "live")
        .tags;
    expect(tags("storefront", "HEAD")).toEqual(["storefront"]);
    expect(tags("storefront", "main")).toEqual(["storefront"]);
    expect(tags("storefront", "dev/x")).toEqual(["storefront · dev/x"]);
    expect(tags("agent-hub", "HEAD")).toEqual([]);
    expect(tags("agent-hub", null)).toEqual([]);
    expect(tags("agent-hub", "dev/x")).toEqual(["dev/x"]);
  });

  it("names a chat's folder only when it differs from the common repo", () => {
    const drv = anAgentSession({ workdir_label: "agent-hub-hub" });
    expect(view(drv, "idle", drv).tags).toEqual(["agent-hub-hub"]);
    expect(rowView(drv, ctx("idle", drv, { commonRepo: "agent-hub-hub" })).tags).toEqual([]);
  });

  it("leads with the project when every project shows", () => {
    const row = observed({ project: "loki-trader" });
    expect(rowView(row, ctx("live", null, { showProject: true })).tags).toEqual([
      "loki-trader",
      "Terminal",
    ]);
  });
});

describe("orderRows", () => {
  const rows = [
    observed({ id: anId(1), last_activity_at: at(200) }),
    observed({ id: anId(2), last_activity_at: at(100) }),
    observed({ id: anId(3), last_activity_at: at(300) }),
  ];
  const ids = (list: SectionRow[]) => list.map((row) => row.id);
  const none = () => null;

  it("puts the oldest wait first in Needs you", () => {
    expect(ids(orderRows("waiting", rows, none))).toEqual([anId(2), anId(1), anId(3)]);
  });

  it("puts the latest activity first in Working and In progress, without changing its input", () => {
    expect(ids(orderRows("live", rows, none))).toEqual([anId(3), anId(1), anId(2)]);
    expect(ids(orderRows("idle", rows, none))).toEqual([anId(3), anId(1), anId(2)]);
    expect(ids(rows)).toEqual([anId(1), anId(2), anId(3)]);
  });

  it("orders Finished by its end, else its last activity, newest first", () => {
    const ended = [
      observed({ id: anId(1), ended_at: at(100), last_activity_at: at(100) }),
      observed({ id: anId(2), ended_at: null, last_activity_at: at(500) }),
      observed({ id: anId(3), ended_at: at(900), last_activity_at: at(900) }),
    ];
    expect(ids(orderRows("ended", ended, none))).toEqual([anId(3), anId(2), anId(1)]);
  });

  it("times a twin by its driven session when that is later, and a chat by its update", () => {
    const drv = anAgentSession({ id: anId(7, "0192a5e5"), updated_at: at(1000) });
    const twin = observed({ id: anId(4), agent_session_id: drv.id, last_activity_at: at(50) });
    const chat = anAgentSession({ id: anId(8, "0192a5e5"), updated_at: at(250) });
    const drvOf = (row: SectionRow) =>
      row.id === anId(4) ? drv : row.id === chat.id ? chat : null;
    expect(ids(orderRows("live", [...rows, twin, chat], drvOf))).toEqual([
      anId(4),
      anId(3),
      chat.id,
      anId(1),
      anId(2),
    ]);
  });

  it("keeps the given order between rows timed alike", () => {
    const alike = [observed({ id: anId(1) }), observed({ id: anId(2) })];
    expect(ids(orderRows("live", alike, none))).toEqual([anId(1), anId(2)]);
  });
});

describe("commonRepoOf", () => {
  it("is the repo most loaded rows share, a chat counted by its folder", () => {
    const repo = (name: string) => observed({ label: aSessionLabel({ repo: name }) });
    const chat = (folder: string) => anAgentSession({ workdir_label: folder });
    expect(commonRepoOf([repo("a"), repo("b"), repo("b"), chat("a"), chat("a")])).toBe("a");
    expect(commonRepoOf([repo("a"), repo("b"), repo("b")])).toBe("b");
  });

  it("reads the session's repo without a label, the first one on a tie, and none without rows", () => {
    expect(commonRepoOf([observed({ label: null, repo: "storefront" })])).toBe("storefront");
    expect(
      commonRepoOf([
        observed({ label: aSessionLabel({ repo: "x" }) }),
        observed({ label: aSessionLabel({ repo: "y" }) }),
      ]),
    ).toBe("x");
    expect(commonRepoOf([])).toBeNull();
  });
});

describe("rowTitle", () => {
  it("is a chat's title or Untitled session, and an observed session's identity", () => {
    expect(rowTitle(anAgentSession({ title: "Fix the build" }))).toBe("Fix the build");
    expect(rowTitle(anAgentSession({ title: null }))).toBe("Untitled session");
    expect(rowTitle(observed({ label: aSessionLabel({ title: "Readable names" }) }))).toBe(
      "Readable names",
    );
    expect(
      rowTitle(observed({ label: aSessionLabel({ issue: "AGH-9", workflow: "/feature" }) })),
    ).toBe("AGH-9 · /feature");
  });
});

describe("the conversation of a chat", () => {
  const drv = anAgentSession({
    status: "idle",
    last_prompt: "Make the list less minimal",
    last_reply: "Done: rows show your ask and my reply",
    changed_files: [
      { path: "/repo/a.ts", last_change_id: "toolu_2" },
      { path: "/repo/b.ts", last_change_id: "toolu_1" },
    ],
  });

  it("shows your last ask and Claude's last reply in Working and In progress", () => {
    expect(view(drv, "idle", drv).conversation).toEqual({
      prompt: "Make the list less minimal",
      reply: "Done: rows show your ask and my reply",
    });
    const twin = observed({ status: "live", agent_session_id: drv.id, last_action: "Ran make" });
    expect(view(twin, "live", drv)).toMatchObject({
      conversation: { prompt: "Make the list less minimal" },
      line: "Ran make",
    });
  });

  it("keeps the one-line view when the chat has no ask or reply yet, and outside those groups", () => {
    const bare = anAgentSession({ status: "idle", last_prompt: null, last_reply: null });
    expect(view(bare, "idle", bare).conversation).toBeNull();
    expect(view(observed({ status: "idle" }), "idle").conversation).toBeNull();
    const ended = anAgentSession({ ...drv, status: "ended", ended_at: at(900) });
    expect(view(ended, "ended", ended).conversation).toBeNull();
  });

  it("counts the files changed since you last viewed them in the chat", () => {
    const { files } = summaryOf(drv);
    expect(filesToReview(files, {})).toEqual({ total: 2, toReview: 2 });
    expect(filesToReview(files, { "/repo/a.ts": "toolu_2", "/repo/b.ts": "toolu_0" })).toEqual({
      total: 2,
      toReview: 1,
    });
    expect(filesToReview([], {})).toEqual({ total: 0, toReview: 0 });
  });
});
