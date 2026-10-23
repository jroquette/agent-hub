import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  aPage,
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

    const check = await screen.findByRole("button", { name: "Check order-on-hold" });
    expect(check).toHaveTextContent("wait until");
    expect(check).toHaveTextContent("status is ON_HOLD");
    expect(within(check).getByLabelText("Check every, order-on-hold")).toHaveValue("10s");
    expect(screen.getByRole("button", { name: "Script fetch-order" })).toHaveTextContent("run");
    expect(screen.getByText("when the scenario starts")).toBeInTheDocument();
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
    const block = screen.getByRole("button", { name: "Manual step manual-step" });
    expect(block).toHaveTextContent("ask me to");
    expect(block).toHaveTextContent("Create the order");
    expect(block).toHaveTextContent("and keep what I type");

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

  it("scenario builder edits a field inside a block", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    const field = await screen.findByLabelText("For up to, order-on-hold");
    await user.clear(field);
    await user.type(field, "10m");
    expect(screen.getByRole("button", { name: "Check order-on-hold" })).toHaveTextContent(
      "(60 checks)",
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

    expect(await screen.findByRole("region", { name: "Inspector: If" })).toBeInTheDocument();
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
    const block = screen.getByRole("button", { name: "Script fetch-order" });
    expect(block).toHaveAttribute("data-invalid", "true");
    block.focus();
    await userEvent.setup().keyboard("{Enter}");
    expect(await screen.findByText("unknown action 'x'", { selector: "li" })).toBeInTheDocument();
  });

  it("scenario builder offers the hub's actions in the palette, a read one as a check with Shift", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await user.keyboard("{Shift>}");
    await user.click(await screen.findByRole("button", { name: "Add action get-order-by-ref" }));
    await user.keyboard("{/Shift}");

    expect(
      await screen.findByRole("region", { name: "Inspector: Check get-order-by-ref" }),
    ).toBeInTheDocument();
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
    await screen.findByRole("button", { name: "Pause pause" });
    first.unmount();

    const second = renderBuilder();
    expect(await screen.findByRole("button", { name: "Pause pause" })).toBeInTheDocument();
    expect(
      screen.getByText(/Your unsaved changes came back from this browser/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard them" }));
    expect(screen.queryByRole("button", { name: "Pause pause" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add block: wait 30s" }));
    second.unmount();

    renderBuilder({
      [DETAIL]: aScenarioDetail({ document, content_hash: "sha256:changed-outside" }),
    });
    await screen.findByRole("button", { name: "Check order-on-hold" });
    expect(screen.queryByRole("button", { name: "Pause pause" })).not.toBeInTheDocument();
    window.localStorage.clear();
  });

  it("scenario builder inserts a block between two others from the + menu", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    await user.click(await screen.findByRole("button", { name: "Add a block after fetch-order" }));
    const menu = screen.getByRole("dialog", { name: "Add a block after fetch-order" });
    await user.type(within(menu).getByLabelText(/Find a block or action/), "wait 30");
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("button", { name: "Pause pause" })).toBeInTheDocument();
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

    expect(
      await screen.findByRole("region", { name: "Inspector: Check order-on-hold" }),
    ).toBeInTheDocument();
  });

  it("scenario builder fills a block's slots on the block itself", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({ [SAVE]: () => SAVED });

    const fetch = await screen.findByRole("button", { name: "Script fetch-order" });
    await user.click(within(fetch).getByRole("button", { name: "action: change" }));
    const picker = screen.getByRole("dialog", { name: "Choose the action" });
    await user.click(within(picker).getByRole("button", { name: /get-order-by-ref/ }));
    expect(within(fetch).getByRole("button", { name: "action: change" })).toHaveTextContent(
      "get-order-by-ref",
    );
    // The action asks for external_ref: an empty slot says so, and fills from a popover.
    await user.click(within(fetch).getByRole("button", { name: "external_ref: choose" }));
    const value = screen.getByRole("dialog", { name: "Value of external_ref" });
    await user.type(within(value).getByRole("textbox"), "T-1");
    await user.click(within(value).getByRole("button", { name: "Done" }));

    const save = screen.getByRole("button", { name: "Save scenario" });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    await user.click(save);
    await screen.findByText("Saved · rev 2");
    const nodes = (await savedNodes(requests)) as (SentNode & { action?: string; with?: object })[];
    expect(nodes[0]).toMatchObject({ action: "get-order-by-ref", with: { external_ref: "T-1" } });
  });

  it("scenario builder deletes with Delete, undoes from the toast, and moves with Alt+arrows", async () => {
    const user = userEvent.setup();
    renderBuilder();

    const check = await screen.findByRole("button", { name: "Check order-on-hold" });
    check.focus();
    await user.keyboard("{Enter}");
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    const blocks = screen.getAllByRole("button", { name: /^(Check|Script) / });
    expect(blocks.map((block) => block.getAttribute("aria-label"))).toEqual([
      "Check order-on-hold",
      "Script fetch-order",
    ]);

    await user.keyboard("{Delete}");
    expect(screen.queryByRole("button", { name: "Check order-on-hold" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("button", { name: "Check order-on-hold" })).toBeInTheDocument();
  });

  it("scenario builder shows the side panel only for a block or the inputs", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await screen.findByRole("button", { name: "Check order-on-hold" });
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
    expect(screen.getByRole("button", { name: "Script notify" })).toHaveAttribute(
      "data-suggested",
      "true",
    );
    expect(screen.getByRole("button", { name: "Script fetch-order" })).not.toHaveAttribute(
      "data-suggested",
    );
    // Block by block: the review panel lists the change, accepted on its own.
    const review = screen.getByRole("region", { name: "Claude's proposal" });
    expect(within(review).getByText("notify")).toBeInTheDocument();
    await user.click(within(review).getByRole("button", { name: "Accept notify" }));

    expect(await screen.findByText("Unsaved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Script notify" })).not.toHaveAttribute(
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

  it("scenario builder writes a new action from the action slot and uses it", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      "POST /api/v1/projects/demo/actions": aScenarioAction({
        ref: "orders/render-invoice-pdf",
        name: "render-invoice-pdf",
        effect: "write",
        draft: true,
      }),
    });

    const fetch = await screen.findByRole("button", { name: "Script fetch-order" });
    await user.click(within(fetch).getByRole("button", { name: "action: change" }));
    await user.click(screen.getByRole("button", { name: "New action…" }));
    const dialog = screen.getByRole("dialog", { name: "New action" });
    await user.type(within(dialog).getByPlaceholderText("send-message"), "render-invoice-pdf");
    await user.type(
      within(dialog).getByPlaceholderText("Send one JSON message to a queue"),
      "Render the PDF",
    );
    await user.click(within(dialog).getByRole("button", { name: "Write the action" }));

    await waitFor(() => {
      expect(within(fetch).getByRole("button", { name: "action: change" })).toHaveTextContent(
        "render-invoice-pdf",
      );
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

    expect(await screen.findByRole("button", { name: "Script script" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check check" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Start the scenario" })).not.toBeInTheDocument();
  });

  it("scenario builder says on each block what it runs, what it changes and what it gives", async () => {
    const user = userEvent.setup();
    renderBuilder();

    const check = await screen.findByRole("button", { name: "Check order-on-hold" });
    await waitFor(() => {
      expect(check).toHaveTextContent("Python");
    });
    expect(
      within(check).getByTitle("actions/orders/scripts/get_order_by_ref.py"),
    ).toBeInTheDocument();
    expect(check).toHaveTextContent("Only reads: changes nothing");
    expect(check).toHaveTextContent("Givesstatus");
    const fetch = screen.getByRole("button", { name: "Script fetch-order" });
    expect(fetch).toHaveTextContent("Changes data");
    await user.click(within(check).getByRole("button", { name: "show script" }));
    expect(within(check).getByLabelText("Script of get-order-by-ref")).toHaveTextContent(
      "print('{}')",
    );
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

    const fetch = screen.getByRole("button", { name: "Script fetch-order" });
    await waitFor(() => {
      expect(fetch).toHaveTextContent("In personal");
    });
    expect(fetch).toHaveTextContent("asks you first");
    expect(fetch).toHaveTextContent("Would send one message");
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

    const check = await screen.findByRole("button", { name: "Check order-on-hold" });
    await user.click(within(check).getByRole("button", { name: "condition: change" }));
    const pop = screen.getByRole("dialog", { name: "Wait until" });
    await user.type(
      within(pop).getByLabelText("Type the condition in words"),
      "status is DONE{Enter}",
    );

    expect(
      within(pop).getByText("Read from your words: check the rows below."),
    ).toBeInTheDocument();
    expect(within(pop).getByLabelText("Value")).toHaveValue("DONE");
    await user.click(within(pop).getByRole("button", { name: "Done" }));
    expect(check).toHaveTextContent("status is DONE");
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
