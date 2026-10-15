import { describe, expect, it } from "vitest";

import { anAgentSession, anId, aSession } from "../../testing/builders";
import {
  SECTIONS,
  placeDriven,
  sectionCount,
  sectionOf,
  sectionQueries,
  type SectionId,
} from "./sections";

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
    expect(sectionCount(4, { added: 2, removed: 1 })).toBe(5);
  });
});

describe("placeDriven (driven-in-list)", () => {
  const twinOf = (status: "live" | "waiting", agent: string) =>
    aSession({ id: anId(3), status, agent_session_id: agent });
  const empty = (): Record<SectionId, ReturnType<typeof aSession>[]> => ({
    waiting: [],
    live: [],
    idle: [],
    ended: [],
  });
  const all = new Set<SectionId>(["waiting", "live", "idle", "ended"]);

  it("places twinless driven sessions only into the sections asked", () => {
    const placed = placeDriven(empty(), [anAgentSession({ status: "running" })], new Set(["idle"]));
    expect(placed.live).toEqual({ rows: [], added: 0, removed: 0 });
    expect(placed.idle.rows).toEqual([]);
  });

  it("keeps a waiting twin in its section when Waiting is not asked", () => {
    const agent = anAgentSession({ status: "waiting_permission", observed_session_id: anId(3) });
    const placed = placeDriven(
      { ...empty(), live: [twinOf("live", agent.id)] },
      [agent],
      new Set(["live"]),
    );
    expect(placed.live).toMatchObject({ added: 0, removed: 0 });
    expect(placed.live.rows).toHaveLength(1);
  });

  it("does not move or count twice a twin already in Waiting", () => {
    const agent = anAgentSession({ status: "waiting_permission", observed_session_id: anId(3) });
    const placed = placeDriven(
      { ...empty(), waiting: [twinOf("waiting", agent.id)] },
      [agent],
      all,
    );
    expect(placed.waiting).toMatchObject({ added: 0, removed: 0 });
    expect(placed.waiting.rows).toHaveLength(1);
  });
});
