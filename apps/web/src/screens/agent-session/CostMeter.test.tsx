import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CostMeter, costDetail } from "./CostMeter";

const meter = {
  costUsd: 1.5,
  usage: { input: 20000, output: 3, cache_read: 7, cache_write: 1 },
  turns: 2,
};

describe("CostMeter (transcript)", () => {
  it("shows the cost labelled as an estimate, two decimals", () => {
    render(<CostMeter meter={meter} />);

    const field = screen.getByRole("group", { name: "Cost and tokens (estimate)" });
    expect(field).toHaveTextContent("Cost $1.50 · estimated");
    expect(field).toHaveAttribute("tabindex", "0");
  });

  it("keeps the precise amount, the tokens and the turns in its tooltip", () => {
    expect(costDetail(meter)).toEqual([
      "$1.5000 · Estimated from transcript",
      "20 k in · 3 out · 7 cache read · 1 cache write",
      "2 turns",
    ]);
    render(<CostMeter meter={meter} />);
    expect(screen.getByRole("tooltip")).toHaveTextContent("20 k in · 3 out");
  });

  it("shows a dash and says why before the first result", () => {
    render(<CostMeter meter={{ costUsd: null, usage: null, turns: 0 }} />);

    expect(screen.getByRole("group")).toHaveTextContent("Cost — · estimated");
    expect(screen.getByRole("tooltip")).toHaveTextContent("No turn has finished yet");
  });

  it("shows only the amount when compact", () => {
    render(<CostMeter meter={meter} compact />);

    expect(screen.getByRole("group")).toHaveTextContent(/^\$1\.50$/);
  });
});
