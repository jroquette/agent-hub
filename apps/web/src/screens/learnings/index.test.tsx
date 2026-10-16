import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aLearning,
  aLearningActionResult,
  aLearningDetail,
  anId,
  aPage,
  aProblem,
  aProjectDetail,
  aStreamCounts,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { LearningsScreen } from "./index";

const newer = aLearning({
  id: "l-new",
  text: "Order book snapshot before diff replay",
  proposed_at: at(900),
  provenance: "agent-from-code",
  project: "loki-trader",
  summary: null,
  note_unavailable: "Note not in the hub checkout",
});
const older = aLearning({
  id: "l-old",
  text: "Retry flaky CI before calling a run failed",
  proposed_at: at(100),
  provenance: "agent-from-external",
  summary: "Rerun once; a second failure is real.",
});
const learnings = [newer, older];
const detailOf = (l: typeof newer) =>
  aLearningDetail({ ...l, note: null, note_unavailable: l.note_unavailable ?? null });
const routes: ApiRoutes = {
  "/api/v1/learnings": aPage(learnings),
  "/api/v1/learnings/l-new": detailOf(newer),
  "/api/v1/learnings/l-old": detailOf(older),
  "/api/v1/projects/agent-hub": aProjectDetail({ hub_repo: "agent-hub-hub" }),
  "/api/v1/projects/loki-trader": aProjectDetail({ hub_repo: "loki-trader-hub" }),
};

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
  it("lists proposals oldest first with their summaries", async () => {
    open();

    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Proposed learnings" });
    await within(table).findByText("Retry flaky CI before calling a run failed");
    const titles = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.textContent);
    expect(titles[0]).toContain("Retry flaky CI");
    expect(titles[0]).toContain("Rerun once; a second failure is real.");
    expect(titles[1]).toContain("Order book snapshot");
    expect(titles[1]).toContain("Note not in the hub checkout");
  });

  it("shows the oldest proposal with its provenance, note and source", async () => {
    open();

    const detail = await screen.findByRole("region", { name: "Proposal" });
    expect(
      within(detail).getByRole("heading", { name: "Retry flaky CI before calling a run failed" }),
    ).toBeInTheDocument();
    expect(within(detail).getByText(/External/)).toBeInTheDocument();
    expect(within(detail).getByText("Proposed")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: /Open at that moment/ })).toHaveAttribute(
      "href",
      `/sessions/${anId(1, "5091b986")}?tab=timeline&event=${anId(10, "0192aaaa")}`,
    );
  });

  it("lets accept and reject act and keeps only snooze in Phase 3", async () => {
    open();

    const detail = await screen.findByRole("region", { name: "Proposal" });
    expect(await within(detail).findByRole("button", { name: "Accept" })).toBeEnabled();
    expect(within(detail).getByRole("button", { name: "Reject" })).toBeEnabled();
    const snooze = within(detail).getByRole("button", { name: /^Snooze/ });
    expect(snooze).toBeDisabled();
    expect(snooze).toHaveAttribute("title", "Available in Phase 3. This version is read-only.");
  });

  it("disables accept and reject on a read-only hub (read-only)", async () => {
    open({
      "/api/v1/learnings/l-old": aLearningDetail({
        ...older,
        actions_unavailable: "Hub is read-only here",
      }),
    });

    const detail = await screen.findByRole("region", { name: "Proposal" });
    await within(detail).findByText("Hub is read-only here");
    for (const name of ["Accept", "Reject"]) {
      const button = within(detail).getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Hub is read-only here");
    }
  });

  it("keeps the decided learning open with its pull request after the list moves on", async () => {
    let decided = false;
    const { router } = open({
      "/api/v1/learnings": () => aPage(decided ? [newer] : learnings),
      "POST /api/v1/learnings/l-old/accept": () => {
        decided = true;
        return aLearningActionResult();
      },
    });
    const detail = await screen.findByRole("region", { name: "Proposal" });

    await userEvent.click(await within(detail).findByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: "Open pull request" }));

    expect(await screen.findByText("Pull request opened")).toBeInTheDocument();
    expect(router.state.location.search).toBe("?learning=l-old");
    await waitFor(() => {
      expect(screen.getAllByRole("row")).toHaveLength(2);
    });
    expect(
      within(screen.getByRole("region", { name: "Proposal" })).getByRole("heading", {
        name: "Retry flaky CI before calling a run failed",
      }),
    ).toBeInTheDocument();
  });

  it("keeps the decided learning open with its pull request when it was the last proposal", async () => {
    let decided = false;
    open({
      "/api/v1/learnings": () => aPage(decided ? [] : [older]),
      "POST /api/v1/learnings/l-old/accept": () => {
        decided = true;
        return aLearningActionResult();
      },
    });
    const detail = await screen.findByRole("region", { name: "Proposal" });

    await userEvent.click(await within(detail).findByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: "Open pull request" }));

    expect(await screen.findByText("Pull request opened")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByRole("row")).toHaveLength(1);
    });
    expect(screen.getByText("Pull request opened")).toBeInTheDocument();
    expect(screen.queryByText("Inbox empty")).not.toBeInTheDocument();
  });

  it("opens the proposal named in the path when a link points at one", async () => {
    renderWithApi(<LearningsScreen />, {
      routes,
      path: "/knowledge/learnings/l-new",
      route: "/knowledge/learnings/:learningId",
    });

    const detail = await screen.findByRole("region", { name: "Proposal" });
    expect(
      await within(detail).findByRole("heading", {
        name: "Order book snapshot before diff replay",
      }),
    ).toBeInTheDocument();
  });

  it("selects another proposal from the queue and keeps it in the URL", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByText("Order book snapshot before diff replay"));

    const detail = screen.getByRole("region", { name: "Proposal" });
    expect(
      within(detail).getByRole("heading", { name: "Order book snapshot before diff replay" }),
    ).toBeInTheDocument();
    expect(await within(detail).findByText("Note not in the hub checkout")).toBeInTheDocument();
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

  it("lists decidable proposals before blocked ones and says why each is blocked", async () => {
    const blocked = aLearning({
      id: "l-gone",
      text: "Proposal: a note nobody pushed",
      proposed_at: at(10),
      summary: null,
      note_unavailable: "Note not in the hub checkout",
      actions_unavailable: "Note not in the hub checkout",
    });
    open({
      "/api/v1/learnings": aPage([blocked, older]),
      "/api/v1/learnings/l-gone": detailOf(blocked),
    });

    const table = await screen.findByRole("table", { name: "Proposed learnings" });
    await within(table).findByText("Retry flaky CI before calling a run failed");
    const [first, second] = within(table).getAllByRole("row").slice(1);
    if (!first || !second) throw new Error("expected two rows");
    expect(first.textContent).toContain("Retry flaky CI");
    expect(second.textContent).toContain("a note nobody pushed");
    expect(second.textContent).not.toContain("Proposal:");
    expect(within(second).getByText("Note not in the hub checkout")).toBeVisible();
    expect(screen.getByText(/1 ready · 1 blocked/)).toBeInTheDocument();
  });

  it("keeps the status in the URL", async () => {
    open({}, "/knowledge/learnings?status=rejected");

    await screen.findByRole("table", { name: "Proposed learnings" });
    expect(screen.getByRole("button", { name: "Rejected" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open();
    const detail = await screen.findByRole("region", { name: "Proposal" });
    await within(detail).findByRole("button", { name: "Accept" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("LearningsScreen filters", () => {
  it("narrows the queue to one project and keeps the choice in the URL", async () => {
    const { router } = open();
    const table = await screen.findByRole("table", { name: "Proposed learnings" });
    await within(table).findByText("Order book snapshot before diff replay");

    const projects = screen.getByRole("group", { name: "Project" });
    await userEvent.click(within(projects).getByRole("button", { name: "loki-trader · 1" }));

    await waitFor(() => {
      expect(within(table).queryByText(/Retry flaky CI/)).not.toBeInTheDocument();
    });
    expect(within(table).getByText("Order book snapshot before diff replay")).toBeInTheDocument();
    expect(router.state.location.search).toContain("project=loki-trader");
  });

  it("says nothing matches when the search finds no learning", async () => {
    open();
    await screen.findByRole("table", { name: "Proposed learnings" });

    await userEvent.type(await screen.findByRole("searchbox", { name: "Search learnings" }), "zzz");

    expect(await screen.findByText("No learnings match these filters.")).toBeInTheDocument();
  });
});
