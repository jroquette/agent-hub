import { useId, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import {
  AppLink,
  Button,
  ExternalLabel,
  Icon,
  ProblemError,
  ProvenanceBadge,
  Skeleton,
  Tooltip,
  type Provenance,
} from "../../components";
import { fmtDateTime } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { LearningStateBadge, Title, stateOf } from "../learnings/LearningDetail";
import type { useNoteLearnings } from "./queries";

type Frontmatter = Record<string, components["schemas"]["FrontmatterValue"]>;
type Learning = components["schemas"]["Learning"];

/** The id of the section's heading, which the note header's jump button focuses. */
export const NOTE_ORIGIN_ID = "brain-note-origin";
/** The section's heading. */
export const NOTE_ORIGIN = "Where this note came from";
/** A frontmatter `session:` this app can link to (Q-7); any other value stays a chip. */
const SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/;
/** The sources shown before "Show all". */
const SOURCES_SHOWN = 5;
const PROVENANCES: ReadonlySet<string> = new Set([
  "human",
  "agent",
  "agent-from-code",
  "agent-from-external",
]);

/** The frontmatter `session:` value when it is a session id the app can link to, else null. */
export function frontmatterSession(frontmatter: Frontmatter): string | null {
  const value = frontmatter.session;
  return typeof value === "string" && SESSION_ID.test(value) ? value : null;
}

/** The frontmatter fields this section shows, which the note's chips leave out (AM-1). */
export function originFields(frontmatter: Frontmatter): string[] {
  return ["provenance", "sources", ...(frontmatterSession(frontmatter) ? ["session"] : [])];
}

/** A session id as the app shows it: a UUID's first 8 hex digits, any other id's first 8 characters. */
function shortSession(id: string): string {
  return /^[0-9a-f]{8}-/i.test(id) ? id.replace(/-/g, "").slice(0, 8) : id.slice(0, 8);
}

function asList(value: Frontmatter[string] | undefined): string[] {
  if (value === undefined) return [];
  return (Array.isArray(value) ? value : [value]).filter((item) => item.trim() !== "");
}

/** A decided date, absolute (`4 Oct 2026`), local or UTC per the top bar; the time on hover. */
function DecidedDate({ iso }: { iso: string }) {
  const { tz } = usePreferences();
  const day = new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(tz === "utc" ? { timeZone: "UTC" } : {}),
  });
  return (
    <time dateTime={iso} title={fmtDateTime(iso, tz)}>
      {day}
    </time>
  );
}

function SessionLink({ id }: { id: string }) {
  return (
    <Link to={`/sessions/${encodeURIComponent(id)}`} aria-label={`Session ${id}`} title={id}>
      session {shortSession(id)}
    </Link>
  );
}

function Row({ label, busy, children }: { label: string; busy?: boolean; children: ReactNode }) {
  return (
    <div className="ah-origin-row" aria-busy={busy ? true : undefined}>
      <dt className="ah-small ah-subtle">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Sources({ sources }: { sources: string[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? sources : sources.slice(0, SOURCES_SHOWN);
  return (
    <>
      <ul className="ah-origin-list">
        {shown.map((source, i) => (
          <li key={`${String(i)}:${source}`}>{source}</li>
        ))}
      </ul>
      {sources.length > SOURCES_SHOWN && (
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={all}
          onClick={() => {
            setAll(!all);
          }}
        >
          {all
            ? `Show the first ${String(SOURCES_SHOWN)}`
            : `Show all ${String(sources.length)} sources`}
        </Button>
      )}
    </>
  );
}

function LearningItem({ learning }: { learning: Learning }) {
  const session = learning.source_session_id;
  return (
    <li className="ah-origin-learning">
      <span className="ah-row ah-wrap" style={{ gap: 6 }}>
        <Icon name="lightbulb" size="sm" />
        <AppLink href={`/knowledge/learnings/${encodeURIComponent(learning.id)}`}>
          <Title t={learning.text} />
        </AppLink>
        <LearningStateBadge state={stateOf(learning)} />
      </span>
      <span className="ah-small ah-muted">
        Accepted
        {learning.decided_at ? (
          <>
            {" "}
            <DecidedDate iso={learning.decided_at} />
          </>
        ) : null}
        {learning.decided_by ? ` by ${learning.decided_by}` : ""}
        {" · "}
        {session ? <SessionLink id={session} /> : "no source session recorded"}
      </span>
    </li>
  );
}

/**
 * "Where this note came from" (AGH-393, D-note-origin): the note's provenance and sources as
 * text, the accepted learnings that put it here with their sessions, or the session its
 * frontmatter names. Only what the records hold: no count, no effect (Q16).
 */
export function NoteOrigin({
  frontmatter,
  learnings,
}: {
  /** The loaded note's frontmatter. */
  frontmatter: Frontmatter;
  /** The accepted learnings that name the note, asked for by the screen as the note opens. */
  learnings: ReturnType<typeof useNoteLearnings>;
}) {
  const tipId = useId();
  const provenance = asList(frontmatter.provenance).join(", ");
  const sources = asList(frontmatter.sources);
  const items = learnings.data?.items ?? [];
  const named = items.some((learning) => learning.source_session_id);
  const session = learnings.isPending || named ? null : frontmatterSession(frontmatter);
  const nothing =
    provenance === "" &&
    sources.length === 0 &&
    learnings.isSuccess &&
    items.length === 0 &&
    !session;

  return (
    <section
      className="ah-note-section"
      aria-labelledby={NOTE_ORIGIN_ID}
      aria-busy={learnings.isPending ? true : undefined}
    >
      <h2 id={NOTE_ORIGIN_ID} className="ah-h3" tabIndex={-1}>
        {NOTE_ORIGIN}
      </h2>
      {nothing ? (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          No provenance recorded for this note.
        </p>
      ) : (
        <dl className="ah-origin">
          {provenance !== "" && (
            <Row label="Provenance">
              {PROVENANCES.has(provenance) ? (
                <span className="ah-row ah-wrap" style={{ gap: 6 }}>
                  <ProvenanceBadge provenance={provenance as Provenance} />
                  {provenance === "agent-from-external" && <ExternalLabel />}
                </span>
              ) : (
                provenance
              )}
            </Row>
          )}
          {sources.length > 0 && (
            <Row label="Sources">
              <Sources sources={sources} />
            </Row>
          )}
          {learnings.isPending && (
            <Row label="Learnings" busy>
              <Skeleton lines={2} />
            </Row>
          )}
          {learnings.isError && (
            <Row label="Learnings">
              <ProblemError
                compact
                title="Could not load the learnings for this note."
                onRetry={() => void learnings.refetch()}
              />
            </Row>
          )}
          {items.length > 0 && (
            <Row label="Learnings">
              <ul className="ah-origin-list">
                {items.map((learning) => (
                  <LearningItem key={learning.id} learning={learning} />
                ))}
              </ul>
              {learnings.data?.next_cursor && (
                <p className="ah-small ah-muted" style={{ margin: 0 }}>
                  More learnings name this note; the 10 newest are shown.
                </p>
              )}
            </Row>
          )}
          {session && (
            <Row label="Session">
              <span className="ah-small">
                <Tooltip label="Opens the session if this app collected it." id={tipId}>
                  <Link
                    to={`/sessions/${encodeURIComponent(session)}`}
                    aria-label={`Session ${session}`}
                    aria-describedby={tipId}
                  >
                    session {shortSession(session)}
                  </Link>
                </Tooltip>
                {" · "}
                <span className="ah-subtle">From the note&apos;s frontmatter.</span>
              </span>
            </Row>
          )}
        </dl>
      )}
    </section>
  );
}
