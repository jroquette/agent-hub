/**
 * What a changed file is to the person reviewing the session: code that goes in the pull request,
 * or one of Claude's own working files (a plan, a learning, a scratch note). Read from the path
 * alone: the chat does not know the session's folder, only the paths Claude wrote to.
 */
export type FileKind = "code" | "plan" | "learning" | "scratch";

/** The tabs of the review, in order: the code first, Claude's scratch last. */
export const FILE_KINDS: readonly FileKind[] = ["code", "plan", "learning", "scratch"];

/** A user's own Claude folder (`~/.claude/`), not a repo's `.claude/` folder. */
const HOME_CLAUDE = /^(?:\/Users\/[^/]+|\/home\/[^/]+|\/root)\/\.claude\//;
const PLAN = /\/\.claude\/plans\/[^/]+\.md$/;
/** A brain's inbox or learnings, or Claude's auto memory (`~/.claude/projects/<p>/memory/`). */
const LEARNING = /\/brain\/(?:_inbox|learnings)\/|\/\.claude\/projects\/[^/]+\/memory\//;
/** The system's temporary folders: what Claude writes there is for itself. */
const TEMP = /^(?:\/private)?\/(?:tmp|var\/folders)\//;

export function fileKind(path: string): FileKind {
  if (PLAN.test(path)) return "plan";
  if (LEARNING.test(path)) return "learning";
  if (TEMP.test(path) || HOME_CLAUDE.test(path)) return "scratch";
  return "code";
}

/** Markdown, which reads better rendered than as a diff. */
export const isMarkdown = (path: string) => /\.(?:md|markdown|mdx)$/i.test(path);

/** A file whose kind the review counts: Claude's scratch is there to look at, not to review. */
export const isReviewable = (path: string) => fileKind(path) !== "scratch";
