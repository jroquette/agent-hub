import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../testing/axe";
import { aShellView, renderWithApi } from "../testing/builders";
import { LockedBanner } from "./LockedBanner";

const SHELL = "/api/v1/screens/shell";

describe("LockedBanner", () => {
  it("says the page is read-only and how to unlock it when the launch cookie is missing", async () => {
    const view = renderWithApi(<LockedBanner />, {
      routes: { [SHELL]: aShellView({ launch_cookie: "missing" }) },
    });

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Changes are locked in this browser. You can read everything here. Open the link hub web printed",
    );
    expect(await seriousViolations(view.container)).toEqual([]);
  });

  it("goes away when dismissed", async () => {
    renderWithApi(<LockedBanner />, {
      routes: { [SHELL]: aShellView({ launch_cookie: "missing" }) },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    expect(screen.queryByRole("status")).toBeNull();
  });

  it.each(["held", "off"] as const)("shows nothing when the cookie is %s", async (cookie) => {
    const view = renderWithApi(<LockedBanner />, {
      routes: { [SHELL]: aShellView({ launch_cookie: cookie }) },
    });

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(view.container).toBeEmptyDOMElement();
  });
});
