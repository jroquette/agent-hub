import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aFinding,
  aHub,
  aPage,
  aProblem,
  aStreamCounts,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { HealthScreen } from "./index";

const findings = [
  aFinding({
    rule: "instructions.size",
    severity: "error",
    path: "AGENTS.md",
    line: 1,
    message: "AGENTS.md: 132 lines, limit 100",
    fix: "Keep it a map: move detail into docs/ until it is 100 lines or fewer.",
  }),
  aFinding({
    rule: "lock.drift",
    severity: "warning",
    path: "hub.lock",
    message: "Sync pending (lock 0.3.0, pin 0.4.0)",
    fix: "Run `./hub sync`, review the diff, open a hub PR.",
  }),
  aFinding({
    rule: "lock.drift",
    severity: "warning",
    path: "hub.lock",
    line: 3,
    message: "Managed file edited by hand",
    fix: "Run `./hub sync` to rewrite it.",
  }),
  aFinding({
    rule: "brain.links",
    severity: "info",
    path: "brain/index.md",
    message: "One orphan note",
    fix: "Link it from brain/index.md.",
  }),
];

const routes: ApiRoutes = {
  "/api/v1/doctor/findings": aPage(findings),
  "/api/v1/hubs": aPage([aHub({ lock_version: "0.3.0", lock_state: "sync_pending" })]),
};

function open(extra: ApiRoutes = {}, connected = true) {
  const ui = connected ? (
    <GlobalStreamProvider project={null}>
      <HealthScreen />
    </GlobalStreamProvider>
  ) : (
    <HealthScreen />
  );
  return renderWithApi(ui, { routes: { ...routes, ...extra }, path: "/health" });
}

function group(rule: string): HTMLElement {
  const header = screen.getByRole("button", { name: new RegExp(`^${rule.replace(".", "\\.")}`) });
  const section = header.closest("section");
  if (!section) throw new Error(`no group ${rule}`);
  return section;
}

describe("HealthScreen", () => {
  it("counts findings by severity in the summary", async () => {
    open();

    const summary = await screen.findByRole("group", { name: "Findings by severity" });
    expect(within(summary).getByRole("button", { name: /1 error/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(summary).getByRole("button", { name: /2 warnings/ })).toBeInTheDocument();
    expect(within(summary).getByRole("button", { name: /1 info/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("groups findings by rule, worst first, with How to fix visible", async () => {
    open();

    await screen.findByText("AGENTS.md: 132 lines, limit 100");
    const headers = screen.getAllByRole("button", { expanded: true }).map((b) => b.textContent);
    expect(headers[0]).toMatch(/^instructions\.size/);
    expect(headers[1]).toMatch(/^lock\.drift.*2 warnings/);
    const drift = group("lock.drift");
    expect(within(drift).getAllByText("How to fix")).toHaveLength(2);
    expect(within(drift).getByText("Managed file edited by hand")).toBeInTheDocument();
    expect(within(drift).getAllByText("./hub sync").length).toBeGreaterThan(0);
  });

  it("copies a finding's fix and the finding as Markdown", async () => {
    const write = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: write },
      configurable: true,
    });
    open();

    await screen.findByText("AGENTS.md: 132 lines, limit 100");
    const size = group("instructions.size");
    await userEvent.click(within(size).getByRole("button", { name: "Copy fix" }));
    expect(write).toHaveBeenLastCalledWith(
      "Keep it a map: move detail into docs/ until it is 100 lines or fewer.",
    );
    await userEvent.click(within(size).getByRole("button", { name: "Copy finding as Markdown" }));
    expect(write).toHaveBeenLastCalledWith(
      "- [error] instructions.size AGENTS.md:1: AGENTS.md: 132 lines, limit 100. Fix: Keep it a map: move detail into docs/ until it is 100 lines or fewer.",
    );
  });

  it("hides info findings until their severity is turned on", async () => {
    open();

    await screen.findByText("AGENTS.md: 132 lines, limit 100");
    expect(screen.queryByText("brain.links")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /1 info/ }));
    expect(screen.getByText("brain.links")).toBeInTheDocument();
  });

  it("filters by area from the rail and collapses every group", async () => {
    open();

    await screen.findByText("AGENTS.md: 132 lines, limit 100");
    await userEvent.click(screen.getByRole("checkbox", { name: /lock/ }));
    expect(screen.queryByText("instructions.size")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(screen.queryByText("How to fix")).not.toBeInTheDocument();
  });

  it("shows the platform pin, the lock state and the P4 Run doctor", async () => {
    open();

    expect(
      await screen.findByText(
        (_, el) =>
          el?.tagName === "SPAN" && el.textContent === "Platform 0.3.0 synced · pinned 0.4.0",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Sync pending")).toBeInTheDocument();
    const run = screen.getByRole("button", { name: /Run doctor/ });
    expect(run).toBeDisabled();
    expect(run).toHaveAttribute("title", "Available in Phase 4. This version is read-only.");
  });

  it("asks for the scoped project's findings", async () => {
    const { requests } = renderWithApi(<HealthScreen />, {
      routes,
      path: "/health?scope=agent-hub",
    });

    await screen.findByText("AGENTS.md: 132 lines, limit 100");
    const url = new URL(requests.find((r) => r.url.includes("doctor"))?.url ?? "");
    expect(url.searchParams.get("project")).toBe("agent-hub");
  });

  it("refetches findings when the stream's doctor error count changes", async () => {
    const { requests, stream } = open();
    await screen.findByText("AGENTS.md: 132 lines, limit 100");
    const before = requests.filter((r) => r.url.includes("doctor")).length;

    act(() => {
      stream("/api/v1/events/stream").emit("counts", aStreamCounts({ doctor_errors: 2 }));
    });
    act(() => {
      stream("/api/v1/events/stream").emit("counts", aStreamCounts({ doctor_errors: 3 }));
    });

    await waitFor(() => {
      expect(requests.filter((r) => r.url.includes("doctor")).length).toBeGreaterThan(before);
    });
  });

  describe("states", () => {
    it("shows skeletons while findings load", async () => {
      const { container } = open({ "/api/v1/doctor/findings": "pending" });

      await waitFor(() => {
        expect(container.querySelector(".ah-skel")).not.toBeNull();
      });
      expect(screen.getByRole("heading", { level: 1, name: "Health" })).toBeInTheDocument();
    });

    it("shows the no-findings copy and the re-run command when the hub is healthy", async () => {
      open({ "/api/v1/doctor/findings": aPage([]) });

      expect(
        await screen.findByText("No findings. The hub passed every doctor check."),
      ).toBeInTheDocument();
      expect(screen.getByText("cd /home/dev/agent-hub-hub && ./hub doctor")).toBeInTheDocument();
    });

    it("shows the problem in the findings region with Try again", async () => {
      open({
        "/api/v1/doctor/findings": aProblem({
          status: 503,
          title: "Hub not readable",
          detail: "The hub at /home/dev/agent-hub-hub could not be read.",
        }),
      });

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Hub not readable");
      expect(alert).toHaveTextContent("could not be read");
      expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 1, name: "Health" })).toBeInTheDocument();
    });

    it("shows the as-of stamp when the collector is offline", async () => {
      open({}, false);

      expect(screen.getByText(/Stale · as of/)).toBeInTheDocument();
      await screen.findByText("AGENTS.md: 132 lines, limit 100");
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open();
    await screen.findByText("AGENTS.md: 132 lines, limit 100");

    expect(await seriousViolations(container)).toEqual([]);
  });
});
