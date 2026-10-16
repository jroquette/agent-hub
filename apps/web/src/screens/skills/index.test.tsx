import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBundledFileText,
  aHookDetail,
  aPage,
  aProblem,
  aProjectSummary,
  aSkillCatalog,
  aSkillDetail,
  anAgentDetail,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { SkillDetailScreen, SkillsPickerScreen, SkillsScreen, skillsHome } from "./index";

const CATALOG = "/api/v1/projects/demo/skills";
const DETAIL = "/api/v1/projects/demo/skills/skill/hub-workflow/feature";
const AGENT = "/api/v1/projects/demo/skills/agent/hub-workflow/evaluator";
const HOOK = "/api/v1/projects/demo/skills/hook/settings/settings-pretooluse-1";
const FILE = `${DETAIL}/files/0123456789abcdef`;
const DETAIL_ROUTE = "projects/:project/skills/:kind/:source/:name";

function openCatalog(path = "/projects/demo/skills", routes: ApiRoutes = {}) {
  return renderWithApi(<SkillsScreen />, {
    routes: { [CATALOG]: aSkillCatalog(), ...routes },
    path,
    route: "projects/:project/skills",
  });
}

function openDetail(
  path = "/projects/demo/skills/skill/hub-workflow/feature",
  routes: ApiRoutes = {},
) {
  return renderWithApi(<SkillDetailScreen />, {
    routes: {
      [DETAIL]: aSkillDetail(),
      [AGENT]: anAgentDetail(),
      [HOOK]: aHookDetail(),
      [FILE]: aBundledFileText(),
      ...routes,
    },
    path,
    route: DETAIL_ROUTE,
  });
}

function pick(path = "/knowledge/skills", routes: ApiRoutes = {}) {
  return renderWithApi(<SkillsPickerScreen />, {
    routes: { "/api/v1/projects": aPage([aProjectSummary({ name: "demo" })]), ...routes },
    path,
    route: "knowledge/skills",
  });
}

const paths = (requests: Request[]) => requests.map((r) => new URL(r.url).pathname);

const scrollIntoView = vi.fn();

beforeEach(() => {
  scrollIntoView.mockClear();
  Element.prototype.scrollIntoView = scrollIntoView;
});

describe("SkillsPickerScreen nav", () => {
  it("lists the projects to pick a catalog when All projects is in scope (AC-164.13)", async () => {
    pick();

    expect(await screen.findByRole("heading", { level: 1, name: "Skills" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "demo" })).toHaveAttribute(
      "href",
      "/projects/demo/skills",
    );
  });

  it("opens the scoped project's catalog when a project is in scope", async () => {
    const { router } = renderWithApi(<SkillsPickerScreen />, {
      path: "/knowledge/skills?scope=demo",
      route: "*",
    });

    await vi.waitFor(() => {
      expect(router.state.location.pathname).toBe("/projects/demo/skills");
    });
  });

  it("encodes the project in the catalog route", () => {
    expect(skillsHome("a b")).toBe("/projects/a%20b/skills");
  });
});

describe("SkillsPickerScreen states", () => {
  it("explains an empty project list", async () => {
    pick("/knowledge/skills", { "/api/v1/projects": aPage([]) });

    expect(await screen.findByText("No projects yet.")).toBeInTheDocument();
  });

  it("shows the problem when the projects cannot be read", async () => {
    pick("/knowledge/skills", { "/api/v1/projects": aProblem({ status: 500, title: "Boom" }) });

    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });
});

describe("SkillsScreen nav", () => {
  it("links each card to its detail route (AC-164.13)", async () => {
    openCatalog();

    const card = await screen.findByRole("article", { name: "feature" });
    expect(within(card).getByRole("link", { name: "feature" })).toHaveAttribute(
      "href",
      "/projects/demo/skills/skill/hub-workflow/feature",
    );
  });
});

describe("SkillsScreen states", () => {
  it("shows the catalog of the project in the URL", async () => {
    const { requests } = openCatalog();

    expect(screen.getByRole("heading", { level: 1, name: "Skills" })).toBeInTheDocument();
    expect(await screen.findByRole("article", { name: "feature" })).toBeInTheDocument();
    expect(paths(requests)).toEqual([CATALOG]);
  });

  it("keeps the filters of the URL when the catalog opens", async () => {
    openCatalog("/projects/demo/skills?kind=agent");

    expect(await screen.findByRole("article", { name: "evaluator" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "feature" })).not.toBeInTheDocument();
  });

  it("shows a skeleton while the catalog loads", () => {
    openCatalog();

    expect(screen.getByLabelText("Loading the catalog")).toHaveAttribute("aria-busy", "true");
  });

  it("explains the empty notice when the hub has no skills", async () => {
    openCatalog("/projects/demo/skills", {
      [CATALOG]: aSkillCatalog({
        items: [],
        external_plugins: [],
        notice: "No skills found in this hub; it may not be synced yet.",
      }),
    });

    expect(
      await screen.findByText("No skills found in this hub; it may not be synced yet."),
    ).toBeInTheDocument();
  });

  it("says the project is unknown when the catalog answers 404", async () => {
    openCatalog("/projects/demo/skills", {
      [CATALOG]: aProblem({ status: 404, title: "Not found", detail: "No project demo." }),
    });

    expect(await screen.findByText("No project demo.")).toBeInTheDocument();
  });

  it("shows the problem with a retry when the catalog cannot be read", async () => {
    openCatalog("/projects/demo/skills", { [CATALOG]: aProblem({ status: 500, title: "Boom" }) });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Boom");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("SkillDetailScreen nav", () => {
  it("leads back to the project's catalog through the breadcrumb", async () => {
    openDetail();

    await screen.findByRole("heading", { level: 1, name: "feature" });
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Skills" })).toHaveAttribute(
      "href",
      "/projects/demo/skills",
    );
    expect(within(crumbs).getByRole("link", { name: "demo" })).toHaveAttribute(
      "href",
      "/projects/demo",
    );
  });

  it("links uses to their detail routes", async () => {
    openDetail();

    const relations = await screen.findByRole("region", { name: "Relations" });
    expect(within(relations).getByRole("link", { name: /requirements-analyst/ })).toHaveAttribute(
      "href",
      "/projects/demo/skills/agent/hub-workflow/requirements-analyst",
    );
  });
});

describe("SkillDetailScreen states", () => {
  it("reads the item named by the URL and shows its sections", async () => {
    const { requests } = openDetail();

    expect(await screen.findByRole("heading", { level: 1, name: "feature" })).toBeInTheDocument();
    expect(paths(requests)).toEqual([DETAIL]);
    for (const name of ["Text", "Structure", "Relations", "Bundled files", "Diagnostics"]) {
      expect(screen.getByRole("region", { name: new RegExp(`^${name}`) })).toBeInTheDocument();
    }
    expect(screen.queryByRole("region", { name: "Hook" })).not.toBeInTheDocument();
  });

  it("shows the hook card and no text or files when a hook is open", async () => {
    openDetail("/projects/demo/skills/hook/settings/settings-pretooluse-1");

    expect(
      await screen.findByRole("heading", { level: 1, name: "settings-pretooluse-1" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Hook" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^Text/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^Bundled files/ })).not.toBeInTheDocument();
  });

  it("offers to edit the item with Claude beside Discuss", async () => {
    openDetail();

    await screen.findByRole("heading", { level: 1, name: "feature" });
    expect(screen.getByRole("button", { name: "Edit with Claude" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Discuss with Claude" })).toBeInTheDocument();
  });

  it("shows no bundled files when an agent is open", async () => {
    openDetail("/projects/demo/skills/agent/hub-workflow/evaluator");

    expect(await screen.findByRole("heading", { level: 1, name: "evaluator" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /^Text/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^Bundled files/ })).not.toBeInTheDocument();
  });

  it("answers not found without a request when the kind is unknown", () => {
    const { requests } = openDetail("/projects/demo/skills/plugin/hub-workflow/feature");

    expect(screen.getByText("No plugin hub-workflow/feature in demo.")).toBeInTheDocument();
    expect(requests).toEqual([]);
  });

  it("answers not found when the item is unknown", async () => {
    openDetail("/projects/demo/skills/skill/hub-workflow/missing", {
      "/api/v1/projects/demo/skills/skill/hub-workflow/missing": aProblem({
        status: 404,
        title: "Not found",
      }),
    });

    expect(await screen.findByText("No skill hub-workflow/missing in demo.")).toBeInTheDocument();
  });

  it("shows the problem with a retry when the detail cannot be read", async () => {
    openDetail("/projects/demo/skills/skill/hub-workflow/feature", {
      [DETAIL]: aProblem({ status: 500, title: "Boom" }),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });

  it("opens the bundled file in the page when a body link names it (AC-164.21)", async () => {
    const body = "# Feature\n\nRead [the checklist](references/checklist.md) first.\n";
    const { requests } = openDetail("/projects/demo/skills/skill/hub-workflow/feature", {
      [DETAIL]: aSkillDetail({ body, toc: [{ level: 1, text: "Feature" }] }),
    });

    const link = await screen.findByRole("link", { name: "the checklist" });
    expect(link).toHaveAttribute("href", "#skill-file-0123456789abcdef");
    fireEvent.click(link);

    expect(await screen.findByText(/The spec is approved/)).toBeInTheDocument();
    expect(paths(requests)).toContain(FILE);
    expect(screen.getByRole("button", { name: "Hide references/checklist.md" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("switches back to Rendered when a step is chosen from Raw", async () => {
    openDetail();

    await screen.findByRole("heading", { level: 1, name: "feature" });
    fireEvent.click(screen.getByRole("button", { name: "Raw" }));
    expect(document.getElementById("step-2")).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: /^2\. Gate: user approves the spec/ }));

    expect(screen.getByRole("button", { name: "Rendered" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await vi.waitFor(() => {
      expect(scrollIntoView.mock.contexts).toContain(document.getElementById("step-2"));
    });
  });
});

describe("SkillDetailScreen unsafe", () => {
  it("renders an unsafe body as inert text through the detail screen (AC-164.29)", async () => {
    const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const body = [
      "<script>alert(1)</script>",
      "",
      "<img src=x onerror=alert(2)>",
      "",
      "A [x](javascript:alert(3)) link and ![r](https://evil.example/x.png).",
      "",
      "Context: !`rm -rf /` then ${CLAUDE_PROJECT_DIR}/scripts.",
      "",
      "```!",
      "git status",
      "```",
      "",
    ].join("\n");
    const { container } = openDetail("/projects/demo/skills/skill/hub-workflow/feature", {
      [DETAIL]: aSkillDetail({ body, raw: body, toc: [] }),
    });

    const text = await screen.findByRole("region", { name: /^Text/ });
    expect(container.querySelector("script, img, iframe, object, embed")).toBeNull();
    expect(text.textContent).toContain("<script>alert(1)</script>");
    expect(text.textContent).toContain("<img src=x onerror=alert(2)>");
    expect(within(text).getByText("x").closest("a")).toBeNull();
    expect(text.textContent).toContain("rm -rf /");
    expect(text.textContent).toContain("${CLAUDE_PROJECT_DIR}/scripts");
    expect(text.textContent).toContain("git status");
    const remote = within(text).queryByRole("link", { name: /Image: r/ });
    expect(remote?.getAttribute("href") ?? "").not.toContain("javascript");
    expect(alert).not.toHaveBeenCalled();
  });
});

describe("Skills screens a11y", () => {
  it("has no serious or critical violation on the catalog (AC-164.31)", async () => {
    const { container } = openCatalog();
    await screen.findByRole("article", { name: "feature" });

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("has no serious or critical violation on a skill detail", async () => {
    const { container } = openDetail();
    await screen.findByRole("heading", { level: 1, name: "feature" });

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("has no serious or critical violation on a hook detail", async () => {
    const { container } = openDetail("/projects/demo/skills/hook/settings/settings-pretooluse-1");
    await screen.findByRole("heading", { level: 1, name: "settings-pretooluse-1" });

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("has no serious or critical violation on the picker", async () => {
    const { container } = pick();
    await screen.findByRole("link", { name: "demo" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
