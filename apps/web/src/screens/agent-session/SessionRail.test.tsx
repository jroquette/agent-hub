import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aSession,
  aSessionLabel,
  anAgentSession,
  renderWithApi,
} from "../../testing/builders";
import { RAIL_KEY, SessionRail, railGroups, railName, railTagsOf } from "./SessionRail";

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
  it("AC-422.18 lists the sessions waiting for you first, then the open ones, then the recent ended ones", () => {
    expect(railGroups(sessions, "").map((g) => [g.id, g.sessions.map((s) => s.id)])).toEqual([
      ["needs", ["b"]],
      ["active", ["d", "a"]],
      ["recent", ["c"]],
    ]);
  });

  it("AC-422.19 filters by name, project, folder or tag, and drops empty groups", () => {
    expect(railGroups(sessions, "GUARD").map((g) => g.id)).toEqual(["needs"]);
    const tagged = () => ({ ticket: "TIP-1576", feature: "allianz", name: null });
    expect(railGroups(sessions, "tip-1576", tagged)).toHaveLength(3);
  });

  it("AC-422.20 names a session by its title, else its last prompt on one line", () => {
    const untitled = anAgentSession({ title: null, last_prompt: "  write\nthe plan " });
    expect(railName(untitled)).toBe("write the plan");
  });

  it("AC-422.20 names a session on a ticket by its ticket, as the chat's header does", () => {
    const titled = anAgentSession({ title: "Campos buyer_ip_address" });
    const tags = { ticket: "TIP-1577", feature: "allianz", name: "TIP-1577: Add the client" };
    expect(railName(titled, tags)).toBe("TIP-1577: Add the client");
  });
});

describe("railTagsOf", () => {
  it("AC-422.20 tags a session with its observed twin's ticket and the feature that plans it", () => {
    const twin = aSession({ id: "obs-1", label: aSessionLabel({ issue: "TIP-1576" }) });
    const lookup = new Map([
      ["TIP-1576", { project: "tipple", slug: "allianz", title: "Add the fraud-check client" }],
    ]);
    const tagsOf = railTagsOf([twin], lookup);

    expect(tagsOf(anAgentSession({ observed_session_id: "obs-1" }))).toEqual({
      ticket: "TIP-1576",
      feature: "allianz",
      name: "TIP-1576: Add the fraud-check client",
    });
    expect(tagsOf(anAgentSession({ observed_session_id: null }))).toEqual({
      ticket: null,
      feature: null,
      name: null,
    });
  });
});

describe("SessionRail", () => {
  const routes = {
    "/api/v1/agent-sessions": aPage(sessions),
    "/api/v1/sessions": aPage([]),
    "/api/v1/features": aPage([]),
  };

  it("AC-422.18 marks the current session and links the others to their chat", async () => {
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

  it("AC-422.21 folds to a strip of the open sessions and remembers it", async () => {
    renderWithApi(<SessionRail current="a" />, { routes });
    await userEvent.click(await screen.findByRole("button", { name: "Hide sessions" }));

    expect(window.localStorage.getItem(RAIL_KEY)).toBe("closed");
    expect(screen.getByRole("button", { name: "Show sessions" })).toBeInTheDocument();
    // The strip keeps the open sessions only.
    expect(screen.queryByRole("link", { name: /Old spike/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Fix the guard/ })).toBeInTheDocument();
  });

  it("AC-422.19 narrows the rail with its filter and clears it on Escape", async () => {
    renderWithApi(<SessionRail current="a" />, { routes });
    const filter = await screen.findByRole("searchbox", { name: "Filter sessions" });
    await within(await screen.findByRole("navigation", { name: "Sessions" })).findByRole("link", {
      name: /Old spike/,
    });

    await userEvent.type(filter, "guard");
    expect(screen.queryByRole("link", { name: /Old spike/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Fix the guard/ })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(filter).toHaveValue("");
    expect(screen.getByRole("link", { name: /Old spike/ })).toBeInTheDocument();
  });
});
