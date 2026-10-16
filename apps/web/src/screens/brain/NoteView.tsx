import "./readable.css";

import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router";

import type { components } from "../../api/schema";
import type { MarkdownProps } from "../../components";
import {
  Banner,
  EmptyState,
  Icon,
  Markdown,
  ProblemError,
  Skeleton,
  markdownHeadings,
  plainHeadingText,
} from "../../components";
import { anchorId, tocAnchors } from "../../lib/brainLinks";
import { AnchorLink } from "../skills/BodyView";
import { useBrainNote } from "./queries";
import { codeReference, readableFields, readableNote } from "./readable";

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

export interface NoteViewProps {
  project: string;
  /** The note's path under `brain/`, e.g. `features/x/plan.md`. */
  path: string;
  /** What a missing note (404) says; defaults to "No note <path> in the <project> brain." */
  missing?: string;
  /**
   * How the note is shown: `agent` (default) is the file as the agents read it, every reference
   * and the frontmatter as written; `readable` is the same file laid out for a person.
   */
  view?: NoteViewMode | undefined;
}

export type NoteViewMode = "readable" | "agent";

type Note = components["schemas"]["BrainNote"];

/** The note for a person: its fields in words, a contents list, and the agents' references compact. */
function ReadableBody({ data, onBrainLink }: { data: Note; onBrainLink: OnBrainLink }) {
  const { source, shorthand } = readableNote(data.markdown);
  const fields = readableFields(data.frontmatter);
  const sections = tocAnchors(markdownHeadings(source), plainHeadingText).filter(
    (entry) => entry.anchor !== null && entry.level === 2,
  );
  return (
    <div className="ah-readable">
      {sections.length >= 3 && (
        <nav className="ah-readable-toc" aria-label="Contents">
          <p className="ah-overline" style={{ margin: "0 0 6px" }}>
            Contents
          </p>
          <ol>
            {sections.map((entry) => (
              <li key={entry.anchor}>
                <AnchorLink anchor={entry.anchor ?? ""}>{plainHeadingText(entry.text)}</AnchorLink>
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="ah-readable-main">
        {fields.length > 0 && (
          <dl className="ah-readable-fields" aria-label="About this note">
            {fields.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{valueText(value)}</dd>
              </div>
            ))}
          </dl>
        )}
        <Markdown
          source={source}
          note={{ project: data.project, path: data.path }}
          onBrainLink={onBrainLink}
          className="ah-md-readable"
          inlineCode={(code) => {
            const ref = codeReference(code, shorthand);
            if (!ref) return null;
            return (
              <span className="ah-md-ref" title={ref.title}>
                <Icon name="file-text" size="sm" />
                {ref.label}
              </span>
            );
          }}
        />
      </div>
    </div>
  );
}

type OnBrainLink = NonNullable<MarkdownProps["onBrainLink"]>;

/**
 * One brain note rendered with the safe `Markdown` (D3, AC-201.35/36): frontmatter as chips, links
 * to other notes open in the app, and the URL's `#anchor` scrolls to its heading once loaded.
 */
export function NoteView({ project, path, missing, view = "agent" }: NoteViewProps) {
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
  const openNote: OnBrainLink = (link) => void navigate(link.route);
  if (view === "readable" && !data.frontmatter_problem) {
    return <ReadableBody data={data} onBrainLink={openNote} />;
  }
  const fields = Object.entries(data.frontmatter);
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      {data.frontmatter_problem && (
        <Banner tone="warning" boxed>
          The frontmatter could not be read: {data.frontmatter_problem}. The whole file is shown.
        </Banner>
      )}
      {fields.length > 0 && (
        <ul
          aria-label="Frontmatter"
          className="ah-row ah-wrap"
          style={{ gap: 6, listStyle: "none", margin: 0, padding: 0 }}
        >
          {fields.map(([key, value]) => (
            <li key={key} className="ah-fm-chip">
              <span className="ah-subtle">{key}:</span> {valueText(value)}
            </li>
          ))}
        </ul>
      )}
      <Markdown source={data.markdown} note={{ project, path }} onBrainLink={openNote} />
    </div>
  );
}
