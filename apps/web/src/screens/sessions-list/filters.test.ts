import { describe, expect, it } from "vitest";

import { badDecimal, chipsOf, periodOf, queryOf, sortOf } from "./filters";

const NOW = Date.parse("2026-10-11T14:00:00.000Z");

describe("queryOf", () => {
  it("maps the URL filters to the API query when they are set", () => {
    const params = new URLSearchParams(
      "period=24 h&status=live&outcome=error&repo=agent-hub&tool=Bash&cost_min=1.5&guard_denial=1&sort=-cost",
    );

    expect(queryOf(params, "agent-hub", NOW)).toEqual({
      sort: "-cost",
      from: "2026-10-10T14:00:00.000Z",
      project: "agent-hub",
      status: "live",
      outcome: "error",
      repo: "agent-hub",
      tool: "Bash",
      cost_min: "1.5",
      guard_denial: true,
    });
  });

  it("uses the last 7 days sorted by newest start when the URL has no filter", () => {
    expect(queryOf(new URLSearchParams(), null, NOW)).toEqual({
      sort: "-started_at",
      from: "2026-10-04T14:00:00.000Z",
    });
    expect(queryOf(new URLSearchParams("period=All&status=nope"), null, NOW)).toEqual({
      sort: "-started_at",
    });
    expect(periodOf(new URLSearchParams("period=x"))).toBe("7 d");
    expect(sortOf(new URLSearchParams("sort=x"))).toBe("-started_at");
  });
});

describe("chipsOf", () => {
  it("names each active filter when filters are set", () => {
    expect(
      chipsOf(new URLSearchParams("outcome=error&guard_denial=1&cost_max=3&file=a.py")),
    ).toEqual([
      { key: "outcome", label: "Outcome", value: "error" },
      { key: "cost_max", label: "Cost to", value: "$3" },
      { key: "file", label: "Touched file", value: "a.py" },
      { key: "guard_denial", label: "Flag", value: "Had a guard denial" },
    ]);
  });
});

describe("badDecimal", () => {
  it("flags a comma decimal when it is typed", () => {
    expect(badDecimal("1,5")).toBe(true);
    expect(badDecimal("1.5")).toBe(false);
    expect(badDecimal(null)).toBe(false);
  });
});
