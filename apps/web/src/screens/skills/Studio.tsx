/* The Studio: create a skill, agent or hook with Claude, or change one the hub has. A conversation
 * on the left (a session `hub web` drives in the hub folder), the draft it writes previewed live on
 * the right, and Publish once the owner has reviewed it. Nothing is published before that click. */
import "./Skills.css";
import "./SkillDetail.css";
import "./Studio.css";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router";

import {
  AppLink,
  Banner,
  Button,
  ConfirmDialog,
  EmptyState,
  Icon,
  Markdown,
  SegmentedControl,
  Skeleton,
} from "../../components";
import type { components } from "../../api/schema";
import { ApiProblem } from "../../lib/api";
import { useNow } from "../../lib/clock";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { Composer, DEFAULT_MESSAGE_MAX_BYTES } from "../agent-session/Composer";
import { DiscussChatView } from "../agent-session/DiscussChat";
import { unifiedDiff, type PermissionMode } from "../agent-session/model";
import { DiffText } from "../agent-session/ToolCallCard";
import { useAgentSessionCommands, useAgentTranscript } from "../agent-session/queries";
import { sessionControlUnavailable } from "../sessions-list/control";
import { useAgentCapabilities, useCreateAgentSession, useWorkdirs } from "../sessions-list/queries";
import {
  confirmedReply,
  destination,
  discardPrompt,
  draftDir,
  draftKind,
  draftWrites,
  editDestination,
  editMainFile,
  editPrompt,
  hookFileText,
  newDraftId,
  projectPluginDir,
  publishEditPrompt,
  publishPrompt,
  studioPrompt,
  summarize,
  type DraftFile,
  type DraftSummary,
  type DraftWrites,
  type EditBaseline,
} from "./draft";
import { KINDS, KIND_HELP, type ItemKind } from "./filters";
import { FrontmatterTable } from "./FrontmatterTable";
import { skillRoute, useSkillCatalog, useSkillDetail, type SkillRef } from "./queries";
import { KIND_ICON, KIND_NAME, SkillCard } from "./SkillCard";
import { forgetDraft, openEditDraft, saveDraft, storedDraft } from "./studioDrafts";

type CatalogItem = components["schemas"]["CatalogItem"];
type SkillDetail = components["schemas"]["SkillDetail"];

const DEFAULT_MODELS = ["default", "opus", "sonnet", "haiku"];

/** The route of a draft in the Studio. */
export function studioRoute(project: string, draftId: string): string {
  return `/projects/${encodeURIComponent(project)}/skills/drafts/${encodeURIComponent(draftId)}`;
}

/** The route that starts a new draft of `kind`. */
export function newDraftRoute(project: string, kind: ItemKind): string {
  return `/projects/${encodeURIComponent(project)}/skills/new/${kind}`;
}

/** What one can ask for, to start from a blank page. */
const STARTERS: Record<ItemKind, string[]> = {
  skill: [
    "A /changelog skill that writes the release notes of the merged PRs since the last tag",
    "A skill the model loads when a migration is touched, with our Alembic rules",
    "A /pr-summary skill that drafts a PR body from the branch diff and the ticket",
  ],
  agent: [
    "A read-only security reviewer that checks a diff for secrets and injection",
    "A test-writer agent that adds missing tests with our factories and fixtures",
    "A docs agent that keeps docs/ in step with the code it is given",
  ],
  hook: [
    "Block any Bash command that touches production profiles or .env files",
    "Run the formatter on every file Claude writes or edits",
    "Log every prompt with a timestamp to .hub/prompts.log at session end",
  ],
};

/** What one can ask to change, to start an edit. */
const EDIT_STARTERS: Record<ItemKind, string[]> = {
  skill: [
    "Tighten the description so the model loads it at the right moments, and only then",
    "Shorten the body: keep the steps, cut what repeats the rest of the hub",
    "Check the steps against the hub as it is today and fix what drifted",
  ],
  agent: [
    "Tighten the description so the main session delegates to it at the right moments",
    "Narrow its tools to what its prompt actually needs",
    "Check the system prompt against the hub as it is today and fix what drifted",
  ],
  hook: [
    "Narrow the matcher so it only runs on the tools it is meant for",
    "Make the command fail loudly with a clear message instead of silently",
    "Add a timeout so a slow command cannot hold the session",
  ],
};

/** What each kind is made of, shown before anything is written. */
const ANATOMY: Record<ItemKind, { file: string; what: string }[]> = {
  skill: [
    {
      file: "SKILL.md",
      what: "Frontmatter (name, description, who invokes it) and the instructions.",
    },
    { file: "references/", what: "Longer material the skill links to and loads on demand." },
    { file: "scripts/", what: "Helpers the instructions run, when a step is mechanical." },
  ],
  agent: [
    {
      file: "<name>.md",
      what: "Frontmatter (name, description, tools, model) and its system prompt.",
    },
  ],
  hook: [
    { file: "hooks.json", what: "The lifecycle event, the tool matcher and the command to run." },
    { file: "scripts/", what: "The script the command calls, when it is more than one line." },
  ],
};

/** The route that starts (or reopens) an edit of an existing item with Claude. */
export function editDraftRoute(project: string, item: SkillRef): string {
  return `${skillRoute(project, item)}/edit`;
}

/** `/projects/:project/skills/:kind/:source/:name/edit`: opens the item's edit draft in the
 * Studio, the one already open for it when there is one. */
export function EditDraftScreen() {
  const { project = "", kind = "", source = "", name = "" } = useParams();
  const valid = KINDS.find((k) => k === kind);
  const [draftId] = useState(() => {
    if (!valid) return null;
    const target: SkillRef = { kind: valid, source, name };
    const open = openEditDraft(project, target);
    if (open) return open.draftId;
    const id = newDraftId(valid);
    saveDraft(id, { project, kind: valid }, { target, name });
    return id;
  });
  if (draftId === null)
    return <Navigate to={`/projects/${encodeURIComponent(project)}/skills`} replace />;
  return <Navigate to={studioRoute(project, draftId)} replace />;
}

/** `/projects/:project/skills/new/:kind`: issues a draft id and opens it in the Studio. */
export function NewDraftScreen() {
  const { project = "", kind = "" } = useParams();
  const valid = KINDS.find((k) => k === kind);
  const [draftId] = useState(() => (valid ? newDraftId(valid) : null));
  if (!valid || draftId === null)
    return <Navigate to={`/projects/${encodeURIComponent(project)}/skills`} replace />;
  return <Navigate to={studioRoute(project, draftId)} replace />;
}

/** `/projects/:project/skills/drafts/:draftId`: one draft, its conversation and its preview. */
export function StudioScreen() {
  const { project = "", draftId = "" } = useParams();
  const kind = draftKind(draftId);
  const [target] = useState(() => storedDraft(draftId)?.target ?? null);
  const label = target
    ? `Edit ${target.name}`
    : kind
      ? `New ${KIND_NAME[kind].toLowerCase()}`
      : "Draft";
  return (
    <div className="ah-page ah-studio-page">
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: project, href: `/projects/${encodeURIComponent(project)}` },
          { label: "Toolkit", href: `/projects/${encodeURIComponent(project)}/skills` },
          { label },
        ]}
      />
      {kind && target ? (
        <EditStudio key={draftId} project={project} draftId={draftId} target={target} />
      ) : kind ? (
        <Studio key={draftId} project={project} kind={kind} draftId={draftId} edit={null} />
      ) : (
        <div className="ah-card">
          <EmptyState icon="file-x" title="This is not a Studio draft.">
            Start one from the Toolkit with Create.
          </EmptyState>
        </div>
      )}
    </div>
  );
}

/** The existing item an edit draft changes, as the hub has it now. */
interface EditContext {
  target: SkillRef;
  sourcePath: string;
  /** The draft's main file (`SKILL.md`, `<name>.md`, `hooks.json`). */
  mainPath: string;
  /** Where Publish writes: the item's folder or file. */
  to: string;
  /** For a hook: its own hooks.json text, the draft's starting point. */
  hookText: string | null;
  baseline: EditBaseline;
}

function editContext(target: SkillRef, detail: SkillDetail): EditContext {
  const hookText = detail.hook ? hookFileText(detail.hook) : null;
  return {
    target,
    sourcePath: detail.source_path,
    mainPath: editMainFile(target.kind, detail.source_path),
    to: editDestination(target.kind, detail.source_path),
    hookText,
    baseline: {
      name: detail.name,
      original: target.kind === "hook" ? hookText : (detail.raw ?? null),
      managed: detail.origin === "managed",
    },
  };
}

/** An edit draft: loads the item as it is now, then opens the Studio on it. */
function EditStudio({
  project,
  draftId,
  target,
}: {
  project: string;
  draftId: string;
  target: SkillRef;
}) {
  const detail = useSkillDetail(project, target);
  const edit = useMemo(
    () => (detail.data ? editContext(target, detail.data) : null),
    [detail.data, target],
  );
  if (detail.isError) {
    return (
      <div className="ah-card">
        <EmptyState icon="file-x" title={`${target.name} is not in the catalog any more.`}>
          {detail.error.detail ?? detail.error.title}
        </EmptyState>
      </div>
    );
  }
  if (!edit) return <Skeleton lines={8} />;
  return <Studio project={project} kind={target.kind} draftId={draftId} edit={edit} />;
}

interface StudioContext {
  project: string;
  kind: ItemKind;
  draftId: string;
  items: readonly CatalogItem[];
  pluginDir: string | null;
  taken: ReadonlySet<string>;
  edit: EditContext | null;
}

function Studio({
  project,
  kind,
  draftId,
  edit,
}: {
  project: string;
  kind: ItemKind;
  draftId: string;
  edit: EditContext | null;
}) {
  const catalog = useSkillCatalog(project);
  const [sessionId, setSessionId] = useState<string | null>(
    () => storedDraft(draftId)?.sessionId ?? null,
  );
  const items = useMemo(() => catalog.data?.items ?? [], [catalog.data]);
  const context: StudioContext = useMemo(
    () => ({
      project,
      kind,
      draftId,
      items,
      pluginDir: projectPluginDir(items),
      taken: new Set(items.filter((item) => item.kind === kind).map((item) => item.name)),
      edit,
    }),
    [project, kind, draftId, items, edit],
  );
  const { refetch } = catalog;
  const refresh = useCallback(() => {
    void refetch();
  }, [refetch]);
  const forget = useCallback(() => {
    saveDraft(draftId, { project, kind }, { sessionId: null });
    setSessionId(null);
  }, [draftId, project, kind]);

  if (catalog.isPending) return <Skeleton lines={8} />;
  return sessionId ? (
    <StudioSession context={context} sessionId={sessionId} onGone={forget} onRefresh={refresh} />
  ) : (
    <StudioStart
      context={context}
      onStarted={(id) => {
        saveDraft(draftId, { project, kind }, { sessionId: id });
        setSessionId(id);
      }}
    />
  );
}

function StudioHeader({
  context,
  summary,
  actions,
}: {
  context: StudioContext;
  summary: DraftSummary | null;
  actions?: ReactNode;
}) {
  const { kind, edit } = context;
  return (
    <header className="ah-studio-head">
      <span className="ah-studio-kind" data-kind={kind}>
        <Icon name={KIND_ICON[kind]} />
      </span>
      <div className="ah-studio-title">
        <h1 className="ah-h1">
          {summary?.name || edit ? (
            <span className="ah-mono">{summary?.name ?? edit?.baseline.name}</span>
          ) : (
            `New ${KIND_NAME[kind].toLowerCase()}`
          )}
        </h1>
        <span className="ah-small ah-muted">
          <span className="ah-studio-chip">
            <Icon name="file-pen" size="sm" />
            {edit ? "Editing" : "Draft"}
          </span>{" "}
          {edit ? (
            <>
              <span className="ah-mono">{edit.sourcePath}</span> in{" "}
              <span className="ah-mono">{draftDir(context.draftId)}/</span> · the original is
              unchanged until you click Publish
            </>
          ) : (
            <>
              in <span className="ah-mono">{draftDir(context.draftId)}/</span> · nothing is
              published until you click Publish
            </>
          )}
        </span>
      </div>
      <span className="ah-grow" />
      {actions}
    </header>
  );
}

function StudioStart({
  context,
  onStarted,
}: {
  context: StudioContext;
  onStarted: (id: string) => void;
}) {
  const { project, kind, draftId, pluginDir, taken, edit } = context;
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const canDrive = capabilities.data !== undefined && unavailable === null;
  const workdirs = useWorkdirs(project, canDrive);
  const hub = workdirs.data?.items.find((w) => w.kind === "hub") ?? null;
  const create = useCreateAgentSession();
  const [mode, setMode] = useState<PermissionMode>("acceptEdits");
  const [model, setModel] = useState<string | null>(null);
  const reason = unavailable
    ? `${unavailable.title}.`
    : !canDrive
      ? "Checking whether this machine can drive Claude…"
      : workdirs.isPending
        ? "Looking for the hub folder…"
        : hub === null
          ? `Project ${project} has no hub folder to work in.`
          : null;
  const start = async (text: string) => {
    if (!hub) return;
    const session = await create.mutateAsync({
      project,
      workdir_id: hub.workdir_id,
      mode,
      fork: false,
      ...(model && model !== "default" ? { model } : {}),
      prompt: edit
        ? editPrompt(
            {
              project,
              kind,
              draftId,
              name: edit.baseline.name,
              sourcePath: edit.sourcePath,
              managed: edit.baseline.managed,
              hookText: edit.hookText,
            },
            text,
          )
        : studioPrompt({ project, kind, draftId, pluginDir, taken: [...taken] }, text),
    });
    onStarted(session.id);
  };
  return (
    <div className="ah-studio">
      <StudioHeader context={context} summary={null} />
      <div className="ah-studio-split">
        <section className="ah-studio-chat" aria-label="Conversation with Claude">
          <div className="ah-studio-intro">
            {edit ? (
              <>
                <h2 className="ah-h3">What should change in {edit.baseline.name}?</h2>
                <p className="ah-small ah-muted">
                  Claude copies the {KIND_NAME[kind].toLowerCase()} into a draft, changes the copy
                  and shows the changes on the right as it writes. Ask for more until it reads
                  right; <span className="ah-mono">{edit.sourcePath}</span> stays as it is until you
                  publish.
                </p>
                {edit.baseline.managed && (
                  <Banner tone="warning" boxed>
                    <b>Managed by hub.lock.</b> The next hub sync overwrites a local edit of it;
                    Claude can tell you where the change should live instead.
                  </Banner>
                )}
              </>
            ) : (
              <>
                <h2 className="ah-h3">Describe the {KIND_NAME[kind].toLowerCase()} you want</h2>
                <p className="ah-small ah-muted">
                  {KIND_HELP[kind]} Claude reads the hub's existing items, writes a draft beside
                  them and shows it on the right as it writes. Ask for changes until it reads right.
                </p>
              </>
            )}
            {unavailable && (
              <Banner tone="warning" boxed>
                <b>{unavailable.title}.</b> {unavailable.detail}
              </Banner>
            )}
            <ul className="ah-studio-starters" aria-label="Ideas to start from">
              {(edit ? EDIT_STARTERS : STARTERS)[kind].map((starter) => (
                <li key={starter}>
                  <button
                    type="button"
                    disabled={reason !== null || create.isPending}
                    onClick={() => void start(starter)}
                  >
                    <Icon name="lightbulb" size="sm" />
                    {starter}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="ah-grow" />
          <footer className="as-footer">
            <div className="as-column">
              <Composer
                status={null}
                mode={mode}
                model={model}
                models={capabilities.data?.models ?? DEFAULT_MODELS}
                onSend={start}
                onInterrupt={() => undefined}
                onSettings={(change) => {
                  if (change.mode) setMode(change.mode);
                  if (change.model) setModel(change.model);
                  return undefined;
                }}
                maxBytes={DEFAULT_MESSAGE_MAX_BYTES}
                draftId={`studio.${draftId}`}
                focusOnOpen
                disabledReason={reason ?? (create.isPending ? "Starting the session…" : null)}
              />
              {create.error instanceof ApiProblem && (
                <p className="ah-small as-error" role="alert">
                  {create.error.detail ?? create.error.title}
                </p>
              )}
            </div>
          </footer>
        </section>
        <section className="ah-studio-preview" aria-label="Draft preview">
          {edit ? (
            <CurrentVersion kind={kind} edit={edit} />
          ) : (
            <div className="ah-studio-empty">
              <Icon name={KIND_ICON[kind]} />
              <h2 className="ah-h3">The draft appears here as Claude writes it</h2>
              <p className="ah-small ah-muted">A {KIND_NAME[kind].toLowerCase()} is made of:</p>
              <ul className="ah-studio-anatomy">
                {ANATOMY[kind].map((part) => (
                  <li key={part.file}>
                    <code>{part.file}</code>
                    <span>{part.what}</span>
                  </li>
                ))}
              </ul>
              <p className="ah-small ah-muted">
                Publishes to <span className="ah-mono">{destination(kind, null, pluginDir)}</span>
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

type Phase = "drafting" | "publishing" | "published" | "discarding" | "discarded";

function StudioSession({
  context,
  sessionId,
  onGone,
  onRefresh,
}: {
  context: StudioContext;
  sessionId: string;
  onGone: () => void;
  onRefresh: () => void;
}) {
  const { project, kind, draftId, pluginDir, taken, items, edit } = context;
  const navigate = useNavigate();
  const transcript = useAgentTranscript(sessionId);
  const commands = useAgentSessionCommands(sessionId);
  const { state } = transcript;
  const writes = useMemo(() => draftWrites(state, draftId), [state, draftId]);
  const [phase, setPhase] = useState<Phase>(() =>
    storedDraft(draftId)?.published ? "published" : "drafting",
  );
  // Before publishing, a name in the catalog is a clash; after, it is the published item.
  const summary = useMemo(
    () =>
      summarize(
        kind,
        writes.files,
        phase === "drafting" ? taken : new Set(),
        edit && phase === "drafting" ? edit.baseline : null,
      ),
    [kind, writes.files, taken, phase, edit],
  );
  const [confirm, setConfirm] = useState<"publish" | "discard" | null>(null);
  const busy = state.turnOpen || state.sending.length > 0;
  const to = edit ? edit.to : destination(kind, summary.name, pluginDir);

  useEffect(() => {
    if (summary.name) saveDraft(draftId, { project, kind }, { name: summary.name });
  }, [summary.name, draftId, project, kind]);

  // The Publish or Discard message once accepted, and how far the transcript was when it went.
  const [request, setRequest] = useState<{ text: string; from: number } | null>(null);
  const [notice, setNotice] = useState<{ tone: "error" | "warning"; text: string } | null>(null);
  // It settles when its turn has ended, on Claude's confirmation only (adjusted while rendering).
  const publishing = phase === "publishing";
  if (request && !busy && (publishing || phase === "discarding")) {
    const marker = publishing ? "PUBLISHED" : "DISCARDED";
    const confirmed = confirmedReply(state.entries, request.text, request.from, marker);
    if (confirmed !== null) {
      setRequest(null);
      setPhase(confirmed ? (publishing ? "published" : "discarded") : "drafting");
      if (!confirmed) {
        setNotice({
          tone: "warning",
          text: `Claude did not confirm the ${publishing ? "publish" : "discard"}. Read its reply and check the hub folder before you try again.`,
        });
      }
    }
  }
  useEffect(() => {
    if (phase === "published") {
      onRefresh();
      saveDraft(draftId, { project, kind }, { published: true });
    } else if (phase === "discarded") {
      forgetDraft(draftId);
      void navigate(`/projects/${encodeURIComponent(project)}/skills`);
    }
  }, [phase, onRefresh, draftId, project, kind, navigate]);

  const published =
    phase === "published" && summary.name
      ? (items.find((item) => item.kind === kind && item.name === summary.name) ?? null)
      : null;

  const send = (text: string) => transcript.send(text, commands.send);
  const ask = async (next: "publishing" | "discarding", text: string) => {
    setConfirm(null);
    setNotice(null);
    setPhase(next);
    const from = state.entries.length;
    try {
      await send(text);
      setRequest({ text, from });
    } catch (cause) {
      setPhase("drafting");
      setNotice({
        tone: "error",
        text:
          cause instanceof ApiProblem
            ? (cause.detail ?? cause.title)
            : "The message did not reach Claude. Try again.",
      });
    }
  };
  const actions =
    phase === "published" ? null : (
      <div className="ah-row" style={{ gap: 8 }}>
        <Button
          variant="ghost"
          icon="file-x"
          disabled={busy || phase !== "drafting"}
          onClick={() => {
            setConfirm("discard");
          }}
        >
          Discard
        </Button>
        <Button
          variant="primary"
          icon="check"
          disabled={busy || phase !== "drafting" || !summary.publishable}
          title={
            busy
              ? "Claude is still working"
              : !summary.publishable
                ? "Nothing to publish yet"
                : `Publish to ${to}`
          }
          onClick={() => {
            setConfirm("publish");
          }}
        >
          {phase === "publishing" ? "Publishing…" : "Publish"}
        </Button>
      </div>
    );

  return (
    <div className="ah-studio">
      <StudioHeader context={context} summary={summary} actions={actions} />
      {notice && (
        <Banner tone={notice.tone} boxed>
          {notice.text}
        </Banner>
      )}
      {phase === "published" && (
        <Banner tone="info" boxed icon="circle-check">
          <b>Published.</b>{" "}
          {published ? (
            <>
              It is in the catalog now:{" "}
              <AppLink href={skillRoute(project, published)}>open {published.name}</AppLink>.
            </>
          ) : (
            <>
              Claude moved the draft to <span className="ah-mono">{to}</span>; it shows in the
              catalog once the hub's files are read again.{" "}
              <Button size="sm" variant="ghost" icon="refresh-cw" onClick={onRefresh}>
                Check again
              </Button>
            </>
          )}{" "}
          Review the change in the hub with git before you commit it.
        </Banner>
      )}
      <div className="ah-studio-split">
        <section className="ah-studio-chat" aria-label="Conversation with Claude">
          <DiscussChatView agentSessionId={sessionId} onGone={onGone} transcript={transcript} />
        </section>
        <section className="ah-studio-preview" aria-label="Draft preview">
          <DraftPreview
            project={project}
            draftId={draftId}
            kind={kind}
            writes={writes}
            summary={summary}
            to={to}
            busy={busy}
            edit={edit}
          />
        </section>
      </div>
      {confirm === "publish" && (
        <ConfirmDialog
          title={
            edit
              ? `Publish the changes to ${edit.baseline.name}?`
              : `Publish ${summary.name ?? `this ${kind}`}?`
          }
          tone="primary"
          confirmLabel="Publish"
          consequences={
            edit
              ? [
                  kind === "hook" ? (
                    <>
                      Claude replaces this hook in{" "}
                      <span className="ah-mono">{edit.sourcePath}</span> and keeps the others, then
                      deletes <span className="ah-mono">{draftDir(draftId)}/</span>.
                    </>
                  ) : (
                    <>
                      Claude writes the draft's files over <span className="ah-mono">{to}</span> and
                      deletes <span className="ah-mono">{draftDir(draftId)}/</span>.
                    </>
                  ),
                  ...(edit.baseline.managed
                    ? ["It is managed by hub.lock: the next hub sync overwrites this edit."]
                    : []),
                  "Nothing is committed: you review and commit the change in the hub.",
                ]
              : [
                  <>
                    Claude moves the draft to <span className="ah-mono">{to}</span> and deletes{" "}
                    <span className="ah-mono">{draftDir(draftId)}/</span>.
                  </>,
                  kind === "hook"
                    ? "The hook runs in every session of this hub once it is synced; check its command."
                    : "Sessions of this hub can use it from their next start.",
                  "Nothing is committed: you review and commit the change in the hub.",
                ]
          }
          onCancel={() => {
            setConfirm(null);
          }}
          onConfirm={() => {
            void ask(
              "publishing",
              edit
                ? publishEditPrompt(kind, draftId, edit.sourcePath, edit.hookText)
                : publishPrompt(kind, draftId, to),
            );
          }}
        />
      )}
      {confirm === "discard" && (
        <ConfirmDialog
          title="Discard this draft?"
          confirmLabel="Discard"
          consequences={[
            <>
              Claude deletes <span className="ah-mono">{draftDir(draftId)}/</span>; the conversation
              stays in Sessions.
            </>,
          ]}
          onCancel={() => {
            setConfirm(null);
          }}
          onConfirm={() => {
            void ask("discarding", discardPrompt(draftId));
          }}
        />
      )}
    </div>
  );
}

type PreviewTab = "preview" | "changes" | "files";

function DraftPreview({
  project,
  draftId,
  kind,
  writes,
  summary,
  to,
  busy,
  edit,
}: {
  project: string;
  draftId: string;
  kind: ItemKind;
  writes: DraftWrites;
  summary: DraftSummary;
  to: string;
  busy: boolean;
  edit: EditContext | null;
}) {
  const now = useNow(60_000);
  const [tab, setTab] = useState<PreviewTab>(edit ? "changes" : "preview");
  const [openPath, setOpenPath] = useState<string | null>(null);
  const shown = writes.files.find((f) => f.path === openPath) ?? writes.files[0] ?? null;

  if (writes.files.length === 0) {
    return (
      <div className="ah-studio-empty">
        <Icon name={busy ? "loader" : KIND_ICON[kind]} />
        <h2 className="ah-h3">{busy ? "Claude is reading the hub…" : "No draft yet"}</h2>
        <p className="ah-small ah-muted">
          Files appear here as soon as Claude writes them into{" "}
          <span className="ah-mono">{draftDir(draftId)}/</span>.
        </p>
        {writes.outside.length > 0 && <OutsideWarning paths={writes.outside} />}
      </div>
    );
  }

  return (
    <div className="ah-studio-preview-body">
      {summary.card && (
        <div className="ah-studio-block">
          <h2 className="ah-studio-label">In the catalog</h2>
          <ul className="ah-skills-grid ah-studio-card">
            <SkillCard
              item={summary.card}
              project={project}
              now={now}
              usageDays={30}
              linked={false}
            />
          </ul>
        </div>
      )}
      <div className="ah-studio-block">
        <h2 className="ah-studio-label">
          {edit ? "Before publishing the changes" : "Before publishing"}
        </h2>
        <ul className="ah-studio-checks">
          {summary.checks.map((check) => (
            <li key={check.id} data-state={check.state}>
              <Icon
                name={
                  check.state === "ok"
                    ? "circle-check"
                    : check.state === "warn"
                      ? "triangle-alert"
                      : "circle-dashed"
                }
                size="sm"
              />
              {check.label}
            </li>
          ))}
          <li data-state="info">
            <Icon name="folder-open" size="sm" />
            Publishes to <span className="ah-mono">{to}</span>
          </li>
        </ul>
        {writes.outside.length > 0 && <OutsideWarning paths={writes.outside} />}
      </div>
      <div className="ah-studio-block ah-grow">
        <div className="ah-row ah-wrap" style={{ gap: 8 }}>
          <SegmentedControl
            label="Preview view"
            value={tab}
            onChange={(id) => {
              setTab(id === "files" ? "files" : id === "changes" ? "changes" : "preview");
            }}
            options={[
              ...(edit ? [{ id: "changes", label: "Changes", icon: "git-compare" as const }] : []),
              { id: "preview", label: "Preview", icon: "scan-eye" },
              { id: "files", label: `Files ${String(writes.files.length)}`, icon: "folder" },
            ]}
          />
          <span className="ah-grow" />
          {busy && (
            <span className="ah-small ah-muted ah-studio-live">
              <Icon name="loader" size="sm" />
              Updating live
            </span>
          )}
        </div>
        {tab === "changes" && edit ? (
          <DraftChanges files={writes.files} edit={edit} />
        ) : tab === "preview" ? (
          <RenderedDraft kind={kind} summary={summary} />
        ) : (
          <div className="ah-studio-files">
            <ul className="ah-studio-tree" aria-label="Draft files">
              {writes.files.map((file) => (
                <li key={file.path}>
                  <button
                    type="button"
                    aria-current={shown?.path === file.path ? true : undefined}
                    onClick={() => {
                      setOpenPath(file.path);
                    }}
                  >
                    <Icon name={file.path.includes("/") ? "file" : "file-text"} size="sm" />
                    <span className="ah-mono ah-grow">{file.path}</span>
                    {file.pending && <Icon name="loader" size="sm" />}
                  </button>
                </li>
              ))}
            </ul>
            {shown && <FileText file={shown} />}
          </div>
        )}
      </div>
    </div>
  );
}

/** Each draft file against the item as it is now: the main file as a diff, the others as new. */
function DraftChanges({ files, edit }: { files: readonly DraftFile[]; edit: EditContext }) {
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      {files.map((file) => {
        const isMain = file.path === edit.mainPath;
        const before = isMain ? edit.baseline.original : null;
        if (isMain && before === null) {
          return (
            <p key={file.path} className="ah-small ah-muted">
              The hub did not send the current text of{" "}
              <span className="ah-mono">{edit.sourcePath}</span>; see Files for the draft.
            </p>
          );
        }
        return (
          <DiffText
            key={file.path}
            diff={unifiedDiff(file.path, before ?? "", file.content)}
            label={`Changes to ${file.path}`}
          />
        );
      })}
    </div>
  );
}

/** Before the first message of an edit: the item as it is now. */
function CurrentVersion({ kind, edit }: { kind: ItemKind; edit: EditContext }) {
  const summary = useMemo(
    () =>
      summarize(
        kind,
        edit.baseline.original === null
          ? []
          : [
              {
                path: edit.mainPath,
                content: edit.baseline.original,
                partial: false,
                pending: false,
              },
            ],
      ),
    [kind, edit],
  );
  return (
    <div className="ah-studio-preview-body">
      <div className="ah-studio-block">
        <h2 className="ah-studio-label">Current version</h2>
        <p className="ah-small ah-muted">
          <span className="ah-mono">{edit.sourcePath}</span> · Claude's changes show here as a diff
          while it writes.
        </p>
      </div>
      <div className="ah-studio-block ah-grow">
        {summary.main ? (
          <RenderedDraft kind={kind} summary={summary} />
        ) : (
          <p className="ah-small ah-muted">The hub did not send the current text.</p>
        )}
      </div>
    </div>
  );
}

function OutsideWarning({ paths }: { paths: readonly string[] }) {
  return (
    <Banner tone="warning" boxed>
      Claude also wrote outside the draft folder:{" "}
      {paths.map((p, i) => (
        <span key={p}>
          {i > 0 && ", "}
          <span className="ah-mono">{p}</span>
        </span>
      ))}
      . Those changes are already on disk; review them in the hub.
    </Banner>
  );
}

function FileText({ file }: { file: DraftFile }) {
  return (
    <pre className="ah-studio-code" aria-label={file.path}>
      <code>{file.content}</code>
    </pre>
  );
}

function RenderedDraft({ kind, summary }: { kind: ItemKind; summary: DraftSummary }) {
  if (kind === "hook") {
    if (summary.hooks.length === 0) {
      return (
        <p className="ah-small ah-muted">
          {summary.hooksError ?? "hooks.json declares no hook yet."}
        </p>
      );
    }
    return (
      <div className="ah-table-wrap">
        <table className="ah-table">
          <caption className="ah-sr">Hooks in the draft</caption>
          <thead>
            <tr>
              <th scope="col">Event</th>
              <th scope="col">Matcher</th>
              <th scope="col">Command</th>
              <th scope="col">Timeout</th>
            </tr>
          </thead>
          <tbody>
            {summary.hooks.map((hook, i) => (
              <tr key={i}>
                <td className="ah-mono">{hook.event}</td>
                <td className="ah-mono">{hook.matcher ?? "any"}</td>
                <td>
                  <code className="ah-studio-command">{hook.command ?? `(${hook.type})`}</code>
                </td>
                <td>{hook.timeout === null ? "default" : `${String(hook.timeout)} s`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  const document = summary.document;
  if (!document) return null;
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      {document.pairs.length > 0 && <FrontmatterTable pairs={document.pairs} />}
      <article className="ah-card ah-pad ah-studio-body">
        {document.body.trim() === "" ? (
          <p className="ah-small ah-muted">The body is empty so far.</p>
        ) : (
          <Markdown source={document.body} />
        )}
      </article>
    </div>
  );
}
