import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { aPage, stubApi, stubEventSource } from "./testing/builders";

// The router starts loading the first page's code as it is made, so this file notes how often the
// hub list had been asked for by then. A file of its own: every test here gets the wrapped router.
const madeRouter = vi.hoisted(() => ({
  hubListAsked: (): number => 0,
  hubListAskedBefore: [] as number[],
}));
vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>();
  return {
    ...actual,
    createBrowserRouter: (...args: Parameters<typeof actual.createBrowserRouter>) => {
      madeRouter.hubListAskedBefore.push(madeRouter.hubListAsked());
      return actual.createBrowserRouter(...args);
    },
  };
});

describe("App", () => {
  it("asks for the hub list before the router starts loading the first page's code", async () => {
    // On a real server the hub list then comes in before the page's code, so with no hub
    // registered the gate draws only its redirect to Welcome, never the page.
    window.history.replaceState(null, "", "/");
    const requests = stubApi({ "/api/v1/hubs": aPage([]), "/api/v1/projects": aPage([]) });
    stubEventSource();
    madeRouter.hubListAsked = () =>
      requests.filter((request) => new URL(request.url).pathname === "/api/v1/hubs").length;

    render(<App />);

    expect(madeRouter.hubListAskedBefore).toEqual([1]);
    expect(
      await screen.findByRole(
        "heading",
        { level: 1, name: "Set up agent-hub on this machine" },
        { timeout: 3_000 },
      ),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/welcome");
  });
});
