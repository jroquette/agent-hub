import { describe, expect, it, vi } from "vitest";

import {
  launchCookieLock,
  launchCookieState,
  needsLaunchCookie,
  noteLaunchCookie,
  subscribeLaunchCookie,
} from "./launchCookie";

describe("needsLaunchCookie", () => {
  it("names the operations the API marks, by method and template", () => {
    expect(needsLaunchCookie("POST", "/api/v1/features/{project}/{slug}/owner-signoff")).toBe(true);
    expect(needsLaunchCookie("put", "/api/v1/projects/{project}/config/local")).toBe(true);
    expect(needsLaunchCookie("POST", "/api/v1/workflow-runs/{run_id}/cancel")).toBe(true);
  });

  it("leaves out the reads and the writes that need no cookie", () => {
    expect(needsLaunchCookie("GET", "/api/v1/features/{project}/{slug}")).toBe(false);
    expect(needsLaunchCookie("POST", "/api/v1/hubs")).toBe(false);
    expect(needsLaunchCookie("GET", "/api/v1/projects/{project}/config/local")).toBe(false);
  });
});

describe("launchCookieLock", () => {
  it("says how to unlock when the cookie is missing, and that the container is read-only", () => {
    expect(launchCookieLock("missing")?.detail).toMatch(/hub web printed/);
    expect(launchCookieLock("off")?.title).toBe("Changes are off in the container");
    expect(launchCookieLock("held")).toBeNull();
  });
});

describe("the launch cookie store", () => {
  it("tells its listeners each change and only a change", () => {
    const listener = vi.fn();
    const stop = subscribeLaunchCookie(listener);

    noteLaunchCookie("missing");
    noteLaunchCookie("missing");
    noteLaunchCookie("held");
    stop();
    noteLaunchCookie("off");

    expect(listener).toHaveBeenCalledTimes(2);
    expect(launchCookieState()).toBe("off");
  });
});
