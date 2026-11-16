import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithApi } from "../../testing/builders";
import { CreateMenu } from "./CreateMenu";

function open() {
  const rendered = renderWithApi(<CreateMenu project="demo" />, {
    path: "/projects/demo/skills",
    route: "/projects/:project/skills",
  });
  fireEvent.click(screen.getByRole("button", { name: /Create with Claude/ }));
  return rendered;
}

describe("CreateMenu", () => {
  it("offers one row per kind, each a name over what the kind is, and focuses the first", () => {
    open();

    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "New agentSpecialists the session delegates to",
      "New skillPackaged instructions, run as /commands",
      "New hookCommands run at lifecycle events",
      "New workflowSteps the hub runs by itself, chaining agents and commands",
    ]);
    expect(items[0]).toHaveFocus();
  });

  it("moves with the arrow keys and closes on Escape, back on the button", () => {
    open();
    const menu = screen.getByRole("menu", { name: "Create with Claude" });

    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(screen.getByRole("menuitem", { name: /New workflow/ })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Escape" });

    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: /Create with Claude/ })).toHaveFocus();
  });

  it("opens the project's new workflow page in the Toolkit from New workflow", () => {
    const { router } = open();

    fireEvent.click(screen.getByRole("menuitem", { name: /New workflow/ }));

    expect(router.state.location.pathname).toBe("/projects/demo/skills/workflows/new");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes when a kind is picked", () => {
    open();

    fireEvent.click(screen.getByRole("menuitem", { name: /New agent/ }));

    expect(screen.queryByRole("menu")).toBeNull();
  });
});
