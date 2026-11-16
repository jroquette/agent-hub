import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { StepBar } from "./StepBar";

const steps = [
  { state: "done", summary: "Spec: done" },
  { state: "skipped", summary: "UX design: skipped · No screen change recorded" },
  { state: "done", summary: "Research: done" },
  { state: "done", summary: "Plan: done · v1" },
  { state: "done", summary: "Tickets: done · 3 of 3 created" },
  { state: "current", summary: "Build: in progress · 1 of 3 merged" },
  { state: "partial", summary: "Acceptance: partial · 3/66 (Build is not done)" },
  { state: "blocked", summary: "Shipped: blocked (Build is not done)" },
] as const;

describe("StepBar", () => {
  it("draws one segment per step in its state", () => {
    const { container } = render(
      <StepBar name="Golden path" label="Build" current={5} steps={steps} />,
    );

    expect(
      [...container.querySelectorAll("[data-state]")].map((el) => el.getAttribute("data-state")),
    ).toEqual(["done", "skipped", "done", "done", "done", "current", "partial", "blocked"]);
  });

  it("labels the current step with its position, '<Step> · n/N'", () => {
    render(<StepBar name="Golden path" label="Build" current={5} steps={steps} />);

    expect(screen.getByRole("img").parentElement).toHaveTextContent(/^Build · 6\/8$/);
  });

  it("reads the last step alone, with no position, once it is done", () => {
    const shipped = steps.map((step) => ({ ...step, state: "done" as const }));
    render(<StepBar name="Golden path" label="Shipped" current={7} steps={shipped} />);

    expect(screen.getByRole("img").parentElement).toHaveTextContent(/^Shipped$/);
  });

  it.each(["pending", "unknown"] as const)(
    "keeps the position on the last step while it is %s",
    (state) => {
      const last = [...steps.slice(0, 7), { state, summary: "Merged: not reached" }];
      render(<StepBar name="Ticket steps" label="Merged" current={7} steps={last} />);

      expect(screen.getByRole("img").parentElement).toHaveTextContent(/^Merged · 8\/8$/);
    },
  );

  it("adds the current step's note after its position", () => {
    render(
      <StepBar
        name="Ticket steps"
        label="Build"
        current={5}
        steps={steps}
        note="Changes requested"
      />,
    );

    expect(screen.getByRole("img").parentElement).toHaveTextContent(
      /^Build · 6\/8 · Changes requested$/,
    );
  });

  it("is an image named by the current step and every step's summary, also in its tooltip", () => {
    render(<StepBar name="Golden path" label="Build" current={5} steps={steps} />);

    expect(screen.getByRole("img")).toHaveAccessibleName(
      `Golden path: Build. ${steps.map((s) => s.summary).join("; ")}`,
    );
    expect(screen.getByRole("img")).not.toHaveAttribute("tabindex");
    expect(screen.getByRole("tooltip")).toHaveTextContent("Shipped: blocked (Build is not done)");
  });

  it("shows no position when the current step is not among the steps", () => {
    render(<StepBar name="Golden path" label="Build" current={-1} steps={steps} />);

    expect(screen.getByRole("img").parentElement).toHaveTextContent(/^Build$/);
  });

  it("draws steps with the same summary without a key clash", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      const same = [
        { state: "pending", summary: "Ticket: pending" },
        { state: "pending", summary: "Ticket: pending" },
      ] as const;
      render(<StepBar name="Ticket" label="Ticket" current={0} steps={same} />);

      expect(error).not.toHaveBeenCalled();
    } finally {
      error.mockRestore();
    }
  });

  it("has no serious axe violation (a11y)", async () => {
    const { container } = render(
      <StepBar name="Golden path" label="Build" current={5} steps={steps} />,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
