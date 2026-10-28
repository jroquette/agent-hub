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
import { codeText } from "../../testing/text";

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
    expect(within(drift).getAllByText(codeText("./hub sync")).length).toBeGreaterThan(0);
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

  it("links a platform.version error to the sync in Settings", async () => {
    open({
      "/api/v1/doctor/findings": aPage([
        aFinding({
          rule: "platform.version",
          severity: "error",
          path: "hub.json",
          message: "this hub is pinned to 0.3.0 but this hub command is 0.4.0",
          fix: "run the pinned release",
        }),
      ]),
    });

    await screen.findByText(/pinned to 0\.3\.0/);
    expect(
      within(group("platform.version")).getByRole("link", { name: "Sync in Settings" }),
    ).toHaveAttribute("href", "/settings/hubs");
    expect(screen.queryByRole("link", { name: "Sync in Settings" })).toBeInTheDocument();
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
      expect(
        screen.getByText(codeText("cd /home/dev/agent-hub-hub && ./hub doctor")),
      ).toBeInTheDocument();
      // AC-596.5.19: the command is coloured as shell, not only found by its text.
      const command = screen.getByText(codeText("cd /home/dev/agent-hub-hub && ./hub doctor"));
      await waitFor(() => {
        expect(command).toHaveClass("hljs");
      });
      expect(command.querySelector("span[class^='hljs-']")).not.toBeNull();
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

  it("offers one command that fixes every brain.leak, split by file", async () => {
    const user = userEvent.setup();
    const leaks = Array.from({ length: 12 }, (_, n) =>
      aFinding({
        rule: "brain.leak",
        severity: "error",
        path: n < 11 ? "../demo-api/docs/adr/0001.md" : "../demo-api/README.md",
        line: n + 1,
        message: `line also in the brain at brain/drafts/0001.md:${String(n + 1)}`,
        fix: "reword or remove the line here, or reword the brain note if it quotes this file",
      }),
    );
    open({ "/api/v1/doctor/findings": aPage([...leaks, ...findings]) });

    const strip = await screen.findByRole("region", { name: "Automatic fixes" });
    expect(strip).toHaveTextContent("12 of 16 findings can be fixed automatically");
    expect(strip).toHaveTextContent("4 need a person");
    expect(strip).toHaveTextContent("./hub doctor --fix");

    const leak = group("brain.leak");
    expect(within(leak).getByText("Auto-fix")).toBeInTheDocument();
    expect(within(leak).getByText(/doctor --fix --only brain\.leak/)).toBeInTheDocument();
    const file = within(leak).getByRole("button", { name: /0001\.md.*11 lines/ });
    expect(within(leak).queryByText("Copy fix")).toBeNull();
    await user.click(file);
    expect(within(leak).getAllByRole("button", { name: "Copy fix" })).toHaveLength(11);
    expect(within(group("lock.drift")).getByText("Needs a person")).toBeInTheDocument();
  });

  it("fixes every auto-fixable finding from the screen after confirming", async () => {
    const user = userEvent.setup();
    const leak = aFinding({
      rule: "brain.leak",
      severity: "error",
      path: "../demo-api/docs/adr/0001.md",
      line: 1,
      message: "line also in the brain at brain/drafts/0001.md:1",
      fix: "reword or remove the line here, or reword the brain note if it quotes this file",
    });
    const { requests } = open({
      "/api/v1/doctor/findings": aPage([leak, ...findings]),
      "/api/v1/hubs": aPage([aHub({ id: "hub-1", project: "demo" })]),
      "POST /api/v1/hubs/hub-1/doctor-fix": {
        hub_id: "hub-1",
        ok: true,
        exit_code: 1,
        output: ["fixed brain/drafts/0001.md: 1 lines now point at the repo"],
        changed_files: ["brain/drafts/0001.md"],
        errors_left: 1,
        warnings_left: 2,
      },
    });

    await user.click(await screen.findByRole("button", { name: "Fix 1 finding" }));
    const dialog = screen.getByRole("alertdialog", { name: "Fix 1 finding in demo?" });
    expect(dialog).toHaveTextContent("never a code repo");
    await user.click(within(dialog).getByRole("button", { name: "Fix" }));

    const done = await screen.findByRole("status", { name: "Fix result" });
    expect(done).toHaveTextContent("Fixed 1 file. Doctor ran again: 1 error, 2 warnings left.");
    expect(done).toHaveTextContent("fixed brain/drafts/0001.md");
    const post = requests.find((r) => r.method === "POST");
    expect(new URL(post?.url ?? "").pathname).toBe("/api/v1/hubs/hub-1/doctor-fix");
  });

  const leakFinding = aFinding({
    rule: "brain.leak",
    severity: "error",
    path: "../demo-api/docs/adr/0001.md",
    line: 1,
    message: "line also in the brain at brain/drafts/0001.md:1",
    fix: "reword or remove the line here, or reword the brain note if it quotes this file",
  });

  it("AC-PG-26.3 says Nothing to fix when the fix changed no file", async () => {
    const user = userEvent.setup();
    open({
      "/api/v1/doctor/findings": aPage([leakFinding, ...findings]),
      "/api/v1/hubs": aPage([aHub({ id: "hub-1", project: "demo" })]),
      "POST /api/v1/hubs/hub-1/doctor-fix": {
        hub_id: "hub-1",
        ok: true,
        exit_code: 0,
        output: [],
        changed_files: [],
        errors_left: 0,
        warnings_left: 2,
      },
    });

    await user.click(await screen.findByRole("button", { name: "Fix 1 finding" }));
    await user.click(
      within(screen.getByRole("alertdialog", { name: "Fix 1 finding in demo?" })).getByRole(
        "button",
        { name: "Fix" },
      ),
    );

    const done = await screen.findByRole("status", { name: "Fix result" });
    expect(done).toHaveTextContent("Nothing to fix: no file changed.");
    expect(done).toHaveTextContent("Doctor ran again: 0 errors, 2 warnings left.");
    expect(done).not.toHaveTextContent("Fixed");
  });

  it("AC-PG-26.3 asks to pick a project when All projects are in scope", async () => {
    const { requests } = open({
      "/api/v1/doctor/findings": aPage([leakFinding, ...findings]),
      "/api/v1/hubs": aPage([
        aHub({ id: "hub-1", project: "demo" }),
        aHub({ id: "hub-2", project: "loki-trader" }),
      ]),
    });

    const strip = await screen.findByRole("region", { name: "Automatic fixes" });
    await waitFor(() => {
      expect(strip).toHaveTextContent("Pick a project to fix");
    });
    expect(within(strip).queryByRole("button", { name: /^Fix/ })).toBeNull();
    expect(requests.some((r) => r.method === "POST")).toBe(false);
  });
});
