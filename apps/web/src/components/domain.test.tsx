import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import {
  AcTable,
  ActivityFeed,
  ApprovalPanel,
  FindingRow,
  FrontmatterChips,
  GoldenPathStepper,
  NeedsYouList,
  ProjectCard,
  SessionTile,
  type LiveSession,
  type ProjectCardData,
} from "./domain";

function inRouter(ui: ReactElement) {
  const router = createMemoryRouter([{ path: "*", element: ui }]);
  return render(<RouterProvider router={router} />);
}

const tile: LiveSession = {
  id: "s1",
  status: "live",
  title: "AGH-48 · /feature",
  detail: "agent-hub · dev/agh-48-live-tiles",
  project: "agent-hub",
  repo: "agent-hub",
  issue: "AGH-48",
  step: "verify",
  lastAction: "make check-fast",
  lastAgo: "3 s ago",
  elapsed: 600,
  turns: 12,
  tokens: 48_200,
  files: 4,
  cost: 1.5,
  problems: "Needs you: command_exit in make check-fast",
  needsYou: true,
  denials: 1,
  activity: [0, 1, 2],
};

const card: ProjectCardData = {
  name: "agent-hub",
  hub: "agent-hub-hub",
  team: "AGH",
  version: "0.4.0",
  lockVersion: "0.3.0",
  syncPending: true,
  repos: ["agent-hub"],
  health: "warning",
  healthLabel: "1 warning",
  live: 2,
  runsInProgress: 1,
  stages: { IMPLEMENTING: 1 },
  prs: null,
  failed7d: 1,
  ready: null,
  cost: 10.5,
  costDelta: "+31 %",
  costDeltaTone: "bad",
  costSpark: [1, 2, 3],
  costPrev: [1, 1, 1],
};

describe("SessionTile", () => {
  it("shows the session label, last action, stats, problems and denials when a problem needs you", () => {
    const onOpen = vi.fn();
    render(<SessionTile s={tile} onOpen={onOpen} />);

    const article = screen.getByRole("article", {
      name: "AGH-48 · /feature in agent-hub, live",
    });
    expect(article).toHaveAttribute("data-trouble", "true");
    expect(screen.getByText("agent-hub › agent-hub · run step verify")).toBeInTheDocument();
    expect(screen.getByText("48 k")).toBeInTheDocument();
    expect(screen.getByText("$1.50")).toBeInTheDocument();
    expect(screen.getByText("agent-hub · dev/agh-48-live-tiles")).toBeInTheDocument();
    expect(screen.getByText("Needs you: command_exit in make check-fast")).toBeInTheDocument();
    fireEvent.keyDown(article, { key: "Enter" });
    fireEvent.click(article);
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("shows the waiting reason, the budget and the last events on hover", () => {
    render(
      <SessionTile
        s={{
          ...tile,
          status: "waiting",
          reason: "Guard asks to edit a migration",
          budget: 5,
          problems: null,
          needsYou: false,
        }}
        hoverEvents={[{ time: "14:02", icon: "terminal", text: "make check" }]}
      />,
    );

    expect(screen.getByText("Guard asks to edit a migration")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByRole("article"));
    expect(screen.getByText("Last 5 events")).toBeInTheDocument();
    fireEvent.mouseLeave(screen.getByRole("article"));
    expect(screen.queryByText("Last 5 events")).not.toBeInTheDocument();
  });

  it("labels an ended session by its outcome", () => {
    render(<SessionTile s={{ ...tile, status: "ended", outcome: "done", needsYou: false }} />);

    expect(screen.getByText("Ended · done")).toBeInTheDocument();
  });

  it("has no red edge when the agent handled its problems", () => {
    render(
      <SessionTile
        s={{ ...tile, detail: null, problems: "2 problems, handled by the agent", needsYou: false }}
      />,
    );

    expect(screen.getByRole("article")).not.toHaveAttribute("data-trouble");
    expect(screen.getByText("2 problems, handled by the agent")).toBeInTheDocument();
  });
});

describe("NeedsYouList", () => {
  it("lists verb-first items with links and a more line", () => {
    inRouter(
      <NeedsYouList
        since="Since your last visit · 08:12"
        more={2}
        moreLabel="2 more: 1 doctor error, 1 learning"
        items={[
          {
            kind: "approval",
            verb: "Approve plan",
            context: "AGH-48",
            age: "2 h",
            href: "/approvals/a1",
          },
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: /Approve plan/ })).toHaveAttribute(
      "href",
      "/approvals/a1",
    );
    expect(screen.getByText("3")).toHaveAttribute("data-tone", "waiting");
    expect(screen.getByRole("link", { name: /2 more/ })).toBeInTheDocument();
  });

  it("says nothing needs you when empty", () => {
    inRouter(<NeedsYouList items={[]} liveCount={1} />);

    expect(screen.getByText(/Nothing needs you\./)).toBeInTheDocument();
    expect(screen.getByText(/1 session running/)).toBeInTheDocument();
  });
});

describe("ProjectCard and ActivityFeed", () => {
  it("shows dashes for unconnected sources and the sync badge", () => {
    const onOpen = vi.fn();
    render(<ProjectCard p={card} onOpen={onOpen} />);

    expect(screen.getByText("Sync pending")).toHaveAttribute("title", "hub.lock 0.3.0, pin 0.4.0");
    expect(screen.getByText("Open PRs").nextElementSibling).toHaveAttribute(
      "title",
      "GitHub is not connected in this version.",
    );
    expect(screen.getByText("Ready issues").nextElementSibling).toHaveTextContent("—");
    fireEvent.keyDown(screen.getByRole("article"), { key: "Enter" });
    expect(onOpen).toHaveBeenCalled();
  });

  it("shows a card with no health and an empty cost series", () => {
    render(
      <ProjectCard
        p={{
          ...card,
          health: null,
          costSpark: [],
          prs: 2,
          ready: 4,
          ciLabel: "CI passing",
          ciTone: "done",
          live: 0,
        }}
      />,
    );

    expect(screen.getByRole("img", { name: "1 warning" })).toBeInTheDocument();
    expect(screen.getByText("CI passing")).toBeInTheDocument();
  });

  it("lists activity with project and age", () => {
    render(
      <ActivityFeed
        items={[
          { kind: "reported", text: "Run AGH-48 reported", project: "agent-hub", age: "2 h" },
        ]}
      />,
    );

    expect(screen.getByText("Run AGH-48 reported")).toBeInTheDocument();
  });
});

describe("FrontmatterChips", () => {
  it("shows every chip and the stale tone when the note was verified over 60 days ago", () => {
    render(
      <FrontmatterChips
        fm={{
          type: "spec",
          status: "draft",
          repos: ["agent-hub"],
          last_verified: "2026-01-01",
          daysSinceVerified: 90,
          provenance: "agent",
        }}
      />,
    );

    expect(screen.getByText("spec")).toBeInTheDocument();
    expect(screen.getByText("draft")).toBeInTheDocument();
    expect(screen.getByText("agent-hub")).toBeInTheDocument();
    expect(screen.getByText("last verified").parentElement).toHaveAttribute("data-tone", "stale");
  });

  it("shows fresh frontmatter without the stale tone", () => {
    render(<FrontmatterChips fm={{ last_verified: "2026-10-01", daysSinceVerified: 3 }} />);

    expect(screen.getByText("last verified").parentElement).not.toHaveAttribute("data-tone");
  });
});

describe("AcTable, ApprovalPanel, GoldenPathStepper, FindingRow", () => {
  it("shows passing, failing and owner-step criteria", () => {
    render(
      <AcTable
        acs={[
          { id: "AC-1", description: "a", repo: "agent-hub", passes: true, command: "npm test" },
          { id: "AC-2", description: "b", repo: null, passes: false },
          {
            id: "AC-3",
            description: "c",
            repo: null,
            passes: false,
            manual: true,
            evidence: "owner",
          },
        ]}
      />,
    );

    expect(screen.getByRole("cell", { name: "Passes" })).toBeInTheDocument();
    expect(screen.getByText("Fails")).toBeInTheDocument();
    expect(screen.getByText("Owner step")).toBeInTheDocument();
  });

  it("explains terminal approval in Phase 2 and disables Phase 4 actions", () => {
    const approval = {
      title: "Approve the plan",
      waiting: "2 h",
      kindLabel: "Plan",
      issue: "AGH-48",
      requestedBy: "hub-workflow:planner",
      session: "5091b986-0000-7000-8000-000000000001",
      project: "agent-hub",
      repo: "agent-hub",
      changes: [{ text: "Implementation starts" }],
    };
    const { rerender } = render(<ApprovalPanel a={approval} />);
    expect(screen.getByText(/Approve in the terminal session that asked/)).toHaveTextContent(
      "session 5091b986",
    );

    rerender(<ApprovalPanel a={approval} phase="P4" />);
    expect(screen.getByRole("button", { name: /Approve plan/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Reject/ })).toBeDisabled();
  });

  it("marks golden path steps", () => {
    render(
      <GoldenPathStepper
        steps={[
          { name: "Spec", state: "done", date: "2026-10-01", by: "owner" },
          { name: "Plan", state: "current" },
          { name: "Ship", state: "pending" },
        ]}
      />,
    );

    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows a finding with its location and how to fix it", () => {
    inRouter(
      <>
        <FindingRow
          f={{
            severity: "error",
            rule: "lock.in_sync",
            ruleHelp: "hub.lock matches",
            path: "hub.lock",
            line: 3,
            href: "/health?finding=1",
            message: "Stale lock",
            fix: "Run ./hub sync",
          }}
        />
        <FindingRow f={{ severity: "info", rule: "x", path: "a.md", message: "m", fix: "f" }} />
        <FindingRow f={{ severity: "warning", rule: "y", message: "m", fix: "f" }} />
      </>,
    );

    expect(screen.getByRole("link", { name: "hub.lock:3" })).toHaveAttribute(
      "href",
      "/health?finding=1",
    );
    expect(screen.getByText("a.md")).toBeInTheDocument();
    expect(screen.getAllByText("How to fix")).toHaveLength(3);
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = inRouter(
      <div>
        <SessionTile s={tile} />
        <ProjectCard p={card} />
        <NeedsYouList items={[]} />
        <AcTable acs={[{ id: "AC-1", description: "a", repo: null, passes: true }]} />
      </div>,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
