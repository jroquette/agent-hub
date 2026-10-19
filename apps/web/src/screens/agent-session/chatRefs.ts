import { createContext, useMemo } from "react";
import { useNavigate } from "react-router";

import type { InlineRef } from "../../components";
import { useApi } from "../../lib/api";
import { githubPullHref, linearHref, safeHref } from "../../lib/safeHref";
import { useTicketLookup } from "../features/queries";

/**
 * What Claude's replies name, turned into links: a bare URL, a pull request (`owner/repo#545`, or
 * `repo#545` for a repo of the project), a ticket of the project's tracker teams (`DEMO-1564`: in
 * Linear when its workspace is known, else on its feature's page here) and a file of the session's review (its full path, or a tail of
 * it that names one file only), which opens in the review drawer. Anything else stays text.
 */
export interface ChatRefsSource {
  /** The project's tracker team keys (`TIP`). */
  ticketKeys: readonly string[];
  /** The Linear workspace's URL (`https://linear.app/<workspace>`), null when not known. */
  linearBase: string | null;
  /** The page of the feature a ticket belongs to, here; null when no feature names it. */
  ticketRoute: (ticket: string) => string | null;
  /** Goes to a page of the app. */
  onNavigate: (route: string) => void;
  /** The project's repos: name and folder, and their GitHub `owner/repo`. */
  repos: readonly { name: string; dir: string; github: string }[];
  /** The files of the session's review, by full path. */
  files: readonly string[];
  /** Opens a file of the review in the drawer. */
  onOpenFile: (path: string) => void;
}

/** Splits a text into its refs: text, or a link (an external `href`, or a file to `open`). */
export type FindRefs = (text: string) => readonly (string | InlineRef)[] | null;

const URL_RE = String.raw`https?:\/\/[^\s<>()\[\]{}"'` + "`" + String.raw`]+`;
const FULL_PR = String.raw`[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9._-]+#[1-9]\d*`;
const PATH = String.raw`~?[\w.@-]*(?:\/[\w.@-]+)+`;
const SHORT_PR = String.raw`[A-Za-z0-9._-]+#[1-9]\d*`;
/** Punctuation that ends a sentence, not a URL. */
const TRAILING = /[.,;:!?]+$/;

/** The project's ref finder; null when there is nothing it could link. */
export function chatRefs(source: ChatRefsSource): FindRefs {
  const keys = source.ticketKeys.filter((key) => /^[A-Z][A-Z0-9]{0,9}$/.test(key));
  const ticket = keys.length > 0 ? String.raw`\b(?:${keys.join("|")})-[1-9]\d*\b` : null;
  const pattern = new RegExp(
    [URL_RE, FULL_PR, PATH, SHORT_PR, ticket].filter(Boolean).join("|"),
    "g",
  );
  const githubOf = (repo: string) => {
    const name = repo.toLowerCase();
    return (
      source.repos.find((r) => r.name.toLowerCase() === name || r.dir.toLowerCase() === name)
        ?.github ?? null
    );
  };
  const fileOf = (path: string): string | null => {
    if (source.files.includes(path)) return path;
    if (path.startsWith("/") || path.startsWith("~")) {
      const home = path.startsWith("~/") ? path.slice(1) : null;
      const hit = home ? source.files.filter((file) => file.endsWith(home)) : [];
      return hit.length === 1 ? (hit[0] ?? null) : null;
    }
    const tail = source.files.filter((file) => file.endsWith(`/${path}`));
    return tail.length === 1 ? (tail[0] ?? null) : null;
  };

  const refOf = (token: string): InlineRef | null => {
    if (/^https?:\/\//.test(token)) {
      const href = safeHref(token);
      return href ? { href, label: token } : null;
    }
    if (ticket && new RegExp(`^${ticket}$`).test(token)) {
      const href = source.linearBase ? linearHref(`${source.linearBase}/issue/${token}`) : null;
      if (href) return { href, label: token, title: `Open ${token} in Linear` };
      const route = source.ticketRoute(token);
      return route
        ? {
            label: token,
            title: `Open ${token}'s feature`,
            open: () => {
              source.onNavigate(route);
            },
          }
        : null;
    }
    const pr = /^(?:([A-Za-z0-9][A-Za-z0-9-]*)\/)?([A-Za-z0-9._-]+)#([1-9]\d*)$/.exec(token);
    if (pr) {
      const [, owner, repo = "", number = ""] = pr;
      const full = owner ? `${owner}/${repo}` : githubOf(repo);
      const href = full ? githubPullHref(`https://github.com/${full}/pull/${number}`) : null;
      return href ? { href, label: token, title: `Open ${token} on GitHub` } : null;
    }
    const file = fileOf(token);
    if (file) {
      return {
        label: token,
        title: `Open ${file} in the review`,
        open: () => {
          source.onOpenFile(file);
        },
      };
    }
    return null;
  };

  return (text) => {
    const parts: (string | InlineRef)[] = [];
    let last = 0;
    let found = false;
    for (const match of text.matchAll(pattern)) {
      let token = match[0];
      const trailing = TRAILING.exec(token)?.[0] ?? "";
      token = token.slice(0, token.length - trailing.length);
      const ref = token ? refOf(token) : null;
      if (!ref) continue;
      if (match.index > last) parts.push(text.slice(last, match.index));
      parts.push(ref);
      last = match.index + token.length;
      found = true;
    }
    if (!found) return null;
    if (last < text.length) parts.push(text.slice(last));
    return parts;
  };
}

/** The chat's ref finder, for Claude's replies; null outside a session page. */
export const ChatRefsContext = createContext<FindRefs | null>(null);

/**
 * The session page's ref finder: the project's tracker teams and repos, the Linear workspace when
 * hub web reads Linear, the features' tickets, and the files of the review.
 */
export function useChatRefs(
  project: string | null,
  files: readonly string[],
  onOpenFile: (path: string) => void,
): FindRefs {
  const navigate = useNavigate();
  const params = { path: { project: project ?? "" } };
  const detail = useApi("/api/v1/projects/{project}", params, {
    enabled: project !== null,
    staleTime: 60_000,
  }).data;
  const repos = useApi("/api/v1/projects/{project}/repos", params, {
    enabled: project !== null,
    staleTime: 60_000,
  }).data?.items;
  const linear = useApi("/api/v1/tracker/linear", undefined, { staleTime: 60_000, retry: false })
    .data?.account?.url;
  const tickets = useTicketLookup(project);
  return useMemo(() => {
    const keys = new Set(detail?.tracker.teams ?? []);
    for (const id of tickets.keys()) keys.add(id.replace(/-\d+$/, ""));
    return chatRefs({
      ticketKeys: [...keys],
      linearBase: linear ?? null,
      ticketRoute: (ticket) => {
        const found = tickets.get(ticket.toUpperCase());
        return found
          ? `/features/${encodeURIComponent(found.project)}/${encodeURIComponent(found.slug)}`
          : null;
      },
      onNavigate: (route) => {
        void navigate(route);
      },
      repos: repos ?? [],
      files,
      onOpenFile,
    });
  }, [detail, tickets, linear, repos, files, onOpenFile, navigate]);
}
