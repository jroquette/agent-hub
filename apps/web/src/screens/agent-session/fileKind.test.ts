import { describe, expect, it } from "vitest";

import { fileKind, isMarkdown, isReviewable, isTestFile } from "./fileKind";

describe("fileKind", () => {
  it.each([
    ["/Users/me/workplace/app/src/index.ts", "code"],
    ["/Users/me/workplace/app/.claude/settings.json", "code"],
    ["/Users/me/workplace/app/docs/plans/rollout.md", "code"],
    ["/Users/me/.claude/plans/happy-otter.md", "plan"],
    ["/Users/me/hub/brain/_inbox/2026-10-19-gotcha.md", "learning"],
    ["/home/me/hub/brain/learnings/gotchas/retry.md", "learning"],
    ["/Users/me/.claude/projects/-Users-me-app/memory/MEMORY.md", "learning"],
    ["/Users/me/hub/brain/decisions/0007-retries.md", "learning"],
    ["/Users/me/hub/brain/features/claims/spec.md", "feature"],
    ["/Users/me/hub/brain/features/claims/reviews/DEM-1/quality-r1.json", "feature"],
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
    expect(isReviewable("/hub/brain/features/f/reviews/T/spec-r1.json")).toBe(false);
    expect(isReviewable("/tmp/notes.md")).toBe(false);
  });

  it("tells markdown by its extension", () => {
    expect(isMarkdown("/a/README.md")).toBe(true);
    expect(isMarkdown("/a/page.MDX")).toBe(true);
    expect(isMarkdown("/a/index.ts")).toBe(false);
  });
});

describe("isTestFile", () => {
  it.each([
    "/repo/demo-shop/tests/order_intents/test_fraud_check_provider.py",
    "/repo/common-data-models/tests/test_payments_constants.py",
    "/repo/pkg/src/thing_test.py",
    "/repo/pkg/conftest.py",
    "/repo/svc/handler_test.go",
    "/repo/apps/web/src/screens/x/FilesPanel.test.tsx",
    "/repo/apps/web/src/lib/format.spec.ts",
    "/repo/apps/web/src/__tests__/helpers.ts",
    "/repo/e2e/review.ts",
  ])("%s is a test", (path) => {
    expect(isTestFile(path)).toBe(true);
  });

  it.each([
    "/repo/demo-shop/src/demo_shop/order_intents/fraud_check_provider.py",
    "/repo/common-data-models/src/common_data_models/insurance/constants.py",
    "/repo/apps/web/src/screens/x/FilesPanel.tsx",
    "/repo/src/testing_utils.py",
    "/repo/src/contest.py",
  ])("%s is not a test", (path) => {
    expect(isTestFile(path)).toBe(false);
  });
});
