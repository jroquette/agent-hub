import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  aCapabilities,
  aProblem,
  anAgentSession,
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { DiscussChat } from "./DiscussChat";

const ID = anId(3, "0192f00d");
const SESSION = `/api/v1/agent-sessions/${ID}`;

function renderChat(restricted: boolean, overrides: ApiRoutes = {}) {
  return renderWithApi(<DiscussChat agentSessionId={ID} onGone={vi.fn()} />, {
    routes: {
      "/api/v1/agent-sessions/capabilities": aCapabilities(),
      [SESSION]: anAgentSession({
        id: ID,
        status: "idle",
        last_seq: 0,
        ...(restricted ? { restricted: true } : {}),
      }),
      [`${SESSION}/events`]: { items: [], next_after: null },
      ...overrides,
    },
  });
}

describe("DiscussChat", () => {
  it("shows no Mode select for a session held to a tool policy, even when not locked", async () => {
    renderChat(true);

    expect(await screen.findByRole("button", { name: /^Model and effort/ })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Mode" })).toBeNull();
  });

  it("shows the Mode select for an ordinary session", async () => {
    renderChat(false);

    expect(await screen.findByRole("combobox", { name: "Mode" })).toBeInTheDocument();
  });

  it("focuses the composer on open when nothing is pending", async () => {
    renderChat(false);

    const composer = await screen.findByRole("textbox", { name: "Message Claude" });
    expect(composer).toHaveFocus();
  });
  it("AC-681.4 AC-681.9 shows the session's effort and Ultracode on the model pill", async () => {
    renderChat(false, {
      [SESSION]: anAgentSession({
        id: ID,
        status: "idle",
        last_seq: 0,
        effort: "high",
        ultracode: true,
      }),
    });

    const pill = await screen.findByRole("button", { name: /^Model and effort/ });
    expect(pill).toHaveAccessibleName(/, High, Ultracode$/);
  });

  it("AC-681.10 lists Fable in the model menu when the capabilities cannot be read", async () => {
    renderChat(false, {
      "/api/v1/agent-sessions/capabilities": aProblem({ status: 500, title: "Server error" }),
    });

    await userEvent.click(await screen.findByRole("button", { name: /^Model and effort/ }));

    expect(screen.getByRole("menuitemradio", { name: "Fable" })).toBeInTheDocument();
  });
});
