import { describe, expect, it } from "vitest";

import { aCapabilities } from "../../testing/builders";
import { sessionControlUnavailable } from "./control";

describe("sessionControlUnavailable (unavailable)", () => {
  it("gives the capabilities' reason, or a generic one, when claude is missing", () => {
    const missing = (reason: string | null) =>
      sessionControlUnavailable(null, aCapabilities({ available: false, reason }))?.detail;
    expect(missing("no claude on PATH")).toBe("no claude on PATH");
    expect(missing(null)).toBe("claude is not available on this machine.");
    expect(sessionControlUnavailable(null, aCapabilities())).toBeNull();
  });
});
