import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { anEvalRecord, renderWithApi } from "../../testing/builders";
import { EvalTab } from "./EvalTab";

const evals = [
  anEvalRecord(),
  anEvalRecord({
    delivery: "agh-202",
    path: "features/control-plane/evals/agh-202.md",
    verdict: "NO-SHIP",
    tickets: ["AGH-202"],
    acs: ["AC-200.4", "AC-200.5"],
    prs: [],
    commit: null,
    evaluated_at: null,
  }),
  anEvalRecord({
    delivery: "legacy",
    path: "features/control-plane/eval.md",
    verdict: "SHIP-WITH-OWNER-STEPS",
    tickets: [],
    acs: "all",
    prs: [],
    commit: null,
    legacy: true,
  }),
  anEvalRecord({
    delivery: "agh-203",
    path: "features/control-plane/evals/agh-203.md",
    verdict: null,
    tickets: [],
    acs: [],
    prs: [],
    commit: null,
    evaluated_at: null,
    problem: "the frontmatter has no verdict",
  }),
];

function rowOf(delivery: string): HTMLElement {
  const row = screen.getByText(delivery, { selector: "b" }).closest("tr");
  if (!row) throw new Error(`no row ${delivery}`);
  return row;
}

describe("EvalTab", () => {
  it("lists every delivery's eval with its verdict, scope and note (golden)", () => {
    renderWithApi(<EvalTab project="agent-hub" evals={evals} />);

    const table = screen.getByRole("table", { name: "Evals" });
    expect(within(table).getAllByRole("row")).toHaveLength(5);

    const first = within(rowOf("agh-201"));
    expect(first.getByText("SHIP")).toBeInTheDocument();
    expect(first.getByText("AGH-201")).toBeInTheDocument();
    expect(first.getByText("3 ACs")).toBeInTheDocument();
    expect(first.getByText("agent-hub#80")).toBeInTheDocument();
    expect(first.getByText("0a1b2c3")).toBeInTheDocument();
    expect(first.getByText("2026-10-11")).toBeInTheDocument();
    expect(first.getByRole("link", { name: "agh-201.md, the eval of agh-201" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/features/control-plane/evals/agh-201.md",
    );

    expect(within(rowOf("agh-202")).getByText("NO-SHIP")).toBeInTheDocument();
    expect(within(rowOf("legacy")).getByText("All ACs")).toBeInTheDocument();
    expect(within(rowOf("legacy")).getByText("eval.md")).toBeInTheDocument();
    expect(within(rowOf("agh-203")).getByText(/no verdict/)).toBeInTheDocument();
  });

  it("names the ACs of a scope in the cell's title (golden)", () => {
    renderWithApi(<EvalTab project="agent-hub" evals={[anEvalRecord()]} />);

    expect(screen.getByText("3 ACs")).toHaveAttribute("title", "AC-200.1, AC-200.2, AC-200.3");
  });

  it("says no eval was written yet when there is none (golden states)", () => {
    renderWithApi(<EvalTab project="agent-hub" evals={[]} />);

    expect(screen.getByText("No evals yet.")).toBeInTheDocument();
  });

  it("has no serious axe violation (golden a11y)", async () => {
    const { container } = renderWithApi(<EvalTab project="agent-hub" evals={evals} />);

    await screen.findByRole("table", { name: "Evals" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
