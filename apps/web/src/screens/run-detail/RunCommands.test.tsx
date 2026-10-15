import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { anEngineRun, aProblem, aRun, renderWithApi, type ApiRoutes } from "../../testing/builders";
import { RunCommands } from "./RunCommands";

const failed = anEngineRun();
const live = anEngineRun({ ended_at: null, status: "running", stage: "PICKED", failure: null });
const command = (run: { id: string }, action: string) =>
  `POST /api/v1/workflow-runs/${run.id}/${action}`;
const accepted = (run: { id: string; project: string }, action: string) => ({
  run_id: run.id,
  project: run.project,
  action,
});

function renderCommands(run = live, routes: ApiRoutes = {}) {
  return renderWithApi(<RunCommands run={run} />, { routes });
}

function names(): string[] {
  const group = screen.queryByRole("group", { name: "Run commands" });
  return group
    ? within(group)
        .getAllByRole("button")
        .map((b) => b.textContent)
    : [];
}

describe("RunCommands", () => {
  it("offers Cancel, Resume and Abandon on a running engine run", () => {
    renderCommands(live);

    expect(names()).toEqual(["Cancel", "Resume", "Abandon"]);
  });

  it("offers Resume and Abandon but not Cancel on a failed engine run", () => {
    renderCommands(failed);

    expect(names()).toEqual(["Resume", "Abandon"]);
  });

  it("offers nothing on an ended or issue-to-pr run", () => {
    renderCommands(anEngineRun({ status: "done", failure: null }));
    expect(names()).toEqual([]);
  });

  it("offers nothing on a run that is not an engine run", () => {
    renderCommands(aRun({ status: "running", content_hash: null }));
    expect(names()).toEqual([]);
  });

  it.each([
    ["Cancel", "cancel", "Cancel this run?", /SIGINT/],
    ["Resume", "resume", "Resume this run?", /reusing what completed/],
    ["Abandon", "abandon", "Abandon this run?", /ends the run cancelled/i],
  ])("asks before %s, then sends the command", async (label, action, heading, consequence) => {
    const { requests } = renderCommands(live, { [command(live, action)]: accepted(live, action) });

    await userEvent.click(screen.getByRole("button", { name: label }));
    const dialog = screen.getByRole("dialog", { name: heading });
    expect(dialog).toHaveTextContent(consequence);
    expect(requests.some((r) => r.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: `${label} run` }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    const post = requests.find((r) => r.method === "POST");
    expect(new URL(post?.url ?? "http://x").pathname).toBe(
      `/api/v1/workflow-runs/${live.id}/${action}`,
    );
    expect(post?.headers.get("content-type")).toContain("application/json");
    expect(await screen.findByRole("status")).toHaveTextContent(/sent|ended|resumes/i);
  });

  it("keeps the dialog with the reason when the server refuses", async () => {
    renderCommands(live, {
      [command(live, "cancel")]: aProblem({
        status: 409,
        title: "Workflow run command refused",
        detail: "no live child started by hub web runs it; stop it where it runs",
      }),
    });

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    const dialog = screen.getByRole("dialog", { name: "Cancel this run?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel run" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Could not cancel the run");
    expect(alert).toHaveTextContent("no live child started by hub web runs it");
  });

  it("closes without sending when kept with Escape", async () => {
    const { requests } = renderCommands(live);

    await userEvent.click(screen.getByRole("button", { name: "Abandon" }));
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Abandon" })).toHaveFocus();
    expect(requests.some((r) => r.method === "POST")).toBe(false);
  });

  it("has no serious accessibility violation with a confirmation open", async () => {
    const { container } = renderCommands(live);

    await userEvent.click(screen.getByRole("button", { name: "Resume" }));

    expect(await seriousViolations(container)).toEqual([]);
  });
});
