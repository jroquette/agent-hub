import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { OfflineBanner } from "./OfflineBanner";

const START = new Date("2026-10-11T14:02:00Z").getTime();
const offline = { open: false, lastMessageAt: START, closedSince: START };

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(START + 61_000);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("OfflineBanner", () => {
  it("shows the offline copy with the time of the last data when the collector is offline", () => {
    render(<OfflineBanner health={offline} tz="utc" />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Collector offline since 14:02. Views show data as of 14:02. Start it with hub web.",
    );
    expect(screen.getByRole("button", { name: "Copy command" })).toBeInTheDocument();
  });

  it("shows nothing when the collector is connected", () => {
    const { container } = render(
      <OfflineBanner health={{ open: true, lastMessageAt: START + 60_000, closedSince: null }} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("stays dismissed until the state changes", () => {
    const { rerender } = render(<OfflineBanner health={offline} tz="utc" />);

    act(() => {
      screen.getByRole("button", { name: "Dismiss" }).click();
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    rerender(
      <OfflineBanner
        health={{ open: true, lastMessageAt: Date.now(), closedSince: null }}
        tz="utc"
      />,
    );
    rerender(
      <OfflineBanner health={{ ...offline, lastMessageAt: Date.now() - 70_000 }} tz="utc" />,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("has no serious or critical a11y violation", async () => {
    vi.useRealTimers();
    const { container } = render(
      <OfflineBanner health={{ open: false, lastMessageAt: 0, closedSince: 0 }} />,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
