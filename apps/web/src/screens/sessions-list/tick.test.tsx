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

const durations = vi.hoisted(() => ({ calls: 0 }));
vi.mock("../../lib/format", async (original) => {
  const actual = await original<typeof import("../../lib/format")>();
  return {
    ...actual,
    fmtDuration: (seconds: number) => {
      durations.calls += 1;
      return actual.fmtDuration(seconds);
    },
  };
});

const named = (name: string) =>
  aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`] });

afterEach(() => {
  vi.useRealTimers();
});

describe("SessionsListScreen clock-ticks", () => {
  it("re-renders only the running sessions' durations on each second", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const ended = Array.from({ length: 30 }, (_, i) =>
      aSession({
        id: anId(100 + i, `eeee${String(i).padStart(4, "0")}`),
        status: "ended",
        ended_at: at(60),
        label: named(`ended-${String(i)}`),
      }),
    );
    const running = aSession({ id: anId(1, "aaaa0001"), status: "live", label: named("runner") });
    renderWithApi(<SessionsListScreen />, {
      routes: {
        "/api/v1/sessions": aSessionsByStatus([running, ...ended]),
        "/api/v1/projects": aPage([aProjectSummary()]),
        "/api/v1/agent-sessions": { items: [] },
      },
      path: "/sessions",
    });
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
