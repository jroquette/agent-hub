import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ICONS } from "../../../components/icons";
import { seriousViolations } from "../../../testing/axe";
import {
  aDebugScenarioRun,
  aPage,
  aProblem,
  aRun,
  aScenarioAction,
  aScenarioDetail,
  aScenarioPlan,
  aScenarioPlanRow,
  aScenarioRunRef,
  aTreeDocument,
  at,
  renderWithApi,
  SCENARIO_RUN,
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

// A scenario written as blocks whose cards say everything a Blocks row says: an action with a
// short value, a long one and a JSON body (both only counted), then a check.
const CARDS = {
  version: 2,
  kind: "scenario",
  name: "order-lifecycle",
  revision: 1,
  inputs: { external_ref: { required: true } },
  stages: [
    {
      name: "Fetch order",
      steps: [
        {
          do: "send-queue-message",
          with: {
            region: "eu-west-1",
            note: "Ship the order to the depot at example.com before noon today",
            body: { order_id: "DEMO-1234" },
          },
        },
        {
          wait_until: "get-order-by-ref",
          until: "$self.output.status == 'ON_HOLD'",
          every: "10s",
          timeout: "5m",
        },
      ],
    },
  ],
};

// The blocks of CARDS as the API lists them, and a scenario run of it at block 1.2.
const CARD_BLOCKS = [
  { address: "1", kind: "stage", label: "Fetch order", entry_nodes: ["fetch-order--1"] },
  { address: "1.1", kind: "do", label: "send-queue-message", entry_nodes: ["fetch-order--1"] },
  {
    address: "1.2",
    kind: "wait_until",
    label: "get-order-by-ref",
    entry_nodes: ["fetch-order--2"],
  },
];
const CARDS_RUN = {
  [`/api/v1/workflow-runs/${SCENARIO_RUN}`]: aRun({
    id: SCENARIO_RUN,
    kind: "scenario",
    workflow: "scenario:order-lifecycle",
    content_hash: "sha256:5f0c2e1d",
    revision: 1,
    status: "running",
    steps: [],
  }),
  [`/api/v1/scenario-runs/${SCENARIO_RUN}`]: aDebugScenarioRun({
    debug: null,
    breakpoints: [],
    timeline: [
      { event: "start", node: null, attempt: null, status: null, at: at(0), block: null },
      {
        event: "step_start",
        node: "fetch-order--1",
        attempt: 1,
        status: null,
        at: at(5),
        block: "1.1",
      },
      {
        event: "step_end",
        node: "fetch-order--1",
        attempt: 1,
        status: "ok",
        at: at(10),
        block: "1.1",
      },
      {
        event: "step_start",
        node: "fetch-order--2",
        attempt: 1,
        status: null,
        at: at(11),
        block: "1.2",
      },
    ],
    polls: [],
    captures: [],
    blocks: CARD_BLOCKS.map(({ address, kind, label }) => ({ address, kind, label })),
  }),
};

/** A stylesheet of the web app, as written. */
const cssOf = (path: string) => readFileSync(join(process.cwd(), path), "utf8");
/** The body of a stylesheet's first top-level rule for exactly `selector`. */
const ruleOf = (css: string, selector: string): string => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rule = new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`).exec(css);
  if (!rule?.[1]) throw new Error(`no rule ${selector}`);
  return rule[1];
};
/** Every rule body of a stylesheet whose selector names `name` (`.st-column`, …). */
const rulesNaming = (css: string, name: string): string[] =>
  [...css.matchAll(/([^{}]*)\{([^}]*)\}/g)]
    .filter(([, selector]) =>
      new RegExp(`${name.replace(".", "\\.")}(?![\\w-])`).test(selector ?? ""),
    )
    .map(([, , body]) => body ?? "");

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

/** The hub's actions, with send-queue-message (the first step's) changed as given. */
function actionsWith(overrides: Parameters<typeof aScenarioAction>[0]) {
  return {
    ...library,
    items: [
      {
        ...library.items[0],
        action: aScenarioAction({
          ref: "orders/send-queue-message",
          name: "send-queue-message",
          effect: "write",
          ...overrides,
        }),
      },
      library.items[1],
    ],
  };
}

/** The scenario with its steps (and anything else of its document) as given. */
function detailWith(changes: Record<string, unknown>, environments?: unknown[]) {
  return aScenarioDetail({
    document: { ...document, ...changes },
    content_hash: "sha256:aaa",
    ...(environments ? { environments } : {}),
  } as Parameters<typeof aScenarioDetail>[0]);
}

/** A service the hub declares, with its address in the run bar's environment (personal). */
function aService(
  name: string,
  kind: string | null,
  resource: string | null,
  more: { repo?: string; description?: string | null } = {},
) {
  return {
    repo: more.repo ?? "",
    name,
    kind,
    description: more.description ?? null,
    endpoints:
      resource === null
        ? []
        : [{ environment: "personal", source: "hub.local.json", endpoint: { resource } }],
  };
}

/** The hub's configuration, as the builder reads it for its services. */
function configWith(services: ReturnType<typeof aService>[]) {
  return {
    project: "demo",
    local_file: null,
    repos: [],
    environments: {
      environments: [],
      services,
      blocked_words: [],
      blocked_files: [],
      blocked_env: [],
    },
  };
}

/** The send step's action with one service input, `target`. */
const SEND_TO_TARGET = actionsWith({
  inputs: [{ name: "target", type: "service", required: true, description: "Where it is sent." }],
});

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
    expect(await screen.findByText("No problems")).toBeInTheDocument();
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
    expect(await screen.findByText("No problems")).toBeInTheDocument();
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
    // Each card is the block as the Blocks list names it: its number, then its kind and title.
    expect(screen.getByRole("button", { name: /^Block 1\.1, / })).toBeInTheDocument();
    // Each stage is a band of its own, its blocks inside it.
    const band = screen.getByRole("region", { name: /^Stage 1: Fix shipping/ });
    const first = within(band).getByRole("button", { name: /^Block 1\.1, / });
    // A card selects its block; Open it in Blocks goes to it there.
    await user.click(first);
    expect(first).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Open it in Blocks" }));
    expect(await screen.findByRole("treeitem", { name: /^Step 1\.1,/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("scenario builder's Graph view draws each stage as a band between Start and End, its blocks left to right with an arrow between two", async () => {
    const user = userEvent.setup();
    renderTree("blocks-together");
    await screen.findByRole("treeitem", { name: /^Stage 1: Fix shipping/ });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    // AC-596.5.7: a band per stage, its number, name and how many blocks it holds.
    const band = await screen.findByRole("region", { name: "Stage 1: Fix shipping" });
    const head = band.querySelector("header");
    expect(head).toHaveTextContent(/^1Fix shipping5 blocks$/);
    // AC-596.5.7: Start before the first band and End after the last.
    const graph = band.parentElement ?? band;
    const start = within(graph).getByText("Start");
    const end = within(graph).getByText("End");
    expect(start.compareDocumentPosition(band) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(band.compareDocumentPosition(end) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // AC-596.5.8: the stage's blocks in the Blocks order, left to right, an arrow between two.
    const steps = [...(band.querySelector(":scope > .sg-flow")?.children ?? [])];
    expect(
      steps.map((step) => step.querySelector("[aria-label]")?.getAttribute("aria-label")),
    ).toEqual([
      expect.stringMatching(/^Block 1\.1, Wait until: /),
      "At the same time 1.2",
      expect.stringMatching(/^Block 1\.3, Run an action: /),
    ]);
    expect(steps.map((step) => step.querySelector(":scope > .sg-arrow") !== null)).toEqual([
      false,
      true,
      true,
    ]);
    // AC-596.5.8: the row wraps at the band's edge.
    const flow = cssOf("src/screens/scenarios/builder/builder.css");
    expect(flow.slice(flow.indexOf("\n.sg-flow {"))).toMatch(
      /^\n\.sg-flow \{[^}]*flex-wrap: wrap;/,
    );
  });

  it("scenario builder's Graph view frames an If with its condition and its two paths", async () => {
    // AC-596.5.9: If yes and Otherwise, each with its blocks.
    const user = userEvent.setup();
    renderTree("blocks-if-else");
    await screen.findByRole("treeitem", { name: /^Stage 1: Check/ });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    const frame = await screen.findByRole("group", { name: "If 1.2" });
    expect(frame.querySelector(".sg-frame-head")).toHaveTextContent(/^1\.2If .+/);
    const yes = within(frame).getByText("If yes").parentElement ?? frame;
    const otherwise = within(frame).getByText("Otherwise").parentElement ?? frame;
    expect(
      within(yes)
        .getAllByRole("button")
        .map((card) => card.getAttribute("aria-label")),
    ).toEqual([expect.stringMatching(/^Block 1\.2\.then\.1, Run an action: /)]);
    expect(
      within(otherwise)
        .getAllByRole("button")
        .map((card) => card.getAttribute("aria-label")),
    ).toEqual([expect.stringMatching(/^Block 1\.2\.else\.1, Ask me: /)]);
  });

  it("scenario builder's Graph view frames At the same time with a path per lane", async () => {
    // AC-596.5.9: Path 1, Path 2, each with its blocks in order.
    const user = userEvent.setup();
    renderTree("blocks-together");
    await screen.findByRole("treeitem", { name: /^Stage 1: Fix shipping/ });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    const frame = await screen.findByRole("group", { name: "At the same time 1.2" });
    expect(frame).toHaveTextContent("At the same time · 2 paths, then continues");
    const lane = (name: string) =>
      within(within(frame).getByText(name).parentElement ?? frame)
        .getAllByRole("button")
        .map((card) => card.getAttribute("aria-label")?.split(",")[0]);
    expect(lane("Path 1")).toEqual(["Block 1.2.p1.1"]);
    expect(lane("Path 2")).toEqual(["Block 1.2.p2.1", "Block 1.2.p2.2"]);
  });

  it("scenario builder's Graph view frames a Repeat around the blocks each round runs", async () => {
    // AC-596.5.9: the Repeat's card, then its round's blocks under "Each round, at most N".
    const user = userEvent.setup();
    renderTree("blocks-repeat");
    await screen.findByRole("treeitem", { name: /^Stage 1: Poll review/ });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    const frame = await screen.findByRole("group", { name: "Repeat 1.2" });
    expect(
      within(frame)
        .getAllByRole("button")
        .map((card) => card.getAttribute("aria-label")?.split(":")[0]),
    ).toEqual(["Block 1.2, Repeat", "Block 1.2.1, Run an action", "Block 1.2.2, Wait until"]);
    const round = within(frame).getByText(/^Each round, at most 5$/).parentElement ?? frame;
    expect(within(round).getAllByRole("button")).toHaveLength(2);
  });

  it("scenario builder's Graph card reads as its Blocks row: number, kind tile, title, sentence, tech line, effect, Draft and problems", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [DETAIL]: aScenarioDetail({ document: CARDS, content_hash: "sha256:aaa", version: 2 }),
      "/api/v1/projects/demo/actions": {
        ...library,
        items: [
          {
            ...library.items[0],
            action: aScenarioAction({
              ref: "orders/send-queue-message",
              name: "send-queue-message",
              effect: "write",
              draft: true,
            }),
          },
          library.items[1],
        ],
      },
      [VALIDATE]: () => ({
        loads: false,
        yaml: "",
        problems: [
          {
            node: "fetch-order--1",
            key: "stages[0].steps[0].with",
            line: null,
            message: "region is not a region",
            severity: "error",
          },
        ],
        nodes: [],
      }),
    });
    await screen.findByText("1 problem");
    // Each row's kind and title (its name up to the first full stop), sentence and tech line.
    const rows = ["1.1", "1.2"].map((number) => {
      const row = screen.getByRole("treeitem", { name: new RegExp(`^Step ${number},`) });
      const label = (row.getAttribute("aria-label") ?? "").replace(/\s+/g, " ");
      const named = /^Step [\d.]+, ([^.]+)\./.exec(label);
      return [
        named?.[1] ?? "",
        ...[".st-detail", ".st-tech"].map((part) => row.querySelector(part)?.textContent ?? null),
      ];
    });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    const send = await screen.findByRole("button", { name: /^Block 1\.1, / });
    const check = screen.getByRole("button", { name: /^Block 1\.2, / });
    // AC-596.5.1: the number, kind tile and title the Blocks list gives the block.
    expect(send).toHaveAccessibleName(`Block 1.1, ${rows[0]?.[0] ?? ""}`);
    expect(check).toHaveAccessibleName(`Block 1.2, ${rows[1]?.[0] ?? ""}`);
    expect(send).toHaveAccessibleName(/^Block 1\.1, Run an action: \S/);
    expect(send.querySelector(".sg-title")).toHaveTextContent(
      (rows[0]?.[0] ?? "").replace("Run an action: ", ""),
    );
    expect(send.querySelector(".sg-num")).toHaveTextContent(/^1\.1$/);
    expect(send.querySelector(".st-tile")).toHaveAttribute("aria-hidden", "true");
    // AC-596.5.2: the same sentence and quiet technical line as the Blocks row.
    for (const [card, row] of [
      [send, rows[0]],
      [check, rows[1]],
    ] as const) {
      expect(
        [".sg-sentence", ".sg-tech"].map((part) => card.querySelector(part)?.textContent ?? null),
      ).toEqual(row?.slice(1));
    }
    expect(check.querySelector(".sg-sentence")).toHaveTextContent("checks every 10 s, up to 5 min");
    expect(check.querySelector(".sg-tech")).toHaveTextContent(/^get-order-by-ref$/);
    // AC-596.5.3: a long value and a JSON body are only counted; the tooltip has them whole.
    expect(send.querySelector(".sg-tech")).toHaveTextContent(
      /^send-queue-message·region eu-west-1·\+2 values$/,
    );
    expect(send.getAttribute("title")).toContain(
      "note Ship the order to the depot at example.com before noon today",
    );
    expect(send.getAttribute("title")).toContain('body {"order_id":"DEMO-1234"}');
    // AC-596.5.4: the effect in words, Draft, and how many problems the block has.
    const foot = send.querySelector(".sg-foot");
    await waitFor(() => {
      expect(foot).toHaveTextContent("Changes data");
    });
    expect(foot).toHaveTextContent("Draft");
    expect(foot).toHaveTextContent("1 problem");
    expect(check.querySelector(".sg-foot")).toHaveTextContent(/^Reads only$/);
  });

  it("scenario builder's Graph card of a graph scenario reads as its Blocks row too", async () => {
    // AC-596.5.1 / AC-596.5.2 / AC-596.5.4: a version 1 scenario's cards, as its Blocks rows.
    const user = userEvent.setup();
    renderBuilder();
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    await waitFor(() => {
      expect(within(tree).getByRole("treeitem", { name: FETCH })).toHaveTextContent("Changes data");
    });
    const rows = [FETCH, CHECK].map((name) => {
      const row = within(tree).getByRole("treeitem", { name });
      return [".st-title", ".st-detail", ".st-tech"].map(
        (part) => row.querySelector(part)?.textContent ?? null,
      );
    });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    const fetch = await screen.findByRole("button", {
      name: "Block 1, Run an action: Fetch order",
    });
    const check = screen.getByRole("button", {
      name: "Block 2, Wait until: Wait until status is ON_HOLD",
    });
    for (const [card, row] of [
      [fetch, rows[0]],
      [check, rows[1]],
    ] as const) {
      expect(card.querySelector(".sg-num")).toBeInTheDocument();
      expect(card.querySelector(".st-tile")).toBeInTheDocument();
      expect(
        [".sg-title", ".sg-sentence", ".sg-tech"].map(
          (part) => card.querySelector(part)?.textContent ?? null,
        ),
      ).toEqual(row);
    }
    expect(fetch.querySelector(".sg-foot")).toHaveTextContent(/^Changes data$/);
    expect(check.querySelector(".sg-foot")).toHaveTextContent(/^Reads only$/);
  });

  it("scenario builder's Graph view shows each block's state in the shown scenario run and marks the block it is at", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: CARDS,
        content_hash: "sha256:aaa",
        version: 2,
        blocks: CARD_BLOCKS,
        runs: [aScenarioRunRef({ status: "running" })],
      }),
      ...CARDS_RUN,
    });
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    await waitFor(() => {
      expect(within(tree).getByRole("treeitem", { name: /^Step 1\.1,/ })).toHaveTextContent("Done");
    });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    // AC-596.5.5: each card shows its block's state in the run, as Blocks does.
    const done = await screen.findByRole("button", { name: /^Block 1\.1, / });
    const running = screen.getByRole("button", { name: /^Block 1\.2, / });
    expect(done.querySelector(".sg-foot")).toHaveTextContent("Done");
    expect(running.querySelector(".sg-foot")).toHaveTextContent(/Running/);
    // AC-596.5.10: the block the scenario run is at is marked as current.
    expect(running.parentElement).toHaveAttribute("data-current", "true");
    expect(done.parentElement).not.toHaveAttribute("data-current");
  });

  it("scenario builder's Graph view says Back to Blocks while nothing is selected, and goes back", async () => {
    // AC-596.5.11: with nothing selected, the button reads Back to Blocks.
    const user = userEvent.setup();
    renderTree("blocks-together");
    await screen.findByRole("treeitem", { name: /^Stage 1: Fix shipping/ });
    await user.click(screen.getByRole("button", { name: "Graph" }));

    await user.click(await screen.findByRole("button", { name: "Back to Blocks" }));
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    expect(within(tree).queryByRole("treeitem", { selected: true })).not.toBeInTheDocument();
  });

  it("scenario builder's Graph card is neutral: no coloured edge, no lift, no entry animation", () => {
    // AC-596.5.6: kind shows by its tile only; selected is an accent border.
    const css = cssOf("src/screens/scenarios/builder/builder.css");
    const rules = [...css.matchAll(/([^{}]*\.sg-card[^{}]*)\{([^}]*)\}/g)].map(
      ([, selector, body]) => [selector?.trim() ?? "", body ?? ""] as const,
    );
    expect(rules.length).toBeGreaterThan(0);
    for (const [, body] of rules) {
      expect(body).not.toMatch(/border-top|animation|transform|translate/);
    }
    const selected = rules.find(([selector]) => selector === ".sg-card[data-selected]");
    expect(selected?.[1]).toContain("border-color: var(--accent);");
  });

  describe("scenario builder layout rules", () => {
    const steps = cssOf("src/screens/scenarios/builder/steps.css");
    const builder = cssOf("src/screens/scenarios/builder/builder.css");
    const blocks = cssOf("src/screens/scenarios/builder/blocks.css");
    const tokens = cssOf("src/styles/tokens.css");
    const px = (token: string) => {
      const value = new RegExp(`--${token}: (\\d+)px;`).exec(tokens)?.[1];
      if (value === undefined) throw new Error(`no token ${token}`);
      return Number(value);
    };

    it("scenario builder keeps the blocks against the left column inside a capped page box", () => {
      // AC-596.2.30: the blocks column is at most 960px with no auto margin (never centred
      // away from the palette), and the page box is capped at 1920px.
      const column = ruleOf(steps, ".st-column");
      expect(column).toContain("max-width: 960px;");
      expect(column).toMatch(/\n\s*margin: 0;/);
      for (const body of [steps, builder, blocks].flatMap((css) =>
        rulesNaming(css, ".st-column"),
      )) {
        expect(body).not.toMatch(/margin[\w-]*:[^;]*auto/);
      }
      const page = ruleOf(steps, ".sb-page");
      expect(page).toContain("max-width: 1920px;");
      expect(page).toContain("width: 100%;");
    });

    it("scenario builder groups the run bar's controls and leaves the environment select room", () => {
      // AC-596.2.41: a separator between the groups; the environment select is wide enough
      // for its name and its arrow.
      const sep = ruleOf(steps, ".sb-runbar-sep");
      expect(sep).toContain("width: 1px;");
      expect(sep).toContain("align-self: stretch;");
      expect(sep).toContain("background: var(--border);");
      expect(ruleOf(steps, ".sb-runbar-controls .sb-env select")).toContain("min-width: 240px;");
    });

    it("scenario builder keeps a step's title a readable minimum width when its right side is full", () => {
      // AC-596.2.43: the title's column never shrinks under 160px; the right side wraps.
      expect(ruleOf(steps, ".st-row")).toMatch(
        /grid-template-columns: [^;]*minmax\(160px, 1fr\) minmax\(0, auto\);/,
      );
      const right = ruleOf(steps, ".st-right");
      expect(right).toContain("flex-wrap: wrap;");
      expect(right).toContain("min-width: 0;");
    });

    it("scenario builder shows an editable plain value on one line, cut with an ellipsis", () => {
      // AC-596.3.8: the chip does not wrap; its text is ellipsed inside it.
      const chip = ruleOf(steps, ".st-chip-edit");
      expect(chip).toContain("white-space: nowrap;");
      expect(chip).toContain("max-width: 100%;");
      const text = ruleOf(steps, ".st-chip-text");
      expect(text).toContain("text-overflow: ellipsis;");
      expect(text).toContain("overflow: hidden;");
      expect(text).toContain("min-width: 0;");
    });

    it("scenario builder runs an open step's body left to right at the row's full width", () => {
      // AC-596.3.26: its cells stretch, not centred.
      const body = ruleOf(steps, ".st-g-body");
      expect(body).toContain("flex-direction: column;");
      expect(body).toContain("align-items: stretch;");
    });

    it("scenario builder insets an open step's part as much on its left as on its right", () => {
      // AC-596.3.28: the row's 4px plus the open part's own padding equal the row's right 12px.
      const row =
        /\n\s*padding: var\(--([\w-]+)\) var\(--([\w-]+)\) var\(--([\w-]+)\) var\(--([\w-]+)\);/.exec(
          ruleOf(steps, ".st-row"),
        );
      if (!row) throw new Error("no padding on .st-row");
      const [, , right = "", , left = ""] = row;
      const open = /padding-left: var\(--([\w-]+)\);/.exec(ruleOf(steps, ".st-open-group"));
      if (!open?.[1]) throw new Error("no padding-left on .st-open-group");
      expect(px(left)).toBe(4);
      expect(px(left) + px(open[1])).toBe(px(right));
      expect(px(right)).toBe(12);
    });
  });

  it("scenario builder's Graph view of a scenario written as blocks has no serious a11y violation (a11y)", async () => {
    // AC-596.5.13: bands as regions, frames as groups, cards as buttons.
    const user = userEvent.setup();
    const { container } = renderTree("blocks-nested");
    await screen.findByRole("treeitem", { name: /^Stage 1: Route order/ });
    await user.click(screen.getByRole("button", { name: "Graph" }));
    await screen.findByRole("region", { name: "Stage 1: Route order" });

    expect(await seriousViolations(container)).toEqual([]);
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
    // AC-596.5.17: the scenario as blocks is coloured as YAML.
    await waitFor(() => {
      expect(
        within(dialog).getByLabelText("The scenario as blocks").querySelector("code"),
      ).toHaveClass("hljs");
    });
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

  it("scenario builder plans after a value left the form when another environment gives it", async () => {
    // AC-596.2.5: only the inputs the form asks for are checked and required; a value kept for
    // one that left it (the environment now gives it) blocks nothing and is not sent empty.
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: {
          ...document,
          inputs: { ...document.inputs, count: { type: "integer", required: true } },
        },
        content_hash: "sha256:aaa",
        environments: [
          { name: "personal", access: "write", production: false, values: { external_ref: "T-9" } },
          {
            name: "qa",
            access: "read",
            production: false,
            values: { external_ref: "T-9", count: "3" },
          },
        ],
      }),
      [`POST ${DETAIL}/plan`]: aScenarioPlan(),
    });

    await screen.findByText("No problems");
    await user.click(screen.getByRole("button", { name: "Plan in personal" }));
    const form = screen.getByRole("form", { name: "Values to plan with" });
    const count = within(form).getByRole("spinbutton", { name: "count" });
    await user.type(count, "5");
    await user.clear(count);

    // qa gives count: the form no longer shows it, so the empty value kept for it is ignored.
    await user.selectOptions(screen.getByRole("combobox", { name: "Environment" }), "qa");
    const open = screen.getByRole("form", { name: "Values to plan with" });
    expect(within(open).queryByRole("spinbutton", { name: "count" })).not.toBeInTheDocument();
    await user.click(within(open).getByRole("button", { name: "Plan in qa" }));
    await waitFor(() => {
      expect(requests.some((request) => request.url.endsWith("/plan"))).toBe(true);
    });
    const sent = requests.find((request) => request.url.endsWith("/plan"));
    expect(await sent?.clone().json()).toEqual({ environment: "qa", inputs: {} });
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

  it("scenario builder words an expect step's stop in its Inspector by the scenario run mode", async () => {
    // AC-596.2.4: the step's stop follows the run bar's mode: Interactive pauses for a
    // read-only agent, Regression fails the scenario run.
    const user = userEvent.setup();
    renderBuilder();

    await user.click(await screen.findByRole("treeitem", { name: CHECK }));
    const editor = screen.getByRole("region", { name: "Inspector: Wait until order-on-hold" });
    await user.click(within(editor).getByRole("button", { name: /^Where it can stop: / }));
    expect(
      within(editor).getByText(
        "If its condition (status is 'ON_HOLD') still does not hold after 5 min, the scenario run pauses and a read-only agent investigates with you (Interactive).",
      ),
    ).toBeInTheDocument();
    expect(within(editor).queryByText(/\(Regression\)/)).not.toBeInTheDocument();

    const mode = screen.getByRole("group", { name: "Scenario run mode" });
    await user.click(within(mode).getByRole("button", { name: "Regression" }));
    expect(
      within(editor).getByText(
        "If its condition (status is 'ON_HOLD') still does not hold after 5 min, the scenario run fails here (Regression).",
      ),
    ).toBeInTheDocument();
    expect(within(editor).queryByText(/\(Interactive\)/)).not.toBeInTheDocument();
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

    await screen.findByText("No problems");
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

    // The "+" is the pointer's way: hidden from the tree, which holds only its items.
    await user.click(await screen.findByTitle("Add a step after step 1"));
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
    // The open step lists the value under its name.
    expect(fetch).toHaveTextContent(/external_ref.*T-1/);
    // AC-596.3.3: on the same row, the value right after its own name.
    const set = within(fetch).getByRole("button", { name: "Edit external_ref: T-1" });
    expect(set.closest(".st-g-row")?.querySelector(".st-g-label")).toHaveTextContent(
      /^external_ref$/,
    );

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

    await screen.findByText("No problems");
    await user.click(screen.getByRole("button", { name: "YAML" }));

    expect(screen.getByLabelText("Generated YAML")).toHaveTextContent("kind: scenario");
    // Coloured as YAML, as every file and code the page shows.
    await waitFor(() => {
      expect(screen.getByLabelText("Generated YAML").querySelector("code")).toHaveClass("hljs");
    });
  });

  it("scenario builder renames a step in place with F2, and Esc leaves it as it was", async () => {
    const user = userEvent.setup();
    renderBuilder();
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const fetch = within(tree).getByRole("treeitem", { name: FETCH });

    fetch.focus();
    await user.keyboard("{F2}");
    const field = screen.getByRole("textbox", { name: "What 1 does" });
    expect(field).toHaveFocus();
    await user.clear(field);
    await user.type(field, "Send the order message{Enter}");

    expect(
      within(tree).getByRole("treeitem", { name: /Run an action: Send the order message/ }),
    ).toHaveFocus();
    expect(screen.getByText("Unsaved")).toBeInTheDocument();

    await user.keyboard("{F2}");
    await user.type(screen.getByRole("textbox", { name: "What 1 does" }), " twice{Escape}");
    expect(
      within(tree).getByRole("treeitem", { name: /Run an action: Send the order message\./ }),
    ).toBeInTheDocument();
  });

  it("scenario builder edits a step's timing on the step itself", async () => {
    const user = userEvent.setup();
    renderBuilder();
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    await user.click(within(tree).getByRole("treeitem", { name: CHECK }));

    await user.click(
      within(tree).getByRole("button", {
        name: "Edit how often it checks: every 10 s, up to 5 min",
      }),
    );
    const field = screen.getByRole("textbox", { name: "How often 2 checks" });
    await user.clear(field);
    await user.type(field, "30s{Enter}");

    expect(within(tree).getByRole("treeitem", { name: CHECK })).toHaveTextContent(
      "every 30 s, up to 5 min",
    );
  });

  it("scenario builder duplicates and deletes a step from its quick actions", async () => {
    const user = userEvent.setup();
    renderBuilder();
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });

    await user.click(within(tree).getByRole("button", { name: "Duplicate step 1 (⌘D)" }));
    expect(within(tree).getAllByRole("treeitem", { name: /Run an action/ })).toHaveLength(2);

    await user.click(within(tree).getByRole("button", { name: "Delete step 1 (Delete)" }));
    expect(within(tree).getAllByRole("treeitem", { name: /Run an action/ })).toHaveLength(1);
    expect(screen.getByText(/^Deleted step /)).toBeInTheDocument();
  });

  it("scenario builder keeps the run panel beside the steps while no step is open", async () => {
    const user = userEvent.setup();
    renderBuilder();
    const panel = await screen.findByRole("complementary", {
      name: "Scenario runs of order-lifecycle",
    });
    expect(within(panel).getByRole("region", { name: "Scenario runs" })).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Run order-lifecycle" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scenario run" })).toBeDisabled();

    // Opening a step in the editor covers the run panel; the run bar stays.
    await user.click(screen.getByRole("treeitem", { name: FETCH }));
    expect(
      screen.queryByRole("complementary", { name: "Scenario runs of order-lifecycle" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Run order-lifecycle" })).toBeInTheDocument();
  });

  it("scenario builder opens a selected step in place with its JSON body indented", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: {
          ...document,
          nodes: [
            {
              id: "fetch-order",
              type: "action",
              action: "send-queue-message",
              with: { body: '{"event_type":"FETCH_ORDERS","minutes":$INPUTS.external_ref}' },
            },
            ...document.nodes.slice(1),
          ],
        },
        content_hash: "sha256:aaa",
      }),
    });
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const fetch = within(tree).getByRole("treeitem", { name: FETCH });
    expect(within(fetch).queryByLabelText("body, as JSON")).not.toBeInTheDocument();

    await user.click(fetch);
    const body = within(fetch).getByLabelText("body, as JSON");
    expect(body.textContent).toContain('"event_type": "FETCH_ORDERS",\n');
    // The bare reference reads as the builder's token, as on the closed row.
    expect(within(body).getByTitle("Scenario input external_ref")).toHaveTextContent(
      "external_ref",
    );
    // The open step reads in order: what it does, its values, then the values from earlier.
    expect(within(fetch).getByText("What it does")).toBeInTheDocument();
    // AC-596.3.20: in that order.
    expect(
      within(within(fetch).getByRole("group", { name: "Step 1 settings" }))
        .getAllByRole("region")
        .map((region) => region.getAttribute("aria-label")),
    ).toEqual(["What it does", "Values for this step", "Values from earlier"]);
    expect(
      within(fetch).getByText("Scenario input · asked when the scenario run starts"),
    ).toBeInTheDocument();
  });

  it("scenario builder folds the code an open step runs, coloured, its script apart from its action file", async () => {
    const user = userEvent.setup();
    renderBuilder();
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const fetch = within(tree).getByRole("treeitem", { name: FETCH });
    await user.click(fetch);

    const script = within(fetch).getByLabelText(
      "Text of actions/orders/scripts/send_queue_message.py",
    );
    // Folded until asked for.
    expect(script).not.toBeVisible();
    await user.click(within(fetch).getByText("Show the code it runs"));
    expect(script).toBeVisible();
    expect(script).toHaveTextContent("print('{}')");
    // Coloured as Python, its file says it is the one that runs; the action file only declares.
    await waitFor(() => {
      expect(script.querySelector("code")).toHaveClass("hljs");
    });
    expect(within(fetch).getByText("Runs.")).toBeInTheDocument();
    // AC-596.3.14: said where it shows.
    expect(within(fetch).getByText("Runs.")).toBeVisible();
    // The action file is the other tab, as in the side panel.
    await user.click(within(fetch).getByRole("tab", { name: "Action file" }));
    expect(within(fetch).getByText("Declares.")).toBeInTheDocument();
    expect(within(fetch).getByText("Declares.").closest(".sc-file")).toHaveTextContent(
      "name: send-queue-message",
    );
    expect(within(fetch).getByText("Declares.")).toBeVisible();
    expect(
      within(fetch).getByLabelText("Text of actions/orders/send-queue-message.yaml"),
    ).toBeVisible();
  });

  it("scenario builder picks where a step sends from the environment's services, by search", async () => {
    const user = userEvent.setup();
    const send = aScenarioAction({
      ref: "orders/send-queue-message",
      name: "send-queue-message",
      effect: "write",
      inputs: [
        { name: "target", type: "service", required: true, description: "Where it is sent." },
      ],
    });
    const service = (name: string, kind: string, resource: string) => ({
      repo: "",
      name,
      kind,
      description: null,
      endpoints: [{ environment: "personal", source: "hub.local.json", endpoint: { resource } }],
    });
    renderBuilder({
      "/api/v1/projects/demo/actions": {
        ...library,
        items: [{ ...library.items[0], action: send }, library.items[1]],
      },
      "/api/v1/projects/demo/config": {
        project: "demo",
        local_file: null,
        repos: [],
        environments: {
          environments: [],
          services: [
            service("orders-queue", "sqs", "orders-queue-personal"),
            service("payments-queue", "sqs", "payments-queue-personal"),
            service("orders-db", "database", "db.example.com:5432/orders"),
          ],
          blocked_words: [],
          blocked_files: [],
          blocked_env: [],
        },
      },
    });
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const fetch = within(tree).getByRole("treeitem", { name: FETCH });
    await user.click(fetch);

    // Never free text: a field opens the services of the environment, grouped by kind.
    // AC-596.4.1: in the open step too, the input is a field, not a text box.
    expect(within(fetch).queryByRole("textbox", { name: /target/ })).not.toBeInTheDocument();
    await user.click(within(fetch).getByRole("button", { name: "target: choose a service" }));
    const picker = screen.getByRole("dialog", { name: "Choose target" });
    expect(within(picker).getByText("Queues (SQS)")).toBeInTheDocument();
    expect(within(picker).getByText("Databases")).toBeInTheDocument();
    // AC-596.4.2: kinds in a fixed order (databases before queues), then by name.
    expect(
      [...picker.querySelectorAll(".bk-menu-group")].map((group) => group.textContent),
    ).toEqual(["Databases", "Queues (SQS)"]);
    expect(
      within(picker)
        .getAllByRole("option")
        .map((option) => option.querySelector(".bk-menu-label")?.textContent),
    ).toEqual(["orders-db", "orders-queue", "payments-queue"]);
    await user.type(within(picker).getByRole("combobox"), "payments");
    expect(within(picker).getAllByRole("option")).toHaveLength(1);
    await user.keyboard("{Enter}");

    expect(screen.queryByRole("dialog", { name: "Choose target" })).not.toBeInTheDocument();
    const field = within(fetch).getByRole("button", { name: "target: payments-queue" });
    // The address is the field's tooltip (and the list's second line), not repeated in it.
    expect(field).toHaveAttribute("title", "payments-queue-personal");
    // AC-596.3.17: the field has the shared field look, as the kind select beside it.
    expect(field).toHaveClass("ah-input");
    expect(screen.getByText("Unsaved")).toBeInTheDocument();
    // No kind was chosen: the picked service sets it.
    const kind = within(fetch).getByRole("combobox", { name: "Kind of service for target" });
    expect(kind).toHaveValue("sqs");
    // The kind takes the input name's place; the name moves to the note under it.
    // The note follows the service picked: its kind and its address, not the action's words.
    expect(kind.closest(".st-g-row")).toHaveTextContent(
      "target · Required · Queue (SQS) · payments-queue-personal",
    );
    // AC-596.4.14: the kind stands in the label column, where the input's name was.
    const label = kind.closest(".st-g-label");
    expect(label).not.toBeNull();
    expect(label).not.toHaveTextContent("target");
    // AC-596.4.11: "Any kind" first, then each declared kind.
    expect(
      within(kind)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Any kind", "Database", "Queue (SQS)"]);
    // A kind chosen filters the list.
    await user.selectOptions(kind, "database");
    await user.click(within(fetch).getByRole("button", { name: "target: payments-queue" }));
    const filtered = screen.getByRole("dialog", { name: "Choose target" });
    expect(
      within(filtered)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([expect.stringContaining("orders-db")]);
    // AC-596.4.11: its header names the kind chosen.
    expect(filtered).toHaveTextContent("Choose target · Database in personal");
    await user.keyboard("{Escape}");
    // AC-596.4.6: Esc closes the list and changes nothing.
    expect(screen.queryByRole("dialog", { name: "Choose target" })).not.toBeInTheDocument();
    expect(within(fetch).getByRole("button", { name: "target: payments-queue" })).toBeVisible();
    // The side panel picks it the same way: a field, never a text box.
    const panel = screen.getByRole("region", { name: /^Inspector: / });
    expect(
      within(panel).getByRole("button", { name: "target: payments-queue" }),
    ).toBeInTheDocument();
    expect(within(panel).queryByRole("textbox", { name: /target/ })).not.toBeInTheDocument();
    // AC-596.4.10: the side panel keeps the input's own description under its field, beside
    // the field's note on the service picked; the open step's note never shows it (AC-596.4.16).
    const panelField = within(panel).getByRole("button", { name: "target: payments-queue" });
    expect(panelField.closest(".ah-stack")).toHaveTextContent("Where it is sent.");
    expect(kind.closest(".st-g-row")).not.toHaveTextContent("Where it is sent.");
  });

  it("scenario builder has no serious a11y violation with a service input open and its list shown (a11y)", async () => {
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": {
        ...library,
        items: [
          {
            ...library.items[0],
            action: aScenarioAction({
              ref: "orders/send-queue-message",
              name: "send-queue-message",
              effect: "write",
              inputs: [{ name: "target", type: "service", required: true }],
            }),
          },
          library.items[1],
        ],
      },
      "/api/v1/projects/demo/config": {
        project: "demo",
        local_file: null,
        repos: [],
        environments: {
          environments: [],
          services: [
            {
              repo: "",
              name: "orders-queue",
              kind: "sqs",
              description: null,
              endpoints: [
                {
                  environment: "personal",
                  source: "hub.local.json",
                  endpoint: { resource: "orders-queue-personal" },
                },
              ],
            },
          ],
          blocked_words: [],
          blocked_files: [],
          blocked_env: [],
        },
      },
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    // The page's body (the list opens on it); `document` here is the scenario's fixture.
    expect(await seriousViolations(globalThis.document.body)).toEqual([]);
    await user.click(within(fetch).getByRole("button", { name: "target: choose a service" }));
    expect(screen.getByRole("dialog", { name: "Choose target" })).toBeInTheDocument();
    // AC-596.3.29, AC-596.4.2: checked with the list's rows shown, its group heading and icon.
    const list = screen.getByRole("listbox", { name: "Services" });
    expect(within(list).getByRole("option", { name: /orders-queue/ })).toBeInTheDocument();
    expect(within(list).getByText("Queues (SQS)")).toBeInTheDocument();
    expect(await seriousViolations(globalThis.document.body)).toEqual([]);
  });

  it("scenario builder's open step says which values it still needs and that its action is a draft", async () => {
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": {
        ...library,
        items: [
          {
            ...library.items[0],
            action: aScenarioAction({
              ref: "orders/send-queue-message",
              name: "send-queue-message",
              effect: "write",
              draft: true,
              accept_command: "git add -- actions/orders/send-queue-message.yaml && git commit",
              inputs: [
                { name: "region_code", type: "string", required: true, description: "The region." },
              ],
            }),
          },
          library.items[1],
        ],
      },
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const open = within(fetch).getByRole("group", { name: "Step 1 settings" });

    // A required value nothing gives: counted on the group, named on its row.
    const values = within(open).getByRole("region", { name: "Values for this step" });
    expect(values).toHaveTextContent("1 needs a value");
    expect(values).toHaveTextContent("region_codeNeeds a value");
    expect(within(values).getByRole("button", { name: "Set it in the panel" })).toBeInTheDocument();
    // The draft says what it means and gives its commit command.
    expect(within(open).getByText("Draft: needs acceptance")).toBeInTheDocument();
    expect(
      within(open).getByRole("button", { name: "Copy the commit command for send-queue-message" }),
    ).toBeInTheDocument();
  });

  it("scenario builder's View control offers no Run view", async () => {
    // AC-596.2.1: the page is one screen; building and running share it.
    renderBuilder();
    const views = await screen.findByRole("group", { name: "View" });
    expect(
      within(views)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Blocks", "Graph", "YAML"]);
    expect(within(views).queryByRole("button", { name: "Run" })).toBeNull();
  });

  it("scenario builder opens a step's row menu from its More quick action", async () => {
    // AC-596.2.25: More (Shift F10) opens the same menu as a right-click.
    const user = userEvent.setup();
    renderBuilder();
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });

    await user.click(within(tree).getByRole("button", { name: "More for step 1 (Shift F10)" }));
    expect(screen.getByRole("menu", { name: /^Step / })).toBeInTheDocument();
  });

  it("scenario builder deletes a stage and its steps from its quick action", async () => {
    // AC-596.2.25: a stage's delete says it took its steps.
    const user = userEvent.setup();
    renderTree(REFERENCE);
    const tree = await screen.findByRole("tree", { name: /^Steps of / });

    await user.click(within(tree).getByRole("button", { name: "Delete stage 1 (Delete)" }));
    expect(screen.getByText("Deleted stage 1 and its steps.")).toBeInTheDocument();
    expect(within(tree).queryByRole("treeitem", { name: /^Stage \d+: Fetch order,/ })).toBeNull();
  });

  it("scenario builder's check counts the draft actions to commit and says where they are", async () => {
    // AC-596.2.29.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": {
        ...library,
        items: [
          {
            ...library.items[0],
            action: aScenarioAction({
              ref: "orders/send-queue-message",
              name: "send-queue-message",
              effect: "write",
              draft: true,
              accept_command: "git add -- actions/orders/send-queue-message.yaml && git commit",
            }),
          },
          library.items[1],
        ],
      },
    });

    const check = await screen.findByRole("button", {
      name: /^No problems ?· 1 draft action to commit$/,
    });
    expect(check).toHaveTextContent("No problems · 1 draft action to commit");
    await user.click(check);
    expect(screen.getByRole("dialog", { name: "Problems" })).toHaveTextContent(
      "Nothing to fix in the file. 1 draft action needs a commit before a scenario run can start: the commands are in Before you start.",
    );
  });

  it("scenario builder's check says the file has no problem when nothing is to fix", async () => {
    // AC-596.2.29.
    const user = userEvent.setup();
    renderBuilder();
    await user.click(await screen.findByRole("button", { name: /^No problems/ }));
    expect(screen.getByRole("dialog", { name: "Problems" })).toHaveTextContent(
      "The scenario file has no problem.",
    );
  });

  it("scenario builder keeps the + of each gap out of the tree", async () => {
    // AC-596.2.36: the tree holds only its items; the + is the pointer's way.
    renderBuilder();
    await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    expect(await screen.findByTitle("Add a step after step 1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a step after step 1" })).toBeNull();
  });

  it("scenario builder says what a step does in its action's first sentence", async () => {
    // AC-596.2.37: the sentence, then how often a wait checks.
    renderBuilder({
      "/api/v1/projects/demo/actions": {
        ...library,
        items: [
          {
            ...library.items[0],
            action: aScenarioAction({
              ref: "orders/send-queue-message",
              name: "send-queue-message",
              effect: "write",
              description: "Sends one message. More about the queue.",
            }),
          },
          library.items[1],
        ],
      },
    });
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const fetch = within(tree).getByRole("treeitem", { name: FETCH });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("Sends one message");
    });
    expect(fetch).not.toHaveTextContent("More about the queue");
    expect(within(tree).getByRole("treeitem", { name: CHECK })).toHaveTextContent(
      "checks every 10 s, up to 5 min",
    );
  });

  it("scenario builder only counts a JSON body on a closed row", async () => {
    // AC-596.2.38: a structured or long value is the open row's; closed, it reads +N value.
    renderBuilder({
      [DETAIL]: aScenarioDetail({
        document: {
          ...document,
          nodes: [
            { ...document.nodes[0], with: { body: '{"event_type":"FETCH","ids":[1]}' } },
            document.nodes[1],
          ],
        },
        content_hash: "sha256:aaa",
      }),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    expect(fetch).toHaveTextContent("+1 value");
    expect(fetch).not.toHaveTextContent("event_type");
  });

  it("scenario builder opens a step in place as one named group under its row, label then value", async () => {
    // AC-596.3.20: one group named "Step N settings", in task order.
    // AC-596.3.16: each row is its label, then its value, then a note across it.
    const user = userEvent.setup();
    renderSources();
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const fetch = within(tree).getByRole("treeitem", { name: FETCH });
    expect(within(fetch).queryByRole("group", { name: "Step 1 settings" })).toBeNull();

    await user.click(fetch);
    expect(fetch).toHaveAttribute("data-open", "true");
    const open = within(fetch).getByRole("group", { name: "Step 1 settings" });
    // A part of the row (spanning it), not a card beside it.
    expect(open.parentElement).toBe(fetch);
    expect(open).toHaveClass("st-open-group");
    expect(
      within(open)
        .getAllByRole("region")
        .map((region) => region.getAttribute("aria-label")),
    ).toEqual(["What it does", "Values for this step"]);
    // What it does: the action, with its runtime in words.
    const does = within(open).getByRole("region", { name: "What it does" });
    expect(does).toHaveTextContent("Actionsend-queue-messagePython");
    // Open, the row's own line 2 and technical line give way to the open part.
    expect(fetch.querySelector(".st-lines > .st-detail")).toBeNull();
    expect(fetch.querySelector(".st-lines > .st-tech")).toBeNull();
    const queue = within(open).getByRole("button", { name: "Edit queue: demo-events" });
    const row = queue.closest(".st-g-row");
    expect([...(row?.children ?? [])].map((cell) => cell.className)).toEqual([
      "st-g-label",
      "st-g-value",
      "st-g-note",
    ]);
  });

  it("scenario builder's open step names a value it sets with its input's note, and lists nothing it does not set", async () => {
    // AC-596.3.3: the value under the input's name, the input's description as its note.
    // AC-596.3.11: an input something else gives (the environment, a default) is not listed.
    const user = userEvent.setup();
    renderSources();
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);

    const values = within(fetch).getByRole("region", { name: "Values for this step" });
    const rows = [...values.querySelectorAll(".st-g-row")];
    expect(rows).toHaveLength(1);
    expect(rows[0]?.querySelector(".st-g-label")).toHaveTextContent(/^queue$/);
    expect(rows[0]?.querySelector(".st-g-value")).toHaveTextContent(/^demo-events$/);
    expect(rows[0]?.querySelector(".st-g-note")).toHaveTextContent(/^Required · The queue$/);
    expect(values).not.toHaveTextContent("aws_region");
    expect(values).not.toHaveTextContent("aws_account_id");
    expect(values).not.toHaveTextContent("external_ref");
  });

  it("scenario builder's open step edits a value from a Tab stop named by what it edits", async () => {
    // AC-596.3.25: each editable value is a Tab stop, "Edit <name>: <value>".
    const user = userEvent.setup();
    renderSources();
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const chip = within(fetch).getByRole("button", { name: "Edit queue: demo-events" });
    act(() => {
      fetch.focus();
    });
    for (let step = 0; step < 10 && globalThis.document.activeElement !== chip; step += 1) {
      await user.tab();
    }
    expect(chip).toHaveFocus();
    await user.keyboard("{Enter}");
    const field = within(fetch).getByRole("textbox", { name: "queue of 1" });
    await user.clear(field);
    await user.type(field, "demo-orders{Enter}");
    expect(within(fetch).getByRole("button", { name: "Edit queue: demo-orders" })).toBeVisible();
  });

  it("scenario builder keeps the selected step when Delete or Backspace is pressed inside its open part", async () => {
    // AC-596.3.25: a chip, the body, the code's summary take the key; only the row deletes.
    const user = userEvent.setup();
    renderBuilder({
      [DETAIL]: detailWith({
        nodes: [
          {
            ...document.nodes[0],
            with: { queue: "demo-events", body: '{"event_type":"FETCH_ORDERS"}' },
          },
          document.nodes[1],
        ],
      }),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);

    const chip = within(fetch).getByRole("button", { name: "Edit queue: demo-events" });
    const body = within(fetch).getByLabelText("body, as JSON");
    const summary = within(fetch).getByText("Show the code it runs");
    for (const [target, key] of [
      [chip, "{Backspace}"],
      [body, "{Delete}"],
      [summary, "{Backspace}"],
    ] as const) {
      act(() => {
        target.focus();
      });
      await user.keyboard(key);
      expect(screen.getByRole("treeitem", { name: FETCH })).toBe(fetch);
    }
    expect(screen.queryByText("Deleted step fetch-order.")).toBeNull();

    // The row itself, focused, still deletes it.
    act(() => {
      fetch.focus();
    });
    await user.keyboard("{Delete}");
    expect(screen.queryByRole("treeitem", { name: FETCH })).toBeNull();
    expect(screen.getByText("Deleted step fetch-order.")).toBeInTheDocument();
  });

  it("scenario builder's open step shows a check's timing and its until, and what a step keeps", async () => {
    // AC-596.3.20: What it does holds Checks and Until for a check; Keeps for later steps lists
    // each kept value as its token, with where it comes from.
    const user = userEvent.setup();
    renderBuilder({
      [DETAIL]: detailWith({
        nodes: [
          document.nodes[0],
          { ...document.nodes[1], capture: { order_status: "$self.output.status" } },
        ],
      }),
    });
    const check = await screen.findByRole("treeitem", { name: CHECK });
    await user.click(check);
    const open = within(check).getByRole("group", { name: "Step 2 settings" });
    const does = within(open).getByRole("region", { name: "What it does" });
    expect(does).toHaveTextContent("Checksevery 10 s, up to 5 min");
    expect(does).toHaveTextContent("Untilstatus is ON_HOLD");
    const keeps = within(open).getByRole("region", { name: "Keeps for later steps" });
    expect(within(keeps).getByTitle("Kept value order_status")).toHaveTextContent("order_status");
    expect(keeps).toHaveTextContent("from");
    expect(within(keeps).getByTitle("Output status of this step")).toBeInTheDocument();
    // Keeps comes last.
    expect(
      within(open)
        .getAllByRole("region")
        .map((region) => region.getAttribute("aria-label"))
        .at(-1),
    ).toBe("Keeps for later steps");
  });

  it("scenario builder's open step says where each value from earlier comes from, only from the steps before it", async () => {
    // AC-596.3.22: a scenario input (asked at start, from the environment, not asked), kept by
    // an earlier step with Go to, or not given by any earlier step.
    const user = userEvent.setup();
    renderBuilder({
      [DETAIL]: detailWith(
        {
          inputs: {
            external_ref: { type: "string", required: true },
            aws_account_id: { type: "string" },
          },
          nodes: [
            {
              ...document.nodes[0],
              with: {
                ref: "$INPUTS.external_ref_copy",
                account: "$INPUTS.aws_account_id",
                seen: "$CTX.order_status",
              },
            },
            { ...document.nodes[1], capture: { order_status: "$self.output.status" } },
            {
              id: "notify",
              type: "action",
              action: "send-queue-message",
              depends_on: ["order-on-hold"],
              with: { seen: "$CTX.order_status", ref: "$INPUTS.external_ref" },
              capture: { sent: "$self.output.status" },
            },
          ],
        },
        [
          {
            name: "personal",
            access: "write",
            production: false,
            values: { aws_account_id: "123456789012" },
          },
        ],
      ),
    });
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    const fetch = within(tree).getByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const earlier = within(fetch).getByRole("region", { name: "Values from earlier" });
    const rowOf = (title: string) => within(earlier).getByTitle(title).closest(".st-g-row");
    expect(rowOf("Scenario input aws_account_id")).toHaveTextContent(
      "Scenario input · 123456789012 from personal",
    );
    expect(rowOf("Scenario input external_ref_copy")).toHaveTextContent(
      "Not asked by the scenario",
    );
    // Kept by step 2 only, which runs after this one: not given before it.
    expect(rowOf("Kept value order_status")).toHaveTextContent("Not given by any earlier step");
    expect(within(earlier).queryByRole("button", { name: /^Go to/ })).toBeNull();

    // Step 3 reads what step 2 keeps: Go to 2 selects it.
    const notify = within(tree).getByRole("treeitem", { name: /Run an action: Notify/ });
    await user.click(notify);
    // In task order: what it does, its values, the values from earlier, what it keeps.
    expect(
      within(within(notify).getByRole("group", { name: "Step 3 settings" }))
        .getAllByRole("region")
        .map((region) => region.getAttribute("aria-label")),
    ).toEqual([
      "What it does",
      "Values for this step",
      "Values from earlier",
      "Keeps for later steps",
    ]);
    const later = within(notify).getByRole("region", { name: "Values from earlier" });
    expect(
      within(later).getByTitle("Kept value order_status").closest(".st-g-row"),
    ).toHaveTextContent("Kept by 2");
    expect(
      within(later).getByTitle("Scenario input external_ref").closest(".st-g-row"),
    ).toHaveTextContent("Scenario input · asked when the scenario run starts");
    await user.click(within(later).getByRole("button", { name: "Go to 2" }));
    expect(within(tree).getByRole("treeitem", { name: CHECK })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("scenario builder's open step lists a JSON body under its name, with Edit and Copy", async () => {
    // AC-596.3.21: Edit <name> opens the side panel's Settings at that field; Copy <name>.
    // AC-596.3.2: indented, its bare reference a token. AC-596.3.7: the body is coloured.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": actionsWith({
        inputs: [{ name: "body", type: "object", required: true, description: "The message." }],
      }),
      [DETAIL]: detailWith({
        nodes: [
          {
            ...document.nodes[0],
            with: { body: '{"event_type":"FETCH_ORDERS","minutes":$INPUTS.external_ref}' },
          },
          document.nodes[1],
        ],
      }),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const values = within(fetch).getByRole("region", { name: "Values for this step" });
    const body = within(values).getByLabelText("body, as JSON");
    expect(body.textContent).toBe(
      '{\n  "event_type": "FETCH_ORDERS",\n  "minutes": Scenario input external_ref\n}',
    );
    expect(within(body).getByText('"event_type"')).toHaveClass("ah-json-k");
    expect(within(body).getByText('"FETCH_ORDERS"')).toHaveClass("ah-json-s");
    expect(within(values).getByRole("button", { name: "Copy body" })).toBeInTheDocument();
    // The effect is the row's badge only, never said again in the open part.
    expect(within(fetch).getByRole("group", { name: "Step 1 settings" })).not.toHaveTextContent(
      "Changes data",
    );

    await user.click(within(values).getByRole("button", { name: "Edit body" }));
    const panel = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    expect(within(panel).getByRole("tab", { name: /Settings/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // At the body's field: its first row, shown as fields.
    await waitFor(() => {
      expect(panel.contains(globalThis.document.activeElement)).toBe(true);
    });
    expect(globalThis.document.activeElement?.tagName).toMatch(/^(INPUT|TEXTAREA|SELECT|BUTTON)$/);
  });

  it("scenario builder's Set it in the panel focuses that value's own field, region apart from region_code", async () => {
    // AC-596.3.23: counted on the group ("2 need a value"), each row opens the panel's Settings
    // at its own field, matched by its exact name.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": actionsWith({
        inputs: [
          { name: "region_code", type: "string", required: true, description: "The code." },
          { name: "region", type: "string", required: true, description: "The region." },
        ],
      }),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const values = within(fetch).getByRole("region", { name: "Values for this step" });
    expect(values).toHaveTextContent("2 need a value");
    const region = within(values).getByText("region", { exact: true }).closest(".st-g-row");
    if (!(region instanceof HTMLElement)) throw new Error("no row for region");
    expect(region).toHaveTextContent("regionNeeds a value");

    await user.click(within(region).getByRole("button", { name: "Set it in the panel" }));
    const panel = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    expect(within(panel).getByRole("tab", { name: /Settings/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() => {
      expect(within(panel).getByLabelText("region")).toHaveFocus();
    });
  });

  it("scenario builder's open step counts only the values it lists as needing one", async () => {
    // AC-596.3.23: under review, a service is not picked here, so it is neither listed nor
    // counted; the value that is listed is.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": actionsWith({
        inputs: [
          { name: "target", type: "service", required: true, description: null },
          { name: "region_code", type: "string", required: true, description: null },
        ],
      }),
      [`${DETAIL}/proposal`]: {
        path: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
        document: {
          ...document,
          nodes: [...document.nodes, { id: "notify", type: "action", action: "get-order-by-ref" }],
        },
        check: { loads: true, yaml: "", problems: [], nodes: [] },
        problem: null,
      },
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    // On the draft, both are listed and counted.
    expect(within(fetch).getByRole("region", { name: "Values for this step" })).toHaveTextContent(
      "2 need a value",
    );

    await user.click(await screen.findByRole("button", { name: "Review" }));
    await user.click(screen.getByRole("treeitem", { name: FETCH }));
    const shown = screen.getByRole("treeitem", { name: FETCH });
    expect(shown).toHaveAttribute("aria-selected", "true");
    const values = within(shown).getByRole("region", { name: "Values for this step" });
    expect(values).toHaveTextContent("1 needs a value");
    expect(values).not.toHaveTextContent("target");
  });

  it("scenario builder's open step needs a value the environment gives only through a scenario input, as its Script tab", async () => {
    // AC-596.3.23: an environment value for an input the scenario does not declare gives the
    // step nothing: Needs a value here, Missing in the Script tab.
    const user = userEvent.setup();
    renderSources({
      "/api/v1/projects/demo/actions": actionsWith({
        inputs: [
          { name: "queue", type: "string", required: true, description: "The queue" },
          { name: "region_hint", type: "string", required: true, description: null },
          { name: "aws_account_id", type: "string", required: true, description: null },
        ],
      }),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const values = within(fetch).getByRole("region", { name: "Values for this step" });
    expect(values).toHaveTextContent("1 needs a value");
    expect(values).toHaveTextContent("region_hintNeeds a value");
    // aws_account_id is a scenario input the environment gives.
    expect(values).not.toHaveTextContent("aws_account_id");

    const form = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    await user.click(await within(form).findByRole("button", { name: /View script/ }));
    const table = within(
      within(form).getByRole("region", { name: "How this step fills each input" }),
    ).getByRole("table");
    const rowOf = (input: string) =>
      within(table)
        .getAllByRole("row")
        .find((row) => within(row).queryByText(input) !== null);
    expect(rowOf("region_hint")).toHaveTextContent("Missing");
    expect(rowOf("aws_account_id")).toHaveTextContent("personal");
  });

  it("scenario builder's open step folds both files with Expand, each said for what it is", async () => {
    // AC-596.3.15: the same Script and Action file tabs as the side panel, with Expand.
    // AC-596.3.14: "Runs." and "Declares." say which file runs. AC-596.3.13: the language badge.
    const user = userEvent.setup();
    renderBuilder();
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    await user.click(within(fetch).getByText("Show the code it runs"));
    const script = within(fetch).getByText("Runs.").closest(".sc-file");
    if (!(script instanceof HTMLElement)) throw new Error("no script file");
    expect(within(script).getByText("Runs.")).toBeVisible();
    expect(within(script).getByText("Python")).toBeVisible();
    await user.click(within(fetch).getByRole("button", { name: "Expand" }));
    const dialog = screen.getByRole("dialog", {
      name: "actions/orders/scripts/send_queue_message.py · send-queue-message",
    });
    expect(dialog).toHaveTextContent("print('{}')");
    await user.keyboard("{Escape}");

    await user.click(within(fetch).getByRole("tab", { name: "Action file" }));
    expect(within(fetch).getByText("Declares.")).toBeVisible();
    const actionFile = within(fetch).getByLabelText(
      "Text of actions/orders/send-queue-message.yaml",
    );
    expect(actionFile).toBeVisible();
    expect(actionFile).toHaveTextContent("name: send-queue-message");
    expect(within(fetch).getByText("YAML")).toBeVisible();

    // The side panel's Script tab shows the same files, with no caption.
    const form = screen.getByRole("region", { name: "Inspector: Run an action fetch-order" });
    await user.click(await within(form).findByRole("button", { name: /View script/ }));
    const files = within(form).getByRole("region", { name: "Files" });
    expect(within(files).getByRole("tab", { name: "Script" })).toBeInTheDocument();
    expect(within(files).getByRole("button", { name: "Expand" })).toBeInTheDocument();
    expect(within(files).queryByText("Runs.")).toBeNull();
  });

  it("scenario builder's action panel shows the action's files in tabs, coloured, with their language", async () => {
    // AC-596.3.13: the side panel's files are coloured by their language and name it.
    const user = userEvent.setup();
    renderBuilder();
    await screen.findByRole("treeitem", { name: CHECK });
    await user.click(screen.getByRole("tab", { name: /Actions/ }));
    const list = screen.getByRole("list", { name: "Actions in this hub" });
    await user.click(within(list).getByRole("button", { name: /get-order-by-ref/ }));
    const panel = await screen.findByRole("complementary", { name: "Action get-order-by-ref" });
    const script = within(panel).getByLabelText(
      "Text of actions/orders/scripts/get_order_by_ref.py",
    );
    await waitFor(() => {
      expect(script.querySelector("code")).toHaveClass("hljs");
    });
    expect(within(panel).getByText("Python")).toBeVisible();
    // No Expand and no caption here: the panel is the larger view.
    expect(within(panel).queryByRole("button", { name: "Expand" })).toBeNull();
    expect(within(panel).queryByText("Runs.")).toBeNull();
    await user.click(within(panel).getByRole("tab", { name: "Action file" }));
    const actionFile = within(panel).getByLabelText("Text of actions/orders/get-order-by-ref.yaml");
    expect(actionFile).toBeVisible();
    expect(actionFile).toHaveTextContent("name: get-order-by-ref");
    expect(within(panel).getByText("YAML")).toBeVisible();
  });

  it("scenario builder's open step says what a service input needs before one is picked, and one not declared", async () => {
    // AC-596.3.27: nothing picked, the note says what to choose. AC-596.3.18: a value not
    // declared in the environment says so, with an icon.
    const user = userEvent.setup();
    const config = {
      project: "demo",
      local_file: null,
      repos: [],
      environments: {
        environments: [],
        services: [
          {
            repo: "",
            name: "orders-queue",
            kind: "sqs",
            description: null,
            endpoints: [
              {
                environment: "personal",
                source: "hub.local.json",
                endpoint: { resource: "orders-queue-personal" },
              },
            ],
          },
        ],
        blocked_words: [],
        blocked_files: [],
        blocked_env: [],
      },
    };
    renderBuilder({
      "/api/v1/projects/demo/actions": actionsWith({
        inputs: [
          { name: "target", type: "service", required: true, description: "Where it is sent." },
          { name: "copy_to", type: "service", required: false, description: null },
        ],
      }),
      "/api/v1/projects/demo/config": config,
      [DETAIL]: detailWith({
        nodes: [{ ...document.nodes[0], with: { copy_to: "ghost-queue" } }, document.nodes[1]],
      }),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const target = within(fetch).getByRole("button", { name: "target: choose a service" });
    expect(target.closest(".st-g-row")?.querySelector(".st-g-note")).toHaveTextContent(
      "target · Needs a value · Choose a service in personal",
    );
    const ghost = await within(fetch).findByRole("button", { name: "copy_to: ghost-queue" });
    expect(ghost).toHaveTextContent("not declared in personal");
    expect(ghost.querySelector("svg")).not.toBeNull();
  });

  it("scenario builder groups the services in the picker's order of kinds, each row with the service icon", async () => {
    // AC-596.4.2: kinds in a fixed order: the snapshot's (api, frontend, database, sqs, queue,
    // bucket, lambda, dynamodb, cognito), each kind Add service writes next to its like, a kind
    // hub web does not know after them and other last; every row has the service icon, the
    // current pick a check.
    const user = userEvent.setup();
    const kinds = [
      "other",
      "cache",
      "cognito",
      "dynamodb",
      "function",
      "lambda",
      "storage",
      "bucket",
      "queue",
      "sqs",
      "database",
      "web",
      "frontend",
      "api",
    ];
    renderBuilder({
      "/api/v1/projects/demo/actions": SEND_TO_TARGET,
      "/api/v1/projects/demo/config": configWith(
        kinds.map((kind) => aService(`${kind}-one`, kind, `${kind}.example.com`)),
      ),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    await user.click(within(fetch).getByRole("button", { name: "target: choose a service" }));
    const picker = screen.getByRole("dialog", { name: "Choose target" });
    expect(
      [...picker.querySelectorAll(".bk-menu-group")].map((group) => group.textContent),
    ).toEqual([
      "APIs and backends",
      "Frontends",
      "Frontends and portals",
      "Databases",
      "Queues (SQS)",
      "Queues and topics",
      "Buckets",
      "Storage buckets",
      "Functions",
      "Functions and jobs",
      "Tables (DynamoDB)",
      "User pools",
      "cache",
      "Other services",
    ]);
    const drawn = (name: "server" | "check") =>
      ICONS[name]
        .map(
          ([tag, attrs]) =>
            `<${tag}${Object.entries(attrs)
              .map(([attr, value]) => ` ${attr}="${value}"`)
              .join("")}></${tag}>`,
        )
        .join("");
    const icons = () =>
      within(screen.getByRole("dialog", { name: "Choose target" }))
        .getAllByRole("option")
        .map((option) => option.querySelector("svg")?.innerHTML);
    expect(icons()).toEqual(kinds.map(() => drawn("server")));

    await user.click(within(picker).getByRole("option", { name: /queue-one/ }));
    await user.click(within(fetch).getByRole("button", { name: "target: queue-one" }));
    await user.selectOptions(
      within(fetch).getByRole("combobox", { name: "Kind of service for target" }),
      "",
    );
    await user.click(within(fetch).getByRole("button", { name: "target: queue-one" }));
    const names = within(screen.getByRole("dialog", { name: "Choose target" }))
      .getAllByRole("option")
      .map((option) => option.querySelector(".bk-menu-label")?.textContent);
    expect(icons()).toEqual(names.map((name) => drawn(name === "queue-one" ? "check" : "server")));
  });

  it("scenario builder lists each service with its address in the run bar's environment, found by name, kind or address", async () => {
    // AC-596.4.3: each row has its address in the environment, or says it has none there.
    // AC-596.4.4: the search keeps what matches by name, kind or address, else says so.
    // AC-596.4.6: Up/Down and a click pick; a press outside closes without a change.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": SEND_TO_TARGET,
      "/api/v1/projects/demo/config": configWith([
        aService("orders-queue", "sqs", "orders-queue-personal"),
        aService("orders-db", "database", "db.example.com:5432/orders"),
        aService("checkout", "web", null),
      ]),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    await user.click(within(fetch).getByRole("button", { name: "target: choose a service" }));
    const picker = screen.getByRole("dialog", { name: "Choose target" });
    expect(picker).toHaveTextContent("Choose target · services in personal");
    const rowOf = (name: string) => within(picker).getByRole("option", { name: new RegExp(name) });
    expect(rowOf("orders-db")).toHaveTextContent("db.example.com:5432/orders");
    expect(rowOf("checkout")).toHaveTextContent("no address in personal");
    // A kind Add service writes is said in words, in its place among the kinds.
    expect(
      [...picker.querySelectorAll(".bk-menu-group")].map((group) => group.textContent),
    ).toEqual(["Frontends and portals", "Databases", "Queues (SQS)"]);

    const search = within(picker).getByRole("combobox");
    const names = () =>
      within(picker)
        .queryAllByRole("option")
        .map((option) => option.querySelector(".bk-menu-label")?.textContent);
    await user.type(search, "database");
    expect(names()).toEqual(["orders-db"]);
    await user.clear(search);
    await user.type(search, "5432");
    expect(names()).toEqual(["orders-db"]);
    await user.clear(search);
    await user.type(search, "zzz");
    expect(names()).toEqual([]);
    expect(picker).toHaveTextContent("Nothing matches.");

    // Up/Down move, Enter picks the row moved to.
    await user.clear(search);
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}{Enter}");
    expect(screen.queryByRole("dialog", { name: "Choose target" })).not.toBeInTheDocument();
    const field = within(fetch).getByRole("button", { name: "target: orders-db" });

    // A press outside closes the list and keeps the pick.
    await user.click(field);
    const scrim = globalThis.document.querySelector(".bk-menu-scrim");
    if (!(scrim instanceof HTMLElement)) throw new Error("no scrim");
    await user.pointer({ keys: "[MouseLeft]", target: scrim });
    expect(screen.queryByRole("dialog", { name: "Choose target" })).not.toBeInTheDocument();
    expect(within(fetch).getByRole("button", { name: "target: orders-db" })).toBeInTheDocument();

    // A click picks too (with any kind: left alone, the list keeps to the picked one's).
    await user.selectOptions(
      within(fetch).getByRole("combobox", { name: "Kind of service for target" }),
      "",
    );
    await user.click(within(fetch).getByRole("button", { name: "target: orders-db" }));
    await user.click(
      within(screen.getByRole("dialog", { name: "Choose target" })).getByRole("option", {
        name: /orders-queue/,
      }),
    );
    expect(within(fetch).getByRole("button", { name: "target: orders-queue" })).toBeInTheDocument();
  });

  it("scenario builder says no service is declared when the environment has none", async () => {
    // AC-596.4.5: the empty list says where to add one.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": SEND_TO_TARGET,
      "/api/v1/projects/demo/config": configWith([]),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    await user.click(within(fetch).getByRole("button", { name: "target: choose a service" }));
    expect(screen.getByRole("dialog", { name: "Choose target" })).toHaveTextContent(
      "No service is declared in personal. Add one in Environments.",
    );
  });

  it("scenario builder picks a service in the side panel the same way, its note following the pick", async () => {
    // AC-596.4.10: the side panel's field and list set the step's value, never a text box.
    // AC-596.4.16: the note gives the pick's kind, description and address, in both places.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": SEND_TO_TARGET,
      "/api/v1/projects/demo/config": configWith([
        aService("orders-queue", "sqs", "orders-queue-personal", { description: "Orders to pay" }),
        aService("orders-db", "database", null),
      ]),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const panel = screen.getByRole("region", { name: /^Inspector: / });
    expect(within(panel).queryByRole("textbox", { name: /target/ })).not.toBeInTheDocument();
    // Nothing picked: the panel says what to choose, not the action's own words.
    const note = within(panel).getByText("Choose a service in personal");
    expect(note).toBeInTheDocument();
    expect(note).not.toHaveTextContent("Where it is sent.");
    // The input's own description stays a line of its own under the field (as the snapshot).
    expect(within(panel).getByText("Where it is sent.")).not.toBe(note);

    await user.click(within(panel).getByRole("button", { name: "target: choose a service" }));
    const picker = screen.getByRole("dialog", { name: "Choose target" });
    await user.click(within(picker).getByRole("option", { name: /orders-queue/ }));
    const field = within(fetch).getByRole("button", { name: "target: orders-queue" });
    expect(field.closest(".st-g-row")?.querySelector(".st-g-note")).toHaveTextContent(
      "target · Required · Queue (SQS) · Orders to pay · orders-queue-personal",
    );
    expect(
      within(panel).getByText("Queue (SQS) · Orders to pay · orders-queue-personal"),
    ).toBeInTheDocument();

    // A service with no address here says so, in both places.
    await user.click(within(panel).getByRole("button", { name: "target: orders-queue" }));
    // The kind follows the pick, so choose any kind to see the database.
    await user.keyboard("{Escape}");
    await user.selectOptions(
      within(panel).getByRole("combobox", { name: "Kind of service for target" }),
      "",
    );
    await user.click(within(panel).getByRole("button", { name: "target: orders-queue" }));
    await user.click(
      within(screen.getByRole("dialog", { name: "Choose target" })).getByRole("option", {
        name: /orders-db/,
      }),
    );
    expect(within(fetch).getByRole("button", { name: "target: orders-db" })).toBeInTheDocument();
    expect(within(panel).getByText("Database · no address in personal")).toBeInTheDocument();
    expect(within(fetch).getByText(/Database · no address in personal/)).toBeInTheDocument();
  });

  it("scenario builder writes a picked service by its name, and by its repo only when the name is shared", async () => {
    // AC-596.4.13: the short name unless another repo declares the same one.
    // AC-596.4.15: written as <repo>/<name>, the field shows the name alone.
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      "/api/v1/projects/demo/actions": actionsWith({
        inputs: [
          { name: "target", type: "service", required: true, description: null },
          { name: "copy_to", type: "service", required: false, description: null },
        ],
      }),
      "/api/v1/projects/demo/config": configWith([
        aService("orders-queue", "sqs", "billing-orders", { repo: "billing" }),
        aService("orders-queue", "sqs", "shop-orders", { repo: "shop" }),
        aService("payments-queue", "sqs", "payments-personal", { repo: "billing" }),
      ]),
      [DETAIL]: detailWith({
        nodes: [{ ...document.nodes[0], with: { copy_to: "orders-queue" } }, document.nodes[1]],
      }),
      [SAVE]: () => SAVED,
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    // A bare name two repos declare is not either one: the run would refuse it.
    const shared = await within(fetch).findByRole("button", { name: "copy_to: orders-queue" });
    expect(shared).toHaveTextContent("in more than one repo");
    expect(shared.querySelector("svg")).not.toBeNull();
    expect(shared.closest(".st-g-row")?.querySelector(".st-g-note")).toHaveTextContent(
      "copy_to · In billing and shop: pick the one it means",
    );

    await user.click(within(fetch).getByRole("button", { name: "target: choose a service" }));
    await user.type(
      within(screen.getByRole("dialog", { name: "Choose target" })).getByRole("combobox"),
      "shop-orders",
    );
    await user.keyboard("{Enter}");
    const field = within(fetch).getByRole("button", { name: "target: orders-queue" });
    expect(field).not.toHaveTextContent("shop/");
    expect(field).toHaveAttribute("title", "shop-orders");

    await user.click(shared);
    await user.type(
      within(screen.getByRole("dialog", { name: "Choose copy_to" })).getByRole("combobox"),
      "payments",
    );
    await user.keyboard("{Enter}");
    await save(user);
    const saved = (await savedDocument(requests)) as {
      nodes: { with?: Record<string, unknown> }[];
    };
    expect(saved.nodes[0]?.with).toMatchObject({
      target: "shop/orders-queue",
      copy_to: "payments-queue",
    });
  });

  it("scenario builder's service note names the kind chosen, and counts a service still to pick", async () => {
    // AC-596.4.17: nothing picked, the note says what to choose, in the kind chosen, with its
    // article and case; a required one needs a value, counted with the others.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": SEND_TO_TARGET,
      "/api/v1/projects/demo/config": configWith([
        aService("orders-queue", "sqs", "orders-queue-personal"),
        aService("orders-api", "api", "https://api.example.com"),
      ]),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const values = within(fetch).getByRole("region", { name: "Values for this step" });
    expect(values).toHaveTextContent("1 needs a value");
    const kind = within(fetch).getByRole("combobox", { name: "Kind of service for target" });
    const note = () => kind.closest(".st-g-row")?.querySelector(".st-g-note");
    expect(note()).toHaveTextContent("target · Needs a value · Choose a service in personal");
    await user.selectOptions(kind, "sqs");
    expect(note()).toHaveTextContent("Choose a queue (SQS) in personal");
    await user.selectOptions(kind, "api");
    expect(note()).toHaveTextContent("Choose an API or backend in personal");
  });

  it("scenario builder keeps a service input that reads a reference as its token, with its edit", async () => {
    // AC-596.4.9: only a name is checked against the services; a reference is not one.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": SEND_TO_TARGET,
      "/api/v1/projects/demo/config": configWith([
        aService("orders-queue", "sqs", "orders-queue-personal"),
      ]),
      [DETAIL]: detailWith({
        nodes: [{ ...document.nodes[0], with: { target: "$CTX.queue" } }, document.nodes[1]],
      }),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    const values = within(fetch).getByRole("region", { name: "Values for this step" });
    expect(within(values).getByTitle("Kept value queue")).toBeInTheDocument();
    expect(within(values).getByRole("button", { name: "Change in the panel" })).toBeInTheDocument();
    expect(values).not.toHaveTextContent("not declared");
    expect(within(fetch).queryByRole("button", { name: /^target: / })).not.toBeInTheDocument();
  });

  it("scenario builder draws a service input's controls at 24px, in the shared field look", () => {
    // AC-596.3.17: the kind select and the service field are both 24px controls.
    const css = readFileSync(
      join(process.cwd(), "src/screens/scenarios/builder/steps.css"),
      "utf8",
    );
    const rule = (selector: string) => {
      const at = css.indexOf(`\n${selector} {`);
      expect(at).toBeGreaterThan(-1);
      return css.slice(at, css.indexOf("}", at));
    };
    expect(rule(".st-service")).toContain("height: var(--control-sm);");
    expect(rule(".st-service-kind")).toContain("height: var(--control-sm);");
    // The look is the shared field's; only size and layout are set here.
    expect(rule(".st-service")).not.toContain("border:");
    expect(rule(".st-service-kind")).not.toContain("padding");
    const tokens = readFileSync(join(process.cwd(), "src/styles/tokens.css"), "utf8");
    expect(tokens).toContain("--control-sm: 24px;");
  });

  it("scenario builder opens a selected step's row menu on the page's body, next to its button", async () => {
    // AC-596.3.5: rendered on document.body, placed under the button that opened it.
    const user = userEvent.setup();
    renderBuilder();
    const tree = await screen.findByRole("tree", { name: "Steps of order-lifecycle" });
    await user.click(within(tree).getByRole("treeitem", { name: FETCH }));
    const more = within(tree).getByRole("button", { name: "More for step 1 (Shift F10)" });
    vi.spyOn(more, "getBoundingClientRect").mockReturnValue({
      top: 80,
      bottom: 100,
      left: 320,
      right: 344,
      width: 24,
      height: 20,
      x: 320,
      y: 80,
      toJSON: () => ({}),
    });
    await user.click(more);
    const menu = screen.getByRole("menu", { name: "Step fetch-order" });
    expect(menu.parentElement).toBe(globalThis.document.body);
    expect(tree.contains(menu)).toBe(false);
    expect(menu.style.top).toBe("104px");
    expect(menu.style.left).toBe("320px");
  });

  it("scenario builder has no serious a11y violation on an open step with a draft, a needed value and its code shown (a11y)", async () => {
    // AC-596.3.29: the nested controls inside the open row pass axe.
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": actionsWith({
        draft: true,
        accept_command: "git add -- actions/orders/send-queue-message.yaml && git commit",
        inputs: [{ name: "region_code", type: "string", required: true, description: null }],
      }),
      [DETAIL]: detailWith({
        nodes: [
          { ...document.nodes[0], with: { body: '{"event_type":"FETCH_ORDERS"}' } },
          document.nodes[1],
        ],
      }),
    });
    const fetch = await screen.findByRole("treeitem", { name: FETCH });
    await user.click(fetch);
    await user.click(within(fetch).getByText("Show the code it runs"));
    expect(within(fetch).getByText("Draft: needs acceptance")).toBeVisible();
    expect(await seriousViolations(globalThis.document.body)).toEqual([]);
  });
});
