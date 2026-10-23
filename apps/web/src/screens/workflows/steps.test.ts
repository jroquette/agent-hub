import { describe, expect, it } from "vitest";

import { kindCounts, STEP_KINDS, stepKind } from "./steps";

describe("steps", () => {
  it("names a scenario's action and expect steps with their own icons", () => {
    expect(stepKind("action")).toBe("action");
    expect(stepKind("expect")).toBe("expect");
    expect(STEP_KINDS.action.icon).toBe("circle-play");
    expect(STEP_KINDS.expect.icon).toBe("timer");
    expect(kindCounts({ action: 2, expect: 1 })).toEqual([
      ["action", 2],
      ["expect", 1],
    ]);
  });

  it("keeps a workflow's shell and script steps as commands", () => {
    expect(stepKind("shell")).toBe("command");
    expect(stepKind("unknown")).toBe("command");
  });
});
