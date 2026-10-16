import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../testing/axe";
import { aPage, aProjectSummary, aStreamCounts, renderWithApi } from "../testing/builders";
import { AppShell } from "./AppShell";

const routes = { "/api/v1/projects": aPage([aProjectSummary()]) };

describe("AppShell", () => {
  it("places the sidebar, top bar and page content", () => {
    renderWithApi(<AppShell />, { routes });

    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("shows the stream's counts as badges when they arrive", () => {
    const { stream } = renderWithApi(<AppShell />, { routes });

    act(() => {
      stream("/api/v1/events/stream").open();
      stream("/api/v1/events/stream").emit("counts", aStreamCounts({ live_sessions: 2 }));
    });

    expect(screen.getByRole("link", { name: "Sessions, 2 live" })).toBeInTheDocument();
    expect(within(screen.getByRole("banner")).getByRole("status")).toHaveAttribute(
      "data-state",
      "connected",
    );
  });

  it("opens the palette with Ctrl K and the shortcut sheet with ?", () => {
    renderWithApi(<AppShell />, { routes });

    fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "?" });
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
  });

  it("goes to a destination with a g sequence", () => {
    const { router } = renderWithApi(<AppShell />, { routes });

    fireEvent.keyDown(document.body, { key: "g" });
    fireEvent.keyDown(document.body, { key: "l" });

    expect(router.state.location.pathname).toBe("/live");
  });

  it("ignores single-key shortcuts while typing in a field", () => {
    const { router } = renderWithApi(
      <AppShell>
        <input aria-label="filter" />
      </AppShell>,
      { routes },
    );
    const input = screen.getByRole("textbox", { name: "filter" });

    fireEvent.keyDown(input, { key: "g" });
    fireEvent.keyDown(input, { key: "s" });

    expect(router.state.location.pathname).toBe("/");
  });

  it("skips a key a screen already handled", () => {
    const { router } = renderWithApi(
      <AppShell>
        <button
          type="button"
          onKeyDown={(event) => {
            event.preventDefault();
          }}
        >
          handles its keys
        </button>
      </AppShell>,
      { routes },
    );
    const own = screen.getByRole("button", { name: "handles its keys" });

    fireEvent.keyDown(own, { key: "g" });
    fireEvent.keyDown(own, { key: "l" });
    fireEvent.keyDown(own, { key: "t" });

    expect(router.state.location.pathname).toBe("/");
    expect(screen.getByRole("button", { name: "UTC" })).toHaveAttribute("aria-pressed", "false");
  });

  it("toggles UTC with t and collapses the sidebar from the top bar", () => {
    renderWithApi(<AppShell />, { routes });

    fireEvent.keyDown(document.body, { key: "t" });
    expect(screen.getByRole("button", { name: "UTC" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(document.querySelector(".ah-shell")).toHaveAttribute("data-collapsed", "true");
  });

  it("cycles the theme from the top bar", () => {
    window.localStorage.setItem("ah.theme", "light");
    renderWithApi(<AppShell />, { routes });

    fireEvent.click(screen.getByRole("button", { name: "Theme: light" }));

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Theme: dark" })).toBeInTheDocument();
    window.localStorage.clear();
  });

  it("switches the project scope from the switcher", async () => {
    const { router } = renderWithApi(<AppShell />, { routes, path: "/sessions" });

    fireEvent.click(screen.getByRole("button", { name: /All projects/ }));
    fireEvent.click(await screen.findByRole("button", { name: /agent-hub · 1 live/ }));

    expect(router.state.location.search).toBe("?scope=agent-hub");
    window.localStorage.clear();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderWithApi(<AppShell />, { routes });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("AppShell scope on a project's Brain or Skills", () => {
  const scoped = {
    "/api/v1/projects": aPage([
      aProjectSummary({ name: "demo" }),
      aProjectSummary({ name: "agent-hub" }),
    ]),
  };
  const switcher = () =>
    within(screen.getByRole("banner")).getByRole("button", {
      expanded: false,
      name: /demo|agent-hub|All projects/,
    });

  it("shows the project in the route, not the stored scope", () => {
    renderWithApi(<AppShell />, {
      routes: scoped,
      path: "/projects/demo/skills?scope=agent-hub",
      route: "*",
    });

    expect(switcher()).toHaveTextContent("demo");
  });

  it("opens the same section of the project picked in the switcher", async () => {
    const { router } = renderWithApi(<AppShell />, {
      routes: scoped,
      path: "/projects/demo/brain/now.md",
      route: "*",
    });

    fireEvent.click(switcher());
    fireEvent.click(await screen.findByRole("button", { name: /^agent-hub ·/ }));

    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain");
  });

  it("opens the section's project index when All projects is picked", async () => {
    const { router } = renderWithApi(<AppShell />, {
      routes: scoped,
      path: "/projects/demo/skills",
      route: "*",
    });

    fireEvent.click(switcher());
    fireEvent.click(await screen.findByRole("button", { name: /^All projects/ }));

    expect(router.state.location.pathname).toBe("/knowledge/skills");
  });
});
