import type { FocusEventHandler, KeyboardEventHandler } from "react";
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
  onOpen?: (() => void) | undefined;
  /** A row of the tree: its path, which the tree's keys find it by (AGH-617). */
  treeRow?: string | undefined;
  /** The tree's roving tab stop: 0 on its current row, -1 on the others. */
  tabIndex?: number | undefined;
  onFocus?: FocusEventHandler<HTMLAnchorElement> | undefined;
  onKeyDown?: KeyboardEventHandler<HTMLAnchorElement> | undefined;
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
  onOpen,
  treeRow,
  tabIndex,
  onFocus,
  onKeyDown,
}: NoteLinkProps) {
  return (
    <Link
      to={withBrainQuery(brainRoute(project, path), query ?? null)}
      className="ah-brain-link"
      aria-current={path === selected ? "page" : undefined}
      title={path}
      data-search-row={searchRow ? "" : undefined}
      data-tree-row={treeRow}
      tabIndex={tabIndex}
      onClick={onOpen}
      onFocus={onFocus}
      onKeyDown={onKeyDown}
    >
      <Icon name="file-text" size="sm" />
      <span className="ah-brain-link-name">{label ?? noteName(path)}</span>
      {folder && <span className="ah-brain-link-folder">{folder}</span>}
    </Link>
  );
}
