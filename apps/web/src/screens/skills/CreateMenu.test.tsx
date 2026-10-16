import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithApi } from "../../testing/builders";
import { CreateMenu } from "./CreateMenu";

function open() {
  renderWithApi(<CreateMenu project="demo" />, {
    path: "/projects/demo/skills",
    route: "/projects/:project/skills",
  });
  fireEvent.click(screen.getByRole("button", { name: /Create with Claude/ }));
}

describe("CreateMenu", () => {
  it("offers one row per kind, each a name over what the kind is, and focuses the first", () => {
    open();

    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "New skillPackaged instructions, run as /commands",
      "New agentSpecialists the session delegates to",
      "New hookCommands run at lifecycle events",
    ]);
    expect(items[0]).toHaveFocus();
  });

  it("moves with the arrow keys and closes on Escape, back on the button", () => {
    open();
    const menu = screen.getByRole("menu", { name: "Create with Claude" });

    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(screen.getByRole("menuitem", { name: /New hook/ })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Escape" });

    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: /Create with Claude/ })).toHaveFocus();
  });

  it("closes when a kind is picked", () => {
    open();

    fireEvent.click(screen.getByRole("menuitem", { name: /New agent/ }));

    expect(screen.queryByRole("menu")).toBeNull();
  });
});
