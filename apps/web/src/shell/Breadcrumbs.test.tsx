import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../testing/axe";
import { renderWithApi } from "../testing/builders";
import { Breadcrumbs } from "./Breadcrumbs";

describe("Breadcrumbs", () => {
  it("links every crumb but the last, which is the page", async () => {
    const { container } = renderWithApi(
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: "agent-hub", href: "/projects/agent-hub" },
          { label: "Session 5091b986", mono: true },
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: "agent-hub" })).toHaveAttribute(
      "href",
      "/projects/agent-hub",
    );
    expect(screen.getByText("Session 5091b986")).toHaveAttribute("aria-current", "page");
    expect(await seriousViolations(container)).toEqual([]);
  });
});
