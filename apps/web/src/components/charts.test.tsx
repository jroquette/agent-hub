import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../testing/axe";
import { BarChart, niceMax, scale } from "./charts";

describe("BarChart", () => {
  it("draws one labelled bar per value with the highlight in the failed tone", () => {
    const { container } = render(
      <BarChart
        label="Where do runs fail?"
        highlight="verify"
        fmt={(v) => `${String(v)} runs`}
        bars={[
          { label: "verify", value: 4, note: "most" },
          { label: "implement", value: 1, tone: "waiting" },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "Where do runs fail?" })).toBeInTheDocument();
    const rects = container.querySelectorAll("rect");
    expect(rects[0]).toHaveStyle({ fill: "var(--failed)" });
    expect(rects[1]).toHaveStyle({ fill: "var(--waiting)" });
    expect(container.textContent).toContain("4 runs  most");
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = render(<BarChart label="Bars" bars={[{ label: "a", value: 1 }]} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("scales", () => {
  it.each([
    [0, 1],
    [0.7, 1],
    [1.5, 2],
    [42, 50],
    [700, 1000],
  ])("rounds %d up to the nice maximum %d", (v, nice) => {
    expect(niceMax(v)).toBe(nice);
  });

  it("maps a domain onto a range", () => {
    expect(scale(0, 10, 100, 200)(5)).toBe(150);
    expect(scale(3, 3, 0, 10)(3)).toBe(0);
  });
});
