/* The playground delivery's feature-page ACs (AGH-314): sign-off refusal, eval card, tickets
   table widths, nickname header, expanded AC card and its check's split button. */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  aBrainNote,
  aCapabilities,
  aFeatureDetail,
  aFeatureRecord,
  aFeatureTickets,
  aGoldenPath,
  aGoldenStep,
  aPage,
  aProblem,
  aWorkdir,
  anEvalRecord,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { EvalTab } from "./EvalTab";
import { FeatureDetailScreen } from "./index";
import { TicketsTab } from "./TicketsTab";

const API = "/api/v1/features/agent-hub/layered-memory";
const NOTE = "/api/v1/projects/agent-hub/brain/note";
const AGENT = "/api/v1/agent-sessions";
const route = "features/:project/:slug";
const PAGE = "/features/agent-hub/layered-memory";

const detail = aFeatureDetail({
  slug: "layered-memory",
  phase: "evaluate",
  verdict: "SHIP-WITH-OWNER-STEPS",
  issues: ["AGH-48"],
  golden_path: aGoldenPath({
    phase: "evaluate",
    steps: [
      aGoldenStep({ name: "spec", state: "done", meta: null, progress: null }),
      aGoldenStep({
        name: "evaluate",
        state: "partial",
        meta: "waiting: owner steps",
        reason: "1 AC waits on owner steps (SHIP-WITH-OWNER-STEPS)",
        progress: null,
      }),
    ],
  }),
  evals: [anEvalRecord({ delivery: "agh-48", path: "features/layered-memory/evals/agh-48.md" })],
  acs: { owner_steps: 1, passing: 1, total: 2 },
  ac_rows: [
    {
      id: "AC-48.1",
      description: "Given a session, when it starts, then the memory loads",
      repo: "agent-hub",
      passes: true,
      manual: false,
      signed_off: false,
      evidence: "test run 1",
      command: "uv run pytest -k case_1",
    },
    {
      id: "AC-48.2",
      description: "Given the feature is merged, when the owner opens a session, then it works",
      repo: "agent-hub",
      passes: false,
      manual: true,
      signed_off: false,
      evidence: "eval.md §Owner steps",
      command: "manual: open a session in the hub",
    },
  ],
  records: (["spec", "research", "plan", "eval", "issues"] as const).map((name) =>
    aFeatureRecord({ name, path: `features/layered-memory/${name}.md`, present: false }),
  ),
});

const driving: ApiRoutes = {
  [`${AGENT}/capabilities`]: aCapabilities(),
  [`${AGENT}/workdirs`]: {
    items: [aWorkdir(), aWorkdir({ kind: "repo", label: "agent-hub", repo: "agent-hub" })],
    warnings: [],
  },
};

const passedRun: ApiRoutes = {
  [`POST ${API}/acs/AC-48.1/check-runs`]: {
    ac: "AC-48.1",
    command: "uv run pytest -k case_1",
    repo: "agent-hub",
    branch: "roquettejh/agh-48-memory",
    commit: "0f4d1f7",
    exit_code: 0,
    passed: true,
    timed_out: false,
    duration_ms: 1200,
    output: "4 passed in 0.4s\n",
    truncated: false,
  },
};

function open(extra: ApiRoutes = {}, path = `${PAGE}?doc=acs`) {
  return renderWithApi(<FeatureDetailScreen />, {
    routes: { [API]: detail, [NOTE]: aBrainNote(), ...driving, ...extra },
    path,
    route,
  });
}

async function expand(id: string) {
  const table = await screen.findByRole("table", { name: "Acceptance criteria" });
  await userEvent.click(within(table).getByRole("button", { name: `Expand ${id}` }));
  return within(table).getByRole("region", { name: "Check it yourself" });
}

async function runInTerminal(check: HTMLElement) {
  await userEvent.click(within(check).getByRole("button", { name: "Choose how to run the check" }));
  await userEvent.click(within(check).getByRole("button", { name: /^Run in terminal/ }));
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("owner sign-off on the feature page", () => {
  it("AC-PG-10.2 shows Could not sign off the owner steps with the 409 reason, in the banner above the tabs", async () => {
    const reason = "No AC waits on owner steps covered by a SHIP eval.";
    const view = open({
      [`POST ${API}/owner-signoff`]: aProblem({
        status: 409,
        title: "Conflict",
        detail: reason,
      }),
    });

    const banner = await screen.findByRole("region", { name: "Owner steps" });
    // AC-PG-31.2: the sign-off lives in the one "Waiting on you" banner, before the tabs.
    expect(banner).toHaveTextContent("Waiting on you");
    const tabs = screen.getByRole("tablist", { name: "Feature record" });
    expect(banner.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await userEvent.click(within(banner).getByRole("button", { name: "Mark owner steps done" }));
    await userEvent.click(within(banner).getByRole("button", { name: "Yes, I did them" }));

    const alert = await within(banner).findByRole("alert");
    expect(alert).toHaveTextContent("Could not sign off the owner steps");
    expect(alert).toHaveTextContent(reason);
    expect(
      view.requests.filter(
        (r) => r.method === "POST" && new URL(r.url).pathname === `${API}/owner-signoff`,
      ),
    ).toHaveLength(1);
  });
});

describe("the eval card", () => {
  const legacy = anEvalRecord({
    delivery: "legacy",
    path: "features/control-plane/eval.md",
    verdict: "SHIP",
    tickets: ["AGH-201"],
    acs: [],
    prs: ["agent-hub#80"],
    commit: "0a1b2c3d4e5f",
    evaluated_at: "2026-10-11",
    legacy: true,
  });
  const note = aBrainNote({
    path: legacy.path,
    frontmatter: {
      verdict: "SHIP",
      evaluated_ref: `agent-hub@${"0a1b2c3d4e5f6a7b8c9d".repeat(3)}`,
      toolchain: "python 3.14.0, uv 0.9.2, node 22.11.0, vitest 3.2.4, playwright 1.55.0",
    },
    markdown: "# Eval\n\nAll good.\n",
  });

  function show() {
    return renderWithApi(
      <EvalTab
        project="agent-hub"
        slug="control-plane"
        tickets={["AGH-201", "AGH-202"]}
        evals={[anEvalRecord({ delivery: "agh-202", tickets: ["AGH-202"] }), legacy]}
        selected={legacy}
        onSelect={() => undefined}
      />,
      { routes: { ...driving, [NOTE]: note } },
    );
  }

  it("AC-PG-15.2 leads with verdict, date, tickets, scope, PRs and commit, with no 0 ACs", async () => {
    show();

    const card = screen.getByRole("article", { name: "Eval legacy" });
    const head = card.firstElementChild as HTMLElement;
    expect(head.textContent).toMatch(/^SHIP.*Evaluated 2026-10-11.*AGH-201.*agent-hub#80.*0a1b2c3/);
    expect(within(card).queryByText(/0 ACs/)).toBeNull();
    await within(card).findByText("Details");
  });

  it("AC-PG-15.2 names a legacy eval eval.md once, not legacy", async () => {
    show();

    const card = screen.getByRole("article", { name: "Eval legacy" });
    const head = card.firstElementChild as HTMLElement;
    expect(within(head).getAllByText("eval.md")).toHaveLength(1);
    expect(head.textContent.match(/eval\.md/g)).toHaveLength(1);
    expect(within(head).queryByText("legacy")).toBeNull();
    await within(card).findByText("Details");
  });

  it("AC-PG-15.2 folds the path, frontmatter chips and long fields into a closed Details", async () => {
    show();

    const card = screen.getByRole("article", { name: "Eval legacy" });
    const details = (await within(card).findByText("Details")).closest("details");
    if (!details) throw new Error("no Details disclosure");
    expect(details).not.toHaveAttribute("open");
    const fold = within(details);
    expect(fold.getByTitle("brain/features/control-plane/eval.md")).toBeInTheDocument();
    expect(fold.getByRole("list", { name: "Frontmatter" })).toHaveTextContent("verdict: SHIP");
    const long = details.querySelector('dl[aria-label="Frontmatter, long fields"]');
    expect(long).toHaveTextContent("evaluated_ref");
    expect(long).toHaveTextContent("toolchain");
    // Nothing of the frontmatter reads outside the disclosure.
    const outside = [...card.querySelectorAll('[aria-label^="Frontmatter"]')].filter(
      (el) => !details.contains(el),
    );
    expect(outside).toEqual([]);
  });
});

describe("the tickets table", () => {
  it("AC-PG-21.1 sets the fixed column widths and keeps Title at least 280 px in a scrolling wrap", () => {
    renderWithApi(
      <TicketsTab
        project="agent-hub"
        slug="control-plane"
        data={aFeatureTickets()}
        error={null}
        onRefresh={() => undefined}
      />,
      { routes: { "/api/v1/sessions": aPage([]) } },
    );

    const table = screen.getByRole("table", { name: "Tickets" });
    const width = (name: string) => within(table).getByRole("columnheader", { name }).style.width;
    expect({
      Ticket: width("Ticket"),
      Status: width("Status"),
      ACs: width("ACs"),
      Sessions: width("Sessions"),
      Readiness: width("Readiness"),
    }).toEqual({
      Ticket: "110px",
      Status: "110px",
      ACs: "150px",
      Sessions: "150px",
      Readiness: "180px",
    });
    const title = within(table).getByRole("columnheader", { name: "Title" });
    expect(title).toHaveClass("ah-ticket-title-col");
    expect(title.style.width).toBe("");
    expect(table.parentElement).toHaveClass("ah-table-wrap");

    // jsdom does not load the CSS: the minimum and the sideways scroll are read from the sheets.
    const flow = readFileSync(
      join(process.cwd(), "src/screens/feature-detail/ticket-flow.css"),
      "utf8",
    );
    expect(flow).toMatch(/\.ah-ticket-table \.ah-ticket-title-col \{\s*min-width: 280px;/);
    const bundle = readFileSync(join(process.cwd(), "src/styles/bundle.css"), "utf8");
    expect(bundle).toMatch(/\.ah-table-wrap \{[^}]*overflow: auto;/);
  });
});

describe("the feature page header", () => {
  it("AC-PG-28.2 shows the nickname as the title with the slug beside it", async () => {
    open(
      {
        "/api/v1/feature-names": {
          items: [{ project: "agent-hub", slug: "layered-memory", name: "Layered memory" }],
        },
      },
      PAGE,
    );

    const title = await screen.findByRole("heading", { level: 1, name: "Layered memory" });
    expect(title).not.toHaveClass("ah-mono");
    const label = title.nextElementSibling;
    expect(label).toHaveAccessibleName("Feature label layered-memory");
    expect(label).toHaveTextContent(/^layered-memory$/);
  });

  it("AC-PG-28.2 reads the slug as the title, mono, when there is no nickname, and keeps the label", async () => {
    open({ "/api/v1/feature-names": { items: [] } }, PAGE);

    const title = await screen.findByRole("heading", { level: 1, name: "layered-memory" });
    expect(title).toHaveClass("ah-mono");
    expect(title.nextElementSibling).toHaveAccessibleName("Feature label layered-memory");
  });
});

describe("the expanded AC card", () => {
  it("AC-PG-37.2 spans the row, without a repeated header or Discuss", async () => {
    open();

    const table = await screen.findByRole("table", { name: "Acceptance criteria" });
    await userEvent.click(within(table).getByRole("button", { name: "Expand AC-48.1" }));
    const check = within(table).getByRole("region", { name: "Check it yourself" });
    const cell = check.closest("td");
    if (!cell) throw new Error("no detail cell");
    const columns = within(table).getAllByRole("columnheader").length;
    expect(cell).toHaveAttribute("colspan", String(columns));
    expect(cell.parentElement?.children).toHaveLength(1);

    const card = within(cell);
    expect(card.queryByRole("button", { name: /Discuss/ })).toBeNull();
    expect(card.queryByRole("link", { name: "AC-48.1" })).toBeNull();
    expect(card.queryByRole("heading", { name: /AC-48\.1/ })).toBeNull();
    // The row above keeps the id and Discuss, once.
    expect(
      within(table).getAllByRole("button", { name: "Discuss AC-48.1 with Claude" }),
    ).toHaveLength(1);
  });
});

describe("the AC check", () => {
  it("AC-PG-37.3 says the run is not recorded and names its branch and commit", async () => {
    open(passedRun);
    const check = await expand("AC-48.1");

    await runInTerminal(check);

    await within(check).findByText("Passed");
    expect(check).toHaveTextContent("on roquettejh/agh-48-memory @ 0f4d1f7");
    expect(check).toHaveTextContent("Not recorded. /evaluate records evidence.");
  });

  it("AC-PG-37.3 says before any click that the browser is locked", async () => {
    const view = open({
      [`${AGENT}/capabilities`]: aProblem({ status: 401, title: "Session cookie required" }),
    });
    const check = await expand("AC-48.1");

    expect(await within(check).findByText(/^Locked in this browser\./)).toBeInTheDocument();
    expect(
      within(check).getByRole("button", { name: /^Run with Claude\. Locked in this browser/ }),
    ).toBeDisabled();
    expect(view.requests.some((r) => r.method === "POST")).toBe(false);
  });

  it("AC-PG-37.3 announces its state in a live status region", async () => {
    open(passedRun);
    const check = await expand("AC-48.1");
    const status = within(check)
      .getAllByRole("status")
      .find((el) => el.getAttribute("aria-live") === "polite");
    if (!status) throw new Error("no live status");
    expect(status).toHaveTextContent("");

    await runInTerminal(check);

    await waitFor(() => {
      expect(status).toHaveTextContent("AC-48.1's check passed, 1.2 s.");
    });
  });

  it("AC-PG-37.3 keeps its result when the card collapses and reopens", async () => {
    open(passedRun);
    await runInTerminal(await expand("AC-48.1"));
    const table = screen.getByRole("table", { name: "Acceptance criteria" });
    await within(table).findByText("Passed");

    await userEvent.click(within(table).getByRole("button", { name: "Collapse AC-48.1" }));
    expect(within(table).queryByText("Passed")).toBeNull();
    await userEvent.click(within(table).getByRole("button", { name: "Expand AC-48.1" }));

    expect(within(table).getByText("Passed")).toBeInTheDocument();
    expect(table).toHaveTextContent("on roquettejh/agh-48-memory @ 0f4d1f7");
  });

  it("AC-PG-37.3 folds the output on a pass", async () => {
    open(passedRun);
    const check = await expand("AC-48.1");

    await runInTerminal(check);

    const output = await within(check).findByLabelText("Output of AC-48.1's check");
    const fold = output.closest("details");
    expect(fold).not.toHaveAttribute("open");
    expect(fold?.querySelector("summary")).toHaveTextContent("Output · 1 line");
  });

  it("AC-PG-37.4 runs with Claude by default, the arrow offers Run in terminal", async () => {
    open();
    const check = await expand("AC-48.1");

    const run = await within(check).findByRole("button", { name: "Run with Claude" });
    await waitFor(() => {
      expect(run).toBeEnabled();
    });
    await userEvent.click(
      within(check).getByRole("button", { name: "Choose how to run the check" }),
    );

    const menu = within(check).getByRole("dialog", { name: "How to run the check" });
    const claude = within(menu).getByRole("button", { name: /^Run with Claude/ });
    expect(claude).toHaveTextContent(/^Run with Claude · default/);
    expect(claude).toHaveAttribute("aria-current", "true");
    expect(within(menu).getByRole("button", { name: /^Run in terminal/ })).toBeVisible();
  });

  it("AC-PG-37.4 remembers the last choice after the page mounts again", async () => {
    const first = open(passedRun);
    await runInTerminal(await expand("AC-48.1"));
    await screen.findByText("Passed");
    first.unmount();

    open(passedRun);
    const check = await expand("AC-48.1");

    expect(within(check).getByRole("button", { name: "Run in terminal" })).toBeInTheDocument();
    expect(within(check).queryByRole("button", { name: "Run with Claude" })).toBeNull();
  });
});
