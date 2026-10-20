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
  it("starts a read-only search on the picked repos and environments", async () => {
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

  it("waits for a repo before it can start", async () => {
    openDiscover();

    await userEvent.click(await screen.findByRole("checkbox", { name: /demo-api/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /demo-web/ }));

    expect(screen.getByText("Pick at least one repo.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Find services with Claude" })).toBeDisabled();
  });

  it("offers the review once Claude has finished", async () => {
    const { router } = openDiscover("/projects/demo/environments/discover?discovery=abc123abc123", {
      [ONE]: aDiscovery("finished", PROPOSAL) as RouteReply,
    });

    await userEvent.click(await screen.findByRole("button", { name: "Review 2 proposals" }));

    expect(router.state.location.pathname).toBe(
      "/projects/demo/environments/discover/abc123abc123",
    );
  });

  it("has no serious a11y violations", async () => {
    const { container } = openDiscover();
    await screen.findByRole("checkbox", { name: /demo-api/ });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("ReviewScreen", () => {
  it("adds the selected proposals for the team in one write", async () => {
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

  it("explains a service it cannot add without its environment", async () => {
    openReview();

    await userEvent.click(await screen.findByRole("checkbox", { name: "Add environment staging" }));

    expect(screen.getByText("Select an environment it runs in first.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Add 0 for the team" })).toBeDisabled();
  });

  it("shows what is probably missing and what Claude did not read", async () => {
    openReview();

    expect(await screen.findByText(/no definition found/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Add by hand" })).toBeVisible();
    expect(screen.getByText(/demo-api\/\.env\.staging \(env file\)/)).toBeVisible();
  });

  it("discards the proposal after a confirmation", async () => {
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
