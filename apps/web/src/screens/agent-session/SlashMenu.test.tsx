import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { Composer, type ComposerProps } from "./Composer";
import { matchCommands } from "./SlashMenu";

const COMMANDS = ["/compact", "/review", "/feature", "/refactor"];

function open(overrides: Partial<ComposerProps> = {}) {
  const props: ComposerProps = {
    status: "idle",
    mode: "default",
    model: "sonnet",
    models: ["sonnet"],
    commands: COMMANDS,
    onSend: vi.fn(() => Promise.resolve()),
    onInterrupt: vi.fn(() => Promise.resolve()),
    onSettings: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
  const view = render(<Composer {...props} />);
  return { ...view, props, box: screen.getByRole("textbox", { name: "Message Claude" }) };
}

const menu = () => screen.queryByRole("listbox", { name: "Commands" });
const names = () =>
  within(screen.getByRole("listbox", { name: "Commands" }))
    .queryAllByRole("option")
    .map((option) => option.textContent);
const active = (box: HTMLElement) => {
  const id = box.getAttribute("aria-activedescendant");
  return id ? document.getElementById(id) : null;
};

describe("matchCommands", () => {
  it("keeps the names holding the query, those starting with it first, ignoring case", () => {
    expect(matchCommands(COMMANDS, "RE")).toEqual(["/review", "/refactor", "/feature"]);
    expect(matchCommands(COMMANDS, "")).toEqual(COMMANDS);
  });
});

describe("SlashMenu (slash-menu)", () => {
  it("opens on / at the start of the composer and lists the commands", async () => {
    const { box } = open();
    expect(menu()).toBeNull();

    await userEvent.type(box, "/");

    expect(names()).toEqual(COMMANDS);
    expect(box).toHaveAttribute("aria-controls", menu()?.id);
    expect(box).toHaveAttribute("aria-autocomplete", "list");
    expect(active(box)).toHaveTextContent("/compact");
    expect(active(box)).toHaveAttribute("aria-selected", "true");
  });

  it("stays closed for a / later in the text and closes after a space", async () => {
    const { box } = open();

    await userEvent.type(box, "run /re");
    expect(menu()).toBeNull();

    await userEvent.clear(box);
    await userEvent.type(box, "/re");
    expect(menu()).not.toBeNull();
    await userEvent.type(box, " ");
    expect(menu()).toBeNull();
    expect(box).not.toHaveAttribute("aria-activedescendant");
  });

  it("filters as you type", async () => {
    const { box } = open();

    await userEvent.type(box, "/fe");
    expect(names()).toEqual(["/feature"]);
    await userEvent.type(box, "{Backspace}{Backspace}re");
    expect(names()).toEqual(["/review", "/refactor", "/feature"]);
  });

  it("moves with the arrows, wrapping, and inserts on Enter without sending", async () => {
    const { box, props } = open();

    await userEvent.type(box, "/re");
    expect(active(box)).toHaveTextContent("/review");
    await userEvent.keyboard("{ArrowDown}");
    expect(active(box)).toHaveTextContent("/refactor");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(active(box)).toHaveTextContent("/review");
    await userEvent.keyboard("{ArrowUp}");
    expect(active(box)).toHaveTextContent("/feature");
    expect(screen.getByRole("option", { name: "/review" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    await userEvent.keyboard("{Enter}");

    expect(box).toHaveValue("/feature ");
    expect(menu()).toBeNull();
    expect(props.onSend).not.toHaveBeenCalled();
    expect(box).toHaveFocus();
  });

  it("inserts on Tab and keeps focus in the composer", async () => {
    const { box } = open();

    await userEvent.type(box, "/com{Tab}");

    expect(box).toHaveValue("/compact ");
    expect(box).toHaveFocus();
  });

  it("inserts the clicked command", async () => {
    const { box } = open();
    await userEvent.type(box, "/");

    await userEvent.click(screen.getByRole("option", { name: "/feature" }));

    expect(box).toHaveValue("/feature ");
    expect(box).toHaveFocus();
  });

  it("never sends on Enter while open, even with no command to insert", async () => {
    const { box, props, container } = open({ commands: [] });

    await userEvent.type(box, "/nothing{Enter}");

    expect(screen.getByText("No commands", { selector: "p" })).toBeVisible();
    expect(names()).toEqual([]);
    expect(box).toHaveValue("/nothing");
    expect(props.onSend).not.toHaveBeenCalled();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("closes on Esc without posting an interrupt, then Enter sends (AC-234.21)", async () => {
    const { box, props } = open({ status: "running" });

    await userEvent.type(box, "/compact");
    await userEvent.keyboard("{Escape}");

    expect(menu()).toBeNull();
    expect(props.onInterrupt).not.toHaveBeenCalled();
    expect(box).toHaveValue("/compact");
    await userEvent.keyboard("{Enter}");
    expect(props.onSend).toHaveBeenCalledWith("/compact");
  });

  it("announces the menu opening, its match count and No commands, once per change", async () => {
    const { box, container } = open();
    const live = container.querySelector<HTMLElement>("[aria-live=polite].ah-sr");
    if (!live) throw new Error("no live region");
    expect(live).toHaveAttribute("aria-atomic", "true");
    expect(live).toHaveTextContent(/^$/);

    await userEvent.type(box, "/");
    expect(live).toHaveTextContent(/^4 commands$/);
    await userEvent.type(box, "r");
    expect(live).toHaveTextContent(/^3 commands$/);

    const changes: MutationRecord[] = [];
    const watch = new MutationObserver((records) => changes.push(...records));
    watch.observe(live, { subtree: true, childList: true, characterData: true });
    await userEvent.type(box, "e{ArrowDown}");
    expect(changes.concat(watch.takeRecords())).toEqual([]);
    watch.disconnect();

    await userEvent.type(box, "v");
    expect(live).toHaveTextContent(/^1 command$/);
    await userEvent.type(box, "x");
    expect(live).toHaveTextContent(/^No commands$/);
    await userEvent.keyboard("{Escape}");
    expect(live).toHaveTextContent(/^$/);
  });

  it("has no serious axe violation while open", async () => {
    const { box, container } = open();
    await userEvent.type(box, "/");

    expect(await seriousViolations(container)).toEqual([]);
  });
});
