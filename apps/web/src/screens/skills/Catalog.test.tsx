import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { T0, aCatalogItem, aSkillCatalog, renderWithApi } from "../../testing/builders";
import { Catalog } from "./Catalog";
import { saveDraft } from "./studioDrafts";

type SkillCatalog = ReturnType<typeof aSkillCatalog>;

const NOW = Date.parse(T0);

function open(path = "/projects/demo/skills", catalog: SkillCatalog = aSkillCatalog()) {
  return renderWithApi(<Catalog catalog={catalog} now={NOW} />, {
    path,
    route: "/projects/:project/skills",
  });
}

const shown = () =>
  screen.queryAllByRole("article").map((card) => within(card).getByRole("heading").textContent);
const tab = (name: RegExp) => screen.getByRole("tab", { name });
const search = () => screen.getByRole("searchbox", { name: /Search/ });
/** Opens a facet menu and returns its options. */
const facet = (label: string) => {
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}:`) }));
  return within(screen.getByRole("dialog", { name: `${label} filter` }));
};

afterEach(() => {
  window.localStorage.clear();
});

describe("Catalog tabs", () => {
  it("opens on Agents, the first kind, and shows one kind per tab", () => {
    open();

    expect(tab(/^Agents/)).toHaveAttribute("aria-selected", "true");
    expect(shown()).toEqual(["evaluator"]);
    fireEvent.click(tab(/^Skills/));
    expect(shown()).toEqual(["feature", "plan"]);
    fireEvent.click(tab(/^Hooks/));
    expect(shown()).toEqual(["settings-pretooluse-1"]);
  });

  it("counts each tab and keeps the tab out of the filters", () => {
    open("/projects/demo/skills?tab=skills");

    expect(tab(/^Agents/)).toHaveTextContent("1");
    expect(tab(/^Skills/)).toHaveTextContent("2");
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("pushes the tab into the URL so Back returns to the previous one", () => {
    const { router } = open("/projects/demo/skills?q=spec");

    fireEvent.click(tab(/^Skills/));

    expect(router.state.location.search).toBe("?q=spec&tab=skills");
    expect(router.state.historyAction).toBe("PUSH");
  });

  it("reads an older kind or view link as the tab it names", () => {
    open("/projects/demo/skills?kind=skill");
    expect(tab(/^Skills/)).toHaveAttribute("aria-selected", "true");
  });

  it("lands on the first tab with matches when the URL filters", () => {
    open("/projects/demo/skills?diag=1");

    expect(tab(/^Skills/)).toHaveAttribute("aria-selected", "true");
    expect(shown()).toEqual(["feature"]);
  });
});

describe("Catalog search_facets", () => {
  it("filters on name or description, ignoring case, and counts within the tab (AC-164.14)", () => {
    open("/projects/demo/skills?tab=skills");

    fireEvent.change(search(), { target: { value: "SPEC" } });

    expect(shown()).toEqual(["feature"]);
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 skills");
    expect(tab(/^Agents/)).toHaveTextContent("1");
    expect(tab(/^Hooks/)).toHaveTextContent("0");
  });

  it("clears search and facets but keeps the tab", () => {
    open("/projects/demo/skills?tab=skills&q=spec&origin=managed");

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(search()).toHaveValue("");
    expect(tab(/^Skills/)).toHaveAttribute("aria-selected", "true");
    expect(shown()).toEqual(["feature", "plan"]);
  });

  it("offers Invocation only on Skills, with Hidden for neither (L2)", () => {
    open(
      "/projects/demo/skills?tab=skills",
      aSkillCatalog({ items: [aCatalogItem(), aCatalogItem({ name: "quiet", mode: "neither" })] }),
    );

    const modes = facet("Invocation");
    expect(
      modes.getAllByRole("checkbox").map((option) => option.closest("label")?.textContent),
    ).toEqual(["User only0", "Model only0", "User and model1", "Hidden1"]);
    fireEvent.click(modes.getByRole("checkbox", { name: /^Hidden/ }));
    expect(shown()).toEqual(["quiet"]);
  });

  it("does not let an Invocation filter empty the Agents tab", () => {
    open("/projects/demo/skills?tab=agents&mode=user-only");

    expect(screen.queryByRole("button", { name: /^Invocation:/ })).toBeNull();
    expect(shown()).toEqual(["evaluator"]);
  });

  it("says which other tabs match when this one has none", () => {
    open("/projects/demo/skills?tab=hooks&q=plan");

    expect(screen.getByText(/No hooks match these filters/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Skills (1)" }));
    expect(shown()).toEqual(["plan"]);
  });

  it("keeps the sort in the URL", () => {
    const { router } = open("/projects/demo/skills?tab=skills");

    fireEvent.click(screen.getByRole("button", { name: "Most used" }));

    expect(router.state.location.search).toBe("?tab=skills&sort=used");
    expect(shown()).toEqual(["feature", "plan"]);
  });

  it("ignores unknown values when the query is hand-written", () => {
    open("/projects/demo/skills?tab=skills&mode=all&diag=yes&origin=nowhere");

    expect(shown()).toEqual(["feature", "plan"]);
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });
});

describe("Catalog groups and notices", () => {
  it("explains the open tab's kind once, under the toolbar", () => {
    open("/projects/demo/skills?tab=hooks");

    expect(screen.getByRole("tabpanel", { name: "Hooks" })).toHaveTextContent(
      /Shell commands Claude Code runs by itself/,
    );
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

    const plugins = screen.getByText("Third-party plugins").closest("details");
    if (!plugins) throw new Error("no plugins section");
    const [first, second] = within(plugins).getAllByRole("listitem", { hidden: true });
    expect(first).toHaveTextContent("superpowers");
    expect(first).toHaveTextContent("pinned 5f0c2e1");
    expect(first).toHaveTextContent("Enabled");
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
  });
});

describe("Catalog a11y", () => {
  it("has no serious or critical axe violation and states the count as text (AC-164.31)", async () => {
    saveDraft("skill-new1", { project: "demo", kind: "skill" }, { name: "release-notes" });
    const { container } = open("/projects/demo/skills?tab=skills&diag=1");

    expect(await seriousViolations(container)).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 skills");
  });
});

describe("Catalog your_drafts", () => {
  it("lists drafts apart from the filters, with a verb and where they are kept", () => {
    saveDraft("skill-new1", { project: "demo", kind: "skill" }, { name: "release-notes" });
    saveDraft(
      "agent-edit1",
      { project: "demo", kind: "agent" },
      { name: "evaluator", target: { kind: "agent", source: "hub-workflow", name: "evaluator" } },
    );
    open();

    const drafts = screen.getByRole("region", { name: /Your drafts/ });
    expect(drafts).toHaveTextContent("Kept in this browser only");
    expect(drafts).toHaveTextContent("Editing agent");
    expect(drafts).toHaveTextContent("New skill");
    expect(
      within(drafts).getByRole("link", { name: "Continue new skill release-notes in the Studio" }),
    ).toBeInTheDocument();
  });

  it("offers to continue an edit draft on its item's card", () => {
    saveDraft(
      "agent-edit1",
      { project: "demo", kind: "agent" },
      { name: "evaluator", target: { kind: "agent", source: "hub-workflow", name: "evaluator" } },
    );
    open();

    const card = screen.getByRole("article", { name: "evaluator" });
    expect(
      within(card).getByRole("link", { name: "Continue your draft of evaluator in the Studio" }),
    ).toBeInTheDocument();
  });

  it("offers to continue an edit draft on its hook's row", () => {
    saveDraft(
      "hook-edit1",
      { project: "demo", kind: "hook" },
      {
        name: "settings-pretooluse-1",
        target: { kind: "hook", source: "settings", name: "settings-pretooluse-1" },
      },
    );
    open("/projects/demo/skills?tab=hooks");

    const row = screen.getByRole("article", { name: "settings-pretooluse-1" });
    expect(
      within(row).getByRole("link", {
        name: "Continue your draft of settings-pretooluse-1 in the Studio",
      }),
    ).toHaveAttribute("href", "/projects/demo/skills/drafts/hook-edit1");
  });

  it("shows the first three drafts and the rest on demand", () => {
    for (const n of [1, 2, 3, 4]) {
      saveDraft(
        `skill-${String(n)}`,
        { project: "demo", kind: "skill" },
        { name: `s${String(n)}` },
      );
    }
    open();

    const drafts = screen.getByRole("region", { name: /Your drafts/ });
    expect(within(drafts).getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(within(drafts).getByRole("button", { name: "Show all 4 drafts" }));
    expect(within(drafts).getAllByRole("listitem")).toHaveLength(4);
  });
});
