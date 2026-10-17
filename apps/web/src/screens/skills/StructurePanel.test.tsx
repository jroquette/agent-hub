import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aHookDetail, aSkillDetail, anAgentDetail } from "../../testing/builders";
import { StructurePanel, stepsHeadline } from "./StructurePanel";

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

    const panel = screen.getByRole("region", { name: "Steps" });
    expect(within(panel).getByText("5 steps")).toBeInTheDocument();
    expect(within(panel).getByText("Derived from the text")).toBeInTheDocument();
    const steps = within(panel).getAllByRole("link");
    expect(steps.map((step) => step.getAttribute("href"))).toEqual([
      "#step-1",
      "#step-2",
      "#step-3",
      "#step-4",
      "#step-5",
    ]);
    expect(steps[1]).toHaveAccessibleName("2. Gate: user approves the spec");
    expect(within(panel).getByText("Stop until they do.")).toBeInTheDocument();
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
  });

  it("shows a declared type instead of the guessed tags and counts the gates", () => {
    const steps = STRUCTURE?.steps ?? [];
    const [first, second] = steps;
    if (!first || !second) throw new Error("fixture has steps");
    const declared = [
      { ...first, declared_type: "agent" as const, tags: [] },
      { ...second, declared_type: "gate" as const, tags: ["gate" as const] },
    ];
    render(<StructurePanel structure={{ ...(STRUCTURE ?? EMPTY), steps: declared }} />);

    const [agent, gate] = within(screen.getByRole("list", { name: "Steps" })).getAllByRole(
      "listitem",
    );
    expect(agent).toHaveTextContent("Agent works");
    expect(agent).not.toHaveTextContent("Gate");
    expect(gate).toHaveTextContent("You approve");
    expect(screen.getByText("2 steps · you approve step 2")).toBeInTheDocument();
  });

  it("renders nothing when the body has no ordered list", () => {
    const { container } = render(<StructurePanel structure={anAgentDetail().structure ?? null} />);

    expect(container).toBeEmptyDOMElement();
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

describe("stepsHeadline", () => {
  it("names the steps you approve and act in", () => {
    const step = (index: number, declared_type: "gate" | "human" | null) => ({
      agents: [],
      commands: [],
      declared_type,
      index,
      scripts: [],
      skills: [],
      summary: "",
      tags: [],
      title: "t",
    });

    expect(stepsHeadline([step(1, null)])).toBe("1 step");
    expect(stepsHeadline([step(1, "gate"), step(2, "human"), step(3, "gate")])).toBe(
      "3 steps · you approve steps 1 and 3 · you act in step 2",
    );
  });
});

describe("StructurePanel a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = render(<StructurePanel structure={STRUCTURE} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
