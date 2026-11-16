import { describe, expect, it } from "vitest";

import {
  aFeature,
  aGoldenPath,
  aGoldenStep,
  aLiveTile,
  aSessionLabel,
  at,
} from "../../testing/builders";
import {
  GROUPS,
  QUIET_DAYS,
  agoWords,
  byGroupOrder,
  daysAgo,
  lastActivityOf,
  reasonOf,
  sessionWaitOf,
  sessionsWorkingOn,
} from "./groups";

const feature = aFeature({ slug: "claims", issues: ["AGH-300", "AGH-301 (provisional)"] });

describe("sessionWaitOf", () => {
  it("prefers a session waiting on a permission over one whose turn ended, then the newest", () => {
    const oldWait = aLiveTile({
      id: "s-old",
      group: "waiting",
      label: aSessionLabel({ issue: "AGH-300" }),
      last_activity_at: at(60),
    });
    const newWait = aLiveTile({
      id: "s-new",
      group: "waiting",
      label: aSessionLabel({ issue: "agh-301" }),
      last_activity_at: at(120),
    });
    const newestTurn = aLiveTile({
      id: "s-turn",
      group: "idle",
      label: aSessionLabel({ issue: "AGH-300" }),
      last_activity_at: at(600),
    });

    expect(sessionWaitOf(feature, [oldWait, newestTurn, newWait])).toEqual({
      tile: newWait,
      group: "waiting",
    });
    expect(sessionWaitOf(feature, [newestTurn])?.group).toBe("idle");
  });

  it("ignores subagents, busy sessions and sessions on other work", () => {
    const subagent = aLiveTile({
      group: "waiting",
      is_subagent: true,
      label: aSessionLabel({ issue: "AGH-300" }),
    });
    const busy = aLiveTile({ group: "live", label: aSessionLabel({ issue: "AGH-300" }) });
    const other = aLiveTile({ group: "waiting", label: aSessionLabel({ issue: "AGH-999" }) });

    expect(sessionWaitOf(feature, [subagent, busy, other])).toBeNull();
  });

  it("reads the tile's issue when its label names none, and a title that names the feature", () => {
    const byTile = aLiveTile({ group: "waiting", issue: "AGH-300", label: null });
    const byTitle = aLiveTile({
      group: "idle",
      issue: null,
      label: aSessionLabel({ issue: null, title: "claims: answer the reviewer" }),
    });

    expect(sessionWaitOf(feature, [byTile])?.tile).toBe(byTile);
    expect(sessionWaitOf(feature, [byTitle])?.tile).toBe(byTitle);
  });
});

describe("reasonOf", () => {
  it("does not flag a shipped feature whose session waits on you", () => {
    const shipped = aFeature({ phase: "shipped", golden_path: aGoldenPath({ phase: "shipped" }) });
    const wait = { tile: aLiveTile({ group: "waiting" }), group: "waiting" as const };

    expect(reasonOf(shipped, wait)).toMatchObject({ group: "done", needs: null });
  });

  // two-level-flows A17: a sign-off only the owner can write by hand waits to be closed, not on you.
  it("puts a hand-written sign-off in Ready to close and opens the eval (A17)", () => {
    const unlisted = aFeature({
      phase: "acceptance",
      verdict: "SHIP-WITH-OWNER-STEPS",
      waiting_on_owner: { kind: "owner_signoff_manual", tickets: [] },
    });

    expect(reasonOf(unlisted)).toMatchObject({
      group: "ready",
      needs: null,
      icon: "hand",
      line: "Evaluator says ship after your checks · no ACs listed, mark it shipped or close it",
      doc: "eval",
    });
  });

  // two-level-flows AC-2.8: a plan change request ranks the feature in Needs you, from its ticket.
  it("names the asking tickets when a plan change waits for you (AC-2.8)", () => {
    const one = aFeature({ waiting_on_owner: { kind: "change_request", tickets: ["DEM-8"] } });
    const two = aFeature({
      waiting_on_owner: { kind: "change_request", tickets: ["DEM-8", "DEM-9"] },
    });

    expect(reasonOf(one)).toMatchObject({
      needs: "change-request",
      icon: "hand",
      tone: "waiting",
      line: "Plan change waits for you · from DEM-8",
      doc: "tickets&ticket=DEM-8&step=preflight",
    });
    expect(reasonOf(two).line).toBe("2 plan changes wait for you · from DEM-8, DEM-9");
  });

  // P5 retired: only the typed wait ranks a feature, never the step's words.
  it("does not count an Acceptance meta that reads like a wait without the typed wait", () => {
    const worded = aFeature({
      phase: "acceptance",
      golden_path: aGoldenPath({
        phase: "acceptance",
        steps: [
          aGoldenStep({
            name: "acceptance",
            state: "current",
            meta: "Waiting for you: sign off 2 ACs",
            progress: null,
          }),
        ],
      }),
    });

    expect(reasonOf(worded).needs).toBeNull();
  });

  // two-level-flows A12, A15 (AGH-330 Q10): no sign-off can be recorded yet, so no Needs you.
  it.each([
    "Acceptance eval undated · evaluate again",
    "Sign-off possible after 21 Nov 2026, 09:01:00 UTC",
  ])("does not count %s as needing you", (meta) => {
    const waiting = aFeature({
      phase: "acceptance",
      verdict: "SHIP-WITH-OWNER-STEPS",
      golden_path: aGoldenPath({
        phase: "acceptance",
        steps: [aGoldenStep({ name: "acceptance", state: "current", meta, progress: null })],
      }),
    });

    expect(reasonOf(waiting)).toMatchObject({ group: "active", needs: null });
  });

  it("names a permission prompt when the waiting session gives no reason", () => {
    const wait = {
      tile: aLiveTile({ group: "waiting", waiting_reason: null }),
      group: "waiting" as const,
    };

    expect(reasonOf(feature, wait)).toMatchObject({
      needs: "session",
      tone: "waiting",
      line: "A session waits on you · a permission prompt",
      doc: null,
    });
  });
});

describe("byGroupOrder", () => {
  it("leads Needs you with a waiting session, your turn, a broken record, NO-SHIP, then a plan change", () => {
    const change = aFeature({
      slug: "a-plan",
      waiting_on_owner: { kind: "change_request", tickets: ["DEM-8"] },
    });
    const noShip = aFeature({ slug: "b-no-ship", verdict: "NO-SHIP" });
    const broken = aFeature({ slug: "c-broken", phase: "spec", problem: "features.json is empty" });
    const turn = aFeature({ slug: "d-turn", issues: ["AGH-2"] });
    const session = aFeature({ slug: "e-session", phase: "spec", issues: ["AGH-1"] });
    const tiles = [
      aLiveTile({ id: "s-1", group: "waiting", label: aSessionLabel({ issue: "AGH-1" }) }),
      aLiveTile({ id: "s-2", group: "idle", label: aSessionLabel({ issue: "AGH-2" }) }),
    ];
    const reason = (f: typeof change) => reasonOf(f, sessionWaitOf(f, tiles));

    const sorted = [change, noShip, broken, turn, session].sort((a, b) =>
      byGroupOrder(a, b, reason),
    );

    expect(sorted.map((f) => reason(f).group)).toEqual(Array<string>(5).fill("needs"));
    expect(sorted.map((f) => reason(f).needs)).toEqual([
      "session",
      "your-turn",
      "problem",
      "no-ship",
      "change-request",
    ]);
    expect(sorted.map((f) => f.slug)).toEqual([
      "e-session",
      "d-turn",
      "c-broken",
      "b-no-ship",
      "a-plan",
    ]);
  });

  it("orders rows of one group by the newest activity first, then furthest along", () => {
    const older = aFeature({ slug: "a-older", phase: "build", last_activity_on: "2026-10-01" });
    const newer = aFeature({ slug: "b-newer", phase: "spec", last_activity_on: "2026-10-09" });
    const undated = aFeature({ slug: "c-undated", phase: "plan" });
    const ahead = aFeature({ slug: "d-ahead", phase: "acceptance" });
    const activity = (f: typeof older) => f.last_activity_on ?? null;

    const sorted = [undated, older, ahead, newer].sort((a, b) =>
      byGroupOrder(a, b, reasonOf, activity),
    );

    expect(sorted.map((f) => f.slug)).toEqual(["b-newer", "a-older", "d-ahead", "c-undated"]);
  });
});

describe("sessions working on a feature", () => {
  const working = aLiveTile({
    id: "s-work",
    group: "live",
    label: aSessionLabel({ issue: "AGH-300" }),
    last_action: "Edited groups.ts",
    last_activity_at: at(60),
  });

  it("keeps the live main sessions of the feature, the most recent first", () => {
    const newer = aLiveTile({
      id: "s-newer",
      group: "live",
      label: aSessionLabel({ issue: null, title: "claims follow-up" }),
      last_activity_at: at(120),
    });
    const subagent = aLiveTile({
      id: "s-sub",
      group: "live",
      is_subagent: true,
      label: aSessionLabel({ issue: "AGH-300" }),
    });
    const waiting = aLiveTile({
      id: "s-wait",
      group: "waiting",
      label: aSessionLabel({ issue: "AGH-300" }),
    });
    const other = aLiveTile({
      id: "s-other",
      group: "live",
      label: aSessionLabel({ issue: "AGH-999" }),
    });

    expect(sessionsWorkingOn(feature, [working, subagent, waiting, other, newer])).toEqual([
      newer,
      working,
    ]);
  });

  it("says a session is working on the line, and keeps the next step for the tooltip", () => {
    const plain = reasonOf(feature);
    const reason = reasonOf(feature, null, [working]);

    expect(reason).toMatchObject({ needs: null, working: 1, plainLine: plain.line });
    expect(reason.line).toBe("A session is working · Edited groups.ts");
    expect(reasonOf(feature, null, [working, working]).line).toBe(
      "2 sessions are working · Edited groups.ts",
    );
  });

  it("lets a warning that needs you keep its line", () => {
    const wait = sessionWaitOf(feature, [
      aLiveTile({ group: "waiting", label: aSessionLabel({ issue: "AGH-300" }) }),
    ]);

    const reason = reasonOf(feature, wait, [working]);

    expect(reason.needs).toBe("session");
    expect(reason.working).toBe(1);
    expect(reason.line).toBe(reason.plainLine);
  });

  it("sorts a working feature after the session warnings and before the other warnings", () => {
    const turn = aFeature({ slug: "c-turn", issues: ["AGH-2"] });
    const busy = aFeature({ slug: "b-busy", phase: "spec", issues: ["AGH-3"] });
    const broken = aFeature({ slug: "a-broken", problem: "features.json is empty" });
    const ahead = aFeature({ slug: "a-ahead", phase: "acceptance" });
    const tiles = [
      aLiveTile({ id: "s-2", group: "idle", label: aSessionLabel({ issue: "AGH-2" }) }),
      aLiveTile({ id: "s-3", group: "live", label: aSessionLabel({ issue: "AGH-3" }) }),
    ];
    const reason = (f: typeof turn) =>
      reasonOf(f, sessionWaitOf(f, tiles), sessionsWorkingOn(f, tiles));

    const sorted = [ahead, broken, busy, turn].sort((a, b) => byGroupOrder(a, b, reason));

    expect(sorted.map((f) => f.slug)).toEqual(["c-turn", "b-busy", "a-broken", "a-ahead"]);
  });
});

describe("the six groups", () => {
  const NOW = Date.parse("2026-11-14T12:00:00Z");
  const demo = (overrides: Parameters<typeof aFeature>[0] = {}) =>
    aFeature({ project: "demo", repos: ["demo-api"], slug: "checkout", ...overrides });
  const groupOf = (f: ReturnType<typeof demo>, wait: Parameters<typeof reasonOf>[1] = null) =>
    reasonOf(f, wait, [], f.last_activity_on ?? null, NOW).group;

  it("lists the groups in order, with Quiet, Paused and Shipped and closed folded", () => {
    expect(GROUPS.map((g) => [g.title, g.folded])).toEqual([
      ["Needs you", false],
      ["Active", false],
      ["Ready to close", false],
      ["Quiet", true],
      ["Paused", true],
      ["Shipped and closed", true],
    ]);
  });

  it.each([
    ["shipped", "done", "circle-check", "Shipped by you on 2026-11-02 · Released to demo-shop"],
    [
      "closed",
      "done",
      "circle-stop",
      "Closed without shipping by you on 2026-11-02 · Released to demo-shop",
    ],
    ["paused", "paused", "circle-pause", "Paused by you on 2026-11-02 · Released to demo-shop"],
  ] as const)(
    "puts a feature the owner marked %s in its group, whatever its records say",
    (status, group, icon, line) => {
      const decided = demo({
        verdict: "NO-SHIP",
        problem: "features.json is empty",
        waiting_on_owner: { kind: "change_request", tickets: ["DEM-8"] },
        owner_status: { status, decided_at: "2026-11-02T10:00:00Z", note: "Released to demo-shop" },
      });
      const wait = { tile: aLiveTile({ group: "waiting" }), group: "waiting" as const };

      expect(reasonOf(decided, wait, [], null, NOW)).toMatchObject({
        group,
        needs: null,
        icon,
        line,
        doc: null,
      });
    },
  );

  it("puts a feature its records show shipped in Shipped and closed", () => {
    expect(
      groupOf(demo({ phase: "shipped", golden_path: aGoldenPath({ phase: "shipped" }) })),
    ).toBe("done");
  });

  it.each([
    ["a session waits on a permission", demo(), "waiting"],
    ["it is your turn in a session", demo(), "idle"],
    [
      "a plan change waits",
      demo({ waiting_on_owner: { kind: "change_request", tickets: ["DEM-8"] } }),
      null,
    ],
    ["the evaluator says NO-SHIP", demo({ verdict: "NO-SHIP" }), null],
    ["a record is broken", demo({ problem: "features.json is empty" }), null],
  ] as const)("puts a feature in Needs you when %s", (_why, f, session) => {
    const wait = session ? { tile: aLiveTile({ group: session }), group: session } : null;

    expect(groupOf(f, wait)).toBe("needs");
  });

  it.each([
    [
      "the evaluator says SHIP and every AC passes",
      demo({ verdict: "SHIP", acs: { owner_steps: 0, passing: 9, total: 9 } }),
    ],
    [
      "the evaluator says ship after the owner's steps, the rest passing",
      demo({ verdict: "SHIP-WITH-OWNER-STEPS", acs: { owner_steps: 2, passing: 7, total: 9 } }),
    ],
    [
      "the owner's sign-off waits",
      demo({ phase: "acceptance", waiting_on_owner: { kind: "owner_signoff", tickets: [] } }),
    ],
    [
      "the owner's hand sign-off waits",
      demo({
        phase: "acceptance",
        waiting_on_owner: { kind: "owner_signoff_manual", tickets: [] },
      }),
    ],
  ] as const)("puts a feature in Ready to close when %s", (_why, f) => {
    expect(groupOf(f)).toBe("ready");
  });

  it("names the checks left and opens the criteria for an owner sign-off in Ready to close", () => {
    const held = demo({
      phase: "acceptance",
      acs: { owner_steps: 2, passing: 7, total: 9 },
      waiting_on_owner: { kind: "owner_signoff", tickets: [] },
    });

    expect(reasonOf(held, null, [], null, NOW)).toMatchObject({
      group: "ready",
      needs: null,
      tone: null,
      line: "Sign off 2 checks of yours, or close it",
      doc: "acs",
    });
  });

  it("keeps a ship verdict whose ACs do not all pass in Active", () => {
    expect(groupOf(demo({ verdict: "SHIP", acs: { owner_steps: 0, passing: 7, total: 9 } }))).toBe(
      "active",
    );
  });

  it(`puts a feature with no activity for ${String(QUIET_DAYS)} days or more in Quiet, saying how long`, () => {
    const quiet = demo({ last_activity_on: "2026-10-31" });

    expect(reasonOf(quiet, null, [], "2026-10-31", NOW)).toMatchObject({
      group: "quiet",
      line: "No activity for 14 days · Building · 1 of 3 tickets merged",
    });
    expect(groupOf(demo({ last_activity_on: "2026-11-01" }))).toBe("active");
  });

  it("keeps an old feature a session works on now in Active", () => {
    const old = demo({ last_activity_on: "2026-09-01" });
    const live = aLiveTile({ group: "live" });

    expect(reasonOf(old, null, [live], "2026-09-01", NOW).group).toBe("active");
  });

  it("keeps an old feature that needs you in Needs you, not Quiet", () => {
    expect(groupOf(demo({ last_activity_on: "2026-09-01", verdict: "NO-SHIP" }))).toBe("needs");
  });
});

describe("last activity", () => {
  const f = aFeature({ slug: "checkout", issues: ["DEM-3"], last_activity_on: "2026-11-01" });

  it("takes the newest of the records' date and the feature's live sessions", () => {
    const newer = aLiveTile({
      group: "live",
      label: aSessionLabel({ issue: "DEM-3" }),
      last_activity_at: "2026-11-10T08:00:00Z",
    });
    const other = aLiveTile({
      group: "live",
      label: aSessionLabel({ issue: "DEM-9" }),
      last_activity_at: "2026-11-12T08:00:00Z",
    });

    expect(lastActivityOf(f, [newer, other])).toBe("2026-11-10T08:00:00Z");
    expect(lastActivityOf(f, [other])).toBe("2026-11-01");
    expect(lastActivityOf(aFeature())).toBeNull();
  });

  it("says the days since in words", () => {
    const now = Date.parse("2026-11-14T12:00:00Z");

    expect(daysAgo("2026-11-14", now)).toBe(0);
    expect(daysAgo("2026-11-01", now)).toBe(13);
    expect(daysAgo(null, now)).toBeNull();
    expect([0, 1, 13, null].map(agoWords)).toEqual([
      "today",
      "yesterday",
      "13 days ago",
      "no date",
    ]);
  });
});
