import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  aProblem,
  anItemVersion,
  anItemVersionPage,
  renderWithApi,
  type ApiRoutes,
  type ItemVersion,
} from "../../testing/builders";
import { HistoryPanel } from ".";
import type { HistoryTarget } from "./queries";

const VERSIONS = "/api/v1/projects/demo/skills/skill/hub-workflow/feature/versions";
const TARGET: HistoryTarget = {
  kind: "item",
  project: "demo",
  item: { kind: "skill", source: "hub-workflow", name: "feature" },
};

const minutesAgo = (n: number) => new Date(Date.now() - n * 60_000).toISOString();
const hash = (head: string) => `sha256:${head}${"0".repeat(64 - head.length)}`;

/** Four versions, newest first: a restore of the first, a publish, a hand edit and the baseline. */
function fourVersions(): ItemVersion[] {
  return [
    anItemVersion({
      id: "0199f0a1-0000-7000-8000-000000000004",
      origin: "restore",
      restored_from: "0199f0a1-0000-7000-8000-000000000001",
      recorded_at: minutesAgo(5),
      content_hash: hash("44444444"),
    }),
    anItemVersion({
      id: "0199f0a1-0000-7000-8000-000000000003",
      origin: "publish",
      recorded_at: minutesAgo(30),
      content_hash: hash("33333333"),
    }),
    anItemVersion({
      id: "0199f0a1-0000-7000-8000-000000000002",
      origin: "external",
      author: null,
      recorded_at: minutesAgo(120),
      content_hash: hash("22222222"),
    }),
    anItemVersion({
      id: "0199f0a1-0000-7000-8000-000000000001",
      origin: "external",
      first: true,
      author: null,
      recorded_at: minutesAgo(60 * 48),
      content_hash: hash("11111111"),
    }),
  ];
}

function renderPanel(routes: ApiRoutes, target: HistoryTarget = TARGET) {
  return renderWithApi(<HistoryPanel target={target} />, { routes });
}

async function openPanel() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Show history" }));
  return user;
}

const rows = async () =>
  within(await screen.findByRole("table", { name: /Versions of/ }))
    .getAllByRole("row")
    .slice(1);

describe("HistoryPanel", () => {
  it("history_panel lists every version with origin author time and hash", async () => {
    const [first, second, ...older] = fourVersions();
    renderPanel({
      [VERSIONS]: (request: Request) =>
        new URL(request.url).searchParams.get("cursor") === "page-2"
          ? anItemVersionPage({ items: older, total_estimate: 4 })
          : anItemVersionPage({
              items: [first, second].filter((v): v is ItemVersion => v !== undefined),
              next_cursor: "page-2",
              total_estimate: 4,
            }),
    });

    const user = await openPanel();
    expect(await rows()).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Load more" }));

    await screen.findByText("First seen");
    const shown = await rows();
    expect(shown).toHaveLength(4);
    expect(shown[0]).toHaveTextContent("Restored from 11111111");
    expect(shown[0]).toHaveTextContent("Example Owner");
    expect(shown[0]).toHaveTextContent("5 min ago");
    expect(shown[0]).toHaveTextContent("44444444");
    expect(shown[1]).toHaveTextContent("Published");
    expect(shown[1]).toHaveTextContent("30 min ago");
    expect(shown[2]).toHaveTextContent("Changed outside the app");
    expect(shown[2]).toHaveTextContent("Outside the app");
    expect(shown[2]).toHaveTextContent("2 h ago");
    expect(shown[3]).toHaveTextContent("First seen");
    expect(shown[3]).toHaveTextContent("2 d ago");
    expect(shown[3]).toHaveTextContent("11111111");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("asks nothing until the panel is opened", async () => {
    const { requests } = renderPanel({ [VERSIONS]: anItemVersionPage() });

    expect(screen.getByRole("heading", { name: "History" })).toBeInTheDocument();
    expect(requests).toHaveLength(0);
    await openPanel();
    await rows();
    expect(requests).toHaveLength(1);
  });

  it("names the unit and the items that share it", async () => {
    renderPanel({
      [VERSIONS]: anItemVersionPage({
        unit_kind: "hook",
        unit_path: ".claude/settings.json",
        shared_by: 3,
        managed: true,
      }),
    });

    await openPanel();
    await rows();
    expect(screen.getByText(".claude/settings.json")).toBeInTheDocument();
    expect(screen.getByText("Shared by 3 hooks")).toBeInTheDocument();
    expect(screen.getByText("Managed by hub.lock")).toBeInTheDocument();
  });

  it("secret state shows Not versioned: secret with earlier versions still listed", async () => {
    renderPanel({ [VERSIONS]: anItemVersionPage({ state: "secret", items: fourVersions() }) });

    await openPanel();

    const notice = await screen.findByText("Not versioned: secret");
    // Text and an icon, never color alone.
    expect(notice.closest("[role=status]")?.querySelector("svg")).not.toBeNull();
    expect(await rows()).toHaveLength(4);
  });

  it("states show too large and cannot read in words", async () => {
    const { unmount } = renderPanel({ [VERSIONS]: anItemVersionPage({ state: "too_large" }) });
    await openPanel();
    expect(await screen.findByText("Not versioned: too large")).toBeInTheDocument();
    unmount();

    renderPanel({ [VERSIONS]: anItemVersionPage({ state: "unreadable" }) });
    await openPanel();
    expect(await screen.findByText("Not versioned: cannot read it")).toBeInTheDocument();
  });

  it("states show loading while the history is read", async () => {
    renderPanel({ [VERSIONS]: "pending" });
    await openPanel();
    expect(screen.getByRole("status", { name: "Loading the history" })).toBeInTheDocument();
  });

  it("states show an empty history with when the first version comes", async () => {
    renderPanel({ [VERSIONS]: anItemVersionPage({ items: [], total_estimate: 0 }) });
    await openPanel();
    expect(await screen.findByText("No versions yet")).toBeInTheDocument();
  });

  it("states show a problem with a retry when the history cannot be read", async () => {
    renderPanel({ [VERSIONS]: aProblem({ status: 500, title: "Internal server error" }) });
    await openPanel();
    expect(await screen.findByText("Could not load the history")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("states say an item without a unit has no history", async () => {
    renderPanel({ [VERSIONS]: aProblem({ status: 404, title: "Item history not found" }) });
    await openPanel();
    expect(await screen.findByText("No history for this item")).toBeInTheDocument();
  });
});
