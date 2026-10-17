import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  aPage,
  aProblem,
  aProjectSummary,
  aSession,
  aSessionLabel,
  aSessionsByStatus,
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { SessionsListScreen } from "./index";

// These tests read the list (the default view): one table, a row group per section.
beforeEach(() => {
  window.localStorage.setItem("ah.sessions.view", "list");
});

const SESSIONS = "/api/v1/sessions";
const COLLAPSED = "ah.sessions.collapsed";

const named = (name: string) =>
  aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`] });
const one = (n: number, status: "waiting" | "live" | "idle" | "ended", name: string) =>
  aSession({ id: anId(n, `bbbb${String(n).padStart(4, "0")}`), status, label: named(name) });
const many = (count: number, status: "live" | "ended", from: number) =>
  Array.from({ length: count }, (_, i) => one(from + i, status, `${status}-${String(i)}`));

const SAMPLE = [one(1, "waiting", "asker"), one(2, "live", "runner"), one(3, "ended", "done")];

function routes(sessions: ApiRoutes[string] = aSessionsByStatus(SAMPLE)): ApiRoutes {
  return {
    [SESSIONS]: sessions,
    "/api/v1/projects": aPage([aProjectSummary()]),
    "/api/v1/agent-sessions": { items: [] },
  };
}

const sessionRequests = (requests: Request[]) =>
  requests.filter((r) => new URL(r.url).pathname === SESSIONS).map((r) => new URL(r.url));
/** The row-group header buttons of the list, in page order (the status tabs are not among them). */
const toggles = () =>
  screen.queryByRole("table")
    ? within(screen.getByRole("table"))
        .queryAllByRole("button")
        .filter((button) => button.hasAttribute("aria-expanded"))
    : [];
const headers = () => toggles().map((button) => button.textContent);
const collapsedHeaders = () =>
  toggles()
    .filter((button) => button.getAttribute("aria-expanded") === "false")
    .map((button) => button.textContent);
/** A section's row group, by its header. */
const group = (name: RegExp) => screen.getByRole("rowgroup", { name });
/** A section's header button, inside the table (a status tab can read the same). */
const toggle = (name: string) => within(screen.getByRole("table")).getByRole("button", { name });

afterEach(() => {
  window.localStorage.clear();
});

describe("SessionsListScreen status-sections", () => {
  it("shows the sections in order with their counts, one query each, and hides an empty one", async () => {
    const live = { ...aPage([one(2, "live", "runner")], { next_cursor: "c2" }), total_estimate: 4 };
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        new URL(request.url).searchParams.get("status") === "live"
          ? live
          : aSessionsByStatus(SAMPLE)(request),
      ),
      path: "/sessions",
    });

    await screen.findByText("/runner");
    // One table, one header row, the sections as its row groups.
    expect(screen.getAllByRole("table")).toHaveLength(1);
    expect(screen.getAllByRole("columnheader", { name: "Status" })).toHaveLength(1);
    expect(headers()).toEqual(["Waiting for you · 1", "Live · ~4", "Ended · last 7 days · 1"]);
    expect(screen.queryByRole("rowgroup", { name: /^Idle/ })).toBeNull();
    expect(within(group(/^Live/)).getByText("/runner")).toBeInTheDocument();
    expect(
      sessionRequests(requests)
        .map((url) => url.searchParams.get("status"))
        .sort(),
    ).toEqual(["ended", "idle", "live", "waiting"]);
  });

  it("collapses a section from its header and remembers it", async () => {
    const first = renderWithApi(<SessionsListScreen />, { routes: routes(), path: "/sessions" });
    await screen.findByText("/runner");

    const live = toggle("Live · 1");
    fireEvent.click(live);
    expect(live).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("/runner")).toBeNull();
    expect(screen.getByText("/asker")).toBeInTheDocument();
    expect(window.localStorage.getItem(COLLAPSED)).toBe('["live"]');
    first.unmount();

    renderWithApi(<SessionsListScreen />, { routes: routes(), path: "/sessions" });
    await screen.findByText("/asker");
    expect(toggle("Live · 1")).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle("Live · 1"));
    expect(screen.getByText("/runner")).toBeInTheDocument();
    expect(window.localStorage.getItem(COLLAPSED)).toBe("[]");
  });

  it("shows one empty state and no section when every section is empty", async () => {
    const { router } = renderWithApi(<SessionsListScreen />, {
      routes: routes(aPage([])),
      path: "/sessions",
    });

    expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
    expect(headers()).toEqual([]);
    expect(screen.queryByRole("table")).toBeNull();
    // The first run replaces the tabs and the toolbar.
    expect(screen.queryByRole("group", { name: "Status" })).toBeNull();
    expect(screen.queryByRole("searchbox", { name: "Find sessions" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show all time" }));
    expect(router.state.location.search).toBe("?period=All");
  });
});

describe("SessionsListScreen collapsed-bad-json", () => {
  it.each([
    ["{not json", []],
    ['{"live":true}', []],
    ['"live"', []],
    ['["live","bogus","live",3]', ["Live · 1"]],
  ])("reads %s as the collapsed set %j", async (stored, collapsed) => {
    window.localStorage.setItem(COLLAPSED, stored);
    renderWithApi(<SessionsListScreen />, { routes: routes(), path: "/sessions" });
    await screen.findByText("/asker");

    expect(headers()).toEqual(["Waiting for you · 1", "Live · 1", "Ended · last 7 days · 1"]);
    expect(collapsedHeaders()).toEqual(collapsed);
  });

  it("keeps only the known sections when it writes the set back", async () => {
    window.localStorage.setItem(COLLAPSED, '["live","bogus","live",3]');
    renderWithApi(<SessionsListScreen />, { routes: routes(), path: "/sessions" });
    await screen.findByText("/asker");

    fireEvent.click(toggle("Waiting for you · 1"));
    expect(window.localStorage.getItem(COLLAPSED)).toBe('["live","waiting"]');
  });
});

describe("SessionsListScreen section-error", () => {
  it("shows the error and Retry in the failing section while the others keep rendering", async () => {
    let failing = true;
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        failing && new URL(request.url).searchParams.get("status") === "ended"
          ? aProblem({ status: 500, title: "Boom", detail: "The read model failed." })
          : aSessionsByStatus(SAMPLE)(request),
      ),
      path: "/sessions",
    });

    const ended = await screen.findByRole("rowgroup", { name: /^Ended/ });
    expect(await within(ended).findByText("Could not load ended sessions")).toBeVisible();
    // No query returned a count: the header shows the ellipsis, not 0.
    expect(headers()).toEqual(["Waiting for you · 1", "Live · 1", "Ended · last 7 days · …"]);
    expect(screen.getByText("/asker")).toBeInTheDocument();
    expect(screen.getByText("/runner")).toBeInTheDocument();

    failing = false;
    fireEvent.click(within(ended).getByRole("button", { name: "Try again" }));
    expect(await within(ended).findByText("/done")).toBeInTheDocument();
    expect(headers()).toEqual(["Waiting for you · 1", "Live · 1", "Ended · last 7 days · 1"]);
    await waitFor(() => {
      expect(sessionRequests(requests).map((url) => url.searchParams.get("status"))).toHaveLength(
        5,
      );
    });
    expect(
      sessionRequests(requests).filter((url) => url.searchParams.get("status") === "ended"),
    ).toHaveLength(2);
  });
});

describe("SessionsListScreen filters-both-views", () => {
  it("shows only the tab's section but asks every one, with the period on Ended only", async () => {
    const faceted = renderWithApi(<SessionsListScreen />, {
      routes: routes(),
      path: "/sessions?status=waiting",
    });
    await screen.findByText("/asker");
    // A tab's group cannot collapse: its header is a title, not a button.
    expect(headers()).toEqual([]);
    expect(screen.getAllByRole("rowgroup", { name: /·/ }).map((g) => g.dataset.group)).toEqual([
      "waiting",
    ]);
    expect(screen.getByRole("rowgroup", { name: "Waiting for you · 1" })).toBeInTheDocument();
    expect(screen.queryByText("/runner")).toBeNull();
    expect(
      sessionRequests(faceted.requests)
        .map((url) => url.searchParams.get("status"))
        .sort(),
    ).toEqual(["ended", "idle", "live", "waiting"]);
    faceted.unmount();

    const all = renderWithApi(<SessionsListScreen />, {
      routes: routes(),
      path: "/sessions?period=24 h&repo=storefront",
    });
    await screen.findByText("/asker");
    const asked = sessionRequests(all.requests);
    expect(asked.every((url) => url.searchParams.get("repo") === "storefront")).toBe(true);
    expect(
      asked
        .filter((url) => url.searchParams.has("from"))
        .map((url) => url.searchParams.get("status")),
    ).toEqual(["ended"]);
  });
});

/** Waits until `count` session requests were sent, then a beat more, so a duplicate would show. */
async function settled(requests: Request[], count: number) {
  await waitFor(() => {
    expect(sessionRequests(requests).length).toBeGreaterThanOrEqual(count);
  });
  await new Promise((resolve) => setTimeout(resolve, 50));
  return sessionRequests(requests);
}

describe("SessionsListScreen filter-requests", () => {
  it("asks only Ended again on a period change, and every section once on a repo filter", async () => {
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes(),
      path: "/sessions",
    });
    await screen.findByText("/asker");
    const first = await settled(requests, 4);
    expect(first).toHaveLength(4);

    fireEvent.click(screen.getByRole("button", { name: "Period: Last 7 days" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Last 24 hours" }));
    const afterPeriod = (await settled(requests, 5)).slice(4);
    expect(afterPeriod.map((url) => url.searchParams.get("status"))).toEqual(["ended"]);
    expect(afterPeriod[0]?.searchParams.has("from")).toBe(true);
    // The period filters Ended only, and its header says so.
    expect(await screen.findByRole("button", { name: "Ended · last 24 hours · 1" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Repo: All" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "agent-hub" }));
    const afterRepo = (await settled(requests, 9)).slice(5);
    expect(afterRepo.map((url) => url.searchParams.get("status")).sort()).toEqual([
      "ended",
      "idle",
      "live",
      "waiting",
    ]);
    expect(afterRepo.every((url) => url.searchParams.get("repo") === "agent-hub")).toBe(true);
  });
});

describe("SessionsListScreen keep-previous", () => {
  it("keeps the shown sections while a sort refetches; a hidden empty one stays hidden", async () => {
    // The sorted pages never arrive, so the screen stays mid-refetch.
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        new URL(request.url).searchParams.get("sort") === "-cost"
          ? "pending"
          : aSessionsByStatus(SAMPLE)(request),
      ),
      path: "/sessions",
    });
    await screen.findByText("/asker");
    expect(headers()).toEqual(["Waiting for you · 1", "Live · 1", "Ended · last 7 days · 1"]);

    fireEvent.click(screen.getByRole("button", { name: /^Cost/ }));
    await waitFor(() => {
      expect(
        sessionRequests(requests).filter((url) => url.searchParams.get("sort") === "-cost"),
      ).toHaveLength(4);
    });
    // Mid-refetch: the same sections and rows, no Idle placeholder, no skeleton.
    expect(headers()).toEqual(["Waiting for you · 1", "Live · 1", "Ended · last 7 days · 1"]);
    expect(screen.getByText("/runner")).toBeInTheDocument();
  });

  it("marks a section busy and hides Load more while it shows the previous pages", async () => {
    renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        new URL(request.url).searchParams.get("sort") === "-cost"
          ? "pending"
          : aSessionsByStatus(SAMPLE, { next_cursor: "c2" })(request),
      ),
      path: "/sessions",
    });
    await screen.findByText("/runner");
    const live = group(/^Live/);
    expect(live).not.toHaveAttribute("aria-busy");
    expect(within(live).getByRole("button", { name: "Load more" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Cost/ }));
    await waitFor(() => {
      expect(live).toHaveAttribute("aria-busy", "true");
    });
    expect(within(live).getByText("Updating…")).toBeInTheDocument();
    // A Load more on placeholder pages would refetch page 1 instead of the next one.
    expect(within(live).queryByRole("button", { name: "Load more" })).toBeNull();
  });
});

describe("SessionsListScreen list-groups", () => {
  it("sorts every section from the one header and marks the sorted column", async () => {
    const { router, requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes(),
      path: "/sessions",
    });
    await screen.findByText("/asker");

    const started = screen.getByRole("columnheader", { name: /^Started/ });
    expect(started).toHaveAttribute("aria-sort", "descending");
    fireEvent.click(screen.getByRole("button", { name: /^Cost/ }));
    expect(router.state.location.search).toBe("?sort=-cost");
    expect(screen.getByRole("columnheader", { name: /^Cost/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(started).not.toHaveAttribute("aria-sort");
    await waitFor(() => {
      expect(
        sessionRequests(requests)
          .filter((url) => url.searchParams.get("sort") === "-cost")
          .map((url) => url.searchParams.get("status"))
          .sort(),
      ).toEqual(["ended", "idle", "live", "waiting"]);
    });
    // A second click flips it; back to the default sort, the URL drops it.
    fireEvent.click(screen.getByRole("button", { name: /^Cost/ }));
    expect(router.state.location.search).toBe("?sort=cost");
    fireEvent.click(screen.getByRole("button", { name: /^Started/ }));
    expect(router.state.location.search).toBe("");
  });

  it("pages one section with Load more in its group, the others untouched", async () => {
    const rows = [...many(3, "live", 1000), ...many(50, "ended", 2000)];
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) => {
        const url = new URL(request.url);
        if (url.searchParams.get("cursor") === "e2") return aPage([one(9, "ended", "older")]);
        const status = url.searchParams.get("status");
        const page = aSessionsByStatus(rows, {
          next_cursor: status === "ended" ? "e2" : null,
        })(request);
        return status === "ended" ? { ...page, total_estimate: 51 } : page;
      }),
      path: "/sessions",
    });
    await screen.findByText("/live-0");

    const ended = group(/^Ended/);
    expect(within(group(/^Live/)).queryByRole("button", { name: "Load more" })).toBeNull();
    expect(within(ended).getByText("Showing 50 of ~51 ended sessions")).toBeInTheDocument();
    fireEvent.click(within(ended).getByRole("button", { name: "Load more" }));
    await waitFor(() => {
      expect(
        sessionRequests(requests)
          .filter((url) => url.searchParams.get("cursor") === "e2")
          .map((url) => url.searchParams.get("status")),
      ).toEqual(["ended"]);
    });
    expect(await within(ended).findByText("/older")).toBeInTheDocument();
    expect(within(ended).queryByRole("button", { name: "Load more" })).toBeNull();
    expect(within(group(/^Live/)).getAllByRole("row")).toHaveLength(4);
  });
});
