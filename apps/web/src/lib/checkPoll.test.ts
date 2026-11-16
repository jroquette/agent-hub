import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type PolledQuery, useCheckPoll } from "./checkPoll";

interface Answer {
  checked_at: string | null;
}

/** One answer of the same query (the Portfolio's projects, say), as `refetchInterval` gets it. */
function answer(checkedAt: string | null): PolledQuery<Answer> {
  return { queryHash: '["/api/v1/projects"]', state: { data: { checked_at: checkedAt } } };
}

describe("useCheckPoll", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: Date.parse("2026-10-11T14:05:00.000Z") });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reads every 2 s again when an unchecked answer follows a checked one", () => {
    const { result } = renderHook(() => useCheckPoll<Answer>((data) => data.checked_at === null));
    const interval = result.current;
    expect(interval(answer(null))).toBe(2_000);
    vi.advanceTimersByTime(61_000);
    // Past the first minute of unchecked answers: every 15 s.
    expect(interval(answer(null))).toBe(15_000);
    // A checked answer starts no polling.
    expect(interval(answer("2026-10-11T14:06:01.000Z"))).toBe(false);

    // A new hub registers: the same query answers unchecked again.
    const next = interval(answer(null));

    expect(next).toBe(2_000);
  });
});
