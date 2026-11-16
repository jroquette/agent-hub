import { describe, expect, it } from "vitest";

import { aCatalogItem, aSkillCatalog } from "../../testing/builders";
import {
  MAX_QUERY_CHARS,
  NO_FILTERS,
  facetCounts,
  filterItems,
  filtersFromParams,
  hasFilters,
  withFilters,
} from "./filters";

const ITEMS = aSkillCatalog().items;
const names = (items: readonly { name: string }[]) => items.map((item) => item.name);

describe("filtersFromParams url_query", () => {
  it("reads search, comma lists and the diagnostics flag when the query holds them", () => {
    const filters = filtersFromParams(
      new URLSearchParams("q=plan&kind=skill,agent&origin=managed&mode=user-only,neither&diag=1"),
    );

    expect(filters).toEqual({
      q: "plan",
      kind: ["agent", "skill"],
      origin: ["managed"],
      mode: ["user-only", "neither"],
      diag: true,
    });
  });

  it("drops unknown values, repeats and over-long search when the query is hand-written", () => {
    const filters = filtersFromParams(
      new URLSearchParams(
        `q=${"x".repeat(MAX_QUERY_CHARS + 50)}&kind=plugin,skill,skill&origin=&mode=all&diag=yes`,
      ),
    );

    expect(filters.q).toHaveLength(MAX_QUERY_CHARS);
    expect(filters.kind).toEqual(["skill"]);
    expect(filters.origin).toEqual([]);
    expect(filters.mode).toEqual([]);
    expect(filters.diag).toBe(false);
  });

  it("gives no filters when the query is empty", () => {
    expect(filtersFromParams(new URLSearchParams())).toEqual(NO_FILTERS);
    expect(hasFilters(NO_FILTERS)).toBe(false);
  });
});

describe("withFilters url_query", () => {
  it("writes set filters in a stable order and keeps other parameters", () => {
    const next = withFilters(new URLSearchParams("scope=demo&q=old&diag=1"), {
      q: "plan",
      kind: ["agent", "skill"],
      origin: [],
      mode: ["both"],
      diag: false,
    });

    expect(next.toString()).toBe("scope=demo&q=plan&kind=agent%2Cskill&mode=both");
  });

  it("removes every filter when cleared", () => {
    expect(withFilters(new URLSearchParams("q=a&kind=hook&diag=1"), NO_FILTERS).toString()).toBe(
      "",
    );
  });
});

describe("filterItems search_facets", () => {
  it("matches search on name or description, ignoring case", () => {
    expect(names(filterItems(ITEMS, { ...NO_FILTERS, q: "PLAN" }))).toEqual(["plan"]);
    expect(names(filterItems(ITEMS, { ...NO_FILTERS, q: "spec" }))).toEqual([
      "feature",
      "evaluator",
    ]);
    expect(names(filterItems(ITEMS, { ...NO_FILTERS, q: "  " }))).toHaveLength(4);
  });

  it("combines facets with search and with each other", () => {
    expect(names(filterItems(ITEMS, { ...NO_FILTERS, kind: ["skill", "hook"] }))).toEqual([
      "feature",
      "plan",
      "settings-pretooluse-1",
    ]);
    expect(names(filterItems(ITEMS, { ...NO_FILTERS, origin: ["project-owned"] }))).toEqual([
      "plan",
    ]);
    expect(names(filterItems(ITEMS, { ...NO_FILTERS, mode: ["user-only", "both"] }))).toEqual([
      "feature",
      "plan",
    ]);
    expect(names(filterItems(ITEMS, { ...NO_FILTERS, diag: true }))).toEqual(["feature"]);
    expect(
      names(filterItems(ITEMS, { ...NO_FILTERS, q: "spec", kind: ["agent"], diag: false })),
    ).toEqual(["evaluator"]);
  });

  it("counts each facet value over the items the other filters keep", () => {
    const counts = facetCounts(ITEMS, { ...NO_FILTERS, q: "spec", kind: ["skill"] });

    expect(counts.kind).toEqual({ skill: 1, agent: 1, hook: 0 });
    expect(counts.origin).toEqual({ managed: 1, "project-owned": 0, local: 0 });
    expect(counts.mode).toEqual({ "user-only": 0, "model-only": 0, both: 1, neither: 0 });
    expect(counts.diag).toEqual({ "1": 1 });
  });

  it("keeps the hidden mode apart when a skill is invocable by no one", () => {
    const hidden = aCatalogItem({ name: "quiet", mode: "neither" });

    expect(names(filterItems([...ITEMS, hidden], { ...NO_FILTERS, mode: ["neither"] }))).toEqual([
      "quiet",
    ]);
  });
});
