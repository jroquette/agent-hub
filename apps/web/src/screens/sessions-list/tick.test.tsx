import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  aPage,
  aProjectSummary,
  aSession,
  aSessionLabel,
  aSessionsByStatus,
  anId,
  at,
  renderWithApi,
} from "../../testing/builders";
import { SessionsListScreen } from "./index";

// These tests read the tables; the grid is the default view (AC-234.3).
beforeEach(() => {
  window.localStorage.setItem("ah.sessions.view", "table");
});

const durations = vi.hoisted(() => ({ calls: 0, money: 0 }));
vi.mock("../../lib/format", async (original) => {
  const actual = await original<typeof import("../../lib/format")>();
  return {
    ...actual,
    fmtDuration: (seconds: number) => {
      durations.calls += 1;
      return actual.fmtDuration(seconds);
    },
    // Once per tile render in the grid: counts whole-tile renders.
    fmtMoney: (usd: number | null) => {
      durations.money += 1;
      return actual.fmtMoney(usd);
    },
  };
});

const named = (name: string) =>
  aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`] });

afterEach(() => {
  vi.useRealTimers();
});

function renderScreen() {
  const ended = Array.from({ length: 30 }, (_, i) =>
    aSession({
      id: anId(100 + i, `eeee${String(i).padStart(4, "0")}`),
      status: "ended",
      ended_at: at(60),
      label: named(`ended-${String(i)}`),
    }),
  );
  const running = aSession({
    id: anId(1, "aaaa0001"),
    status: "live",
    label: named("runner"),
    // Seconds old, so each tick changes its elapsed text.
    started_at: new Date(Date.now() - 5_000).toISOString(),
  });
  return renderWithApi(<SessionsListScreen />, {
    routes: {
      "/api/v1/sessions": aSessionsByStatus([running, ...ended]),
      "/api/v1/projects": aPage([aProjectSummary()]),
      "/api/v1/agent-sessions": { items: [] },
    },
    path: "/sessions",
  });
}

describe("SessionsListScreen clock-ticks", () => {
  it("re-renders only the running sessions' durations on each second", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderScreen();
    await screen.findByText("/ended-29");

    durations.calls = 0;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    // Three ticks re-format the one running duration, not the 30 ended ones.
    expect(durations.calls).toBeGreaterThan(0);
    expect(durations.calls).toBeLessThanOrEqual(3);
  });
});

describe("SessionsListScreen clock-ticks (grid)", () => {
  beforeEach(() => {
    window.localStorage.setItem("ah.sessions.view", "grid");
  });

  it("re-renders no tile on each second, only a running tile's elapsed time", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderScreen();
    await screen.findByText("/ended-29");
    expect(screen.queryByRole("table")).toBeNull();
    // The first stat is the elapsed time.
    const elapsed = () =>
      screen.getByRole("article", { name: /^\/runner in / }).querySelector(".ah-tile-stats b")
        ?.textContent;
    const before = elapsed();

    durations.calls = 0;
    durations.money = 0;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    // Three ticks re-format the one running duration; no tile (ended or live) renders again.
    expect(durations.calls).toBeGreaterThan(0);
    expect(durations.calls).toBeLessThanOrEqual(3);
    expect(durations.money).toBe(0);
    expect(elapsed()).not.toBe(before);
  });
});
