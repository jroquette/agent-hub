import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { Sidebar } from "./Sidebar";

function renderSidebar(path = "/", props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const router = createMemoryRouter(
    [{ path: "*", element: <Sidebar counts={{}} onShortcuts={vi.fn()} {...props} /> }],
    { initialEntries: [path] },
  );
  return render(<RouterProvider router={router} />);
}

describe("Sidebar", () => {
  it("lists the Phase 2 destinations in the design's groups", () => {
    renderSidebar();

    const nav = screen.getByRole("navigation", { name: "Main" });
    const names = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(names).toEqual([
      "Portfolio",
      "Approvals",
      "Live sessions",
      "Sessions",
      "Workflow runs",
      "KnowledgeP3",
      "Learnings",
      "Features",
      "Health",
      "Settings",
    ]);
    for (const group of ["Overview", "Observe", "Understand", "Hub"]) {
      expect(within(nav).getByText(group)).toBeInTheDocument();
    }
  });

  it("tags Knowledge P3 and hides Metrics, Bench, Tracker queue and Workflows", () => {
    renderSidebar();

    const knowledge = screen.getByRole("link", { name: /Knowledge/ });
    expect(within(knowledge).getByText("P3")).toHaveClass("ah-phase");
    for (const hidden of ["Metrics", "Bench", "Tracker queue", "Workflows", "Improve", "Brain"]) {
      expect(screen.queryByText(hidden)).not.toBeInTheDocument();
    }
  });

  it("marks the current destination as the page when its route is open", () => {
    renderSidebar("/sessions/abc");

    expect(screen.getByRole("link", { name: "Sessions" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Portfolio" })).not.toHaveAttribute("aria-current");
  });

  it("shows badge counts and names them when the stream has counts", () => {
    renderSidebar("/", { counts: { approvals: 2, live: 3, learnings: 4, health: 1 } });

    expect(screen.getByRole("link", { name: "Approvals, 2 waiting" })).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: "Live sessions, 3 live" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Learnings, 4 to triage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Health, 1 doctor error" })).toBeInTheDocument();
  });

  it("caps a badge at 99+ when the count is larger", () => {
    renderSidebar("/", { counts: { approvals: 120 } });

    expect(screen.getByRole("link", { name: "Approvals, 120 waiting" })).toHaveTextContent("99+");
  });

  it("opens the shortcut sheet from its footer button", () => {
    const onShortcuts = vi.fn();
    renderSidebar("/", { onShortcuts });

    screen.getByRole("button", { name: /Shortcuts/ }).click();

    expect(onShortcuts).toHaveBeenCalledOnce();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderSidebar("/", { counts: { approvals: 2, live: 1 } });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
