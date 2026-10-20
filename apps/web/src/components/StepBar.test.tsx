import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

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
  afterEach(() => {
    delete document.documentElement.dataset.theme;
  });

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

  it("reads the last step alone, with no position", () => {
    render(<StepBar name="Golden path" label="Shipped" current={7} steps={steps} />);

    expect(screen.getByRole("img").parentElement).toHaveTextContent(/^Shipped$/);
  });

  it("is an image named by the current step and every step's summary, also in its tooltip", () => {
    render(<StepBar name="Golden path" label="Build" current={5} steps={steps} />);

    expect(screen.getByRole("img")).toHaveAccessibleName(
      `Golden path: Build. ${steps.map((s) => s.summary).join("; ")}`,
    );
    expect(screen.getByRole("img")).not.toHaveAttribute("tabindex");
    expect(screen.getByRole("tooltip")).toHaveTextContent("Shipped: blocked (Build is not done)");
  });

  it.each(["light", "dark"])(
    "has no serious axe violation in the %s theme (a11y)",
    async (theme) => {
      document.documentElement.dataset.theme = theme;
      const { container } = render(
        <StepBar name="Golden path" label="Build" current={5} steps={steps} />,
      );

      expect(await seriousViolations(container)).toEqual([]);
    },
  );
});
