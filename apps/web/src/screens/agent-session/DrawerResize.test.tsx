import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import {
  DRAWER_MIN,
  DRAWER_WIDTH_KEY,
  LIST_MIN,
  LIST_WIDTH_KEY,
  drawerMax,
  listMax,
  useDrawerWidth,
  useListWidth,
} from "./DrawerResize";

function Drawer() {
  const drawer = useDrawerWidth();
  return (
    <div className="as-page">
      <aside data-testid="drawer" style={drawer.style}>
        <div {...drawer.handle} />
        <button type="button" onClick={drawer.toggleWide}>
          {drawer.wide ? "Narrow" : "Widen"}
        </button>
      </aside>
    </div>
  );
}

afterEach(() => {
  window.localStorage.clear();
});

describe("useDrawerWidth (drawer)", () => {
  it("keeps the chat's minimum beside the widest drawer (AC-265.12)", () => {
    expect(drawerMax(1200)).toBe(920);
    expect(drawerMax(400)).toBe(DRAWER_MIN);
  });

  it("starts at the page's default, then resizes from the keyboard and keeps the width (AC-265.12)", async () => {
    window.localStorage.setItem(DRAWER_WIDTH_KEY, "500");
    render(<Drawer />);
    const handle = screen.getByRole("separator", { name: "Resize the panel" });
    expect(handle).toHaveAttribute("aria-valuenow", "500");

    handle.focus();
    await userEvent.keyboard("{Home}");

    expect(screen.getByTestId("drawer").style.getPropertyValue("--as-panel-w")).toBe("");
    expect(window.localStorage.getItem(DRAWER_WIDTH_KEY)).toBeNull();
  });

  it("widens to the whole page and back (AC-265.12)", async () => {
    window.localStorage.setItem(DRAWER_WIDTH_KEY, "480");
    render(<Drawer />);

    await userEvent.click(screen.getByRole("button", { name: "Widen" }));
    expect(screen.getByTestId("drawer").style.getPropertyValue("--as-panel-w")).toBe("100000px");
    await userEvent.click(screen.getByRole("button", { name: "Narrow" }));
    expect(screen.getByTestId("drawer").style.getPropertyValue("--as-panel-w")).toBe("480px");
  });
});

function Split({ body }: { body: number }) {
  const list = useListWidth(body);
  return (
    <div data-testid="body" style={list.style}>
      <div {...list.handle} />
    </div>
  );
}

describe("useListWidth (the file list beside the open file)", () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it("keeps the open file at least 360px and the list at most 60% of the drawer", () => {
    expect(listMax(1000)).toBe(600);
    expect(listMax(800)).toBe(440);
    expect(listMax(300)).toBe(LIST_MIN);
  });

  it("widens with →, narrows with ←, resets with Home, and keeps the width", async () => {
    render(<Split body={1000} />);
    const handle = screen.getByRole("separator", { name: "Resize the file list" });
    expect(handle).toHaveAttribute("aria-valuenow", "280");
    expect(handle).toHaveAttribute("aria-valuemax", "600");

    handle.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(handle).toHaveAttribute("aria-valuenow", "320");
    expect(window.localStorage.getItem(LIST_WIDTH_KEY)).toBe("320");
    expect(screen.getByTestId("body").style.getPropertyValue("--as-files-list-w")).toBe("320px");

    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(handle).toHaveAttribute("aria-valuenow", "240");

    await userEvent.keyboard("{Home}");
    expect(handle).toHaveAttribute("aria-valuenow", "280");
    expect(window.localStorage.getItem(LIST_WIDTH_KEY)).toBeNull();
  });

  it("gives the open file its room back when the drawer narrows", () => {
    window.localStorage.setItem(LIST_WIDTH_KEY, "560");
    render(<Split body={760} />);
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "400");
  });
});
