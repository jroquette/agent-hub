import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { aSession, aSessionLabel, anId } from "../testing/builders";
import { SessionLabel, sessionIdentity, slugAfterIssue, ticketName } from "./SessionLabel";

const ID = anId(1, "5091b986");

describe("sessionIdentity", () => {
  it("reads issue and workflow over repo and branch when the label has them (AC-201.4)", () => {
    const session = aSession({
      label: aSessionLabel({
        issue: "ACME-1511",
        workflow: "/feature",
        repo: "storefront",
        branch: "main",
      }),
    });

    expect(sessionIdentity(session)).toEqual({
      title: "ACME-1511 · /feature",
      detail: "storefront · main",
      named: false,
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
      named: false,
    });
    expect(
      sessionIdentity(
        aSession({ id: ID, repo: "web", label: { ...bare, repo: null, branch: null } }),
      ),
    ).toEqual({ title: "web", detail: "5091b986", named: false });
    expect(sessionIdentity(aSession({ id: ID, repo: null, label: null }))).toEqual({
      title: "5091b986",
      detail: null,
      named: false,
    });
  });

  it("reads the session's name over workflow, repo and branch when it has a title", () => {
    const session = aSession({
      label: aSessionLabel({
        title: "Orders export as CSV",
        issue: null,
        workflow: "/feature",
        repo: "storefront",
        branch: "main",
      }),
    });

    expect(sessionIdentity(session)).toEqual({
      title: "Orders export as CSV",
      detail: "/feature · storefront · main",
      named: true,
    });
  });

  it("names a session on a ticket by the ticket, its title after it when nothing gives a slug", () => {
    const session = aSession({
      label: aSessionLabel({
        title: "Orders export as CSV",
        issue: "ACME-1511",
        workflow: "/feature",
        repo: "storefront",
        branch: "main",
      }),
    });

    expect(sessionIdentity(session)).toEqual({
      title: "ACME-1511: Orders export as CSV",
      detail: "/feature · storefront · main",
      named: true,
    });
  });

  it("keeps the short id under the name when the label has nothing else", () => {
    const label = aSessionLabel({
      title: "Orders export",
      issue: null,
      workflow: null,
      repo: null,
      branch: null,
    });

    expect(sessionIdentity(aSession({ id: ID, repo: null, label })).detail).toBe("5091b986");
    expect(
      sessionIdentity(aSession({ label: aSessionLabel({ title: "  ", issue: null }) })).named,
    ).toBe(false);
  });

  it("uses the session's repo when the label has none", () => {
    const session = aSession({
      repo: "web",
      label: aSessionLabel({ repo: null, branch: "x", issue: null }),
    });

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
            issue: "ACME-1511",
            repo: "storefront",
            branch: "roquettejh/acme-1511-x",
          }),
        })}
      />,
    );

    expect(screen.getByText("ACME-1511: x")).toBeInTheDocument();
    expect(screen.getByText("/feature · storefront · roquettejh/acme-1511-x")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\bmain\b/);
  });

  it("renders the name in prose, not as an identifier, when the session has a title", () => {
    render(
      <SessionLabel
        session={aSession({ label: aSessionLabel({ title: "Orders export", issue: null }) })}
      />,
    );

    expect(screen.getByText("Orders export")).not.toHaveClass("ah-mono");
    expect(screen.getByText("/feature · agent-hub · dev/agh-48-live-tiles")).toHaveClass("ah-mono");
  });

  it("is never blank when the session has no label, repo or branch (AC-201.5)", () => {
    const { container } = render(
      <SessionLabel session={aSession({ id: ID, repo: null, label: null })} />,
    );

    expect(container.textContent).toBe("5091b986");
  });
});

describe("ticket names", () => {
  it("names a ticket session as its commits read: the ticket's title, else the feature's slug", () => {
    const label = aSessionLabel({
      issue: "TIP-1563",
      branch: "roquettejh/tip-1563-allianz-claim-api",
      title: "Status do agente em execução",
    });

    const feature = { project: "tipple", slug: "allianz-ecommerce-claim" };
    expect(ticketName(label, new Map([["TIP-1563", { ...feature, title: null }]]))).toBe(
      "TIP-1563: allianz-ecommerce-claim",
    );
    expect(
      ticketName(
        label,
        new Map([["TIP-1563", { ...feature, title: "Allianz claims from the e-commerce flow" }]]),
      ),
    ).toBe("TIP-1563: Allianz claims from the e-commerce flow");
    expect(ticketName(label)).toBe("TIP-1563: allianz-claim-api");
    expect(sessionIdentity(aSession({ label }))).toMatchObject({
      title: "TIP-1563: allianz-claim-api",
      named: true,
    });
  });

  it("falls back to the worktree's slug, then Claude's title, and is null without an issue", () => {
    expect(
      ticketName(
        aSessionLabel({ issue: "AGH-288", branch: "main", worktree: "agh-288-guard-asks" }),
      ),
    ).toBe("AGH-288: guard-asks");
    expect(
      ticketName(
        aSessionLabel({ issue: "AGH-288", branch: "main", worktree: null, title: "Guard" }),
      ),
    ).toBe("AGH-288: Guard");
    expect(ticketName(aSessionLabel({ issue: null, title: "Guard" }))).toBeNull();
  });

  it("reads the slug only after the whole issue id", () => {
    expect(slugAfterIssue("dev/agh-28-fix", "AGH-2")).toBeNull();
    expect(slugAfterIssue("dev/AGH-2_fix-it", "AGH-2")).toBe("fix-it");
    expect(slugAfterIssue("dev/agh-2", "AGH-2")).toBeNull();
  });
});
