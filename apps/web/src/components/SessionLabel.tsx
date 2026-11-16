/**
 * What a session is about (S1, AC-201.4, AC-201.5): its name over `ACME-1511 · /feature · repo · branch`.
 *
 * A session on a ticket is named as its commits are, the ticket then what it is about:
 * `ACME-1511: Export orders as CSV` (the ticket's title, when the hub's features have read it), else
 * its slug (the hub feature's slug for that ticket, else what the branch or worktree says after the
 * ticket), else Claude's title. Otherwise the name is the session's title (the
 * user's `/rename`, else the one Claude Code wrote, ADR 0035). Without one, the title is
 * `ACME-1511 · /feature` over `repo · branch`, as before.
 *
 * The deprecated `agent` field is never shown: the main agent's stored value "main" read as a branch
 * and said nothing about the session. Without an issue or a workflow the title falls back to
 * `repo · branch`, then to the short session id, so it is never blank.
 */
import type { components } from "../api/schema";

type Label = components["schemas"]["SessionLabel"];

/** The fields a session label needs (a `Session` has them). */
export interface LabelledSession {
  id: string;
  repo: string | null;
  label?: Label | null | undefined;
}

export interface SessionIdentity {
  /** The session's name, else `ACME-1511 · /feature`, else `repo · branch`, else the short id. */
  title: string;
  /** What the title leaves out: issue, workflow, repo and branch under a name, else the short id. */
  detail: string | null;
  /** Whether `title` is the session's name (prose), not an identifier. */
  named: boolean;
}

export const shortSessionId = (id: string) => id.replace(/-/g, "").slice(0, 8);

/** A ticket a hub feature works on: the feature, and the ticket's title once read. */
export interface TicketInfo {
  project: string;
  /** The feature's slug. */
  slug: string;
  title: string | null;
}

/** The tickets the hub's features work on, by ticket id (uppercased). */
export type TicketLookup = ReadonlyMap<string, TicketInfo>;

const escaped = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** What `text` (a branch, a worktree) says after `issue`: `roquettejh/acme-12-fix-login` gives
 * `fix-login`; null when it does not name the issue or says nothing after it. */
export function slugAfterIssue(text: string | null | undefined, issue: string): string | null {
  if (!text) return null;
  const found = new RegExp(`${escaped(issue)}(?![0-9])[-_/]*(.*)$`, "i").exec(text);
  const rest = found?.[1]?.trim();
  return rest === undefined || rest === "" ? null : rest;
}

/** A ticket session's name, as its commits read: `ACME-12: fix-login`; null without an issue. */
export function ticketName(label: Label | null | undefined, tickets?: TicketLookup): string | null {
  const issue = label?.issue;
  if (!issue) return null;
  const known = tickets?.get(issue.toUpperCase());
  const slug =
    known?.title?.trim() ??
    known?.slug ??
    slugAfterIssue(label.branch, issue) ??
    slugAfterIssue(label.worktree, issue) ??
    label.title?.trim();
  return slug ? `${issue}: ${slug}` : null;
}

const joined = (...parts: (string | null | undefined)[]) =>
  parts.filter((part): part is string => Boolean(part)).join(" · ");

export function sessionIdentity(session: LabelledSession, tickets?: TicketLookup): SessionIdentity {
  const label = session.label ?? null;
  const what = joined(label?.issue, label?.workflow);
  const where = joined(label?.repo ?? session.repo, label?.branch);
  const short = shortSessionId(session.id);
  const ticket = ticketName(label, tickets);
  if (ticket)
    return { title: ticket, detail: joined(label?.workflow, where) || short, named: true };
  const name = label?.title?.trim();
  if (name) return { title: name, detail: joined(what, where) || short, named: true };
  if (what) return { title: what, detail: where || null, named: false };
  if (where) return { title: where, detail: short, named: false };
  return { title: short, detail: null, named: false };
}

/** One line of text for aria labels and announcements: "ACME-1511 · /feature, storefront · main". */
export function sessionLabelText(session: LabelledSession): string {
  const { title, detail } = sessionIdentity(session);
  return detail ? `${title}, ${detail}` : title;
}

export interface SessionLabelProps {
  session: LabelledSession;
  /** The title's class (e.g. `ah-tile-agent` on a live tile). */
  titleClassName?: string | undefined;
}

/** The session cell of lists and tiles: the title, then what it leaves out below. */
export function SessionLabel({ session, titleClassName }: SessionLabelProps) {
  const { title, detail, named } = sessionIdentity(session);
  return (
    <span className="ah-stack" style={{ gap: 0, minWidth: 0 }}>
      <span
        className={titleClassName ?? (named ? undefined : "ah-mono")}
        style={{
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          ...(named && { fontWeight: 500 }),
        }}
        title={title}
      >
        {title}
      </span>
      {detail && (
        <span
          className="ah-mono ah-small ah-subtle"
          style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          title={detail}
        >
          {detail}
        </span>
      )}
    </span>
  );
}
