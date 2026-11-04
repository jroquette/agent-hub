/* The UX designs tab of Feature detail: one designed screen at a time, beside the list of them. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aBrainNote, aFeatureDetail, aUxDesign, renderWithApi } from "../../testing/builders";
import { FeatureDetailScreen } from "./index";

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
