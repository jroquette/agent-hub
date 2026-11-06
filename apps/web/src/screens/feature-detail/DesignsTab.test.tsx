/* The UX designs tab of Feature detail: one designed screen at a time, beside the list of them. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aFeatureDetail,
  aGoldenPath,
  aGoldenStep,
  aProblem,
  aUxDesign,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { pickDesign } from "./DesignsTab";
import { FeatureDetailScreen } from "./index";
import { describePoint, mockupPageUrl } from "./MockupView";

const API = "/api/v1/features/agent-hub/control-plane";
const NOTE = "/api/v1/projects/agent-hub/brain/note";
const route = "features/:project/:slug";

const designs = [
  aUxDesign(),
  aUxDesign({
    path: "features/control-plane/ux-change-sidebar.md",
    screen: "sidebar",
    change: "change",
    title: "Sidebar",
    approved: false,
  }),
];

function note(request: Request) {
  const path = new URL(request.url).searchParams.get("path") ?? "";
  return aBrainNote({
    path,
    markdown: `# Design of ${path}\n\n\`\`\`\n+---+\n| x |\n+---+\n\`\`\`\n`,
  });
}

function open(path: string, uxDesigns = designs) {
  return renderWithApi(<FeatureDetailScreen />, {
    routes: { [API]: aFeatureDetail({ ux_designs: uxDesigns }), [NOTE]: note },
    path,
    route,
  });
}

/** What the Discuss panel would be handed on this page: its starters and its brief. */
function DiscussProbe() {
  const { target } = useDiscuss();
  return (
    <>
      <output aria-label="discuss starters">
        {(target?.starters ?? []).map((starter) => starter.label).join(" | ")}
      </output>
      <output aria-label="discuss brief">{target?.brief ?? ""}</output>
    </>
  );
}

describe("Feature detail UX designs tab", () => {
  it("shows the first design and switches to another screen from the list", async () => {
    const { container } = open("/features/agent-hub/control-plane?doc=designs");

    expect(await screen.findByText("2 screens · 1 approved.", { exact: false })).toBeVisible();
    expect(
      await screen.findByRole("heading", {
        name: "Design of features/control-plane/ux-new-overview.md",
      }),
    ).toBeVisible();

    const nav = screen.getByRole("navigation", { name: "Designed screens" });
    await userEvent.click(within(nav).getByRole("button", { name: /Sidebar/ }));

    expect(
      await screen.findByRole("heading", {
        name: "Design of features/control-plane/ux-change-sidebar.md",
      }),
    ).toBeVisible();
    expect(within(nav).getByRole("button", { name: /Sidebar/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByText("Draft")).toBeVisible();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("opens on the UX designs tab while the feature is in UX design", async () => {
    renderWithApi(<FeatureDetailScreen />, {
      routes: {
        [API]: aFeatureDetail({ phase: "ux_design", ux_designs: designs }),
        [NOTE]: note,
      },
      path: "/features/agent-hub/control-plane",
      route,
    });

    expect(await screen.findByRole("tab", { name: /UX designs/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      await screen.findByRole("heading", {
        name: "Design of features/control-plane/ux-new-overview.md",
      }),
    ).toBeVisible();
  });

  it("opens the UX designs tab from its golden path step", async () => {
    const { router } = renderWithApi(<FeatureDetailScreen />, {
      routes: {
        [API]: aFeatureDetail({
          ux_designs: designs,
          golden_path: aGoldenPath({
            steps: [
              aGoldenStep({ name: "spec", state: "done", meta: null, progress: null }),
              aGoldenStep({ name: "ux_design", state: "partial", meta: null, progress: null }),
            ],
          }),
        }),
        [NOTE]: note,
      },
      path: "/features/agent-hub/control-plane?doc=spec",
      route,
    });

    await userEvent.click(
      await screen.findByRole("button", { name: "Open the UX designs of ux_design" }),
    );

    expect(screen.getByRole("tab", { name: /UX designs/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(router.state.location.search).toContain("doc=designs");
  });

  it("opens the design ?design= names, by its screen or by its file", async () => {
    open("/features/agent-hub/control-plane?doc=designs&design=sidebar");

    expect(
      await screen.findByRole("heading", {
        name: "Design of features/control-plane/ux-change-sidebar.md",
      }),
    ).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Designed screens" });
    expect(within(nav).getByRole("button", { name: /Sidebar/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("selects each of two designs of the same screen from the list", async () => {
    const twins = [
      aUxDesign({
        path: "features/control-plane/ux-new-orders.md",
        screen: "orders",
        title: "Orders",
      }),
      aUxDesign({
        path: "features/control-plane/ux-change-orders.md",
        screen: "orders",
        change: "change",
        title: "Orders filters",
      }),
    ];
    const { router } = open("/features/agent-hub/control-plane?doc=designs", twins);
    const nav = await screen.findByRole("navigation", { name: "Designed screens" });

    await userEvent.click(within(nav).getByRole("button", { name: /Orders filters/ }));

    expect(
      await screen.findByRole("heading", {
        name: "Design of features/control-plane/ux-change-orders.md",
      }),
    ).toBeVisible();
    expect(within(nav).getByRole("button", { name: /Orders filters/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(router.state.location.search).toContain("design=ux-change-orders");

    await userEvent.click(within(nav).getByRole("button", { name: /^Orders\s*new/ }));

    expect(
      await screen.findByRole("heading", {
        name: "Design of features/control-plane/ux-new-orders.md",
      }),
    ).toBeVisible();
  });

  it("hands Discuss the design starters and a brief naming the design", async () => {
    renderWithApi(
      <DiscussProvider>
        <FeatureDetailScreen />
        <DiscussProbe />
      </DiscussProvider>,
      {
        routes: { [API]: aFeatureDetail({ ux_designs: designs }), [NOTE]: note },
        path: "/features/agent-hub/control-plane?doc=designs&design=sidebar",
        route,
      },
    );

    await waitFor(() => {
      expect(screen.getByLabelText("discuss starters")).toHaveTextContent(
        "Walk me through this screen",
      );
    });
    const brief = screen.getByLabelText("discuss brief");
    expect(brief).toHaveTextContent("brain/features/control-plane/ux-change-sidebar.md");
    expect(brief).toHaveTextContent("I am looking at its UX designs tab.");
    expect(brief).not.toHaveTextContent("visual mockup");
  });

  it("shows the empty state when ?doc=designs names a feature with no UX designs", async () => {
    open("/features/agent-hub/control-plane?doc=designs", []);

    expect(await screen.findByText("No UX designs yet.")).toBeVisible();
  });

  it("leaves the tab out when the feature has no UX designs", async () => {
    open("/features/agent-hub/control-plane", []);

    expect(await screen.findByRole("tab", { name: /Spec/ })).toBeVisible();
    expect(screen.queryByRole("tab", { name: /UX designs/ })).toBeNull();
  });
});

describe("Feature detail UX mockups", () => {
  const withMockup = [aUxDesign({ mockup: "ux-new-overview.html" })];
  const MOCKUP = `${API}/mockups/ux-new-overview.html`;
  const MOCKUP_FILE = {
    project: "agent-hub",
    slug: "control-plane",
    name: "ux-new-overview.html",
    html: "<main data-ux='table'>Orders</main>",
    size: 36,
    sha256: "b".repeat(64),
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function openMockup(
    path = "/features/agent-hub/control-plane?doc=designs",
    routes: ApiRoutes = {},
  ) {
    return renderWithApi(
      <DiscussProvider>
        <FeatureDetailScreen />
        <DiscussProbe />
      </DiscussProvider>,
      {
        routes: {
          [API]: aFeatureDetail({ ux_designs: withMockup }),
          [NOTE]: note,
          [MOCKUP]: MOCKUP_FILE,
          ...routes,
        },
        path,
        route,
      },
    );
  }

  it("opens on the mockup, its own page in a frame with no scripts", async () => {
    openMockup();

    const frame = await screen.findByTitle("Mockup of overview");
    expect(frame).toHaveAttribute("sandbox", "allow-same-origin");
    // The page route sends the mockup's own policy (no request, inline styles only): a srcdoc
    // frame would inherit hub web's policy, which blocks the mockup's inline styles.
    expect(frame).toHaveAttribute(
      "src",
      "/api/v1/features/agent-hub/control-plane/mockups/ux-new-overview.html/page",
    );
    expect(frame).not.toHaveAttribute("srcdoc");
  });

  it("scales a mockup to the column's width on its first load", async () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.classList.contains("ah-mockup") ? 640 : 0;
    });
    openMockup();

    const frame = await screen.findByTitle("Mockup of overview");

    expect(frame.style.transform).toBe("scale(0.5)");
    await userEvent.click(screen.getByRole("button", { name: "Actual size" }));
    expect(frame.style.transform).toBe("scale(1)");
    expect(screen.getByRole("button", { name: "Fit to width" })).toBeVisible();
  });

  it("draws the mockup at its own size until the column is measured", async () => {
    openMockup();

    const frame = await screen.findByTitle("Mockup of overview");

    expect(frame.style.transform).toBe("scale(1)");
  });

  it("stops dropping pins on Escape", async () => {
    openMockup();

    await userEvent.click(await screen.findByRole("button", { name: "Comment on a point" }));
    expect(
      screen.getByRole("button", { name: "Click the mockup to drop a pin · Esc to stop" }),
    ).toHaveAttribute("aria-pressed", "true");
    await userEvent.keyboard("{Escape}");

    expect(screen.getByRole("button", { name: "Comment on a point" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(document.querySelector(".ah-mockup-layer")).toBeNull();
  });

  it("shows the problem with a retry when the mockup cannot be read", async () => {
    openMockup(undefined, {
      [MOCKUP]: aProblem({ status: 404, title: "Not found", detail: "No such mockup." }),
    });

    expect(await screen.findByText("No such mockup.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
    expect(screen.queryByTitle("Mockup of overview")).toBeNull();
  });

  it("tells Discuss about the mockup in its brief", async () => {
    openMockup();

    await screen.findByTitle("Mockup of overview");
    expect(screen.getByLabelText("discuss starters")).toHaveTextContent(
      "Walk me through this screen",
    );
    expect(screen.getByLabelText("discuss brief")).toHaveTextContent(
      "The design on screen has a visual mockup, `brain/features/control-plane/ux-new-overview.html`",
    );
  });

  it("shows the written design from the toggle", async () => {
    openMockup();

    await userEvent.click(await screen.findByRole("button", { name: /Written design/ }));

    expect(
      await screen.findByRole("heading", {
        name: "Design of features/control-plane/ux-new-overview.md",
      }),
    ).toBeVisible();
  });

  it("drops a numbered pin into the next Discuss message on a click in comment mode", async () => {
    openMockup();

    await userEvent.click(await screen.findByRole("button", { name: "Comment on a point" }));
    const layer = document.querySelector(".ah-mockup-layer");
    expect(layer).not.toBeNull();
    if (!layer) return;
    await userEvent.click(layer);

    expect(await screen.findByTitle("Pin 1")).toHaveTextContent("1");
    expect(screen.getByText("1 pin in your next Discuss message")).toBeVisible();
  });
});

describe("describePoint", () => {
  it("names the region and the text under the point", () => {
    const doc = document.implementation.createHTMLDocument("m");
    doc.body.innerHTML = "<section data-ux='filters'><button>Clear filters</button></section>";
    const button = doc.querySelector("button");
    doc.elementFromPoint = () => button;

    expect(describePoint(doc, 10, 10)).toBe('region "filters", <button>, reading "Clear filters"');
  });

  it("names the mockup's page route with each part encoded", () => {
    expect(mockupPageUrl("demo", "a b", "ux-new-a.html")).toBe(
      "/api/v1/features/demo/a%20b/mockups/ux-new-a.html/page",
    );
  });
});

describe("pickDesign", () => {
  const twins = [
    aUxDesign({ path: "features/f/ux-new-orders.md", screen: "orders" }),
    aUxDesign({ path: "features/f/ux-change-orders.md", screen: "orders" }),
  ];

  it("picks a design by its file, then by its screen, then the first", () => {
    expect(pickDesign(twins, "ux-change-orders")?.path).toBe("features/f/ux-change-orders.md");
    expect(pickDesign(twins, "ux-new-orders")?.path).toBe("features/f/ux-new-orders.md");
    expect(pickDesign(twins, "orders")?.path).toBe("features/f/ux-new-orders.md");
    expect(pickDesign(twins, null)?.path).toBe("features/f/ux-new-orders.md");
    expect(pickDesign([], "orders")).toBeNull();
  });
});
