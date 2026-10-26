import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../../testing/axe";
import {
  aPage,
  aProblem,
  aScenarioAction,
  aScenarioDetail,
  aScenarioPlan,
  aScenarioPlanRow,
  aTreeDocument,
  renderWithApi,
  type ApiRoutes,
} from "../../../testing/builders";
import { ScenarioDetailScreen } from "..";

const PATH = "/scenarios/demo/order-lifecycle";
const DETAIL = "/api/v1/scenarios/demo/order-lifecycle";
const VALIDATE = "POST /api/v1/projects/demo/scenarios/validate";
const SAVE = `PUT ${DETAIL}`;
const ENV_EDIT = "POST /api/v1/projects/demo/config/environments";
const MIGRATE = `POST ${DETAIL}/migrate`;
// The reference scenario written as blocks, and its stages with how many blocks each holds.
const REFERENCE = "demo-order-roundtrip";
const STAGES: readonly (readonly [string, number])[] = [
  ["Fetch order", 2],
  ["Review", 2],
  ["Switch carrier", 5],
  ["Dispatch", 2],
  ["Invoice PDF", 1],
  ["Send invoice", 2],
  ["Approval", 4],
  ["Payment", 4],
];

const document = {
  version: 1,
  kind: "scenario",
  name: "order-lifecycle",
  revision: 1,
  inputs: { external_ref: { type: "string", required: true } },
  nodes: [
    { id: "fetch-order", type: "action", action: "send-queue-message" },
    {
      id: "order-on-hold",
      type: "expect",
      action: "get-order-by-ref",
      depends_on: ["fetch-order"],
      every: "10s",
      timeout: "5m",
      until_when: "$self.output.status == 'ON_HOLD'",
    },
  ],
};

const library = {
  items: [
    {
      action: aScenarioAction({
        ref: "orders/send-queue-message",
        name: "send-queue-message",
        effect: "write",
      }),
      output_fields: [],
      used_by: ["order-lifecycle"],
    },
    {
      action: aScenarioAction({ ref: "orders/get-order-by-ref", name: "get-order-by-ref" }),
      output_fields: [{ path: "status", type: "string" }],
      used_by: ["order-lifecycle"],
    },
  ],
  problems: [],
};

// A scenario written as blocks whose second block reads the first one's output under the id
// the first one's place gives it.
const REFERRING = {
  version: 2,
  kind: "scenario",
  name: "order-lifecycle",
  revision: 1,
  stages: [
    {
      name: "Fetch order",
      steps: [
        { do: "get-order-by-ref" },
        { do: "send-queue-message", with: { order_id: "$fetch-order--1.output.order_id" } },
      ],
    },
  ],
};

// What migrate gives for the graph scenario above, checked (nothing written).
const MIGRATION = {
  path: "scenarios/orders/order-lifecycle.yaml",
  written: false,
  yaml: "version: 2\nkind: scenario\nname: order-lifecycle\nrevision: 1\nstages:\n- name: order-lifecycle\n",
  content_hash: "sha256:aaa",
  problems: [],
};

const SAVED = {
  path: "scenarios/orders/order-lifecycle.yaml",
  revision: 2,
  content_hash: "sha256:bbb",
  yaml: "version: 1\n",
  changed: true,
  versioned: true,
};

// The rows of the step list, by kind and what they say ("Step 1, Run an action: Fetch order.").
const FETCH = /Run an action: Fetch order/;
const CHECK = /Wait until: Wait until status is ON_HOLD/;

function renderBuilder(extra: ApiRoutes = {}, path = PATH) {
  return renderWithApi(<ScenarioDetailScreen />, {
    routes: {
      [DETAIL]: aScenarioDetail({ document, content_hash: "sha256:aaa" }),
      "/api/v1/approvals": aPage([]),
      "/api/v1/workflow-runs": aPage([]),
      "/api/v1/projects/demo/actions": library,
      [VALIDATE]: () => ({ loads: true, yaml: "version: 1\n", problems: [], nodes: [] }),
      ...extra,
    },
    path,
    route: "/scenarios/:project/:name",
  });
}

/** The builder on a tree fixture (a scenario written as blocks, `version: 2`). */
function renderTree(name: string, extra: ApiRoutes = {}) {
  return renderBuilder({
    [DETAIL]: aScenarioDetail({
      document: aTreeDocument(name),
      content_hash: "sha256:aaa",
      version: 2,
    }),
    ...extra,
  });
}

/** A scenario whose step's action takes values from every source: the step itself, the
 * environment, the scenario run and the action's default. */
function renderSources(extra: ApiRoutes = {}) {
  return renderBuilder({
    [DETAIL]: aScenarioDetail({
      document: {
        ...document,
        inputs: {
          external_ref: { type: "string", required: true },
          aws_account_id: { type: "string", default: "000000000000" },
        },
        nodes: [
          {
            id: "fetch-order",
            type: "action",
            action: "send-queue-message",
            with: { queue: "demo-events" },
          },
        ],
      },
      content_hash: "sha256:aaa",
      environments: [
        {
          name: "personal",
          access: "write",
          production: false,
          values: { aws_account_id: "123456789012", region_hint: "eu" },
        },
        { name: "qa", access: "read", production: false, values: {} },
      ],
    }),
    "/api/v1/projects/demo/actions": {
      ...library,
      items: [
        {
          action: aScenarioAction({
            ref: "orders/send-queue-message",
            name: "send-queue-message",
            effect: "write",
            inputs: [
              { name: "queue", type: "string", required: true, description: "The queue" },
              { name: "external_ref", type: "string", required: true, description: null },
              { name: "aws_account_id", type: "string", required: true, description: null },
              {
                name: "aws_region",
                type: "string",
                required: false,
                description: null,
                default: "eu-west-1",
              },
            ],
          }),
          output_fields: [],
          used_by: [],
        },
      ],
    },
    ...extra,
  });
}

interface SentNode {
  id: string;
  depends_on?: string[];
  capture_response?: boolean;
}

async function savedNodes(requests: Request[]): Promise<SentNode[]> {
  const sent = requests.find((request) => request.method === "PUT");
  const body = (await sent?.clone().json()) as {
    base_content_hash: string;
    document: { nodes: SentNode[] };
  };
  expect(body.base_content_hash).toBe("sha256:aaa");
  return body.document.nodes;
}

async function savedDocument(requests: Request[]): Promise<unknown> {
  const sent = requests.find((request) => request.method === "PUT");
  const body = (await sent?.clone().json()) as { base_content_hash: string; document: unknown };
  expect(body.base_content_hash).toBe("sha256:aaa");
  return body.document;
}

async function save(user: ReturnType<typeof userEvent.setup>) {
  const button = screen.getByRole("button", { name: "Save scenario" });
  await waitFor(() => {
    expect(button).toBeEnabled();
  });
  await user.click(button);
  await screen.findByText("Saved · rev 2");
}

/** Opens the insert menu from a "+" (or "Add step") and picks a step type. */
async function insertStep(
  user: ReturnType<typeof userEvent.setup>,
  opener: string,
  stepType: RegExp,
) {
  await user.click(await screen.findByRole("button", { name: opener }));
  const menu = screen.getByRole("dialog", { name: opener });
  await user.click(within(menu).getByRole("option", { name: stepType }));
}

/** The last indented group of the step list (the one just added). */
function lastGroup(): HTMLElement {
  const group = screen.getAllByRole("group").at(-1);
  if (!group) throw new Error("no group in the step list");
  return group;
}

describe("ScenarioBuilder (scenario builder)", () => {
  // Each test starts with no draft kept in this browser.
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("scenario builder reads the scenario as numbered steps that say what they do", async () => {
    renderBuilder();

    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const check = await within(tree).findByRole("treeitem", { name: CHECK });
    expect(check).toHaveAccessibleName(/^Step 2, Wait until: Wait until status is ON_HOLD\./);
    expect(check).toHaveTextContent("get-order-by-ref");
    expect(check).toHaveTextContent("every 10 s, up to 5 min");
    const fetch = within(tree).getByRole("treeitem", { name: FETCH });
    expect(fetch).toHaveAttribute("aria-level", "1");
    await waitFor(() => {
      expect(fetch).toHaveTextContent("Changes data");
    });
    expect(fetch).toHaveTextContent("send-queue-message");
    expect(check).toHaveTextContent("Reads only");
    expect(await screen.findByText("Loads")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save scenario" })).toBeDisabled();
  });

  it("scenario builder opens the reference scenario written as blocks with every block in its stage, in file order", async () => {
    const user = userEvent.setup();
    const { requests } = renderTree(REFERENCE, { [SAVE]: () => SAVED });

    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const stages = within(tree).getAllByRole("treeitem", { name: /^Stage / });
    expect(stages.map((row) => row.getAttribute("aria-label"))).toEqual(
      STAGES.map(([name, count], index) =>
        `Stage ${String(index + 1)}: ${name}, ${String(count)} steps.`.replace(
          ", 1 steps.",
          ", 1 step.",
        ),
      ),
    );
    // Each stage holds its blocks, in the file's order, numbered by their address.
    for (const [index, [name, count]] of STAGES.entries()) {
      const stage = String(index + 1);
      const group = screen.getByRole("group", { name: `Stage ${stage}: ${name}` });
      expect(
        within(group)
          .getAllByRole("treeitem")
          .map((row) => row.getAttribute("aria-label")?.split(",")[0]),
      ).toEqual(Array.from({ length: count }, (_, n) => `Step ${stage}.${String(n + 1)}`));
    }
    expect(
      within(tree).getByRole("treeitem", { name: /^Step 1\.2, Wait until/ }),
    ).toHaveTextContent("every 15 s, up to 10 min");
    // No block is left out of the stages.
    expect(
      screen.queryByRole("region", { name: "Steps not in the order" }),
    ).not.toBeInTheDocument();
    // The check reads the very document the server parsed: opening rewrites nothing.
    expect(await screen.findByText("Loads")).toBeInTheDocument();
    const checked = requests.find((request) => request.url.endsWith("/scenarios/validate"));
    expect(((await checked?.clone().json()) as { document: unknown }).document).toStrictEqual(
      aTreeDocument(REFERENCE),
    );
    const saveButton = screen.getByRole("button", { name: "Save scenario" });
    expect(saveButton).toBeDisabled();

    // A block moved down and back up writes the same document again: nothing to save.
    await user.click(within(tree).getByRole("treeitem", { name: /^Step 3\.2,/ }));
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: /^Step 3\.3, Run an action/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    await waitFor(() => {
      expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
    });
    expect(saveButton).toBeDisabled();

    // One change is the only change Save sends.
    await user.click(within(tree).getByRole("treeitem", { name: /^Step 1\.2,/ }));
    const editor = screen.getByRole("region", { name: "Inspector: Wait until fetch-order--2" });
    const field = within(editor).getByLabelText("Give up after");
    await user.clear(field);
    await user.type(field, "20m");
    await save(user);
    const expected = aTreeDocument(REFERENCE) as { stages: { steps: Record<string, unknown>[] }[] };
    const changed = expected.stages[0]?.steps[1];
    if (changed) changed.timeout = "20m";
    expect(await savedDocument(requests)).toStrictEqual(expected);
  });

  it("scenario builder has no serious a11y violation on a scenario written as blocks (a11y)", async () => {
    const { container } = renderTree(REFERENCE);
    await screen.findByRole("treeitem", { name: /^Stage 8: Payment/ });

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("scenario builder has no serious a11y violation on nested blocks and an empty stage (a11y)", async () => {
    const user = userEvent.setup();
    const { container } = renderTree("blocks-nested");
    await screen.findByRole("treeitem", { name: /^Stage 1: Route order/ });
    const blocks = screen.getByRole("complementary", { name: "Blocks, variables and actions" });
    await user.click(within(blocks).getByRole("button", { name: "Add Stage at the end" }));
    await screen.findByRole("treeitem", { name: /^Stage 2: Stage 2, 0 steps/ });

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("scenario builder has no serious a11y violation on a block's editor with its id open, or on Claude's proposal under review (a11y)", async () => {
    const user = userEvent.setup();
    const proposed = aTreeDocument("blocks-together") as { stages: { steps: unknown[] }[] };
    proposed.stages[0]?.steps.unshift({ you: "Check the shipment by hand, then approve." });
    const { container } = renderTree("blocks-together", {
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
    });

    await user.click(await screen.findByRole("treeitem", { name: /^Step 1\.3,/ }));
    const editor = screen.getByRole("region", { name: /^Inspector: Run an action / });
    await user.click(within(editor).getByRole("button", { name: "More: id" }));
    expect(within(editor).getByLabelText("Id")).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Review" }));
    expect(screen.getByRole("region", { name: "Claude's proposal" })).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("scenario builder adds a stage from the Blocks tab, renames, fills, moves and removes it", async () => {
    const user = userEvent.setup();
    const { requests } = renderTree("blocks-together", { [SAVE]: () => SAVED });

    await screen.findByRole("treeitem", { name: /^Stage 1: Fix shipping/ });
    const blocks = screen.getByRole("complementary", { name: "Blocks, variables and actions" });
    await user.click(within(blocks).getByRole("button", { name: "Add Stage at the end" }));
    const added = await screen.findByRole("treeitem", { name: /^Stage 2: Stage 2, 0 steps/ });
    expect(added).toHaveAttribute("aria-selected", "true");

    // Its editor renames it; a step goes into it from its empty slot.
    const editor = screen.getByRole("region", { name: "Inspector: Stage 2" });
    const nameField = within(editor).getByLabelText("Name");
    await user.clear(nameField);
    // A stage with no name is read out as it shows.
    expect(screen.getByRole("treeitem", { name: /^Stage 2:/ })).toHaveAttribute(
      "aria-label",
      "Stage 2: A stage with no name, 0 steps.",
    );
    await user.type(nameField, "Ship");
    const stage = screen.getByRole("group", { name: "Stage 2: Ship" });
    await user.click(within(stage).getByRole("button", { name: /Empty. Add a step here/ }));
    await user.click(
      within(screen.getByRole("dialog", { name: "Add a step here" })).getByRole("option", {
        name: /^Pause/,
      }),
    );
    expect(
      await within(stage).findByRole("treeitem", { name: /^Step 2\.1, Pause/ }),
    ).toBeInTheDocument();

    // Moved before the first stage from its row menu.
    await user.click(screen.getByRole("button", { name: "Move stage 2" }));
    await user.click(
      within(screen.getByRole("menu", { name: "Stage 2" })).getByRole("button", {
        name: "Move up",
      }),
    );
    expect(
      screen
        .getAllByRole("treeitem", { name: /^Stage / })
        .map((row) => row.getAttribute("aria-label")),
    ).toEqual(["Stage 1: Ship, 1 step.", "Stage 2: Fix shipping, 3 steps."]);

    // Its editor removes it, with what it holds, and Undo brings it back.
    await user.click(screen.getByRole("treeitem", { name: /^Stage 1: Ship/ }));
    expect(screen.getByRole("region", { name: "Inspector: Stage 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete the stage and its steps" }));
    expect(screen.queryByRole("treeitem", { name: /^Stage 1: Ship/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("treeitem", { name: /^Stage 1: Ship/ })).toBeInTheDocument();
    // The Delete key removes it too, and says so as the editor's button does.
    await user.click(screen.getByRole("treeitem", { name: /^Stage 1: Ship/ }));
    await user.keyboard("{Delete}");
    expect(screen.queryByRole("treeitem", { name: /^Stage 1: Ship/ })).not.toBeInTheDocument();
    expect(screen.getByText("Deleted stage 1 and its steps.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("treeitem", { name: /^Stage 1: Ship/ })).toBeInTheDocument();

    // Save sends the stages as the list holds them: the new one first, its step with no id.
    await save(user);
    const sent = (await savedDocument(requests)) as { stages: unknown[] };
    const fixture = aTreeDocument("blocks-together") as { stages: unknown[] };
    expect(sent.stages).toStrictEqual([
      { name: "Ship", steps: [{ wait: { duration: "30s" } }] },
      ...fixture.stages,
    ]);
  });

  it("scenario builder's editor of a block written as blocks sets no order, and its id only when given", async () => {
    const user = userEvent.setup();
    const { requests } = renderTree(REFERENCE, { [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("treeitem", { name: /^Step 1\.1,/ }));
    const editor = screen.getByRole("region", { name: "Inspector: Run an action fetch-order--1" });
    await user.click(within(editor).getByRole("button", { name: "More: id" }));
    // Position is order: no "runs after", no "only if", no join to choose.
    expect(within(editor).queryByText("Runs after")).not.toBeInTheDocument();
    expect(within(editor).queryByText("Runs when")).not.toBeInTheDocument();
    expect(within(editor).queryByText("Only if")).not.toBeInTheDocument();
    const id = within(editor).getByLabelText("Id");
    expect(id).toHaveValue("");
    expect(id).toHaveAttribute("placeholder", "fetch-order--1");

    await user.type(id, "fetch");
    await user.tab();
    expect(
      await screen.findByRole("region", { name: "Inspector: Run an action fetch" }),
    ).toBeInTheDocument();
    await save(user);
    const sent = (await savedDocument(requests)) as { stages: { steps: { id?: string }[] }[] };
    expect(sent.stages[0]?.steps.map((step) => step.id ?? null)).toEqual(["fetch", null]);
  });

  it("scenario builder's editor of a block written as blocks refuses the id self, which reads a block's own output", async () => {
    const user = userEvent.setup();
    renderTree(REFERENCE, { [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("treeitem", { name: /^Step 1\.1,/ }));
    const editor = screen.getByRole("region", { name: "Inspector: Run an action fetch-order--1" });
    await user.click(within(editor).getByRole("button", { name: "More: id" }));
    const id = within(editor).getByLabelText("Id");
    await user.type(id, "self");
    await user.tab();

    expect(id).toHaveValue("");
    expect(
      screen.getByRole("region", { name: "Inspector: Run an action fetch-order--1" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
  });

  it("scenario builder writes the id a block's place gives when it is given as its own, and keeps it when a block goes before it", async () => {
    const user = userEvent.setup();
    // The check as the server makes it: a block put at the pinned block's old place runs under
    // the same id until one of them has another.
    let shared = false;
    const { requests } = renderTree(REFERENCE, {
      [SAVE]: () => SAVED,
      [VALIDATE]: () => ({
        loads: !shared,
        yaml: "",
        problems: shared
          ? [
              {
                node: "fetch-order--2",
                key: "stages[0].steps[2].id",
                line: null,
                message: "the id fetch-order--2 is also block 1.2's",
                severity: "error",
              },
            ]
          : [],
        nodes: [],
      }),
    });

    await user.click(await screen.findByRole("treeitem", { name: /^Step 1\.2,/ }));
    const editor = screen.getByRole("region", { name: "Inspector: Wait until fetch-order--2" });
    await user.click(within(editor).getByRole("button", { name: "More: id" }));
    const id = within(editor).getByLabelText("Id");
    expect(id).toHaveValue("");
    // The id its place gives, typed as its own: it is the block's id now, written in the file.
    await user.type(id, "fetch-order--2");
    await user.tab();
    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    expect(id).toHaveValue("fetch-order--2");
    // A Pause put before it: the block is 1.3 and runs under the id it was given.
    await user.click(screen.getByRole("treeitem", { name: /^Step 1\.1,/ }));
    const blocks = screen.getByRole("complementary", { name: "Blocks, variables and actions" });
    shared = true;
    await user.click(within(blocks).getByRole("button", { name: "Add Pause after step 1.1" }));
    await user.click(await screen.findByRole("treeitem", { name: /^Step 1\.3, Wait until/ }));
    const moved = screen.getByRole("region", { name: "Inspector: Wait until fetch-order--2" });
    await user.click(within(moved).getByRole("button", { name: "More: id" }));
    expect(within(moved).getByLabelText("Id")).toHaveValue("fetch-order--2");
    // The Pause now at 1.2 runs under that id too: the check names it, and Save stays off.
    expect(await screen.findByText("1 problem")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save scenario" })).toBeDisabled();

    // The Pause given an id of its own: nothing is shared, and the file can be saved.
    await user.click(screen.getByRole("treeitem", { name: /^Step 1\.2,/ }));
    const pause = screen.getByRole("region", { name: /^Inspector: .* fetch-order--2$/ });
    await user.click(within(pause).getByRole("button", { name: "More: id" }));
    await user.type(within(pause).getByLabelText("Id"), "pause");
    shared = false;
    await user.tab();
    await save(user);
    const sent = (await savedDocument(requests)) as { stages: { steps: unknown[] }[] };
    const [fetch, pinned] = (aTreeDocument(REFERENCE) as { stages: { steps: object[] }[] })
      .stages[0]?.steps ?? [{}, {}];
    expect(sent.stages[0]?.steps).toStrictEqual([
      fetch,
      { wait: { duration: "30s" }, id: "pause" },
      { ...pinned, id: "fetch-order--2" },
    ]);
  });

  it("scenario builder rewrites what reads a block written as blocks when its own id is renamed", async () => {
    const user = userEvent.setup();
    const { requests } = renderTree("blocks-repeat", { [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("treeitem", { name: /^Step 1\.2\.2,/ }));
    const editor = screen.getByRole("region", { name: "Inspector: Wait until poll" });
    await user.click(within(editor).getByRole("button", { name: "More: id" }));
    const id = within(editor).getByLabelText("Id");
    expect(id).toHaveValue("poll");
    await user.clear(id);
    await user.type(id, "review-poll");
    await user.tab();
    expect(
      await screen.findByRole("region", { name: "Inspector: Wait until review-poll" }),
    ).toBeInTheDocument();

    await save(user);
    const sent = (await savedDocument(requests)) as {
      stages: { steps: { repeat?: { until: string; steps: { id?: string }[] } }[] }[];
    };
    const repeat = sent.stages[0]?.steps[1]?.repeat;
    expect(repeat?.until).toBe("$review-poll.output.review_status == 'APPROVED'");
    expect(repeat?.steps.map((step) => step.id ?? null)).toEqual([null, "review-poll"]);
  });

  it("scenario builder keeps a reference on the block it reads when a block goes before it and its stage is renamed", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      [DETAIL]: aScenarioDetail({ document: REFERRING, content_hash: "sha256:aaa", version: 2 }),
      [SAVE]: () => SAVED,
    });

    // A Pause added after block 1.1, then moved above it: the block read is now 1.2.
    await user.click(await screen.findByRole("treeitem", { name: /^Step 1\.1,/ }));
    const blocks = screen.getByRole("complementary", { name: "Blocks, variables and actions" });
    await user.click(within(blocks).getByRole("button", { name: "Add Pause after step 1.1" }));
    expect(await screen.findByRole("treeitem", { name: /^Step 1\.2, Pause/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(await screen.findByRole("treeitem", { name: /^Step 1\.1, Pause/ })).toBeInTheDocument();
    // The stage renamed, letter by letter.
    await user.click(screen.getByRole("treeitem", { name: /^Stage 1: Fetch order/ }));
    const nameField = within(
      screen.getByRole("region", { name: "Inspector: Stage 1" }),
    ).getByLabelText("Name");
    await user.clear(nameField);
    await user.type(nameField, "Get order");

    await save(user);
    const sent = (await savedDocument(requests)) as { stages: unknown[] };
    expect(sent.stages).toStrictEqual([
      {
        name: "Get order",
        steps: [
          { wait: { duration: "30s" } },
          { do: "get-order-by-ref" },
          { do: "send-queue-message", with: { order_id: "$get-order--2.output.order_id" } },
        ],
      },
    ]);
  });

  it("scenario builder keeps each reference on the block it reads when a block's id is renamed into another block's and out again", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: {
          ...REFERRING,
          stages: [
            {
              name: "Ship",
              steps: [
                { do: "get-order-by-ref", id: "fetch" },
                { do: "send-queue-message" },
                { do: "get-order-by-ref", with: { order_id: "$fetch.output.order_id" } },
                { do: "send-queue-message", with: { status: "$ship--3.output.status" } },
              ],
            },
          ],
        },
        content_hash: "sha256:aaa",
        version: 2,
      }),
      [SAVE]: () => SAVED,
    });

    await user.click(await screen.findByRole("treeitem", { name: /^Step 1\.2,/ }));
    await user.click(
      within(screen.getByRole("region", { name: "Inspector: Run an action ship--2" })).getByRole(
        "button",
        { name: "More: id" },
      ),
    );
    // Block 1.2 given the id block 1.1 has, then the id block 1.3's place gives, each fixed after.
    for (const [from, to] of [
      ["ship--2", "fetch"],
      ["fetch", "fetch-2"],
      ["fetch-2", "ship--3"],
      ["ship--3", "ship-two"],
    ] as const) {
      const editor = screen.getByRole("region", { name: `Inspector: Run an action ${from}` });
      const id = within(editor).getByLabelText("Id");
      await user.clear(id);
      await user.type(id, to);
      await user.tab();
      expect(
        await screen.findByRole("region", { name: `Inspector: Run an action ${to}` }),
      ).toBeInTheDocument();
    }

    await save(user);
    const sent = (await savedDocument(requests)) as { stages: unknown[] };
    expect(sent.stages).toStrictEqual([
      {
        name: "Ship",
        steps: [
          { do: "get-order-by-ref", id: "fetch" },
          { do: "send-queue-message", id: "ship-two" },
          { do: "get-order-by-ref", with: { order_id: "$fetch.output.order_id" } },
          { do: "send-queue-message", with: { status: "$ship--3.output.status" } },
        ],
      },
    ]);
  });

  it("scenario builder keeps a reference on its block when the block's stage is renamed through another stage's name", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: {
          ...REFERRING,
          stages: [
            { name: "Order", steps: [{ do: "get-order-by-ref" }] },
            {
              name: "Pay",
              steps: [
                { do: "get-order-by-ref" },
                {
                  do: "send-queue-message",
                  with: { order_id: "$pay--1.output.order_id", status: "$order--1.output.status" },
                },
              ],
            },
          ],
        },
        content_hash: "sha256:aaa",
        version: 2,
      }),
      [SAVE]: () => SAVED,
    });

    // Typed letter by letter, the name passes through "Order", the first stage's: two blocks
    // then run as order--1 for a moment.
    await user.click(await screen.findByRole("treeitem", { name: /^Stage 2: Pay/ }));
    const nameField = within(
      screen.getByRole("region", { name: "Inspector: Stage 2" }),
    ).getByLabelText("Name");
    await user.clear(nameField);
    await user.type(nameField, "Order pay");

    await save(user);
    const sent = (await savedDocument(requests)) as { stages: unknown[] };
    expect(sent.stages).toStrictEqual([
      { name: "Order", steps: [{ do: "get-order-by-ref" }] },
      {
        name: "Order pay",
        steps: [
          { do: "get-order-by-ref" },
          {
            do: "send-queue-message",
            with: {
              order_id: "$order-pay--1.output.order_id",
              status: "$order--1.output.status",
            },
          },
        ],
      },
    ]);
  });

  it("scenario builder's Graph view of a scenario written as blocks is a picture with nothing to add", async () => {
    const user = userEvent.setup();
    renderTree("blocks-together");

    await screen.findByRole("treeitem", { name: /^Stage 1: Fix shipping/ });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    expect(
      await screen.findByText("The graph shows how the blocks run: edit them in Blocks."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Add a block/ })).not.toBeInTheDocument();
  });

  it("scenario builder shows Claude's proposal for a scenario written as blocks by block address", async () => {
    const user = userEvent.setup();
    const proposed = aTreeDocument("blocks-together") as {
      stages: { steps: Record<string, unknown>[] }[];
    };
    proposed.stages[0]?.steps.push({ you: "Check the shipment by hand, then approve." });
    const { requests } = renderTree("blocks-together", {
      [SAVE]: () => SAVED,
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
      [`POST ${DETAIL}/proposal/dismiss`]: {},
    });

    const proposes = await screen.findByText("Claude proposes");
    expect(proposes.parentElement).toHaveTextContent(/Claude proposes 1 new or changed block/);
    await user.click(screen.getByRole("button", { name: "Review" }));
    const added = screen.getByRole("treeitem", { name: /^Step 1\.4, Ask me/ });
    expect(added).toHaveAttribute("data-suggested", "true");
    expect(screen.getByRole("treeitem", { name: /^Step 1\.3,/ })).not.toHaveAttribute(
      "data-suggested",
    );
    const review = screen.getByRole("region", { name: "Claude's proposal" });
    await user.click(within(review).getByRole("button", { name: "Accept new block 1.4" }));

    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: /^Step 1\.4, Ask me/ })).not.toHaveAttribute(
      "data-suggested",
    );
    // The accepted block is the stage's fourth, and the only change Save sends.
    expect(
      within(screen.getByRole("group", { name: "Stage 1: Fix shipping" }))
        .getAllByRole("treeitem")
        .map((row) => row.getAttribute("aria-label")?.split(",")[0]),
    ).toEqual([
      "Step 1.1",
      "Step 1.2",
      "Step 1.2.p1.1",
      "Step 1.2.p2.1",
      "Step 1.2.p2.2",
      "Step 1.3",
      "Step 1.4",
    ]);
    await save(user);
    expect(await savedDocument(requests)).toStrictEqual(proposed);
  });

  it("scenario builder's Accept all takes the stages of Claude's proposal for a scenario written as blocks", async () => {
    const user = userEvent.setup();
    const proposed = aTreeDocument("blocks-together") as {
      stages: { name: string; steps: unknown[] }[];
      inputs: Record<string, unknown>;
    };
    proposed.stages[0]?.steps.shift();
    proposed.stages.push({ name: "Ship", steps: [{ wait: { duration: "30s" } }] });
    proposed.inputs = { ...proposed.inputs, carrier: { default: "ground" } };
    const { requests } = renderTree("blocks-together", {
      [SAVE]: () => SAVED,
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
      [`POST ${DETAIL}/proposal/dismiss`]: {},
    });

    // The new stage counts as a stage, not as one of the blocks.
    const proposes = await screen.findByText("Claude proposes");
    expect(proposes.parentElement).toHaveTextContent(
      /Claude proposes 1 new or changed stage, 1 removed, changed inputs/,
    );
    await user.click(screen.getByRole("button", { name: "Accept all" }));

    expect(await screen.findByRole("treeitem", { name: /^Stage 2: Ship/ })).toBeInTheDocument();
    await save(user);
    expect(await savedDocument(requests)).toStrictEqual(proposed);
  });

  it("scenario builder takes or leaves each of two alike blocks Claude's proposal removes, in one stage and across stages", async () => {
    const user = userEvent.setup();
    // The proposal drops the two alike `queue-send demo.poll` blocks of Approval (7.1 and 7.3)
    // and the same block in Payment (8.3).
    const dropped = (stage: number, ...at: number[]) => {
      const changed = aTreeDocument(REFERENCE) as { stages: { steps: unknown[] }[] };
      for (const index of at) changed.stages[stage]?.steps.splice(index, 1);
      return changed;
    };
    const proposed = dropped(6, 2, 0);
    proposed.stages[7]?.steps.splice(2, 1);
    const { requests } = renderTree(REFERENCE, {
      [SAVE]: () => SAVED,
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
      [`POST ${DETAIL}/proposal/dismiss`]: {},
    });

    await screen.findByText("Claude proposes");
    await user.click(screen.getByRole("button", { name: "Review" }));
    const review = screen.getByRole("region", { name: "Claude's proposal" });
    const listed = () =>
      within(review)
        .getAllByRole("button", { name: /^Accept / })
        .map((button) => button.getAttribute("aria-label"));
    expect(listed()).toEqual([
      "Accept removed block 7.1",
      "Accept removed block 7.3",
      "Accept removed block 8.3",
    ]);

    // One taken: only that block goes, and its twin is still to decide, named as the review
    // listed it when it opened (its address in the draft then).
    await user.click(within(review).getByRole("button", { name: "Accept removed block 7.1" }));
    await waitFor(() => {
      expect(listed()).toEqual(["Accept removed block 7.3", "Accept removed block 8.3"]);
    });
    // One left as it is: the other is still to decide.
    await user.click(within(review).getByRole("button", { name: "Reject removed block 7.3" }));
    expect(listed()).toEqual(["Accept removed block 8.3"]);
    await user.click(within(review).getByRole("button", { name: "Accept removed block 8.3" }));

    // Every change decided: the review closes and the proposal is dismissed.
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Claude's proposal" })).not.toBeInTheDocument();
    });
    expect(requests.some((request) => request.url.endsWith("/proposal/dismiss"))).toBe(true);
    await save(user);
    const expected = dropped(6, 0);
    expected.stages[7]?.steps.splice(2, 1);
    expect(await savedDocument(requests)).toStrictEqual(expected);
  });

  it("scenario builder keeps the other of two alike blocks Claude's proposal adds to decide when the later one is accepted first", async () => {
    const user = userEvent.setup();
    const proposed = aTreeDocument("blocks-together") as { stages: { steps: unknown[] }[] };
    proposed.stages[0]?.steps.push({ wait: { duration: "30s" } }, { wait: { duration: "30s" } });
    const { requests } = renderTree("blocks-together", {
      [SAVE]: () => SAVED,
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
      [`POST ${DETAIL}/proposal/dismiss`]: {},
    });

    await screen.findByText("Claude proposes");
    await user.click(screen.getByRole("button", { name: "Review" }));
    const review = screen.getByRole("region", { name: "Claude's proposal" });
    const listed = () =>
      within(review)
        .getAllByRole("button", { name: /^Accept / })
        .map((button) => button.getAttribute("aria-label"));
    expect(listed()).toEqual(["Accept new block 1.4", "Accept new block 1.5"]);

    // The later one taken: the earlier one is still to decide, and the review stays open.
    await user.click(within(review).getByRole("button", { name: "Accept new block 1.5" }));
    await waitFor(() => {
      expect(listed()).toEqual(["Accept new block 1.4"]);
    });
    expect(requests.some((request) => request.url.endsWith("/proposal/dismiss"))).toBe(false);
    await user.click(within(review).getByRole("button", { name: "Accept new block 1.4" }));

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Claude's proposal" })).not.toBeInTheDocument();
    });
    await save(user);
    expect(await savedDocument(requests)).toStrictEqual(proposed);
  });

  it("scenario builder's Reject all gives back the draft the review opened on, and an edit outside the review opens it again", async () => {
    const user = userEvent.setup();
    const proposed = aTreeDocument("blocks-together") as { stages: { steps: unknown[] }[] };
    proposed.stages[0]?.steps.push({ wait: { duration: "30s" } }, { wait: { duration: "30s" } });
    const { requests } = renderTree("blocks-together", {
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
      [`POST ${DETAIL}/proposal/dismiss`]: {},
    });

    await screen.findByText("Claude proposes");
    await user.click(screen.getByRole("button", { name: "Review" }));
    const listed = () =>
      within(screen.getByRole("region", { name: "Claude's proposal" }))
        .getAllByRole("button", { name: /^Accept / })
        .map((button) => button.getAttribute("aria-label"));
    await user.click(screen.getByRole("button", { name: "Accept new block 1.4" }));
    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    expect(listed()).toEqual(["Accept new block 1.5"]);

    // Undone from the draft: the review opens again on the draft as it now is.
    await user.click(screen.getByRole("button", { name: "Back to my draft" }));
    await user.click(screen.getByRole("button", { name: "Undo (⌘Z)" }));
    await waitFor(() => {
      expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Review" }));
    expect(listed()).toEqual(["Accept new block 1.4", "Accept new block 1.5"]);

    // Reject all after an accept: every change rejected, the draft as the review opened on it.
    await user.click(screen.getByRole("button", { name: "Accept new block 1.5" }));
    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reject all" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Claude's proposal" })).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
    expect(requests.some((request) => request.url.endsWith("/proposal/dismiss"))).toBe(true);
  });

  it("scenario builder takes a proposal's block as Claude wrote it, so the blocks accepted bottom-up give the proposal", async () => {
    const user = userEvent.setup();
    const draft = {
      version: 2,
      kind: "scenario",
      name: "order-lifecycle",
      revision: 1,
      stages: [
        { name: "Fetch order", steps: [{ do: "get-order-by-ref" }, { do: "send-queue-message" }] },
      ],
    };
    // Two blocks after the first: the second reads the first by the id its place gives it.
    const proposed = {
      ...draft,
      stages: [
        {
          name: "Fetch order",
          steps: [
            { do: "get-order-by-ref" },
            { you: "Find the order's id by hand." },
            { do: "send-queue-message", with: { order_id: "$fetch-order--2.output.order_id" } },
            { do: "send-queue-message" },
          ],
        },
      ],
    };
    const { requests } = renderBuilder({
      [DETAIL]: aScenarioDetail({ document: draft, content_hash: "sha256:aaa", version: 2 }),
      [SAVE]: () => SAVED,
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
      [`POST ${DETAIL}/proposal/dismiss`]: {},
    });

    await screen.findByText("Claude proposes");
    await user.click(screen.getByRole("button", { name: "Review" }));
    const review = screen.getByRole("region", { name: "Claude's proposal" });
    const listed = () =>
      within(review)
        .getAllByRole("button", { name: /^Accept / })
        .map((button) => button.getAttribute("aria-label"));
    expect(listed()).toEqual(["Accept new block 1.2", "Accept new block 1.3"]);

    // The block that reads the other taken first: it keeps reading the place Claude wrote.
    await user.click(within(review).getByRole("button", { name: "Accept new block 1.3" }));
    await waitFor(() => {
      expect(listed()).toEqual(["Accept new block 1.2"]);
    });
    await user.click(within(review).getByRole("button", { name: "Accept new block 1.2" }));

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Claude's proposal" })).not.toBeInTheDocument();
    });
    await save(user);
    expect(await savedDocument(requests)).toStrictEqual(proposed);
  });

  it("scenario builder shows a plan on the draft's blocks, never on Claude's proposal under review", async () => {
    const user = userEvent.setup();
    const proposed = aTreeDocument("blocks-together") as { stages: { steps: unknown[] }[] };
    proposed.stages[0]?.steps.unshift({ wait: { duration: "30s" } });
    renderTree("blocks-together", {
      [`POST ${DETAIL}/plan`]: aScenarioPlan({
        rows: [aScenarioPlanRow({ step: "fix-shipping--1", plan: "Would read the order" })],
      }),
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
    });

    await user.click(await screen.findByRole("button", { name: "Plan in personal" }));
    const form = screen.queryByRole("form", { name: "Values to plan with" });
    if (form) {
      for (const box of within(form).getAllByRole("textbox")) await user.type(box, "x-1");
      await user.click(within(form).getByRole("button", { name: "Plan in personal" }));
    }
    await waitFor(() => {
      expect(screen.getByRole("treeitem", { name: /^Step 1\.1,/ })).toHaveTextContent(
        "Would read the order",
      );
    });

    // Under review, block 1.1 is the proposal's new Pause: the draft's plan is not its own.
    await user.click(await screen.findByRole("button", { name: "Review" }));
    expect(screen.getByRole("treeitem", { name: /^Step 1\.1, Pause/ })).not.toHaveTextContent(
      "Would read the order",
    );
    await user.click(screen.getByRole("button", { name: "Back to my draft" }));
    expect(screen.getByRole("treeitem", { name: /^Step 1\.1,/ })).toHaveTextContent(
      "Would read the order",
    );
  });

  it("scenario builder's keys and Blocks tab edit nothing when a row of Claude's proposal under review is selected", async () => {
    const user = userEvent.setup();
    // The proposal asks for a block first: its 1.2 is the draft's 1.1, its 1.3 the draft's 1.2.
    const proposed = aTreeDocument("blocks-together") as { stages: { steps: unknown[] }[] };
    proposed.stages[0]?.steps.unshift({ you: "Check the shipment by hand, then approve." });
    renderTree("blocks-together", {
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
      [`POST ${DETAIL}/proposal/dismiss`]: {},
    });
    const rows = () =>
      within(screen.getByRole("group", { name: "Stage 1: Fix shipping" }))
        .getAllByRole("treeitem")
        .map((row) => row.getAttribute("aria-label")?.split(":")[0]);

    await screen.findByText("Claude proposes");
    await user.click(screen.getByRole("treeitem", { name: /^Step 1\.1, Wait until/ }));
    await user.click(screen.getByRole("button", { name: "Review" }));
    // The selection made on the draft is gone once the review shows the proposal.
    expect(screen.queryByRole("treeitem", { selected: true })).not.toBeInTheDocument();
    const shown = rows();
    expect(shown.slice(0, 3)).toEqual([
      "Step 1.1, Ask me",
      "Step 1.2, Wait until",
      "Step 1.3, At the same time",
    ]);

    await user.click(screen.getByRole("treeitem", { name: /^Step 1\.2, Wait until/ }));
    await user.keyboard("{Delete}");
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await user.keyboard("{Control>}d{/Control}");
    const blocks = screen.getByRole("complementary", { name: "Blocks, variables and actions" });
    // The Blocks tab says the draft is not edited, and names no step of the proposal to add after.
    expect(blocks).toHaveTextContent(
      "While you review Claude's proposal the draft is not edited: go back to your draft to add a block.",
    );
    expect(blocks).not.toHaveTextContent(/after step/);
    const pause = within(blocks).getByRole("button", { name: /^Add Pause/ });
    expect(pause).toHaveAttribute("aria-disabled", "true");
    pause.focus();
    await user.keyboard("{Enter}");

    expect(screen.queryByText(/^Deleted /)).not.toBeInTheDocument();
    expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Claude's proposal" })).toBeInTheDocument();
    expect(rows()).toEqual(shown);
    // Nor does Describe place new steps after the draft's block at that address.
    await user.click(screen.getByRole("button", { name: "Describe with Claude" }));
    const dialog = screen.getByRole("dialog", { name: "Describe it to Claude" });
    expect(within(dialog).getByText("Steps at the end")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    // Back to the draft: as it was, nothing selected.
    await user.click(screen.getByRole("button", { name: "Back to my draft" }));
    expect(screen.queryByRole("treeitem", { selected: true })).not.toBeInTheDocument();
    expect(rows()).toEqual([
      "Step 1.1, Wait until",
      "Step 1.2, At the same time",
      expect.stringMatching(/^Step 1\.2\.p1\.1, /),
      expect.stringMatching(/^Step 1\.2\.p2\.1, /),
      expect.stringMatching(/^Step 1\.2\.p2\.2, /),
      expect.stringMatching(/^Step 1\.3, /),
    ]);
    expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
  });

  it("scenario builder counts a stage Claude's proposal only renames as a changed stage, no block", async () => {
    const proposed = aTreeDocument("blocks-together") as { stages: { name: string }[] };
    const [stage] = proposed.stages;
    // The same slug, so the same stage: its own change.
    if (stage) stage.name = stage.name.toUpperCase();
    renderTree("blocks-together", {
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
    });

    const proposes = await screen.findByText("Claude proposes");
    expect(proposes.parentElement).toHaveTextContent(/Claude proposes 1 new or changed stage · /);
    expect(proposes.parentElement).not.toHaveTextContent(/block/);
  });

  it("scenario builder says so when Claude's proposal for a scenario written as blocks is a graph", async () => {
    renderTree("blocks-together", {
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: { ...document, name: "blocks-together" },
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
    });

    const proposes = await screen.findByText("Claude proposes");
    expect(proposes.parentElement).toHaveTextContent(
      "it is written as a graph (nodes), not as stages: accepting it all leaves no stage",
    );
  });

  it("scenario builder's Describe names the place of a scenario written as blocks as Claude is told it", async () => {
    const user = userEvent.setup();
    renderTree(REFERENCE);

    await user.click(await screen.findByRole("treeitem", { name: /^Stage 2: Review/ }));
    await user.click(screen.getByRole("button", { name: "Describe with Claude" }));
    let dialog = screen.getByRole("dialog", { name: "Describe it to Claude" });
    expect(within(dialog).getByText("Steps at the end of stage 2")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("treeitem", { name: /^Step 1\.2,/ }));
    await user.click(screen.getByRole("button", { name: "Describe with Claude" }));
    dialog = screen.getByRole("dialog", { name: "Describe it to Claude" });
    expect(within(dialog).getByText("Steps after block 1.2")).toBeInTheDocument();
  });

  it("scenario builder pins a problem of a scenario written as blocks on its block, the field it names and the Problems list", async () => {
    const user = userEvent.setup();
    renderTree("blocks-if-else", {
      [VALIDATE]: () => ({
        loads: false,
        yaml: "",
        problems: [
          {
            node: "check--3",
            key: "stages[0].steps[2].do",
            line: null,
            message: "unknown action 'queue-send'",
            severity: "error",
          },
          {
            node: "check--2-then-1",
            key: "stages[0].steps[1].if",
            line: null,
            message: "the If's condition names no value",
            severity: "error",
          },
        ],
        nodes: [],
      }),
    });

    expect(await screen.findByText("2 problems")).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: /^Step 1\.1,/ })).not.toHaveAttribute(
      "data-problem",
    );
    expect(screen.getByRole("treeitem", { name: /^Step 1\.2,/ })).toHaveAttribute(
      "data-problem",
      "true",
    );
    expect(screen.getByRole("treeitem", { name: /^Step 1\.3,/ })).toHaveAttribute(
      "data-problem",
      "true",
    );
    // The If's editor says what is wrong with its condition.
    await user.click(screen.getByRole("treeitem", { name: /^Step 1\.2,/ }));
    expect(screen.getByRole("region", { name: "Inspector: If" })).toHaveTextContent(
      "the If's condition names no value",
    );
    // The Problems list opens the block a problem is on; its editor shows it under the field.
    await user.click(screen.getByRole("button", { name: /2 problems/ }));
    const list = screen.getByRole("dialog", { name: "Problems" });
    await user.click(within(list).getByRole("button", { name: /^1\.3: ?unknown action/ }));
    expect(await screen.findByRole("treeitem", { name: /^Step 1\.3,/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const action = within(
      screen.getByRole("region", { name: "Inspector: Run an action check--3" }),
    ).getByLabelText("Action");
    expect(action.closest(".sb-field")).toHaveTextContent("unknown action 'queue-send'");
  });

  it("scenario builder shows a stage's problem in its editor, one on its steps as one on its name", async () => {
    const user = userEvent.setup();
    renderTree("blocks-if-else", {
      [VALIDATE]: () => ({
        loads: false,
        yaml: "",
        problems: [
          {
            node: null,
            key: "stages[0].steps",
            line: null,
            message: "a stage holds at most 64 steps",
            severity: "error",
          },
          {
            node: null,
            key: "stages[0].name",
            line: null,
            message: "the stage name is also stage 2's",
            severity: "error",
          },
        ],
        nodes: [],
      }),
    });

    expect(await screen.findByText("2 problems")).toBeInTheDocument();
    await user.click(screen.getByRole("treeitem", { name: /^Stage 1:/ }));
    const editor = screen.getByRole("region", { name: "Inspector: Stage 1" });
    expect(editor).toHaveTextContent("a stage holds at most 64 steps");
    expect(within(editor).getByLabelText("Name").closest(".sb-field")).toHaveTextContent(
      "the stage name is also stage 2's",
    );
  });

  it("scenario builder has no serious a11y violation on a stage's editor showing its problems (a11y)", async () => {
    const user = userEvent.setup();
    const problem = (key: string, message: string) => ({
      node: null,
      key,
      line: null,
      message,
      severity: "error",
    });
    const { container } = renderTree("blocks-if-else", {
      [VALIDATE]: () => ({
        loads: false,
        yaml: "",
        problems: [
          problem("stages[0].steps", "a stage holds at most 64 steps"),
          problem("stages[0].name", "the stage name is also stage 2's"),
        ],
        nodes: [],
      }),
    });

    expect(await screen.findByText("2 problems")).toBeInTheDocument();
    await user.click(screen.getByRole("treeitem", { name: /^Stage 1:/ }));
    const editor = screen.getByRole("region", { name: "Inspector: Stage 1" });
    expect(within(editor).getByLabelText("Name")).toBeInTheDocument();
    expect(within(editor).getByLabelText(/What it is for/)).toBeInTheDocument();

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("scenario builder offers Migrate for a graph scenario: it checks first, shows the blocks, then writes", async () => {
    const user = userEvent.setup();
    let calls = 0;
    const { requests } = renderBuilder({
      [MIGRATE]: () => {
        calls += 1;
        return calls === 1
          ? MIGRATION
          : { ...MIGRATION, written: true, content_hash: "sha256:ccc" };
      },
    });

    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("button", { name: "Migrate to stages of blocks" }));
    const dialog = screen.getByRole("dialog", { name: "Migrate to stages of blocks" });
    expect(await within(dialog).findByLabelText("The scenario as blocks")).toHaveTextContent(
      "stages:",
    );
    expect(dialog).toHaveTextContent("Nothing is written until you migrate.");
    // What the dialog says as it goes is read out too.
    const status = within(dialog).getByRole("status");
    expect(status).toHaveTextContent("Checked: it can be written as blocks.");
    await user.click(within(dialog).getByRole("button", { name: "Migrate" }));

    expect(
      await screen.findByText(/Migrated: order-lifecycle is now written as blocks/),
    ).toBeInTheDocument();
    expect(status).toHaveTextContent("Done: the file is written as blocks.");
    const sent = requests.filter((request) => request.url.endsWith("/migrate"));
    expect(await Promise.all(sent.map((request) => request.clone().json()))).toEqual([
      { check: true, base_content_hash: "sha256:aaa" },
      { check: false, base_content_hash: "sha256:aaa" },
    ]);
  });

  it("scenario builder's Migrate asks to save unsaved changes first and checks nothing", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [MIGRATE]: () => MIGRATION });

    await user.click(await screen.findByRole("treeitem", { name: CHECK }));
    const field = within(
      screen.getByRole("region", { name: "Inspector: Wait until order-on-hold" }),
    ).getByLabelText("Give up after");
    await user.clear(field);
    await user.type(field, "10m");
    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("button", { name: "Migrate to stages of blocks" }));
    const dialog = screen.getByRole("dialog", { name: "Migrate to stages of blocks" });

    expect(dialog).toHaveTextContent(
      "Save your changes first: Migrate rewrites the file as it is saved.",
    );
    expect(within(dialog).queryByRole("button", { name: "Migrate" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Check again" })).not.toBeInTheDocument();
    expect(requests.filter((request) => request.url.endsWith("/migrate"))).toEqual([]);
  });

  it("scenario builder's Migrate writes over the file it checked: one changed since is refused and checked again", async () => {
    const user = userEvent.setup();
    let hash = "sha256:aaa";
    let migrated = false;
    let calls = 0;
    const { requests, queryClient } = renderBuilder({
      [DETAIL]: () =>
        migrated
          ? aScenarioDetail({ document: REFERRING, content_hash: hash, version: 2 })
          : aScenarioDetail({ document, content_hash: hash }),
      [MIGRATE]: () => {
        calls += 1;
        if (calls === 2) {
          return aProblem({
            status: 409,
            title: "Conflict",
            detail: "the scenario file changed since the builder read it",
          });
        }
        // The file changed once more before this check read it: it answers that file's hash.
        if (calls === 3) return { ...MIGRATION, content_hash: "sha256:fff" };
        return calls === 1
          ? MIGRATION
          : { ...MIGRATION, written: true, content_hash: "sha256:eee" };
      },
    });

    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("button", { name: "Migrate to stages of blocks" }));
    const dialog = screen.getByRole("dialog", { name: "Migrate to stages of blocks" });
    await within(dialog).findByLabelText("The scenario as blocks");
    // The file is changed outside (an editor) while the check shows: the builder reads it again.
    hash = "sha256:ddd";
    await act(() => queryClient.refetchQueries());
    await user.click(within(dialog).getByRole("button", { name: "Migrate" }));

    expect(
      await within(dialog).findByText("the scenario file changed since the builder read it"),
    ).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Migrate" })).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("The scenario as blocks")).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Check again" }));
    await within(dialog).findByLabelText("The scenario as blocks");
    await user.click(within(dialog).getByRole("button", { name: "Migrate" }));

    expect(
      await screen.findByText(/Migrated: order-lifecycle is now written as blocks/),
    ).toBeInTheDocument();
    const sent = requests.filter((request) => request.url.endsWith("/migrate"));
    expect(await Promise.all(sent.map((request) => request.clone().json()))).toEqual([
      { check: true, base_content_hash: "sha256:aaa" },
      { check: false, base_content_hash: "sha256:aaa" },
      { check: true, base_content_hash: "sha256:ddd" },
      { check: false, base_content_hash: "sha256:fff" },
    ]);
    // The file read again is written as blocks: the page opens its stages.
    migrated = true;
    hash = "sha256:eee";
    await act(() => queryClient.refetchQueries());
    expect(
      await screen.findByRole("treeitem", { name: /^Stage 1: Fetch order/ }),
    ).toBeInTheDocument();
  });

  it("scenario builder's Check again reads the file again first when Migrate is refused before the builder has", async () => {
    const user = userEvent.setup();
    let hash = "sha256:aaa";
    let calls = 0;
    const { requests } = renderBuilder({
      [DETAIL]: () => aScenarioDetail({ document, content_hash: hash }),
      [MIGRATE]: () => {
        calls += 1;
        if (calls === 2) {
          return aProblem({
            status: 409,
            title: "Conflict",
            detail: "the scenario file changed since the builder read it",
          });
        }
        return { ...MIGRATION, content_hash: hash };
      },
    });

    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("button", { name: "Migrate to stages of blocks" }));
    const dialog = screen.getByRole("dialog", { name: "Migrate to stages of blocks" });
    await within(dialog).findByLabelText("The scenario as blocks");
    // The file is changed outside, and the builder has not read it again yet.
    hash = "sha256:ddd";
    await user.click(within(dialog).getByRole("button", { name: "Migrate" }));
    expect(
      await within(dialog).findByText("the scenario file changed since the builder read it"),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Check again" }));
    await within(dialog).findByLabelText("The scenario as blocks");

    const sent = requests.filter((request) => request.url.endsWith("/migrate"));
    expect(await Promise.all(sent.map((request) => request.clone().json()))).toEqual([
      { check: true, base_content_hash: "sha256:aaa" },
      { check: false, base_content_hash: "sha256:aaa" },
      { check: true, base_content_hash: "sha256:ddd" },
    ]);
  });

  it("scenario builder's Migrate lists what the write could not migrate and offers no Migrate", async () => {
    const user = userEvent.setup();
    let calls = 0;
    renderBuilder({
      [MIGRATE]: () => {
        calls += 1;
        return calls === 1
          ? MIGRATION
          : {
              ...MIGRATION,
              yaml: null,
              problems: [
                { node: "order-on-hold", message: "its trigger_rule one_success has no block" },
              ],
            };
      },
    });

    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("button", { name: "Migrate to stages of blocks" }));
    const dialog = screen.getByRole("dialog", { name: "Migrate to stages of blocks" });
    await within(dialog).findByLabelText("The scenario as blocks");
    await user.click(within(dialog).getByRole("button", { name: "Migrate" }));

    expect(
      await within(dialog).findByText("its trigger_rule one_success has no block"),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("list", { name: "What blocks cannot hold" })).toHaveTextContent(
      "order-on-hold",
    );
    expect(within(dialog).queryByRole("button", { name: "Migrate" })).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("The scenario as blocks")).not.toBeInTheDocument();
  });

  it("scenario builder's Migrate dialog has no serious a11y violation, checked or refused (a11y)", async () => {
    const user = userEvent.setup();
    let calls = 0;
    renderBuilder({
      [MIGRATE]: () => {
        calls += 1;
        return calls === 1
          ? MIGRATION
          : {
              ...MIGRATION,
              yaml: null,
              problems: [
                { node: "order-on-hold", message: "its trigger_rule one_success has no block" },
              ],
            };
      },
    });

    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("button", { name: "Migrate to stages of blocks" }));
    const dialog = screen.getByRole("dialog", { name: "Migrate to stages of blocks" });
    await within(dialog).findByLabelText("The scenario as blocks");
    expect(await seriousViolations(dialog)).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Migrate" }));
    await within(dialog).findByRole("list", { name: "What blocks cannot hold" });
    expect(await seriousViolations(dialog)).toEqual([]);
  });

  it("scenario builder's Migrate names each step a graph cannot hold and writes nothing", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [MIGRATE]: {
        ...MIGRATION,
        yaml: null,
        problems: [{ node: "order-on-hold", message: "its trigger_rule one_success has no block" }],
      },
    });

    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("button", { name: "Migrate to stages of blocks" }));
    const dialog = screen.getByRole("dialog", { name: "Migrate to stages of blocks" });

    expect(
      await within(dialog).findByText("its trigger_rule one_success has no block"),
    ).toBeInTheDocument();
    expect(dialog).toHaveTextContent("order-on-hold");
    expect(within(dialog).queryByRole("button", { name: "Migrate" })).not.toBeInTheDocument();
    // A check again would read the same file: the steps are changed in the builder first.
    expect(dialog).toHaveTextContent("Change these steps in the builder, then open Migrate again");
    expect(within(dialog).queryByRole("button", { name: "Check again" })).not.toBeInTheDocument();
  });

  it("scenario builder's Start row says where the scenario starts and what it asks for", async () => {
    const user = userEvent.setup();
    renderBuilder();

    const start = await screen.findByRole("treeitem", { name: /Starts in personal/ });
    expect(start).toHaveTextContent("Asks for external_ref");
    // Nothing open: no editor. The Start row opens the scenario's settings.
    expect(screen.queryByRole("region", { name: "Scenario settings" })).not.toBeInTheDocument();
    await user.click(start);
    expect(start).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("region", { name: "Scenario settings" })).toHaveTextContent(
      "external_ref",
    );
  });

  it("scenario builder's Start editor sets a value, or leaves it empty to ask each run", async () => {
    const user = userEvent.setup();
    renderBuilder();

    const start = await screen.findByRole("treeitem", { name: /Starts in personal/ });
    await user.click(start);
    const settings = screen.getByRole("region", { name: "Scenario settings" });
    // No type or required to pick: a name, its value and what it is.
    expect(within(settings).queryByLabelText("Type")).not.toBeInTheDocument();
    expect(within(settings).queryByLabelText("Required")).not.toBeInTheDocument();
    const value = within(settings).getByLabelText("external_ref");
    expect(value).toHaveAttribute("placeholder", "Asked each time the scenario runs");

    await user.type(value, "T-1");
    expect(start).toHaveTextContent("Asks for nothing");
    await user.clear(value);
    expect(start).toHaveTextContent("Asks for external_ref");
  });

  it("scenario builder's Start row asks for nothing the environment gives", async () => {
    renderBuilder({
      [DETAIL]: aScenarioDetail({
        document,
        content_hash: "sha256:aaa",
        environments: [
          { name: "personal", access: "write", production: false, values: { external_ref: "T-9" } },
        ],
      }),
    });

    expect(await screen.findByRole("treeitem", { name: /Starts in personal/ })).toHaveTextContent(
      "Asks for nothing",
    );
  });

  it("scenario builder's Environment select drives ?env= and what the page reads in", async () => {
    const user = userEvent.setup();
    const { router } = renderBuilder({}, `${PATH}?env=qa`);

    const select = await screen.findByRole("combobox", { name: "Environment" });
    expect(select).toHaveValue("qa");
    expect(await screen.findByRole("treeitem", { name: /Starts in qa/ })).toBeInTheDocument();

    await user.selectOptions(select, "personal");
    expect(new URLSearchParams(router.state.location.search).get("env")).toBe("personal");
    expect(screen.getByRole("treeitem", { name: /Starts in personal/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plan in personal" })).toBeInTheDocument();
  });

  it("scenario builder adds a step from the insert menu, edits it and saves over the file read", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    await insertStep(user, "Add step", /^Ask me/);
    const editor = await screen.findByRole("region", { name: "Inspector: Ask me manual-step" });
    await user.clear(within(editor).getByLabelText("What to do"));
    await user.type(within(editor).getByLabelText("What to do"), "Create the order");
    await user.click(within(editor).getByLabelText(/Ask me to type a value/));
    const row = screen.getByRole("treeitem", { name: /Ask me: Create the order/ });
    expect(row).toHaveAttribute("aria-selected", "true");
    expect(row).toHaveTextContent("You approve or reject · asks for a value");

    await save(user);
    const nodes = await savedNodes(requests);
    expect(nodes.map((node) => node.id)).toEqual(["fetch-order", "order-on-hold", "manual-step"]);
    expect(nodes[2]).toMatchObject({ depends_on: ["order-on-hold"], capture_response: true });
  });

  it("scenario builder edits a step in the step editor", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("treeitem", { name: CHECK }));
    const editor = screen.getByRole("region", { name: "Inspector: Wait until order-on-hold" });
    const field = within(editor).getByLabelText("Give up after");
    await user.clear(field);
    await user.type(field, "10m");
    expect(within(editor).getByText("Checks at most 60 times.")).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: CHECK })).toHaveTextContent("up to 10 min");

    await save(user);
    const nodes = await savedNodes(requests);
    expect(nodes[1]).toMatchObject({ id: "order-on-hold", timeout: "10m" });
  });

  it("scenario builder adds If and Repeat as indented groups", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await insertStep(user, "Add step", /^If/);
    const branch = await screen.findByRole("treeitem", { name: /, If: If/ });
    expect(branch).toHaveAttribute("aria-expanded", "true");
    const paths = lastGroup();
    expect(paths).toHaveTextContent("If yes");
    expect(paths).toHaveTextContent("Otherwise");
    expect(
      within(paths).getAllByRole("button", {
        name: /Empty. Add a step here/,
      }),
    ).toHaveLength(2);

    await insertStep(user, "Add step", /^Repeat/);
    const repeat = await screen.findByRole("treeitem", { name: /, Repeat: Repeat/ });
    expect(repeat).toHaveAttribute("aria-expanded", "true");
    // A step added inside the group is indented under it and numbered from it.
    const body = lastGroup();
    await user.click(within(body).getByRole("button", { name: /Empty. Add a step here/ }));
    await user.click(
      within(screen.getByRole("dialog", { name: "Add a step here" })).getByRole("option", {
        name: /^Pause/,
      }),
    );
    const inner = await screen.findByRole("treeitem", { name: /^Step 4\.1, Pause/ });
    expect(inner).toHaveAttribute("aria-level", "2");
    expect(within(body).getByRole("treeitem", { name: /Pause/ })).toBe(inner);
  });

  it("scenario builder pins the server's problems on their step and keeps Save off", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [VALIDATE]: () => ({
        loads: false,
        yaml: "",
        problems: [
          {
            node: "fetch-order",
            key: "action",
            line: null,
            message: "unknown action 'x'",
            severity: "error",
          },
        ],
        nodes: [],
      }),
    });

    expect(await screen.findByText("1 problem")).toBeInTheDocument();
    const row = screen.getByRole("treeitem", { name: FETCH });
    expect(row).toHaveAttribute("data-problem", "true");
    expect(row).toHaveTextContent("Problem");
    expect(screen.getByRole("button", { name: "Save scenario" })).toBeDisabled();
    row.focus();
    await user.keyboard("{Enter}");
    expect(
      within(
        screen.getByRole("region", { name: "Inspector: Run an action fetch-order" }),
      ).getAllByText("unknown action 'x'").length,
    ).toBeGreaterThan(0);
  });

  it("scenario builder previews an action from the Actions tab and adds it", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("tab", { name: /Actions/ }));
    const list = screen.getByRole("list", { name: "Actions in this hub" });
    expect(within(list).getByRole("button", { name: /get-order-by-ref/ })).toHaveTextContent(
      "used by 1 step",
    );
    await user.click(within(list).getByRole("button", { name: /get-order-by-ref/ }));
    const panel = await screen.findByRole("complementary", { name: "Action get-order-by-ref" });
    expect(panel).toHaveTextContent("print('{}')");
    await user.click(within(panel).getByRole("button", { name: "Add to the scenario" }));

    const added = await screen.findByRole("treeitem", { name: /^Step 3, Run an action/ });
    expect(added).toHaveAttribute("aria-selected", "true");
    expect(added).toHaveTextContent("get-order-by-ref");
  });

  it("scenario builder keeps unsaved changes across a reload, and drops them for a changed file", async () => {
    const user = userEvent.setup();
    const first = renderBuilder();
    await insertStep(user, "Add step", /^Pause/);
    await screen.findByRole("treeitem", { name: /, Pause: / });
    first.unmount();

    const second = renderBuilder();
    expect(await screen.findByRole("treeitem", { name: /, Pause: / })).toBeInTheDocument();
    expect(
      screen.getByText(/Your unsaved changes came back from this browser/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard them" }));
    expect(screen.queryByRole("treeitem", { name: /, Pause: / })).not.toBeInTheDocument();
    await insertStep(user, "Add step", /^Pause/);
    second.unmount();

    renderBuilder({
      [DETAIL]: aScenarioDetail({ document, content_hash: "sha256:changed-outside" }),
    });
    await screen.findByRole("treeitem", { name: CHECK });
    expect(screen.queryByRole("treeitem", { name: /, Pause: / })).not.toBeInTheDocument();
  });

  it("scenario builder says so when the hub's actions cannot be read", async () => {
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": aProblem({ status: 500, title: "Boom" }),
    });

    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    await waitFor(() => {
      expect(
        screen.getByRole("region", { name: "Inspector: Run an action fetch-order" }),
      ).toHaveTextContent("The hub's actions could not be read");
    });
    expect(fetch).not.toHaveTextContent("Changes data");
    await user.click(screen.getByRole("tab", { name: /Actions/ }));
    expect(screen.getByText(/Could not load the actions/)).toBeInTheDocument();
  });

  it("scenario builder plans in the environment and marks a plan made before the last change", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      [`POST ${DETAIL}/plan`]: aScenarioPlan({
        rows: [
          aScenarioPlanRow({
            step: "fetch-order",
            plan: "Would send one message",
            decision: "ask",
          }),
        ],
      }),
    });

    await screen.findByText("Loads");
    // external_ref has no value anywhere: the plan asks for it first.
    await user.click(screen.getByRole("button", { name: "Plan in personal" }));
    const form = screen.getByRole("form", { name: "Values to plan with" });
    await user.type(within(form).getByRole("textbox", { name: "external_ref" }), "T-1");
    await user.click(within(form).getByRole("button", { name: "Plan in personal" }));

    const fetch = screen.getByRole("treeitem", { name: FETCH });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("Would send one message");
    });
    expect(fetch).toHaveTextContent("Asks you");
    const sent = requests.find((request) => request.url.endsWith("/plan"));
    expect(await sent?.clone().json()).toEqual({
      environment: "personal",
      inputs: { external_ref: "T-1" },
    });
    await user.click(fetch);
    expect(
      screen.getByRole("region", { name: "Inspector: Run an action fetch-order" }),
    ).toHaveTextContent("asks you first");

    await insertStep(user, "Add step", /^Pause/);
    expect(fetch).toHaveTextContent("Planned before your changes · Would send one message");
    expect(screen.getByRole("button", { name: "Save and plan" })).toBeInTheDocument();
  });

  it("scenario builder edits a JSON body as fields or as JSON, keeping bare references", async () => {
    const user = userEvent.setup();
    const body = '{"event_type":"FETCH","ids":["$INPUTS.external_ref"],"minutes":$INPUTS.minutes}';
    const { requests } = renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: {
          ...document,
          nodes: [
            {
              id: "fetch-order",
              type: "action",
              action: "send-queue-message",
              with: { body },
            },
          ],
        },
        content_hash: "sha256:aaa",
      }),
      "/api/v1/projects/demo/actions": {
        ...library,
        items: [
          {
            action: aScenarioAction({
              ref: "orders/send-queue-message",
              name: "send-queue-message",
              effect: "write",
              inputs: [
                { name: "body", type: "string", required: true, description: "One JSON object" },
              ],
            }),
            output_fields: [],
            used_by: [],
          },
        ],
      },
      [SAVE]: () => SAVED,
    });

    await user.click(await screen.findByRole("treeitem", { name: FETCH }));
    const form = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    // Fields: one row per key; a bare reference stays a token, "as a number".
    const event = await within(form).findByLabelText("Value of event_type in body");
    await user.clear(event);
    await user.type(event, "RESOLVE");
    expect(within(form).getByText("as a number")).toBeInTheDocument();

    // JSON: indented, checked as you type; an invalid text does not reach the file.
    await user.click(within(form).getByRole("button", { name: "JSON" }));
    const text = within(form).getByLabelText("body");
    expect((text as HTMLTextAreaElement).value).toContain('\n  "event_type": "RESOLVE",');
    await user.type(text, "{{");
    expect(within(form).getByText(/Not valid JSON yet/)).toBeInTheDocument();

    await save(user);
    const nodes = (await savedNodes(requests)) as (SentNode & { with?: { body?: string } })[];
    expect(nodes[0]?.with?.body).toBe(
      '{"event_type":"RESOLVE","ids":["$INPUTS.external_ref"],"minutes":$INPUTS.minutes}',
    );
  });

  it("scenario builder gives every step the run's values and drops the repeats", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: {
          ...document,
          nodes: [
            {
              id: "fetch-order",
              type: "action",
              action: "send-queue-message",
              with: { external_ref: "$INPUTS.external_ref" },
            },
            { ...document.nodes[1], with: { external_ref: "$INPUTS.external_ref" } },
          ],
        },
        content_hash: "sha256:aaa",
      }),
      [SAVE]: () => SAVED,
    });

    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(screen.getByRole("tab", { name: "Variables" }));
    // A repeat is not a value of the step's own: the row does not list it.
    expect(fetch).not.toHaveTextContent("external_ref");
    const asked = screen.getByRole("region", { name: "Set in the scenario" });
    await waitFor(() => {
      expect(asked).toHaveTextContent("used by 2 steps");
    });
    expect(asked).toHaveTextContent("2 values repeat a run value");
    await user.click(within(asked).getByRole("button", { name: "Remove the repeats" }));

    await save(user);
    const nodes = (await savedNodes(requests)) as (SentNode & { with?: object })[];
    expect(nodes.map((node) => node.with)).toEqual([undefined, undefined]);
    // Still the run's value, as the editor says.
    await user.click(fetch);
    expect(
      within(
        screen.getByRole("region", { name: "Inspector: Run an action fetch-order" }),
      ).getByRole("note"),
    ).toHaveTextContent("external_ref comes from the scenario run (asked at start).");
  });

  it("scenario builder inserts a step between two others from the + in the gap", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("button", { name: "Add a step after step 1" }));
    const menu = screen.getByRole("dialog", { name: "Add a step after step 1" });
    await user.type(within(menu).getByLabelText(/Find an action or a step type/), "pause");
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("treeitem", { name: /^Step 2, Pause/ })).toBeInTheDocument();
    await save(user);
    const nodes = await savedNodes(requests);
    expect(nodes.map((node) => node.id)).toEqual(["fetch-order", "pause", "order-on-hold"]);
    expect(nodes[2]?.depends_on).toEqual(["pause"]);
  });

  it("scenario builder lists the problems and opens the step of one", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [VALIDATE]: () => ({
        loads: false,
        yaml: "",
        problems: [
          {
            node: "order-on-hold",
            key: "until_when",
            line: null,
            message: "the condition does not parse",
            severity: "error",
          },
        ],
        nodes: [],
      }),
    });

    await user.click(await screen.findByRole("button", { name: /1 problem/ }));
    const list = screen.getByRole("dialog", { name: "Problems" });
    await user.click(within(list).getByRole("button", { name: /the condition does not parse/ }));

    const check = await screen.findByRole("treeitem", { name: CHECK });
    expect(check).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("region", { name: "Inspector: Wait until order-on-hold" }),
    ).toHaveTextContent("the condition does not parse");
  });

  it("scenario builder picks a step's action and sets a value the run would give", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const form = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    await user.selectOptions(within(form).getByLabelText("Action"), "orders/get-order-by-ref");
    expect(fetch).toHaveTextContent("get-order-by-ref");
    // external_ref is a scenario input: the step takes the run's value unless it sets its own.
    expect(within(form).getByRole("note")).toHaveTextContent(
      "external_ref comes from the scenario run",
    );
    await user.selectOptions(
      within(form).getByRole("combobox", { name: "Set one for this step" }),
      "external_ref",
    );
    await user.type(within(form).getByLabelText("external_ref"), "T-1");
    expect(fetch).toHaveTextContent("external_ref T-1");

    await save(user);
    const nodes = (await savedNodes(requests)) as (SentNode & { action?: string; with?: object })[];
    expect(nodes[0]).toMatchObject({
      action: "orders/get-order-by-ref",
      with: { external_ref: "T-1" },
    });
  });

  it("scenario builder deletes with Delete, undoes from the toast, and moves with Alt+arrows", async () => {
    const user = userEvent.setup();
    renderBuilder();

    const check = await screen.findByRole("treeitem", { name: CHECK });
    await user.click(check);
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    const rows = screen.getAllByRole("treeitem", { name: /^Step / });
    expect(rows.map((row) => row.getAttribute("aria-label"))).toEqual([
      expect.stringMatching(/^Step 1, Wait until: Wait until status is ON_HOLD\./),
      expect.stringMatching(/^Step 2, Run an action: Fetch order\./),
    ]);

    await user.keyboard("{Delete}");
    expect(screen.queryByRole("treeitem", { name: CHECK })).not.toBeInTheDocument();
    expect(screen.getByText("Deleted step order-on-hold.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("treeitem", { name: CHECK })).toBeInTheDocument();
  });

  it("scenario builder moves a step down from its row menu, rewiring what waits for what", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    await screen.findByRole("treeitem", { name: FETCH });
    await user.click(screen.getByRole("button", { name: "Move step 1" }));
    const menu = screen.getByRole("menu", { name: "Step fetch-order" });
    expect(within(menu).queryByRole("button", { name: "Move up" })).not.toBeInTheDocument();
    await user.click(within(menu).getByRole("button", { name: "Move down" }));

    expect(screen.getByRole("treeitem", { name: /^Step 2, Run an action: Fetch order/ })).toBe(
      screen.getByRole("treeitem", { name: FETCH }),
    );
    await save(user);
    const nodes = await savedNodes(requests);
    expect(nodes.map((node) => node.id)).toEqual(["order-on-hold", "fetch-order"]);
    expect(nodes[0]?.depends_on ?? []).toEqual([]);
    expect(nodes[1]?.depends_on).toEqual(["order-on-hold"]);
  });

  it("scenario builder shows Claude's proposal as suggested steps to accept", async () => {
    const user = userEvent.setup();
    const proposed = {
      ...document,
      nodes: [
        ...document.nodes,
        {
          id: "notify",
          type: "action",
          action: "send-queue-message",
          depends_on: ["order-on-hold"],
        },
      ],
    };
    const { requests } = renderBuilder({
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: proposed,
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
      [`POST ${DETAIL}/proposal/dismiss`]: {},
    });

    const proposes = await screen.findByText("Claude proposes");
    expect(proposes.parentElement).toHaveTextContent(
      /Claude proposes 1 new or changed .* it loads/,
    );
    await user.click(screen.getByRole("button", { name: "Review" }));
    const notify = screen.getByRole("treeitem", { name: /Run an action: Notify/ });
    expect(notify).toHaveAttribute("data-suggested", "true");
    expect(notify).toHaveTextContent("Suggested");
    expect(screen.getByRole("treeitem", { name: FETCH })).not.toHaveAttribute("data-suggested");
    // Step by step: the review panel lists the change, accepted on its own.
    const review = screen.getByRole("region", { name: "Claude's proposal" });
    expect(within(review).getByText("notify")).toBeInTheDocument();
    await user.click(within(review).getByRole("button", { name: "Accept notify" }));

    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: /Run an action: Notify/ })).not.toHaveAttribute(
      "data-suggested",
    );
    await waitFor(() => {
      expect(
        requests.some(
          (request) => request.method === "POST" && request.url.endsWith("/proposal/dismiss"),
        ),
      ).toBe(true);
    });
  });

  it("scenario builder writes a new action from the step editor and uses it", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      "POST /api/v1/projects/demo/actions": aScenarioAction({
        ref: "orders/render-invoice-pdf",
        name: "render-invoice-pdf",
        effect: "write",
        draft: true,
      }),
    });

    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const form = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    // A step with no action yet offers to write one.
    await user.selectOptions(within(form).getByLabelText("Action"), "");
    await user.click(within(form).getByRole("button", { name: "New action" }));
    const dialog = screen.getByRole("dialog", { name: "New action" });
    await user.type(within(dialog).getByPlaceholderText("send-message"), "render-invoice-pdf");
    await user.type(
      within(dialog).getByPlaceholderText("Send one JSON message to a queue"),
      "Render the PDF",
    );
    await user.click(within(dialog).getByRole("button", { name: "Write the action" }));

    await waitFor(() => {
      expect(fetch).toHaveTextContent("render-invoice-pdf");
    });
    const sent = requests.find(
      (request) => request.method === "POST" && request.url.endsWith("/projects/demo/actions"),
    );
    const body = (await sent?.clone().json()) as {
      name: string;
      effect: string;
      script_text: string;
    };
    expect(body.name).toBe("render-invoice-pdf");
    expect(body.effect).toBe("write");
    expect(body.script_text).toContain('request["mode"] == "plan"');
  });

  it("scenario builder starts an empty scenario from a shape", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: { ...document, nodes: [] },
        content_hash: "sha256:aaa",
      }),
    });

    const start = await screen.findByRole("region", { name: "Start the scenario" });
    expect(
      within(start).getByRole("button", { name: "Describe it to Claude" }),
    ).toBeInTheDocument();
    await user.click(within(start).getByRole("button", { name: /Do something, then wait/ }));

    expect(
      await screen.findByRole("treeitem", { name: /^Step 1, Run an action/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: /^Step 2, Wait until/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Start the scenario" })).not.toBeInTheDocument();
  });

  it("scenario builder's Blocks tab adds a block after the selected step, by click or Enter", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await user.click(await screen.findByRole("treeitem", { name: FETCH }));
    const blocks = screen.getByRole("complementary", { name: "Blocks, variables and actions" });
    expect(within(blocks).getByRole("tab", { name: "Blocks" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // The step types, and the hub's actions as ready blocks (a read one can also wait).
    expect(within(blocks).getByRole("region", { name: "Control" })).toHaveTextContent("Repeat");
    expect(
      within(blocks).getByRole("button", { name: "Add Run send-queue-message after step 1" }),
    ).toBeInTheDocument();
    expect(
      within(blocks).getByRole("button", {
        name: "Add Wait until, with get-order-by-ref after step 1",
      }),
    ).toBeInTheDocument();

    await user.click(within(blocks).getByRole("button", { name: "Add Pause after step 1" }));
    expect(await screen.findByRole("treeitem", { name: /^Step 2, Pause/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("treeitem", { name: CHECK })).toHaveAccessibleName(/^Step 3/);

    within(blocks)
      .getByRole("button", { name: /^Add Ask me after step 2/ })
      .focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("treeitem", { name: /^Step 3, Ask me/ })).toBeInTheDocument();
  });

  it("scenario builder takes blocks into an empty scenario", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: { ...document, nodes: [] },
        content_hash: "sha256:aaa",
      }),
    });

    // The list (its Start row) shows even with no step, so a block has somewhere to land.
    expect(await screen.findByRole("treeitem", { name: /Starts in/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add Run an action at the end" }));
    expect(
      await screen.findByRole("treeitem", { name: /^Step 1, Run an action/ }),
    ).toBeInTheDocument();
  });

  it("scenario builder's Settings tab folds the values that come from elsewhere into one box", async () => {
    const user = userEvent.setup();
    renderSources();

    await user.click(await screen.findByRole("treeitem", { name: FETCH }));
    const form = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    await waitFor(() => {
      expect(within(form).getByRole("tab", { name: /Settings/ })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });
    // Only the value the step sets is a field; the rest fold into the "comes from" box.
    expect(within(form).getByLabelText("queue")).toHaveValue("demo-events");
    expect(within(form).queryByLabelText("aws_account_id")).not.toBeInTheDocument();
    const box = within(form).getByRole("note");
    expect(box).toHaveTextContent("aws_account_id comes from personal.");
    expect(box).toHaveTextContent("external_ref comes from the scenario run (asked at start).");
    expect(box).toHaveTextContent("aws_region uses its default, eu-west-1.");
  });

  it("scenario builder's Script tab says how the step fills each input, and shows the script", async () => {
    const user = userEvent.setup();
    renderSources();

    await user.click(await screen.findByRole("treeitem", { name: FETCH }));
    const form = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    await user.click(await within(form).findByRole("button", { name: /View script/ }));
    const tabs = within(form).getByRole("tablist", { name: "Step editor" });
    expect(within(tabs).getByRole("tab", { name: /Script/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    const fills = within(form).getByRole("region", { name: "How this step fills each input" });
    expect(fills).toHaveTextContent("How this step fills each input · in personal");
    const table = within(fills).getByRole("table");
    const sourceOf = (input: string) =>
      within(table)
        .getAllByRole("row")
        .find((row) => within(row).queryByText(input) !== null);
    expect(sourceOf("queue")).toHaveTextContent("this step");
    expect(sourceOf("queue")).toHaveTextContent("demo-events");
    expect(sourceOf("aws_account_id")).toHaveTextContent("personal");
    expect(sourceOf("aws_account_id")).toHaveTextContent("123456789012");
    expect(sourceOf("external_ref")).toHaveTextContent("scenario run");
    expect(sourceOf("external_ref")).toHaveTextContent("asked at start");
    expect(sourceOf("aws_region")).toHaveTextContent("default");
    expect(sourceOf("aws_region")).toHaveTextContent("eu-west-1");
    expect(within(form).getByRole("region", { name: "What it does" })).toHaveTextContent(
      "Changes data",
    );
    expect(within(form).getByRole("region", { name: "Files" })).toHaveTextContent("print('{}')");
  });

  it("scenario builder's Variables tab lists the environment's values and saves one", async () => {
    const user = userEvent.setup();
    const { requests } = renderSources({ [ENV_EDIT]: { environments: [] } });

    await screen.findByRole("treeitem", { name: FETCH });
    await user.click(screen.getByRole("tab", { name: "Variables" }));
    const fromEnv = screen.getByRole("region", { name: "From personal" });
    expect(fromEnv).toHaveTextContent("aws_account_id");
    expect(fromEnv).toHaveTextContent("123456789012");
    // A value this scenario does not use folds away.
    expect(fromEnv).not.toHaveTextContent("region_hint");
    expect(screen.getByRole("region", { name: "Set in the scenario" })).not.toHaveTextContent(
      "aws_account_id",
    );

    await user.click(within(fromEnv).getByRole("button", { name: /aws_account_id/ }));
    const editor = within(fromEnv).getByRole("form", { name: "Value aws_account_id in personal" });
    const value = within(editor).getByLabelText("Value");
    await user.clear(value);
    await user.type(value, "123456789012");
    await user.click(within(editor).getByRole("button", { name: "Save value" }));

    expect(await screen.findByText("Saved aws_account_id in personal.")).toBeInTheDocument();
    const sent = requests.find(
      (request) => request.method === "POST" && request.url.endsWith("/config/environments"),
    );
    expect(await sent?.clone().json()).toEqual({
      op: "set_environment",
      scope: "local",
      name: "personal",
      values: { aws_account_id: "123456789012" },
    });
  });

  it("scenario builder keeps a value most steps share in the environment and drops its repeats", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      [ENV_EDIT]: { environments: [] },
      [DETAIL]: aScenarioDetail({
        document: {
          ...document,
          inputs: { personal_name: { type: "string", default: "jane" } },
          nodes: [
            {
              id: "fetch-order",
              type: "action",
              action: "send-queue-message",
              with: { personal_name: "$INPUTS.personal_name" },
            },
            {
              id: "send-again",
              type: "action",
              action: "send-queue-message",
              depends_on: ["fetch-order"],
              with: { personal_name: "$INPUTS.personal_name" },
            },
          ],
        },
        content_hash: "sha256:aaa",
        environments: [{ name: "personal", access: "write", production: false, values: {} }],
      }),
    });

    await screen.findByRole("treeitem", { name: FETCH });
    await user.click(screen.getByRole("tab", { name: "Variables" }));
    const asked = screen.getByRole("region", { name: "Set in the scenario" });
    expect(asked).toHaveTextContent("personal_name is used by most steps");
    await user.click(within(asked).getByRole("button", { name: "Keep in personal" }));

    expect(
      await screen.findByText("Kept personal_name in personal and removed 2 repeats."),
    ).toBeInTheDocument();
    const sent = requests.find(
      (request) => request.method === "POST" && request.url.endsWith("/config/environments"),
    );
    expect(await sent?.clone().json()).toEqual({
      op: "set_environment",
      scope: "local",
      name: "personal",
      values: { personal_name: "jane" },
    });
  });

  it("scenario builder makes and edits actions from the Actions tab", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      "PUT /api/v1/projects/demo/actions/orders/get-order-by-ref": aScenarioAction({
        ref: "orders/get-order-by-ref",
        name: "get-order-by-ref",
        description: "Read one record",
        draft: true,
      }),
    });

    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("tab", { name: /Actions/ }));
    await user.click(screen.getByRole("button", { name: "New action" }));
    expect(screen.getByRole("dialog", { name: "New action" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    const list = screen.getByRole("list", { name: "Actions in this hub" });
    await user.click(within(list).getByRole("button", { name: /get-order-by-ref/ }));
    const panel = await screen.findByRole("complementary", { name: "Action get-order-by-ref" });
    await user.click(within(panel).getByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit action get-order-by-ref" });
    const what = within(dialog).getByPlaceholderText("Send one JSON message to a queue");
    await user.clear(what);
    await user.type(what, "Read one record");
    await user.click(within(dialog).getByRole("button", { name: "Save the action" }));

    await waitFor(() => {
      expect(requests.some((request) => request.method === "PUT")).toBe(true);
    });
    const put = requests.find((request) => request.method === "PUT");
    expect(put?.url).toContain("/projects/demo/actions/orders/get-order-by-ref");
    expect(((await put?.clone().json()) as { description: string }).description).toBe(
      "Read one record",
    );
  });

  it("scenario builder turns a condition typed in words into rows", async () => {
    const user = userEvent.setup();
    renderBuilder();

    const check = await screen.findByRole("treeitem", { name: CHECK });
    await user.click(check);
    const form = screen.getByRole("region", { name: "Inspector: Wait until order-on-hold" });
    const [words] = within(form).getAllByLabelText("Type the condition in words");
    if (!words) throw new Error("no words field");
    await user.type(words, "status is DONE{Enter}");

    expect(
      within(form).getByText("Read from your words: check the rows below."),
    ).toBeInTheDocument();
    expect(within(form).getAllByLabelText("Value")[0]).toHaveValue("DONE");
    expect(
      screen.getByRole("treeitem", { name: /Wait until: Wait until status is DONE/ }),
    ).toBeInTheDocument();
  });

  it("scenario builder still adds steps in the graph view", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await user.click(await screen.findByRole("button", { name: "Graph" }));
    await user.click(await screen.findByRole("button", { name: "Add a block after fetch-order" }));
    await user.click(screen.getByRole("menuitem", { name: "Pause" }));

    expect(
      await screen.findByRole("region", { name: "Inspector: Pause pause" }),
    ).toBeInTheDocument();
  });

  it("scenario builder shows the generated YAML", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [VALIDATE]: () => ({
        loads: true,
        yaml: "version: 1\nkind: scenario\n",
        problems: [],
        nodes: [],
      }),
    });

    await screen.findByText("Loads");
    await user.click(screen.getByRole("button", { name: "YAML" }));

    expect(screen.getByLabelText("Generated YAML")).toHaveTextContent("kind: scenario");
  });
});
