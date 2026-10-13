import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aSkillDetail, anAgentDetail, renderWithApi } from "../../testing/builders";
import { Relations } from "./Relations";

describe("Relations relations", () => {
  it("links each skill and agent it uses to its detail in the app (AC-164.20)", () => {
    const detail = aSkillDetail();
    renderWithApi(<Relations project="demo" uses={detail.uses} usedBy={detail.used_by} />);

    const uses = within(screen.getByRole("list", { name: "Uses" }));
    expect(uses.getByRole("link", { name: "requirements-analyst" })).toHaveAttribute(
      "href",
      "/projects/demo/skills/agent/hub-workflow/requirements-analyst",
    );
    expect(uses.getByRole("link", { name: "create-plan" })).toHaveAttribute(
      "href",
      "/projects/demo/skills/skill/hub-workflow/create-plan",
    );
    expect(uses.getAllByRole("listitem")[0]).toHaveTextContent("Agent");
    expect(screen.getByText(/No other item names it/)).toBeInTheDocument();
  });

  it("lists the skills that use an agent under Used by", () => {
    const detail = anAgentDetail();
    renderWithApi(<Relations project="demo" uses={detail.uses} usedBy={detail.used_by} />);

    const usedBy = within(screen.getByRole("list", { name: "Used by" }));
    expect(usedBy.getByRole("link", { name: "feature" })).toHaveAttribute(
      "href",
      "/projects/demo/skills/skill/hub-workflow/feature",
    );
    expect(screen.getByText(/Names no skill or agent/)).toBeInTheDocument();
  });

  it("names the source when it is not the managed plugin", () => {
    renderWithApi(
      <Relations
        project="demo"
        uses={[{ id: "skill/demo/plan", kind: "skill", source: "demo", name: "plan" }]}
        usedBy={[]}
      />,
    );

    expect(screen.getByRole("list", { name: "Uses" })).toHaveTextContent("from demo");
  });
});

describe("Relations a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const detail = aSkillDetail();
    const { container } = renderWithApi(
      <Relations project="demo" uses={detail.uses} usedBy={anAgentDetail().used_by} />,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
