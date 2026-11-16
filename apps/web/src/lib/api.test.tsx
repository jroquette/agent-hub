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
  apiCommand,
  apiPost,
  apiQuery,
  createQueryClient,
  shouldRetry,
  toProblem,
  useApi,
} from "./api";
import {
  LAUNCH_COOKIE_UNAUTHORIZED_TYPE,
  launchCookieState,
  noteLaunchCookie,
} from "./launchCookie";

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

  it("keeps the problem's code and reason members when it names them", async () => {
    stubApi({
      "/api/v1/sessions/x": aProblem({
        status: 409,
        title: "Item write refused",
        code: "secret_unversioned",
        reason: "The item on disk holds a secret match and has no version",
      }),
      "/api/v1/sessions/y": aProblem({ status: 409, title: "Conflict", code: 7 }),
    });

    const named = (id: string) =>
      apiGet("/api/v1/sessions/{session_id}", { path: { session_id: id } }).catch(
        (e: unknown) => e,
      );

    expect(await named("x")).toMatchObject({
      code: "secret_unversioned",
      reason: "The item on disk holds a secret match and has no version",
    });
    expect(await named("y")).toMatchObject({ code: null, reason: null });
  });

  it("keeps a failed publish's published member only when it is true", async () => {
    stubApi({
      "/api/v1/sessions/x": aProblem({ status: 500, title: "Draft not removed", published: true }),
      "/api/v1/sessions/y": aProblem({ status: 500, title: "Item write failed", published: "yes" }),
      "/api/v1/sessions/z": aProblem({ status: 500, title: "Item write failed" }),
    });

    const named = (id: string) =>
      apiGet("/api/v1/sessions/{session_id}", { path: { session_id: id } }).catch(
        (e: unknown) => e,
      );

    expect(await named("x")).toMatchObject({ published: true });
    expect(await named("y")).toMatchObject({ published: false });
    expect(await named("z")).toMatchObject({ published: false });
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

describe("apiCommand", () => {
  it("sends an empty JSON object when a command route takes no body", async () => {
    const requests = stubApi({
      "POST /api/v1/workflow-runs/r1/cancel": { run_id: "r1", project: "demo", action: "cancel" },
    });

    const accepted = await apiCommand("/api/v1/workflow-runs/{run_id}/cancel", {
      path: { run_id: "r1" },
    });

    expect(accepted.action).toBe("cancel");
    expect(requests[0]?.method).toBe("POST");
    expect(requests[0]?.headers.get("content-type")).toContain("application/json");
    expect(await requests[0]?.clone().text()).toBe("{}");
  });
});

describe("the launch cookie guard", () => {
  const CANCEL = "/api/v1/workflow-runs/{run_id}/cancel";
  const params = { path: { run_id: "r1" } };

  it("refuses a write that needs the cookie, without a request, when the page lacks it", async () => {
    const requests = stubApi({});
    noteLaunchCookie("missing");

    const refused = await apiCommand(CANCEL, params).catch((error: unknown) => error);

    expect(refused).toBeInstanceOf(ApiProblem);
    expect((refused as ApiProblem).status).toBe(401);
    expect((refused as ApiProblem).detail).toMatch(/hub web printed/);
    expect(requests).toHaveLength(0);
  });

  it("says the container is read-only when changes are off", async () => {
    stubApi({});
    noteLaunchCookie("off");

    const refused = await apiCommand(CANCEL, params).catch((error: unknown) => error);

    expect((refused as ApiProblem).title).toBe("Changes are off in the container");
  });

  it("sends the writes that need no cookie, and every write while the cookie is held", async () => {
    const requests = stubApi({
      "POST /api/v1/hubs": aHub(),
      "POST /api/v1/workflow-runs/r1/cancel": { run_id: "r1", project: "demo", action: "cancel" },
    });
    noteLaunchCookie("missing");
    await apiPost("/api/v1/hubs", { path: "/home/dev/hub" });
    noteLaunchCookie("held");
    await apiCommand(CANCEL, params);

    expect(requests.map((r) => new URL(r.url).pathname)).toEqual([
      "/api/v1/hubs",
      "/api/v1/workflow-runs/r1/cancel",
    ]);
  });

  it("learns the cookie is missing from the server's refusal of a write that needs it", async () => {
    stubApi({
      "POST /api/v1/workflow-runs/r1/cancel": aProblem({
        status: 401,
        title: "Session cookie required",
        type: LAUNCH_COOKIE_UNAUTHORIZED_TYPE,
      }),
    });

    await apiCommand(CANCEL, params).catch(() => undefined);

    expect(launchCookieState()).toBe("missing");
  });

  it("learns nothing from another 401", async () => {
    stubApi({
      "POST /api/v1/workflow-runs/r1/cancel": aProblem({ status: 401, title: "Unauthorized" }),
    });

    await apiCommand(CANCEL, params).catch(() => undefined);

    expect(launchCookieState()).toBeUndefined();
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
