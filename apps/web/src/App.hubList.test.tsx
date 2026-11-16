import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { aPage, aShellView, stubApi, stubEventSource } from "./testing/builders";

// The router starts loading the first page's code as it is made, so this file notes how often the
// shell read had been asked for by then. A file of its own: every test here gets the wrapped
// router.
const madeRouter = vi.hoisted(() => ({
  shellReadAsked: (): number => 0,
  shellReadAskedBefore: [] as number[],
}));
vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>();
  return {
    ...actual,
    createBrowserRouter: (...args: Parameters<typeof actual.createBrowserRouter>) => {
      madeRouter.shellReadAskedBefore.push(madeRouter.shellReadAsked());
      return actual.createBrowserRouter(...args);
    },
  };
});

// The code of the first page and of Welcome, loaded once before the test. On the way to Welcome
// the router waits for both, and a first import also transforms the module: under coverage on a
// busy runner that alone took longer than the wait below, which is for the app's own steps (the
// shell read, the gate's redirect), not for the test runner's.
beforeAll(async () => {
  await Promise.all([import("./screens/portfolio"), import("./screens/welcome")]);
}, 60_000);

describe("App", () => {
  it("asks for the shell read before the router starts loading the first page's code", async () => {
    // On a real server the shell read then comes in before the page's code, so with no hub
    // registered the gate draws only its redirect to Welcome, never the page.
    window.history.replaceState(null, "", "/");
    const requests = stubApi({
      "/api/v1/screens/shell": aShellView({ hub_count: 0 }),
      "/api/v1/hubs": aPage([]),
      "/api/v1/projects": aPage([]),
    });
    stubEventSource();
    madeRouter.shellReadAsked = () =>
      requests.filter((request) => new URL(request.url).pathname === "/api/v1/screens/shell")
        .length;

    render(<App />);

    expect(madeRouter.shellReadAskedBefore).toEqual([1]);
    expect(
      await screen.findByRole(
        "heading",
        { level: 1, name: "Set up agent-hub on this machine" },
        { timeout: 3_000 },
      ),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/welcome");
    // The shell and the gate read the early answer: a key of their own would ask again.
    expect(madeRouter.shellReadAsked()).toBe(1);
  });
});
