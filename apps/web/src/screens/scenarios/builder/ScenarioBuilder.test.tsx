import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  aPage,
  aProblem,
  aScenarioAction,
  aScenarioDetail,
  aScenarioPlan,
  aScenarioPlanRow,
  renderWithApi,
  type ApiRoutes,
} from "../../../testing/builders";
import { ScenarioDetailScreen } from "..";

const PATH = "/scenarios/demo/order-lifecycle";
const DETAIL = "/api/v1/scenarios/demo/order-lifecycle";
const VALIDATE = "POST /api/v1/projects/demo/scenarios/validate";
const SAVE = `PUT ${DETAIL}`;
const ENV_EDIT = "POST /api/v1/projects/demo/config/environments";

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
