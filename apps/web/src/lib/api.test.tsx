import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { aHub, aPage, aProblem, aSession, stubApi, testQueryClient } from "../testing/builders";
import {
  ApiProblem,
  apiDelete,
  apiGet,
  apiKey,
  apiPost,
  apiQuery,
  createQueryClient,
  shouldRetry,
  toProblem,
  useApi,
} from "./api";

describe("apiGet", () => {
  it("returns the typed body when the API answers 200", async () => {
    stubApi({ "/api/v1/hubs": aPage([aHub()]) });

    const page = await apiGet("/api/v1/hubs");

    expect(page.items[0]?.project).toBe("agent-hub");
  });

  it("fills path and query parameters when given them", async () => {
    const requests = stubApi({ "/api/v1/sessions/abc": aSession({ id: "abc" }) });

    await apiGet("/api/v1/sessions/{session_id}", { path: { session_id: "abc" } });
    await apiGet("/api/v1/sessions", { query: { project: "agent-hub", limit: 5 } }).catch(
      () => undefined,
    );

    expect(new URL(requests[0]?.url ?? "").pathname).toBe("/api/v1/sessions/abc");
    expect(new URL(requests[1]?.url ?? "").search).toBe("?project=agent-hub&limit=5");
  });

  it("rejects with the API's problem when it answers one", async () => {
    stubApi({
      "/api/v1/sessions/x": aProblem({
        status: 404,
        title: "Session not found",
        detail: "No session has the id x.",
        instance: "/api/v1/sessions/x",
      }),
    });

    const error: unknown = await apiGet("/api/v1/sessions/{session_id}", {
      path: { session_id: "x" },
    }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiProblem);
    expect(error).toMatchObject({
      status: 404,
      title: "Session not found",
      detail: "No session has the id x.",
      instance: "/api/v1/sessions/x",
    });
  });

  it("rejects with a status-based problem when the error body is not a problem", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("oops", { status: 502, statusText: "Bad Gateway" }),
    );

    await expect(apiGet("/api/v1/hubs")).rejects.toMatchObject({
      status: 502,
      title: "Bad Gateway",
    });
  });

  it("rejects with an unreachable problem when the network fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(apiGet("/api/v1/hubs")).rejects.toMatchObject({
      status: 0,
      title: "Could not reach agent-hub",
    });
  });

  it("passes an abort through when the query is cancelled", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new DOMException("aborted", "AbortError"));

    await expect(apiGet("/api/v1/hubs")).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("apiPost and apiDelete", () => {
  it("sends the JSON body and the path id when writing hubs", async () => {
    const requests = stubApi({
      "POST /api/v1/hubs": aHub(),
      "DELETE /api/v1/hubs/h1": {},
    });

    const hub = await apiPost("/api/v1/hubs", { path: "/home/dev/hub" });
    await apiDelete("/api/v1/hubs/{hub_id}", { path: { hub_id: "h1" } });

    expect(hub.project).toBe("agent-hub");
    expect(requests[0]?.method).toBe("POST");
    expect(await requests[0]?.clone().json()).toEqual({ path: "/home/dev/hub" });
    expect(requests[1]?.method).toBe("DELETE");
  });
});

describe("useApi", () => {
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={testQueryClient()}>{children}</QueryClientProvider>;
  }

  it("exposes data when the request succeeds", async () => {
    stubApi({ "/api/v1/hubs": aPage([aHub()]) });

    const { result } = renderHook(() => useApi("/api/v1/hubs"), { wrapper });

    await waitFor(() => {
      expect(result.current.data?.items).toHaveLength(1);
    });
  });

  it("exposes an ApiProblem when the request fails", async () => {
    stubApi({ "/api/v1/hubs": aProblem({ status: 503, title: "Collector database busy" }) });

    const { result } = renderHook(() => useApi("/api/v1/hubs"), { wrapper });

    await waitFor(() => {
      expect(result.current.error?.title).toBe("Collector database busy");
    });
  });
});

describe("query helpers", () => {
  it("keys queries by path then parameters", () => {
    expect(apiKey("/api/v1/sessions", { query: { project: "a" } })).toEqual([
      "api",
      "/api/v1/sessions",
      { query: { project: "a" } },
    ]);
    expect(apiQuery("/api/v1/hubs").queryKey).toEqual(["api", "/api/v1/hubs", {}]);
  });

  it("retries only network failures and busy answers, twice", () => {
    expect(shouldRetry(0, new ApiProblem({ status: 0, title: "x" }))).toBe(true);
    expect(shouldRetry(1, new ApiProblem({ status: 503, title: "x" }))).toBe(true);
    expect(shouldRetry(2, new ApiProblem({ status: 503, title: "x" }))).toBe(false);
    expect(shouldRetry(0, new ApiProblem({ status: 404, title: "x" }))).toBe(false);
    expect(shouldRetry(0, new ApiProblem({ status: 500, title: "x" }))).toBe(false);
  });

  it("wraps unknown errors as unreachable problems", () => {
    const known = new ApiProblem({ status: 404, title: "Not found" });
    expect(toProblem(known)).toBe(known);
    expect(toProblem(new Error("x")).status).toBe(0);
  });

  it("creates a client with the app defaults", () => {
    const queries = createQueryClient().getDefaultOptions().queries;
    expect(queries?.staleTime).toBe(10_000);
    expect(queries?.refetchOnWindowFocus).toBe(false);
  });
});
