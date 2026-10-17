/*
 * The human summary of a feature record: `brain/features/<slug>/summaries/<record>.md`, written by
 * the hub's `/summarize` skill. People skim long agent records instead of reading them, so the
 * record tabs open on this short summary; the record itself stays the agents' reference.
 */
import "./summary.css";

import { useNavigate } from "react-router";

import type { components } from "../../api/schema";
import { Banner, Button, EmptyState, Markdown, ProblemError, Skeleton } from "../../components";
import type { LocalLink } from "../../components";
import { useDiscuss } from "../../shell/discuss";
import { useBrainNote, useBrainTree } from "../brain/queries";

type Note = components["schemas"]["BrainNote"];

/** Where a record's human summary lives, under `brain/`. */
export function summaryPath(recordPath: string): string {
  const cut = recordPath.lastIndexOf("/");
  return `${recordPath.slice(0, cut)}/summaries/${recordPath.slice(cut + 1)}`;
}

/** The message that asks Claude, in the Discuss panel, to write or refresh a record's summary. */
export function summaryRequest(slug: string, record: string): string {
  return (
    `Run /summarize ${slug} ${record}: write the human summary of brain/features/${slug}/${record}.md ` +
    `to brain/features/${slug}/summaries/${record}.md, following the hub-workflow summarize skill.`
  );
}

function fieldText(note: Note, key: string): string | null {
  const value = note.frontmatter[key];
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

/** "fresh" when the summary names the record's current bytes, "stale" when another version. */
export function summaryState(summary: Note, record: Note | undefined): "fresh" | "stale" | null {
  const source = fieldText(summary, "source_sha256");
  if (!record?.sha256 || !source) return null;
  return source.toLowerCase() === record.sha256.toLowerCase() ? "fresh" : "stale";
}

export interface RecordSummaryProps {
  project: string;
  /** `spec`, `research` or `plan`. */
  record: string;
  /** The record's path under `brain/`. */
  recordPath: string;
  /** Shows the record itself (the Agent markdown view), at a heading when given. */
  onReadRecord: (anchor?: string) => void;
}

/** The summary, how fresh it is, and the way to the full record or to a new summary. */
export function RecordSummary({ project, record, recordPath, onReadRecord }: RecordSummaryProps) {
  const path = summaryPath(recordPath);
  // The brain's listing says whether a summary exists, so a record without one asks for nothing
  // that is not there (no 404 in the console); an unreadable listing falls back to asking.
  const tree = useBrainTree(project);
  const listed = tree.isError ? true : tree.data?.entries.some((entry) => entry.path === path);
  const summary = useBrainNote(project, path, listed === true);
  const missing = listed === false || (summary.isError && summary.error.status === 404);
  const source = useBrainNote(project, recordPath);
  const navigate = useNavigate();
  const { setOpen } = useDiscuss();
  const file = `${record}.md`;

  const askClaude = (
    <Button
      size="sm"
      icon="message-square"
      onClick={() => {
        setOpen(true);
      }}
    >
      Ask Claude to {missing ? "write" : "update"} it
    </Button>
  );
  const readRecord = (
    <Button
      size="sm"
      variant="ghost"
      icon="file-text"
      onClick={() => {
        onReadRecord();
      }}
    >
      Read the full {file}
    </Button>
  );

  if (!missing && (listed === undefined || summary.isPending)) {
    return (
      <div aria-busy="true" className="ah-stack">
        <Skeleton width={280} height={22} />
        <Skeleton lines={6} />
      </div>
    );
  }
  if (missing || summary.isError) {
    if (!missing && summary.isError) {
      return (
        <ProblemError
          title={summary.error.title}
          detail={summary.error.detail}
          status={summary.error.status}
          onRetry={() => void summary.refetch()}
        />
      );
    }
    return (
      <EmptyState icon="book-open" title={`No human summary of ${file} yet.`}>
        <span className="ah-stack" style={{ gap: 10, alignItems: "center" }}>
          <span>
            The hub&apos;s <code>/summarize</code> skill writes a one-minute version of it to{" "}
            <code>{path}</code>. In the Discuss panel, start with &ldquo;Write the human summary of{" "}
            {record}&rdquo;.
          </span>
          <span className="ah-row" style={{ gap: 8 }}>
            {askClaude}
            {readRecord}
          </span>
        </span>
      </EmptyState>
    );
  }

  const note = summary.data;
  // Narrowed above: listed, fetched and not an error.
  if (!note) return null;
  const state = summaryState(note, source.data);
  const written = fieldText(note, "written_at");
  // `../spec.md#goals` opens the record itself at that heading, in this tab.
  const localLink = (href: string): LocalLink | null => {
    const [target = "", fragment] = href.split("#", 2);
    if (target !== `../${file}` && target !== file) return null;
    return {
      href: `#${fragment ?? ""}`,
      open: () => {
        onReadRecord(fragment);
      },
    };
  };
  return (
    <div className="ah-stack" style={{ gap: 14 }}>
      {state === "stale" ? (
        <Banner tone="warning" boxed>
          <b>{file} changed after this summary was written.</b> It may miss or misstate the latest
          changes; read the full record, or ask Claude to update the summary.
          <span className="ah-row" style={{ gap: 8, marginTop: 8 }}>
            {askClaude}
            {readRecord}
          </span>
        </Banner>
      ) : (
        <p className="ah-small ah-muted ah-summary-meta">
          Summary written by Claude from {file}
          {written ? `, ${written}` : ""}
          {state === "fresh" ? " (the current version)" : ""}. Every point links to the part of the
          record it comes from.
        </p>
      )}
      <Markdown
        source={note.markdown}
        note={{ project, path: note.path }}
        className="ah-md-readable"
        localLink={localLink}
        onBrainLink={(link) => void navigate(link.route)}
      />
      {state !== "stale" && <div className="ah-row">{readRecord}</div>}
    </div>
  );
}
