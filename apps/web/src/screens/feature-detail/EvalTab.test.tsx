import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aCapabilities,
  aWorkdir,
  anAgentSession,
  anAcRow,
  aTicketRow,
  anEvalRecord,
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import {
  EvalTab,
  OwnerSignOff,
  evalHistory,
  evalPrompt,
  pickEval,
  ranBy,
  settledOwnerSteps,
  type EvalTabProps,
} from "./EvalTab";

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

/** Opens every folded group of the evals table. */
async function openGroups() {
  const table = screen.getByRole("table", { name: "Evals" });
  for (const toggle of within(table).queryAllByRole("button", { expanded: false })) {
    await userEvent.click(toggle);
  }
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

describe("settledOwnerSteps", () => {
  const waiting = (delivery: string, evaluated_at: string | null) =>
    anEvalRecord({
      delivery,
      path: `${delivery}.md`,
      verdict: "SHIP-WITH-OWNER-STEPS",
      evaluated_at,
    });
  const signoff = anEvalRecord({
    delivery: "owner-signoff",
    path: "owner-signoff.md",
    verdict: "SHIP",
    provenance: "owner",
    evaluated_at: "2026-10-19T11:57:18+02:00",
  });

  it("settles the owner-steps evals before the owner's sign-off, not the ones after", () => {
    const before = waiting("dem-1", "2026-10-14T16:35:32+02:00");
    const undated = waiting("dem-2", null);
    const after = waiting("feature-r2", "2026-10-20T09:00:00+02:00");

    const settled = settledOwnerSteps([before, undated, after, signoff]);

    expect([...settled.keys()]).toEqual(["dem-1.md", "dem-2.md"]);
    expect(settled.get("dem-1.md")).toBe(signoff);
  });

  it("settles nothing without an owner sign-off", () => {
    expect(settledOwnerSteps([waiting("dem-1", "2026-10-14")]).size).toBe(0);
  });

  it("reads a signed-off eval as SHIP in the table", () => {
    renderWithApi(tab({ evals: [waiting("dem-1", "2026-10-14T16:35:32+02:00"), signoff] }), {});

    expect(within(rowOf("dem-1")).getByText("SHIP")).toBeInTheDocument();
    expect(within(rowOf("dem-1")).getByText("owner steps signed off")).toBeInTheDocument();
    expect(within(rowOf("dem-1")).queryByText("SHIP-WITH-OWNER-STEPS")).toBeNull();
  });
});

describe("EvalTab rows", () => {
  const SIGNOFF = "/api/v1/features/agent-hub/control-plane/owner-signoff";
  const runs = [
    anEvalRecord({
      delivery: "agh-201",
      path: "agh-201.md",
      verdict: "SHIP-WITH-OWNER-STEPS",
      evaluated_at: "2026-10-12T10:00:00Z",
    }),
    anEvalRecord({
      delivery: "agh-201-r2",
      path: "agh-201-r2.md",
      verdict: "SHIP-WITH-OWNER-STEPS",
      evaluated_at: "2026-10-13T10:00:00Z",
    }),
  ];

  it("names runs by number, the group by its ticket's title, the newest as latest", () => {
    renderWithApi(
      tab({ evals: runs, ticketRows: [aTicketRow({ id: "AGH-201", title: "Claim lifecycle" })] }),
    );

    expect(screen.getByRole("button", { name: /^AGH-201\b.*evals/ })).toHaveTextContent(
      "Claim lifecycle",
    );
    expect(rowOf("agh-201-r2")).toHaveTextContent(/Eval 2\s*latest/);
    expect(within(rowOf("agh-201")).getByText("replaced by Eval 2")).toBeInTheDocument();
  });

  it("shows an eval's ACs as the Tickets tab does, with how many pass", () => {
    renderWithApi(
      tab({
        evals: [anEvalRecord()],
        acRows: [
          anAcRow({ id: "AC-200.1", passes: true }),
          anAcRow({ id: "AC-200.2", passes: false }),
          anAcRow({ id: "AC-200.3", passes: true }),
        ],
      }),
    );

    expect(within(rowOf("agh-201")).getByText("2/3 ACs passing")).toBeInTheDocument();
  });

  it("lines a folded ticket's latest eval up under the table's columns", async () => {
    renderWithApi(tab({ evals: runs }));

    await userEvent.click(screen.getByRole("button", { name: /^AGH-201\b.*2 evals/ }));
    const summary = screen.getByRole("button", { name: /^AGH-201\b.*2 evals/ }).closest("tr");
    if (!summary) throw new Error("no summary row");
    // One cell per column: the ticket, then the latest eval's verdict, ACs, author and date.
    expect(summary.children).toHaveLength(5);
    expect(within(summary).getByText("SHIP-WITH-OWNER-STEPS")).toBeInTheDocument();
    expect(within(summary).getByText("3 ACs")).toBeInTheDocument();
  });

  it("keeps the owner's callout in view when its group is folded", async () => {
    renderWithApi(tab({ evals: runs }));

    await userEvent.click(screen.getByRole("button", { name: /^AGH-201\b.*2 evals/ }));
    expect(screen.queryByRole("button", { name: /^agh-201-r2,/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Mark owner steps done" })).toBeInTheDocument();
  });

  it("folds the whole list and remembers it", async () => {
    const view = renderWithApi(tab({ evals: runs }));

    await userEvent.click(screen.getByRole("button", { name: "Hide list" }));
    expect(screen.queryByRole("table", { name: "Evals" })).toBeNull();
    view.unmount();
    renderWithApi(tab({ evals: runs }));
    expect(screen.queryByRole("table", { name: "Evals" })).toBeNull();
    expect(screen.getByRole("button", { name: "Show list" })).toBeInTheDocument();
  });

  it("records that the owner found more work on the latest run, with a note", async () => {
    const onSelect = vi.fn();
    const written = anEvalRecord({ delivery: "owner-signoff", verdict: "NO-SHIP" });
    const view = renderWithApi(tab({ evals: runs, onSelect }), {
      routes: { [`POST ${SIGNOFF}`]: written },
    });

    // One callout, for the newest eval only, says it waits on the owner.
    expect(screen.getAllByRole("button", { name: "Needs more work" })).toHaveLength(1);
    expect(screen.getByText(/AGH-201 Eval 2 passed with owner steps/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Needs more work" }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "Note (optional)" }),
      "Run the migration",
    );
    await userEvent.click(screen.getByRole("button", { name: "Needs more work" }));

    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledWith("owner-signoff");
    });
    const post = view.requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      delivery: "agh-201-r2",
      decision: "more_work",
      note: "Run the migration",
    });
  });

  it("marks the latest run's owner steps done with a note, after a cancel that sends nothing", async () => {
    const onSelect = vi.fn();
    const written = anEvalRecord({ delivery: "owner-signoff", verdict: "SHIP" });
    const view = renderWithApi(tab({ evals: runs, onSelect }), {
      routes: { [`POST ${SIGNOFF}`]: written },
    });

    await userEvent.click(screen.getByRole("button", { name: "Mark owner steps done" }));
    expect(
      screen.getByRole("form", { name: "Mark the owner steps done: AGH-201 · Eval 2" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox", { name: "Note (optional)" })).toBeNull();
    expect(view.requests.some((r) => r.method === "POST")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Mark owner steps done" }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "Note (optional)" }),
      "Deployed the config by hand",
    );
    await userEvent.click(screen.getByRole("button", { name: "Mark owner steps done" }));

    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledWith("owner-signoff");
    });
    const post = view.requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      delivery: "agh-201-r2",
      decision: "done",
      note: "Deployed the config by hand",
    });
  });

  it("asks nothing more once an owner sign-off settles the latest run", () => {
    const signoff = anEvalRecord({
      delivery: "owner-signoff",
      path: "owner-signoff.md",
      verdict: "SHIP",
      provenance: "owner",
      evaluated_at: "2026-10-14T10:00:00Z",
    });
    renderWithApi(tab({ evals: [...runs, signoff] }));

    expect(screen.queryByRole("button", { name: "Mark owner steps done" })).toBeNull();
    expect(screen.queryByText(/passed with owner steps/)).toBeNull();
    expect(rowOf("owner-signoff")).toHaveTextContent("Owner sign-off");
  });

  it("reads a run the owner found more work on as handled, not as waiting", () => {
    const review = anEvalRecord({
      delivery: "owner-signoff",
      path: "owner-signoff.md",
      verdict: "NO-SHIP",
      provenance: "owner",
      evaluated_at: "2026-10-14T10:00:00Z",
    });
    renderWithApi(tab({ evals: [...runs, review] }));

    expect(within(rowOf("agh-201-r2")).getByText("you found more work")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark owner steps done" })).toBeNull();
    expect(rowOf("owner-signoff")).toHaveTextContent("Owner: more work");
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
    // Only the selected eval's group opens; the others fold to their header.
    expect(screen.queryByRole("button", { name: /^agh-201,/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /^AGH-201\b.*1 eval/ }));
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
      <OwnerSignOff
        project="agent-hub"
        slug="control-plane"
        reason="17 ACs wait on owner steps (SHIP-WITH-OWNER-STEPS)"
        onShow={onSelect}
      />,
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

  it("offers no sign-off inside the Eval tab: the page's banner holds it", () => {
    renderWithApi(tab({ evals }), { routes: driving });

    expect(screen.queryByRole("button", { name: "Mark owner steps done" })).toBeNull();
  });

  it("lists every delivery's eval with its verdict, scope and date (golden)", async () => {
    renderWithApi(tab({ evals }));

    const table = screen.getByRole("table", { name: "Evals" });
    // Folded: the header and a row per scope.
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    await openGroups();
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
    // One scope only: its group starts open.
    expect(
      screen.getByRole("button", { name: /^Whole feature · AGH-200 epic\b.*1 eval/ }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("1 eval · newest first")).toBeInTheDocument();
  });

  it("offers no scope choice when the feature has a single ticket", () => {
    renderWithApi(tab({ tickets: ["AGH-200"] }), { routes: driving });

    expect(screen.queryByRole("radiogroup", { name: "Evaluation scope" })).toBeNull();
    expect(screen.getByRole("button", { name: /^Evaluate whole feature/ })).toBeInTheDocument();
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
