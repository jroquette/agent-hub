import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppShell } from "../../shell/AppShell";
import { aPage, renderWithApi } from "../../testing/builders";
import { seriousViolations } from "../../testing/axe";
import { NotFoundBody, NotFoundScreen } from "./index";

describe("NotFoundScreen", () => {
  it("names the unknown route in the entity line when no page matches", () => {
    renderWithApi(<NotFoundScreen />, { path: "/sesions" });

    expect(screen.getByRole("heading", { name: "This page does not exist" })).toBeInTheDocument();
    expect(screen.getByText("404 · Not found")).toBeInTheDocument();
    expect(
      screen.getByText("There is no page at /sesions. Check the address or search."),
    ).toBeInTheDocument();
    expect(screen.getByText("/sesions", { selector: ".ah-mono" })).toBeInTheDocument();
  });

  it("shows the entity line and query it is given when an id is unknown", () => {
    renderWithApi(
      <NotFoundBody line="No session with id 5091b98x in the registered hubs." query="5091b98x" />,
      { path: "/sessions/5091b98x" },
    );

    expect(
      screen.getByText("No session with id 5091b98x in the registered hubs."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Search opens prefilled with/)).toHaveTextContent("5091b98x");
  });

  it("opens the palette prefilled with the last path segment when Search is pressed", async () => {
    renderWithApi(
      <AppShell>
        <NotFoundScreen />
      </AppShell>,
      { path: "/sessions/5091b98x", routes: { "/api/v1/search": aPage([]) } },
    );

    await userEvent.click(screen.getByRole("button", { name: /Search with/ }));

    expect(await screen.findByRole("combobox")).toHaveValue("5091b98x");
  });

  it("goes to Portfolio from its second action", async () => {
    const { router } = renderWithApi(<NotFoundScreen />, { path: "/nowhere" });

    await userEvent.click(screen.getByRole("link", { name: "Go to Portfolio" }));

    expect(router.state.location.pathname).toBe("/");
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderWithApi(<NotFoundScreen />, { path: "/nowhere" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
