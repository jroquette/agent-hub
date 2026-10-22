import { Link } from "react-router";

import { Icon } from "../../components";
import { brainRoute, withBrainQuery } from "../../lib/brainLinks";
import { noteName } from "./tree";

export interface NoteLinkProps {
  project: string;
  path: string;
  selected: string;
  label?: string | undefined;
  folder?: string | undefined;
  /** The Brain search's query, kept on the link (`?q=`). */
  query?: string | null | undefined;
  /** The row is one of the search's results, which the arrow and j/k keys move between. */
  searchRow?: boolean | undefined;
}

/** A note of the Brain's tree or path matches: its name (and folder), opening it beside. */
export function NoteLink({
  project,
  path,
  selected,
  label,
  folder,
  query,
  searchRow,
}: NoteLinkProps) {
  return (
    <Link
      to={withBrainQuery(brainRoute(project, path), query ?? null)}
      className="ah-brain-link"
      aria-current={path === selected ? "page" : undefined}
      title={path}
      data-search-row={searchRow ? "" : undefined}
    >
      <Icon name="file-text" size="sm" />
      <span className="ah-brain-link-name">{label ?? noteName(path)}</span>
      {folder && <span className="ah-brain-link-folder">{folder}</span>}
    </Link>
  );
}
