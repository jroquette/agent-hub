import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  aSession,
  aSessionLabel,
  anActor,
  anId,
  at,
  renderWithApi,
  type Session,
} from "../../testing/builders";
import { Header } from "./Header";

const NOW = Date.parse(at(900));

function renderHeader(session: Session) {
  return renderWithApi(<Header session={session} now={NOW} staleSince={null} />);
}

describe("Header", () => {
  it("titles the session by its label and shows repo · branch, never the agent (label)", () => {
    const { container } = renderHeader(
      aSession({
        agent: "main",
        issue: null,
        label: aSessionLabel({ issue: "DEMO-1511", repo: "demo", branch: "main" }),
      }),
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "DEMO-1511 · /feature" }),
    ).toBeInTheDocument();
    expect(screen.getByText("demo · main")).toBeInTheDocument();
    const texts = [...container.querySelectorAll("*")]
      .flatMap((element) => [...element.childNodes])
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent ?? "");
    expect(texts.filter((text) => /\bmain\b/.test(text))).toEqual(["demo · main"]);
  });

  it("falls back to the short id when the label is missing (label)", () => {
    renderHeader(aSession({ id: anId(1, "5091b986"), repo: null, label: null, issue: null }));

    expect(screen.getByRole("heading", { level: 1, name: "5091b986" })).toBeInTheDocument();
  });

  it("names the subagents that acted when the session has some (label)", () => {
    renderHeader(
      aSession({
        actors: [
          anActor(),
          anActor({ kind: "subagent", type: "Explore", agent_id: "a1" }),
          anActor({ kind: "subagent", type: "Explore", agent_id: "a2" }),
          anActor({ kind: "subagent", type: "reviewer", agent_id: "a3" }),
        ],
      }),
    );

    expect(screen.getByText("Main agent · 3 subagents: Explore ×2, reviewer")).toBeInTheDocument();
  });
});
