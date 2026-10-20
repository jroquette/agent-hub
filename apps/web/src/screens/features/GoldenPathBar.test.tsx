import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aGoldenPath, aGoldenStep } from "../../testing/builders";
import { GoldenPathBar, waitsOnOwner } from "./GoldenPathBar";

describe("GoldenPathBar", () => {
  it("shows the phase with its meta and one segment per step (golden)", () => {
    const { container } = render(<GoldenPathBar path={aGoldenPath()} />);

    expect(screen.getByText("Build")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 merged · 1 in progress")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("tabindex", "0");
    expect(screen.getByText("Build").parentElement).toHaveTextContent("Build · step 6 of 8");
    expect(
      [...container.querySelectorAll("[data-state]")].map((el) => el.getAttribute("data-state")),
    ).toEqual(["done", "skipped", "done", "done", "done", "current", "partial", "pending"]);
  });

  it("names partial, blocked and unknown steps with their reason (golden)", () => {
    render(
      <GoldenPathBar
        path={aGoldenPath({
          phase: "build",
          steps: [
            aGoldenStep({
              name: "build",
              state: "unknown",
              meta: "Linear not connected",
              reason: "Linear is not connected for hub web",
              progress: null,
            }),
            aGoldenStep({
              name: "acceptance",
              state: "partial",
              meta: "Ticket evals cover 3 of 36 ACs",
              reason: "Build is unknown",
              progress: { done: 3, total: 36 },
            }),
            aGoldenStep({
              name: "shipped",
              state: "blocked",
              meta: null,
              reason: "Build is unknown",
              progress: null,
            }),
          ],
        })}
      />,
    );

    const bar = screen.getByRole("img");
    expect(bar).toHaveAccessibleName(/^Golden path: Build\./);
    expect(bar).toHaveAccessibleName(
      /Build: unknown · Linear not connected \(Linear is not connected for hub web\)/,
    );
    expect(bar).toHaveAccessibleName(
      /Acceptance: partial · Ticket evals cover 3 of 36 ACs \(Build is unknown\)/,
    );
    expect(bar).toHaveAccessibleName(/Shipped: blocked \(Build is unknown\)/);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Shipped: blocked (Build is unknown)");
  });

  it("never shows a segment done after a gate that is not done (golden)", () => {
    const { container } = render(
      <GoldenPathBar
        path={aGoldenPath({
          phase: "build",
          steps: [
            aGoldenStep({ name: "build", state: "current" }),
            aGoldenStep({ name: "acceptance", state: "done", meta: null, reason: null }),
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

  it("flags a feature held at Acceptance by owner steps as waiting for you", () => {
    const path = aGoldenPath({
      phase: "acceptance",
      steps: [
        aGoldenStep({
          name: "acceptance",
          state: "current",
          meta: "Waiting on you: sign off 2 ACs",
        }),
      ],
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
