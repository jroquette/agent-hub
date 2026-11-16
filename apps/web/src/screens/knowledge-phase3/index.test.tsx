import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithApi } from "../../testing/builders";
import { seriousViolations } from "../../testing/axe";
import { KnowledgePhase3Screen } from "./index";

const route = "/knowledge/:section";

describe("KnowledgePhase3Screen", () => {
  it("shows only the title and the Phase 3 line when a later Knowledge item opens", () => {
    const { container } = renderWithApi(<KnowledgePhase3Screen />, {
      path: "/knowledge/decisions",
      route,
    });

    expect(screen.getByRole("heading", { level: 1, name: "Decisions" })).toBeInTheDocument();
    expect(screen.getByText("Arrives in Phase 3.")).toBeInTheDocument();
    expect(container.querySelectorAll("button, a")).toHaveLength(0);
  });

  it("titles the context item Context", () => {
    renderWithApi(<KnowledgePhase3Screen />, { path: "/knowledge/context", route });

    expect(screen.getByRole("heading", { level: 1, name: "Context" })).toBeInTheDocument();
  });

  it("shows the 404 page for brain now that Brain has its own screen", () => {
    renderWithApi(<KnowledgePhase3Screen />, { path: "/knowledge/brain", route });

    expect(screen.getByRole("heading", { name: "This page does not exist" })).toBeInTheDocument();
  });

  it("shows the 404 page when the Knowledge item is unknown", () => {
    renderWithApi(<KnowledgePhase3Screen />, { path: "/knowledge/metrics", route });

    expect(screen.getByRole("heading", { name: "This page does not exist" })).toBeInTheDocument();
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderWithApi(<KnowledgePhase3Screen />, {
      path: "/knowledge/decisions",
      route,
    });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
