import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { aCapabilities, aWorkdir, anAgentSession, anId, renderWithApi } from "../testing/builders";
import {
  discussPrompt,
  DiscussProvider,
  referencedMessage,
  useDiscuss,
  useDiscussTarget,
} from "./discuss";
import type { DiscussReference, DiscussTarget } from "./discuss";
import { DiscussPanel } from "./DiscussPanel";

const ID = anId(3, "0192a5e5");
const SESSION = `/api/v1/agent-sessions/${ID}`;

const feature: DiscussTarget = {
  key: "feature:demo:virtual-iban",
  project: "demo",
  kind: "Feature spec",
  title: "virtual-iban",
  path: "brain/features/virtual-iban/spec.md",
};
const skill: DiscussTarget = {
  key: "skill:demo:plan",
  project: "demo",
  kind: "Skill",
  title: "plan",
  starters: [{ label: "Is this still true?", message: "Check it against the code." }],
};
const AC: DiscussReference = {
  id: "ac:AC-7",
  label: "AC-7",
  source: "brain/features/virtual-iban/features.json",
  quote: "AC-7: routes multi-parcel",
};

function Screen() {
  const [target, setTarget] = useState(feature);
  useDiscussTarget(target);
  const { addReference } = useDiscuss();
  return (
    <>
      <button
        type="button"
        onClick={() => {
          addReference(AC);
        }}
      >
        point
      </button>
      <button
        type="button"
        onClick={() => {
          setTarget((t) => (t === feature ? skill : feature));
        }}
      >
        switch
      </button>
      <DiscussPanel />
    </>
  );
}

function renderPanel() {
  return renderWithApi(
    <DiscussProvider>
      <Screen />
    </DiscussProvider>,
    {
      routes: {
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": { items: [aWorkdir()], warnings: [] },
        "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }),
        [SESSION]: anAgentSession({ id: ID, status: "idle", last_seq: 0 }),
        [`${SESSION}/events`]: { items: [], next_after: null },
      },
    },
  );
}

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  window.localStorage.clear();
});

describe("DiscussPanel", () => {
  it("starts with the discuss prompt and the references, then keeps that session for its target", async () => {
    const view = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "point" }));
    const box = await screen.findByRole("textbox", { name: "Message Claude" });
    await waitFor(() => {
      expect(box).toBeEnabled();
    });

    await userEvent.type(box, "Is this still right?{Enter}");

    const created = await waitFor(() => {
      const found = view.requests.filter(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      );
      expect(found).toHaveLength(1);
      return found[0];
    });
    const body = JSON.parse((await created?.clone().text()) ?? "{}") as { prompt: string };
    expect(body.prompt).toBe(
      discussPrompt(feature, referencedMessage([AC], "Is this still right?")),
    );
    expect(await screen.findByRole("link", { name: "Full chat" })).toHaveAttribute(
      "href",
      `/agent-sessions/${ID}`,
    );
    expect(window.localStorage.getItem(`ah.discuss.session.${feature.key}`)).toBe(ID);

    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    expect(screen.queryByRole("link", { name: "Full chat" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    expect(await screen.findByRole("link", { name: "Full chat" })).toHaveAttribute(
      "href",
      `/agent-sessions/${ID}`,
    );
  });

  it("starts the conversation with a starter's message in one click", async () => {
    window.localStorage.setItem("ah.discuss.open", "1");
    const view = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    const group = await screen.findByRole("group", { name: "Start with" });
    const starter = within(group).getByRole("button", { name: "Is this still true?" });
    await waitFor(() => {
      expect(starter).toBeEnabled();
    });

    await userEvent.click(starter);

    const created = await waitFor(() => {
      const found = view.requests.filter(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      );
      expect(found).toHaveLength(1);
      return found[0];
    });
    const body = JSON.parse((await created?.clone().text()) ?? "{}") as { prompt: string };
    expect(body.prompt).toBe(discussPrompt(skill, "Check it against the code."));
  });

  it("offers no starters when the target has none", async () => {
    window.localStorage.setItem("ah.discuss.open", "1");
    renderPanel();
    await screen.findByRole("textbox", { name: "Message Claude" });

    expect(screen.queryByRole("group", { name: "Start with" })).toBeNull();
  });
});
