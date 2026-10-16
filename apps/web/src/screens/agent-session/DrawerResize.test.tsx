import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { DRAWER_MIN, DRAWER_WIDTH_KEY, drawerMax, useDrawerWidth } from "./DrawerResize";

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
  it("keeps the chat's minimum beside the widest drawer", () => {
    expect(drawerMax(1200)).toBe(920);
    expect(drawerMax(400)).toBe(DRAWER_MIN);
  });

  it("starts at the page's default, then resizes from the keyboard and keeps the width", async () => {
    window.localStorage.setItem(DRAWER_WIDTH_KEY, "500");
    render(<Drawer />);
    const handle = screen.getByRole("separator", { name: "Resize the panel" });
    expect(handle).toHaveAttribute("aria-valuenow", "500");

    handle.focus();
    await userEvent.keyboard("{Home}");

    expect(screen.getByTestId("drawer").style.getPropertyValue("--as-panel-w")).toBe("");
    expect(window.localStorage.getItem(DRAWER_WIDTH_KEY)).toBeNull();
  });

  it("widens to the whole page and back", async () => {
    window.localStorage.setItem(DRAWER_WIDTH_KEY, "480");
    render(<Drawer />);

    await userEvent.click(screen.getByRole("button", { name: "Widen" }));
    expect(screen.getByTestId("drawer").style.getPropertyValue("--as-panel-w")).toBe("100000px");
    await userEvent.click(screen.getByRole("button", { name: "Narrow" }));
    expect(screen.getByTestId("drawer").style.getPropertyValue("--as-panel-w")).toBe("480px");
  });
});
