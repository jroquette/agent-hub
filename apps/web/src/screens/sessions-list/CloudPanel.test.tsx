import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aCapabilities, aCloudSession } from "../../testing/builders";
import {
  CloudPanel,
  cloudCommand,
  shellQuote,
  taskProblem,
  type CloudPanelProps,
} from "./CloudPanel";

function show(overrides: Partial<CloudPanelProps> = {}) {
  const props: CloudPanelProps = {
    capabilities: aCapabilities(),
    sessions: [aCloudSession()],
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

  it("builds a copyable start command with the task quoted for the shell (cloud start guidance)", async () => {
    const { panel } = show();

    await userEvent.type(
      within(panel).getByRole("textbox", { name: "Task" }),
      "Fix it's `ls` and $HOME",
    );

    const command = within(panel).getByRole("group", { name: "Cloud start command" });
    expect(command).toHaveTextContent("claude --cloud 'Fix it'\\''s `ls` and $HOME'");
    expect(within(command).getByRole("button", { name: "Copy command" })).toBeInTheDocument();
    expect(panel).toHaveTextContent("claude --teleport <id>");
    expect(panel).toHaveTextContent("Only https://claude.ai/code/ links open from here.");
  });

  it("offers no start form, start button or follow-up even when the CLI could (cloud)", () => {
    const { panel } = show({ capabilities: aCapabilities({ cloud: true, cloud_followup: true }) });

    expect(within(panel).queryByRole("button", { name: /Start/ })).toBeNull();
    expect(within(panel).queryByRole("textbox", { name: "One-shot follow-up" })).toBeNull();
    expect(within(panel).queryByRole("combobox")).toBeNull();
    expect(panel.querySelector("form")).toBeNull();
  });

  it("shows the command template and no copy until the task is valid (cloud)", async () => {
    const { panel } = show();
    const command = () => within(panel).getByRole("group", { name: "Cloud start command" });
    expect(command()).toHaveTextContent('claude --cloud "<task>"');
    expect(within(command()).queryByRole("button")).toBeNull();

    await userEvent.type(within(panel).getByRole("textbox", { name: "Task" }), "--help");

    expect(within(panel).getByText("A task cannot start with “-”.")).toBeInTheDocument();
    expect(command()).toHaveTextContent('claude --cloud "<task>"');
    expect(within(command()).queryByRole("button")).toBeNull();
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

describe("cloudCommand (cloud)", () => {
  it("quotes the task as one shell word whatever it holds", () => {
    expect(shellQuote("plain")).toBe("'plain'");
    expect(shellQuote("it's")).toBe("'it'\\''s'");
    expect(shellQuote('$(rm -rf ~) `id` "x" \\ !!')).toBe("'$(rm -rf ~) `id` \"x\" \\ !!'");
    expect(cloudCommand("Upgrade the linter")).toBe("claude --cloud 'Upgrade the linter'");
  });
});
