import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aProjectSummary,
  aScenarioCatalog,
  aScenarioSummary,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { NewScenarioScreen } from "./NewScenario";

function Probe() {
  const { target, open } = useDiscuss();
  return (
    <>
      <output aria-label="discuss">
        {open ? "open" : "closed"}|{target?.kind ?? ""}|{target?.starters?.[0]?.message ?? ""}
      </output>
      <output aria-label="brief">{target?.brief ?? ""}</output>
    </>
  );
}

function aConfig() {
  return {
    project: "agent-hub",
    environments: {
      environments: [
        {
          name: "personal",
          access: "write",
          production: false,
          description: null,
          credentials: null,
          source: "hub.json",
          team_access: "write",
        },
      ],
      services: [],
      blocked_words: [],
      blocked_files: [],
      blocked_env: [],
    },
  };
}

const BASE: ApiRoutes = {
  "/api/v1/projects": aPage([aProjectSummary()]),
  "/api/v1/projects/agent-hub/config": aConfig(),
  "/api/v1/scenarios": aScenarioCatalog({
    items: [aScenarioSummary({ project: "agent-hub", pack: "orders" })],
  }),
};

function renderNew(routes: ApiRoutes = {}) {
  return renderWithApi(
    <DiscussProvider>
      <NewScenarioScreen />
      <Probe />
    </DiscussProvider>,
    { routes: { ...BASE, ...routes }, path: "/scenarios/new" },
  );
}

describe("NewScenarioScreen", () => {
  it("creates a blank scenario to build with blocks, and opens it", async () => {
    const user = userEvent.setup();
    const { requests, router } = renderNew({
      "PUT /api/v1/scenarios/agent-hub/record-roundtrip": {
        path: "scenarios/orders/record-roundtrip.yaml",
        revision: 1,
        content_hash: "sha256:new",
        yaml: "",
        changed: true,
        versioned: true,
      },
    });

    const blank = await screen.findByRole("button", {
      name: "Create it blank and build with blocks",
    });
    expect(blank).toBeDisabled();
    await user.selectOptions(await screen.findByLabelText("Pack"), "orders");
    await user.type(screen.getByLabelText("Name (optional)"), "record-roundtrip");
    await user.click(blank);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/scenarios/agent-hub/record-roundtrip");
    });
    const put = requests.find((request) => request.method === "PUT");
    const body = (await put?.clone().json()) as {
      pack: string;
      base_content_hash: string | null;
      document: { version: number; nodes?: unknown; stages: { name: string; steps: unknown[] }[] };
    };
    expect(body.base_content_hash).toBeNull();
    expect(body.pack).toBe("orders");
    // Written as blocks: one stage holding the one block to replace.
    expect(body.document.version).toBe(2);
    expect(body.document.nodes).toBeUndefined();
    expect(body.document.stages).toEqual([
      {
        name: "First stage",
        steps: [{ you: "Replace this block with the first step of the scenario." }],
      },
    ]);
  });

  it("waits for a description before Claude can be asked", async () => {
    renderNew();

    expect(await screen.findByRole("button", { name: "Create with Claude" })).toBeDisabled();
  });

  it("refuses a name that is not kebab-case", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.type(await screen.findByLabelText("Name (optional)"), "Bad_Name");

    expect(screen.getByText(/Lowercase letters, digits and dashes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create with Claude" })).toBeDisabled();
  });

  it("opens the Discuss panel on a request built from the form", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.click(await screen.findByRole("button", { name: "Create, then wait for a state" }));
    await user.selectOptions(await screen.findByLabelText("Environment"), "personal");
    await user.selectOptions(screen.getByLabelText("Pack"), "orders");
    await user.type(screen.getByLabelText("Name (optional)"), "order-to-invoice");
    await user.click(screen.getByRole("button", { name: "Create with Claude" }));

    const discuss = screen.getByRole("status", { name: "discuss" });
    expect(discuss).toHaveTextContent("open|New scenario|");
    expect(discuss).toHaveTextContent("Name: order-to-invoice");
    expect(discuss).toHaveTextContent("Pack: orders");
    expect(discuss).toHaveTextContent("Environment: personal");
    expect(discuss).toHaveTextContent("Create a test record");
    const draft = Object.keys(window.localStorage).find((key) =>
      key.startsWith("ah.chat.draft.discuss.scenario-new:agent-hub:"),
    );
    expect(window.localStorage.getItem(draft ?? "")).toContain("order-to-invoice");
    // Claude is taught the blocks format, so the scenario it writes opens as stages.
    const brief = screen.getByRole("status", { name: "brief" });
    expect(brief).toHaveTextContent("version: 2");
    expect(brief).toHaveTextContent("wait_until: <read action>");
    expect(brief).not.toHaveTextContent("schema v1");
  });

  it("takes a new pack's name and refuses one that is not kebab-case", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.click(await screen.findByRole("button", { name: "Health check" }));
    await user.selectOptions(await screen.findByLabelText("Pack"), "A new pack…");
    await user.type(screen.getByLabelText("New pack name"), "Bad Pack");
    expect(screen.getByRole("button", { name: "Create with Claude" })).toBeDisabled();

    await user.clear(screen.getByLabelText("New pack name"));
    await user.type(screen.getByLabelText("New pack name"), "health");
    await user.click(screen.getByRole("button", { name: "Create with Claude" }));

    expect(screen.getByRole("status", { name: "discuss" })).toHaveTextContent("Pack: health");
  });

  it("says the new scenario loads, with a link to it, once the catalog lists it", async () => {
    const user = userEvent.setup();
    renderNew({
      "/api/v1/scenarios": aScenarioCatalog({
        items: [
          aScenarioSummary({ project: "agent-hub", pack: "orders" }),
          aScenarioSummary({ project: "agent-hub", name: "order-to-invoice" }),
        ],
      }),
    });

    await user.click(await screen.findByRole("button", { name: "Create, then wait for a state" }));
    await user.type(screen.getByLabelText("Name (optional)"), "order-to-invoice");
    await user.click(screen.getByRole("button", { name: "Create with Claude" }));

    expect(await screen.findByRole("link", { name: "Open it and plan it" })).toHaveAttribute(
      "href",
      "/scenarios/agent-hub/order-to-invoice",
    );
  });

  it("asks for a hub first when there is no project", async () => {
    renderNew({ "/api/v1/projects": aPage([]) });

    expect(await screen.findByText("No project yet.")).toBeInTheDocument();
  });

  it("a11y: has no serious violations", async () => {
    const { container } = renderNew();
    await screen.findByLabelText("Environment");

    expect(await seriousViolations(container)).toEqual([]);
  });
});
