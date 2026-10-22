import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { DiscussProvider } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { aCapabilities, renderWithApi } from "../../testing/builders";
import type { ApiRoutes, RouteReply } from "../../testing/builders";
import { DiscoverScreen } from "./DiscoverPage";
import { ReviewScreen } from "./ReviewPage";

const CONFIG = "/api/v1/projects/demo/config";
const DISCOVERIES = "/api/v1/projects/demo/environment-discoveries";
const ONE = `${DISCOVERIES}/abc123abc123`;
const WRITE = "POST /api/v1/projects/demo/config/environments";
const CAPABILITIES = "/api/v1/agent-sessions/capabilities";

function aConfig() {
  return {
    project: "demo",
    local_file: { name: "hub.local.json", path: "/hubs/demo-hub/hub.local.json", problems: [] },
    repos: [
      { dir: "demo-api", github: "acme/demo-api", role: "backend" },
      { dir: "demo-web", github: "acme/demo-web", role: "frontend" },
    ],
    environments: {
      environments: [
        {
          name: "local",
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

function aDiscovery(state: string, proposal: unknown = null) {
  return {
    id: "abc123abc123",
    project: "demo",
    agent_session_id: "as-1",
    repos: ["demo-api"],
    environments: ["local"],
    suggest_environments: true,
    created_at: "2026-10-20T10:00:00Z",
    state,
    problem: null,
    proposal,
  };
}

const PROPOSAL = {
  environments: [
    {
      name: "staging",
      preset: "staging",
      access: "ask",
      production: false,
      description: null,
      aws_profile: null,
      env_file: null,
      evidence: [{ path: "demo-api/serverless.yml", line: 12 }],
      status: "new",
      yours: null,
    },
  ],
  services: [
    {
      repo: "demo-api",
      name: "orders-queue",
      kind: "queue",
      description: null,
      evidence: [{ path: "demo-api/serverless.yml", line: 40 }],
      status: "new",
      addresses: [
        {
          environment: "staging",
          address: "orders-queue-staging",
          note: null,
          evidence: [],
          status: "new",
          yours: null,
        },
      ],
    },
  ],
  missing: [
    {
      repo: "demo-api",
      name: "orders-dlq",
      kind: "queue",
      why: "Sent to in handlers/orders.py:88, no definition found",
      evidence: [],
    },
  ],
  not_read: [{ path: "demo-api/.env.staging", reason: "env file" }],
  dropped: [],
};

function openDiscover(path = "/projects/demo/environments/discover", routes: ApiRoutes = {}) {
  return renderWithApi(createElement(DiscussProvider, null, createElement(DiscoverScreen)), {
    routes: {
      [CONFIG]: aConfig(),
      [CAPABILITIES]: aCapabilities(),
      ...routes,
    },
    path,
    route: "projects/:project/environments/discover",
  });
}

function openReview(routes: ApiRoutes = {}) {
  return renderWithApi(createElement(DiscussProvider, null, createElement(ReviewScreen)), {
    routes: {
      [CONFIG]: aConfig(),
      [ONE]: aDiscovery("finished", PROPOSAL),
      ...routes,
    },
    path: "/projects/demo/environments/discover/abc123abc123",
    route: "projects/:project/environments/discover/:discoveryId",
  });
}

describe("DiscoverScreen", () => {
  it("AC-418.9 starts a read-only search on the picked repos and environments at once", async () => {
    const { requests, router } = openDiscover(undefined, {
      [`POST ${DISCOVERIES}`]: aDiscovery("running") as RouteReply,
    });

    await userEvent.click(await screen.findByRole("checkbox", { name: /demo-web/ }));
    await userEvent.click(screen.getByRole("button", { name: "Find services with Claude" }));

    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      repos: ["demo-api"],
      environments: ["local"],
      suggest_environments: true,
    });
    expect(router.state.location.search).toBe("?discovery=abc123abc123");
  });

  it("AC-418.9 waits for a repo before it can start", async () => {
    openDiscover();

    await userEvent.click(await screen.findByRole("checkbox", { name: /demo-api/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /demo-web/ }));

    expect(screen.getByText("Pick at least one repo.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Find services with Claude" })).toBeDisabled();
  });

  it("AC-418.10 offers the review once Claude has finished", async () => {
    const { router } = openDiscover("/projects/demo/environments/discover?discovery=abc123abc123", {
      [ONE]: aDiscovery("finished", PROPOSAL) as RouteReply,
    });

    await userEvent.click(await screen.findByRole("button", { name: "Review 2 proposals" }));

    expect(router.state.location.pathname).toBe(
      "/projects/demo/environments/discover/abc123abc123",
    );
  });

  it("AC-418.9 checks every repo and environment and the suggestion when it opens", async () => {
    openDiscover();

    expect(await screen.findByRole("checkbox", { name: /demo-api/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /demo-web/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^local/ })).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /Suggest environments we have not declared/ }),
    ).toBeChecked();
  });

  it("AC-418.10 shows a running search with Stop and the conversation", async () => {
    openDiscover("/projects/demo/environments/discover?discovery=abc123abc123", {
      [ONE]: aDiscovery("running") as RouteReply,
    });

    expect(await screen.findByRole("heading", { name: "Claude is reading 1 repo" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Stop" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the conversation" })).toHaveAttribute(
      "href",
      "/agent-sessions/as-1",
    );
  });

  it("AC-418.10 says nothing was written when the search was stopped", async () => {
    const { router } = openDiscover("/projects/demo/environments/discover?discovery=abc123abc123", {
      [ONE]: aDiscovery("stopped") as RouteReply,
    });

    expect(
      await screen.findByText("Stopped before Claude sent its proposal. Nothing was written."),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Start again" }));

    expect(router.state.location.search).toBe("");
  });

  it("AC-418.10 gives the reason when the search failed", async () => {
    openDiscover("/projects/demo/environments/discover?discovery=abc123abc123", {
      [ONE]: { ...aDiscovery("failed"), problem: "The reply held no JSON proposal" } as RouteReply,
    });

    expect(await screen.findByText("Claude could not finish reading the repos")).toBeVisible();
    expect(
      screen.getByText("The reply held no JSON proposal. Nothing was written.", { exact: false }),
    ).toBeVisible();
  });

  it("has no serious a11y violations", async () => {
    const { container } = openDiscover();
    await screen.findByRole("checkbox", { name: /demo-api/ });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("ReviewScreen", () => {
  it("AC-418.12 adds the selected proposals for the team in one write", async () => {
    const { requests } = openReview({ [WRITE]: aConfig() as RouteReply });

    const bar = await screen.findByRole("region", { name: "Add the selected proposals" });
    expect(within(bar).getByText("2 items selected")).toBeVisible();
    await userEvent.click(within(bar).getByRole("button", { name: "Add 2 for the team" }));

    expect(await screen.findByText("Added 1 environment and 1 service")).toBeVisible();
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toMatchObject({
      op: "batch",
      ops: [
        { op: "add_environment", scope: "team", name: "staging", access: "ask" },
        {
          op: "add_service",
          repo: "demo-api",
          service: "orders-queue",
          addresses: [{ environment: "staging", address: "orders-queue-staging", note: null }],
        },
      ],
    });
  });

  it("AC-418.11 shows each proposal with where it was found and its status, new ones selected", async () => {
    openReview();

    const table = await screen.findByRole("table", { name: "Proposals from Claude" });
    expect(within(table).getByRole("checkbox", { name: "Add environment staging" })).toBeChecked();
    expect(
      within(table).getByRole("button", { name: "Copy demo-api/serverless.yml:12" }),
    ).toBeVisible();
    expect(within(table).getAllByText("New")).toHaveLength(2);
  });

  it("AC-418.11 shows one status at a time when filtered", async () => {
    openReview();

    await screen.findByRole("table", { name: "Proposals from Claude" });
    await userEvent.click(screen.getByRole("button", { name: "Already declared 0" }));

    expect(screen.queryByRole("checkbox", { name: "Add environment staging" })).toBeNull();
  });

  it("AC-418.12 explains a service it cannot add without its environment", async () => {
    openReview();

    await userEvent.click(await screen.findByRole("checkbox", { name: "Add environment staging" }));

    expect(screen.getByText("Select an environment it runs in first.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Add 0 for the team" })).toBeDisabled();
  });

  it("AC-418.13 shows what is probably missing and what Claude did not read", async () => {
    openReview();

    expect(await screen.findByText(/no definition found/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Add by hand" })).toBeVisible();
    expect(screen.getByText(/demo-api\/\.env\.staging \(env file\)/)).toBeVisible();
  });

  it("AC-418.13 discards the proposal after a confirmation", async () => {
    const { requests, router } = openReview({
      [`DELETE ${ONE}`]: {},
    });

    await userEvent.click(await screen.findByRole("button", { name: "Discard proposal" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog", { name: "Discard Claude's proposal?" })).getByRole(
        "button",
        { name: "Discard proposal" },
      ),
    );

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/projects/demo/environments");
    });
    expect(requests.some((r) => r.method === "DELETE")).toBe(true);
  });

  it("has no serious a11y violations", async () => {
    const { container } = openReview();
    await screen.findByRole("table", { name: "Proposals from Claude" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
