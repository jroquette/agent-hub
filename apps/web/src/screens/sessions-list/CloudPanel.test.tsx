import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { seriousViolations } from "../../testing/axe";
import { aCapabilities, aCloudSession, aWorkdir } from "../../testing/builders";
import { CloudPanel, taskProblem, type CloudPanelProps } from "./CloudPanel";

function show(overrides: Partial<CloudPanelProps> = {}) {
  const props: CloudPanelProps = {
    capabilities: aCapabilities(),
    project: "agent-hub",
    workdirs: [aWorkdir()],
    sessions: [aCloudSession()],
    onStart: vi.fn(),
    onFollowUp: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
  const view = render(<CloudPanel {...props} />);
  return { ...view, props, panel: screen.getByRole("region", { name: "Start in the cloud" }) };
}

describe("CloudPanel (cloud)", () => {
  it("shows the link-out, the teleport command and the limited-control label when cloud is capable", () => {
    const { panel } = show();
    const session = aCloudSession();

    const item = within(within(panel).getByRole("list", { name: "Cloud sessions" })).getByRole(
      "listitem",
    );
    expect(within(item).getByRole("link", { name: /Open in claude\.ai/ })).toHaveAttribute(
      "href",
      session.url,
    );
    expect(within(item).getByRole("link")).toHaveAttribute("target", "_blank");
    expect(within(item).getByRole("group", { name: "Teleport command" })).toHaveTextContent(
      session.teleport_command,
    );
    expect(within(item).getByText("cloud: limited control")).toBeInTheDocument();
  });

  it("shows guidance only when the CLI has no cloud capability", () => {
    const { panel } = show({
      capabilities: aCapabilities({ cloud: false, cloud_followup: false }),
    });

    expect(panel).toHaveTextContent("This claude does not offer cloud sessions");
    expect(panel).toHaveTextContent("claude --teleport <id>");
    expect(within(panel).queryByRole("link")).toBeNull();
    expect(within(panel).queryByRole("textbox")).toBeNull();
    expect(within(panel).queryByRole("list")).toBeNull();
  });

  it("never renders a link when the url is not under claude.ai/code (claude-code-link)", () => {
    const { panel } = show({
      sessions: [
        aCloudSession({ url: "https://evil.example/code/x" }),
        aCloudSession({ id: "c2", url: null }),
      ],
    });

    expect(within(panel).queryByRole("link")).toBeNull();
    expect(
      within(panel).getAllByText("No link: the session address is not a claude.ai/code URL."),
    ).toHaveLength(2);
  });

  it("starts a cloud task as typed from the chosen folder", async () => {
    const { panel, props } = show();

    await userEvent.type(
      within(panel).getByRole("textbox", { name: "Task" }),
      "Upgrade the linter",
    );
    await userEvent.click(within(panel).getByRole("button", { name: "Start in the cloud" }));

    expect(props.onStart).toHaveBeenCalledWith({
      project: "agent-hub",
      workdir_id: aWorkdir().workdir_id,
      task: "Upgrade the linter",
    });
  });

  it("refuses a task that starts with a dash", async () => {
    const { panel, props } = show();

    await userEvent.type(within(panel).getByRole("textbox", { name: "Task" }), "--help");

    expect(within(panel).getByText("A task cannot start with “-”.")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Start in the cloud" })).toBeDisabled();
    expect(props.onStart).not.toHaveBeenCalled();
  });

  it("shows progress and the problem the start answered", () => {
    const { rerender, props } = show({ pending: true });
    expect(screen.getByRole("status")).toHaveTextContent("Starting the cloud session…");

    rerender(
      <CloudPanel
        {...props}
        pending={false}
        error={
          new ApiProblem({ status: 501, title: "Not available", detail: "Use claude.ai/code" })
        }
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Not available: Use claude.ai/code");
  });

  it("sends a one-shot follow-up when the CLI supports it", async () => {
    const { panel, props } = show();

    await userEvent.type(
      within(panel).getByRole("textbox", { name: "One-shot follow-up" }),
      "Status?",
    );
    await userEvent.click(within(panel).getByRole("button", { name: "Send" }));

    expect(props.onFollowUp).toHaveBeenCalledWith(aCloudSession().cloud_id, "Status?");
    expect(await within(panel).findByRole("status")).toHaveTextContent("Sent.");
  });

  it("says so when a follow-up fails", async () => {
    const { panel } = show({ onFollowUp: vi.fn(() => Promise.reject(new Error("502"))) });

    await userEvent.type(within(panel).getByRole("textbox", { name: "One-shot follow-up" }), "Hi");
    await userEvent.click(within(panel).getByRole("button", { name: "Send" }));

    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      "Could not send the follow-up",
    );
  });

  it("offers no follow-up without the follow-up capability", () => {
    const { panel } = show({ capabilities: aCapabilities({ cloud_followup: false }) });

    expect(within(panel).queryByRole("textbox", { name: "One-shot follow-up" })).toBeNull();
  });

  it("has no serious violation (cloud a11y)", async () => {
    const { container } = show();

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("taskProblem (cloud)", () => {
  it("accepts a task and names what is wrong otherwise", () => {
    expect(taskProblem("Fix it")).toBeNull();
    expect(taskProblem("  ")).toBe("Describe the task.");
    expect(taskProblem(" -x")).toBe("A task cannot start with “-”.");
    expect(taskProblem("x".repeat(64 * 1024 + 1))).toBe("Too long: at most 64 KiB.");
  });
});
