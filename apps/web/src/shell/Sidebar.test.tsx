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
      "Knowledge",
      "Learnings",
      "Brain",
      "Skills",
      "Features",
      "Workflows",
      "Health",
      "Settings",
    ]);
    for (const group of ["Overview", "Observe", "Understand", "Improve", "Hub"]) {
      expect(within(nav).getByText(group)).toBeInTheDocument();
    }
  });

  it("has no P3 tag and hides Metrics, Bench and Tracker queue", () => {
    const { container } = renderSidebar();

    expect(container.querySelector(".ah-phase")).toBeNull();
    expect(screen.getByRole("link", { name: "Learnings" })).toHaveTextContent(/^Learnings$/);
    for (const hidden of ["Metrics", "Bench", "Tracker queue"]) {
      expect(screen.queryByText(hidden)).not.toBeInTheDocument();
    }
  });

  it("shows Brain under Knowledge for the project in scope", () => {
    renderSidebar("/sessions?scope=agent-hub");

    expect(screen.getByRole("link", { name: "Brain" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain",
    );
  });

  it("points Brain to the project picker when All projects is in scope", () => {
    renderSidebar("/sessions");

    expect(screen.getByRole("link", { name: "Brain" })).toHaveAttribute("href", "/knowledge/brain");
  });

  it("marks Brain as the page when a project's brain note is open", () => {
    renderSidebar("/projects/other%20hub/brain/decisions/index.md?scope=agent-hub");

    const brain = screen.getByRole("link", { name: "Brain" });
    expect(brain).toHaveAttribute("href", "/projects/other%20hub/brain");
    expect(brain).toHaveAttribute("aria-current", "page");
  });

  it("shows Skills right after Brain for the project in scope (nav, AC-164.13)", () => {
    renderSidebar("/sessions?scope=agent-hub");

    const nav = screen.getByRole("navigation", { name: "Main" });
    const names = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(names.indexOf("Skills")).toBe(names.indexOf("Brain") + 1);
    expect(screen.getByRole("link", { name: "Skills" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/skills",
    );
  });

  it("points Skills to the project picker when All projects is in scope (nav)", () => {
    renderSidebar("/sessions");

    expect(screen.getByRole("link", { name: "Skills" })).toHaveAttribute(
      "href",
      "/knowledge/skills",
    );
  });

  it("marks Skills as the page when a project's skill detail is open (nav)", () => {
    renderSidebar("/projects/other%20hub/skills/skill/hub-workflow/feature?scope=agent-hub");

    const skills = screen.getByRole("link", { name: "Skills" });
    expect(skills).toHaveAttribute("href", "/projects/other%20hub/skills");
    expect(skills).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Brain" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain",
    );
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
