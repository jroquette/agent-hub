import "./Brain.css";

import { Link, Navigate, useParams } from "react-router";

import { Banner, EmptyState, Icon, ProblemError, Skeleton } from "../../components";
import { useApi } from "../../lib/api";
import { brainRoute } from "../../lib/brainLinks";
import { useScope } from "../../lib/scope";
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { BRAIN_NOTE_STARTERS } from "../learnings/discussLearning";
import { NoteView } from "./NoteView";
import { useBrainTree } from "./queries";
import { buildTree, noteName, type BrainFolder } from "./tree";

/** The note a project's Brain opens when the URL names none (AC-201.38). */
export const DEFAULT_NOTE = "index.md";

/** The in-app route of a project's Brain, on its default note. */
export function brainHome(project: string): string {
  return `/projects/${encodeURIComponent(project)}/brain`;
}

function Folder({
  folder,
  project,
  selected,
}: {
  folder: BrainFolder;
  project: string;
  selected: string;
}) {
  return (
    <ul className="ah-brain-tree" data-root={folder.path === "" || undefined}>
      {folder.notes.map((entry) => {
        const current = entry.path === selected;
        return (
          <li key={entry.path}>
            <Link
              to={brainRoute(project, entry.path)}
              className="ah-brain-link"
              aria-current={current ? "page" : undefined}
              title={entry.path}
            >
              <Icon name="file-text" size="sm" />
              <span>{noteName(entry.path)}</span>
            </Link>
          </li>
        );
      })}
      {folder.folders.map((child) => (
        <li key={child.path}>
          <details open={selected.startsWith(child.path)}>
            <summary className="ah-mono">{child.name}/</summary>
            <Folder folder={child} project={project} selected={selected} />
          </details>
        </li>
      ))}
    </ul>
  );
}

function BrainTreePanel({ project, selected }: { project: string; selected: string }) {
  const tree = useBrainTree(project);
  if (tree.isError) {
    return (
      <ProblemError
        compact
        title={tree.error.title}
        detail={tree.error.detail}
        status={tree.error.status}
        onRetry={() => void tree.refetch()}
      />
    );
  }
  if (tree.isPending) {
    return (
      <div aria-busy="true">
        <Skeleton lines={8} />
      </div>
    );
  }
  const { entries, truncated, skipped } = tree.data;
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      {(truncated || skipped > 0) && (
        <Banner tone="warning">
          {truncated && "The listing stopped at its limit: some notes are not shown. "}
          {skipped > 0 &&
            `${String(skipped)} ${skipped === 1 ? "entry was" : "entries were"} skipped (unreadable or past a limit).`}
        </Banner>
      )}
      {entries.length === 0 ? (
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          This brain has no notes yet.
        </p>
      ) : (
        <Folder folder={buildTree(entries)} project={project} selected={selected} />
      )}
    </div>
  );
}

/**
 * A project's Brain (D3, AC-201.38): the tree of its notes beside the selected note, `index.md`
 * by default. The URL `projects/:project/brain/<path>` names the note, so deep links work.
 */
export function BrainScreen() {
  const { project = "", "*": rest = "" } = useParams();
  const path = rest === "" ? DEFAULT_NOTE : rest;
  useDiscussTarget({
    key: `brain:${project}:${path}`,
    project,
    kind: "Note",
    title: path,
    path: `brain/${path}`,
    starters: BRAIN_NOTE_STARTERS,
  });
  return (
    <div className="ah-page" style={{ gap: 16 }}>
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 className="ah-h1">Brain</h1>
        <span className="ah-small ah-muted">{project}</span>
      </div>
      <div className="ah-brain-layout">
        <nav aria-label="Brain notes" className="ah-card ah-pad">
          <BrainTreePanel project={project} selected={path} />
        </nav>
        <article aria-label={path} className="ah-card ah-pad ah-stack" style={{ gap: 12 }}>
          <div className="ah-row" style={{ gap: 8 }}>
            <Icon name="file-text" size="sm" />
            <span className="ah-mono ah-small">brain/{path}</span>
            <span className="ah-grow" />
            <DiscussButton />
          </div>
          <NoteView key={path} project={project} path={path} />
        </article>
      </div>
    </div>
  );
}

/**
 * Knowledge › Brain: with a project in scope it opens that project's Brain; with All projects it
 * lists the projects to choose one.
 */
export function BrainPickerScreen() {
  const [scope] = useScope();
  const projects = useApi("/api/v1/projects", undefined, { enabled: scope === null });
  if (scope !== null) return <Navigate to={brainHome(scope)} replace />;
  let body;
  if (projects.isError) {
    body = (
      <ProblemError
        title={projects.error.title}
        detail={projects.error.detail}
        status={projects.error.status}
        onRetry={() => void projects.refetch()}
      />
    );
  } else if (projects.isPending) {
    body = <Skeleton lines={3} />;
  } else if (projects.data.items.length === 0) {
    body = (
      <div className="ah-card">
        <EmptyState icon="book-open" title="No projects yet.">
          Register a hub in Settings to read its brain.
        </EmptyState>
      </div>
    );
  } else {
    body = (
      <ul
        aria-label="Projects"
        className="ah-card ah-pad ah-stack"
        style={{ listStyle: "none", margin: 0, gap: 4 }}
      >
        {projects.data.items.map((project) => (
          <li key={project.name}>
            <Link to={brainHome(project.name)} className="ah-brain-link">
              <Icon name="book-open" size="sm" />
              <span>{project.name}</span>
            </Link>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="ah-page" style={{ gap: 16 }}>
      <h1 className="ah-h1">Brain</h1>
      <p className="ah-muted" style={{ margin: 0 }}>
        Pick a project to read its brain, or choose one in the project scope.
      </p>
      {body}
    </div>
  );
}
