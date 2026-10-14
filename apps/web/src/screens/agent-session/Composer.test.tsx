import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { seriousViolations } from "../../testing/axe";
import { Composer, type ComposerProps } from "./Composer";

function open(overrides: Partial<ComposerProps> = {}) {
  const props: ComposerProps = {
    status: "idle",
    mode: "default",
    model: "sonnet",
    models: ["default", "opus", "sonnet", "haiku"],
    onSend: vi.fn(() => Promise.resolve()),
    onInterrupt: vi.fn(() => Promise.resolve()),
    onSettings: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
  const view = render(<Composer {...props} />);
  return { ...view, props, box: screen.getByRole("textbox", { name: "Message Claude" }) };
}

describe("Composer (composer)", () => {
  it("sends on Enter and clears the box", async () => {
    const { box, props } = open();

    await userEvent.type(box, "Run the tests{Enter}");

    expect(props.onSend).toHaveBeenCalledWith("Run the tests");
    expect(box).toHaveValue("");
  });

  it("inserts a newline on Shift+Enter without sending", async () => {
    const { box, props } = open();

    await userEvent.type(box, "one{Shift>}{Enter}{/Shift}two");

    expect(box).toHaveValue("one\ntwo");
    expect(props.onSend).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(props.onSend).toHaveBeenCalledWith("one\ntwo");
  });

  it("sends nothing when the box is blank", async () => {
    const { box, props } = open();

    await userEvent.type(box, "   {Enter}");

    expect(props.onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it.each([
    ["running", true],
    ["idle", false],
    ["waiting_permission", false],
    ["ended", false],
  ] as const)("enables Stop only while running when the status is %s", async (status, enabled) => {
    const { props } = open({ status });
    const stop = screen.getByRole("button", { name: "Stop" });

    if (enabled) {
      expect(stop).toBeEnabled();
      await userEvent.click(stop);
      expect(props.onInterrupt).toHaveBeenCalledTimes(1);
    } else {
      expect(stop).toBeDisabled();
    }
  });

  it("offers only the three web modes and posts a mode change", async () => {
    const { props } = open();
    const mode = screen.getByRole("combobox", { name: "Mode" });

    expect(
      within(mode)
        .getAllByRole("option")
        .map((option) => option.getAttribute("value")),
    ).toEqual(["default", "acceptEdits", "plan"]);
    await userEvent.selectOptions(mode, "plan");

    expect(props.onSettings).toHaveBeenCalledWith({ mode: "plan" });
  });

  it("posts a model change and keeps a custom current model in the list", async () => {
    const { props } = open({ model: "claude-opus-4-1" });
    const model = screen.getByRole("combobox", { name: "Model" });

    expect(model).toHaveValue("claude-opus-4-1");
    await userEvent.selectOptions(model, "haiku");

    expect(props.onSettings).toHaveBeenCalledWith({ model: "haiku" });
  });

  it("disables sending and settings when the session has ended", () => {
    open({ status: "failed" });

    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("textbox")).toHaveAttribute(
      "placeholder",
      "This session has ended. Resume it to continue.",
    );
    expect(screen.getByRole("combobox", { name: "Mode" })).toBeDisabled();
  });

  it("disables sending with the given reason", () => {
    open({ disabledReason: "The log is full: resume the session." });

    expect(screen.getByRole("textbox")).toHaveAttribute(
      "placeholder",
      "The log is full: resume the session.",
    );
  });

  it("refuses a message over the byte limit", async () => {
    const { box } = open({ maxBytes: 1024 });

    await userEvent.click(box);
    await userEvent.paste("é".repeat(600));

    expect(box).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Too long: 2 KiB of 1 KiB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("keeps the text and shows the problem when sending fails", async () => {
    const onSend = vi.fn(() =>
      Promise.reject(new ApiProblem({ status: 409, title: "Busy", detail: "Wait for the turn" })),
    );
    const { box } = open({ onSend });

    await userEvent.type(box, "hello{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Busy: Wait for the turn");
    expect(box).toHaveValue("hello");
  });

  it("shows a generic problem when a setting cannot be posted", async () => {
    open({ onSettings: vi.fn(() => Promise.reject(new Error("network"))) });

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Mode" }), "acceptEdits");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not change the mode. Try again.",
    );
  });

  it("has no serious violation (composer a11y)", async () => {
    const { container } = open({ status: "running" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
