import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { ContextCost } from "./ContextCost";

const COST = { always_loaded_tokens: 100, on_invoke_tokens: 1000, approximate: true } as const;

describe("ContextCost context_cost", () => {
  it("labels both token counts approximate (AC-164.24)", () => {
    render(<ContextCost cost={COST} kind="skill" />);

    const always = screen.getByText("Always loaded").closest("div");
    const invoke = screen.getByText("On invoke").closest("div");
    expect(always).toHaveTextContent("≈ 100 tokens");
    expect(always).toHaveTextContent("approximate");
    expect(always).toHaveTextContent("from the description");
    expect(invoke).toHaveTextContent("≈ 1,000 tokens");
    expect(invoke).toHaveTextContent("approximate");
    expect(invoke).toHaveTextContent("from the body");
  });

  it("explains a zero always-loaded cost and names an agent's system prompt", () => {
    render(<ContextCost cost={{ ...COST, always_loaded_tokens: 0 }} kind="agent" />);

    expect(screen.getByText("Always loaded").closest("div")).toHaveTextContent("≈ 0 tokens");
    expect(screen.getByText("On invoke").closest("div")).toHaveTextContent(
      "from the system prompt",
    );
  });

  it("renders nothing when there is no cost", () => {
    const { container } = render(<ContextCost cost={null} kind="hook" />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("ContextCost a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = render(<ContextCost cost={COST} kind="skill" />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
