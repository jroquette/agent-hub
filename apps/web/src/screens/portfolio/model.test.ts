import { describe, expect, it } from "vitest";

import { anActivityItem } from "../../testing/builders";
import { ACTIVITY_FILTERS, collapseRepeats } from "./model";

describe("activity rail model", () => {
  it("leaves answered approvals out of every activity filter (AC-PG-29.4)", () => {
    for (const filter of ACTIVITY_FILTERS) expect(filter.kinds).not.toContain("approval");
    expect(ACTIVITY_FILTERS.find((f) => f.id === "All")?.kinds).toEqual([
      "reported",
      "failed",
      "learning",
      "doctor",
    ]);
  });

  it("collapses consecutive rows with the same text and project into one row with a count (AC-PG-29.4)", () => {
    const failed = anActivityItem({ kind: "failed", text: "Run AGH-79 failed" });
    const rows = collapseRepeats([
      failed,
      { ...failed },
      { ...failed },
      anActivityItem({ text: "Run AGH-48 reported" }),
    ]);

    expect(rows.map(({ item, count }) => [item.text, count])).toEqual([
      ["Run AGH-79 failed", 3],
      ["Run AGH-48 reported", 1],
    ]);
  });

  it("keeps repeats apart when another row sits between them or the project differs (AC-PG-29.4)", () => {
    const a = anActivityItem({ text: "Learning accepted" });
    const b = anActivityItem({ text: "Run AGH-48 reported" });
    const elsewhere = anActivityItem({ text: "Learning accepted", project: "loki-trader" });

    expect(collapseRepeats([a, b, a, elsewhere]).map(({ count }) => count)).toEqual([1, 1, 1, 1]);
    expect(collapseRepeats([])).toEqual([]);
  });
});
