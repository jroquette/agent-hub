import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aProblem,
  aRun,
  aWorkflowCatalog,
  aWorkflowDetail,
  aWorkflowSummary,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { StartRun } from "./StartRun";

const LIST = "/api/v1/workflows";
const FIX = "/api/v1/workflows/agent-hub/fix";
const START = "POST /api/v1/workflow-runs";
const ACCEPTED = { run_id: "a1b2c3d4", project: "agent-hub", action: "start" };

const fix = aWorkflowDetail({
  ...aWorkflowSummary({ name: "fix", description: "Fixes an issue." }),
  document: {
    name: "fix",
    inputs: {
      issue: { type: "string", required: true, description: "The tracker issue." },
      tries: { type: "integer", default: 2 },
      ratio: { type: "number" },
      strict: { type: "boolean", default: true },
      note: { type: "string" },
    },
    nodes: [{ id: "work", type: "shell", command: ["make"] }],
  },
});

function routes(extra: ApiRoutes = {}): ApiRoutes {
  return {
    "/api/v1/workflow-runs": aPage([aRun({ id: "a1b2c3d4", workflow: "fix" })]),
    [LIST]: aWorkflowCatalog({
      items: [
        aWorkflowSummary({ name: "fix", description: "Fixes an issue." }),
        aWorkflowSummary({ name: "issue-to-pr", source: "builtin" }),
      ],
      problems: [],
    }),
    [FIX]: fix,
    ...extra,
  };
}

function renderStart(extra: ApiRoutes = {}) {
  return renderWithApi(<StartRun project={null} />, { routes: routes(extra), path: "/runs" });
}

async function openDialog() {
  await userEvent.click(await screen.findByRole("button", { name: "Start run" }));
  return screen.getByRole("dialog", { name: "Start a workflow run" });
}

async function chooseFix(dialog: HTMLElement) {
  const picker = within(dialog).getByRole("combobox", { name: "Workflow" });
  await waitFor(() => {
    expect(within(picker).getAllByRole("option").length).toBeGreaterThan(1);
  });
  await userEvent.selectOptions(picker, "agent-hub / fix");
  await within(dialog).findByRole("textbox", { name: /^issue/ });
}

describe("StartRun", () => {
  it("lists the workflows a web start may run, without issue-to-pr", async () => {
    renderStart();

    const dialog = await openDialog();
    const picker = within(dialog).getByRole("combobox", { name: "Workflow" });
    await waitFor(() => {
      expect(within(picker).getByRole("option", { name: "agent-hub / fix" })).toBeInTheDocument();
    });
    expect(within(picker).queryByRole("option", { name: /issue-to-pr/ })).toBeNull();
    expect(dialog).toHaveTextContent("issue-to-pr starts from hub run");
    expect(dialog).toHaveTextContent("Runs live on this machine");
    expect(within(dialog).queryByRole("radio")).toBeNull();
  });

  it("builds the inputs form from the workflow's inputs with their defaults", async () => {
    renderStart();
    const dialog = await openDialog();

    await chooseFix(dialog);

    expect(within(dialog).getByRole("textbox", { name: /^issue \(required\)/ })).toHaveValue("");
    expect(within(dialog).getByText("The tracker issue.")).toBeInTheDocument();
    expect(within(dialog).getByRole("spinbutton", { name: /^tries/ })).toHaveValue(2);
    expect(within(dialog).getByRole("spinbutton", { name: /^ratio/ })).toHaveValue(null);
    expect(within(dialog).getByRole("checkbox", { name: /^strict/ })).toBeChecked();
    expect(within(dialog).getByRole("button", { name: "Start run" })).toBeDisabled();
  });

  it("waits until the new run reports before opening it", async () => {
    let lists = 0;
    const { router } = renderStart({
      [START]: ACCEPTED,
      "/api/v1/workflow-runs": () => {
        lists += 1;
        return aPage(lists < 2 ? [] : [aRun({ id: "a1b2c3d4", workflow: "fix" })]);
      },
    });
    const dialog = await openDialog();
    await chooseFix(dialog);
    await userEvent.type(within(dialog).getByRole("textbox", { name: /^issue/ }), "DEM-7");

    await userEvent.click(within(dialog).getByRole("button", { name: "Start run" }));

    expect(await within(dialog).findByRole("status")).toHaveTextContent(
      "Started. Waiting for the run's first event…",
    );
    expect(router.state.location.pathname).toBe("/runs");
    await waitFor(
      () => {
        expect(router.state.location.pathname).toBe("/runs/a1b2c3d4");
      },
      { timeout: 4000 },
    );
  });

  it("starts the run with typed inputs and opens it", async () => {
    const { requests, router } = renderStart({ [START]: ACCEPTED });
    const dialog = await openDialog();
    await chooseFix(dialog);

    await userEvent.type(within(dialog).getByRole("textbox", { name: /^issue/ }), "DEM-7");
    const tries = within(dialog).getByRole("spinbutton", { name: /^tries/ });
    await userEvent.clear(tries);
    await userEvent.type(tries, "3");
    await userEvent.type(within(dialog).getByRole("spinbutton", { name: /^ratio/ }), "0.5");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /^strict/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Start run" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/runs/a1b2c3d4");
    });
    const post = requests.find((r) => r.method === "POST");
    expect(post?.headers.get("content-type")).toContain("application/json");
    expect(await post?.json()).toEqual({
      project: "agent-hub",
      workflow: "fix",
      inputs: { issue: "DEM-7", tries: 3, ratio: 0.5, strict: false },
    });
  });

  it("keeps the start off while an integer input holds a fraction", async () => {
    renderStart();
    const dialog = await openDialog();
    await chooseFix(dialog);
    await userEvent.type(within(dialog).getByRole("textbox", { name: /^issue/ }), "DEM-7");
    const tries = within(dialog).getByRole("spinbutton", { name: /^tries/ });

    await userEvent.clear(tries);
    await userEvent.type(tries, "1.5");

    expect(within(dialog).getByRole("button", { name: "Start run" })).toBeDisabled();
    expect(within(dialog).getByText("tries must be a whole number.")).toBeInTheDocument();
  });

  it("keeps the start off while an integer input is beyond a safe whole number", async () => {
    renderStart();
    const dialog = await openDialog();
    await chooseFix(dialog);
    await userEvent.type(within(dialog).getByRole("textbox", { name: /^issue/ }), "DEM-7");
    const tries = within(dialog).getByRole("spinbutton", { name: /^tries/ });

    await userEvent.clear(tries);
    await userEvent.type(tries, "9007199254740993");

    expect(within(dialog).getByRole("button", { name: "Start run" })).toBeDisabled();
    expect(
      within(dialog).getByText("tries must be a whole number up to 2^53."),
    ).toBeInTheDocument();
  });

  it("keeps every field off while the start is sent", async () => {
    renderStart({ [START]: "pending" });
    const dialog = await openDialog();
    await chooseFix(dialog);
    await userEvent.type(within(dialog).getByRole("textbox", { name: /^issue/ }), "DEM-7");

    await userEvent.click(within(dialog).getByRole("button", { name: "Start run" }));

    await within(dialog).findByText("Starting the run…");
    expect(within(dialog).getByRole("textbox", { name: /^issue/ })).toBeDisabled();
    expect(within(dialog).getByRole("checkbox", { name: /^strict/ })).toBeDisabled();
    expect(dialog).toHaveFocus();
  });

  it("shows the API's reason and keeps the dialog when the start is refused", async () => {
    renderStart({
      [START]: aProblem({
        status: 409,
        title: "Workflow run command refused",
        detail: "the issue already has a live run (r9); cancel or abandon it first",
      }),
    });
    const dialog = await openDialog();
    await chooseFix(dialog);
    await userEvent.type(within(dialog).getByRole("textbox", { name: /^issue/ }), "DEM-7");

    await userEvent.click(within(dialog).getByRole("button", { name: "Start run" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Could not start the run");
    expect(alert).toHaveTextContent("the issue already has a live run (r9)");
    expect(screen.getByRole("dialog", { name: "Start a workflow run" })).toBeInTheDocument();
  });

  it("closes without starting when cancelled", async () => {
    const { requests } = renderStart();
    const dialog = await openDialog();

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Start run" })).toHaveFocus();
    expect(requests.some((r) => r.method === "POST")).toBe(false);
  });

  it("asks only the scoped project's workflows when a project is in scope", async () => {
    const { requests } = renderWithApi(<StartRun project="agent-hub" />, {
      routes: routes(),
      path: "/runs",
    });

    await openDialog();

    await waitFor(() => {
      const list = requests.find((r) => new URL(r.url).pathname === LIST);
      expect(new URL(list?.url ?? "http://x").searchParams.get("project")).toBe("agent-hub");
    });
  });

  it("has no serious accessibility violation with the form open", async () => {
    const { container } = renderStart();
    const dialog = await openDialog();
    await chooseFix(dialog);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
