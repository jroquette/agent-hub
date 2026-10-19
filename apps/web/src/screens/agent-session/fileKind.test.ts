import { describe, expect, it } from "vitest";

import { fileKind, isMarkdown, isReviewable } from "./fileKind";

describe("fileKind", () => {
  it.each([
    ["/Users/me/workplace/app/src/index.ts", "code"],
    ["/Users/me/workplace/app/.claude/settings.json", "code"],
    ["/Users/me/workplace/app/docs/plans/rollout.md", "code"],
    ["/Users/me/.claude/plans/happy-otter.md", "plan"],
    ["/Users/me/hub/brain/_inbox/2026-10-19-gotcha.md", "learning"],
    ["/home/me/hub/brain/learnings/gotchas/retry.md", "learning"],
    ["/Users/me/.claude/projects/-Users-me-app/memory/MEMORY.md", "learning"],
    ["/tmp/notes.md", "scratch"],
    ["/private/tmp/claude-501/out.json", "scratch"],
    ["/var/folders/x1/T/scratch.md", "scratch"],
    ["/Users/me/.claude/settings.json", "scratch"],
  ])("%s is %s", (path, kind) => {
    expect(fileKind(path)).toBe(kind);
  });

  it("counts only the code as something to review", () => {
    expect(isReviewable("/repo/src/index.ts")).toBe(true);
    expect(isReviewable("/Users/me/.claude/plans/p.md")).toBe(false);
    expect(isReviewable("/hub/brain/_inbox/l.md")).toBe(false);
    expect(isReviewable("/tmp/notes.md")).toBe(false);
  });

  it("tells markdown by its extension", () => {
    expect(isMarkdown("/a/README.md")).toBe(true);
    expect(isMarkdown("/a/page.MDX")).toBe(true);
    expect(isMarkdown("/a/index.ts")).toBe(false);
  });
});
