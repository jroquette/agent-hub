import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentStatusBadge, ReconnectBanner, StoredCopyLabel } from "./SessionStatus";

describe("AgentStatusBadge", () => {
  it.each([
    ["running", null, "Running"],
    ["idle", null, "Idle"],
    ["waiting_permission", null, "Waiting for you"],
    ["failed", null, "Failed"],
    ["ended", "idle_timeout", "Ended · idle timeout"],
    ["ended", null, "Ended"],
  ] as const)("reads %s (%s) as %s", (status, endReason, text) => {
    render(<AgentStatusBadge status={status} endReason={endReason} />);

    expect(screen.getByText(text)).toBeInTheDocument();
  });
});

describe("AgentStatusBadge with background agents", () => {
  it("reads an idle session with agents still running as at work", () => {
    const task = (id: string, type: string) => ({
      id,
      description: null,
      toolUseId: null,
      startedAt: "2026-10-19T10:00:00Z",
      endedAt: null,
      status: "running" as const,
      type,
    });
    render(
      <AgentStatusBadge
        status="idle"
        background={[task("a", "local_agent"), task("b", "local_agent"), task("c", "local_bash")]}
      />,
    );

    expect(screen.getByText("Background · 2 agents, 1 command")).toBeInTheDocument();
  });
});

describe("ReconnectBanner (composer)", () => {
  it("shows the banner while the stream is lost and hides it once it resumes", () => {
    const { rerender } = render(<ReconnectBanner connected={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Connection to this session lost");

    rerender(<ReconnectBanner connected />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("StoredCopyLabel", () => {
  it("explains where the redacted copy comes from", () => {
    render(<StoredCopyLabel />);

    expect(screen.getByText("stored copy, redacted")).toHaveAttribute(
      "title",
      expect.stringContaining("secrets are redacted") as string,
    );
  });
});
