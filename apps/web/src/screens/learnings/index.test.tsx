import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aLearning,
  anId,
  aPage,
  aProblem,
  aStreamCounts,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { LearningsScreen } from "./index";

const learnings = [
  aLearning({
    id: "l-new",
    text: "Order book snapshot before diff replay",
    proposed_at: at(900),
    provenance: "agent-from-code",
    target: { kind: "repo", path: "tradeSentinel/AGENTS.md" },
    project: "loki-trader",
  }),
  aLearning({
    id: "l-old",
    text: "Retry flaky CI before calling a run failed",
    proposed_at: at(100),
    provenance: "agent-from-external",
    target: { kind: "team", path: "brain/learnings/ci.md" },
  }),
];
const routes: ApiRoutes = { "/api/v1/learnings": aPage(learnings) };

function open(extra: ApiRoutes = {}, path = "/knowledge/learnings", connected = true) {
  const ui = connected ? (
    <GlobalStreamProvider project={null}>
      <LearningsScreen />
    </GlobalStreamProvider>
  ) : (
    <LearningsScreen />
  );
  return renderWithApi(ui, { routes: { ...routes, ...extra }, path });
}

describe("LearningsScreen", () => {
  it("tags Knowledge P3 and lists proposals oldest first", async () => {
    open();

    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).toBeInTheDocument();
    expect(screen.getAllByText("P3")[0]).toHaveClass("ah-phase");
    const table = await screen.findByRole("table", { name: "Proposed learnings" });
    await within(table).findByText("Retry flaky CI before calling a run failed");
    const titles = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.textContent);
    expect(titles[0]).toContain("Retry flaky CI");
    expect(titles[1]).toContain("Order book snapshot");
  });

  it("shows the oldest proposal with its provenance, target and evidence", async () => {
    open();

    const detail = await screen.findByRole("region", { name: "Proposal" });
    expect(
      within(detail).getByRole("heading", { name: "Retry flaky CI before calling a run failed" }),
    ).toBeInTheDocument();
    expect(within(detail).getByText(/External/)).toBeInTheDocument();
    expect(within(detail).getByTitle("brain/learnings/ci.md")).toBeInTheDocument();
    expect(within(detail).getByText(/team brain · via hub PR/)).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: /Open at that moment/ })).toHaveAttribute(
      "href",
      `/sessions/${anId(1, "5091b986")}?tab=timeline&event=${anId(10, "0192aaaa")}`,
    );
  });

  it("keeps accept, reject and snooze disabled with the Phase 3 tooltip", async () => {
    open();

    await screen.findByRole("region", { name: "Proposal" });
    for (const name of [/^Accept a/, /^Reject r/, /^Snooze/]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Available in Phase 3. This version is read-only.");
    }
  });

  it("selects another proposal from the queue and keeps it in the URL", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByText("Order book snapshot before diff replay"));

    const detail = screen.getByRole("region", { name: "Proposal" });
    expect(within(detail).getByText(/repo AGENTS.md · via that repo's PR/)).toBeInTheDocument();
    expect(router.state.location.search).toBe("?learning=l-new");
  });

  it("asks for accepted learnings when the status changes", async () => {
    const { requests } = open();
    await screen.findByRole("table", { name: "Proposed learnings" });

    await userEvent.click(screen.getByRole("button", { name: "Accepted" }));

    await waitFor(() => {
      expect(requests.some((r) => new URL(r.url).searchParams.get("status") === "accepted")).toBe(
        true,
      );
    });
  });

  it("refetches when the stream's proposal count changes", async () => {
    const { requests, stream } = open();
    await screen.findByRole("table", { name: "Proposed learnings" });
    const before = requests.length;

    act(() => {
      stream("/api/v1/events/stream").emit("counts", aStreamCounts({ learnings_proposed: 2 }));
    });
    act(() => {
      stream("/api/v1/events/stream").emit("counts", aStreamCounts({ learnings_proposed: 3 }));
    });

    await waitFor(() => {
      expect(requests.length).toBeGreaterThan(before);
    });
  });

  describe("states", () => {
    it("shows skeletons while loading", async () => {
      const { container } = open({ "/api/v1/learnings": "pending" });

      await waitFor(() => {
        expect(container.querySelector(".ah-skel")).not.toBeNull();
      });
    });

    it("shows the inbox empty copy", async () => {
      open({ "/api/v1/learnings": aPage([]) });

      expect(await screen.findByText("Inbox empty")).toBeInTheDocument();
      expect(
        screen.getByText(/notes in brain\/_inbox\/ appear here for triage/),
      ).toBeInTheDocument();
    });

    it("shows the problem with Try again", async () => {
      open({
        "/api/v1/learnings": aProblem({ status: 503, title: "Database busy", detail: "Locked." }),
      });

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Database busy");
      expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    });

    it("shows the as-of stamp when the collector is offline", () => {
      open({}, "/knowledge/learnings", false);

      expect(screen.getByText(/Stale · as of/)).toBeInTheDocument();
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open();
    await screen.findByRole("region", { name: "Proposal" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
