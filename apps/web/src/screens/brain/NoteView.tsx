import { useEffect } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";

import type { components } from "../../api/schema";
import { Banner, EmptyState, Markdown, ProblemError, Skeleton } from "../../components";
import { anchorId } from "../../lib/brainLinks";
import { useBrainNote } from "./queries";

type FrontmatterValue = components["schemas"]["FrontmatterValue"];

/** The `#fragment` of the URL as written in the note, or null when there is none or it is malformed. */
export function fragmentOf(hash: string): string | null {
  if (hash.length <= 1) return null;
  try {
    return decodeURIComponent(hash.slice(1));
  } catch {
    return null;
  }
}

function valueText(value: FrontmatterValue): string {
  return Array.isArray(value) ? value.join(", ") : value;
}

/** Past this length a value no longer fits a chip; it gets a full-width row that wraps. */
const CHIP_MAX = 48;

export interface NoteViewProps {
  project: string;
  /** The note's path under `brain/`, e.g. `features/x/plan.md`. */
  path: string;
  /** What a missing note (404) says; defaults to "No note <path> in the <project> brain." */
  missing?: string;
  /**
   * Fold the frontmatter into a closed "Details" disclosure instead of showing it above the body,
   * with `lead` (e.g. the note's path) first inside it. For views where the body is the point.
   */
  foldFrontmatter?: { lead?: ReactNode };
}

/**
 * One brain note rendered with the safe `Markdown` (D3, AC-201.35/36): frontmatter as chips, links
 * to other notes open in the app, and the URL's `#anchor` scrolls to its heading once loaded.
 */
export function NoteView({ project, path, missing, foldFrontmatter }: NoteViewProps) {
  const note = useBrainNote(project, path);
  const navigate = useNavigate();
  const { hash } = useLocation();
  const loaded = note.data !== undefined;

  useEffect(() => {
    if (!loaded) return;
    const fragment = fragmentOf(hash);
    if (fragment === null) return;
    document.getElementById(anchorId(fragment))?.scrollIntoView({ block: "start" });
  }, [loaded, hash, path]);

  if (note.isError) {
    const { status, title, detail } = note.error;
    if (status === 404) {
      return (
        <EmptyState icon="file-text" title={missing ?? `No note ${path} in the ${project} brain.`}>
          It may have been moved or removed from the hub.
        </EmptyState>
      );
    }
    if (status === 413) {
      return (
        <ProblemError
          title="This note is too large to show"
          detail={detail ?? "Notes over 256 KiB are not served. Open it in the hub."}
          status={status}
        />
      );
    }
    return (
      <ProblemError
        title={title}
        detail={detail}
        status={status}
        onRetry={() => void note.refetch()}
      />
    );
  }
  if (note.isPending) {
    return (
      <div aria-busy="true" className="ah-stack">
        <Skeleton width={280} height={22} />
        <Skeleton lines={6} />
      </div>
    );
  }

  const data = note.data;
  const fields = Object.entries(data.frontmatter).map(
    ([key, value]) => [key, valueText(value)] as const,
  );
  const chips = fields.filter(([, text]) => text.length <= CHIP_MAX);
  const long = fields.filter(([, text]) => text.length > CHIP_MAX);
  const frontmatter = (
    <>
      {chips.length > 0 && (
        <ul
          aria-label="Frontmatter"
          className="ah-row ah-wrap"
          style={{ gap: 6, listStyle: "none", margin: 0, padding: 0 }}
        >
          {chips.map(([key, text]) => (
            <li key={key} className="ah-fm-chip" title={text}>
              <span className="ah-subtle">{key}:</span> {text}
            </li>
          ))}
        </ul>
      )}
      {long.length > 0 && (
        <dl aria-label="Frontmatter, long fields" className="ah-fm-long">
          {long.map(([key, text]) => (
            <div key={key}>
              <dt className="ah-subtle">{key}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      )}
    </>
  );
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      {data.frontmatter_problem && (
        <Banner tone="warning" boxed>
          The frontmatter could not be read: {data.frontmatter_problem}. The whole file is shown.
        </Banner>
      )}
      {foldFrontmatter ? (
        <details className="ah-note-details">
          <summary>Details</summary>
          <div className="ah-stack" style={{ gap: 8, marginTop: 8 }}>
            {foldFrontmatter.lead}
            {frontmatter}
          </div>
        </details>
      ) : (
        frontmatter
      )}
      <Markdown
        source={data.markdown}
        note={{ project, path }}
        onBrainLink={(link) => void navigate(link.route)}
      />
    </div>
  );
}
