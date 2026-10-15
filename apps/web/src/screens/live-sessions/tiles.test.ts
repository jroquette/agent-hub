import { describe, expect, it } from "vitest";

import { aLiveTile, anId } from "../../testing/builders";
import { splitTiles } from "./tiles";

describe("live tiles (waiting)", () => {
  it("puts a tile waiting on a hub web permission prompt with the waiting tiles", () => {
    const waiting = aLiveTile({
      id: anId(1, "5091b986"),
      group: "waiting",
      status: "waiting",
      waiting_reason: "Permission prompt",
    });
    const running = aLiveTile({ id: anId(2, "5091b986"), group: "live", status: "live" });

    expect(splitTiles([running, waiting]).waiting).toEqual([waiting]);
  });
});
