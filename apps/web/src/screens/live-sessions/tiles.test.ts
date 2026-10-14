import { describe, expect, it } from "vitest";

import { aLiveTile, anId } from "../../testing/builders";
import { splitTiles, waitingLink } from "./tiles";

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

  it("links a permission prompt to its session, where the chat answers it", () => {
    const tile = aLiveTile({
      id: anId(1, "5091b986"),
      group: "waiting",
      status: "waiting",
      waiting_reason: "Permission prompt",
    });

    expect(waitingLink(tile)).toEqual({
      href: `/sessions/${anId(1, "5091b986")}`,
      label: "Open session",
    });
  });

  it("links any other wait to the approvals", () => {
    const tile = aLiveTile({
      group: "waiting",
      status: "waiting",
      waiting_reason: "Plan approval",
    });

    expect(waitingLink(tile)).toEqual({ href: "/approvals", label: "Open approval" });
  });
});
