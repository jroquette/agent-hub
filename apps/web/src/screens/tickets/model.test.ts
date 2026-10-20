import { describe, expect, it } from "vitest";

import { aSession, aSessionLabel } from "../../testing/builders";
import { matchesQuery, ticketsOf, type Session } from "./model";

const fixSession = (id: string, overrides: Partial<Session> = {}): Session =>
  aSession({
    id,
    issue: null,
    label: aSessionLabel({ issue: "AGH-7", workflow: "/fix", workflows: ["/kickoff", "/fix"] }),
    ...overrides,
  });

describe("ticketsOf", () => {
  it("groups the sessions of one issue into one row, the newest session first", () => {
    const rows = ticketsOf(
      [
        fixSession("a", { last_activity_at: "2026-10-20T10:00:00Z", status: "ended" }),
        fixSession("b", { last_activity_at: "2026-10-20T11:00:00Z", status: "ended" }),
      ],
      new Set(),
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      issue: "AGH-7",
      kind: "fix",
      workflows: ["/fix"],
      sessions: 2,
      group: "done",
    });
    expect(rows[0]?.latest.id).toBe("b");
  });

  it("leaves out the tickets a feature plans and the ones the feature path worked on", () => {
    const planned = fixSession("a");
    const featurePath = aSession({
      id: "b",
      label: aSessionLabel({ issue: "AGH-9", workflows: ["/feature"] }),
    });
    expect(ticketsOf([planned, featurePath], new Set(["AGH-7"]))).toEqual([]);
  });

  it("leaves out sessions with no issue", () => {
    expect(
      ticketsOf(
        [fixSession("a", { label: aSessionLabel({ issue: null, workflows: [] }) })],
        new Set(),
      ),
    ).toEqual([]);
  });

  it("puts a ticket with a waiting session under Needs you, a live one under In progress", () => {
    const waiting = ticketsOf([fixSession("a", { status: "waiting" })], new Set());
    const live = ticketsOf([fixSession("a", { status: "live" })], new Set());
    expect(waiting[0]?.group).toBe("needs");
    expect(live[0]?.group).toBe("active");
  });

  it("names the kind by the skill, a hub run, else other", () => {
    const upgrade = fixSession("a", {
      label: aSessionLabel({ issue: "AGH-7", workflows: ["/upgrade"] }),
    });
    const run = fixSession("b", {
      run_id: "run-1",
      label: aSessionLabel({ issue: "AGH-8", workflows: [] }),
    });
    const other = fixSession("c", { label: aSessionLabel({ issue: "AGH-9", workflows: [] }) });
    const kinds = Object.fromEntries(
      ticketsOf([upgrade, run, other], new Set()).map((row) => [row.issue, row.kind]),
    );
    expect(kinds).toEqual({ "AGH-7": "upgrade", "AGH-8": "run", "AGH-9": "other" });
  });

  it("finds a row by its issue, repo or skill", () => {
    const [row] = ticketsOf([fixSession("a")], new Set());
    if (!row) throw new Error("no row");
    expect(matchesQuery(row, "agh-7")).toBe(true);
    expect(matchesQuery(row, "/fix")).toBe(true);
    expect(matchesQuery(row, "nothing")).toBe(false);
  });
});
