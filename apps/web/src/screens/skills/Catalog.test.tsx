import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { T0, aCatalogItem, aSkillCatalog, renderWithApi } from "../../testing/builders";
import { Catalog } from "./Catalog";

type SkillCatalog = ReturnType<typeof aSkillCatalog>;

const NOW = Date.parse(T0);

function open(path = "/projects/demo/skills", catalog: SkillCatalog = aSkillCatalog()) {
  return renderWithApi(<Catalog catalog={catalog} now={NOW} />, {
    path,
    route: "/projects/:project/skills",
  });
}

const cards = () =>
  screen.queryAllByRole("article").map((card) => card.getAttribute("aria-labelledby"));
const shown = () =>
  screen.queryAllByRole("article").map((card) => within(card).getByRole("heading").textContent);
const box = (name: RegExp) => screen.getByRole("checkbox", { name });

describe("Catalog search_facets", () => {
  it("filters on name or description, ignoring case, and restores all when cleared (AC-164.14)", () => {
    open();
    expect(shown()).toEqual(["feature", "plan", "evaluator", "settings-pretooluse-1"]);

    fireEvent.change(screen.getByRole("searchbox", { name: /Search/ }), {
      target: { value: "SPEC" },
    });
    expect(shown()).toEqual(["feature", "evaluator"]);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 2 of 4");

    fireEvent.change(screen.getByRole("searchbox", { name: /Search/ }), {
      target: { value: "" },
    });
    expect(shown()).toHaveLength(4);
  });

  it("combines facets with search and shows each value's count", () => {
    open();

    fireEvent.change(screen.getByRole("searchbox", { name: /Search/ }), {
      target: { value: "spec" },
    });
    expect(box(/^Skills/)).toHaveAccessibleName("Skills1");
    expect(box(/^Agents/)).toHaveAccessibleName("Agents1");
    expect(box(/^Hooks/)).toHaveAccessibleName("Hooks0");

    fireEvent.click(box(/^Agents/));
    expect(shown()).toEqual(["evaluator"]);
    expect(box(/^Managed/)).toHaveAccessibleName("Managed1");

    fireEvent.click(box(/^Has diagnostics/));
    expect(shown()).toEqual([]);
    expect(screen.getByText("No items match these filters.")).toBeInTheDocument();

    const clear = screen.getAllByRole("button", { name: "Clear filters" });
    expect(clear).toHaveLength(2);
    const inMessage = clear.pop();
    if (inMessage) fireEvent.click(inMessage);
    expect(shown()).toHaveLength(4);
    expect(screen.getByRole("searchbox", { name: /Search/ })).toHaveValue("");
    expect(box(/^Agents/)).not.toBeChecked();
  });

  it("offers the four modes with Hidden for neither (L2)", () => {
    open(
      "/projects/demo/skills",
      aSkillCatalog({ items: [aCatalogItem(), aCatalogItem({ name: "quiet", mode: "neither" })] }),
    );

    const modes = within(screen.getByRole("group", { name: "Invocation" }));
    expect(
      modes.getAllByRole("checkbox").map((option) => option.closest("label")?.textContent),
    ).toEqual(["User only0", "Model only0", "User and model1", "Hidden1"]);
    fireEvent.click(box(/^Hidden/));
    expect(shown()).toEqual(["quiet"]);
  });
});

describe("Catalog url_query", () => {
  it("opens with the URL's search and facets applied (AC-164.40)", () => {
    open("/projects/demo/skills?q=plan&kind=skill&mode=user-only");

    expect(screen.getByRole("searchbox", { name: /Search/ })).toHaveValue("plan");
    expect(box(/^Skills/)).toBeChecked();
    expect(box(/^User only/)).toBeChecked();
    expect(box(/^Agents/)).not.toBeChecked();
    expect(shown()).toEqual(["plan"]);
  });

  it("updates the query in place when a facet changes", () => {
    const { router } = open("/projects/demo/skills?q=plan&kind=skill&mode=user-only");

    fireEvent.click(box(/^Agents/));

    expect(router.state.location.search).toBe("?q=plan&kind=skill%2Cagent&mode=user-only");
    expect(router.state.historyAction).toBe("REPLACE");
    fireEvent.change(screen.getByRole("searchbox", { name: /Search/ }), {
      target: { value: "" },
    });
    expect(router.state.location.search).toBe("?kind=skill%2Cagent&mode=user-only");
  });

  it("ignores unknown values when the query is hand-written", () => {
    open("/projects/demo/skills?kind=plugin&mode=all&diag=yes&origin=nowhere");

    expect(
      screen.getAllByRole("checkbox").filter((option) => (option as HTMLInputElement).checked),
    ).toEqual([]);
    expect(shown()).toHaveLength(4);
  });
});

describe("Catalog groups and notices", () => {
  it("groups cards by kind under headings with counts", () => {
    open();

    expect(screen.getByRole("heading", { level: 2, name: "Skills 2" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Agents 1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Hooks 1" })).toBeInTheDocument();
    expect(cards()).toHaveLength(4);
  });

  it("lists third-party plugins as not in this hub (D1)", () => {
    open(
      "/projects/demo/skills",
      aSkillCatalog({
        external_plugins: [
          ...aSkillCatalog().external_plugins,
          {
            content: "not in this hub",
            enabled: false,
            marketplace: null,
            name: "other",
            pin: null,
          },
        ],
      }),
    );

    const plugins = screen.getByRole("region", { name: "Third-party plugins" });
    const [first, second] = within(plugins).getAllByRole("listitem");
    expect(first).toHaveTextContent("superpowers");
    expect(first).toHaveTextContent("agent-hub");
    expect(first).toHaveTextContent("pinned 5f0c2e1");
    expect(first).toHaveTextContent("Enabled");
    expect(first).toHaveTextContent("content not in this hub");
    expect(second).toHaveTextContent("not pinned");
    expect(second).toHaveTextContent("Disabled");
  });

  it("warns when the catalog is truncated and shows its notice", () => {
    open(
      "/projects/demo/skills",
      aSkillCatalog({ truncated: true, notice: "hub.lock not read: origins from folder names" }),
    );

    const banner = screen.getByText(/catalog is incomplete/).closest("[role='status']");
    expect(banner).toHaveTextContent("hub.lock not read: origins from folder names");
  });

  it("shows a notice alone when nothing is truncated", () => {
    open("/projects/demo/skills", aSkillCatalog({ notice: "plugin/x/hooks/hooks.json: not read" }));

    expect(screen.getByText("plugin/x/hooks/hooks.json: not read")).toBeInTheDocument();
    expect(screen.queryByText(/catalog is incomplete/)).toBeNull();
  });

  it("explains an empty hub with its notice and no filters", () => {
    open(
      "/projects/demo/skills",
      aSkillCatalog({
        items: [],
        external_plugins: [],
        notice: "No skills found in this hub; it may not be synced yet.",
      }),
    );

    expect(
      screen.getByRole("heading", {
        name: "No skills found in this hub; it may not be synced yet.",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByRole("region", { name: "Third-party plugins" })).toBeNull();
  });
});

describe("Catalog a11y", () => {
  it("has no serious or critical axe violation and states status as text (AC-164.31)", async () => {
    const { container } = open("/projects/demo/skills?diag=1");

    expect(await seriousViolations(container)).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 1 of 4");
  });
});
