import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { servedCheckout } from "../../lib/devCheckout";
import { seriousViolations } from "../../testing/axe";
import { Composer, DEFAULT_MESSAGE_MAX_BYTES, type ComposerProps } from "./Composer";

vi.mock("../../lib/pastedImage", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/pastedImage")>();
  // The canvas is not in jsdom: an image "converts" to a data URL naming its file.
  return {
    ...actual,
    imageToPng: vi.fn((file: File) => Promise.resolve(`data:image/png;base64,${file.name}`)),
  };
});

vi.mock("../../lib/devCheckout", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/devCheckout")>();
  return { ...actual, servedCheckout: vi.fn(() => null) };
});

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

    expect(props.onSend).toHaveBeenCalledWith("Run the tests", []);
    expect(box).toHaveValue("");
  });

  it("inserts a newline on Shift+Enter without sending", async () => {
    const { box, props } = open();

    await userEvent.type(box, "one{Shift>}{Enter}{/Shift}two");

    expect(box).toHaveValue("one\ntwo");
    expect(props.onSend).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(props.onSend).toHaveBeenCalledWith("one\ntwo", []);
  });

  it("sends on Alt+Enter, but leaves Ctrl/Cmd+Alt+Enter to the chat's allow chord", async () => {
    const { box, props } = open();
    await userEvent.type(box, "Run it");

    expect(fireEvent.keyDown(box, { key: "Enter", ctrlKey: true, altKey: true })).toBe(true);
    expect(fireEvent.keyDown(box, { key: "Enter", metaKey: true, altKey: true })).toBe(true);
    await act(() => Promise.resolve());
    expect(props.onSend).not.toHaveBeenCalled();

    expect(fireEvent.keyDown(box, { key: "Enter", altKey: true })).toBe(false);
    await waitFor(() => {
      expect(props.onSend).toHaveBeenCalledWith("Run it", []);
    });
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
    ["waiting_permission", true],
    ["ended", false],
  ] as const)(
    "enables stop while running or waiting when the status is %s",
    async (status, enabled) => {
      const { props } = open({ status });
      const stop = screen.getByRole("button", { name: "Stop" });

      if (enabled) {
        expect(stop).toBeEnabled();
        await userEvent.click(stop);
        expect(props.onInterrupt).toHaveBeenCalledTimes(1);
      } else {
        expect(stop).toBeDisabled();
      }
    },
  );

  it("offers Auto too in the dev app of make playground", () => {
    vi.mocked(servedCheckout).mockReturnValue("/srv/demo/agent-hub");
    open();

    expect(
      within(screen.getByRole("combobox", { name: "Mode" }))
        .getAllByRole("option")
        .map((option) => option.getAttribute("value")),
    ).toEqual(["default", "acceptEdits", "plan", "auto"]);
  });

  it("offers only the three web modes and posts a mode change", async () => {
    vi.mocked(servedCheckout).mockReturnValue(null);
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

  it("shows a session in Auto as Auto in the built app, without offering it", () => {
    vi.mocked(servedCheckout).mockReturnValue(null);
    open({ mode: "auto" });
    const mode = screen.getByRole("combobox", { name: "Mode" });

    expect(mode).toHaveValue("auto");
    expect(within(mode).getByRole("option", { name: "Auto" })).toBeDisabled();
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
      "This session has ended. Start a new session to continue.",
    );
    expect(screen.getByRole("combobox", { name: "Mode" })).toBeDisabled();
  });

  it("sends to an ended session a message resumes", async () => {
    const { props } = open({ status: "ended", resumable: true });
    const box = screen.getByRole("textbox");

    expect(box).toHaveAttribute(
      "placeholder",
      "This session has ended. Send a message to resume it.",
    );
    await userEvent.type(box, "Go on.{Enter}");

    expect(props.onSend).toHaveBeenCalledWith("Go on.", []);
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

  it("takes a long text up to 1 MiB by default (AC-266.9)", () => {
    const { box } = open();

    fireEvent.change(box, { target: { value: "x".repeat(200 * 1024) } });

    expect(box).not.toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/Too long/)).not.toBeInTheDocument();
    expect(DEFAULT_MESSAGE_MAX_BYTES).toBe(1024 * 1024);
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

  it.each([
    [120, "120px", "hidden"],
    [400, "400px", "hidden"],
    [401, "400px", "auto"],
  ])("grows to fit %i px of text, up to 40vh, then scrolls", async (content, height, overflow) => {
    vi.stubGlobal("innerHeight", 1000);
    const { box } = open();
    // Only the composer's own box reports the content height.
    Object.defineProperty(box, "scrollHeight", { configurable: true, get: () => content });

    await userEvent.type(box, "a");

    expect(box.style.height).toBe(height);
    expect(box.style.overflowY).toBe(overflow);
    vi.unstubAllGlobals();
  });

  it("measures the content height once per change", async () => {
    vi.stubGlobal("innerHeight", 1000);
    const { box } = open();
    const measure = vi.fn(() => 120);
    Object.defineProperty(box, "scrollHeight", { configurable: true, get: measure });

    await userEvent.type(box, "a");

    expect(measure).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("fits the box again when the window shrinks, and scrolls past the new cap", async () => {
    vi.stubGlobal("innerHeight", 2000);
    const { box } = open();
    Object.defineProperty(box, "scrollHeight", { configurable: true, get: () => 500 });
    await userEvent.type(box, "a");
    expect([box.style.height, box.style.overflowY]).toEqual(["500px", "hidden"]);

    vi.stubGlobal("innerHeight", 1000);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });

    expect([box.style.height, box.style.overflowY]).toEqual(["400px", "auto"]);
    vi.unstubAllGlobals();
  });

  it("restores the session's draft and clears it once the send is accepted", async () => {
    window.localStorage.setItem("ah.chat.draft.s-1", JSON.stringify("Saved earlier"));
    const { box, props } = open({ draftId: "s-1" });

    expect(box).toHaveValue("Saved earlier");
    await userEvent.type(box, "{Enter}");

    expect(props.onSend).toHaveBeenCalledWith("Saved earlier", []);
    expect(box).toHaveValue("");
    expect(window.localStorage.getItem("ah.chat.draft.s-1")).toBeNull();
  });

  it("keeps the saved draft when the send fails", async () => {
    window.localStorage.setItem("ah.chat.draft.s-1", JSON.stringify("Try me"));
    const { box } = open({ draftId: "s-1", onSend: vi.fn(() => Promise.reject(new Error("x"))) });

    await userEvent.type(box, "{Enter}");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(box).toHaveValue("Try me");
    expect(window.localStorage.getItem("ah.chat.draft.s-1")).toBe(JSON.stringify("Try me"));
    window.localStorage.clear();
  });

  it.each([
    [true, true],
    [false, false],
  ])("takes focus on open without scrolling when asked (%s)", (focusOnOpen, focused) => {
    const focus = vi.spyOn(HTMLTextAreaElement.prototype, "focus");
    const { box } = open({ focusOnOpen });

    expect(box === document.activeElement).toBe(focused);
    if (focused) expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    focus.mockRestore();
  });

  it("keeps focus in the box after Send, without scrolling", async () => {
    const { box } = open();
    await userEvent.type(box, "Go");
    const focus = vi.spyOn(HTMLTextAreaElement.prototype, "focus");

    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(box).toHaveValue("");
    expect(box).toHaveFocus();
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    focus.mockRestore();
  });

  /** Presses Enter and lets a send that started reach `onSend`. */
  const pressEnter = async (box: HTMLElement, init: object = {}) => {
    await act(async () => {
      fireEvent.keyDown(box, { key: "Enter", ...init });
      await Promise.resolve();
    });
  };

  it.each([
    ["the key event says so", true],
    ["only the composition events say so", false],
  ])("never sends on Enter while an IME composes (%s)", async (_, isComposing) => {
    const { box, props } = open();
    fireEvent.change(box, { target: { value: "にほん" } });

    if (!isComposing) fireEvent.compositionStart(box);

    await pressEnter(box, { isComposing });

    expect(props.onSend).not.toHaveBeenCalled();
    fireEvent.compositionEnd(box);
  });

  it.each([
    [499, false],
    [500, true],
  ])("sends on Enter %i ms after the composition ends: %s", async (after, sends) => {
    const now = vi.spyOn(performance, "now").mockReturnValue(1000);
    const { box, props } = open();
    fireEvent.change(box, { target: { value: "日本" } });
    fireEvent.compositionStart(box);
    fireEvent.compositionEnd(box);

    now.mockReturnValue(1000 + after);
    await pressEnter(box);

    expect(props.onSend).toHaveBeenCalledTimes(sends ? 1 : 0);
    now.mockRestore();
  });

  it("keeps Enter as a new line under a coarse pointer; Send sends", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(pointer: coarse)" }));
    const { box, props } = open();
    await userEvent.type(box, "one{Enter}two");

    expect(box).toHaveValue("one\ntwo");
    expect(props.onSend).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(props.onSend).toHaveBeenCalledWith("one\ntwo", []);
    vi.unstubAllGlobals();
  });

  it("has no serious violation (composer a11y)", async () => {
    const { container } = open({ status: "running" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("Composer (stop)", () => {
  it("interrupts once on Esc in an empty composer while the interrupt is in flight", async () => {
    let done: (value?: unknown) => void = () => undefined;
    const onInterrupt = vi.fn(
      () =>
        new Promise((resolve) => {
          done = resolve;
        }),
    );
    const { box } = open({ status: "waiting_permission", onInterrupt });

    await userEvent.type(box, "{Escape}{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Stopping…" }));
    expect(onInterrupt).toHaveBeenCalledTimes(1);

    await act(async () => {
      done();
      await Promise.resolve();
    });
    await userEvent.type(box, "{Escape}");
    expect(onInterrupt).toHaveBeenCalledTimes(2);
  });

  it("shows a pending interrupt on a disabled Stopping… button until it answers", async () => {
    let done: (value?: unknown) => void = () => undefined;
    const onInterrupt = vi.fn(
      () =>
        new Promise((resolve) => {
          done = resolve;
        }),
    );
    open({ status: "running", onInterrupt });

    await userEvent.click(screen.getByRole("button", { name: "Stop" }));

    const pending = screen.getByRole("button", { name: "Stopping…" });
    expect(pending).toHaveAttribute("aria-disabled", "true");
    // Not `disabled`: a browser drops keyboard focus from a disabled button (jsdom does not).
    expect(pending).not.toBeDisabled();
    await userEvent.click(pending);
    expect(onInterrupt).toHaveBeenCalledTimes(1);
    await act(async () => {
      done();
      await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Stop" })).not.toHaveAttribute("aria-disabled");
  });

  it.each([
    ["the composer holds text", "running", "Keep going"],
    ["no turn runs", "idle", ""],
  ] as const)("leaves Esc alone when %s", async (_, status, text) => {
    const { box, props } = open({ status });

    await userEvent.type(box, `${text}{Escape}`);

    expect(props.onInterrupt).not.toHaveBeenCalled();
    expect(box).toHaveValue(text);
  });
});

describe("Composer (images)", () => {
  const image = (name: string) => new File(["x"], name, { type: "image/png" });

  it("adds a pasted image above the text and sends it with the message (AC-266.6)", async () => {
    const { box, props } = open({ acceptsImages: true });

    fireEvent.paste(box, { clipboardData: { files: [image("shot.png")] } });

    const strip = await screen.findByRole("list", { name: "Images in this message" });
    expect(within(strip).getByRole("img", { name: "Image 1" })).toHaveAttribute(
      "src",
      "data:image/png;base64,shot.png",
    );
    expect(screen.getByText("Add a message to send with the image")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    await userEvent.type(box, "What is wrong here?{Enter}");

    expect(props.onSend).toHaveBeenCalledWith("What is wrong here?", [
      "data:image/png;base64,shot.png",
    ]);
    await waitFor(() => {
      expect(screen.queryByRole("list", { name: "Images in this message" })).toBeNull();
    });
  });

  it("takes dropped images, removes one, and refuses past ten (AC-266.6)", async () => {
    const { box, props } = open({ acceptsImages: true });
    const form = screen.getByRole("form", { name: "Message composer" });

    fireEvent.drop(form, {
      dataTransfer: {
        files: "abcdefghijk".split("").map((n) => image(`${n}.png`)),
        types: ["Files"],
      },
    });

    const strip = await screen.findByRole("list", { name: "Images in this message" });
    await waitFor(() => {
      expect(within(strip).getAllByRole("img")).toHaveLength(10);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("A message takes up to 10 images.");
    expect(screen.getByRole("button", { name: "Add an image" })).toBeDisabled();

    await userEvent.click(within(strip).getByRole("button", { name: "Remove image 2" }));
    await userEvent.type(box, "Compare{Enter}");

    expect(props.onSend).toHaveBeenCalledWith(
      "Compare",
      "acdefghij".split("").map((n) => `data:image/png;base64,${n}.png`),
    );
  });

  it("pastes text as usual and takes no image where images are not accepted", () => {
    const { box } = open();

    fireEvent.paste(box, { clipboardData: { files: [image("shot.png")] } });

    expect(screen.queryByRole("list", { name: "Images in this message" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add an image" })).toBeNull();
  });
});
