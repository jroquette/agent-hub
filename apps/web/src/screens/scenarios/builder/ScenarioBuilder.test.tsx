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

function renderBuilder(extra: ApiRoutes = {}) {
  return renderWithApi(<ScenarioDetailScreen />, {
    routes: {
      [DETAIL]: aScenarioDetail({ document, content_hash: "sha256:aaa" }),
      "/api/v1/approvals": aPage([]),
      "/api/v1/workflow-runs": aPage([]),
      "/api/v1/projects/demo/actions": library,
      [VALIDATE]: () => ({ loads: true, yaml: "version: 1\n", problems: [], nodes: [] }),
      ...extra,
    },
    path: PATH,
    route: "/scenarios/:project/:name",
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

describe("ScenarioBuilder (scenario builder)", () => {
  // Each test starts with no draft kept in this browser.
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("scenario builder reads the scenario as blocks that say what they do", async () => {
    renderBuilder();

    const check = await screen.findByRole("treeitem", { name: "Check order-on-hold" });
    expect(check).toHaveTextContent("Wait until status is ON_HOLD");
    expect(check).toHaveTextContent("every 10 s, up to 5 min (at most 30 checks)");
    // What runs: the action's own description, its script and what it gives.
    const fetch = screen.getByRole("treeitem", { name: "Script fetch-order" });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("Send one message to the orders queue");
    });
    expect(fetch).toHaveTextContent("send-queue-message· Python· scripts/send_queue_message.py");
    expect(fetch).toHaveTextContent("Changes data");
    expect(fetch).toHaveTextContent("Givesstatus");
    expect(screen.getByText("When the scenario starts")).toBeInTheDocument();
    expect(await screen.findByText("Loads")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save scenario" })).toBeDisabled();
  });

  it("scenario builder adds a block from the palette, edits it and saves over the file read", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("button", { name: "Add block: ask me to …" }));
    const inspector = await screen.findByRole("region", {
      name: "Inspector: Manual step manual-step",
    });
    await user.clear(within(inspector).getByLabelText("What to do"));
    await user.type(within(inspector).getByLabelText("What to do"), "Create the order");
    await user.click(within(inspector).getByLabelText(/Ask me to type a value/));
    const block = screen.getByRole("treeitem", { name: "Manual step manual-step" });
    expect(block).toHaveTextContent("Create the order");
    expect(block).toHaveTextContent("a typed value later steps can use");

    const save = screen.getByRole("button", { name: "Save scenario" });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    await user.click(save);

    expect(await screen.findByText("Saved · rev 2")).toBeInTheDocument();
    const nodes = await savedNodes(requests);
    expect(nodes.map((node) => node.id)).toEqual(["fetch-order", "order-on-hold", "manual-step"]);
    expect(nodes[2]).toMatchObject({ depends_on: ["order-on-hold"], capture_response: true });
  });

  it("scenario builder edits a step in the side form", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("treeitem", { name: "Check order-on-hold" }));
    const form = screen.getByRole("region", { name: "Inspector: Check order-on-hold" });
    const field = within(form).getByLabelText("For up to");
    await user.clear(field);
    await user.type(field, "10m");
    expect(within(form).getByText("At most 60 checks.")).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: "Check order-on-hold" })).toHaveTextContent(
      "up to 10 min",
    );
    const save = screen.getByRole("button", { name: "Save scenario" });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    await user.click(save);

    await screen.findByText("Saved · rev 2");
    const nodes = await savedNodes(requests);
    expect(nodes[1]).toMatchObject({ id: "order-on-hold", timeout: "10m" });
  });

  it("scenario builder wraps blocks in an if when they are clicked in from the palette", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await user.click(await screen.findByRole("button", { name: "Add block: if … else" }));

    expect(
      screen.getByRole("button", { name: "Add a block what happens when it holds" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Add a block otherwise (or nothing: skip to the next block)",
      }),
    ).toBeInTheDocument();
  });

  it("scenario builder pins the server's problems on their block and keeps Save off", async () => {
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
    const block = screen.getByRole("treeitem", { name: "Script fetch-order" });
    expect(block).toHaveAttribute("data-invalid", "true");
    block.focus();
    await userEvent.setup().keyboard("{Enter}");
    expect(within(block).getByText("unknown action 'x'")).toBeInTheDocument();
  });

  it("scenario builder offers the hub's actions in the palette, a read one as a check with Shift", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await user.keyboard("{Shift>}");
    await user.click(await screen.findByRole("button", { name: "Add action get-order-by-ref" }));
    await user.keyboard("{/Shift}");

    expect(await screen.findByRole("treeitem", { name: "Check get-order-by-ref" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("scenario builder still adds blocks in the graph view", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await user.click(await screen.findByRole("button", { name: "Graph" }));
    await user.click(await screen.findByRole("button", { name: "Add a block after fetch-order" }));
    await user.click(screen.getByRole("menuitem", { name: "Pause" }));

    expect(
      await screen.findByRole("region", { name: "Inspector: Pause pause" }),
    ).toBeInTheDocument();
  });

  it("scenario builder keeps unsaved changes across a reload, and drops them for a changed file", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const first = renderBuilder();
    await user.click(await screen.findByRole("button", { name: "Add block: wait 30s" }));
    await screen.findByRole("treeitem", { name: "Pause pause" });
    first.unmount();

    const second = renderBuilder();
    expect(await screen.findByRole("treeitem", { name: "Pause pause" })).toBeInTheDocument();
    expect(
      screen.getByText(/Your unsaved changes came back from this browser/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard them" }));
    expect(screen.queryByRole("treeitem", { name: "Pause pause" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add block: wait 30s" }));
    second.unmount();

    renderBuilder({
      [DETAIL]: aScenarioDetail({ document, content_hash: "sha256:changed-outside" }),
    });
    await screen.findByRole("treeitem", { name: "Check order-on-hold" });
    expect(screen.queryByRole("treeitem", { name: "Pause pause" })).not.toBeInTheDocument();
    window.localStorage.clear();
  });

  it("scenario builder drops a loose copy of a step that is back in the file", async () => {
    // A loose stack kept in this browser, while the file holds the same step (an undo, a
    // discarded draft): it must not show twice.
    window.localStorage.setItem(
      "ah.builder.layout.demo/order-lifecycle",
      JSON.stringify({
        main: { x: 80, y: 40 },
        loose: [
          {
            id: "stack-1",
            x: 700,
            y: 40,
            items: [{ kind: "block", node: { id: "fetch-order", type: "action" } }],
          },
        ],
      }),
    );
    renderBuilder();

    await screen.findByRole("treeitem", { name: "Check order-on-hold" });
    expect(screen.getAllByRole("treeitem", { name: "Script fetch-order" })).toHaveLength(1);
    expect(screen.queryByText(/loose block/)).not.toBeInTheDocument();
    expect(
      JSON.parse(window.localStorage.getItem("ah.builder.layout.demo/order-lifecycle") ?? "{}"),
    ).toMatchObject({ loose: [] });
  });

  it("scenario builder says so when the hub's actions cannot be read", async () => {
    const user = userEvent.setup();
    renderBuilder({
      "/api/v1/projects/demo/actions": aProblem({ status: 500, title: "Boom" }),
    });

    const fetch = await screen.findByRole("treeitem", { name: "Script fetch-order" });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("Action details could not be read.");
    });
    expect(fetch).not.toHaveTextContent("is not an action of this hub");
    await user.click(fetch);
    expect(screen.getByRole("region", { name: "Inspector: Script fetch-order" })).toHaveTextContent(
      "The hub's actions could not be read",
    );
  });

  it("scenario builder marks a preview made before the last change", async () => {
    const user = userEvent.setup();
    renderBuilder({
      [`POST ${DETAIL}/plan`]: aScenarioPlan({
        rows: [aScenarioPlanRow({ step: "fetch-order", plan: "Would send one message" })],
      }),
    });

    await user.click(await screen.findByRole("button", { name: "Preview in…" }));
    const form = screen.getByRole("form", { name: "Preview in an environment" });
    await user.type(within(form).getByRole("textbox", { name: /external_ref/ }), "T-1");
    await user.click(within(form).getByRole("button", { name: "Preview" }));
    const fetch = screen.getByRole("treeitem", { name: "Script fetch-order" });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("In personal: Would send one message");
    });

    await user.click(screen.getByRole("button", { name: "Add block: wait 30s" }));
    expect(fetch).toHaveTextContent(
      "In personal (before your last change): Would send one message",
    );
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

    await user.click(await screen.findByRole("treeitem", { name: "Script fetch-order" }));
    const form = screen.getByRole("region", { name: "Inspector: Script fetch-order" });
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

    const save = screen.getByRole("button", { name: "Save scenario" });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    await user.click(save);
    await screen.findByText("Saved · rev 2");
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

    const fetch = await screen.findByRole("treeitem", { name: "Script fetch-order" });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("+ 1 from the run");
    });
    await user.click(screen.getByRole("button", { name: "Inputs" }));
    const settings = screen.getByRole("region", { name: "Scenario settings" });
    expect(settings).toHaveTextContent("2 steps take it");
    expect(settings).toHaveTextContent("2 values repeat a run value");
    await user.click(within(settings).getByRole("button", { name: "Remove the repeats" }));

    const save = screen.getByRole("button", { name: "Save scenario" });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    await user.click(save);
    await screen.findByText("Saved · rev 2");
    const nodes = (await savedNodes(requests)) as (SentNode & { with?: object })[];
    expect(nodes.map((node) => node.with)).toEqual([undefined, undefined]);
    // Still the run's value on the card.
    expect(fetch).toHaveTextContent("+ 1 from the run");
  });

  it("scenario builder inserts a block between two others from the + menu", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("button", { name: "Add a block after fetch-order" }));
    const menu = screen.getByRole("dialog", { name: "Add a block after fetch-order" });
    await user.type(within(menu).getByLabelText(/Find a block or action/), "wait 30");
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("treeitem", { name: "Pause pause" })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save scenario" });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    await user.click(save);
    await screen.findByText("Saved · rev 2");
    const nodes = await savedNodes(requests);
    expect(nodes.map((node) => node.id)).toEqual(["fetch-order", "pause", "order-on-hold"]);
    expect(nodes[2]?.depends_on).toEqual(["pause"]);
  });

  it("scenario builder lists the problems and opens the block of one", async () => {
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

    const check = await screen.findByRole("treeitem", { name: "Check order-on-hold" });
    expect(check).toHaveAttribute("aria-selected", "true");
    expect(within(check).getByText("the condition does not parse")).toBeInTheDocument();
  });

  it("scenario builder picks a step's action and its values in the side form", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    const fetch = await screen.findByRole("treeitem", { name: "Script fetch-order" });
    await user.click(fetch);
    const form = screen.getByRole("region", { name: "Inspector: Script fetch-order" });
    await user.selectOptions(within(form).getByLabelText("Action"), "orders/get-order-by-ref");
    expect(fetch).toHaveTextContent("get-order-by-ref· Python");
    // external_ref is a scenario input: the step takes the run's value unless it sets its own.
    expect(
      within(form).getByRole("note", { name: /external_ref: the run's value/ }),
    ).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Set for this step" }));
    await user.type(within(form).getByLabelText("external_ref"), "T-1");
    expect(fetch).toHaveTextContent("external_refT-1");

    const save = screen.getByRole("button", { name: "Save scenario" });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    await user.click(save);
    await screen.findByText("Saved · rev 2");
    const nodes = (await savedNodes(requests)) as (SentNode & { action?: string; with?: object })[];
    expect(nodes[0]).toMatchObject({
      action: "orders/get-order-by-ref",
      with: { external_ref: "T-1" },
    });
  });

  it("scenario builder deletes with Delete, undoes from the toast, and moves with Alt+arrows", async () => {
    const user = userEvent.setup();
    renderBuilder();

    const check = await screen.findByRole("treeitem", { name: "Check order-on-hold" });
    check.focus();
    await user.keyboard("{Enter}");
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    const blocks = screen.getAllByRole("treeitem", { name: /^(Check|Script) / });
    expect(blocks.map((block) => block.getAttribute("aria-label"))).toEqual([
      "Check order-on-hold",
      "Script fetch-order",
    ]);

    await user.keyboard("{Delete}");
    expect(screen.queryByRole("treeitem", { name: "Check order-on-hold" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(
      await screen.findByRole("treeitem", { name: "Check order-on-hold" }),
    ).toBeInTheDocument();
  });

  it("scenario builder shows the side panel only for a block or the inputs", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await screen.findByRole("treeitem", { name: "Check order-on-hold" });
    expect(screen.queryByRole("region", { name: "Scenario settings" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Inputs" }));
    expect(screen.getByRole("region", { name: "Scenario settings" })).toHaveTextContent(
      "external_ref",
    );
  });

  it("scenario builder shows Claude's proposal as suggested blocks to accept", async () => {
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
      "Claude proposes 1 new or changed block · it loads",
    );
    await user.click(screen.getByRole("button", { name: "Review" }));
    expect(screen.getByRole("treeitem", { name: "Script notify" })).toHaveAttribute(
      "data-suggested",
      "true",
    );
    expect(screen.getByRole("treeitem", { name: "Script fetch-order" })).not.toHaveAttribute(
      "data-suggested",
    );
    // Block by block: the review panel lists the change, accepted on its own.
    const review = screen.getByRole("region", { name: "Claude's proposal" });
    expect(within(review).getByText("notify")).toBeInTheDocument();
    await user.click(within(review).getByRole("button", { name: "Accept notify" }));

    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: "Script notify" })).not.toHaveAttribute(
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

  it("scenario builder writes a new action from the side form and uses it", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      "POST /api/v1/projects/demo/actions": aScenarioAction({
        ref: "orders/render-invoice-pdf",
        name: "render-invoice-pdf",
        effect: "write",
        draft: true,
      }),
    });

    const fetch = await screen.findByRole("treeitem", { name: "Script fetch-order" });
    await user.click(fetch);
    const form = screen.getByRole("region", { name: "Inspector: Script fetch-order" });
    await user.click(within(form).getByRole("button", { name: "New action" }));
    const dialog = screen.getByRole("dialog", { name: "New action" });
    await user.type(within(dialog).getByPlaceholderText("send-message"), "render-invoice-pdf");
    await user.type(
      within(dialog).getByPlaceholderText("Send one JSON message to a queue"),
      "Render the PDF",
    );
    await user.click(within(dialog).getByRole("button", { name: "Write the action" }));

    await waitFor(() => {
      expect(fetch).toHaveTextContent("Run render-invoice-pdf");
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

    expect(await screen.findByRole("treeitem", { name: "Script script" })).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: "Check check" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Start the scenario" })).not.toBeInTheDocument();
  });

  it("scenario builder says on each block what it runs, what it changes and what it gives", async () => {
    const user = userEvent.setup();
    renderBuilder();

    const check = await screen.findByRole("treeitem", { name: "Check order-on-hold" });
    // The card marks its effect; the side form tells every fact.
    const fetch = screen.getByRole("treeitem", { name: "Script fetch-order" });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("Changes data");
    });
    check.focus();
    await user.keyboard("{Enter}");
    const form = screen.getByRole("region", { name: "Inspector: Check order-on-hold" });
    await waitFor(() => {
      expect(form).toHaveTextContent("Python");
    });
    expect(
      within(form).getByTitle("actions/orders/scripts/get_order_by_ref.py"),
    ).toBeInTheDocument();
    expect(form).toHaveTextContent("Reads only");
    expect(form).toHaveTextContent("Givesstatus");
    // The action's own panel has its script.
    await user.click(within(form).getByRole("button", { name: "Open action get-order-by-ref" }));
    expect(
      await screen.findByRole("complementary", { name: "Action get-order-by-ref" }),
    ).toHaveTextContent("print('{}')");
  });

  it("scenario builder previews in an environment what each block would do there", async () => {
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

    await user.click(await screen.findByRole("button", { name: "Preview in…" }));
    const form = screen.getByRole("form", { name: "Preview in an environment" });
    await user.type(within(form).getByRole("textbox", { name: /external_ref/ }), "T-1");
    await user.click(within(form).getByRole("button", { name: "Preview" }));

    const fetch = screen.getByRole("treeitem", { name: "Script fetch-order" });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("In personal: Would send one message");
    });
    fetch.focus();
    await user.keyboard("{Enter}");
    const inspector = screen.getByRole("region", { name: "Inspector: Script fetch-order" });
    expect(inspector).toHaveTextContent("asks you first");
    const sent = requests.find((request) => request.url.endsWith("/plan"));
    expect(await sent?.clone().json()).toEqual({
      environment: "personal",
      inputs: { external_ref: "T-1" },
    });
  });

  it("scenario builder makes and edits actions from the palette", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      "PUT /api/v1/projects/demo/actions/orders/get-order-by-ref": aScenarioAction({
        ref: "orders/get-order-by-ref",
        name: "get-order-by-ref",
        description: "Read one record",
        draft: true,
      }),
    });

    await user.click(await screen.findByRole("button", { name: "New action" }));
    expect(screen.getByRole("dialog", { name: "New action" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("button", { name: "About get-order-by-ref" }));
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

    const check = await screen.findByRole("treeitem", { name: "Check order-on-hold" });
    await user.click(check);
    const form = screen.getByRole("region", { name: "Inspector: Check order-on-hold" });
    const [words] = within(form).getAllByLabelText("Type the condition in words");
    if (!words) throw new Error("no words field");
    await user.type(words, "status is DONE{Enter}");

    expect(
      within(form).getByText("Read from your words: check the rows below."),
    ).toBeInTheDocument();
    expect(within(form).getAllByLabelText("Value")[0]).toHaveValue("DONE");
    expect(check).toHaveTextContent("Wait until status is DONE");
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
