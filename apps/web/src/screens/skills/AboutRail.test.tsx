import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aHookDetail, aSkillDetail, anAgentDetail, renderWithApi } from "../../testing/builders";
import { AboutRail } from "./AboutRail";

function rail(detail = aSkillDetail()) {
  return renderWithApi(<AboutRail project="agent-hub" detail={detail} />);
}

const fact = (term: string) =>
  screen.getByText(term, { selector: "dt" }).nextElementSibling as HTMLElement;

describe("AboutRail about_rail", () => {
  it("shows where a skill lives, its lock, cost, relations and commands (AC-164.17)", () => {
    rail(
      aSkillDetail({
        allowed_tools: ["Read", "Grep"],
        model: "opus",
        frontmatter: [...aSkillDetail().frontmatter, { key: "effort", known: true, value: "high" }],
      }),
    );

    const about = screen.getByRole("complementary", { name: "About this skill" });
    expect(
      within(about).getByTitle("plugin/hub-workflow/skills/feature/SKILL.md"),
    ).toBeInTheDocument();
    expect(
      within(about).getByRole("button", {
        name: "Copy path plugin/hub-workflow/skills/feature/SKILL.md",
      }),
    ).toBeInTheDocument();
    expect(fact("Linked from")).toHaveTextContent(".claude/skills/feature");
    expect(fact("hub.lock")).toHaveTextContent("Managed by hub sync");
    expect(
      within(fact("hub.lock")).getByRole("button", { name: `Copy sha256 ${"a".repeat(64)}` }),
    ).toHaveTextContent("a".repeat(12));
    expect(fact("Allowed tools")).toHaveTextContent("ReadGrep");
    expect(fact("Model")).toHaveTextContent("opus");
    expect(fact("effort")).toHaveTextContent("high");
    expect(screen.getByRole("region", { name: "Context cost" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Uses" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Commands it runs" })).toHaveTextContent(
      "./hub doctor",
    );
  });

  it("leaves out the facts a skill does not set", () => {
    rail(aSkillDetail({ linked_from: [], lock: null }));

    expect(screen.queryByText("Linked from", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("hub.lock", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("Model", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("Argument hint", { selector: "dt" })).toBeNull();
  });

  it("leads an agent's facts with its model and tools", () => {
    rail(anAgentDetail());

    expect(screen.getByRole("complementary", { name: "About this agent" })).toBeInTheDocument();
    expect(fact("Model")).toHaveTextContent("sonnet");
    expect(fact("Tools")).toHaveTextContent("ReadGrep");
    expect(screen.getByRole("list", { name: "Used by" })).toHaveTextContent("feature");
  });

  it("shows a hook's event, matcher and source file, and no cost or relations", () => {
    rail(aHookDetail());

    expect(fact("Event")).toHaveTextContent("PreToolUse");
    expect(fact("Source file")).toHaveTextContent(".claude/settings.json");
    expect(screen.queryByRole("region", { name: "Context cost" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Uses" })).toBeNull();
  });
});

describe("AboutRail a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = rail();

    expect(await seriousViolations(container)).toEqual([]);
  });
});
