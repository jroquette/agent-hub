import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { Composer, type ComposerProps } from "./Composer";
import { aCatalogItem } from "../../testing/builders";
import { hubOptions, matchCommands, slashOptions, slashToken, type SlashOption } from "./SlashMenu";

const option = (command: string, hub = false): SlashOption => ({
  command,
  hub,
  description: null,
});
const COMMANDS = ["/compact", "/review", "/feature", "/refactor"].map((name) => option(name));

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
    .map((item) => item.querySelector(".as-slash-command")?.textContent);
const active = (box: HTMLElement) => {
  const id = box.getAttribute("aria-activedescendant");
  return id ? document.getElementById(id) : null;
};

describe("matchCommands", () => {
  it("keeps the names holding the query, those starting with it first, ignoring case", () => {
    const commands = (query: string) => matchCommands(COMMANDS, query).map((o) => o.command);
    expect(commands("RE")).toEqual(["/review", "/refactor", "/feature"]);
    expect(matchCommands(COMMANDS, "")).toEqual(COMMANDS);
  });
});

describe("slashToken", () => {
  it("finds the /word at the caret when it starts the text or follows a space", () => {
    expect(slashToken("/fe", 3)).toEqual({ start: 0, end: 3, query: "fe" });
    expect(slashToken("run /fe now", 7)).toEqual({ start: 4, end: 7, query: "fe" });
    expect(slashToken("run /feature", 6)).toEqual({ start: 4, end: 12, query: "f" });
    expect(slashToken("a/fe", 4)).toBeNull();
    expect(slashToken("/fe x", 5)).toBeNull();
  });
});

describe("slash options", () => {
  it("offers the hub's callable skills as /name and its agents as /agent-name", () => {
    const items = [
      aCatalogItem({ kind: "skill", name: "fix", mode: "both", description: "Fix a bug" }),
      aCatalogItem({ kind: "skill", name: "recall", mode: "model-only" }),
      aCatalogItem({ kind: "agent", name: "researcher", mode: null }),
      aCatalogItem({ kind: "hook", name: "guard", mode: null }),
    ];

    expect(hubOptions("demo", items).map((o) => [o.command, o.description, o.href])).toEqual([
      ["/fix", "Fix a bug", `/projects/demo/skills/skill/${items[0]?.source ?? ""}/fix`],
      [
        "/agent-researcher",
        items[2]?.description ?? null,
        `/projects/demo/skills/agent/${items[2]?.source ?? ""}/researcher`,
      ],
    ]);
  });

  it("lists the hub first, then the session's commands the hub does not offer", () => {
    const hub = [option("/fix", true), option("/agent-researcher", true)];
    const session = [
      "/compact",
      "/hub-workflow:fix",
      "/agent-hub-workflow:researcher",
      "/vercel:deploy",
    ];

    expect(slashOptions(hub, session).map((o) => [o.command, o.hub])).toEqual([
      ["/fix", true],
      ["/agent-researcher", true],
      ["/compact", false],
      ["/vercel:deploy", false],
    ]);
  });
});

describe("SlashMenu (slash-menu)", () => {
  it("opens on / at the start of the composer and lists the commands", async () => {
    const { box } = open();
    expect(menu()).toBeNull();

    await userEvent.type(box, "/");

    expect(names()).toEqual(COMMANDS.map((o) => o.command));
    expect(box).toHaveAttribute("aria-controls", menu()?.id);
    expect(box).toHaveAttribute("aria-autocomplete", "list");
    expect(active(box)).toHaveTextContent("/compact");
    expect(active(box)).toHaveAttribute("aria-selected", "true");
  });

  it("opens for a matching /word later in the text and inserts it in place", async () => {
    const { box } = open();

    await userEvent.type(box, "run /re");
    expect(names()).toEqual(["/review", "/refactor", "/feature"]);
    await userEvent.keyboard("{Enter}");

    expect(box).toHaveValue("run /review ");
  });

  it("stays closed for a later /word that matches nothing, so Enter sends", async () => {
    const { box, props } = open();

    await userEvent.type(box, "see /tmp/x{Enter}");

    expect(menu()).toBeNull();
    expect(props.onSend).toHaveBeenCalledWith("see /tmp/x", []);
  });

  it("labels what the hub brings", async () => {
    const { box } = open({ commands: [option("/fix", true), option("/compact")] });

    await userEvent.type(box, "/");

    expect(screen.getByRole("option", { name: "/fix, from the hub" })).toHaveTextContent("hub/fix");
    expect(screen.getByRole("option", { name: "/compact" })).not.toHaveTextContent("hub");
  });

  it("puts the menu's scroll in the tab order, keeping the composer's Tab for picking", async () => {
    const { box, container } = open({ commands: [option("/fix", true), option("/compact")] });
    await userEvent.type(box, "/");

    // axe scrollable-region-focusable: the list scrolls once the hub's items fill it.
    expect(container.querySelector(".as-slash")).toHaveAttribute("tabindex", "0");
    await userEvent.keyboard("{Tab}");
    expect(box).toHaveValue("/fix ");
    expect(box).toHaveFocus();
  });

  it("opens a hub item's page in a new tab without picking it", async () => {
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const fix = { ...option("/fix", true), href: "/projects/demo/skills/skill/hub-workflow/fix" };
    const { box, container } = open({ commands: [fix, option("/compact")] });
    await userEvent.type(box, "/");

    expect(container.querySelectorAll(".as-slash-open")).toHaveLength(1);
    const button = container.querySelector<HTMLElement>(".as-slash-open");
    if (!button) throw new Error("no open button");
    await userEvent.click(button);
    expect(opened).toHaveBeenLastCalledWith(fix.href, "_blank", "noopener");
    expect(box).toHaveValue("/");

    await userEvent.keyboard("{Control>}{Enter}{/Control}");
    expect(opened).toHaveBeenCalledTimes(2);
    expect(box).toHaveValue("/");
    opened.mockRestore();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("closes after a space", async () => {
    const { box } = open();

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
    expect(props.onSend).toHaveBeenCalledWith("/compact", []);
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
