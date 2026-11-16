import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { CollectorPill, collectorState } from "./CollectorPill";

const START = new Date("2026-10-11T14:02:00Z").getTime();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(START);
});

afterEach(() => {
  vi.useRealTimers();
});

function pill() {
  return screen.getByRole("status");
}

describe("CollectorPill", () => {
  it("shows Connected, Delayed and Offline after 10, 35 and 70 s of silence", () => {
    render(
      <CollectorPill health={{ open: true, lastMessageAt: START, closedSince: null }} tz="utc" />,
    );

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(pill()).toHaveAttribute("data-state", "connected");
    expect(pill()).toHaveTextContent("Connected · last event 10 s ago");

    act(() => {
      vi.advanceTimersByTime(25_000);
    });
    expect(pill()).toHaveAttribute("data-state", "delayed");
    expect(pill()).toHaveTextContent("Delayed · last event 35 s ago");

    act(() => {
      vi.advanceTimersByTime(35_000);
    });
    expect(pill()).toHaveAttribute("data-state", "offline");
    expect(pill()).toHaveTextContent("Offline · as of 14:02");
  });

  it("says how to start the collector when it is offline", () => {
    render(
      <CollectorPill health={{ open: false, lastMessageAt: START, closedSince: START }} tz="utc" />,
    );
    act(() => {
      vi.advanceTimersByTime(11_000);
    });

    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Collector not reachable since 14:02. Start it with hub web in the hub directory.",
    );
  });

  it("has no serious or critical a11y violation", async () => {
    vi.useRealTimers();
    const { container } = render(
      <CollectorPill health={{ open: true, lastMessageAt: Date.now(), closedSince: null }} />,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("collectorState", () => {
  it.each([
    [0, true, null, "connected"],
    [29_999, true, null, "connected"],
    [30_000, true, null, "delayed"],
    [59_999, true, null, "delayed"],
    [60_000, true, null, "offline"],
    [5_000, false, 0, "connected"],
    [10_000, false, 0, "offline"],
  ] as const)("at %d ms with open=%s is %s", (now, open, closedSince, state) => {
    expect(collectorState({ open, lastMessageAt: 0, closedSince }, now)).toBe(state);
  });
});
