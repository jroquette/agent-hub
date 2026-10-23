import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  aPage,
  aScenarioAction,
  aScenarioDetail,
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

describe("ScenarioBuilder (scenario builder)", () => {
  it("scenario builder draws the blocks and their words, with a check that loads", async () => {
    renderBuilder();

    const check = await screen.findByRole("button", { name: /^Check order-on-hold/ });
    expect(check).toHaveTextContent("Waits until status is 'ON_HOLD'");
    expect(screen.getByRole("button", { name: /^Script fetch-order/ })).toBeInTheDocument();
    expect(await screen.findByText("Loads")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save scenario" })).toBeDisabled();
  });

  it("scenario builder adds a manual step after a block, edits it and saves over the file read", async () => {
    const user = userEvent.setup();
    const { requests } = renderBuilder({
      [SAVE]: () => ({
        path: "scenarios/orders/order-lifecycle.yaml",
        revision: 2,
        content_hash: "sha256:bbb",
        yaml: "version: 1\n",
        changed: true,
        versioned: true,
      }),
    });

    await user.click(await screen.findByRole("button", { name: "Add a block after fetch-order" }));
    await user.click(screen.getByRole("menuitem", { name: "Manual step" }));
    const inspector = await screen.findByRole("region", {
      name: "Inspector: Manual step manual-step",
    });
    await user.clear(within(inspector).getByLabelText("What to do"));
    await user.type(within(inspector).getByLabelText("What to do"), "Create the order");
    await user.click(within(inspector).getByLabelText(/Ask me to type a value/));
    expect(
      screen.getByRole("button", { name: /^Manual step manual-step: Create the order/ }),
    ).toHaveTextContent("you type a value");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    const save = screen.getByRole("button", { name: "Save scenario" });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    await user.click(save);

    expect(await screen.findByText("Saved · revision 2")).toBeInTheDocument();
    const sent = requests.find((request) => request.method === "PUT");
    const body = (await sent?.clone().json()) as {
      base_content_hash: string;
      document: { nodes: { id: string; depends_on?: string[]; capture_response?: boolean }[] };
    };
    expect(body.base_content_hash).toBe("sha256:aaa");
    const ids = body.document.nodes.map((node) => node.id);
    expect(ids).toEqual(["fetch-order", "manual-step", "order-on-hold"]);
    expect(body.document.nodes[1]?.capture_response).toBe(true);
    expect(body.document.nodes[2]?.depends_on).toEqual(["manual-step"]);
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
    const block = screen.getByRole("button", { name: /^Script fetch-order/ });
    expect(block).toHaveAttribute("data-invalid", "true");
    await userEvent.setup().click(block);
    expect(await screen.findByText("unknown action 'x'", { selector: "li" })).toBeInTheDocument();
  });

  it("scenario builder offers the hub's actions in the palette and adds one as a check", async () => {
    const user = userEvent.setup();
    renderBuilder();

    await user.click(
      await screen.findByRole("button", { name: "Add get-order-by-ref as a check block" }),
    );

    expect(
      await screen.findByRole("region", { name: "Inspector: Check get-order-by-ref" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Check get-order-by-ref/ })).toBeInTheDocument();
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
