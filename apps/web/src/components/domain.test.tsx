import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { aGoldenPath, aGoldenStep } from "../testing/builders";
import {
  AcTable,
  ActivityFeed,
  ApprovalPanel,
  FindingRow,
  FrontmatterChips,
  GOLDEN_STEP_LABEL,
  GoldenPathStepper,
  goldenStepSummary,
  ownerWaitStep,
  shownGoldenSteps,
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

  it("shows the waiting reason, the cost so far and the last events on hover", () => {
    render(
      <SessionTile
        s={{
          ...tile,
          status: "waiting",
          reason: "Guard asks to edit a migration",
          problems: null,
          needsYou: false,
        }}
        hoverEvents={[{ time: "14:02", icon: "terminal", text: "make check" }]}
      />,
    );

    expect(screen.getByText("Guard asks to edit a migration")).toBeInTheDocument();
    expect(screen.getByText("Cost so far")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    // @ts-expect-error A tile has no run budget since Live sessions retired (ADR 0033 D8).
    expect(<SessionTile s={{ ...tile, budget: 5 }} />).toBeTruthy();
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

  it("shows the failing notice and the waiting link, which opens without opening the tile", async () => {
    const onOpen = vi.fn();
    inRouter(
      <SessionTile
        s={{
          ...tile,
          status: "waiting",
          notice: "make check failed 2 times",
          link: { href: "/agent-sessions/a1", label: "Open chat" },
          chat: true,
        }}
        onOpen={onOpen}
      />,
    );

    expect(await screen.findByText("make check failed 2 times")).toBeInTheDocument();
    expect(screen.getByText("Chat")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open chat" });
    expect(link).toHaveAttribute("href", "/agent-sessions/a1");
    fireEvent.click(link);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("shows blanks for the stats a driven session does not know, and no sparkline once ended", () => {
    render(<SessionTile s={{ ...tile, status: "ended", turns: null, files: null }} />);

    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.queryByRole("img", { name: "Events per 5 s, last 60 s" })).toBeNull();
    expect(screen.queryByText("Chat")).toBeNull();
  });

  it("shows the sparkline while the session runs", () => {
    render(<SessionTile s={tile} />);

    expect(screen.getByRole("img", { name: "Events per 5 s, last 60 s" })).toBeInTheDocument();
  });
});

describe("NeedsYouList", () => {
  it("lists verb-first items with links and a more line", () => {
    inRouter(
      <NeedsYouList
        since="Since your last visit · 08:12"
        more={2}
        moreLabel="2 more: 1 doctor error, 1 learning"
        moreHref="/?needs=all"
        items={[
          {
            kind: "approval",
            verb: "Approve plan",
            context: "AGH-48",
            age: "2 h",
            href: "/sessions/s1",
          },
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: /Approve plan/ })).toHaveAttribute(
      "href",
      "/sessions/s1",
    );
    expect(screen.getByText("3")).toHaveAttribute("data-tone", "waiting");
    expect(screen.getByRole("link", { name: /2 more/ })).toHaveAttribute("href", "/?needs=all");
  });

  it("shows no more line when there is nowhere to go", () => {
    inRouter(
      <NeedsYouList
        more={2}
        items={[{ kind: "failed", verb: "Check", context: "r1", age: "1 h", href: "/runs/r1" }]}
      />,
    );

    expect(screen.queryByRole("link", { name: /2 more/ })).toBeNull();
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
    expect(screen.getByText(/GitHub and Linear are not connected/)).toBeInTheDocument();
    expect(screen.getByText("Doctor warnings")).toBeInTheDocument();
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

describe("AcTable, ApprovalPanel, FindingRow", () => {
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

/** The owner's case (AC-136.14): 17 tickets, 1 merged, one SHIP eval over 3 of 36 ACs. */
const ownerCase = aGoldenPath({
  phase: "build",
  steps: [
    aGoldenStep({ name: "spec", state: "done", meta: null, progress: null }),
    aGoldenStep({
      name: "ux_design",
      state: "skipped",
      meta: "No screen change recorded",
      progress: null,
    }),
    aGoldenStep({ name: "research", state: "skipped", meta: null, progress: null }),
    aGoldenStep({ name: "plan", state: "done", meta: "v1", progress: null }),
    aGoldenStep({
      name: "tickets",
      state: "done",
      meta: "17 of 17 created",
      progress: { done: 17, total: 17 },
    }),
    aGoldenStep({
      name: "build",
      state: "current",
      meta: "1 of 17 merged · 16 in progress",
      progress: { done: 1, total: 17 },
    }),
    aGoldenStep({
      name: "acceptance",
      state: "partial",
      meta: "Ticket evals cover 3 of 36 ACs",
      reason: "Build is not done",
      progress: { done: 3, total: 36 },
    }),
    aGoldenStep({
      name: "shipped",
      state: "pending",
      meta: null,
      reason: "Build is not done",
      progress: null,
    }),
  ],
});

describe("GoldenPathStepper", () => {
  it("shows each step's state as text with its meta and reason (golden)", () => {
    render(<GoldenPathStepper steps={ownerCase.steps} />);

    const steps = screen.getAllByRole("listitem");
    expect(steps.map((li) => li.dataset.state)).toEqual([
      "done",
      "skipped",
      "skipped",
      "done",
      "done",
      "current",
      "partial",
      "pending",
    ]);
    // Only the step in focus (the first not done) shows its meta; the rest is on demand.
    const metaOf = (li: HTMLElement | undefined) =>
      [...(li?.querySelectorAll(".ah-golden-meta") ?? [])].map((m) => m.textContent);
    expect(metaOf(steps[0])).toEqual(["Done"]);
    expect(metaOf(steps[5])).toEqual(["In progress", "1 of 17 merged · 16 in progress"]);
    expect(metaOf(steps[6])).toEqual(["Partial"]);
    expect(metaOf(steps[7])).toEqual(["Not reached"]);
    // Every step's meta and reason stay in its description (and tooltip).
    expect(
      screen.getByText("Shipped", { selector: ".ah-golden-name" }),
    ).toHaveAccessibleDescription("Shipped: not reached (Build is not done)");
    expect(
      screen.getByText("Acceptance", { selector: ".ah-golden-name" }),
    ).toHaveAccessibleDescription(
      "Acceptance: partial · Ticket evals cover 3 of 36 ACs (Build is not done)",
    );
  });

  it("shows the count of the step in focus when it has no meta (golden)", () => {
    render(
      <GoldenPathStepper
        steps={[aGoldenStep({ name: "build", meta: null, progress: { done: 2, total: 8 } })]}
      />,
    );

    expect(screen.getByRole("listitem")).toHaveTextContent("2/8");
  });

  it("reads an owner wait as waiting on you", () => {
    render(
      <GoldenPathStepper
        steps={[
          aGoldenStep({
            name: "acceptance",
            state: "current",
            meta: "Waiting on you: sign off 2 ACs",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Waiting on you: sign off 2 ACs")).toBeInTheDocument();
  });

  it("labels the eight feature steps (AC-1.1)", () => {
    expect(GOLDEN_STEP_LABEL).toEqual({
      spec: "Spec",
      ux_design: "UX design",
      research: "Research",
      plan: "Plan",
      tickets: "Tickets",
      build: "Build",
      acceptance: "Acceptance",
      shipped: "Shipped",
    });
    expect(Object.keys(GOLDEN_STEP_LABEL)).toEqual(aGoldenPath().steps.map((step) => step.name));
  });

  it("shows Not recorded for an unrecorded step (AC-1.6)", () => {
    render(
      <GoldenPathStepper
        steps={[
          aGoldenStep({
            name: "acceptance",
            state: "unrecorded",
            meta: "Ticket evals cover 6 of 23 ACs",
            reason: "no whole-feature eval yet",
          }),
        ]}
      />,
    );

    const step = screen.getByRole("listitem");
    expect(step).toHaveTextContent("Not recorded");
    expect(step).toHaveTextContent("Ticket evals cover 6 of 23 ACs");
    expect(
      screen.getByText("Acceptance", { selector: ".ah-golden-name" }),
    ).toHaveAccessibleDescription(
      "Acceptance: not recorded · Ticket evals cover 6 of 23 ACs (no whole-feature eval yet)",
    );
  });

  it("finds the acceptance step waiting on the owner (ownerWaitStep)", () => {
    const waiting = aGoldenStep({
      name: "acceptance",
      state: "current",
      meta: "Waiting on you: sign off 2 ACs",
      reason: "2 ACs wait on owner steps (SHIP-WITH-OWNER-STEPS)",
    });

    expect(ownerWaitStep([aGoldenStep(), waiting])).toBe(waiting);
    expect(
      ownerWaitStep([
        aGoldenStep({ name: "acceptance", state: "done", meta: "Owner steps signed off" }),
      ]),
    ).toBeNull();
    expect(ownerWaitStep([aGoldenStep({ meta: "Waiting on you: sign off 2 ACs" })])).toBeNull();
    // No AC to sign off: the step waits, but there is nothing for the sign-off to write.
    expect(
      ownerWaitStep([
        aGoldenStep({
          name: "acceptance",
          state: "current",
          meta: "Waiting on owner steps · no ACs listed",
        }),
      ]),
    ).toBeNull();
    // Reopened ACs need a new evaluation (A11): no sign-off that the API would refuse.
    expect(
      ownerWaitStep([
        aGoldenStep({
          name: "acceptance",
          state: "current",
          meta: "3 ACs reopened · evaluate again",
        }),
      ]),
    ).toBeNull();
  });

  it("never shows a step done after a gate that is not done (golden)", () => {
    const steps = [
      aGoldenStep({ name: "build", state: "current", reason: null }),
      aGoldenStep({ name: "acceptance", state: "done", meta: null, reason: null }),
      aGoldenStep({ name: "shipped", state: "done", meta: null, reason: null }),
    ];

    expect(shownGoldenSteps(steps).map((s) => [s.state, s.reason])).toEqual([
      ["current", null],
      ["blocked", "Build is not done"],
      ["blocked", "Build is not done"],
    ]);
    render(<GoldenPathStepper steps={steps} />);
    expect(screen.getAllByRole("listitem").map((li) => li.dataset.state)).toEqual([
      "current",
      "blocked",
      "blocked",
    ]);
  });

  it("keeps done after skipped and done steps (golden)", () => {
    const steps = [
      aGoldenStep({ name: "spec", state: "done" }),
      aGoldenStep({ name: "research", state: "skipped" }),
      aGoldenStep({ name: "plan", state: "done" }),
    ];

    expect(shownGoldenSteps(steps).map((s) => s.state)).toEqual(["done", "skipped", "done"]);
  });

  it("summarises a step in one line (golden)", () => {
    expect(goldenStepSummary(ownerCase.steps[6] ?? aGoldenStep())).toBe(
      "Acceptance: partial · Ticket evals cover 3 of 36 ACs (Build is not done)",
    );
    expect(
      goldenStepSummary(aGoldenStep({ name: "spec", state: "done", meta: null, progress: null })),
    ).toBe("Spec: done");
  });

  it("draws a given step list with given labels, vertically, its open step disclosed", async () => {
    const onSelect = vi.fn();
    render(
      <GoldenPathStepper
        steps={[
          { name: "context", state: "unrecorded", meta: null },
          { name: "implement", state: "done", meta: null },
          { name: "review", state: "current", meta: "Changes requested" },
        ]}
        labels={{ context: "Context", implement: "Implement", review: "Review" }}
        label="Ticket steps"
        vertical
        open="review"
        detail={(step) => `Details of ${step.name}`}
        onSelect={onSelect}
        selectLabel={(step) => `${step}, show details`}
      />,
    );

    const list = screen.getByRole("list", { name: "Ticket steps" });
    expect(list).toHaveAttribute("data-orientation", "vertical");
    const steps = within(list).getAllByRole("listitem");
    // A step left without a record before later evidence is no gate: Implement stays done.
    expect(steps.map((li) => li.dataset.state)).toEqual(["unrecorded", "done", "current"]);
    // Vertically, every step says its state and meta.
    const metaOf = (li: HTMLElement | undefined) =>
      [...(li?.querySelectorAll(".ah-golden-meta") ?? [])].map((m) => m.textContent);
    expect(steps.map((li) => li.querySelector(".ah-golden-name")?.textContent)).toEqual([
      "Context",
      "Implement",
      "Review",
    ]);
    expect(metaOf(steps[0])).toEqual(["Not recorded"]);
    expect(metaOf(steps[2])).toEqual(["In progress", "Changes requested"]);
    const review = screen.getByRole("button", { name: "review, show details" });
    expect(review).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "context, show details" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByText("Details of review")).toBeInTheDocument();
    expect(screen.queryByText("Details of context")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "context, show details" }));
    expect(onSelect).toHaveBeenCalledWith("context");
  });

  it("has no serious axe violation (golden a11y)", async () => {
    const { container } = render(<GoldenPathStepper steps={ownerCase.steps} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
