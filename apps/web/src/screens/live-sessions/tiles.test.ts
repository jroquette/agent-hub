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

  it("links a permission prompt of a session hub web drives to its chat", () => {
    const tile = aLiveTile({
      id: anId(1, "5091b986"),
      group: "waiting",
      status: "waiting",
      waiting_reason: "Permission prompt",
      agent_session_id: anId(7, "0192aaaa"),
    });

    expect(waitingLink(tile)).toEqual({
      href: `/agent-sessions/${anId(7, "0192aaaa")}`,
      label: "Open chat",
    });
  });

  it("links a hook-observed permission prompt to the approvals", () => {
    const tile = aLiveTile({
      id: anId(1, "5091b986"),
      group: "waiting",
      status: "waiting",
      waiting_reason: "Permission prompt",
    });

    expect(waitingLink(tile)).toEqual({ href: "/approvals", label: "Open approval" });
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
