import type { components } from "../../api/schema";
import type { ChangedFile } from "./model";

/**
 * The review's files as the pull request has them: the session's own changes (what Claude's file
 * tools did, in order) laid over what git says each repository changes against its base branch.
 *
 * The chat alone only knows the files Claude's Edit and Write calls touched in this session, so a
 * change made from the shell, by another session or before this one would be missing, and a file
 * rewritten whole would read as all added. Where git read the file's repository, git wins: the
 * file's lines and its final diff (the "Final result" a review comment on the file anchors to, with
 * the file's real line numbers) are git's, a file only git knows is listed too, and its commits
 * are the file's history. The session's changes stay as "Each change", in order.
 */

type Schemas = components["schemas"];
export type RepoChanges = Schemas["RepoChanges"];
export type RepoFileChange = Schemas["RepoFileChange"];
export type RepoFileStatus = RepoFileChange["status"];

/** A commit that touched a file, with what it changed there. */
export interface FileCommit {
  sha: string;
  subject: string;
  author: string;
  authoredAt: string;
  added: number;
  removed: number;
}

/** What git says about a file of the review. */
export interface RepoFileInfo {
  /** The repository's folder label and the base its branch is compared with. */
  label: string;
  base: string;
  status: RepoFileStatus;
  /** The name before a rename (absolute). */
  oldPath: string | null;
  /** The branch's commits that touched it, newest first. */
  commits: FileCommit[];
  /** The working tree differs from the last commit too. */
  uncommitted: boolean;
  /** No diff to show: a binary file, or one too big. */
  binary: boolean;
  tooBig: boolean;
  /** Git lists it nowhere: it ends as it is on the base (the session's changes undone, or an
   * ignored file). */
  unchanged: boolean;
}

const inside = (path: string, root: string) =>
  path === root || path.startsWith(root.endsWith("/") ? root : `${root}/`);

function commitsOf(repo: RepoChanges, file: RepoFileChange): FileCommit[] {
  const known = new Map(repo.commits.map((commit) => [commit.sha, commit]));
  const seen = new Set<string>();
  const out: FileCommit[] = [];
  for (const touch of file.commits) {
    const commit = known.get(touch.sha);
    if (!commit || seen.has(touch.sha)) continue;
    seen.add(touch.sha);
    out.push({
      sha: commit.sha,
      subject: commit.subject,
      author: commit.author,
      authoredAt: commit.authored_at,
      added: touch.added,
      removed: touch.removed,
    });
  }
  return out;
}

function fromRepo(repo: RepoChanges, file: RepoFileChange, own: ChangedFile | undefined) {
  const net =
    file.diff === null || file.diff === undefined
      ? null
      : { diff: file.diff, numbered: true, added: file.added, removed: file.removed };
  const merged: ChangedFile = {
    path: file.path,
    created: file.status === "added",
    changes: own?.changes ?? [],
    added: file.added,
    removed: file.removed,
    // A review mark holds this: once git's diff of the file changes, it reads as not viewed.
    lastChangeId: `git:${file.fingerprint}`,
    net,
    repo: {
      label: repo.label,
      base: repo.base ?? "",
      status: file.status,
      oldPath: file.old_path ?? null,
      commits: commitsOf(repo, file),
      uncommitted: file.uncommitted,
      binary: file.binary,
      tooBig: !file.binary && net === null,
      unchanged: false,
    },
  };
  return merged;
}

/** A file the session changed in a repository git read, but that git lists nowhere. */
function unchanged(repo: RepoChanges, own: ChangedFile): ChangedFile {
  return {
    ...own,
    added: 0,
    removed: 0,
    net: { diff: "", numbered: true, added: 0, removed: 0 },
    repo: {
      label: repo.label,
      base: repo.base ?? "",
      status: "modified",
      oldPath: null,
      commits: [],
      uncommitted: false,
      binary: false,
      tooBig: false,
      unchanged: true,
    },
  };
}

/**
 * The session's `files` with git's `repos` laid over them (see the module comment): a file in a
 * repository git compared with a base takes git's view; the repositories' files come first, by
 * path, then the session's other files in their order. Without repositories, `files` as they are.
 */
export function withRepoChanges(
  files: readonly ChangedFile[],
  repos: readonly RepoChanges[] | undefined,
): ChangedFile[] {
  const compared = (repos ?? []).filter((repo) => repo.base);
  if (compared.length === 0) return [...files];
  const own = new Map(files.map((file) => [file.path, file]));
  const out: ChangedFile[] = [];
  const taken = new Set<string>();
  for (const repo of compared) {
    const listed = [...repo.files].sort((a, b) => a.path.localeCompare(b.path));
    for (const file of listed) {
      if (taken.has(file.path)) continue;
      taken.add(file.path);
      out.push(fromRepo(repo, file, own.get(file.path)));
    }
    for (const file of files) {
      if (taken.has(file.path) || !inside(file.path, repo.root)) continue;
      taken.add(file.path);
      out.push(unchanged(repo, file));
    }
  }
  for (const file of files) if (!taken.has(file.path)) out.push(file);
  return out;
}

/** The base and commit count the code tab names: "against origin/main · 12 commits". */
export function repoSummary(repos: readonly RepoChanges[] | undefined): string | null {
  const compared = (repos ?? []).filter((repo) => repo.base);
  if (compared.length === 0) return null;
  return compared
    .map((repo) => {
      const count = repo.commits.length;
      const commits = `${String(count)}${repo.truncated ? "+" : ""} ${count === 1 ? "commit" : "commits"}`;
      const branch = repo.branch ? `${repo.branch} ` : "";
      return `${repo.label}: ${branch}against ${repo.base ?? ""} · ${commits}`;
    })
    .join("; ");
}
