import { afterEach, describe, expect, it } from "vitest";

import { EFFORTS, effortLabel, rememberEffort, rememberedEffort } from "./effort";

const KEY = "ah.session.effort";

afterEach(() => {
  window.localStorage.removeItem(KEY);
});

describe("effort (AC-681.4, AC-681.5)", () => {
  it("offers the five levels in order, Medium recommended and Max costly", () => {
    expect(EFFORTS.map((option) => [option.value, option.label, option.tag ?? null])).toEqual([
      ["low", "Low", null],
      ["medium", "Medium", "Recommended"],
      ["high", "High", null],
      ["xhigh", "Extra", null],
      ["max", "Max", "3.5× or more usage"],
    ]);
    expect(EFFORTS.filter((option) => option.costly).map((option) => option.value)).toEqual([
      "max",
    ]);
  });

  it("gives back the effort last remembered in this browser", () => {
    rememberEffort("xhigh");

    expect(window.localStorage.getItem(KEY)).toBe("xhigh");
    expect(rememberedEffort()).toBe("xhigh");
  });

  it("remembers no effort when nothing is stored", () => {
    expect(rememberedEffort()).toBeNull();
  });

  it("ignores a stored value that is not a level", () => {
    window.localStorage.setItem(KEY, "ultra");

    expect(rememberedEffort()).toBeNull();
  });

  it("labels each level as the menu shows it", () => {
    expect(effortLabel("xhigh")).toBe("Extra");
    expect(effortLabel("high")).toBe("High");
  });
});
