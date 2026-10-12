import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { aSession, aSessionLabel, anId } from "../testing/builders";
import { SessionLabel, sessionIdentity } from "./SessionLabel";

const ID = anId(1, "5091b986");

describe("sessionIdentity", () => {
  it("reads issue and workflow over repo and branch when the label has them (AC-201.4)", () => {
    const session = aSession({
      label: aSessionLabel({
        issue: "DEMO-1511",
        workflow: "/feature",
        repo: "demo",
        branch: "main",
      }),
    });

    expect(sessionIdentity(session)).toEqual({
      title: "DEMO-1511 · /feature",
      detail: "demo · main",
    });
  });

  it("shows only what it has when the label has an issue or a workflow alone", () => {
    expect(
      sessionIdentity(aSession({ label: aSessionLabel({ issue: null, workflow: "/fix" }) })).title,
    ).toBe("/fix");
    expect(
      sessionIdentity(aSession({ label: aSessionLabel({ issue: "AGH-9", workflow: null }) })).title,
    ).toBe("AGH-9");
  });

  it("falls back to repo · branch, then the short id when no issue and no workflow (AC-201.5)", () => {
    const bare = aSessionLabel({ issue: null, workflow: null, workflows: [] });

    expect(sessionIdentity(aSession({ id: ID, label: bare }))).toEqual({
      title: "agent-hub · dev/agh-48-live-tiles",
      detail: "5091b986",
    });
    expect(
      sessionIdentity(
        aSession({ id: ID, repo: "web", label: { ...bare, repo: null, branch: null } }),
      ),
    ).toEqual({ title: "web", detail: "5091b986" });
    expect(sessionIdentity(aSession({ id: ID, repo: null, label: null }))).toEqual({
      title: "5091b986",
      detail: null,
    });
  });

  it("uses the session's repo when the label has none", () => {
    const session = aSession({ repo: "web", label: aSessionLabel({ repo: null, branch: "x" }) });

    expect(sessionIdentity(session).detail).toBe("web · x");
  });
});

describe("SessionLabel", () => {
  it("renders the title over repo · branch and never the agent when given a main-agent session", () => {
    const { container } = render(
      <SessionLabel
        session={aSession({
          agent: "main",
          label: aSessionLabel({
            issue: "DEMO-1511",
            repo: "demo",
            branch: "roquettejh/demo-1511-x",
          }),
        })}
      />,
    );

    expect(screen.getByText("DEMO-1511 · /feature")).toBeInTheDocument();
    expect(screen.getByText("demo · roquettejh/demo-1511-x")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\bmain\b/);
  });

  it("is never blank when the session has no label, repo or branch (AC-201.5)", () => {
    const { container } = render(
      <SessionLabel session={aSession({ id: ID, repo: null, label: null })} />,
    );

    expect(container.textContent).toBe("5091b986");
  });
});
