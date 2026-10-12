import { describe, expect, it } from "vitest";

import {
  fmtAgo,
  fmtClock,
  fmtDuration,
  fmtInt,
  fmtMoney,
  fmtTokens,
  middleTruncate,
  toNumber,
} from "./format";

describe("fmtMoney", () => {
  it("formats dollars with two decimals when given a number", () => {
    expect(fmtMoney(1234.5)).toBe("$1,234.50");
  });

  it("reads the API's decimal strings when given a Money value", () => {
    expect(fmtMoney("2.1400", 4)).toBe("$2.1400");
  });

  it("shows a dash when the value is unknown", () => {
    expect(fmtMoney(null)).toBe("—");
    expect(fmtMoney(undefined)).toBe("—");
    expect(fmtMoney("not a number")).toBe("—");
  });
});

describe("fmtInt and fmtTokens", () => {
  it("groups thousands when given an integer", () => {
    expect(fmtInt(1284)).toBe("1,284");
    expect(fmtInt(null)).toBe("—");
  });

  it("abbreviates tokens when they reach ten thousand or a million", () => {
    expect(fmtTokens(9999)).toBe("9,999");
    expect(fmtTokens(48_200)).toBe("48 k");
    expect(fmtTokens(2_345_678)).toBe("2.35 M");
    expect(fmtTokens(null)).toBe("—");
  });
});

describe("fmtDuration", () => {
  it.each([
    [42, "42 s"],
    [192, "3 min 12 s"],
    [600, "10 min"],
    [725, "12 min"],
    [3600, "1 h"],
    [5400, "1 h 30 min"],
  ])("formats %d seconds as %s", (seconds, text) => {
    expect(fmtDuration(seconds)).toBe(text);
  });

  it("shows a dash when the duration is unknown", () => {
    expect(fmtDuration(null)).toBe("—");
  });
});

describe("fmtAgo", () => {
  it.each([
    [0.2, "1 s ago"],
    [3, "3 s ago"],
    [120, "2 min ago"],
    [7200, "2 h ago"],
    [172_800, "2 d ago"],
  ])("formats %d seconds as %s", (seconds, text) => {
    expect(fmtAgo(seconds)).toBe(text);
  });
});

describe("fmtClock", () => {
  it("shows hours and minutes in UTC when the time zone is utc", () => {
    expect(fmtClock("2026-10-11T14:02:11Z", "utc")).toBe("14:02");
  });

  it("shows seconds when asked", () => {
    expect(fmtClock(new Date("2026-10-11T14:02:11Z"), "utc", true)).toBe("14:02:11");
  });
});

describe("middleTruncate", () => {
  it("keeps a short path whole", () => {
    expect(middleTruncate("brain/now.md")).toBe("brain/now.md");
  });

  it("keeps the head and the longest tail that fits when the path is long", () => {
    const path = "packages/core/src/agent_hub/core/memory/brain_memory_rule.py";
    expect(middleTruncate(path, 40)).toBe("packages/…/memory/brain_memory_rule.py");
  });

  it("cuts in the middle when there are no folders", () => {
    expect(middleTruncate("a".repeat(30) + "b".repeat(30), 21)).toBe(
      "a".repeat(10) + "…" + "b".repeat(10),
    );
  });
});

describe("toNumber", () => {
  it("parses Money strings and passes numbers", () => {
    expect(toNumber("1.5000")).toBe(1.5);
    expect(toNumber(3)).toBe(3);
    expect(toNumber(null)).toBeNull();
    expect(toNumber("x")).toBeNull();
  });
});
