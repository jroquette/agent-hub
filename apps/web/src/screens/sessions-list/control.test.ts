import { describe, expect, it } from "vitest";

import { aCapabilities } from "../../testing/builders";
import { launchCookieUnavailable, sessionControlUnavailable } from "./control";

describe("sessionControlUnavailable (unavailable)", () => {
  it("gives the capabilities' reason, or a generic one, when claude is missing", () => {
    const missing = (reason: string | null) =>
      sessionControlUnavailable(null, aCapabilities({ available: false, reason }))?.detail;
    expect(missing("no claude on PATH")).toBe("no claude on PATH");
    expect(missing(null)).toBe("claude is not available on this machine.");
    expect(sessionControlUnavailable(null, aCapabilities())).toBeNull();
  });
});

describe("launchCookieUnavailable", () => {
  it("locks the launch-cookie writes when the cookie is missing", () => {
    expect(launchCookieUnavailable("missing")?.title).toBe("Changes are locked in this browser");
  });

  it("turns them off in the container", () => {
    expect(launchCookieUnavailable("off")?.title).toBe("Changes are off in the container");
  });

  it("leaves them open when the cookie is held or still unknown", () => {
    expect(launchCookieUnavailable("held")).toBeNull();
    expect(launchCookieUnavailable(undefined)).toBeNull();
  });
});
