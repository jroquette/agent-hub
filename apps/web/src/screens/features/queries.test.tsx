import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import {
  TestProviders,
  aFeature,
  aLiveTile,
  aPage,
  aSessionLabel,
  stubApi,
  testQueryClient,
} from "../../testing/builders";
import { useFeaturesNeedingYou } from "./queries";

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
