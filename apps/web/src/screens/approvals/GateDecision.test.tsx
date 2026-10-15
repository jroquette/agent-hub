import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aProblem, renderWithApi, type ApiRoutes } from "../../testing/builders";
import { GateDecision } from "./GateDecision";
import type { WorkflowGate } from "./queries";

const ID = "run-9:ship:1";
// The client encodes the gate id's colons in the path.
const PATH_ID = encodeURIComponent(ID);
const GATE = `/api/v1/approvals/${PATH_ID}/gate`;
const DECIDE = `POST /api/v1/approvals/${PATH_ID}/decision`;
const DECIDED = { approval_id: ID, run_id: "run-9", project: "demo", decision: "approve" };

function aGate(overrides: Partial<WorkflowGate> = {}): WorkflowGate {
  return {
    approval_id: ID,
    run_id: "run-9",
    project: "demo",
    workflow: "ship",
    node: "ship",
    attempt: 1,
    form: "decision",
    choices: [
      { id: "approve", label: "Approve" },
      { id: "request-changes", label: "Request changes" },
      { id: "reject", label: "Reject" },
    ],
    text: "off",
    ...overrides,
  };
}

function renderGate(routes: ApiRoutes) {
  return renderWithApi(<GateDecision approvalId={ID} />, { routes });
}

async function card() {
  return screen.findByRole("group", { name: "Decide this gate" });
}

describe("GateDecision", () => {
  it("shows one button per declared decision with its label", async () => {
    renderGate({ [GATE]: aGate() });

    const decide = await card();
    const names = within(decide)
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(names).toEqual(["Approve", "Request changes", "Reject"]);
    for (const button of within(decide).getAllByRole("button")) {
      expect(button).toBeEnabled();
      expect(within(button).queryByText("P4")).toBeNull();
    }
  });

  it("records a decision at once when the gate takes no text", async () => {
    const { requests } = renderGate({ [GATE]: aGate(), [DECIDE]: DECIDED });

    await userEvent.click(within(await card()).getByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Decision recorded. The run resumes; its events update this page.",
    );
    const post = requests.find((r) => r.method === "POST");
    expect(post?.headers.get("content-type")).toContain("application/json");
    expect(await post?.json()).toEqual({ decision: "approve" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks for an optional reason in a dialog when the gate captures a response", async () => {
    const { requests } = renderGate({ [GATE]: aGate({ text: "optional" }), [DECIDE]: DECIDED });

    await userEvent.click(within(await card()).getByRole("button", { name: "Request changes" }));
    const dialog = screen.getByRole("dialog", { name: "Request changes?" });
    const reason = within(dialog).getByRole("textbox", { name: "Reason (optional)" });
    expect(reason).toHaveFocus();
    await userEvent.type(reason, "  add tests  ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Request changes" }));

    await screen.findByRole("status");
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({ decision: "request-changes", text: "add tests" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("sends no text when an optional reason is left empty", async () => {
    const { requests } = renderGate({ [GATE]: aGate({ text: "optional" }), [DECIDE]: DECIDED });

    await userEvent.click(within(await card()).getByRole("button", { name: "Reject" }));
    const dialog = screen.getByRole("dialog", { name: "Reject?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Reject" }));

    await screen.findByRole("status");
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({ decision: "reject" });
  });

  it("requires a response before sending when a wait takes text only", async () => {
    const { requests } = renderGate({
      [GATE]: aGate({ form: "text", choices: [], text: "required" }),
      [DECIDE]: DECIDED,
    });

    await userEvent.click(within(await card()).getByRole("button", { name: "Respond" }));
    const dialog = screen.getByRole("dialog", { name: "Respond to this gate?" });
    const send = within(dialog).getByRole("button", { name: "Respond" });
    expect(send).toBeDisabled();
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Response (required)" }),
      "   ",
    );
    expect(send).toBeDisabled();
    await userEvent.type(within(dialog).getByRole("textbox"), "blue");
    await userEvent.click(send);

    await screen.findByRole("status");
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({ text: "blue" });
  });

  it("closes the dialog without sending when cancelled with Escape", async () => {
    const { requests } = renderGate({ [GATE]: aGate({ text: "optional" }) });

    await userEvent.click(within(await card()).getByRole("button", { name: "Approve" }));
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(requests.some((r) => r.method === "POST")).toBe(false);
  });

  it("keeps the dialog open with the problem when the decision is refused", async () => {
    renderGate({
      [GATE]: aGate({ text: "optional" }),
      [DECIDE]: aProblem({
        status: 409,
        title: "Workflow run command refused",
        detail: "the gate is already decided (approved)",
      }),
    });

    await userEvent.click(within(await card()).getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Could not record the decision");
    expect(alert).toHaveTextContent("the gate is already decided (approved)");
    expect(alert).toHaveTextContent("Nothing was recorded.");
  });

  it("says the decision is kept when the run could not resume", async () => {
    renderGate({
      [GATE]: aGate(),
      [DECIDE]: aProblem({
        status: 502,
        type: "urn:agent-hub:problem:workflow-run-resume-failed",
        title: "Could not resume the workflow run",
        detail: "The decision is recorded, but the run did not resume; resume the run to continue.",
      }),
    });

    await userEvent.click(within(await card()).getByRole("button", { name: "Reject" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not resume the workflow run");
    expect(alert).toHaveTextContent("The decision is recorded");
    expect(alert).not.toHaveTextContent("Nothing was recorded.");
  });

  it("shows why the gate cannot be decided here when the API refuses it", async () => {
    renderGate({
      [GATE]: aProblem({
        status: 409,
        title: "Workflow run command refused",
        detail: "the workflow ship has no gate a person answers at ship",
      }),
    });

    expect(await screen.findByText(/no gate a person answers at ship/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Decide this gate" })).toBeNull();
  });

  it("disables every choice while a decision is being recorded", async () => {
    renderGate({ [GATE]: aGate(), [DECIDE]: "pending" });

    const decide = await card();
    await userEvent.click(within(decide).getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      for (const button of within(decide).getAllByRole("button")) expect(button).toBeDisabled();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Recording the decision");
  });

  it("has no serious accessibility violation with its dialog open", async () => {
    const { container } = renderGate({ [GATE]: aGate({ text: "optional" }) });

    await userEvent.click(within(await card()).getByRole("button", { name: "Approve" }));

    expect(await seriousViolations(container)).toEqual([]);
  });
});
