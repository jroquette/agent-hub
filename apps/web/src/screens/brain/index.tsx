import "./Brain.css";

import { Link, Navigate, useParams } from "react-router";

import { AppLink, Banner, Icon, ProblemError, Skeleton } from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { useScope } from "../../lib/scope";
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { CountCell, KnowledgeProjectIndex } from "../knowledge-index";
import { useProjectNow } from "../project-overview/queries";
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

/** One project's brain, counted by top folder for the All-projects index. */
function useBrainCounts(project: string) {
  const tree = useBrainTree(project);
  const paths = (tree.data?.entries ?? []).map((entry) => entry.path);
  const under = (folder: string) => paths.filter((path) => path.startsWith(`${folder}/`));
  const features = new Set(
    under("features").flatMap((path) => {
      const slug = path.split("/")[1];
      return slug !== undefined && path.split("/").length > 2 ? [slug] : [];
    }),
  );
  const incomplete =
    tree.data && (tree.data.truncated || tree.data.skipped > 0)
      ? "The listing stopped at its limit or skipped entries: some notes are not counted."
      : null;
  return {
    pending: tree.isPending,
    error: tree.isError ? `Could not read this brain: ${tree.error.title}` : null,
    incomplete,
    notes: paths.length,
    features: features.size,
    decisions: under("decisions").length,
    learnings: under("learnings").length,
    inbox: under("_inbox").length,
  };
}

type BrainCount = "notes" | "features" | "decisions" | "learnings";

function BrainCountCell({ project, count }: { project: string; count: BrainCount }) {
  const counts = useBrainCounts(project);
  return (
    <CountCell
      {...counts}
      incomplete={count === "notes" ? counts.incomplete : null}
      value={counts[count]}
    />
  );
}

function InboxCell({ project }: { project: string }) {
  const counts = useBrainCounts(project);
  if (counts.pending || counts.error !== null || counts.inbox === 0) {
    return (
      <CountCell {...counts} incomplete={null} value={<span className="ah-muted">None</span>} />
    );
  }
  return (
    <AppLink
      href={`/knowledge/learnings?scope=${encodeURIComponent(project)}`}
      className="ah-row"
      style={{ gap: 4 }}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <Icon name="lightbulb" size="sm" />
      <span>{counts.inbox} to triage</span>
    </AppLink>
  );
}

function FocusCell({ project }: { project: string }) {
  const now = useProjectNow(project);
  if (now.isPending) return <Skeleton lines={1} />;
  const focus = now.isError || now.data.problem ? [] : now.data.focus;
  const first = focus[0];
  if (first === undefined) {
    return <span className="ah-small ah-muted">No current focus recorded</span>;
  }
  return (
    <span className="ah-row ah-small" style={{ gap: 6, minWidth: 0 }}>
      <span
        title={first.text}
        style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
      >
        {first.text}
      </span>
      {focus.length > 1 && (
        <span className="ah-muted" style={{ whiteSpace: "nowrap" }}>
          +{focus.length - 1} more
        </span>
      )}
    </span>
  );
}

/**
 * Knowledge › Brain: with a project in scope it opens that project's Brain; with All projects it
 * lists the projects with what each brain holds, to choose one.
 */
export function BrainPickerScreen() {
  const [scope] = useScope();
  if (scope !== null) return <Navigate to={brainHome(scope)} replace />;
  return (
    <KnowledgeProjectIndex
      title="Brain"
      intro="What each project's hub knows: current focus, decisions, playbooks and feature records. Open a project to read its brain."
      caption="Projects and their brains"
      emptyLine="Register a hub to read its brain."
      tip="Tip: pick a project in the scope switcher to open its brain directly."
      href={brainHome}
      columns={[
        {
          id: "focus",
          label: "Current focus",
          render: (project) => <FocusCell project={project.name} />,
        },
        {
          id: "notes",
          label: "Notes",
          align: "right",
          width: 90,
          render: (project) => <BrainCountCell project={project.name} count="notes" />,
        },
        {
          id: "features",
          label: "Features",
          hint: "Feature records under brain/features/.",
          align: "right",
          width: 100,
          render: (project) => <BrainCountCell project={project.name} count="features" />,
        },
        {
          id: "decisions",
          label: "Decisions",
          align: "right",
          width: 100,
          render: (project) => <BrainCountCell project={project.name} count="decisions" />,
        },
        {
          id: "learnings",
          label: "Learnings",
          align: "right",
          width: 100,
          render: (project) => <BrainCountCell project={project.name} count="learnings" />,
        },
        {
          id: "inbox",
          label: "Inbox",
          hint: "Unreviewed proposals in brain/_inbox/; nothing there is authoritative.",
          width: 140,
          render: (project) => <InboxCell project={project.name} />,
        },
      ]}
    />
  );
}
