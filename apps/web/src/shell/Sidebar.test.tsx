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
  it("lists the destinations in Work, Knowledge and the Hub footer", () => {
    renderSidebar();

    const nav = screen.getByRole("navigation", { name: "Main" });
    const names = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(names).toEqual([
      "Portfolio",
      "Sessions",
      "Workflow runs",
      "Workflows",
      "Features",
      "Learnings",
      "Brain",
      "Toolkit",
      "Health",
      "Settings",
    ]);
    for (const group of ["Work", "Knowledge"]) {
      expect(within(nav).getByText(group)).toBeInTheDocument();
    }
    expect(within(nav).queryByText("Live sessions")).not.toBeInTheDocument();
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
    expect(names.indexOf("Toolkit")).toBe(names.indexOf("Brain") + 1);
    expect(screen.getByRole("link", { name: "Toolkit" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/skills",
    );
  });

  it("points Skills to the project picker when All projects is in scope (nav)", () => {
    renderSidebar("/sessions");

    expect(screen.getByRole("link", { name: "Toolkit" })).toHaveAttribute(
      "href",
      "/knowledge/skills",
    );
  });

  it("marks Skills as the page when a project's skill detail is open (nav)", () => {
    renderSidebar("/projects/other%20hub/skills/skill/hub-workflow/feature?scope=agent-hub");

    const skills = screen.getByRole("link", { name: "Toolkit" });
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
    renderSidebar("/", { counts: { live: 3, learnings: 4, health: 1 } });

    expect(screen.getByRole("link", { name: "Sessions, 3 live" })).toHaveTextContent("3");
    expect(screen.getByRole("link", { name: "Learnings, 4 to triage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Health, 1 doctor error" })).toBeInTheDocument();
  });

  it("caps a badge at 99+ when the count is larger", () => {
    renderSidebar("/", { counts: { live: 120 } });

    expect(screen.getByRole("link", { name: "Sessions, 120 live" })).toHaveTextContent("99+");
  });

  it("pins Health and Settings to the footer, next to Shortcuts", () => {
    const { container } = renderSidebar();

    const foot = container.querySelector(".ah-sidebar-foot");
    expect(foot).not.toBeNull();
    const names = within(foot as HTMLElement)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(names).toEqual(["Health", "Settings"]);
  });

  it("opens the shortcut sheet from its footer button", () => {
    const onShortcuts = vi.fn();
    renderSidebar("/", { onShortcuts });

    screen.getByRole("button", { name: /Shortcuts/ }).click();

    expect(onShortcuts).toHaveBeenCalledOnce();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderSidebar("/", { counts: { live: 1 } });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
