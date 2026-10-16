import { describe, expect, it } from "vitest";

import { aLearning } from "../../testing/builders";
import {
  facetCounts,
  filterLearnings,
  filtersFromParams,
  hasFilters,
  MAX_QUERY_CHARS,
  NO_FILTERS,
  withFilters,
  type ClaudeVerdict,
} from "./filters";

const ROWS = [
  aLearning({ id: "a", project: "demo", provenance: "agent-from-code", text: "Stripe clients" }),
  aLearning({
    id: "b",
    project: "demo",
    provenance: "agent",
    text: "Guard env files",
    actions_unavailable: "Note not in the hub checkout",
  }),
  aLearning({ id: "c", project: "agent-hub", provenance: "agent", text: "Run the web gates" }),
];
const ids = (rows: readonly { id: string }[]) => rows.map((l) => l.id);

describe("filtersFromParams url_query", () => {
  it("reads search, project and comma lists when the query holds them", () => {
    const filters = filtersFromParams(
      new URLSearchParams("q=stripe&project=demo&provenance=agent,human&readiness=blocked"),
    );

    expect(filters).toEqual({
      q: "stripe",
      project: "demo",
      provenance: ["human", "agent"],
      readiness: ["blocked"],
      claude: [],
    });
  });

  it("drops unknown values and over-long search when the query is hand-written", () => {
    const filters = filtersFromParams(
      new URLSearchParams(
        `q=${"x".repeat(MAX_QUERY_CHARS + 5)}&project=&provenance=bot&readiness=no`,
      ),
    );

    expect(filters.q).toHaveLength(MAX_QUERY_CHARS);
    expect(filters.project).toBeNull();
    expect(filters.provenance).toEqual([]);
    expect(filters.readiness).toEqual([]);
  });

  it("round-trips through withFilters and keeps other parameters", () => {
    const filters = { ...NO_FILTERS, project: "demo", readiness: ["ready" as const] };
    const params = withFilters(new URLSearchParams("status=accepted&q=old"), filters);

    expect(params.toString()).toBe("status=accepted&project=demo&readiness=ready");
    expect(filtersFromParams(params)).toEqual(filters);
    expect(hasFilters(NO_FILTERS)).toBe(false);
    expect(hasFilters(filters)).toBe(true);
  });
});

describe("filterLearnings facets", () => {
  it("keeps one project's learnings when a project is picked", () => {
    expect(ids(filterLearnings(ROWS, { ...NO_FILTERS, project: "demo" }))).toEqual(["a", "b"]);
  });

  it("matches search against title, summary and project", () => {
    expect(ids(filterLearnings(ROWS, { ...NO_FILTERS, q: "STRIPE" }))).toEqual(["a"]);
    expect(ids(filterLearnings(ROWS, { ...NO_FILTERS, q: "agent-hub" }))).toEqual(["c"]);
  });

  it("splits ready from blocked proposals", () => {
    expect(ids(filterLearnings(ROWS, { ...NO_FILTERS, readiness: ["blocked"] }))).toEqual(["b"]);
    expect(ids(filterLearnings(ROWS, { ...NO_FILTERS, readiness: ["ready"] }))).toEqual(["a", "c"]);
  });

  it("counts each facet with the others applied, projects in name order", () => {
    const counts = facetCounts(ROWS, { ...NO_FILTERS, provenance: ["agent"] });

    expect(counts.project).toEqual([
      ["agent-hub", 1],
      ["demo", 1],
    ]);
    expect(counts.provenance).toEqual({
      human: 0,
      agent: 2,
      "agent-from-code": 1,
      "agent-from-external": 0,
    });
    expect(counts.readiness).toEqual({ ready: 1, blocked: 1 });
  });

  it("keeps the learnings Claude recommends when the Claude facet is picked", () => {
    const verdictOf = (l: { id: string }): ClaudeVerdict => (l.id === "a" ? "ready" : "unreviewed");
    const filters = { ...NO_FILTERS, claude: ["ready" as const] };

    expect(ids(filterLearnings(ROWS, filters, verdictOf))).toEqual(["a"]);
    expect(facetCounts(ROWS, NO_FILTERS, verdictOf).claude).toMatchObject({
      ready: 1,
      unreviewed: 2,
    });
    expect(filtersFromParams(withFilters(new URLSearchParams(), filters)).claude).toEqual([
      "ready",
    ]);
  });
});
