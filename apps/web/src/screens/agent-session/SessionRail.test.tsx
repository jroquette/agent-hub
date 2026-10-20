import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aPage, anAgentSession, renderWithApi } from "../../testing/builders";
import { RAIL_KEY, SessionRail, railGroups, railName } from "./SessionRail";

const NOW = Date.UTC(2026, 9, 20, 13, 0);
const at = (minutes: number) => new Date(Date.UTC(2026, 9, 20, 12, minutes)).toISOString();
const sessions = [
  anAgentSession({ id: "a", title: "Ship the rail", status: "running", updated_at: at(5) }),
  anAgentSession({
    id: "b",
    title: "Fix the guard",
    status: "waiting_permission",
    updated_at: at(1),
  }),
  anAgentSession({ id: "c", title: "Old spike", status: "ended", updated_at: at(0) }),
  anAgentSession({
    id: "d",
    title: null,
    last_prompt: "  write\nthe plan ",
    status: "idle",
    updated_at: at(9),
  }),
];

afterEach(() => {
  window.localStorage.clear();
});

describe("railGroups", () => {
  it("pins the sessions waiting for you, then groups the rest by day, newest first", () => {
    const lastWeek = anAgentSession({
      id: "w",
      status: "ended",
      updated_at: new Date(NOW - 3 * 86_400_000).toISOString(),
    });
    expect(
      railGroups([...sessions, lastWeek], "", NOW).map((g) => [g.id, g.sessions.map((s) => s.id)]),
    ).toEqual([
      ["needs", ["b"]],
      ["today", ["d", "a", "c"]],
      ["week", ["w"]],
    ]);
  });

  it("filters by name, project or folder, and drops empty groups", () => {
    expect(railGroups(sessions, "GUARD", NOW).map((g) => g.id)).toEqual(["needs"]);
  });

  it("names a session by its title, else its last prompt on one line", () => {
    const untitled = anAgentSession({ title: null, last_prompt: "  write\nthe plan " });
    expect(railName(untitled)).toBe("write the plan");
  });
});

describe("SessionRail", () => {
  const routes = { "/api/v1/agent-sessions": aPage(sessions) };

  it("marks the current session and links the others to their chat", async () => {
    const { container } = renderWithApi(<SessionRail current="a" />, { routes });
    const rail = await screen.findByRole("navigation", { name: "Sessions" });

    const current = await within(rail).findByRole("link", { current: "page" });
    expect(current).toHaveTextContent("Ship the rail");
    expect(within(rail).getByRole("link", { name: /Fix the guard/ })).toHaveAttribute(
      "href",
      "/agent-sessions/b",
    );
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("folds to a strip of the open sessions and remembers it", async () => {
    renderWithApi(<SessionRail current="a" />, { routes });
    await userEvent.click(await screen.findByRole("button", { name: "Hide sessions" }));

    expect(window.localStorage.getItem(RAIL_KEY)).toBe("closed");
    expect(screen.getByRole("button", { name: "Show sessions" })).toBeInTheDocument();
    // The strip keeps the open sessions only.
    expect(screen.queryByRole("link", { name: /Old spike/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Fix the guard/ })).toBeInTheDocument();
  });
});
