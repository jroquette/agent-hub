import { describe, expect, it } from "vitest";

import { SECTIONS, sectionCount, sectionOf, sectionQueries } from "./sections";

const NOW = Date.parse("2026-10-11T14:00:00.000Z");
const queries = (search: string) => sectionQueries(new URLSearchParams(search), "agent-hub", NOW);

describe("status sections (filters-both-views)", () => {
  it("orders the sections needs-me first", () => {
    expect(SECTIONS.map((section) => section.title)).toEqual([
      "Waiting",
      "Live",
      "Idle",
      "Ended or failed",
    ]);
  });

  it("maps observed and driven statuses to their section", () => {
    expect(["waiting", "live", "idle", "ended"].map(sectionOf)).toEqual([
      "waiting",
      "live",
      "idle",
      "ended",
    ]);
    expect(["waiting_permission", "running", "idle", "ended", "failed"].map(sectionOf)).toEqual([
      "waiting",
      "live",
      "idle",
      "ended",
      "ended",
    ]);
  });

  it("asks each section by its status with the same filters and the period on Ended only", () => {
    const all = queries("period=24 h&repo=demo&sort=-cost");

    expect(all).toEqual({
      waiting: { sort: "-cost", project: "agent-hub", repo: "demo", status: "waiting" },
      live: { sort: "-cost", project: "agent-hub", repo: "demo", status: "live" },
      idle: { sort: "-cost", project: "agent-hub", repo: "demo", status: "idle" },
      ended: {
        sort: "-cost",
        project: "agent-hub",
        repo: "demo",
        status: "ended",
        from: "2026-10-10T14:00:00.000Z",
      },
    });
  });

  it("asks only the faceted section when a status is chosen, and Live for Live now", () => {
    expect(queries("status=waiting")).toEqual({
      waiting: { sort: "-started_at", project: "agent-hub", status: "waiting" },
      live: null,
      idle: null,
      ended: null,
    });
    // The built-in "Live now" view is status=live with period=All.
    expect(queries("status=live&period=All")).toMatchObject({
      waiting: null,
      live: { status: "live" },
      idle: null,
      ended: null,
    });
  });

  it("asks only Ended when an outcome is chosen, since only ended sessions have one", () => {
    expect(queries("outcome=error")).toMatchObject({
      waiting: null,
      live: null,
      idle: null,
      ended: { status: "ended", outcome: "error" },
    });
  });

  it("counts a section from its query's total plus its driven rows without a twin", () => {
    expect(sectionCount(1233)).toBe(1233);
    expect(sectionCount(4, [{}, {}])).toBe(6);
  });
});
