import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";

import {
  Banner,
  Button,
  ProblemError,
  SKELETON_DELAY_MS,
  Skeleton,
  useDelayed,
} from "../../components";
import type { ApiData, ApiProblem } from "../../lib/api";
import { KnowledgeRow } from "./KnowledgeRow";
import { NoteLink } from "./NoteLink";
import { hasWord, useKnowledgeSearch } from "./queries";
import { matchNotes, noteName } from "./tree";

/** The path matches shown before "Show all" (AM-1, amending AC-270.10). */
export const PATHS_SHOWN = 8;
/** The route's default limit: at that many results the list says it shows the best only. */
export const TEXT_LIMIT = 50;
/** Spec 01's palette debounce, kept by the Brain's text search. */
export const BRAIN_SEARCH_DEBOUNCE_MS = 120;
/** The focus moves to the note instead of staying on the result when the note is below it. */
const STACKED = "(max-width: 899px)";
/** The id of the note column's path line, which a result opened on a narrow screen focuses. */
export const NOTE_PATH_ID = "brain-note-path";
const SAY_SEARCHING_MS = 1_000;
const SAY_SLOW_MS = 2_000;

type KnowledgeSearch = ApiData<"/api/v1/projects/{project}/knowledge/search">;

/** The trimmed query, sent `BRAIN_SEARCH_DEBOUNCE_MS` after the last key; `flush` sends it now. */
export function useSearchTerm(text: string): [string, () => void] {
  const [term, setTerm] = useState(text);
  useEffect(() => {
    if (term === text) return undefined;
    const timer = setTimeout(() => {
      setTerm(text);
    }, BRAIN_SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [text, term]);
  return [
    term,
    () => {
      setTerm(text);
    },
  ];
}

/**
 * Whether the loading skeleton shows: only once `pending` has lasted the skeleton delay, then for
 * at least that long, so a fast answer never flashes it and a slow one never blinks it away.
 */
function useSkeleton(pending: boolean): boolean {
  const [shownAt, setShownAt] = useState<number | null>(null);
  useEffect(() => {
    if (pending && shownAt === null) {
      const timer = setTimeout(() => {
        setShownAt(Date.now());
      }, SKELETON_DELAY_MS);
      return () => {
        clearTimeout(timer);
      };
    }
    if (!pending && shownAt !== null) {
      const timer = setTimeout(
        () => {
          setShownAt(null);
        },
        Math.max(0, shownAt + SKELETON_DELAY_MS - Date.now()),
      );
      return () => {
        clearTimeout(timer);
      };
    }
    return undefined;
  }, [pending, shownAt]);
  return shownAt !== null;
}

function plural(count: number, one: string, many: string): string {
  return `${String(count)} ${count === 1 ? one : many}`;
}

/** On a stacked layout the opened note is out of view: bring its path line to the reader. */
function focusNoteWhenStacked() {
  if (typeof window.matchMedia !== "function" || !window.matchMedia(STACKED).matches) return;
  requestAnimationFrame(() => {
    const line = document.getElementById(NOTE_PATH_ID);
    line?.scrollIntoView({ block: "start" });
    line?.focus();
  });
}

function Section({
  label,
  busy,
  children,
}: {
  label: string;
  busy?: boolean | undefined;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section className="ah-brain-group" aria-labelledby={id} aria-busy={busy ? true : undefined}>
      <h2 id={id} className="ah-brain-group-label">
        {label}
      </h2>
      {children}
    </section>
  );
}

function PathMatches({
  project,
  text,
  matches,
  selected,
  query,
}: {
  project: string;
  text: string;
  matches: readonly { path: string }[];
  selected: string;
  query: string;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? matches : matches.slice(0, PATHS_SHOWN);
  return (
    <Section label={`Paths matching “${text}” · ${String(matches.length)}`}>
      <ul className="ah-brain-tree" data-root aria-label="Matching notes">
        {shown.map((entry) => (
          <li key={entry.path}>
            <NoteLink
              project={project}
              path={entry.path}
              selected={selected}
              folder={entry.path.slice(0, entry.path.length - noteName(entry.path).length)}
              query={query}
              searchRow
            />
          </li>
        ))}
      </ul>
      {matches.length > PATHS_SHOWN && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setAll(!all);
          }}
        >
          {all
            ? `Show the first ${String(PATHS_SHOWN)}`
            : `Show all ${String(matches.length)} path matches`}
        </Button>
      )}
    </Section>
  );
}

/** The text section while its answer is pending: three skeleton rows, then a word on slowness. */
function PendingText({ text }: { text: string }) {
  const searching = useDelayed(SAY_SEARCHING_MS);
  const slow = useDelayed(SAY_SLOW_MS);
  return (
    <Section label={`Text matching “${text}”`} busy>
      <div className="ah-stack" style={{ gap: 8 }} aria-hidden="true">
        {[0, 1, 2].map((row) => (
          <div key={row} className="ah-know-skeleton">
            <Skeleton width="70%" delay={0} />
            <Skeleton width="90%" height={10} delay={0} />
            <Skeleton width="40%" height={10} delay={0} />
          </div>
        ))}
      </div>
      {slow && (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Reading the hub&apos;s notes for this search. A first search after an update can take a
          few seconds.
        </p>
      )}
      <span className="ah-sr" role="status">
        {searching ? "Searching notes" : ""}
      </span>
    </Section>
  );
}

function FailedText({
  text,
  error,
  onRetry,
}: {
  text: string;
  error: ApiProblem;
  onRetry: () => void;
}) {
  const unreachable = error.status === 0;
  return (
    <Section label={`Text matching “${text}”`}>
      <ProblemError
        compact
        title={unreachable ? "The app's server is not responding" : error.title}
        detail={unreachable ? "Check that hub web is still running, then try again." : error.detail}
        status={error.status || undefined}
        onRetry={onRetry}
      />
    </Section>
  );
}

function Skipped({ skipped }: { skipped: KnowledgeSearch["skipped"] }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  return (
    <div className="ah-stack" style={{ gap: 4 }}>
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        {plural(skipped.length, "file was", "files were")} not searched (a secret rule matched, too
        large, or unreadable).
      </p>
      <Button
        size="sm"
        variant="ghost"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => {
          setOpen(!open);
        }}
      >
        Show which
      </Button>
      {open && (
        <ul id={listId} className="ah-know-skipped">
          {skipped.map((file) => (
            <li key={file.path} className="ah-mono ah-small">
              {file.path} · {file.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TextMatches({
  project,
  term,
  found,
  selected,
  query,
}: {
  project: string;
  term: string;
  found: KnowledgeSearch;
  selected: string;
  query: string;
}) {
  const capped = found.results.length >= TEXT_LIMIT;
  const count = capped ? `${String(TEXT_LIMIT)} best` : String(found.results.length);
  return (
    <Section label={`Text matching “${term}” · ${count}`}>
      {found.warnings.map((warning) => (
        <Banner key={warning} tone="info" live={false}>
          {warning}
        </Banner>
      ))}
      <ul className="ah-know-list">
        {found.results.map((result) => (
          <KnowledgeRow
            key={result.path}
            item={result}
            project={project}
            query={query}
            selected={selected}
            onOpen={focusNoteWhenStacked}
          />
        ))}
      </ul>
      {found.skipped.length > 0 && <Skipped skipped={found.skipped} />}
      {capped && (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Showing the {TEXT_LIMIT} best matches. Add a word to narrow the search.
        </p>
      )}
    </Section>
  );
}

function NothingMatches({ text, onClear }: { text: string; onClear: () => void }) {
  return (
    <div className="ah-stack" style={{ gap: 8, alignItems: "flex-start" }}>
      <p className="ah-small" style={{ margin: 0 }}>
        Nothing matches “{text}”.
      </p>
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        {/\s/.test(text)
          ? "Every word must appear: try fewer words."
          : "No note path or text contains it."}
      </p>
      <Button size="sm" variant="ghost" onClick={onClear}>
        Clear search
      </Button>
    </div>
  );
}

/** What the live line says once a search has answered, or null while there is nothing to say. */
function liveLine(text: string, paths: number, results: number | null): string {
  if (paths === 0 && (results ?? 0) === 0) return `Nothing matches “${text}”.`;
  if (results === null) return `${plural(paths, "path match", "path matches")} for “${text}”.`;
  return `${plural(paths, "path", "paths")} and ${plural(results, "text match", "text matches")} for “${text}”.`;
}

export interface BrainSearchProps {
  project: string;
  entries: readonly { path: string }[];
  /** The field's text, as `?q=` holds it. */
  query: string;
  /** The trimmed query the text search was sent for (debounced). */
  term: string;
  selected: string;
  field: RefObject<HTMLInputElement | null>;
  onClear: () => void;
}

/**
 * The Brain's search (AGH-393): the notes whose path holds the text, at once, then the AGH-391
 * index's text matches in rank order. Its rows are moved between with the arrows and j/k.
 */
export function BrainSearch({
  project,
  entries,
  query,
  term,
  selected,
  field,
  onClear,
}: BrainSearchProps) {
  const text = query.trim();
  const asked = hasWord(term);
  const search = useKnowledgeSearch(project, term, { enabled: asked });
  const results = useRef<HTMLDivElement>(null);
  const wordless = !hasWord(text) || (search.isError && search.error.status === 400);
  const settled = term === text;
  const pending = !wordless && (!settled || search.isPending);
  const skeleton = useSkeleton(pending);
  const paths = matchNotes(entries, text);
  const found = !pending && settled && search.data ? search.data : null;

  useEffect(() => {
    const list = results.current;
    if (!list) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const rows = [...list.querySelectorAll<HTMLElement>("[data-search-row]")];
      const at = rows.indexOf(event.target as HTMLElement);
      if (at < 0) return;
      if (event.key === "ArrowDown" || event.key === "j") {
        event.preventDefault();
        rows[at + 1]?.focus();
      } else if (event.key === "ArrowUp" || event.key === "k") {
        event.preventDefault();
        (at === 0 ? field.current : rows[at - 1])?.focus();
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        field.current?.focus();
      }
    };
    list.addEventListener("keydown", onKey);
    return () => {
      list.removeEventListener("keydown", onKey);
    };
  }, [field]);

  let textPart = null;
  if (wordless) {
    textPart = (
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        Type a letter or a digit to search the text of notes.
      </p>
    );
  } else if (pending || skeleton) {
    textPart = skeleton ? <PendingText key={text} text={text} /> : null;
  } else if (search.isError) {
    textPart = (
      <FailedText text={term} error={search.error} onRetry={() => void search.refetch()} />
    );
  } else if (found && found.results.length > 0) {
    textPart = (
      <TextMatches project={project} term={term} found={found} selected={selected} query={query} />
    );
  } else if (paths.length === 0) {
    textPart = <NothingMatches text={text} onClear={onClear} />;
  }
  const said =
    pending || skeleton || (search.isError && !wordless)
      ? ""
      : liveLine(text, paths.length, wordless ? null : (found?.results.length ?? 0));
  return (
    <div ref={results} className="ah-stack" style={{ gap: 12 }}>
      {paths.length > 0 && (
        <PathMatches
          key={text}
          project={project}
          text={text}
          matches={paths}
          selected={selected}
          query={query}
        />
      )}
      {textPart}
      <span className="ah-sr" role="status">
        {said}
      </span>
    </div>
  );
}

/** Moves focus from the field to the first result, path matches first. */
export function focusFirstResult(panel: HTMLElement | null): boolean {
  const first = panel?.querySelector<HTMLElement>("[data-search-row]");
  first?.focus();
  return first !== undefined && first !== null;
}
