/**
 * What a session is about (S1, AC-201.4, AC-201.5): its name over `TIP-1511 · /feature · repo · branch`.
 *
 * The name is the session's title (the user's `/rename`, else the one Claude Code wrote, ADR 0035).
 * Without one, the title is `TIP-1511 · /feature` over `repo · branch`, as before.
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
  /** The session's name, else `TIP-1511 · /feature`, else `repo · branch`, else the short id. */
  title: string;
  /** What the title leaves out: issue, workflow, repo and branch under a name, else the short id. */
  detail: string | null;
  /** Whether `title` is the session's name (prose), not an identifier. */
  named: boolean;
}

export const shortSessionId = (id: string) => id.replace(/-/g, "").slice(0, 8);

const joined = (...parts: (string | null | undefined)[]) =>
  parts.filter((part): part is string => Boolean(part)).join(" · ");

export function sessionIdentity(session: LabelledSession): SessionIdentity {
  const label = session.label ?? null;
  const what = joined(label?.issue, label?.workflow);
  const where = joined(label?.repo ?? session.repo, label?.branch);
  const short = shortSessionId(session.id);
  const name = label?.title?.trim();
  if (name) return { title: name, detail: joined(what, where) || short, named: true };
  if (what) return { title: what, detail: where || null, named: false };
  if (where) return { title: where, detail: short, named: false };
  return { title: short, detail: null, named: false };
}

/** One line of text for aria labels and announcements: "TIP-1511 · /feature, tipple · main". */
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
