import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  T0,
  aHookDetail,
  aSkillDetail,
  anAgentDetail,
  renderWithApi,
} from "../../testing/builders";
import { DetailHeader } from "./DetailHeader";

const NOW = Date.parse(T0);

function header(detail = aSkillDetail()) {
  return renderWithApi(<DetailHeader detail={detail} now={NOW} usageDays={30} />);
}

const fact = (term: string) => {
  const dt = screen.getByText(term, { selector: "dt" });
  return dt.nextElementSibling as HTMLElement;
};

describe("DetailHeader detail_header_raw", () => {
  it("shows the D4 fields a skill has when its detail is rendered (AC-164.17)", () => {
    header(
      aSkillDetail({
        when_to_use: "When an idea needs a spec.",
        allowed_tools: ["Read", "Grep"],
        model: "opus",
        frontmatter: [
          ...aSkillDetail().frontmatter,
          { key: "effort", known: true, value: "high" },
          { key: "metadata", known: true, value: { owner: "platform" } },
        ],
      }),
    );

    expect(screen.getByRole("heading", { level: 1, name: "feature" })).toBeInTheDocument();
    expect(
      screen.getByText("Takes an idea or a tracker issue from spec to delivery."),
    ).toBeInTheDocument();
    expect(fact("When to use")).toHaveTextContent("When an idea needs a spec.");
    expect(screen.getByText("/feature <idea or tracker issue id>").tagName).toBe("CODE");
    expect(
      screen.getByRole("button", { name: "Copy /feature <idea or tracker issue id>" }),
    ).toBeInTheDocument();
    expect(screen.getByText("User and model")).toBeInTheDocument();
    expect(screen.getByText("Managed")).toBeInTheDocument();
    expect(fact("Source")).toHaveTextContent("plugin/hub-workflow/skills/feature/SKILL.md");
    expect(fact("Linked from")).toHaveTextContent(".claude/skills/feature");
    expect(fact("hub.lock")).toHaveTextContent("managed · sha256 aaaaaaaaaaaa");
    expect(fact("Argument hint")).toHaveTextContent("<idea or tracker issue id>");
    expect(fact("Allowed tools")).toHaveTextContent("Read, Grep");
    expect(fact("Model")).toHaveTextContent("opus");
    expect(fact("effort")).toHaveTextContent("high");
    expect(fact("metadata")).toHaveTextContent("owner: platform");
    expect(screen.queryByText("Tools", { selector: "dt" })).toBeNull();
    expect(screen.getByText(/3 uses in 30 days/)).toBeInTheDocument();
  });

  it("leaves out the fields a skill does not set", () => {
    header(
      aSkillDetail({ argument_hint: null, linked_from: [], lock: null, invocation: "/feature" }),
    );

    expect(screen.queryByText("Argument hint", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("Linked from", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("hub.lock", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("When to use", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("Model", { selector: "dt" })).toBeNull();
  });

  it("copies exactly the invocation when Copy is pressed", () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    header();

    fireEvent.click(screen.getByRole("button", { name: /^Copy/ }));

    expect(writeText).toHaveBeenCalledWith("/feature <idea or tracker issue id>");
    vi.unstubAllGlobals();
  });

  it("shows an agent's tools, model and subagent line and no Copy", () => {
    header(anAgentDetail());

    expect(screen.getByRole("heading", { level: 1, name: "evaluator" })).toBeInTheDocument();
    expect(screen.getByText(/^subagent/)).toHaveTextContent("subagent evaluator");
    expect(fact("Tools")).toHaveTextContent("Read, Grep");
    expect(fact("Model")).toHaveTextContent("sonnet");
    expect(screen.queryByRole("button", { name: /^Copy/ })).toBeNull();
  });

  it("shows a hook's source and state, not a description", () => {
    header(aHookDetail({ active: false }));

    const banner = screen.getByRole("banner");
    expect(within(banner).getByRole("heading", { level: 1 })).toHaveTextContent(
      "settings-pretooluse-1",
    );
    expect(fact("Source")).toHaveTextContent(".claude/settings.json");
    expect(banner).toHaveTextContent("Inactive");
    expect(banner).not.toHaveTextContent("uses in");
  });
});

describe("DetailHeader a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = header();

    expect(await seriousViolations(container)).toEqual([]);
  });
});
