import { act, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  aNeedsYouItem,
  anActivityItem,
  aPage,
  aProblem,
  aProjectSummary,
  renderWithApi,
  type ApiRoutes,
} from "../testing/builders";
import { apiKey, createQueryClient, useApi } from "./api";
import { ScreenReadProvider } from "./screenRead";

// Home's read for All projects and the three resources it stands in for, under the keys Home's
// queries read (activity: its first page of 20). The app's query client throughout: under the
// test client's staleTime 0 a seeded query would fetch anyway.
const PORTFOLIO = "/api/v1/screens/portfolio";
const ALL = { query: { project: null } };
const FIRST_PAGE = { query: { project: null, limit: 20 } };
const projectsKey = apiKey("/api/v1/projects", ALL);
const needsKey = apiKey("/api/v1/needs-you", ALL);
const activityKey = apiKey("/api/v1/activity", FIRST_PAGE);
const RESOURCES = ["/api/v1/activity", "/api/v1/needs-you", "/api/v1/projects"];

const read = {
  projects: aPage([aProjectSummary({ name: "read-project" })]),
  needs_you: aPage([aNeedsYouItem({ verb: "Read need" })]),
  activity: aPage([anActivityItem({ text: "Read activity" })]),
};
const resources: ApiRoutes = {
  "/api/v1/projects": aPage([aProjectSummary({ name: "route-project" })]),
  "/api/v1/needs-you": aPage([aNeedsYouItem({ verb: "Route need" })]),
  "/api/v1/activity": aPage([anActivityItem({ text: "Route activity" })]),
};

/** Home's three regions: each query's items, or "waiting" before it has any. */
function Regions() {
  const projects = useApi("/api/v1/projects", ALL).data?.items.map((item) => item.name);
  const needs = useApi("/api/v1/needs-you", ALL).data?.items.map((item) => item.verb);
  const activity = useApi("/api/v1/activity", FIRST_PAGE).data?.items.map((item) => item.text);
  return (
    <>
      <p>{`projects: ${projects?.join(", ") ?? "waiting"}`}</p>
      <p>{`needs: ${needs?.join(", ") ?? "waiting"}`}</p>
      <p>{`activity: ${activity?.join(", ") ?? "waiting"}`}</p>
    </>
  );
}

function Home({ enabled = true, children }: { enabled?: boolean; children: ReactNode }) {
  return (
    <ScreenReadProvider
      path={PORTFOLIO}
      params={ALL}
      seeds={(data) => [
        [projectsKey, data.projects],
        [needsKey, data.needs_you],
        [activityKey, data.activity],
      ]}
      enabled={enabled}
    >
      {children}
    </ScreenReadProvider>
  );
}

/** Lets a fetch that the last answer would start go out before the calls are read. */
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
}

describe("ScreenReadProvider", () => {
  it("seeds the covered queries so they send no request", async () => {
    const { calls } = renderWithApi(
      <Home>
        <Regions />
      </Home>,
      { routes: { [PORTFOLIO]: read, ...resources }, queryClient: createQueryClient() },
    );

    expect(await screen.findByText("projects: read-project")).toBeInTheDocument();
    expect(await screen.findByText("needs: Read need")).toBeInTheDocument();
    expect(await screen.findByText("activity: Read activity")).toBeInTheDocument();
    await settle();
    expect(calls()).toEqual([PORTFOLIO]);
  });

  it("lets each covered query read its resource when the screen read fails", async () => {
    const { calls } = renderWithApi(
      <Home>
        <Regions />
      </Home>,
      {
        routes: { [PORTFOLIO]: aProblem({ status: 500, title: "Internal error" }), ...resources },
        queryClient: createQueryClient(),
      },
    );

    expect(await screen.findByText("projects: route-project")).toBeInTheDocument();
    expect(await screen.findByText("needs: Route need")).toBeInTheDocument();
    expect(await screen.findByText("activity: Route activity")).toBeInTheDocument();
    // The covered queries waited for the read's answer before reading their routes.
    expect(calls()[0]).toBe(PORTFOLIO);
    expect([...calls().slice(1)].sort()).toEqual(RESOURCES);
  });

  it("lets each covered query read its resource when the screen read does not answer in 5 s", async () => {
    vi.useFakeTimers();
    try {
      const { calls, requests } = renderWithApi(
        <Home>
          <Regions />
        </Home>,
        { routes: { [PORTFOLIO]: "pending", ...resources }, queryClient: createQueryClient() },
      );

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4_900);
      });
      expect(calls()).toEqual([PORTFOLIO]);
      expect(screen.getByText("projects: waiting")).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(200);
      });
      expect(screen.getByText("projects: route-project")).toBeInTheDocument();
      expect(screen.getByText("needs: Route need")).toBeInTheDocument();
      expect(screen.getByText("activity: Route activity")).toBeInTheDocument();
      expect([...calls()].sort()).toEqual([...RESOURCES, PORTFOLIO]);
      // The read that did not answer is given up.
      const asked = requests.find((request) => new URL(request.url).pathname === PORTFOLIO);
      expect(asked?.signal.aborted).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
