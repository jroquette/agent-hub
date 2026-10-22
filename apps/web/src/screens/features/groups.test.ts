import { describe, expect, it } from "vitest";

import {
  aFeature,
  aGoldenPath,
  aGoldenStep,
  aLiveTile,
  aSessionLabel,
  at,
} from "../../testing/builders";
import { NEEDS_ORDER, byGroupOrder, reasonOf, sessionWaitOf } from "./groups";

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

    expect(reasonOf(shipped, wait)).toMatchObject({ group: "shipped", needs: null });
  });

  // two-level-flows A17: a sign-off only the owner can write by hand needs the owner, with no button.
  it("counts a hand-written sign-off as needing you (A17)", () => {
    const unlisted = aFeature({
      phase: "acceptance",
      verdict: "SHIP-WITH-OWNER-STEPS",
      waiting_on_owner: { kind: "owner_signoff_manual", tickets: [] },
    });

    expect(reasonOf(unlisted)).toMatchObject({
      group: "progress",
      needs: "owner-manual",
      icon: "hand",
      line: "Sign off by hand · no ACs listed",
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

    expect(reasonOf(waiting)).toMatchObject({ group: "progress", needs: null });
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
  it("leads with a waiting session, your turn, a broken record, NO-SHIP, a plan change, owner steps, a hand sign-off, then the rest", () => {
    const owner = aFeature({
      slug: "a-owner",
      phase: "acceptance",
      verdict: "SHIP-WITH-OWNER-STEPS",
      waiting_on_owner: { kind: "owner_signoff", tickets: [] },
    });
    const change = aFeature({
      slug: "a-plan",
      waiting_on_owner: { kind: "change_request", tickets: ["DEM-8"] },
    });
    const manual = aFeature({
      slug: "a-manual",
      phase: "acceptance",
      waiting_on_owner: { kind: "owner_signoff_manual", tickets: [] },
    });
    const noShip = aFeature({ slug: "b-no-ship", verdict: "NO-SHIP" });
    const broken = aFeature({ slug: "c-broken", phase: "spec", problem: "features.json is empty" });
    const turn = aFeature({ slug: "d-turn", issues: ["AGH-2"] });
    const session = aFeature({ slug: "e-session", phase: "spec", issues: ["AGH-1"] });
    const plain = aFeature({ slug: "f-plain", phase: "acceptance" });
    const tiles = [
      aLiveTile({ id: "s-1", group: "waiting", label: aSessionLabel({ issue: "AGH-1" }) }),
      aLiveTile({ id: "s-2", group: "idle", label: aSessionLabel({ issue: "AGH-2" }) }),
    ];
    const reason = (f: typeof plain) => reasonOf(f, sessionWaitOf(f, tiles));

    const sorted = [plain, manual, owner, change, noShip, broken, turn, session].sort((a, b) =>
      byGroupOrder(a, b, reason),
    );

    expect(sorted.map((f) => reason(f).needs)).toEqual([...NEEDS_ORDER, null]);
    expect(sorted.map((f) => f.slug)).toEqual([
      "e-session",
      "d-turn",
      "c-broken",
      "b-no-ship",
      "a-plan",
      "a-owner",
      "a-manual",
      "f-plain",
    ]);
  });
});
