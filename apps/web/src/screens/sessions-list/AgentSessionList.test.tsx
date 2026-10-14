import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { seriousViolations } from "../../testing/axe";
import { aCapabilities, aPermissionRequest, anAgentSession, anId } from "../../testing/builders";
import {
  AgentSessionList,
  SESSIONS_OFF_TYPE,
  agentSessionHref,
  type AgentSessionListProps,
} from "./AgentSessionList";

function show(overrides: Partial<AgentSessionListProps> = {}) {
  const props: AgentSessionListProps = {
    sessions: [anAgentSession()],
    capabilities: aCapabilities(),
    onNewSession: vi.fn(),
    ...overrides,
  };
  const view = render(
    <MemoryRouter>
      <AgentSessionList {...props} />
    </MemoryRouter>,
  );
  return { ...view, props };
}

describe("AgentSessionList (permission)", () => {
  it("highlights a session waiting for a permission with what it waits on", () => {
    show({
      sessions: [
        anAgentSession({
          id: anId(2, "0192a5e5"),
          title: "Push the fix",
          status: "waiting_permission",
          open_permission: aPermissionRequest(),
        }),
        anAgentSession(),
      ],
    });

    const list = screen.getByRole("list", { name: "Agent sessions" });
    const [waiting, idle] = within(list).getAllByRole("listitem");
    expect(waiting).toHaveClass("as-list-waiting");
    expect(waiting).toHaveTextContent("Waiting for you");
    expect(waiting).toHaveTextContent("Waiting for you: Bash · git status");
    expect(idle).not.toHaveClass("as-list-waiting");
    expect(idle).toHaveTextContent("Idle");
    expect(screen.getByText("1 waiting for you")).toBeInTheDocument();
  });

  it("links each session to its chat view and shows mode, model and cost", () => {
    show({ sessions: [anAgentSession({ status: "ended", end_reason: "closed" })] });

    expect(screen.getByRole("link", { name: "Run the tests" })).toHaveAttribute(
      "href",
      agentSessionHref(anAgentSession().id),
    );
    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent("Ended · closed");
    expect(item).toHaveTextContent("Ask before edits · sonnet");
    expect(item).toHaveTextContent("agent-hub-hub");
  });

  it("opens New session when sessions can start", async () => {
    const { props } = show({ sessions: [] });

    expect(screen.getByText("No session started from hub web yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New session" }));
    expect(props.onNewSession).toHaveBeenCalledTimes(1);
  });

  it("has no serious violation (permission a11y)", async () => {
    const { container } = show({
      sessions: [
        anAgentSession({ status: "waiting_permission", open_permission: aPermissionRequest() }),
      ],
    });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("AgentSessionList (unavailable)", () => {
  it.each([
    [
      new ApiProblem({ status: 401, title: "Unauthorized" }),
      "Session control is locked in this browser.",
      "?token=",
    ],
    [
      new ApiProblem({ status: 404, title: "Off", type: SESSIONS_OFF_TYPE }),
      "Session control is off in the container.",
      "Docker image",
    ],
    [
      new ApiProblem({
        status: 503,
        title: "Unavailable",
        detail: "Install agent-hub[sessions] to drive sessions",
      }),
      "Sessions cannot start here.",
      "Install agent-hub[sessions]",
    ],
  ])("shows the cause instead of New session when the API answers %s", (problem, title, detail) => {
    show({ sessions: [], problem });

    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent(title);
    expect(banner).toHaveTextContent(detail);
    expect(screen.queryByRole("button", { name: "New session" })).toBeNull();
    expect(screen.queryByText("No session started from hub web yet.")).toBeNull();
  });

  it("shows the capabilities' reason when claude is missing", () => {
    show({ capabilities: aCapabilities({ available: false, reason: "no claude on PATH" }) });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Sessions cannot start here. no claude on PATH",
    );
    expect(screen.queryByRole("button", { name: "New session" })).toBeNull();
    expect(screen.getByRole("link", { name: "Run the tests" })).toBeInTheDocument();
  });

  it("names a generic default when no reason is given", () => {
    show({ capabilities: aCapabilities({ available: false, reason: null }), sessions: [] });

    expect(screen.getByRole("status")).toHaveTextContent(
      "claude is not available on this machine.",
    );
  });

  it("offers a retry for any other problem", async () => {
    const onRetry = vi.fn();
    show({ sessions: [], problem: new ApiProblem({ status: 500, title: "Boom" }), onRetry });

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load the agent sessions");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
