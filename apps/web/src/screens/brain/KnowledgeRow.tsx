import { useId } from "react";
import type { MouseEvent } from "react";
import { Link } from "react-router";

import { ExternalLabel, Icon, PathText, Tooltip } from "../../components";
import {
  BRAIN_PREFIX,
  NOT_OPENED_HERE,
  UNSERVED_NOTE_REASON,
  brainRoute,
  isServedNote,
  withBrainQuery,
} from "../../lib/brainLinks";

/** Why a repo doc is listed but not opened (D-results-web). */
export const REPO_DOC_TOOLTIP = "Repo docs are not opened in the app";
const EXTERNAL = "agent-from-external";
/** The path's room in the 280 px panel, in characters. */
const PATH_CHARS = 34;

/** A document the index holds: a search result, or (without a snippet) a backlink's source. */
export interface KnowledgeItem {
  path: string;
  kind: string;
  title: string;
  status?: string | null | undefined;
  provenance?: string | null | undefined;
  snippet?: string | null | undefined;
}

export interface KnowledgeRowProps {
  item: KnowledgeItem;
  project: string;
  /** The Brain search's query, kept on the note's link (`?q=`). */
  query?: string | null | undefined;
  /** The note open beside the list, as the URL names it (without `brain/`). */
  selected: string;
  onOpen?: ((event: MouseEvent<HTMLAnchorElement>) => void) | undefined;
}

function fileName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/**
 * The kind line: `decision · accepted`; the inbox is unreviewed; a repo doc and a refused note
 * (AM-8) say they stay shut.
 */
function kindLine(item: KnowledgeItem, repoDoc: boolean, served: boolean): string {
  const parts =
    item.kind === "inbox"
      ? ["inbox", "unreviewed"]
      : [item.kind, ...(item.status ? [item.status] : [])];
  if (repoDoc) parts.push(`repo doc, ${NOT_OPENED_HERE}`);
  else if (!served) parts.push(NOT_OPENED_HERE);
  return parts.join(" · ");
}

/**
 * One document of the knowledge index in a narrow column (AGH-393's `new` pattern): the title,
 * the path in mono, the kind (and status), and the snippet when there is one. A brain note is one
 * link named by its title, the rest its description; a repo doc is text with the reason in words.
 */
export function KnowledgeRow({ item, project, query, selected, onOpen }: KnowledgeRowProps) {
  const id = useId();
  const repoDoc = !item.path.startsWith(BRAIN_PREFIX);
  const note = item.path.slice(BRAIN_PREFIX.length);
  const served = !repoDoc && isServedNote(note);
  const title = item.title || fileName(item.path);
  const details = (
    <span id={`${id}-details`} className="ah-know-details">
      <PathText path={item.path} max={PATH_CHARS} dimDir />
      <span className="ah-know-kind">
        {kindLine(item, repoDoc, served)}
        {item.provenance === EXTERNAL && <ExternalLabel />}
      </span>
      {item.snippet && <span className="ah-know-snippet">{item.snippet}</span>}
    </span>
  );
  const heading = (icon: "book" | "file-text") => (
    <span className="ah-know-title">
      <Icon name={icon} size="sm" />
      <span className="ah-know-title-text" title={title}>
        {title}
      </span>
    </span>
  );
  if (repoDoc || !served) {
    return (
      <li className="ah-know-row" data-search-row="" tabIndex={-1} aria-describedby={`${id}-tip`}>
        <Tooltip label={repoDoc ? REPO_DOC_TOOLTIP : UNSERVED_NOTE_REASON} id={`${id}-tip`} block>
          <span className="ah-know-body">
            {heading(repoDoc ? "book" : "file-text")}
            {details}
          </span>
        </Tooltip>
      </li>
    );
  }
  return (
    <li>
      <Link
        to={withBrainQuery(brainRoute(project, note), query ?? null)}
        className="ah-know-row ah-know-body"
        data-search-row=""
        aria-current={note === selected ? "page" : undefined}
        aria-label={title}
        aria-describedby={`${id}-details`}
        onClick={onOpen}
      >
        {heading("file-text")}
        {details}
      </Link>
    </li>
  );
}
