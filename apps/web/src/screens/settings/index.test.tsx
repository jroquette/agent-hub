import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aCollectorStatus,
  aHub,
  aPage,
  aProblem,
  aSettings,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { SettingsScreen } from "./index";

const route = "settings/:section";
const routes: ApiRoutes = {
  "/api/v1/hubs": aPage([
    aHub(),
    aHub({
      id: "hub-2",
      project: "loki-trader",
      path: "/home/dev/loki-trader-hub",
      repos: ["tradeSentinel", "loki-ui"],
      lock_version: "0.3.0",
      lock_state: "sync_pending",
      warnings: ["pinned 0.3.1, running 0.4.0"],
    }),
  ]),
  "/api/v1/collector/status": aCollectorStatus(),
  "/api/v1/settings": aSettings(),
  "/api/v1/tracker/linear": aLinearConnection(),
};

function aLinearConnection(overrides: Record<string, unknown> = {}) {
  return {
    connected: false,
    source: null,
    account: null,
    problem: null,
    problem_kind: null,
    checked_at: null,
    key_path: "/home/dev/.config/agent-hub/linear-api-key",
    ...overrides,
  };
}

const CONNECTED = aLinearConnection({
  connected: true,
  source: "settings",
  account: {
    name: "Ada Example",
    email: "ada@example.com",
    workspace: "Example",
    url: "https://linear.app/example",
  },
  checked_at: "2026-10-17T12:00:00Z",
});

function open(section: string, extra: ApiRoutes = {}, connected = true) {
  const ui = connected ? (
    <GlobalStreamProvider project={null}>
      <SettingsScreen />
    </GlobalStreamProvider>
  ) : (
    <SettingsScreen />
  );
  return renderWithApi(ui, {
    routes: { ...routes, ...extra },
    path: `/settings/${section}`,
    route,
  });
}

describe("SettingsScreen", () => {
  it("lists the six sections and marks the open one", () => {
    open("hubs");

    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual(["Hubs", "Collector", "Linear", "Privacy", "Appearance", "About"]);
    expect(within(nav).getByRole("link", { name: "Hubs" })).toHaveAttribute("aria-current", "page");
  });

  it("lists registered hubs with their pin and lock state", async () => {
    open("hubs");

    const row = (await screen.findByText("loki-trader")).closest("tr");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent("2 repos");
    expect(row).toHaveTextContent("0.4.0 pinned · lock 0.3.0 · sync pending");
    expect(row).toHaveTextContent("pinned 0.3.1, running 0.4.0");
  });

  it("warns when a hub is pinned to another release and syncs it after confirming", async () => {
    const behind = aHub({ id: "hub-3", project: "old-hub", platform_pin: "0.3.0" });
    const { requests } = open("hubs", {
      "/api/v1/hubs": aPage([aHub(), behind]),
      "POST /api/v1/hubs/hub-3/platform-sync": {
        hub_id: "hub-3",
        previous_version: "0.3.0",
        version: "0.4.0",
        ok: true,
        exit_code: 0,
        output: ["updated hub.lock"],
        changed_files: ["hub.json", "hub.lock"],
      },
    });

    const card = await screen.findByLabelText("old-hub platform version");
    expect(card).toHaveTextContent("old-hub is pinned to 0.3.0, this hub web runs 0.4.0");
    expect(screen.queryByLabelText("agent-hub platform version")).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Sync to 0.4.0" }));
    const dialog = screen.getByRole("alertdialog", { name: "Sync old-hub to 0.4.0?" });
    expect(dialog).toHaveTextContent("platform.version 0.3.0 → 0.4.0");
    await userEvent.click(within(dialog).getByRole("button", { name: "Sync" }));

    expect(await within(card).findByText("Pinned to 0.4.0 and synced (was 0.3.0).")).toBeVisible();
    expect(card).toHaveTextContent("hub.json, hub.lock");
    const post = requests.find((r) => r.method === "POST");
    expect(new URL(post?.url ?? "").pathname).toBe("/api/v1/hubs/hub-3/platform-sync");
  });

  it("shows why a sync failed", async () => {
    open("hubs", {
      "/api/v1/hubs": aPage([aHub({ id: "hub-3", project: "old-hub", platform_pin: "0.3.0" })]),
      "POST /api/v1/hubs/hub-3/platform-sync": {
        hub_id: "hub-3",
        previous_version: "0.3.0",
        version: "0.3.0",
        ok: false,
        exit_code: 3,
        output: ["conflict: AGENTS.md"],
        changed_files: [],
      },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Sync to 0.4.0" }));
    await userEvent.click(screen.getByRole("button", { name: "Sync" }));

    expect(
      await screen.findByText("hub sync failed (exit 3); hub.json was put back to 0.3.0."),
    ).toBeVisible();
    expect(screen.getByLabelText("old-hub platform version")).toHaveTextContent(
      "conflict: AGENTS.md",
    );
  });

  it("removes a hub after confirming", async () => {
    const { requests } = open("hubs", { "DELETE /api/v1/hubs/hub-2": {} });

    await userEvent.click(await screen.findByRole("button", { name: "Remove loki-trader" }));
    const dialog = screen.getByRole("alertdialog", { name: "Stop reading loki-trader?" });
    expect(dialog).toHaveTextContent("The hub folder is not touched.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove hub" }));

    await waitFor(() => {
      expect(requests.some((r) => r.method === "DELETE")).toBe(true);
    });
    expect(new URL(requests.find((r) => r.method === "DELETE")?.url ?? "").pathname).toBe(
      "/api/v1/hubs/hub-2",
    );
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
  });

  it("keeps the confirmation open while the removal runs", async () => {
    open("hubs", { "DELETE /api/v1/hubs/hub-2": "pending" });

    await userEvent.click(await screen.findByRole("button", { name: "Remove loki-trader" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove hub" }));
    await userEvent.keyboard("{Escape}");
    for (const scrim of screen.getAllByRole("presentation")) {
      fireEvent.mouseDown(scrim);
      fireEvent.click(scrim);
    }

    expect(screen.getByRole("alertdialog", { name: "Stop reading loki-trader?" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Removing…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  });

  it("shows the removal's error in the confirmation after an Escape while it ran", async () => {
    open("hubs");
    let answer: (response: Response) => void = () => undefined;
    const stubbed = vi.mocked(globalThis.fetch);
    const routed = stubbed.getMockImplementation();
    stubbed.mockImplementation((input, init) => {
      const method = input instanceof Request ? input.method : (init?.method ?? "GET");
      if (method !== "DELETE") return routed ? routed(input, init) : Promise.reject(new Error());
      return new Promise<Response>((resolve) => {
        answer = resolve;
      });
    });

    await userEvent.click(await screen.findByRole("button", { name: "Remove loki-trader" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove hub" }));
    await userEvent.keyboard("{Escape}");
    await act(async () => {
      answer(
        new Response(
          JSON.stringify({ status: 409, title: "Conflict", detail: "The hub is in use." }),
          {
            status: 409,
            headers: { "content-type": "application/problem+json" },
          },
        ),
      );
      await Promise.resolve();
    });

    const dialog = screen.getByRole("alertdialog", { name: "Stop reading loki-trader?" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The hub is in use.");
  });

  it("keeps the hub when the removal is cancelled", async () => {
    const { requests } = open("hubs");

    await userEvent.click(await screen.findByRole("button", { name: "Remove agent-hub" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(requests.some((r) => r.method === "DELETE")).toBe(false);
  });

  it("moves focus to the hub path from Add hub", async () => {
    open("hubs");

    await userEvent.click(screen.getByRole("button", { name: "Add hub" }));

    expect(screen.getByLabelText("Hub path")).toHaveFocus();
  });

  it("registers a hub from the Add hub form", async () => {
    const { requests } = open("hubs", { "POST /api/v1/hubs": aHub({ id: "hub-3" }) });

    await userEvent.type(screen.getByLabelText("Hub path"), "/home/dev/third-hub");
    await userEvent.click(screen.getByRole("button", { name: "Register hub" }));

    await waitFor(() => {
      expect(requests.some((r) => r.method === "POST")).toBe(true);
    });
    expect(await requests.find((r) => r.method === "POST")?.json()).toEqual({
      path: "/home/dev/third-hub",
    });
  });

  it("shows the collector's database, counters and every source", async () => {
    open("collector");

    expect(await screen.findByTitle("/home/dev/.local/share/agent-hub/events.db")).toBeVisible();
    expect(screen.getByText("1,284")).toBeInTheDocument();
    expect(screen.getByText("hub web")).toBeInTheDocument();
    const sources = screen.getByRole("table");
    for (const source of ["claude_code", "transcript", "executor", "otel", "github", "linear"]) {
      expect(within(sources).getByText(source)).toBeInTheDocument();
    }
    expect(within(sources).getAllByText("not connected")).toHaveLength(3);
    expect(screen.getByText(/Connected/)).toBeInTheDocument();
  });

  it("shows Linear as connected in the collector's sources once a key works", async () => {
    open("collector", { "/api/v1/tracker/linear": CONNECTED });

    const sources = screen.getByRole("table");
    expect(await within(sources).findByRole("link", { name: /Linear: connected/ })).toHaveAttribute(
      "href",
      "/settings/linear",
    );
  });

  it("connects Linear with a key the server accepts", async () => {
    const { requests } = open("linear", { "PUT /api/v1/tracker/linear": CONNECTED });

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Linear API key"), "lin_api_synthetic");
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByText("Ada Example")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Example/ })).toHaveAttribute(
      "href",
      "https://linear.app/example",
    );
    expect(await requests.find((r) => r.method === "PUT")?.json()).toEqual({
      api_key: "lin_api_synthetic",
    });
  });

  it("shows why Linear refused a key and keeps it out of the connection", async () => {
    open("linear", {
      "PUT /api/v1/tracker/linear": aLinearConnection({
        source: "settings",
        problem: "Linear refused the key (HTTP 401).",
        problem_kind: "unauthorized",
      }),
    });

    await userEvent.type(await screen.findByLabelText("Linear API key"), "lin_api_wrong");
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Linear refused the key (HTTP 401).",
    );
    expect(screen.getByText("Not connected")).toBeInTheDocument();
  });

  it("checks and disconnects a saved Linear key", async () => {
    let saved = true;
    const { requests } = open("linear", {
      "/api/v1/tracker/linear": () => (saved ? CONNECTED : aLinearConnection()),
      "DELETE /api/v1/tracker/linear": () => {
        saved = false;
        return aLinearConnection();
      },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Check connection" }));
    await waitFor(() => {
      expect(requests.some((r) => r.url.includes("fresh=true"))).toBe(true);
    });
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByLabelText("Linear API key")).toBeInTheDocument();
  });

  it("has no serious a11y violations in Linear (a11y)", async () => {
    const { container } = open("linear", { "/api/v1/tracker/linear": CONNECTED });
    await screen.findByText("Ada Example");

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("shows the redaction ruleset and kinds in Privacy", async () => {
    open("privacy");

    expect(await screen.findByText("r1")).toBeInTheDocument();
    for (const kind of ["github token", "anthropic key", "secret"]) {
      expect(screen.getByText(kind)).toBeInTheDocument();
    }
    expect(screen.getByText(/is never read/, { selector: "b" })).toBeInTheDocument();
  });

  it("applies the theme and time zone from Appearance", async () => {
    open("appearance");

    await userEvent.click(screen.getByRole("button", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "UTC" }));
    expect(screen.getByRole("button", { name: "UTC" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Light" }));
  });

  it("shake: toggle shows off, writes and removes ah.shakeToSession", async () => {
    window.localStorage.removeItem("ah.shakeToSession");
    open("appearance");

    const toggle = screen.getByRole("checkbox", { name: "Shake to start a session" });
    expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    expect(toggle).toBeChecked();
    expect(window.localStorage.getItem("ah.shakeToSession")).toBe("on");
    await userEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(window.localStorage.getItem("ah.shakeToSession")).toBeNull();
  });

  it("has no serious a11y violations in Appearance (a11y)", async () => {
    const { container } = open("appearance");
    await screen.findByRole("checkbox", { name: "Shake to start a session" });

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("shows versions in About", async () => {
    open("about");

    expect(await screen.findByText("0.4.0 · 127.0.0.1:7420")).toBeInTheDocument();
    expect(screen.getByText("/api/v1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy diagnostics" })).toBeEnabled();
  });

  it("redirects the design's retention route to Privacy", async () => {
    const { router } = open("retention");

    await screen.findByRole("heading", { level: 2, name: "Privacy" });
    expect(router.state.location.pathname).toBe("/settings/privacy");
  });

  it("shows the 404 page for an unknown section", () => {
    open("billing");

    expect(screen.getByRole("heading", { name: "This page does not exist" })).toBeInTheDocument();
  });

  describe("states", () => {
    it("shows a skeleton while the hubs load", async () => {
      const { container } = open("hubs", { "/api/v1/hubs": "pending" });

      await waitFor(() => {
        expect(container.querySelector(".ah-skel")).not.toBeNull();
      });
    });

    it("shows the registry problem in the hubs region with Try again", async () => {
      open("hubs", {
        "/api/v1/hubs": aProblem({
          status: 503,
          title: "Hub registry unreadable",
          detail: "hubs.json is not valid JSON.",
        }),
      });

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Hub registry unreadable");
      expect(alert).toHaveTextContent("hubs.json is not valid JSON.");
      expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
      expect(screen.getByLabelText("Hub path")).toBeInTheDocument();
    });

    it("says no hub is registered when the list is empty", async () => {
      open("hubs", { "/api/v1/hubs": aPage([]) });

      expect(await screen.findByText("No hub registered yet.")).toBeInTheDocument();
    });

    it("shows the as-of stamp and the offline state when the collector is offline", async () => {
      open("collector", {}, false);

      expect(screen.getByText(/Stale · as of/)).toBeInTheDocument();
      expect(await screen.findByText(/Offline since/)).toBeInTheDocument();
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open("hubs");
    await screen.findByText("loki-trader");

    expect(await seriousViolations(container)).toEqual([]);
  });
});
