import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import {
  TestProviders,
  aFeature,
  aFeatureTickets,
  aGoldenPath,
  aGoldenStep,
  aLiveTile,
  aPage,
  aSessionLabel,
  stubApi,
  testQueryClient,
} from "../../testing/builders";
import { useFeatures, useFeaturesNeedingYou, useWarmTickets } from "./queries";

function wrapper({ children }: { children: ReactNode }) {
  return <TestProviders client={testQueryClient()}>{children}</TestProviders>;
}

describe("useFeaturesNeedingYou", () => {
  it("counts the features the list flags: a session waiting on you, a broken record and NO-SHIP", async () => {
    stubApi({
      "/api/v1/features": aPage([
        aFeature({ slug: "plain", issues: ["AGH-1"] }),
        aFeature({ slug: "asked", issues: ["AGH-2"] }),
        aFeature({ slug: "broken", problem: "features.json could not be parsed" }),
        aFeature({ slug: "refused", verdict: "NO-SHIP" }),
      ]),
      "/api/v1/live-sessions": aPage([
        aLiveTile({ group: "waiting", label: aSessionLabel({ issue: "AGH-2" }) }),
        aLiveTile({ group: "live", label: aSessionLabel({ issue: "AGH-1" }) }),
      ]),
    });

    const { result } = renderHook(() => useFeaturesNeedingYou(null), { wrapper });

    await waitFor(() => {
      expect(result.current).toBe(3);
    });
  });

  it("has no count until the features are read, and counts them without the sessions", async () => {
    stubApi({
      "/api/v1/features": aPage([aFeature({ slug: "refused", verdict: "NO-SHIP" })]),
    });

    const { result } = renderHook(() => useFeaturesNeedingYou(null), { wrapper });

    expect(result.current).toBeUndefined();
    await waitFor(() => {
      expect(result.current).toBe(1);
    });
  });
});

describe("useWarmTickets", () => {
  const missingLinear = aGoldenPath({
    phase: "build",
    steps: [aGoldenStep({ state: "unknown", reason: "Ticket states from Linear not loaded" })],
  });
  const shipped = aGoldenPath({
    phase: "shipped",
    steps: [aGoldenStep({ name: "shipped", state: "done", reason: null })],
  });

  it("reads the tickets of a feature missing Linear's status, then rereads the list", async () => {
    let listReads = 0;
    const requests = stubApi({
      "/api/v1/features": () => {
        listReads += 1;
        const path = listReads === 1 ? missingLinear : shipped;
        return aPage([
          aFeature({ slug: "done-one", issues: ["AGH-1"], golden_path: path, phase: path.phase }),
          aFeature({ slug: "no-tickets", issues: [], golden_path: missingLinear }),
        ]);
      },
      "/api/v1/features/agent-hub/done-one/tickets": aFeatureTickets({ slug: "done-one" }),
    });

    const { result } = renderHook(
      () => {
        const features = useFeatures(null);
        useWarmTickets(features.data?.items);
        return features.data?.items[0]?.phase;
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current).toBe("shipped");
    });
    const paths = requests.map((r) => new URL(r.url).pathname);
    expect(paths.filter((p) => p.endsWith("/tickets"))).toEqual([
      "/api/v1/features/agent-hub/done-one/tickets",
    ]);
  });

  it("reads no tickets when every feature already has Linear's status", async () => {
    const requests = stubApi({
      "/api/v1/features": aPage([
        aFeature({ slug: "warm", issues: ["AGH-1"], golden_path: shipped }),
      ]),
    });

    const { result } = renderHook(
      () => {
        const features = useFeatures(null);
        useWarmTickets(features.data?.items);
        return features.isSuccess;
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current).toBe(true);
    });
    expect(requests.some((r) => r.url.includes("/tickets"))).toBe(false);
  });
});
