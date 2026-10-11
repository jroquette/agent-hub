import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { seriousViolations } from "./testing/axe";

describe("App", () => {
  it("renders the product name as the page heading", () => {
    render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: "agent-hub" })).toBeInTheDocument();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = render(<App />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
