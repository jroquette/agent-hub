import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aWorkflowCatalog, renderWithApi } from "../../testing/builders";
import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { NewWorkflowScreen } from "./NewWorkflow";

function Probe() {
  const { target, open } = useDiscuss();
  return (
    <output aria-label="discuss">
      {open ? "open" : "closed"}|{target?.kind ?? ""}|{target?.starters?.[0]?.message ?? ""}
    </output>
  );
}

function renderNew() {
  return renderWithApi(
    <DiscussProvider>
      <NewWorkflowScreen />
      <Probe />
    </DiscussProvider>,
    { routes: { "/api/v1/workflows": aWorkflowCatalog() }, path: "/workflows/new" },
  );
}

describe("NewWorkflowScreen", () => {
  it("waits for a description before Claude can be asked", async () => {
    renderNew();

    expect(await screen.findByRole("button", { name: "Create with Claude" })).toBeDisabled();
  });

  it("refuses a name that is not kebab-case", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.type(await screen.findByLabelText("Name (optional)"), "Bad_Name");

    expect(screen.getByText(/Lowercase letters, digits and dashes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create with Claude" })).toBeDisabled();
  });

  it("opens the Discuss panel on a request built from the form", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.click(await screen.findByRole("button", { name: "Fix a failing test" }));
    await user.click(screen.getByLabelText(/Ask for my approval/));
    await user.type(screen.getByLabelText("Name (optional)"), "fix-test");
    await user.selectOptions(screen.getByLabelText("Start from"), "issue-to-pr");
    await user.click(screen.getByRole("button", { name: "Create with Claude" }));

    const discuss = screen.getByRole("status", { name: "discuss" });
    expect(discuss).toHaveTextContent("open|New workflow|");
    expect(discuss).toHaveTextContent("Name: fix-test");
    expect(discuss).toHaveTextContent("a failing test name");
    expect(discuss).toHaveTextContent("a copy of the workflow `issue-to-pr`");
    expect(discuss).toHaveTextContent("Pause for my approval");
    const draft = Object.keys(window.localStorage).find((key) =>
      key.startsWith("ah.chat.draft.discuss.workflow-new:agent-hub:"),
    );
    expect(window.localStorage.getItem(draft ?? "")).toContain("fix-test");
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderNew();

    await screen.findByRole("button", { name: "Fix a failing test" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
