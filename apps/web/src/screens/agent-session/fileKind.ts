import type { IconName } from "../../components";

/**
 * What a changed file is to the person reviewing the session: code that goes in the pull request,
 * or one of Claude's own working files (a plan, a feature's record, a brain note, a scratch note). Read from the path
 * alone: the chat does not know the session's folder, only the paths Claude wrote to.
 */
export type FileKind = "code" | "plan" | "feature" | "learning" | "scratch";

/** The tabs of the review, in order: the code first, Claude's scratch last. */
export const FILE_KINDS: readonly FileKind[] = ["code", "plan", "feature", "learning", "scratch"];

/** A user's own Claude folder (`~/.claude/`), not a repo's `.claude/` folder. */
const HOME_CLAUDE = /^(?:\/Users\/[^/]+|\/home\/[^/]+|\/root)\/\.claude\//;
const PLAN = /\/\.claude\/plans\/[^/]+\.md$/;
/** A feature's record in a hub's brain: its spec, plan, research, evals and the workflow's
 * spec and quality reviews (`brain/features/<feature>/…`). */
const FEATURE = "/brain/features/";
/** Any other note of a hub's brain (inbox, learnings, decisions, domain…), or Claude's auto
 * memory (`~/.claude/projects/<p>/memory/`). */
const LEARNING = /\/brain\/|\/\.claude\/projects\/[^/]+\/memory\//;
/** The system's temporary folders: what Claude writes there is for itself. */
const TEMP = /^(?:\/private)?\/(?:tmp|var\/folders)\//;

/** Each kind of file as the review shows it: its tab, and its group in a turn's files card. */
export const KIND_TAB: Record<FileKind, { label: string; icon: IconName; hint: string }> = {
  code: { label: "Code", icon: "git-pull-request", hint: "goes in the pull request" },
  plan: { label: "Plans", icon: "list-checks", hint: "Claude's plan, stays on this machine" },
  feature: {
    label: "Reviews & specs",
    icon: "clipboard-list",
    hint: "the workflow's reviews, spec, plan and evals of the feature, in the brain",
  },
  learning: { label: "Learnings", icon: "lightbulb", hint: "notes for the brain" },
  scratch: { label: "Scratch", icon: "pencil", hint: "Claude's notes, nothing to review" },
};

export function fileKind(path: string): FileKind {
  if (PLAN.test(path)) return "plan";
  if (path.includes(FEATURE)) return "feature";
  if (LEARNING.test(path)) return "learning";
  if (TEMP.test(path) || HOME_CLAUDE.test(path)) return "scratch";
  return "code";
}

/** Markdown, which reads better rendered than as a diff. */
export const isMarkdown = (path: string) => /\.(?:md|markdown|mdx)$/i.test(path);

/** A file you review (viewed marks, "to review" counts): only the code that goes in the pull
 * request. Claude's plans, feature records, brain notes and scratch are there to read, not to sign
 * off. */
export const isReviewable = (path: string) => fileKind(path) === "code";

/** A test file (a folder like `tests/`, `__tests__/` or `e2e/`, or a name like `test_x.py`,
 * `x_test.go`, `x.test.ts`, `x.spec.tsx`, `conftest.py`): the code tab can show them apart from
 * the code they test. */
const TEST_DIR = /(?:^|\/)(?:tests?|__tests__|specs?|e2e)\//;
const TEST_NAME =
  /(?:^|\/)(?:test_[^/]+\.py|[^/]+_test\.(?:py|go)|[^/]+\.(?:test|spec)\.[cm]?[jt]sx?|conftest\.py)$/;
export const isTestFile = (path: string) => TEST_DIR.test(path) || TEST_NAME.test(path);
