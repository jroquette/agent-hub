import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { T0, aCatalogItem, aSkillCatalog, renderWithApi } from "../../testing/builders";
import { SkillCard } from "./SkillCard";

const NOW = Date.parse(T0);
const [, PLAN = aCatalogItem(), AGENT = aCatalogItem(), HOOK = aCatalogItem()] =
  aSkillCatalog().items;

function card(item = aCatalogItem()) {
  return renderWithApi(
    <ul>
      <SkillCard item={item} project="demo" now={NOW} usageDays={30} />
    </ul>,
  );
}

describe("SkillCard card", () => {
  it("shows name, description, invocation, origin, mode and usage when a skill is rendered (AC-164.15)", () => {
    card();

    const article = screen.getByRole("article", { name: "feature" });
    expect(within(article).getByRole("link", { name: "feature" })).toHaveAttribute(
      "href",
      "/projects/demo/skills/skill/hub-workflow/feature",
    );
    expect(article).toHaveTextContent("Takes an idea or a tracker issue from spec to delivery.");
    expect(within(article).getByText("/feature <idea or tracker issue id>").tagName).toBe("CODE");
    expect(article).toHaveTextContent("Managed");
    expect(article).toHaveTextContent("User and model");
    expect(article).toHaveTextContent("3 uses in 30 days (2 by you) · last used 1 h ago");
    expect(article).toHaveTextContent("1 diagnostic");
  });

  it("shows the full description and invocation on hover when they are truncated", () => {
    card();

    const article = screen.getByRole("article", { name: "feature" });
    expect(within(article).getByText("/feature <idea or tracker issue id>")).toHaveAttribute(
      "title",
      "/feature <idea or tracker issue id>",
    );
    expect(
      within(article).getByText("Takes an idea or a tracker issue from spec to delivery."),
    ).toHaveAttribute("title", "Takes an idea or a tracker issue from spec to delivery.");
  });

  it("writes exactly the invocation to the clipboard when Copy is pressed", () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    card();

    fireEvent.click(
      screen.getByRole("button", { name: "Copy /feature <idea or tracker issue id>" }),
    );

    expect(writeText).toHaveBeenCalledWith("/feature <idea or tracker issue id>");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("says not used and shows the mode as text when a user-only skill has no use", () => {
    card(PLAN);

    const article = screen.getByRole("article", { name: "plan" });
    expect(article).toHaveTextContent("Not used in 30 days");
    expect(article).toHaveTextContent("User only");
    expect(article).toHaveTextContent("Project-owned");
    expect(article).not.toHaveTextContent("diagnostic");
  });

  it("reads Hidden when neither the user nor the model can invoke the skill (L2)", () => {
    card(
      aCatalogItem({
        mode: "neither",
        usage: { count: 1, last_used_at: null, model_count: 0, user_count: 1 },
      }),
    );

    expect(screen.getByRole("article")).toHaveTextContent("Hidden");
    expect(screen.getByRole("article")).toHaveTextContent("1 use in 30 days");
  });

  it("shows no Copy and does not repeat the kind when an agent is rendered", () => {
    card(AGENT);

    const article = screen.getByRole("article", { name: "evaluator" });
    expect(within(article).queryByRole("button")).toBeNull();
    expect(article).not.toHaveTextContent("subagent");
    expect(article).toHaveTextContent("Managed");
    expect(article).toHaveTextContent("Not used in 30 days");
  });

  it("takes one Tab stop for the name: origin and mode are plain text", () => {
    card();

    const article = screen.getByRole("article", { name: "feature" });
    expect(article.querySelectorAll("[tabindex='0']")).toHaveLength(0);
  });

  it("offers to continue an open draft of the item", () => {
    renderWithApi(
      <ul>
        <SkillCard item={aCatalogItem()} project="demo" now={NOW} usageDays={30} draftHref="/x" />
      </ul>,
    );

    expect(
      screen.getByRole("link", { name: "Continue your draft of feature in the Studio" }),
    ).toHaveAttribute("href", "/x");
  });

  it("shows a hook's command, source and state as text when a hook is rendered", () => {
    card({ ...HOOK, active: false, state: "not synced" });

    const article = screen.getByRole("article", { name: "settings-pretooluse-1" });
    expect(article).toHaveTextContent("python3 plugin/hub-workflow/hooks/guard.py");
    expect(article).toHaveTextContent("Inactive");
    expect(article).toHaveTextContent("Not synced");
    expect(article).not.toHaveTextContent("uses in");
    expect(within(article).queryByRole("button")).toBeNull();
  });
});
