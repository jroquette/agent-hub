import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import {
  AsOfStamp,
  BudgetBar,
  DerivedLabel,
  ExpiredContent,
  ExternalLabel,
  MiniStageBar,
  ProvenanceBadge,
  StageChip,
  StagePipeline,
  StatusBadge,
} from "./status";

describe("StatusBadge", () => {
  it("shows an icon and a label, never colour alone", () => {
    const { container } = render(<StatusBadge status="failed" />);

    expect(screen.getByText("Failed")).toHaveClass("ah-badge", "ah-badge-failed");
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("pulses for live and running", () => {
    const { container } = render(<StatusBadge status="running" />);

    expect(container.querySelector(".ah-pulse")).not.toBeNull();
    expect(screen.getByText("Running")).toHaveClass("ah-badge-live");
  });

  it("labels an inferred end", () => {
    render(<StatusBadge status="ended" inferred quiet />);

    const badge = screen.getByText(/Ended/);
    expect(badge).toHaveTextContent("Ended · inferred");
    expect(badge).toHaveAttribute("title", "Ended (inferred: no end event received)");
    expect(badge).toHaveClass("ah-badge-quiet", "ah-badge-inferred");
  });
});

describe("stages", () => {
  it("labels stage chips by state", () => {
    render(
      <>
        <StageChip stage="VERIFYING" failed />
        <StageChip stage="PR_OPEN" state="done" />
        <StageChip stage="PICKED" state="waiting" />
        <StageChip stage="REPORTED" state="pending" />
        <StageChip stage="IMPLEMENTING" />
      </>,
    );

    expect(screen.getByText("Failed · Verifying")).toHaveClass("ah-stage-failed");
    expect(screen.getByText("PR open")).toHaveClass("ah-stage-done");
    expect(screen.getByText("Implementing")).toHaveClass("ah-stage-active");
  });

  it("shows attempts, loops and notes of pipeline steps, and selects one", () => {
    const onSelect = vi.fn();
    render(
      <StagePipeline
        onSelect={onSelect}
        selected="verify"
        steps={[
          { id: "pick", label: "Pick", state: "done", duration: 30 },
          {
            id: "verify",
            label: "Verify",
            state: "failed",
            duration: 192,
            attempt: 2,
            maxAttempts: 2,
            loop: "looped back from verify",
            note: "make check failed",
          },
          { id: "pr", label: "PR", state: "pending" },
        ]}
      />,
    );

    expect(screen.getByText(/3 min 12 s · attempt 2 of 2/)).toBeInTheDocument();
    expect(screen.getByText("looped back from verify")).toBeInTheDocument();
    expect(screen.getByText("not started")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));
    expect(onSelect).toHaveBeenCalledWith("verify");
  });

  it("renders steps without buttons when nothing can be selected", () => {
    render(<StagePipeline steps={[{ id: "a", label: "A", state: "active", attempts: 3 }]} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/attempt 3 of 3/)).toBeInTheDocument();
  });

  it("describes runs in progress per stage", () => {
    render(<MiniStageBar counts={{ IMPLEMENTING: 1, PR_OPEN: 2 }} failed={1} waiting="PR_OPEN" />);

    expect(
      screen.getByRole("img", { name: "Runs in progress: 1 implementing, 2 pr open" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tooltip")).toHaveTextContent("; 1 failed");
  });

  it("says no runs are in progress when the counts are empty", () => {
    render(<MiniStageBar />);

    expect(
      screen.getByRole("img", { name: "Runs in progress: No runs in progress" }),
    ).toBeInTheDocument();
  });
});

describe("BudgetBar", () => {
  it.each([
    [1, "ok"],
    [4, "warn"],
    [6, "over"],
  ])("turns amber at 80 %% and red at 100 %% (spent %d of 5)", (spent, level) => {
    const { container } = render(<BudgetBar spent={spent} budget={5} projection="Projected $6" />);

    expect(container.querySelector(".ah-budget")).toHaveAttribute("data-level", level);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", String(spent));
  });
});

describe("trust labels", () => {
  it("explains derived values", () => {
    render(<DerivedLabel how="Folded from events" />);

    expect(screen.getByText("Derived")).toHaveClass("ah-derived");
    expect(screen.getByRole("tooltip")).toHaveTextContent("Folded from events");
  });

  it("warns about external provenance", () => {
    render(<ProvenanceBadge provenance="agent-from-external" />);

    expect(screen.getByText("agent-from-external")).toHaveClass("ah-prov-external");
  });

  it("labels external content and expired content", () => {
    render(
      <>
        <ExternalLabel source="Issue comment" />
        <ExpiredContent date="2026-11-10" what="Transcript" />
      </>,
    );

    expect(screen.getByText("Issue comment · not verified")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Transcript expired 2026-11-10.");
  });

  it("shows fresh and stale stamps", () => {
    const { rerender } = render(<AsOfStamp time="14:02" source="hooks" />);
    expect(screen.getByText("Updated 14:02")).toHaveClass("ah-asof-fresh");

    rerender(<AsOfStamp time="14:02" stale />);
    expect(screen.getByText("Stale · as of 14:02")).not.toHaveClass("ah-asof-fresh");
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = render(
      <div>
        <StatusBadge status="waiting" />
        <DerivedLabel />
        <ProvenanceBadge provenance="human" />
        <BudgetBar spent={1} budget={2} />
        <MiniStageBar counts={{ PICKED: 1 }} />
        <AsOfStamp time="14:02" />
      </div>,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
