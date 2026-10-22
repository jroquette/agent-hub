import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  aCapabilities,
  aPage,
  aProjectSummary,
  aWorkdir,
  anAgentSession,
  anId,
  renderWithApi,
} from "../../testing/builders";
import { StartTicketControl } from "./StartTicket";

const AGENT = "/api/v1/agent-sessions";
const HUB = aWorkdir({ kind: "hub", skills: ["fix", "refactor"], workdir_id: "aaaaaaaaaaaaaaaa" });
const REPO = aWorkdir({ kind: "repo", label: "agent-hub", workdir_id: "bbbbbbbbbbbbbbbb" });

function mount(capabilities = aCapabilities()) {
  const created = anAgentSession({ id: anId(9, "0192a5e5"), status: "running" });
  const view = renderWithApi(<StartTicketControl scope="agent-hub" />, {
    routes: {
      "/api/v1/projects": aPage([aProjectSummary()]),
      "/api/v1/agent-sessions/capabilities": capabilities,
      [AGENT]: aPage([]),
      "/api/v1/agent-sessions/workdirs": aPage([REPO, HUB]),
      [`POST ${AGENT}`]: created,
    },
    path: "/tickets",
  });
  return { created, view };
}

describe("StartTicketControl", () => {
  it("starts a session in the hub folder with the skill and the issue written (AC-426.10)", async () => {
    const { created, view } = mount();

    await userEvent.click(await screen.findByRole("button", { name: "Start ticket" }));
    const dialog = screen.getByRole("dialog", { name: "Start ticket" });
    const prompt = within(dialog).getByRole("textbox", { name: "Prompt" });
    expect(prompt).toHaveValue("/fix ");
    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      HUB.workdir_id,
    );

    await userEvent.click(within(dialog).getByRole("button", { name: "/refactor" }));
    await userEvent.type(prompt, "AGH-12");
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    const post = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
    );
    expect(JSON.parse((await post?.clone().text()) ?? "{}")).toMatchObject({
      prompt: "/refactor AGH-12",
      workdir_id: HUB.workdir_id,
    });
  });

  it("is not offered where sessions cannot be driven (AC-426.10)", async () => {
    mount(aCapabilities({ available: false, reason: "claude is not installed" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Start ticket" })).not.toBeInTheDocument();
    });
  });
});
