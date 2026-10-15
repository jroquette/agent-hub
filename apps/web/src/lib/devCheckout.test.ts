import { describe, expect, it } from "vitest";

import { aWorkdir } from "../testing/builders";
import { derivedWorkdirId, matchingWorkdir, servedCheckout } from "./devCheckout";

// The same vector as core's test_matches_known_vector_when_id_derived (E6).
const ROOT = "/srv/demo/agent-hub";
const REPO_ID = "5703fef9dd5a3894";
const WORKTREE_ID = "51735bb2177a46eb";

describe("devCheckout (O8)", () => {
  it("known-vector: same id as core", async () => {
    expect(await derivedWorkdirId("repo", ROOT)).toBe(REPO_ID);
    expect(await derivedWorkdirId("worktree", ROOT)).toBe(WORKTREE_ID);
  });

  it("live-edit: matches the repo or worktree workdir", async () => {
    const hub = aWorkdir();
    const repo = aWorkdir({ kind: "repo", label: "agent-hub", workdir_id: REPO_ID });
    const worktree = aWorkdir({ kind: "worktree", label: "agh-1", workdir_id: WORKTREE_ID });

    expect(await matchingWorkdir(ROOT, [hub, repo])).toBe(REPO_ID);
    expect(await matchingWorkdir(ROOT, [hub, worktree])).toBe(WORKTREE_ID);
  });

  it("live-edit-fallback: null root or no match gives null", async () => {
    const repo = aWorkdir({ kind: "repo", label: "agent-hub", workdir_id: REPO_ID });

    expect(await matchingWorkdir(null, [repo])).toBeNull();
    expect(await matchingWorkdir("/srv/other", [repo, aWorkdir()])).toBeNull();
    expect(await matchingWorkdir(ROOT, [])).toBeNull();
  });

  it("live-edit-fallback: the served checkout is a string or null, never in a build", () => {
    const served = servedCheckout();
    expect(served === null || typeof served === "string").toBe(true);
  });
});
