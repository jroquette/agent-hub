import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ModelMenu, modelLabel, type ModelMenuProps } from "./ModelMenu";

const MODELS = ["default", "opus", "fable", "sonnet", "haiku"];

function open(overrides: Partial<ModelMenuProps> = {}) {
  const props: ModelMenuProps = {
    model: "sonnet",
    models: MODELS,
    effort: null,
    onModel: vi.fn(),
    onEffort: vi.fn(),
    ...overrides,
  };
  const view = render(<ModelMenu {...props} />);
  return { ...view, props, pill: screen.getByRole("button", { name: /^Model and effort/ }) };
}

async function openEfforts(pill: HTMLElement) {
  await userEvent.click(pill);
  await userEvent.click(screen.getByRole("menuitem", { name: /Effort/ }));
  return screen.getByRole("menu", { name: "Effort" });
}

/** The window, the pill and the model list where a test puts them; each menu is 240 px wide. */
function place({ width, list }: { width: number; list: { left: number; right: number } }) {
  vi.spyOn(window, "innerWidth", "get").mockReturnValue(width);
  vi.spyOn(window, "innerHeight", "get").mockReturnValue(800);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(240);
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    if (this.classList.contains("as-model-trigger")) return new DOMRect(100, 700, 100, 30);
    if (
      this.getAttribute("aria-label") === "Model and effort" &&
      this.getAttribute("role") === "menu"
    ) {
      return new DOMRect(list.left, 400, list.right - list.left, 294);
    }
    return new DOMRect(0, 0, 0, 0);
  });
}

describe("modelLabel (AC-681.4, AC-681.10)", () => {
  it.each([
    ["claude-opus-5-5[1m]", "Opus 5.5 (1M)"],
    ["claude-sonnet-4-5-20250929", "Sonnet 4.5"],
    ["claude-haiku-4", "Haiku 4"],
    ["fable", "Fable"],
    ["default", "Default"],
    ["custom-model", "custom-model"],
  ])("reads %s as %s", (model, label) => {
    expect(modelLabel(model)).toBe(label);
  });
});

describe("ModelMenu (AC-681.4)", () => {
  it("shows the model and the effort on the pill", () => {
    const { pill } = open({ model: "opus", effort: "xhigh" });

    expect(pill).toHaveAccessibleName("Model and effort: Opus, Extra");
    expect(pill).toHaveTextContent("Opus");
    expect(pill).toHaveTextContent("Extra");
    expect(pill).toHaveAttribute("aria-expanded", "false");
  });

  it("lists every model, Fable included, with the current one checked and focused", async () => {
    const { pill } = open({ model: "sonnet" });

    await userEvent.click(pill);

    const menu = screen.getByRole("menu", { name: "Model and effort" });
    expect(
      within(menu)
        .getAllByRole("menuitemradio")
        .map((row) => row.textContent),
    ).toEqual(["Default", "Opus", "Fable", "Sonnet", "Haiku"]);
    expect(within(menu).getByRole("menuitemradio", { name: "Sonnet" })).toBeChecked();
    expect(within(menu).getByRole("menuitemradio", { name: "Sonnet" })).toHaveFocus();
    expect(pill).toHaveAttribute("aria-expanded", "true");
  });

  it("calls onModel and closes when another model is picked", async () => {
    const { pill, props } = open();
    await userEvent.click(pill);

    await userEvent.click(screen.getByRole("menuitemradio", { name: "Fable" }));

    expect(props.onModel).toHaveBeenCalledWith("fable");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(pill).toHaveFocus();
  });

  it("closes again when the pill is pressed while open", async () => {
    const { pill } = open();
    await userEvent.click(pill);

    await userEvent.click(pill);

    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("opens the effort levels with their tags in a side menu, the current one checked", async () => {
    const { pill } = open({ effort: "medium" });

    const efforts = await openEfforts(pill);

    expect(
      within(efforts)
        .getAllByRole("menuitemradio")
        .map((row) => row.textContent),
    ).toEqual(["Low", "MediumRecommended", "High", "Extra", "Max3.5× or more usage"]);
    expect(within(efforts).getByRole("menuitemradio", { name: /^Medium/ })).toBeChecked();
    expect(screen.getByRole("menuitem", { name: /Effort/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("names the default effort on the Effort row when none is set", async () => {
    const { pill } = open();
    await userEvent.click(pill);

    expect(screen.getByRole("menuitem", { name: /Effort/ })).toHaveTextContent("Default");
  });

  it("calls onEffort and closes both menus when a level is picked", async () => {
    const { pill, props } = open({ effort: "low" });
    const efforts = await openEfforts(pill);

    await userEvent.click(within(efforts).getByRole("menuitemradio", { name: /^High/ }));

    expect(props.onEffort).toHaveBeenCalledWith("high");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(pill).toHaveFocus();
  });

  it("calls nothing when the current model or effort is picked again", async () => {
    const { pill, props } = open({ effort: "low" });
    await userEvent.click(pill);
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Sonnet" }));
    const efforts = await openEfforts(pill);
    await userEvent.click(within(efforts).getByRole("menuitemradio", { name: /^Low/ }));

    expect(props.onModel).not.toHaveBeenCalled();
    expect(props.onEffort).not.toHaveBeenCalled();
  });

  it("opens the side menu on hover and closes it on a model row's hover", async () => {
    const { pill } = open();
    await userEvent.click(pill);

    await userEvent.hover(screen.getByRole("menuitem", { name: /Effort/ }));
    expect(screen.getByRole("menu", { name: "Effort" })).toBeInTheDocument();
    await userEvent.hover(screen.getByRole("menuitemradio", { name: "Opus" }));

    expect(screen.queryByRole("menu", { name: "Effort" })).toBeNull();
  });

  it("moves focus with the arrow keys, wrapping at both ends", async () => {
    const { pill } = open({ model: "default" });
    await userEvent.click(pill);
    expect(screen.getByRole("menuitemradio", { name: "Default" })).toHaveFocus();

    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemradio", { name: "Opus" })).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: /Effort/ })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");

    expect(screen.getByRole("menuitemradio", { name: "Default" })).toHaveFocus();
  });

  it("opens the side menu on ArrowRight with focus on the current level", async () => {
    const { pill } = open({ effort: "medium" });
    await userEvent.click(pill);
    screen.getByRole("menuitem", { name: /Effort/ }).focus();

    await userEvent.keyboard("{ArrowRight}");

    expect(screen.getByRole("menuitemradio", { name: /^Medium/ })).toHaveFocus();
  });

  it("moves focus in the side menu and goes back to the Effort row on ArrowLeft", async () => {
    const { pill } = open({ effort: "max" });
    await userEvent.click(pill);
    screen.getByRole("menuitem", { name: /Effort/ }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("menuitemradio", { name: /^Max/ })).toHaveFocus();

    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemradio", { name: /^Low/ })).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitemradio", { name: /^Max/ })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");

    expect(screen.queryByRole("menu", { name: "Effort" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: /Effort/ })).toHaveFocus();
  });

  it.each(["{Escape}", "{Tab}"])("closes and gives focus back to the pill on %s", async (key) => {
    const { pill } = open();
    await userEvent.click(pill);

    await userEvent.keyboard(key);

    expect(screen.queryByRole("menu")).toBeNull();
    expect(pill).toHaveFocus();
  });

  it("closes both menus and gives focus back to the pill on Tab in the side menu", async () => {
    const { pill } = open();
    await userEvent.click(pill);
    screen.getByRole("menuitem", { name: /Effort/ }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("menuitemradio", { name: /^Low/ })).toHaveFocus();

    await userEvent.keyboard("{Tab}");

    expect(screen.queryByRole("menu")).toBeNull();
    expect(pill).toHaveFocus();
  });

  it("closes on a press outside it, not on a press inside it", async () => {
    const { pill } = open();
    await userEvent.click(pill);

    fireEvent.mouseDown(screen.getByRole("menu", { name: "Model and effort" }));
    expect(screen.getByRole("menu", { name: "Model and effort" })).toBeInTheDocument();
    fireEvent.mouseDown(document.body);

    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes when the window is resized", async () => {
    const { pill } = open();
    await openEfforts(pill);

    fireEvent(window, new Event("resize"));

    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("cannot open while disabled", () => {
    const { pill } = open({ disabled: true });

    expect(pill).toBeDisabled();
  });

  it("keeps a model no row offers as a row of its own, checked", async () => {
    const { pill } = open({ model: "custom-model" });
    await userEvent.click(pill);

    expect(screen.getByRole("menuitemradio", { name: "custom-model" })).toBeChecked();
  });
});

describe("ModelMenu (extra row, AC-681.5)", () => {
  it("offers the extra row after the models and calls its onPick when picked", async () => {
    const onPick = vi.fn();
    const { pill } = open({
      model: "default",
      extra: { label: "Other model id…", checked: false, onPick },
    });
    await userEvent.click(pill);
    const rows = screen.getAllByRole("menuitemradio");
    expect(rows.at(-1)).toHaveTextContent("Other model id…");
    expect(screen.getByRole("menuitemradio", { name: "Default" })).toBeChecked();

    await userEvent.click(screen.getByRole("menuitemradio", { name: "Other model id…" }));

    expect(onPick).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("names the extra row on the pill and checks only it when it is the choice", async () => {
    const { pill } = open({
      model: "default",
      extra: { label: "Other model id…", checked: true, onPick: vi.fn() },
    });

    expect(pill).toHaveTextContent("Other model id…");
    await userEvent.click(pill);

    expect(screen.getByRole("menuitemradio", { name: "Other model id…" })).toBeChecked();
    expect(screen.getByRole("menuitemradio", { name: "Default" })).not.toBeChecked();
  });
});

describe("ModelMenu (Ultracode, AC-681.9)", () => {
  it("offers no Ultracode switch without onUltracode", async () => {
    const { pill } = open();

    await openEfforts(pill);

    expect(screen.queryByRole("menuitemcheckbox", { name: "Ultracode" })).toBeNull();
  });

  it("calls onUltracode from the switch and keeps the side menu open", async () => {
    const onUltracode = vi.fn();
    const { pill } = open({ onUltracode });
    await openEfforts(pill);
    expect(screen.getByRole("menuitemcheckbox", { name: "Ultracode" })).not.toBeChecked();

    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Ultracode" }));

    expect(onUltracode).toHaveBeenCalledWith(true);
    expect(screen.getByRole("menu", { name: "Effort" })).toBeInTheDocument();
  });

  it("shows Ultracode on the pill and the Effort row when it is on", async () => {
    const { pill } = open({ effort: "high", ultracode: true, onUltracode: vi.fn() });

    expect(pill).toHaveAccessibleName("Model and effort: Sonnet, High, Ultracode");
    await userEvent.click(pill);

    expect(screen.getByRole("menuitem", { name: /Effort/ })).toHaveTextContent("High · Ultracode");
  });
});

describe("ModelMenu (placement, AC-681.6)", () => {
  it("opens both menus in a portal on the body, outside the pill's parents", async () => {
    render(
      <div role="dialog" aria-label="Host" style={{ overflow: "auto" }}>
        <ModelMenu
          model="sonnet"
          models={MODELS}
          effort={null}
          onModel={vi.fn()}
          onEffort={vi.fn()}
        />
      </div>,
    );
    const dialog = screen.getByRole("dialog", { name: "Host" });

    await openEfforts(within(dialog).getByRole("button", { name: /^Model and effort/ }));

    for (const name of ["Model and effort", "Effort"]) {
      const menu = screen.getByRole("menu", { name });
      expect(dialog).not.toContainElement(menu);
      expect(menu.parentElement?.parentElement).toBe(document.body);
    }
  });

  it("opens the list above the pill, from its left edge", async () => {
    place({ width: 1000, list: { left: 100, right: 340 } });
    const { pill } = open();

    await userEvent.click(pill);

    const menu = screen.getByRole("menu", { name: "Model and effort" });
    expect(menu.style.left).toBe("100px");
    expect(menu.style.bottom).toBe("106px");
  });

  it("keeps the list inside the window when the pill is near its right edge", async () => {
    place({ width: 300, list: { left: 52, right: 292 } });
    const { pill } = open();

    await userEvent.click(pill);

    expect(screen.getByRole("menu", { name: "Model and effort" }).style.left).toBe("52px");
  });

  it("puts the side menu right of the list when it fits", async () => {
    place({ width: 1000, list: { left: 100, right: 340 } });
    const { pill } = open();

    const efforts = await openEfforts(pill);

    expect(efforts.style.left).toBe("346px");
    expect(efforts.style.bottom).toBe("106px");
  });

  it("puts the side menu left of the list when the right has no room", async () => {
    place({ width: 1000, list: { left: 700, right: 940 } });
    const { pill } = open();

    const efforts = await openEfforts(pill);

    expect(efforts.style.left).toBe("454px");
  });

  it("puts the side menu over the list when neither side has room", async () => {
    place({ width: 400, list: { left: 100, right: 340 } });
    const { pill } = open();

    const efforts = await openEfforts(pill);

    expect(efforts.style.left).toBe("100px");
  });
});
