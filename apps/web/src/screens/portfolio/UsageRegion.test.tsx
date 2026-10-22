import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aProblem,
  aUsageReport,
  aUsageRow,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { UsageRegion } from "./UsageRegion";

const USAGE = "/api/v1/skill-usage";

function region() {
  return screen.getByRole("region", { name: "Skills and agents" });
}

/** The table's body rows as their cell texts. */
function rows(): string[][] {
  const table = within(region()).getByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );
}

describe("UsageRegion", () => {
  it("lists never-used skills first: /refactor 0 above /feature 2", async () => {
    renderWithApi(<UsageRegion project="demo" single />, { routes: { [USAGE]: aUsageReport() } });

    await within(await screen.findByRole("table")).findByText("/refactor");
    const names = rows().map((cells) => [cells[0], cells[2]]);
    expect(names).toEqual([
      ["/refactor", "0"],
      ["/feature", "2"],
    ]);
    expect(screen.getByText("Runs in the last 30 days · never used first")).toBeInTheDocument();
  });

  it("shows the quality-reviewer agent with its runs and last-used date", async () => {
    const used = at(-7200);
    renderWithApi(<UsageRegion project="demo" single />, {
      routes: {
        [USAGE]: aUsageReport({
          items: [
            aUsageRow({
              kind: "agent",
              name: "quality-reviewer",
              runs_7d: 2,
              runs_30d: 2,
              runs_90d: 2,
              last_used_at: used,
            }),
          ],
        }),
      },
    });

    const name = await screen.findByText("quality-reviewer");
    const row = name.closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement).getAllByRole("cell");
    expect(cells.map((cell) => cell.textContent).slice(0, 3)).toEqual([
      "quality-reviewer",
      "Agent",
      "2",
    ]);
    expect(row?.querySelector("time")).toHaveAttribute("datetime", used);
  });

  it("shows a hub skill with no event as 0", async () => {
    renderWithApi(<UsageRegion project="demo" single />, {
      routes: { [USAGE]: aUsageReport({ items: [aUsageRow()] }) },
    });

    await screen.findByText("/refactor");
    expect(rows()).toEqual([["/refactor", "Skill", "0", "Not in 90 d"]]);
  });

  it("refetches with days=7 when the 7 d window is chosen", async () => {
    const user = userEvent.setup();
    const { requests } = renderWithApi(<UsageRegion project="demo" single />, {
      routes: {
        [USAGE]: (request: Request) =>
          aUsageReport({ days: Number(new URL(request.url).searchParams.get("days")) as 30 }),
      },
    });
    await screen.findByText("/refactor");
    expect(new URL(requests[0]?.url ?? "").searchParams.get("days")).toBe("30");

    await user.click(within(screen.getByRole("group", { name: "Usage window" })).getByText("7 d"));

    await waitFor(() => {
      expect(requests.map((r) => new URL(r.url).searchParams.get("days"))).toContain("7");
    });
    expect(await screen.findByText("Runs in the last 7 days · never used first")).toBeVisible();
    expect(new URL(requests.at(-1)?.url ?? "").searchParams.get("project")).toBe("demo");
  });

  it("shows 10 rows, then all after Show all", async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 12 }, (_, i) =>
      aUsageRow({ name: `skill-${String(i).padStart(2, "0")}` }),
    );
    renderWithApi(<UsageRegion project="demo" single />, {
      routes: { [USAGE]: aUsageReport({ items }) },
    });

    await screen.findByText("/skill-00");
    expect(rows()).toHaveLength(10);

    await user.click(screen.getByRole("button", { name: "Show all 12" }));

    expect(rows()).toHaveLength(12);
    expect(screen.queryByRole("button", { name: /Show all/ })).not.toBeInTheDocument();
  });

  it("hides the Project column when one project is in scope", async () => {
    const report = aUsageReport({
      items: [aUsageRow(), aUsageRow({ project: "loki", name: "ship" })],
    });
    const { unmount } = renderWithApi(<UsageRegion project={null} single={false} />, {
      routes: { [USAGE]: report },
    });

    await screen.findByText("/ship");
    expect(within(region()).getByRole("columnheader", { name: "Project" })).toBeInTheDocument();
    expect(rows()[1]?.[0]).toBe("loki");
    unmount();

    renderWithApi(<UsageRegion project="demo" single />, { routes: { [USAGE]: report } });

    await screen.findByText("/ship");
    expect(within(region()).queryByRole("columnheader", { name: "Project" })).toBeNull();
  });

  describe("states", () => {
    it("shows a skeleton after 300 ms while the report is pending", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderWithApi(<UsageRegion project={null} single={false} />, {
          routes: { [USAGE]: "pending" },
        });
        expect(document.querySelectorAll(".ah-skel")).toHaveLength(0);

        await act(async () => {
          await vi.advanceTimersByTimeAsync(350);
        });

        expect(document.querySelectorAll(".ah-skel").length).toBeGreaterThan(0);
        expect(region()).toHaveAttribute("aria-busy", "true");
      } finally {
        vi.useRealTimers();
      }
    });

    it("shows the empty copy when the hub has no skills or agents", async () => {
      renderWithApi(<UsageRegion project={null} single={false} />, {
        routes: { [USAGE]: aUsageReport({ items: [] }) },
      });

      expect(
        await screen.findByText("No skills or agents in this hub's .claude folder."),
      ).toBeInTheDocument();
    });

    it("keeps the problem in its region with Try again", async () => {
      const user = userEvent.setup();
      const { requests } = renderWithApi(<UsageRegion project={null} single={false} />, {
        routes: { [USAGE]: aProblem({ status: 503, title: "Busy", detail: "Database busy." }) },
      });

      const alert = await within(region()).findByRole("alert");
      expect(within(alert).getByText("Could not load skill and agent usage")).toBeInTheDocument();
      const before = requests.length;
      await user.click(within(alert).getByRole("button", { name: "Try again" }));
      await waitFor(() => {
        expect(requests.length).toBe(before + 1);
      });
    });

    it("says the list may be incomplete when the report is truncated", async () => {
      renderWithApi(<UsageRegion project={null} single={false} />, {
        routes: { [USAGE]: aUsageReport({ truncated: true }) },
      });

      expect(
        await screen.findByText("Some items were not read; the list may be incomplete."),
      ).toBeInTheDocument();
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const routes: ApiRoutes = { [USAGE]: aUsageReport() };
    const { container } = renderWithApi(<UsageRegion project={null} single={false} />, {
      routes,
    });

    await screen.findByText("/feature");
    expect(await seriousViolations(container)).toEqual([]);
  });
});
