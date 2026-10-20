import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDismissDrawer } from "./useDismissDrawer";

/** A page with a drawer, empty space, a button and the composer. */
function aPage() {
  document.body.innerHTML = `
    <div id="space"><p id="text">Some reply</p><button id="toggle">Open</button><textarea id="composer"></textarea></div>
    <aside class="as-drawer"><p id="inside">Drawer</p></aside>
    <div role="dialog"><p id="dialog">Dialog</p></div>`;
  return (id: string) => {
    const element = document.getElementById(id);
    if (!element) throw new Error(`no #${id}`);
    return element;
  };
}

describe("useDismissDrawer", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("closes an open drawer on a click on space outside it", () => {
    const byId = aPage();
    const onClose = vi.fn();
    renderHook(() => {
      useDismissDrawer(true, onClose);
    });

    byId("text").click();

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps it open on a click inside it, in a dialog, or on something with its own action", () => {
    const byId = aPage();
    const onClose = vi.fn();
    renderHook(() => {
      useDismissDrawer(true, onClose);
    });

    for (const id of ["inside", "dialog", "toggle", "composer"]) byId(id).click();

    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps it open when the click ends a text selection", () => {
    const byId = aPage();
    const onClose = vi.fn();
    vi.spyOn(window, "getSelection").mockReturnValue({
      toString: () => "Some",
    } as unknown as Selection);
    renderHook(() => {
      useDismissDrawer(true, onClose);
    });

    byId("text").click();

    expect(onClose).not.toHaveBeenCalled();
  });

  it("does nothing while no drawer is open", () => {
    const byId = aPage();
    const onClose = vi.fn();
    renderHook(() => {
      useDismissDrawer(false, onClose);
    });

    byId("text").click();

    expect(onClose).not.toHaveBeenCalled();
  });
});
