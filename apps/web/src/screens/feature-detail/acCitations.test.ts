import { describe, expect, it } from "vitest";

import { acIdsIn, citationsIn } from "./acCitations";

const KNOWN = new Set(["AC-1", "AC-10", "AC-11", "AC-12", "AC-48.2"]);

describe("acIdsIn", () => {
  it("never matches AC-1 inside AC-11", () => {
    expect([...acIdsIn("only AC-11 here", KNOWN)]).toEqual(["AC-11"]);
  });

  it("expands the AC-10/11/12 short form", () => {
    expect([...acIdsIn("checks for AC-10/11/12 run first", KNOWN)]).toEqual([
      "AC-10",
      "AC-11",
      "AC-12",
    ]);
  });

  it("matches dotted ids and ignores unknown ones", () => {
    expect([...acIdsIn("AC-48.2 and AC-99", KNOWN)]).toEqual(["AC-48.2"]);
  });
});

describe("citationsIn", () => {
  it("keeps the first mention's section and snippet and counts the lines", () => {
    const markdown = [
      "# Spec",
      "intro",
      "## Acceptance criteria",
      "**AC-11: unsupported currency**",
      "- on a validation error (AC-10 first case, AC-11), the modal shows it",
      "```",
      "# not a heading AC-1",
      "```",
    ].join("\n");

    const found = citationsIn("features/x/spec.md", markdown, KNOWN);

    expect(found.get("AC-11")).toEqual({
      path: "features/x/spec.md",
      section: "Acceptance criteria",
      snippet: "AC-11: unsupported currency",
      count: 2,
    });
    expect(found.get("AC-1")?.section).toBe("Acceptance criteria");
  });

  it("reads a table row as plain text", () => {
    const found = citationsIn("features/x/plan.md", "| AC-11 | `test_x` (`T_GPS`) |", KNOWN);

    expect(found.get("AC-11")?.snippet).toBe("AC-11 · test_x (T_GPS)");
  });
});
