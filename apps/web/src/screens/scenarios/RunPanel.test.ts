import { describe, expect, it } from "vitest";

import { oneCommit } from "./RunPanel";

describe("oneCommit (scenario run panel)", () => {
  it("joins the draft actions' paths into one git add and one commit", () => {
    expect(
      oneCommit(
        [
          "git add -- actions/orders/a.yaml actions/orders/scripts/a.py actions/orders/scripts/personal.py && git commit -m 'Accept action orders/a'",
          "git add -- actions/orders/b.yaml actions/orders/scripts/personal.py && git commit -m 'Accept action orders/b'",
        ],
        ["orders/a", "orders/b"],
      ),
    ).toBe(
      "git add -- actions/orders/a.yaml actions/orders/scripts/a.py actions/orders/scripts/personal.py actions/orders/b.yaml && git commit -m 'Accept actions orders/a, orders/b'",
    );
  });

  it("keeps the commands as they are when one has another shape", () => {
    expect(oneCommit(["git add x && git commit", "echo y"], ["a", "b"])).toBe(
      "git add x && git commit && echo y",
    );
  });
});
