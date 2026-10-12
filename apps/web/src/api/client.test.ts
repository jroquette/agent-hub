import { describe, expect, it } from "vitest";

import { client } from "./client";

describe("client", () => {
  it("exposes typed request methods", () => {
    expect(typeof client.GET).toBe("function");
    expect(typeof client.POST).toBe("function");
    expect(typeof client.DELETE).toBe("function");
  });
});
