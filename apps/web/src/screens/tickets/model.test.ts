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
  it("groups the sessions of one issue into one row, the newest session first (AC-426.2)", () => {
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

  it("leaves out the tickets a feature plans and the ones the feature path worked on (AC-426.3)", () => {
    const planned = fixSession("a");
    const featurePath = aSession({
      id: "b",
      label: aSessionLabel({ issue: "AGH-9", workflows: ["/feature"] }),
    });
    expect(ticketsOf([planned, featurePath], new Set(["AGH-7"]))).toEqual([]);
  });

  it("leaves out sessions with no issue (AC-426.2)", () => {
    expect(
      ticketsOf(
        [fixSession("a", { label: aSessionLabel({ issue: null, workflows: [] }) })],
        new Set(),
      ),
    ).toEqual([]);
  });

  it("puts a ticket with a waiting session under Needs you, a live one under In progress (AC-426.4)", () => {
    const waiting = ticketsOf([fixSession("a", { status: "waiting" })], new Set());
    const live = ticketsOf([fixSession("a", { status: "live" })], new Set());
    expect(waiting[0]?.group).toBe("needs");
    expect(live[0]?.group).toBe("active");
  });

  it("names the kind by the skill, a hub run, else other (AC-426.6)", () => {
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

  it("finds a row by its issue, repo or skill (AC-426.7)", () => {
    const [row] = ticketsOf([fixSession("a")], new Set());
    if (!row) throw new Error("no row");
    expect(matchesQuery(row, "agh-7")).toBe(true);
    expect(matchesQuery(row, "/fix")).toBe(true);
    expect(matchesQuery(row, "nothing")).toBe(false);
  });

  it("leaves out a ticket the feature's ticket flow worked on (AC-426.3)", () => {
    const implement = aSession({
      id: "a",
      label: aSessionLabel({ issue: "AGH-11", workflows: ["/implement"] }),
    });
    expect(ticketsOf([implement], new Set())).toEqual([]);
  });

  it("groups one issue per project, in upper case, and keeps routine commands out of its skills (AC-426.2, AC-426.6)", () => {
    const rows = ticketsOf(
      [
        fixSession("a", {
          label: aSessionLabel({ issue: "agh-7", workflows: ["/kickoff", "/learn", "/refactor"] }),
        }),
        fixSession("b", { project: "demo-shop" }),
      ],
      new Set(),
    );
    expect(rows.map((row) => [row.project, row.issue, row.kind, row.workflows])).toEqual(
      expect.arrayContaining([
        ["agent-hub", "AGH-7", "refactor", ["/refactor"]],
        ["demo-shop", "AGH-7", "fix", ["/fix"]],
      ]),
    );
  });

  it("sums the cost and keeps the newest pull request (AC-426.5)", () => {
    const pr = { number: 41, state: "open", url: "https://github.com/acme/app/pull/41" };
    const [row] = ticketsOf(
      [
        fixSession("a", { cost_usd: "1.00", last_activity_at: "2026-10-20T10:00:00Z" }),
        fixSession("b", {
          cost_usd: "0.25",
          last_activity_at: "2026-10-20T11:00:00Z",
          pr,
        }),
      ],
      new Set(),
    );
    expect(row?.costUsd).toBeCloseTo(1.25);
    expect(row?.pr?.number).toBe(41);
  });
});
