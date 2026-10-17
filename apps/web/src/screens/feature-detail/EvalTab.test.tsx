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
import { EvalTab, evalHistory, evalPrompt, pickEval, ranBy, type EvalTabProps } from "./EvalTab";

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

describe("evalHistory", () => {
  it("groups by scope, the whole feature first then plan order, newest first", () => {
    const a = anEvalRecord({ delivery: "a", path: "a.md", tickets: ["T2"], acs: ["AC-1"] });
    const b = anEvalRecord({ delivery: "b", path: "b.md", tickets: ["T1"], acs: ["AC-2"] });
    const c = anEvalRecord({ delivery: "c", path: "c.md", tickets: ["T2"], acs: ["AC-3"] });
    const epic = anEvalRecord({ delivery: "e", path: "e.md", tickets: ["EP"], acs: ["AC-4"] });

    const groups = evalHistory([a, b, c, epic], ["EP", "T1", "T2"], ["EP"]);

    expect(groups.map((g) => [g.scope, g.evals.map((e) => e.delivery)])).toEqual([
      ["feature", ["e"]],
      ["T1", ["b"]],
      ["T2", ["c", "a"]],
    ]);
  });

  it("names who ran an eval in words", () => {
    expect([ranBy("owner"), ranBy("agent"), ranBy("ci"), ranBy(null)]).toEqual([
      "You (owner sign-off)",
      "Agent",
      "ci",
      null,
    ]);
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

  it("signs off the owner steps after a confirmation when the eval waits on them", async () => {
    const SIGNOFF = "/api/v1/features/agent-hub/control-plane/owner-signoff";
    const onSelect = vi.fn();
    const written = anEvalRecord({
      delivery: "owner-signoff",
      path: "features/control-plane/evals/owner-signoff.md",
      verdict: "SHIP",
    });
    const view = renderWithApi(
      tab({ evals, onSelect, ownerWait: "17 ACs wait on owner steps (SHIP-WITH-OWNER-STEPS)" }),
      { routes: { ...driving, [`POST ${SIGNOFF}`]: written } },
    );

    await userEvent.click(screen.getByRole("button", { name: "Mark owner steps done" }));
    expect(view.requests.some((r) => r.method === "POST")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Yes, I did them" }));

    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledWith("owner-signoff");
    });
    expect(
      view.requests.some((r) => r.method === "POST" && new URL(r.url).pathname === SIGNOFF),
    ).toBe(true);
  });

  it("offers no sign-off when nothing waits on the owner", () => {
    renderWithApi(tab({ evals }), { routes: driving });

    expect(screen.queryByRole("button", { name: "Mark owner steps done" })).toBeNull();
  });

  it("lists every delivery's eval with its verdict, scope and date (golden)", () => {
    renderWithApi(tab({ evals }));

    const table = screen.getByRole("table", { name: "Evals" });
    // The header, a row per scope (whole feature, AGH-201, AGH-202) and the four evals.
    expect(within(table).getAllByRole("row")).toHaveLength(8);

    const first = within(rowOf("agh-201"));
    expect(first.getByText("SHIP")).toBeInTheDocument();
    expect(first.getByText("3 ACs")).toBeInTheDocument();
    expect(first.getByText("2026-10-11")).toBeInTheDocument();

    expect(within(rowOf("agh-202")).getByText("NO-SHIP")).toBeInTheDocument();
    expect(within(rowOf("legacy")).getByText("All ACs")).toBeInTheDocument();
    expect(rowOf("legacy")).toHaveTextContent(/^eval\.md/);
    expect(within(rowOf("legacy")).queryByText("legacy")).toBeNull();
    expect(within(rowOf("agh-203")).getByText(/no verdict/)).toBeInTheDocument();
  });

  it("reads the selected eval in place with who ran it, its details folded (golden)", async () => {
    const one = anEvalRecord({ provenance: "agent-evaluator" });
    renderWithApi(tab({ evals: [one], selected: one }), {
      routes: { "/api/v1/projects/agent-hub/brain/note": aBrainNote() },
    });

    expect(within(rowOf("agh-201")).getByText("Evaluator agent")).toBeInTheDocument();
    const card = within(screen.getByRole("article", { name: "Eval agh-201" }));
    expect(card.getByText("SHIP")).toBeInTheDocument();
    expect(card.getByText("3 ACs")).toHaveAttribute("title", "AC-200.1, AC-200.2, AC-200.3");
    expect(card.getByText("Evaluated 2026-10-11")).toBeInTheDocument();
    expect(card.getByText(/by Evaluator agent/)).toBeInTheDocument();
    expect(card.getByText(/AGH-201/)).toBeInTheDocument();
    expect(card.getByText(/agent-hub#80/)).toBeInTheDocument();
    expect(card.getByText("0a1b2c3")).toBeInTheDocument();
    expect(card.getByRole("link", { name: "Open in Brain" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/features/control-plane/evals/agh-201.md",
    );
    const details = (await card.findByText("Details")).closest("details");
    expect(details).not.toHaveAttribute("open");
  });

  it("treats the epic as the whole feature, not as a scope of its own", () => {
    const epicEval = anEvalRecord({ delivery: "agh-200", tickets: ["AGH-200"] });
    renderWithApi(tab({ tickets: ["AGH-200", "AGH-201"], epics: ["AGH-200"], evals: [epicEval] }), {
      routes: driving,
    });

    expect(
      screen.getByRole("button", { name: "Whole feature · AGH-200 epic" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "AGH-200" })).toBeNull();
    expect(screen.getByRole("button", { name: "AGH-201" })).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /Whole feature · AGH-200 epic/ }),
    ).toBeInTheDocument();
  });

  it("leaves out an empty AC list instead of saying 0 ACs", () => {
    const none = anEvalRecord({ acs: [] });
    renderWithApi(tab({ evals: [none], selected: none }));

    expect(screen.queryByText(/0 ACs/)).toBeNull();
  });

  it("makes Evaluate secondary once an eval exists, primary before (AC-269.8)", async () => {
    const view = renderWithApi(tab({ evals: [anEvalRecord()] }), { routes: driving });
    expect(await screen.findByRole("button", { name: "Evaluate whole feature" })).not.toHaveClass(
      "ah-btn-primary",
    );
    view.unmount();
    renderWithApi(tab(), { routes: driving });
    expect(await screen.findByRole("button", { name: "Evaluate whole feature" })).toHaveClass(
      "ah-btn-primary",
    );
  });

  it("says no eval was written yet and points to Evaluate when there is none (AC-269.8, golden states)", () => {
    renderWithApi(tab());

    expect(screen.getByText("No evals yet.")).toBeInTheDocument();
    expect(
      screen.getByText(/Press Evaluate whole feature to write the first one/),
    ).toBeInTheDocument();
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
