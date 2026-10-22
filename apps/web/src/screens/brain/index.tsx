import "./Brain.css";

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Navigate, useParams, useSearchParams } from "react-router";

import {
  AppLink,
  Banner,
  Button,
  EmptyState,
  Icon,
  ProblemError,
  Skeleton,
} from "../../components";
import { useScope } from "../../lib/scope";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { CountCell, KnowledgeProjectIndex, PickFoot } from "../knowledge-index";
import { useProjectNow } from "../project-overview/queries";
import { BRAIN_NOTE_STARTERS } from "../learnings/discussLearning";
import { BrainSearch, NOTE_PATH_ID, focusFirstResult, useSearchTerm } from "./BrainSearch";
import { LINKED_FROM_ID, LinkedFrom, linkedFromLabel } from "./LinkedFrom";
import { NOTE_ORIGIN_ID, NoteOrigin, originFields } from "./NoteOrigin";
import { NoteLink } from "./NoteLink";
import { NoteView } from "./NoteView";
import { useBacklinks, useBrainNote, useBrainTree, useNoteLearnings } from "./queries";
import { INBOX_FOLDER, START_NOTES, buildTree, countNotes, type BrainFolder } from "./tree";

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
      {folder.notes.map((entry) => (
        <li key={entry.path}>
          <NoteLink project={project} path={entry.path} selected={selected} />
        </li>
      ))}
      {folder.folders.map((child) => (
        <FolderItem key={child.path} folder={child} project={project} selected={selected} />
      ))}
    </ul>
  );
}

function FolderItem({
  folder,
  project,
  selected,
}: {
  folder: BrainFolder;
  project: string;
  selected: string;
}) {
  const count = countNotes(folder);
  return (
    <li>
      <details open={selected.startsWith(folder.path)}>
        <summary
          className="ah-brain-folder"
          aria-label={`${folder.name}, ${String(count)} ${count === 1 ? "note" : "notes"}`}
        >
          <span className="ah-mono">{folder.name}/</span>
          <span className="ah-count">{count}</span>
        </summary>
        <Folder folder={folder} project={project} selected={selected} />
      </details>
    </li>
  );
}

function TreeGroup({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <section className="ah-brain-group" aria-labelledby={id}>
      <h2 id={id} className="ah-brain-group-label">
        {label}
      </h2>
      {children}
    </section>
  );
}

function GroupedTree({
  root,
  project,
  selected,
}: {
  root: BrainFolder;
  project: string;
  selected: string;
}) {
  const start = root.notes;
  const folders = root.folders.filter((folder) => folder.name !== INBOX_FOLDER);
  const inbox = root.folders.find((folder) => folder.name === INBOX_FOLDER);
  return (
    <>
      {start.length > 0 && (
        <TreeGroup id="brain-start" label="Start here">
          <ul className="ah-brain-tree" data-root>
            {[...start]
              .sort((a, b) => Number(b.path in START_NOTES) - Number(a.path in START_NOTES))
              .map((entry) => (
                <li key={entry.path}>
                  <NoteLink
                    project={project}
                    path={entry.path}
                    selected={selected}
                    label={START_NOTES[entry.path]}
                  />
                </li>
              ))}
          </ul>
        </TreeGroup>
      )}
      {folders.length > 0 && (
        <TreeGroup id="brain-folders" label="Folders">
          <ul className="ah-brain-tree" data-root>
            {folders.map((folder) => (
              <FolderItem key={folder.path} folder={folder} project={project} selected={selected} />
            ))}
          </ul>
        </TreeGroup>
      )}
      {inbox && (
        <TreeGroup id="brain-inbox" label="Inbox · unreviewed">
          <ul className="ah-brain-tree" data-root>
            <FolderItem folder={inbox} project={project} selected={selected} />
          </ul>
          <AppLink
            href={`/knowledge/learnings?scope=${encodeURIComponent(project)}`}
            className="ah-brain-link"
          >
            <Icon name="lightbulb" size="sm" />
            <span>Triage in Learnings</span>
          </AppLink>
        </TreeGroup>
      )}
    </>
  );
}

function typingIn(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

/** The Brain search's query, kept in `?q=` and written with `replace` so typing fills no history. */
function useBrainQuery(): [string, (value: string) => void] {
  const [params, setParams] = useSearchParams();
  const setQuery = (value: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value === "") next.delete("q");
        else next.set("q", value);
        return next;
      },
      { replace: true },
    );
  };
  return [params.get("q") ?? "", setQuery];
}

/** The search field's bound: the knowledge route's longest query. */
const MAX_QUERY_CHARS = 500;

function BrainTreePanel({ project, selected }: { project: string; selected: string }) {
  const tree = useBrainTree(project);
  const [query, setQuery] = useBrainQuery();
  const [term, searchNow] = useSearchTerm(query.trim());
  const fieldRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.defaultPrevented || typingIn(event.target)) return;
      event.preventDefault();
      fieldRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);
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
  if (entries.length === 0) {
    return (
      <EmptyState icon="library" title="No brain in this hub" command="./hub sync">
        This reads brain/ in the hub. Run ./hub sync to create the skeleton.
      </EmptyState>
    );
  }
  return (
    <div ref={panelRef} className="ah-stack" style={{ gap: 12 }}>
      <div className="ah-search">
        <Icon name="search" size="sm" />
        <input
          ref={fieldRef}
          type="search"
          className="ah-input"
          aria-label="Search brain notes and repo docs"
          placeholder="Search notes and repo docs"
          maxLength={MAX_QUERY_CHARS}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape" && query !== "") {
              event.preventDefault();
              event.stopPropagation();
              setQuery("");
            } else if (event.key === "Enter") {
              event.preventDefault();
              searchNow();
            } else if (event.key === "ArrowDown" && focusFirstResult(panelRef.current)) {
              event.preventDefault();
            }
          }}
        />
      </div>
      {(truncated || skipped > 0) && (
        <Banner tone="warning">
          {truncated && "The listing stopped at its limit: some notes are not shown. "}
          {skipped > 0 &&
            `${String(skipped)} ${skipped === 1 ? "entry was" : "entries were"} skipped (unreadable or past a limit).`}
        </Banner>
      )}
      {query.trim() === "" ? (
        <GroupedTree root={buildTree(entries)} project={project} selected={selected} />
      ) : (
        <BrainSearch
          project={project}
          entries={entries}
          query={query}
          term={term}
          selected={selected}
          field={fieldRef}
          onClear={() => {
            setQuery("");
            fieldRef.current?.focus();
          }}
        />
      )}
    </div>
  );
}

/** Scrolls the note column's section headed `id` into view and moves the focus to its heading. */
function jumpTo(id: string) {
  const heading = document.getElementById(id);
  const still =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  heading?.scrollIntoView({ block: "start", behavior: still ? "auto" : "smooth" });
  heading?.focus({ preventScroll: true });
}

/** The note header's in-page buttons to the sections after the body (AGH-393). */
function NoteJumps({ total }: { total: number | undefined }) {
  const notes = total === undefined ? "" : `, ${String(total)} ${total === 1 ? "note" : "notes"}`;
  return (
    <span className="ah-row ah-brain-jumps" style={{ gap: 4 }}>
      <Button
        size="sm"
        variant="ghost"
        aria-label="Go to Where this note came from"
        onClick={() => {
          jumpTo(NOTE_ORIGIN_ID);
        }}
      >
        Where it came from
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`Go to Linked from${notes}`}
        onClick={() => {
          jumpTo(LINKED_FROM_ID);
        }}
      >
        {linkedFromLabel(total)}
      </Button>
    </span>
  );
}

/**
 * A project's Brain (D3, AC-201.38): the tree of its notes beside the selected note, `index.md`
 * by default. The URL `projects/:project/brain/<path>` names the note, so deep links work.
 */
export function BrainScreen() {
  const { project = "", "*": rest = "" } = useParams();
  const path = rest === "" ? DEFAULT_NOTE : rest;
  const [params] = useSearchParams();
  // The note, its backlinks and its learnings are asked for together; the sections after the
  // body show only for a note that loaded (not a 404 or a failure).
  const note = useBrainNote(project, path).data;
  const backlinks = useBacklinks(project, path);
  const learnings = useNoteLearnings(project, path);
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
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: project, href: `/projects/${encodeURIComponent(project)}` },
          { label: "Brain" },
        ]}
      />
      <div className="ah-stack" style={{ gap: 4 }}>
        <h1 className="ah-h1">Brain</h1>
        <p className="ah-muted" style={{ margin: 0 }}>
          What {project}&apos;s agents know, read from brain/ in its hub.
        </p>
      </div>
      <div className="ah-brain-layout">
        <nav aria-label="Brain notes" className="ah-card ah-pad">
          <BrainTreePanel project={project} selected={path} />
        </nav>
        <article
          aria-label={path}
          className="ah-card ah-pad ah-stack ah-brain-note"
          style={{ gap: 12 }}
        >
          <div className="ah-row ah-brain-note-head" style={{ gap: 8 }}>
            <Icon name="file-text" size="sm" />
            <span id={NOTE_PATH_ID} className="ah-mono ah-small" tabIndex={-1}>
              brain/{path}
            </span>
            {note && <NoteJumps total={backlinks.data?.total} />}
            <span className="ah-grow" />
            <DiscussButton />
          </div>
          <div key={path} className="ah-stack" style={{ gap: 16 }}>
            <NoteView
              project={project}
              path={path}
              hiddenFields={note ? originFields(note.frontmatter) : undefined}
            />
            {note && (
              <>
                <NoteOrigin frontmatter={note.frontmatter} learnings={learnings} />
                <LinkedFrom
                  project={project}
                  path={path}
                  query={params.get("q")}
                  backlinks={backlinks}
                />
              </>
            )}
          </div>
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
    retry: () => void tree.refetch(),
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

function InboxFoot({ project }: { project: string }) {
  const counts = useBrainCounts(project);
  if (counts.pending) return null;
  if (counts.error !== null) {
    return (
      <PickFoot tone="error" onRetry={counts.retry}>
        {counts.error}.
      </PickFoot>
    );
  }
  if (counts.inbox === 0) return <PickFoot tone="quiet">Inbox empty</PickFoot>;
  return (
    <PickFoot
      tone="attention"
      icon="sprout"
      href={`/knowledge/learnings?scope=${encodeURIComponent(project)}`}
      label={`${String(counts.inbox)} to triage in Learnings for ${project}`}
    >
      {counts.inbox} to triage in Learnings
    </PickFoot>
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
        Current focus: {first.text}
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
      tip="To come straight here, choose a project in the top bar."
      href={brainHome}
      lead={(project) => <FocusCell project={project.name} />}
      figures={[
        {
          id: "notes",
          label: "Notes",
          render: (project) => <BrainCountCell project={project.name} count="notes" />,
        },
        {
          id: "features",
          label: "Features",
          hint: "Feature records under brain/features/.",
          render: (project) => <BrainCountCell project={project.name} count="features" />,
        },
        {
          id: "decisions",
          label: "Decisions",
          render: (project) => <BrainCountCell project={project.name} count="decisions" />,
        },
        {
          id: "learnings",
          label: "Learnings",
          render: (project) => <BrainCountCell project={project.name} count="learnings" />,
        },
      ]}
      foot={(project) => <InboxFoot project={project.name} />}
    />
  );
}
