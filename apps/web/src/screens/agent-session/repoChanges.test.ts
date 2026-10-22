import { describe, expect, it } from "vitest";

import { changedFiles, type ToolView } from "./model";
import {
  isDiscarded,
  repoSummary,
  repoState,
  withRepoChanges,
  type RepoChanges,
  type RepoFileChange,
} from "./repoChanges";

const tool = (id: string, name: string, input: Record<string, unknown>): ToolView => ({
  id,
  name,
  input,
  parentId: null,
  diff: null,
  result: { content: "ok", isError: false, truncated: false, originalBytes: null },
});

const own = changedFiles({
  tools: {
    t1: tool("t1", "Edit", { file_path: "/w/api/a.py", old_string: "x", new_string: "y" }),
    t2: tool("t2", "Edit", { file_path: "/w/api/reverted.py", old_string: "x", new_string: "y" }),
    t3: tool("t3", "Write", { file_path: "/w/hub/brain/features/f/spec.md", content: "# s" }),
  },
  permissions: {},
});

const file = (path: string, fields: Partial<RepoFileChange> = {}): RepoFileChange => ({
  path,
  status: "modified",
  added: 3,
  removed: 2,
  diff: `--- a/${path}\n+++ b/${path}\n@@ -1 +1 @@\n-x\n+y`,
  binary: false,
  fingerprint: `fp-${path}`,
  commits: [],
  uncommitted: false,
  ...fields,
});

const repo = (fields: Partial<RepoChanges> = {}): RepoChanges => ({
  source: "worktree",
  root: "/w/api",
  label: "api/dem-1",
  branch: "dem-1",
  base: "origin/main",
  base_sha: "f0",
  commits: [
    { sha: "c2", subject: "second", author: "Ana", authored_at: "2026-10-19T15:00:00Z" },
    { sha: "c1", subject: "first", author: "Ana", authored_at: "2026-10-19T14:00:00Z" },
  ],
  files: [
    file("/w/api/z.py", { commits: [{ sha: "c1", added: 3, removed: 2 }] }),
    file("/w/api/a.py", {
      added: 40,
      removed: 10,
      commits: [
        { sha: "c2", added: 30, removed: 10 },
        { sha: "c1", added: 10, removed: 0 },
      ],
      uncommitted: true,
    }),
    file("/w/api/gone.py", { status: "deleted", added: 0, removed: 9 }),
  ],
  truncated: false,
  ...fields,
});

describe("withRepoChanges", () => {
  it("lists what git says the branch changes, by path, then the session's other files", () => {
    const files = withRepoChanges(own, [repo()]);

    expect(files.map((one) => one.path)).toEqual([
      "/w/api/a.py",
      "/w/api/gone.py",
      "/w/api/z.py",
      "/w/api/reverted.py",
      "/w/hub/brain/features/f/spec.md",
    ]);
  });

  it("takes git's lines and final diff, keeps the session's changes and lists the file's commits", () => {
    const [a] = withRepoChanges(own, [repo()]);

    expect(a).toMatchObject({ added: 40, removed: 10, lastChangeId: "git:fp-/w/api/a.py" });
    expect(a?.net).toMatchObject({ numbered: true, added: 40, removed: 10 });
    expect(a?.changes.map((change) => change.tool.id)).toEqual(["t1"]);
    expect(a?.repo?.commits.map((commit) => [commit.subject, commit.added])).toEqual([
      ["second", 30],
      ["first", 10],
    ]);
    expect(a?.repo?.uncommitted).toBe(true);
  });

  it("lists a file only git knows, and one deleted, with their status", () => {
    const files = withRepoChanges(own, [repo()]);
    const gone = files.find((one) => one.path === "/w/api/gone.py");
    const z = files.find((one) => one.path === "/w/api/z.py");

    expect(gone?.repo?.status).toBe("deleted");
    expect(z?.changes).toEqual([]);
    expect(z?.repo?.commits.map((commit) => commit.sha)).toEqual(["c1"]);
  });

  it("says a file the session changed ends as on the base when git lists it nowhere", () => {
    const reverted = withRepoChanges(own, [repo()]).find(
      (one) => one.path === "/w/api/reverted.py",
    );

    expect(reverted).toMatchObject({ added: 0, removed: 0 });
    expect(reverted?.repo?.unchanged).toBe(true);
  });

  it("calls a file discarded when it ends as it began, and only then (AC-424.6)", () => {
    const files = withRepoChanges(own, [repo()]);

    expect(files.filter(isDiscarded).map((one) => one.path)).toEqual(["/w/api/reverted.py"]);
    expect(own.filter(isDiscarded)).toEqual([]);
  });

  it("marks a file with no diff to show as binary or too big", () => {
    const files = withRepoChanges(own, [
      repo({
        files: [
          file("/w/api/logo.png", { diff: null, binary: true }),
          file("/w/api/huge.json", { diff: null }),
        ],
      }),
    ]);

    expect(files[0]?.repo).toMatchObject({ binary: false, tooBig: true });
    expect(files[1]?.repo).toMatchObject({ binary: true, tooBig: false });
  });

  it("keeps the session's files as they are without a repository git compared", () => {
    expect(withRepoChanges(own, undefined)).toEqual(own);
    expect(withRepoChanges(own, [repo({ base: null, files: [] })])).toEqual(own);
  });
});

describe("repoSummary", () => {
  it("names the branch, its base and how many commits", () => {
    expect(repoSummary([repo()])).toBe("api/dem-1: dem-1 against origin/main · 2 commits");
    expect(repoSummary(undefined)).toBeNull();
  });
});

describe("repoState", () => {
  const pull = (fields: Partial<NonNullable<RepoChanges["pull_request"]>> = {}) => ({
    number: 545,
    url: "https://github.com/acme/ui/pull/545",
    state: "OPEN",
    head_sha: "h1",
    ...fields,
  });

  it.each([
    ["no pull request yet", repo({ head_sha: "h1", files: [] }), "No pull request yet"],
    [
      "in sync",
      repo({ head_sha: "h1", files: [], pull_request: pull() }),
      "In sync with the pull request",
    ],
    [
      "uncommitted since the PR",
      repo({
        head_sha: "h1",
        pull_request: pull(),
        files: [file("/w/api/a.py", { uncommitted: true })],
      }),
      "1 file changed since the pull request",
    ],
    [
      "local commits the PR lacks",
      repo({ head_sha: "h2", pull_request: pull() }),
      "Commits not in the pull request yet",
    ],
    ["merged", repo({ pull_request: pull({ state: "MERGED" }) }), "Pull request merged"],
    ["closed", repo({ pull_request: pull({ state: "CLOSED" }) }), "Pull request closed"],
    ["worktree removed", repo({ source: "recorded" }), "Worktree removed: its recorded commits"],
    [
      "uncommitted, no PR",
      repo({
        files: [
          file("/w/api/a.py", { uncommitted: true }),
          file("/w/api/b.py", { uncommitted: true }),
        ],
      }),
      "2 files not committed",
    ],
  ])("%s", (_, given, text) => {
    expect(repoState(given).text).toBe(text);
  });
});
