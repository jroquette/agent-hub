/**
 * What a session is about (S1, AC-201.4, AC-201.5): `DEMO-1511 · /feature` over `repo · branch`.
 *
 * The deprecated `agent` field is never shown: the main agent's stored value "main" read as a branch
 * and said nothing about the session. Without an issue or a workflow the title falls back to
 * `repo · branch`, then to the short session id, so it is never blank.
 */
import type { components } from "../api/schema";

type Label = components["schemas"]["SessionLabel"];

/** The fields a session label needs; Session and LiveTile both have them. */
export interface LabelledSession {
  id: string;
  repo: string | null;
  label?: Label | null | undefined;
}

export interface SessionIdentity {
  /** `DEMO-1511 · /feature`, else `repo · branch`, else the short id. */
  title: string;
  /** What the title leaves out: `repo · branch` under an issue or workflow, else the short id. */
  detail: string | null;
}

export const shortSessionId = (id: string) => id.replace(/-/g, "").slice(0, 8);

const joined = (...parts: (string | null | undefined)[]) =>
  parts.filter((part): part is string => Boolean(part)).join(" · ");

export function sessionIdentity(session: LabelledSession): SessionIdentity {
  const label = session.label ?? null;
  const what = joined(label?.issue, label?.workflow);
  const where = joined(label?.repo ?? session.repo, label?.branch);
  const short = shortSessionId(session.id);
  if (what) return { title: what, detail: where || null };
  if (where) return { title: where, detail: short };
  return { title: short, detail: null };
}

/** One line of text for aria labels and announcements: "DEMO-1511 · /feature, demo · main". */
export function sessionLabelText(session: LabelledSession): string {
  const { title, detail } = sessionIdentity(session);
  return detail ? `${title}, ${detail}` : title;
}

export interface SessionLabelProps {
  session: LabelledSession;
  /** The title's class (e.g. `ah-tile-agent` on a live tile). */
  titleClassName?: string | undefined;
}

/** The session cell of lists and tiles: the title, then `repo · branch` below. */
export function SessionLabel({ session, titleClassName }: SessionLabelProps) {
  const { title, detail } = sessionIdentity(session);
  return (
    <span className="ah-stack" style={{ gap: 0, minWidth: 0 }}>
      <span
        className={titleClassName ?? "ah-mono"}
        style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
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
