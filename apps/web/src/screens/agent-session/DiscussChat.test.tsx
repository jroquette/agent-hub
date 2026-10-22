import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { aCapabilities, anAgentSession, anId, renderWithApi } from "../../testing/builders";
import { DiscussChat } from "./DiscussChat";

const ID = anId(3, "0192f00d");
const SESSION = `/api/v1/agent-sessions/${ID}`;

function renderChat(restricted: boolean) {
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
    },
  });
}

describe("DiscussChat", () => {
  it("shows no Mode select for a session held to a tool policy, even when not locked", async () => {
    renderChat(true);

    expect(await screen.findByRole("combobox", { name: "Model" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Mode" })).toBeNull();
  });

  it("shows the Mode select for an ordinary session", async () => {
    renderChat(false);

    expect(await screen.findByRole("combobox", { name: "Mode" })).toBeInTheDocument();
  });
});
