import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aGoldenPath, aGoldenStep } from "../../testing/builders";
import { GoldenPathBar, waitsOnOwner } from "./GoldenPathBar";

describe("GoldenPathBar", () => {
  it("shows the phase with its meta and one segment per step (golden)", () => {
    const { container } = render(<GoldenPathBar path={aGoldenPath()} />);

    expect(screen.getByText("Implement")).toBeInTheDocument();
    // The ACs column counts the ACs, so the row's meta keeps only the tickets.
    expect(screen.getByText("1/3 tickets")).toBeInTheDocument();
    expect(screen.getByText("1/3 tickets").parentElement).not.toHaveTextContent("40/66 ACs");
    expect(screen.getByRole("img")).toHaveAttribute("tabindex", "0");
    expect(screen.getByText("Implement").parentElement).toHaveTextContent(
      "Implement · step 5 of 8",
    );
    expect(
      [...container.querySelectorAll("[data-state]")].map((el) => el.getAttribute("data-state")),
    ).toEqual(["done", "done", "done", "done", "current", "pending", "partial", "pending"]);
  });

  it("names partial, blocked and unknown steps with their reason (golden)", () => {
    render(
      <GoldenPathBar
        path={aGoldenPath({
          phase: "implement",
          steps: [
            aGoldenStep({ name: "implement", state: "current", meta: "1/17 tickets · 3/36 ACs" }),
            aGoldenStep({
              name: "review",
              state: "unknown",
              meta: "Linear not connected",
              reason: "Linear is not connected for hub web",
              progress: null,
            }),
            aGoldenStep({
              name: "evaluate",
              state: "partial",
              meta: "partial: covers 3 of 36 ACs",
              reason: "Implement is not done",
              progress: { done: 3, total: 36 },
            }),
            aGoldenStep({
              name: "shipped",
              state: "blocked",
              meta: null,
              reason: "Review is unknown",
              progress: null,
            }),
          ],
        })}
      />,
    );

    const bar = screen.getByRole("img");
    expect(bar).toHaveAccessibleName(/^Golden path: Implement\./);
    expect(bar).toHaveAccessibleName(
      /Review: unknown · Linear not connected \(Linear is not connected for hub web\)/,
    );
    expect(bar).toHaveAccessibleName(
      /Evaluate: partial · partial: covers 3 of 36 ACs \(Implement is not done\)/,
    );
    expect(bar).toHaveAccessibleName(/Shipped: blocked \(Review is unknown\)/);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Shipped: blocked (Review is unknown)");
  });

  it("never shows a segment done after a gate that is not done (golden)", () => {
    const { container } = render(
      <GoldenPathBar
        path={aGoldenPath({
          phase: "implement",
          steps: [
            aGoldenStep({ name: "implement", state: "current" }),
            aGoldenStep({ name: "evaluate", state: "done", meta: null, reason: null }),
          ],
        })}
      />,
    );

    expect(
      [...container.querySelectorAll("[data-state]")].map((el) => el.getAttribute("data-state")),
    ).toEqual(["current", "blocked"]);
  });

  it("says Shipped when every step is done (golden)", () => {
    render(
      <GoldenPathBar
        path={aGoldenPath({
          phase: "shipped",
          steps: [aGoldenStep({ name: "shipped", state: "done", meta: null, progress: null })],
        })}
      />,
    );

    expect(screen.getByText("Shipped")).toBeInTheDocument();
  });

  it("flags a feature held at Evaluate by owner steps as waiting for you", () => {
    const path = aGoldenPath({
      phase: "evaluate",
      steps: [aGoldenStep({ name: "evaluate", state: "current", meta: "waiting: owner steps" })],
    });
    render(<GoldenPathBar path={path} />);

    expect(waitsOnOwner(path)).toBe(true);
    expect(screen.getByText("Waiting for you")).toBeInTheDocument();
  });

  it("has no serious axe violation (golden a11y)", async () => {
    const { container } = render(<GoldenPathBar path={aGoldenPath()} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
