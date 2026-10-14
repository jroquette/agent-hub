import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CostMeter } from "./CostMeter";

describe("CostMeter (transcript)", () => {
  it("shows cache tokens when there are some", () => {
    render(
      <CostMeter
        meter={{
          costUsd: 1.5,
          usage: { input: 20000, output: 3, cache_read: 7, cache_write: 1 },
          turns: 1,
        }}
      />,
    );

    const meter = screen.getByRole("group", { name: "Cost and tokens (estimate)" });
    expect(meter).toHaveTextContent("$1.5000");
    expect(meter).toHaveTextContent("20 k in");
    expect(meter).toHaveTextContent("cache 7 / 1");
  });

  it("shows dashes before the first result", () => {
    render(<CostMeter meter={{ costUsd: null, usage: null, turns: 0 }} />);

    expect(screen.getByRole("group")).toHaveTextContent(/^—— in— out/);
  });
});
