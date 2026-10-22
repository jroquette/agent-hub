/* Plan change requests and the ticket flow's signals on Feature detail (two-level-flows S2,
 * AGH-405): the waiting banner and its opener (AC-2.8, AC-1.10 via A8), the asking and affected
 * tickets' signals (AC-2.8), local drift (AC-2.5), discoveries (AC-2.13) and the decision in the
 * ticket panel: the run's gate (AC-2.7, AC-2.12) or the lost-run form (AC-2.12, AC-2.14). */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aChangeRequest,
  aFeatureDetail,
  aFeatureTickets,
  aGoldenPath,
  aPage,
  aPreflightRun,
  aTicketFlow,
  aTicketRecords,
  anEvalRecord,
  ProblemReply,
  renderWithApi,
  type FeatureTickets,
} from "../../testing/builders";
import { fmtDateTime } from "../../lib/format";
import { FeatureDetailScreen } from "./index";
import { belowHeading } from "./TicketPanel";
import { TicketsTab } from "./TicketsTab";

const API = "/api/v1/features/agent-hub/control-plane";
const RECORDS = `${API}/tickets/AGH-202`;
const GATE = "implement-202:approve-change:1";
const GATE_PATH = `/api/v1/approvals/${encodeURIComponent(GATE)}`;

type Flow = ReturnType<typeof aTicketFlow>;
type Step = Flow["steps"][number];

/** A flow whose Preflight step is `preflight`, with `signal`; at Preflight. */
function flowWith(preflight: Partial<Step>, signal: string | null): Flow {
  return aTicketFlow({
    steps: aTicketFlow().steps.map((step) =>
      step.name === "preflight" ? { ...step, ...preflight } : step,
    ),
    current: "preflight",
    signal,
  });
}

const ASKING = flowWith(
  { state: "waiting", meta: "Waiting for you" },
  "Waiting for you: plan change",
);
const HELD = flowWith({ state: "done", meta: null }, "Held: plan change pending");
const LOCAL = flowWith({ state: "done", meta: "Local drift · 2 notes" }, "Local drift · 2 notes");
const STALE = flowWith(
  { state: "stale", meta: "Plan v3 approved: re-run preflight" },
  "Plan v3 approved: re-run preflight",
);

/** The three tickets of `control-plane`, AGH-202 and AGH-203 with the given flows. */
function tickets(flows: Partial<Record<string, Flow>>): FeatureTickets {
  const data = aFeatureTickets();
  return {
    ...data,
    tickets: data.tickets.map((row) => ({ ...row, flow: flows[row.ref] ?? aTicketFlow() })),
  };
}

const LOCAL_RECORDS = aTicketRecords({
  preflight: {
    runs: [
      aPreflightRun({
        drift: "local",
        local_notes: ["Reuse the shared form.", "Name the route as the API does."],
      }),
      aPreflightRun({
        ran_at: "2026-10-21T11:00:00Z",
        input: "discovery",
        input_text: "The claim service needs auth headers",
      }),
    ],
    problem: null,
  },
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function panel(): HTMLElement {
  return screen.getByRole("complementary", { name: /^Ticket AGH-202/ });
}

function showTab(data: FeatureTickets, path: string, routes: Record<string, unknown> = {}) {
  return renderWithApi(
    <TicketsTab
      project="agent-hub"
      slug="control-plane"
      data={data}
      error={null}
      onRefresh={() => undefined}
      evals={[]}
      openerRef={{ current: null }}
    />,
    { routes: { "/api/v1/sessions": aPage([]), ...routes }, path },
  );
}

describe("Waiting banner (AC-2.8, AC-1.10)", () => {
  const detail = aFeatureDetail({
    change_requests: [aChangeRequest()],
    golden_path: aGoldenPath({
      steps: aGoldenPath().steps.map((step) =>
        step.name === "plan" ? { ...step, signal: "v3 waits for you" } : step,
      ),
    }),
  });

  function open(path = "/features/agent-hub/control-plane?doc=acs") {
    return renderWithApi(<FeatureDetailScreen />, {
      routes: {
        [API]: detail,
        [`${API}/tickets`]: tickets({ "AGH-202": ASKING, "AGH-203": HELD }),
        [RECORDS]: aTicketRecords({ change_requests: [aChangeRequest()] }),
        "/api/v1/sessions": aPage([]),
      },
      path,
      route: "features/:project/:slug",
    });
  }

  it("AC-2.8 names the open change request above the tabs, and Plan carries its signal (a11y)", async () => {
    open();

    const banner = (
      await screen.findByText(
        (_, element) =>
          element?.tagName === "LI" &&
          element.textContent.startsWith(
            "Plan change request 2 from AGH-202: plan v2 → v3 · affects AGH-203 · waiting ",
          ),
      )
    ).closest('[role="status"]');
    if (!(banner instanceof HTMLElement)) throw new Error("no banner");
    expect(within(banner).getByText("Waiting for you")).toBeInTheDocument();
    // A20: how long the request has waited.
    expect(banner).toHaveTextContent("waiting");
    expect(screen.getByRole("list", { name: "Golden path" })).toHaveTextContent("v3 waits for you");
    expect(await seriousViolations(document.body)).toEqual([]);
  });

  it("AC-1.10 the banner opens the asking ticket's panel at Preflight; Esc returns focus to it", async () => {
    const { router } = open();

    const review = await screen.findByRole("button", {
      name: "Review change request 2 from AGH-202",
    });
    await userEvent.click(review);

    expect(router.state.location.search).toBe("?doc=tickets&ticket=AGH-202&step=preflight");
    expect(router.state.historyAction).toBe("REPLACE");
    const opened = await screen.findByRole("complementary", { name: /^Ticket AGH-202/ });
    expect(
      within(opened).getByRole("button", { name: /^Preflight, waiting for you/ }),
    ).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: /^Ticket AGH-202/ })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Review change request 2 from AGH-202" }),
    ).toHaveFocus();
  });

  // U5: a request that arrives while the page is open is said once in a polite region.
  it("AC-2.8 announces a newly arrived change request once", async () => {
    let requests: ReturnType<typeof aChangeRequest>[] = [aChangeRequest({ n: 1 })];
    const { queryClient } = renderWithApi(<FeatureDetailScreen />, {
      routes: { [API]: () => aFeatureDetail({ change_requests: requests }) },
      path: "/features/agent-hub/control-plane?doc=acs",
      route: "features/:project/:slug",
    });
    await screen.findByRole("list", { name: "Golden path" });
    const region = document.querySelector('[aria-live="polite"].ah-sr');
    expect(region).toHaveTextContent(/^$/);

    requests = [aChangeRequest({ n: 1 }), aChangeRequest()];
    await queryClient.invalidateQueries();

    // Q12: only the new one: the request open at load is the banner's.
    await vi.waitFor(() => {
      expect(region).toHaveTextContent(/^AGH-202 waits for you: plan change request 2\.$/);
    });
  });

  // UX F2, A18/A19: a sign-off the owner writes by hand is a wait too: the banner signposts it,
  // with no button (the Eval tab's callout says what to write).
  it("A19 lists the hand-written sign-off in the banner, with no button", async () => {
    const record = anEvalRecord({ delivery: "feature", tickets: [], acs: "all" });
    const { router } = renderWithApi(<FeatureDetailScreen />, {
      routes: {
        [API]: aFeatureDetail({
          evals: [record],
          acceptance_eval: {
            delivery: "feature",
            verdict: "SHIP-WITH-OWNER-STEPS",
            owner_wait: { state: "no_acs", acs: [], reopened: [] },
          },
        }),
      },
      path: "/features/agent-hub/control-plane?doc=acs",
      route: "features/:project/:slug",
    });

    const line = await screen.findByRole("link", {
      name: /^Acceptance: sign off by hand · no ACs listed/,
    });
    const banner = line.closest('[role="status"]');
    if (!(banner instanceof HTMLElement)) throw new Error("no banner");
    expect(within(banner).getByText("Waiting for you")).toBeInTheDocument();
    expect(within(banner).queryByRole("button")).toBeNull();
    await userEvent.click(line);
    expect(router.state.location.search).toBe("?doc=eval&eval=feature");
  });

  it("AC-2.8 shows no banner once the request is decided", async () => {
    renderWithApi(<FeatureDetailScreen />, {
      routes: {
        [API]: aFeatureDetail({ change_requests: [aChangeRequest({ status: "approved" })] }),
      },
      path: "/features/agent-hub/control-plane?doc=acs",
      route: "features/:project/:slug",
    });

    await screen.findByRole("list", { name: "Golden path" });
    expect(screen.queryByText("Waiting for you")).toBeNull();
  });
});

describe("Ticket signals on cards and rows (AC-2.8, AC-2.5, A13)", () => {
  const data = tickets({ "AGH-202": ASKING, "AGH-203": HELD });

  // U13: the signals' marks and words pass axe in both views.
  it("AC-2.8 has no serious axe violation with the signals, Flow and Table (a11y)", async () => {
    const { unmount } = showTab(data, "/?doc=tickets");
    expect(await seriousViolations(document.body)).toEqual([]);
    unmount();
    showTab(data, "/?doc=tickets&tickets=table");
    expect(await seriousViolations(document.body)).toEqual([]);
  });

  // U7: while a plan change waits for the owner, Start is no view's primary.
  it("AC-2.8 makes Start secondary while a plan change waits", async () => {
    const waiting = tickets({ "AGH-203": ASKING });
    const { unmount } = showTab(waiting, "/?doc=tickets");
    const quiet = await screen.findByRole("button", { name: /^Start AGH-202/ });
    expect(quiet).not.toHaveClass("ah-btn-primary");
    unmount();
    showTab(tickets({}), "/?doc=tickets");
    expect(await screen.findByRole("button", { name: /^Start AGH-202/ })).toHaveClass(
      "ah-btn-primary",
    );
  });

  it("AC-2.8 the asking ticket waits for you and the affected one is held, in place of readiness", () => {
    showTab(data, "/?doc=tickets");

    const asking = screen.getByRole("listitem", { name: /^AGH-202/ });
    const held = screen.getByRole("listitem", { name: /^AGH-203/ });
    expect(asking).toHaveTextContent("Waiting for you: plan change");
    expect(asking).toHaveTextContent("Preflight · 2/7 · Waiting for you");
    expect(asking).not.toHaveTextContent("Can start now");
    expect(held).toHaveTextContent("Held: plan change pending");
  });

  it("AC-2.8 a stale preflight reads its re-run on the row", () => {
    showTab(tickets({ "AGH-202": STALE }), "/?doc=tickets&tickets=table");

    const row = screen.getByRole("row", { name: /^AGH-202/ });
    expect(row).toHaveTextContent("Plan v3 approved: re-run preflight");
    expect(row).not.toHaveTextContent("Can start now");
  });

  it("AC-2.5 local drift joins the readiness line on the card and the row, never replaces it", () => {
    showTab(tickets({ "AGH-202": LOCAL }), "/?doc=tickets");
    const card = screen.getByRole("listitem", { name: /^AGH-202/ });
    expect(card).toHaveTextContent("Local drift · 2 notes");
    expect(card).toHaveTextContent("Can start now");
  });

  it("AC-2.5 local drift shows in the table's readiness cell", () => {
    showTab(tickets({ "AGH-202": LOCAL }), "/?doc=tickets&tickets=table");
    const row = screen.getByRole("row", { name: /^AGH-202/ });
    expect(row).toHaveTextContent("Local drift · 2 notes");
    expect(row).toHaveTextContent("Can start now");
  });
});

describe("Ticket panel Preflight and Implement (AC-2.5, AC-2.13)", () => {
  it("AC-2.5 lists every local note under Preflight, which stays done", async () => {
    showTab(tickets({ "AGH-202": LOCAL }), "/?doc=tickets&ticket=AGH-202&step=preflight", {
      [RECORDS]: LOCAL_RECORDS,
    });

    const preflight = within(panel()).getByRole("button", { name: /^Preflight, done/ });
    expect(preflight).toHaveAttribute("aria-expanded", "true");
    expect(await within(panel()).findByText("Reuse the shared form.")).toBeInTheDocument();
    expect(within(panel()).getByText("Name the route as the API does.")).toBeInTheDocument();
    expect(panel()).toHaveTextContent("Local drift · 2 notes");
    expect(panel()).toHaveTextContent("after a discovery: The claim service needs auth headers");
  });

  it("AC-2.13 lists each discovery under Implement", async () => {
    showTab(tickets({ "AGH-202": LOCAL }), "/?doc=tickets&ticket=AGH-202&step=implement", {
      [RECORDS]: LOCAL_RECORDS,
    });

    expect(
      await within(panel()).findByText(/Discovery .*: The claim service needs auth headers\./),
    ).toBeInTheDocument();
  });
});

describe("Deciding a change request in the ticket panel (AC-2.7, AC-2.12, AC-2.14)", () => {
  const path = "/?doc=tickets&ticket=AGH-202&step=preflight";
  const gate = {
    approval_id: GATE,
    run_id: "implement-202",
    project: "agent-hub",
    workflow: "implement",
    node: "approve-change",
    attempt: 1,
    form: "decision",
    choices: [
      { id: "approve", label: "Approve" },
      { id: "decline", label: "Decline" },
    ],
    text: "optional",
  };

  it("AC-2.7 AC-2.12 answers the run's gate: Approve, and Decline only with a note", async () => {
    const decided = { approval_id: GATE, run_id: "implement-202", project: "agent-hub" };
    const { requests } = showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({ change_requests: [aChangeRequest()] }),
      [`${GATE_PATH}/gate`]: gate,
      [`POST ${GATE_PATH}/decision`]: { ...decided, decision: "decline" },
    });

    await userEvent.click(await within(panel()).findByRole("button", { name: "Decline" }));
    const dialog = screen.getByRole("dialog", { name: "Decline?" });
    const confirm = within(dialog).getByRole("button", { name: "Decline" });
    expect(within(dialog).getByLabelText("Note (required)")).toBeInTheDocument();
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Note (required)"), "Follow the plan.");
    await userEvent.click(confirm);

    const post = requests.find((r) => r.method === "POST");
    expect(post?.url).toContain(`${GATE_PATH}/decision`);
    expect(await post?.json()).toEqual({ decision: "decline", text: "Follow the plan." });
    expect(requests.some((r) => r.url.includes("/change-requests/"))).toBe(false);
  });

  it("AC-2.14 without an open gate, records the decision in the hub; Decline needs a note (a11y)", async () => {
    const lost = aChangeRequest({ approval_id: null, decidable_here: true });
    const { requests } = showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({ change_requests: [lost] }),
      [`POST ${API}/change-requests/2/decision`]: aChangeRequest({ status: "declined" }),
    });

    const group = await within(panel()).findByRole("group", { name: "Decide change request 2" });
    await userEvent.click(within(group).getByRole("button", { name: "Decline" }));
    expect(within(panel()).getByRole("alert")).toHaveTextContent(
      "Write a note to decline: the next preflight follows it.",
    );
    expect(within(panel()).getByLabelText("Note (required to decline)")).toHaveFocus();
    expect(requests.some((r) => r.method === "POST")).toBe(false);
    expect(await seriousViolations(panel())).toEqual([]);

    await userEvent.type(
      within(panel()).getByLabelText("Note (required to decline)"),
      "Keep the current contract.",
    );
    await userEvent.click(within(group).getByRole("button", { name: "Decline" }));

    const post = requests.find((r) => r.method === "POST");
    expect(post?.url).toContain(`${API}/change-requests/2/decision`);
    expect(await post?.json()).toEqual({
      decision: "declined",
      note: "Keep the current contract.",
    });
  });

  it("AC-2.14 approves a lost run's request without a note", async () => {
    const { requests } = showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({
        change_requests: [aChangeRequest({ approval_id: null, decidable_here: true })],
      }),
      [`POST ${API}/change-requests/2/decision`]: aChangeRequest({ status: "approved" }),
    });

    await userEvent.click(await within(panel()).findByRole("button", { name: "Approve plan v3" }));

    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({ decision: "approved", note: null });
    // U3: it says it was recorded, and the buttons stay off.
    expect(
      await within(panel()).findByText(
        "Decision recorded in the hub. The next /implement of AGH-202 reads it.",
      ),
    ).toBeInTheDocument();
    expect(within(panel()).getByRole("button", { name: "Approve plan v3" })).toBeDisabled();
  });

  // Q1: no open gate is not enough: while the run lives it records the decision itself.
  it("AC-2.14 offers no lost-run form while the server says the run lives", async () => {
    showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({
        change_requests: [aChangeRequest({ approval_id: null, decidable_here: false })],
      }),
    });

    expect(await within(panel()).findByText(/Its run is live/)).toBeInTheDocument();
    expect(within(panel()).queryByRole("group", { name: /^Decide/ })).toBeNull();
  });

  // U3: a refusal reads as the gate's does, and says nothing was recorded.
  it("AC-2.14 shows the server's refusal when the lost-run decision is refused", async () => {
    showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({
        change_requests: [aChangeRequest({ approval_id: null, decidable_here: true })],
      }),
      [`POST ${API}/change-requests/2/decision`]: new ProblemReply({
        status: 409,
        type: "urn:agent-hub:problem:change-request-live-run",
        title: "Change request cannot be decided",
        detail: "run implement-202 is live: it records the decision itself",
      }),
    });

    await userEvent.click(await within(panel()).findByRole("button", { name: "Approve plan v3" }));

    const alert = await within(panel()).findByRole("alert");
    expect(alert).toHaveTextContent("run implement-202 is live: it records the decision itself");
    expect(alert).toHaveTextContent("Nothing was recorded.");
  });

  // U6: after a decision here, focus lands on the line that records it.
  it("AC-2.14 moves focus to the decided line once the decision is read back", async () => {
    let decided = false;
    const open = aChangeRequest({ approval_id: null, decidable_here: true });
    const done = aChangeRequest({
      status: "approved",
      approval_id: null,
      decision: {
        decision: "approved",
        decided_by: "Dana Owner",
        decided_at: "2026-10-21",
        note: null,
      },
    });
    showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: () => aTicketRecords({ change_requests: [decided ? done : open] }),
      [`POST ${API}/change-requests/2/decision`]: () => {
        decided = true;
        return done;
      },
    });

    await userEvent.click(await within(panel()).findByRole("button", { name: "Approve plan v3" }));

    const line = await within(panel()).findByText(
      "Change request 2 approved by Dana Owner · 2026-10-21",
    );
    expect(line).toHaveFocus();
  });

  // UX F1, Q1: after a decision through the gate, the panel says it went to the run, then focus
  // lands on the decided line once the run records it.
  it("AC-2.7 moves focus to the decided line after a decision through the gate", async () => {
    let stage: "open" | "sent" | "recorded" = "open";
    const sent = aChangeRequest({ approval_id: null, decidable_here: false });
    const recorded = aChangeRequest({
      status: "approved",
      approval_id: null,
      decision: {
        decision: "approved",
        decided_by: "Dana Owner",
        decided_at: "2026-10-21",
        note: null,
      },
    });
    const { queryClient } = showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: () =>
        aTicketRecords({
          change_requests: [
            stage === "open" ? aChangeRequest() : stage === "sent" ? sent : recorded,
          ],
        }),
      [`${GATE_PATH}/gate`]: gate,
      [`POST ${GATE_PATH}/decision`]: () => {
        stage = "sent";
        return {
          approval_id: GATE,
          run_id: "implement-202",
          project: "agent-hub",
          decision: "approve",
        };
      },
    });

    await userEvent.click(await within(panel()).findByRole("button", { name: "Approve" }));
    const confirm = await screen.findByRole("dialog", { name: "Approve?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Approve" }));
    await queryClient.invalidateQueries();
    // UX r3 1: the sent line takes focus while the run records the decision.
    const sentLine = await within(panel()).findByText(
      "Decision sent; the run records it and this shows it.",
    );
    expect(sentLine).toHaveAttribute("role", "status");
    await vi.waitFor(() => {
      expect(sentLine).toHaveFocus();
    });

    stage = "recorded";
    await queryClient.invalidateQueries();

    const line = await within(panel()).findByText(
      "Change request 2 approved by Dana Owner · 2026-10-21",
    );
    expect(line).toHaveFocus();
  });

  // Q16: a gate that takes no text sends the decline at once, with no text the gate would refuse.
  it("AC-2.12 sends a decline with no text on a gate that takes none", async () => {
    const { requests } = showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({ change_requests: [aChangeRequest()] }),
      [`${GATE_PATH}/gate`]: { ...gate, text: "off" },
      [`POST ${GATE_PATH}/decision`]: {
        approval_id: GATE,
        run_id: "implement-202",
        project: "agent-hub",
        decision: "decline",
      },
    });

    await userEvent.click(await within(panel()).findByRole("button", { name: "Decline" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({ decision: "decline" });
  });

  // A20, U13: evidence, proposal, consequences and the wait before the gate's buttons.
  it("A20 shows the request's evidence and what approving does before deciding (a11y)", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-21T11:30:00Z") });
    showTab(tickets({ "AGH-202": ASKING, "AGH-203": HELD }), path, {
      [RECORDS]: aTicketRecords({ change_requests: [aChangeRequest()] }),
      [`${GATE_PATH}/gate`]: gate,
    });

    const block = await within(panel()).findByRole("region", { name: "Plan change request 2" });
    expect(within(block).getByRole("heading", { name: "Evidence" })).toBeInTheDocument();
    expect(within(block).getByRole("heading", { name: "Proposal" })).toBeInTheDocument();
    expect(block).toHaveTextContent("agent");
    expect(block).toHaveTextContent(
      "Plan drift: it changes an AC, a contract or another ticket, so AGH-202 is paused until you answer.",
    );
    expect(block).toHaveTextContent("Plan v2 becomes v3 (a new amendment).");
    expect(block).toHaveTextContent("AGH-203 runs preflight again before it goes on.");
    expect(block).toHaveTextContent("Nothing is merged or pushed.");
    expect(block).toHaveTextContent("waiting 2 h");
    // UX r3 4: the age's title is the date-time as the page writes it, not the raw ISO.
    expect(within(block).getByText("2 h").closest("time")).toHaveAttribute(
      "title",
      fmtDateTime("2026-10-21T09:30:00Z", "local"),
    );
    // UX F4: the request is a heading, its body's headings one level below it.
    expect(
      within(block).getByRole("heading", { level: 4, name: "Plan change request 2: plan v2 → v3" }),
    ).toBeInTheDocument();
    expect(within(block).getByRole("heading", { level: 5, name: "Evidence" })).toBeInTheDocument();
    const evidence = within(block).getByText("What changes if you approve");
    const decline = await within(block).findByRole("button", { name: "Decline" });
    expect(
      evidence.compareDocumentPosition(decline) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    vi.useRealTimers();
    expect(await seriousViolations(panel())).toEqual([]);
  });

  // UX F3: the consequence agrees with how many tickets it names.
  it("A20 says several affected tickets in the plural", async () => {
    showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({
        change_requests: [aChangeRequest({ affected: ["AGH-203", "AGH-204"] })],
      }),
      [`${GATE_PATH}/gate`]: gate,
    });

    expect(
      await within(panel()).findByText("AGH-203, AGH-204 run preflight again before they go on."),
    ).toBeInTheDocument();
  });

  // Q13: a request cut at the head read says so beside its text.
  it("A20 says a long request is cut and where to read it whole", async () => {
    showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({ change_requests: [aChangeRequest({ body_cut: true })] }),
      [`${GATE_PATH}/gate`]: gate,
    });

    expect(
      await within(panel()).findByText(
        "The request goes on past what is shown: read the full request in Brain before deciding.",
      ),
    ).toBeInTheDocument();
  });

  // U12: the panel's one primary act opens Preflight at the request.
  it("AC-1.10 the panel header's Review change request opens Preflight at the request", async () => {
    const { router } = showTab(
      tickets({ "AGH-202": ASKING }),
      "/?doc=tickets&ticket=AGH-202&step=review",
      {
        [RECORDS]: aTicketRecords({ change_requests: [aChangeRequest()] }),
        [`${GATE_PATH}/gate`]: gate,
      },
    );

    await userEvent.click(
      await within(panel()).findByRole("button", { name: "Review change request" }),
    );

    expect(router.state.location.search).toBe("?doc=tickets&ticket=AGH-202&step=preflight");
    await vi.waitFor(() => {
      expect(within(panel()).getByRole("region", { name: "Plan change request 2" })).toHaveFocus();
    });
  });

  // Q5: an unreadable request offers no decision; a decided one holds nobody.
  it("AC-2.8 offers no decision on an unreadable request and holds no ticket once decided", async () => {
    const unreadable = aChangeRequest({
      status: null,
      approval_id: null,
      decidable_here: true,
      problem: "change-requests/2.md could not be read (plan_to is missing). Fix it in a hub PR.",
    });
    const decidedOther = aChangeRequest({
      n: 3,
      ticket: "AGH-201",
      affected: ["AGH-202"],
      status: "approved",
      approval_id: null,
    });
    showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: aTicketRecords({ change_requests: [unreadable, decidedOther] }),
    });

    expect(await within(panel()).findByText(/plan_to is missing/)).toBeInTheDocument();
    expect(within(panel()).queryByRole("group", { name: /^Decide/ })).toBeNull();
    expect(within(panel()).queryByText(/Held by/)).toBeNull();
  });

  it("AC-2.14 a decided request reads who decided it, with the note", async () => {
    const decided = aChangeRequest({
      status: "declined",
      approval_id: null,
      decision: {
        decision: "declined",
        decided_by: "Dana Owner",
        decided_at: "2026-10-21",
        note: "Keep the contract",
      },
    });
    showTab(tickets({ "AGH-202": STALE }), path, {
      [RECORDS]: aTicketRecords({ change_requests: [decided] }),
    });

    expect(
      await within(panel()).findByText(
        "Change request 2 declined by Dana Owner · 2026-10-21: Keep the contract",
      ),
    ).toBeInTheDocument();
    expect(within(panel()).queryByRole("group", { name: /^Decide/ })).toBeNull();
  });
});

describe("Ticket panel states (U1, U4)", () => {
  const path = "/?doc=tickets&ticket=AGH-202&step=preflight";

  it("U1 shows a skeleton while the ticket's records load, not Not reached", async () => {
    showTab(tickets({ "AGH-202": ASKING }), path, { [RECORDS]: "pending" });

    const preflight = within(panel()).getByRole("button", { name: /^Preflight, waiting for you/ });
    expect(preflight).toHaveAttribute("aria-expanded", "true");
    expect(panel()).not.toHaveTextContent("Not reached.");
    await vi.waitFor(() => {
      expect(panel().querySelector(".ah-golden-detail .ah-skel")).not.toBeNull();
    });
  });

  it("U1 says why the records failed, with Retry", async () => {
    showTab(tickets({ "AGH-202": ASKING }), path, {
      [RECORDS]: new ProblemReply({
        type: "about:blank",
        status: 500,
        title: "Server error",
        detail: "boom",
      }),
    });

    expect(
      await within(panel()).findByText("Could not load this ticket's records"),
    ).toBeInTheDocument();
    expect(within(panel()).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("U1 falls back to the step's meta when the ticket has no records", async () => {
    showTab(tickets({ "AGH-202": STALE }), path, { [RECORDS]: aTicketRecords() });

    await vi.waitFor(() => {
      expect(panel().querySelector(".ah-golden-detail")).toHaveTextContent(
        "Plan v3 approved: re-run preflight",
      );
    });
    expect(panel()).not.toHaveTextContent("Not reached.");
  });

  it("U4 the held line opens the asking ticket's panel at Preflight", async () => {
    const { router } = showTab(
      tickets({ "AGH-203": HELD }),
      "/?doc=tickets&ticket=AGH-203&step=preflight",
      {
        [`${API}/tickets/AGH-203`]: aTicketRecords({
          ticket: "AGH-203",
          change_requests: [aChangeRequest()],
        }),
      },
    );

    await userEvent.click(
      await screen.findByRole("link", { name: "change request 2 from AGH-202" }),
    );

    expect(router.state.location.search).toBe("?doc=tickets&ticket=AGH-202&step=preflight");
  });
});

describe("belowHeading (Q17)", () => {
  it("shifts only headings outside fences, the fence closed by its own marker", () => {
    const source = [
      "## Evidence",
      "```bash",
      "# install",
      "~~~",
      "# still code",
      "```",
      "# Proposal",
    ].join("\n");

    expect(belowHeading(source, 5).split("\n")).toEqual([
      "###### Evidence",
      "```bash",
      "# install",
      "~~~",
      "# still code",
      "```",
      "##### Proposal",
    ]);
  });

  it("shifts a heading indented by up to three spaces", () => {
    expect(belowHeading("   ## Evidence", 5)).toBe("   ##### Evidence");
  });
});
