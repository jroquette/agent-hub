/* The UX designs tab of Feature detail: one designed screen at a time, beside the list of them. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DiscussProvider } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { aBrainNote, aFeatureDetail, aUxDesign, renderWithApi } from "../../testing/builders";
import { FeatureDetailScreen } from "./index";
import { describePoint, framedDocument } from "./MockupView";

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

  it("leaves the tab out when the feature has no UX designs", async () => {
    open("/features/agent-hub/control-plane", []);

    expect(await screen.findByRole("tab", { name: /Spec/ })).toBeVisible();
    expect(screen.queryByRole("tab", { name: /UX designs/ })).toBeNull();
  });
});

describe("Feature detail UX mockups", () => {
  const withMockup = [aUxDesign({ mockup: "ux-new-overview.html" })];
  const MOCKUP = `${API}/mockups/ux-new-overview.html`;

  function openMockup(path = "/features/agent-hub/control-plane?doc=designs") {
    return renderWithApi(
      <DiscussProvider>
        <FeatureDetailScreen />
      </DiscussProvider>,
      {
        routes: {
          [API]: aFeatureDetail({ ux_designs: withMockup }),
          [NOTE]: note,
          [MOCKUP]: {
            project: "agent-hub",
            slug: "control-plane",
            name: "ux-new-overview.html",
            html: "<main data-ux='table'>Orders</main>",
            size: 36,
            sha256: "b".repeat(64),
          },
        },
        path,
        route,
      },
    );
  }

  it("opens on the mockup, in a frame with no scripts and no network", async () => {
    openMockup();

    const frame = await screen.findByTitle("Mockup of overview");
    expect(frame).toHaveAttribute("sandbox", "allow-same-origin");
    const doc = frame.getAttribute("srcdoc") ?? "";
    expect(
      doc.startsWith('<meta http-equiv="Content-Security-Policy" content="default-src \'none\';'),
    ).toBe(true);
    expect(doc).toContain("<main data-ux='table'>Orders</main>");
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
    await userEvent.click(layer!);

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

  it("puts the policy before the mockup's own markup", () => {
    expect(framedDocument("<p>x</p>").endsWith("><p>x</p>")).toBe(true);
  });
});
