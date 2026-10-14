import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aHookDetail, aSkillDetail, anAgentDetail } from "../../testing/builders";
import { StructurePanel } from "./StructurePanel";

const STRUCTURE = aSkillDetail().structure ?? null;
const EMPTY = {
  agents: [],
  commands: [],
  dynamic_context: 0,
  gates: [],
  skills: [],
  steps: [],
  truncated: false,
};

describe("StructurePanel structure", () => {
  it("is headed Derived from the text and links each step to its anchor (AC-164.19)", () => {
    const onStep = vi.fn();
    render(<StructurePanel structure={STRUCTURE} onStep={onStep} />);

    const panel = screen.getByRole("region", { name: "Structure" });
    expect(within(panel).getByText("Derived from the text")).toBeInTheDocument();
    const steps = within(panel).getAllByRole("link");
    expect(steps.map((step) => step.getAttribute("href"))).toEqual([
      "#step-1",
      "#step-2",
      "#step-3",
      "#step-4",
      "#step-5",
    ]);
    expect(steps[1]).toHaveTextContent("2. Gate: user approves the spec");
    const [, second] = steps;
    if (second) fireEvent.click(second);
    expect(onStep).toHaveBeenCalledWith("step-2");
  });

  it("names each step's tags, agents, skills and commands as text", () => {
    render(<StructurePanel structure={STRUCTURE} />);

    const items = within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Agent");
    expect(items[0]).toHaveTextContent("requirements-analyst");
    expect(items[1]).toHaveTextContent("Gate");
    expect(items[1]).toHaveTextContent("Needs you");
    expect(items[2]).toHaveTextContent("/create-plan");
    expect(items[3]).toHaveTextContent("make check");
    const summary = screen.getByRole("region", { name: "Structure" });
    expect(summary).toHaveTextContent("Gate: user approves the spec");
    expect(summary).toHaveTextContent("./hub doctor");
  });

  it("reads No numbered steps found when the body has no ordered list", () => {
    render(<StructurePanel structure={anAgentDetail().structure ?? null} />);

    expect(screen.getByText("No numbered steps found")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Steps" })).toBeNull();
  });

  it("says dynamic context runs at invocation and steps were cut when the structure says so", () => {
    render(
      <StructurePanel
        structure={{ ...(STRUCTURE ?? EMPTY), dynamic_context: 2, truncated: true }}
      />,
    );

    expect(screen.getByText(/2 dynamic context blocks/)).toHaveTextContent("runs at invocation");
    expect(screen.getByText(/first 200 steps/)).toBeInTheDocument();
  });

  it("scrolls to the step when no handler is given", () => {
    const scroll = vi.fn();
    const target = document.createElement("li");
    target.id = "step-1";
    target.scrollIntoView = scroll;
    document.body.append(target);
    render(<StructurePanel structure={STRUCTURE} />);

    fireEvent.click(screen.getByRole("link", { name: /1\. Spec/ }));

    expect(scroll).toHaveBeenCalledTimes(1);
    target.remove();
  });

  it("renders nothing for a hook", () => {
    const { container } = render(<StructurePanel structure={aHookDetail().structure ?? null} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("StructurePanel a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = render(<StructurePanel structure={STRUCTURE} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
