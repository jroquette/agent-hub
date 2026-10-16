import { describe, expect, it } from "vitest";

import { quoteLabel } from "./DiscussSelection";

describe("quoteLabel", () => {
  it("reads as the quote's first words on one line", () => {
    expect(quoteLabel("Only the live\n  DataMode")).toBe("“Only the live DataMode”");
    expect(quoteLabel("x".repeat(60))).toBe(`“${"x".repeat(39)}…”`);
  });
});
