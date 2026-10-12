import { describe, expect, it } from "vitest";

import { aSession, at } from "../../testing/builders";
import { durationOf, isOpen, statusOf, tokensText } from "./session-status";

const NOW = Date.parse(at(1200));

describe("statusOf", () => {
  it("names each status and outcome with the design's copy", () => {
    expect(statusOf(aSession({ status: "live" }), NOW).label).toBe("Live");
    expect(statusOf(aSession({ status: "waiting" }), NOW).label).toBe("Waiting");
    expect(statusOf(aSession({ status: "idle", last_activity_at: at(780) }), NOW).label).toBe(
      "Idle · 7 min",
    );
    for (const [outcome, label] of [
      ["done", "Done"],
      ["stopped", "Stopped"],
      ["blocked", "Blocked"],
      ["error", "Error"],
    ] as const) {
      expect(
        statusOf(aSession({ status: "ended", outcome, end_reason: "other" }), NOW),
      ).toMatchObject({
        label,
        title: "end_reason: other",
      });
    }
    expect(
      statusOf(aSession({ status: "ended", outcome: null, end_inferred: true }), NOW).label,
    ).toBe("Ended · no end event");
    expect(statusOf(aSession({ status: "ended", outcome: null }), NOW).label).toBe("Ended");
  });
});

describe("durationOf and tokensText", () => {
  it("measures to now while running and splits tokens when usage exists", () => {
    expect(durationOf(aSession({ ended_at: null }), NOW)).toBe(1200);
    expect(durationOf(aSession({ ended_at: at(60) }), NOW)).toBe(60);
    expect(tokensText(aSession().tokens).text).toBe("4,000 in · 900 out · 1,500 cache");
    expect(tokensText(null).text).toBe("—");
    expect(isOpen(aSession({ status: "idle" }))).toBe(true);
  });
});
