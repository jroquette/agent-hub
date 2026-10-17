import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aCapabilities,
  aWorkdir,
  anAgentSession,
  anEvalRecord,
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { EvalTab, evalPrompt, pickEval, type EvalTabProps } from "./EvalTab";

const AGENT = "/api/v1/agent-sessions";

function tab(props: Partial<EvalTabProps> = {}) {
  return (
    <EvalTab
      project="agent-hub"
      slug="control-plane"
      tickets={["AGH-201", "AGH-202"]}
      evals={[]}
      selected={undefined}
      onSelect={() => undefined}
      {...props}
    />
  );
}

const driving: ApiRoutes = {
  [`${AGENT}/capabilities`]: aCapabilities(),
  [`${AGENT}/workdirs`]: { items: [aWorkdir()], warnings: [] },
};

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
  const row = screen.getByRole("button", { name: new RegExp(`^${delivery},`) }).closest("tr");
  if (!row) throw new Error(`no row ${delivery}`);
  return row;
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("pickEval", () => {
  it("takes the asked delivery, else the newest by date, else the last by name (AC-269.4)", () => {
    const old = anEvalRecord({ delivery: "a", path: "a.md", evaluated_at: "2026-10-01" });
    const recent = anEvalRecord({
      delivery: "b",
      path: "b.md",
      evaluated_at: "2026-10-14T15:46:51Z",
    });
    const undated = anEvalRecord({ delivery: "c", path: "c.md", evaluated_at: null });

    expect(pickEval([recent, old, undated], "a")).toBe(old);
    expect(pickEval([old, recent, undated], null)).toBe(recent);
    expect(pickEval([old, recent], "missing")).toBe(recent);
    expect(pickEval([undated, { ...undated, delivery: "d", path: "d.md" }], null)?.delivery).toBe(
      "d",
    );
    expect(pickEval([], null)).toBeUndefined();
  });
});

describe("evalPrompt", () => {
  it("asks the evaluator for one scope and never to touch an existing eval (AC-269.1)", () => {
    expect(evalPrompt("agent-hub", "control-plane", "feature")).toContain(
      "Scope: the whole feature.",
    );
    const ticket = evalPrompt("agent-hub", "control-plane", "AGH-202");
    expect(ticket).toContain("Scope: ticket AGH-202.");
    expect(ticket).toContain("never edit an existing eval");
  });
});

describe("EvalTab", () => {
  it("selects an eval from its row and reads the selected one below (AC-269.4)", async () => {
    const onSelect = vi.fn();
    renderWithApi(tab({ evals, selected: evals[1], onSelect }), {
      routes: { "/api/v1/projects/agent-hub/brain/note": aBrainNote() },
    });

    expect(rowOf("agh-202")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("article", { name: "Eval agh-202" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^agh-201,/ }));
    expect(onSelect).toHaveBeenCalledWith("agh-201");
  });

  it("starts the evaluator in the hub folder for the chosen scope (AC-269.1, AC-269.2)", async () => {
    const created = anAgentSession({ id: anId(8, "0192a5e5"), status: "running" });
    const view = renderWithApi(tab({ evals }), {
      routes: {
        ...driving,
        [`POST ${AGENT}`]: created,
        [`${AGENT}/${created.id}`]: created,
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "AGH-202" }));
    await userEvent.click(await screen.findByRole("button", { name: "Evaluate AGH-202" }));

    const post = await waitFor(() => {
      const found = view.requests.find(
        (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
      );
      if (!found) throw new Error("no POST");
      return found;
    });
    const body = JSON.parse(await post.clone().text()) as Record<string, unknown>;
    expect(body).toMatchObject({ project: "agent-hub", mode: "acceptEdits" });
    expect(String(body.prompt)).toContain("Scope: ticket AGH-202.");
    expect(await screen.findByText("Evaluating")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open chat/ })).toHaveAttribute(
      "href",
      `/agent-sessions/${created.id}`,
    );
    expect(screen.getByRole("button", { name: /An evaluation is already running/ })).toBeDisabled();
  });

  it("lists every delivery's eval with its verdict, scope and note (golden)", () => {
    renderWithApi(tab({ evals }));

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
    renderWithApi(tab({ evals: [anEvalRecord()] }));

    expect(screen.getByText("3 ACs")).toHaveAttribute("title", "AC-200.1, AC-200.2, AC-200.3");
  });

  it("says no eval was written yet and points to Evaluate when there is none (AC-269.8, golden states)", () => {
    renderWithApi(tab());

    expect(screen.getByText("No evals yet.")).toBeInTheDocument();
    expect(screen.getByText(/Press Evaluate above to write the first one/)).toBeInTheDocument();
  });

  it("puts a run waiting for the owner up front, scope locked (AC-269.3, AC-269.7, golden a11y)", async () => {
    const waiting = anAgentSession({ id: anId(9, "0192a5e5"), status: "waiting_permission" });
    window.localStorage.setItem(
      "agent-hub:eval-run:agent-hub:control-plane",
      JSON.stringify({
        id: waiting.id,
        scope: "AGH-201",
        started_at: new Date().toISOString(),
        known: evals.map((e) => e.path),
      }),
    );
    const { container } = renderWithApi(tab({ evals }), {
      routes: { ...driving, [`${AGENT}/${waiting.id}`]: waiting },
    });

    expect(await screen.findByRole("link", { name: /Answer in chat/ })).toHaveAttribute(
      "href",
      `/agent-sessions/${waiting.id}`,
    );
    expect(screen.getByRole("button", { name: "AGH-201" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Whole feature" })).toBeDisabled();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("keeps Evaluate off with the reason when the project has no hub folder (AC-269.6)", async () => {
    renderWithApi(tab({ evals }), {
      routes: { ...driving, [`${AGENT}/workdirs`]: { items: [], warnings: [] } },
    });

    expect(
      await screen.findByRole("button", {
        name: "Evaluate whole feature. Project agent-hub has no hub folder to work in.",
      }),
    ).toBeDisabled();
  });

  function storeRun(id: string, known: readonly string[]) {
    window.localStorage.setItem(
      "agent-hub:eval-run:agent-hub:control-plane",
      JSON.stringify({ id, scope: "feature", started_at: new Date().toISOString(), known }),
    );
  }

  it("does not read a run idle without a new eval as done (AC-269.5)", async () => {
    const idle = anAgentSession({ id: anId(10, "0192a5e5"), status: "idle" });
    storeRun(
      idle.id,
      evals.map((e) => e.path),
    );
    renderWithApi(tab({ evals }), { routes: { ...driving, [`${AGENT}/${idle.id}`]: idle } });

    expect(await screen.findByText("Finished without a new eval")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Show / })).not.toBeInTheDocument();
  });

  it("shows the eval a finished run wrote and clears the run (AC-269.5)", async () => {
    const onSelect = vi.fn();
    const idle = anAgentSession({ id: anId(11, "0192a5e5"), status: "idle" });
    storeRun(
      idle.id,
      evals.slice(1).map((e) => e.path),
    );
    renderWithApi(tab({ evals, onSelect }), {
      routes: { ...driving, [`${AGENT}/${idle.id}`]: idle },
    });

    expect(await screen.findByText("Finished")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Finished");
    await userEvent.click(screen.getByRole("button", { name: "Show agh-201" }));
    expect(onSelect).toHaveBeenCalledWith("agh-201");
    await userEvent.click(screen.getByRole("button", { name: "Clear this run" }));
    expect(screen.queryByText("Finished")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("agent-hub:eval-run:agent-hub:control-plane")).toBeNull();
  });

  it("forgets a run whose session was deleted (AC-269.5)", async () => {
    storeRun(anId(12, "0192a5e5"), []);
    renderWithApi(tab({ evals }), { routes: driving });

    await waitFor(() => {
      expect(window.localStorage.getItem("agent-hub:eval-run:agent-hub:control-plane")).toBeNull();
    });
    expect(screen.queryByRole("link", { name: /Open chat/ })).not.toBeInTheDocument();
  });

  it("has no serious axe violation (golden a11y)", async () => {
    const { container } = renderWithApi(tab({ evals }));

    await screen.findByRole("table", { name: "Evals" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
