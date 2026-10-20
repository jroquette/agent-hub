import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aFeature,
  aPage,
  aProjectSummary,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { NewFeatureScreen, composeFeatureMessage } from "./NewFeature";

function Probe() {
  const { target, open } = useDiscuss();
  return (
    <output aria-label="discuss">
      {open ? "open" : "closed"}|{target?.kind ?? ""}|{target?.starters?.[0]?.message ?? ""}
    </output>
  );
}

const IDEA = "Owners export the orders of a period as CSV.";

function renderNew(routes: ApiRoutes = {}) {
  return renderWithApi(
    <DiscussProvider>
      <NewFeatureScreen />
      <Probe />
    </DiscussProvider>,
    {
      routes: {
        "/api/v1/projects": aPage([aProjectSummary()]),
        "/api/v1/features": aPage([aFeature()]),
        ...routes,
      },
      path: "/features/new",
    },
  );
}

describe("composeFeatureMessage", () => {
  it("names only the fields the owner filled", () => {
    expect(composeFeatureMessage({ idea: IDEA, issue: "", size: "", slug: "" })).toBe(
      `Start a new feature in this hub.\n\nThe idea:\n${IDEA}`,
    );
  });
});

describe("NewFeatureScreen", () => {
  it("waits for an idea or an issue before Claude can be asked", async () => {
    const user = userEvent.setup();
    renderNew();

    const start = await screen.findByRole("button", { name: "Start with Claude" });
    expect(start).toBeDisabled();
    await user.type(screen.getByLabelText("Tracker issue (optional)"), "agh-12");
    expect(start).toBeEnabled();
  });

  it("refuses a slug that already names a feature", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await user.type(screen.getByLabelText("Slug (optional)"), "control-plane");

    expect(await screen.findByText("A feature with this slug already exists.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start with Claude" })).toBeDisabled();
  });

  it("opens the Discuss panel on the golden-path request built from the form", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await user.type(screen.getByLabelText("Tracker issue (optional)"), "AGH-12");
    await user.type(screen.getByLabelText("Slug (optional)"), "orders-csv");
    await user.selectOptions(screen.getByLabelText("Size"), "bounded");
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));

    const discuss = screen.getByRole("status", { name: "discuss" });
    expect(discuss).toHaveTextContent("open|New feature|");
    expect(discuss).toHaveTextContent("Tracker issue: AGH-12");
    expect(discuss).toHaveTextContent("Slug: orders-csv");
    expect(discuss).toHaveTextContent("Size: bounded");
    expect(discuss).toHaveTextContent(IDEA);
    const draft = Object.keys(window.localStorage).find((key) =>
      key.startsWith("ah.chat.draft.discuss.feature-new:agent-hub:"),
    );
    expect(window.localStorage.getItem(draft ?? "")).toContain("orders-csv");
  });

  it("links to the new feature once its record appears", async () => {
    const user = userEvent.setup();
    let written = false;
    renderNew({
      "/api/v1/features": () =>
        aPage(written ? [aFeature(), aFeature({ slug: "orders-csv" })] : [aFeature()]),
    });

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));
    expect(screen.queryByRole("link", { name: "Open the feature" })).toBeNull();
    written = true;

    expect(
      await screen.findByRole("link", { name: "Open the feature" }, { timeout: 5_000 }),
    ).toHaveAttribute("href", "/features/agent-hub/orders-csv");
  }, 10_000);

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderNew();

    await screen.findByRole("button", { name: "Start with Claude" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
