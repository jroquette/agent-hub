import { ProblemError, Skeleton, useDelayed } from "../../components";
import { NOTE_PATH_ID } from "./BrainSearch";
import { KnowledgeRow } from "./KnowledgeRow";
import type { useBacklinks } from "./queries";

/** The id of the section's heading, which the note header's jump button focuses. */
export const LINKED_FROM_ID = "brain-linked-from";
/** The route's most items; past it the section says how many more link here. */
const MAX_BACKLINKS = 100;
const SAY_SLOW_MS = 2_000;

/** The header's name of the section: its total once known (`Linked from · 2`). */
export function linkedFromLabel(total: number | undefined): string {
  return total === undefined ? "Linked from" : `Linked from · ${String(total)}`;
}

/** After following a source, the opened note's path line takes the focus (it replaced the link). */
function focusNotePath() {
  requestAnimationFrame(() => {
    const line = document.getElementById(NOTE_PATH_ID);
    line?.scrollIntoView({ block: "start" });
    line?.focus();
  });
}

function Pending() {
  const slow = useDelayed(SAY_SLOW_MS);
  return (
    <>
      <div className="ah-stack" style={{ gap: 8 }} aria-hidden="true">
        {[0, 1].map((row) => (
          <div key={row} className="ah-know-skeleton">
            <Skeleton width="60%" />
            <Skeleton width="80%" height={10} />
          </div>
        ))}
      </div>
      {slow && (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          Reading the hub&apos;s notes to find the links. A first read after an update can take a
          few seconds.
        </p>
      )}
    </>
  );
}

/**
 * "Linked from" (AGH-393, D-linked-from): the notes and repo docs whose links point to the note,
 * sorted by path. A brain source opens its note (keeping `?q=`); one the app cannot open is text.
 */
export function LinkedFrom({
  project,
  path,
  query,
  backlinks,
}: {
  project: string;
  /** The note's path under `brain/`. */
  path: string;
  /** The Brain search's query, kept on each source's link. */
  query: string | null;
  /** The note's backlinks, asked for by the screen as the note opens. */
  backlinks: ReturnType<typeof useBacklinks>;
}) {
  const data = backlinks.data;
  let body;
  if (backlinks.isError) {
    const unreachable = backlinks.error.status === 0;
    body = (
      <ProblemError
        compact
        title={unreachable ? "The app's server is not responding" : backlinks.error.title}
        detail={
          unreachable
            ? "Check that hub web is still running, then try again."
            : backlinks.error.detail
        }
        status={backlinks.error.status || undefined}
        onRetry={() => void backlinks.refetch()}
      />
    );
  } else if (data === undefined) {
    body = <Pending />;
  } else if (data.items.length === 0) {
    body = (
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        No note links here.
      </p>
    );
  } else {
    body = (
      <>
        <ul className="ah-know-list">
          {data.items.map((item) => (
            <KnowledgeRow
              key={item.path}
              item={item}
              project={project}
              query={query}
              selected={path}
              onOpen={focusNotePath}
            />
          ))}
        </ul>
        {data.total > MAX_BACKLINKS && (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            and {data.total - MAX_BACKLINKS} more
          </p>
        )}
      </>
    );
  }
  return (
    <section
      className="ah-note-section"
      aria-labelledby={LINKED_FROM_ID}
      aria-busy={backlinks.isPending ? true : undefined}
    >
      <h2 id={LINKED_FROM_ID} className="ah-h3" tabIndex={-1}>
        {linkedFromLabel(data?.total)}
      </h2>
      {body}
    </section>
  );
}
