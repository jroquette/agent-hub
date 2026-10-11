import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

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
};

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
  it("lists the five sections and marks the open one", () => {
    open("hubs");

    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual(["Hubs", "Collector", "Privacy", "Appearance", "About"]);
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
