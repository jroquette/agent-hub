import "../agent-session/agent-session.css";

import { useId, useRef, useState, type KeyboardEvent } from "react";

import {
  AppLink,
  AttachmentList,
  Banner,
  Button,
  EmptyState,
  Icon,
  Kbd,
  SegmentedControl,
  Skeleton,
  useMessageAttachments,
  type AttachedFile,
  type AttachedImage,
} from "../../components";
import { ApiProblem, useApi } from "../../lib/api";
import { cx } from "../../lib/cx";
import { useScope } from "../../lib/scope";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import {
  discussPrompt,
  useDiscuss,
  useDiscussTarget,
  type DiscussTarget,
} from "../../shell/discuss";
import { rememberDiscussSession, useStartDiscussion } from "../../shell/discussSession";
import { useDraft } from "../agent-session/useDraft";
import { featureHref } from "./FeatureChip";
import { useFeatures } from "./queries";

/* New feature: the brief (text, images, PDFs, text files) is the screen. One press starts the
 * conversation in the project's hub folder and opens the Discuss panel on it: Claude runs the
 * hub's golden path with the owner, from the brief to the spec. The page then watches the feature
 * records for the new one. */

const KEBAB = /^[a-z][a-z0-9-]*$/;
const ISSUE = /^[A-Za-z][A-Za-z0-9]*-\d+$/;
const MIN_IDEA = 10;

const SIZES: readonly { id: string; label: string; hint: string }[] = [
  { id: "", label: "Let Claude ask", hint: "Claude proposes a size and asks you." },
  { id: "spike", label: "Spike", hint: "Throwaway learning, nothing merged." },
  { id: "bounded", label: "Bounded", hint: "A few PRs, the design is known." },
  {
    id: "architectural",
    label: "Architectural",
    hint: "A new contract between repos or services, or a decision worth an ADR.",
  },
];
// The segmented control needs a non-empty id for "Let Claude ask".
const ASK = "ask";
const sizeLabel = (size: string) => SIZES.find((option) => option.id === size)?.label ?? size;

const BRIEF = [
  "This is the start of a new feature, run on the hub's golden path: the `feature` skill of this hub (`plugin/hub-workflow/skills/feature/SKILL.md`, or `.claude/skills/feature/SKILL.md` when the plugin is not there). Read it first and follow it here, in this conversation, from step 0 (the brief).",
  "Ask me one question at a time, as the skill says, and stop at each of its gates for my approval. Writing the files the skill asks for (the tracker issue's brief, `brain/features/<slug>/spec.md`, its summary) is part of this request; show me each one before it is written.",
  "The files and images attached to this message are part of the idea: read them before your first question.",
  "Tell me the feature's slug as soon as you choose it.",
].join("\n");

export function composeFeatureMessage(fields: {
  idea: string;
  issue: string;
  size: string;
  slug: string;
}): string {
  const lines = ["Start a new feature in this hub."];
  if (fields.issue) lines.push(`Tracker issue: ${fields.issue} (read its brief first).`);
  if (fields.slug) lines.push(`Slug: ${fields.slug}`);
  if (fields.size) lines.push(`Size: ${fields.size}`);
  lines.push("", "The idea:", fields.idea.trim());
  return lines.join("\n");
}

/** One conversation per request: asking again starts a fresh one. */
function newFeatureKey(project: string): string {
  return `feature-new:${project}:${String(Date.now())}`;
}

/** What was sent, kept on screen once the conversation started. */
interface SentRequest {
  sessionId: string;
  idea: string;
  issue: string;
  slug: string;
  size: string;
  images: readonly AttachedImage[];
  files: readonly AttachedFile[];
  /** The slugs there were when Claude was asked: the first one after that is the new feature. */
  known: ReadonlySet<string>;
}

/** `/features/new`: say the idea, attach what Claude should see, and start with Claude. */
export function NewFeatureScreen() {
  const [scope] = useScope();
  const projectsQuery = useApi("/api/v1/projects");
  const projects = (projectsQuery.data?.items ?? []).map((item) => item.name);
  const [project, setProject] = useState<string>(scope ?? "");
  const chosenProject = project || (projects[0] ?? "");
  const [target, setTarget] = useState<DiscussTarget | null>(null);
  const [sent, setSent] = useState<SentRequest | null>(null);
  const { open, setOpen } = useDiscuss();
  useDiscussTarget(target);

  if (projectsQuery.data && projects.length === 0) {
    return (
      <div className="ft-new">
        <Breadcrumbs items={[{ label: "Features", href: "/features" }, { label: "New" }]} />
        <EmptyState
          icon="folder-kanban"
          title="No project yet"
          action={<AppLink href="/welcome">Open Welcome</AppLink>}
        >
          Register a hub to start features in it.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="ft-new">
      <Breadcrumbs items={[{ label: "Features", href: "/features" }, { label: "New" }]} />
      <header className="ft-new-head">
        <div className="ft-new-title">
          <h1 className="ah-h1">New feature</h1>
          {projectsQuery.isPending ? (
            <Skeleton width={160} height={30} />
          ) : (
            projects.length > 1 &&
            !sent && (
              <ProjectSelect projects={projects} value={chosenProject} onChange={setProject} />
            )
          )}
        </div>
        <p className="ft-new-lead">
          Say what to build. Claude writes the brief and the spec with you, one question at a time.
        </p>
      </header>
      {sent && target ? (
        <SentCard
          sent={sent}
          project={chosenProject}
          panelOpen={open}
          onOpenPanel={() => {
            setOpen(true);
          }}
          onAnother={() => {
            setSent(null);
            setTarget(null);
          }}
        />
      ) : chosenProject === "" ? (
        // The brief's draft is kept per project: the form waits for it to be known.
        <Skeleton height={200} radius={12} />
      ) : (
        <BriefForm
          key={chosenProject}
          project={chosenProject}
          onStarted={(request, startedTarget) => {
            setSent(request);
            setTarget(startedTarget);
            setOpen(true);
          }}
        />
      )}
    </div>
  );
}

function ProjectSelect({
  projects,
  value,
  onChange,
}: {
  projects: readonly string[];
  value: string;
  onChange: (project: string) => void;
}) {
  const id = useId();
  return (
    <div className="ft-new-project">
      <label htmlFor={id} className="ah-small ah-muted">
        Project
      </label>
      <select
        id={id}
        className="ah-input"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        {projects.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
    </div>
  );
}

function BriefForm({
  project,
  onStarted,
}: {
  project: string;
  onStarted: (request: SentRequest, target: DiscussTarget) => void;
}) {
  const { text: idea, setText: setIdea, accepted } = useDraft(`feature-new.${project}`);
  const [issue, setIssue] = useState("");
  const [size, setSize] = useState("");
  const [slug, setSlug] = useState("");
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const filePicker = useRef<HTMLInputElement | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const discussion = useStartDiscussion(project || null);
  const attachments = useMessageAttachments({
    acceptsImages: true,
    acceptsFiles: true,
    onError: setAttachError,
  });
  const features = useFeatures(project || null);
  const items = (features.data?.items ?? []).filter((f) => f.project === project);
  const ids = {
    idea: useId(),
    hint: useId(),
    issue: useId(),
    issueHint: useId(),
    slug: useId(),
    slugHint: useId(),
    reason: useId(),
  };

  const badSlug = slug !== "" && !KEBAB.test(slug);
  const badIssue = issue !== "" && !ISSUE.test(issue);
  const taken = slug !== "" && items.some((f) => f.slug === slug);
  const hasIdea = idea.trim().length >= MIN_IDEA;
  const hasIssue = issue !== "" && !badIssue;
  // The first reason that holds, said next to the button (and read with it).
  const why =
    discussion.unavailable !== null
      ? "Claude cannot run on this machine yet."
      : attachments.reading > 0
        ? "Wait for the files to be read."
        : !hasIdea && !hasIssue
          ? attachments.count > 0
            ? "Add a sentence on what to build with the attachments."
            : "Write at least a sentence, or give an issue."
          : badIssue || badSlug || taken
            ? "Fix the field marked above."
            : discussion.reason;
  const ready = why === null && !discussion.pending;

  const start = () => {
    if (!ready) return;
    const key = newFeatureKey(project);
    const target: DiscussTarget = {
      key,
      project,
      kind: "New feature",
      title: slug || issue || "a new feature",
      brief: BRIEF,
      openOnArrive: true,
    };
    const message = composeFeatureMessage({ idea, issue, size, slug });
    const images = attachments.images;
    const files = attachments.files;
    const known = new Set(items.map((f) => f.slug));
    void discussion
      .start({
        target,
        prompt: discussPrompt(target, message),
        images: images.map((image) => image.url),
        files: files.map((attached) => attached.file),
      })
      .then((sessionId) => {
        if (!sessionId) return;
        // Kept before the target is set, so the panel opens straight on this conversation.
        rememberDiscussSession(target, sessionId);
        accepted(idea);
        onStarted({ sessionId, idea, issue, slug, size, images, files, known }, target);
      })
      .catch(() => undefined); // The failure shows under the button (discussion.error).
  };

  const startOnChord = (event: KeyboardEvent) => {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      start();
    } else if (event.target instanceof HTMLInputElement) {
      event.preventDefault(); // Enter in a one-line field never starts by accident.
    }
  };

  const placeholder =
    attachments.images.length > 0
      ? "Say what to build, and what Claude should see in the image."
      : attachments.files.length > 0
        ? "Say what to build, and what Claude should take from the file."
        : "Owners can export the orders of a period as CSV from the admin portal, with the same filters as the list.";

  const startError =
    discussion.error instanceof ApiProblem
      ? (discussion.error.detail ?? discussion.error.title)
      : discussion.error
        ? "Could not start the conversation. Try again."
        : null;

  return (
    // Ctrl/Cmd+Enter starts from any field of the form; the button does the same.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <form
      aria-label="New feature"
      className="ft-new-form"
      onSubmit={(event) => {
        event.preventDefault();
        start();
      }}
      onKeyDown={startOnChord}
    >
      {discussion.unavailable && (
        <Banner tone="warning" boxed>
          <b>{discussion.unavailable.title}.</b> {discussion.unavailable.detail}
        </Banner>
      )}
      <div className="ft-new-field">
        <label htmlFor={ids.idea} className="ft-new-label">
          What do you want to build?
        </label>
        {/* A file dropped anywhere on the box joins the brief; the keyboard has Attach. */}
        {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
        <div
          className={cx("as-composer ft-new-brief", dragging && "as-composer-drop")}
          onDragOver={(event) => {
            if (!event.dataTransfer.types.includes("Files")) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
            setDragging(true);
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null))
              setDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            attachments.add(event.dataTransfer);
            box.current?.focus();
          }}
        >
          <AttachmentList
            images={attachments.images}
            files={attachments.files}
            reading={attachments.reading}
            label="Attached to this request"
            onRemoveImage={(key) => {
              attachments.removeImage(key);
              box.current?.focus();
            }}
            onRemoveFile={(key) => {
              attachments.removeFile(key);
              box.current?.focus();
            }}
            onReplaceImage={attachments.replaceImage}
          />
          <textarea
            id={ids.idea}
            ref={box}
            className="ah-input as-composer-input ft-new-idea"
            rows={6}
            value={idea}
            placeholder={placeholder}
            aria-describedby={ids.hint}
            onChange={(event) => {
              setIdea(event.target.value);
            }}
            onPaste={(event) => {
              if (!attachments.takes(event.clipboardData)) return;
              // A copied file may also carry its name as text: only the file is pasted.
              event.preventDefault();
              attachments.add(event.clipboardData);
            }}
          />
          <div className="as-composer-bar">
            <div className="ft-new-attach">
              <input
                ref={filePicker}
                type="file"
                multiple
                hidden
                tabIndex={-1}
                onChange={(event) => {
                  attachments.add(event.target);
                  event.target.value = "";
                  box.current?.focus();
                }}
              />
              <Button
                size="sm"
                variant="ghost"
                icon="plus"
                disabled={attachments.full}
                aria-label="Attach a file"
                title="Attach images, PDFs or text files up to 5 MB (or paste or drop them in the box)"
                onClick={() => filePicker.current?.click()}
              >
                Attach
              </Button>
              <span className="ah-small ah-subtle">Paste or drop images, PDFs and text files</span>
            </div>
          </div>
        </div>
        {attachError ? (
          <p id={ids.hint} className="ft-new-hint" data-error role="alert">
            <Icon name="circle-x" size="sm" />
            {attachError}
          </p>
        ) : (
          <p id={ids.hint} className="ft-new-hint">
            Up to 10 images and 5 files of 5 MB each.
          </p>
        )}
      </div>

      <div className="ft-new-field ft-new-issue">
        <label htmlFor={ids.issue} className="ft-new-label">
          Start from an issue (optional)
        </label>
        <input
          id={ids.issue}
          className="ah-input ah-mono"
          value={issue}
          placeholder="DEMO-1600"
          aria-invalid={badIssue || undefined}
          aria-describedby={ids.issueHint}
          onChange={(event) => {
            setIssue(event.target.value.trim().toUpperCase());
          }}
        />
        <FieldHint id={ids.issueHint} error={badIssue ? "An issue id, like DEMO-1600." : null}>
          Left empty, Claude writes the brief with you and creates it.
        </FieldHint>
      </div>

      <details
        className="ft-new-more"
        open={optionsOpen || badSlug || taken}
        onToggle={(event) => {
          setOptionsOpen(event.currentTarget.open);
        }}
      >
        <summary>
          <Icon name="chevron-right" size="sm" className="ft-new-more-caret" />
          <span>More options</span>
          <span className="ah-small ah-subtle">
            · Slug: {slug || "Claude picks"} · Size: {sizeLabel(size)}
          </span>
        </summary>
        <div className="ft-new-more-body">
          <div className="ft-new-field">
            <label htmlFor={ids.slug} className="ft-new-label">
              Slug (optional)
            </label>
            <input
              id={ids.slug}
              className="ah-input ah-mono"
              value={slug}
              placeholder="orders-csv-export"
              aria-invalid={badSlug || taken || undefined}
              aria-describedby={ids.slugHint}
              onChange={(event) => {
                setSlug(event.target.value.trim());
              }}
            />
            <FieldHint
              id={ids.slugHint}
              error={
                badSlug
                  ? "Lowercase letters, digits and dashes, starting with a letter."
                  : taken
                    ? "A feature with this slug already exists."
                    : null
              }
            >
              Left empty, Claude picks one.
            </FieldHint>
          </div>
          <div className="ft-new-field">
            <span className="ft-new-label">Size</span>
            <SegmentedControl
              label="Size"
              options={SIZES.map((option) => ({ id: option.id || ASK, label: option.label }))}
              value={size || ASK}
              onChange={(id) => {
                setSize(id === ASK ? "" : id);
              }}
            />
            <span className="ft-new-hint">{SIZES.find((option) => option.id === size)?.hint}</span>
          </div>
        </div>
      </details>

      <div className="ft-new-actions">
        <Button
          type="submit"
          variant="primary"
          icon="message-square"
          disabled={!ready}
          aria-describedby={ids.reason}
        >
          {discussion.pending ? "Starting…" : "Start with Claude"}
        </Button>
        <span id={ids.reason} className="ah-small ah-subtle">
          {why ?? "Opens the Discuss panel. Claude asks before writing any file."}
        </span>
        <span className="ft-new-kbd ah-small ah-subtle" aria-hidden="true">
          <Kbd>Ctrl</Kbd> or <Kbd>⌘</Kbd> <Kbd>Enter</Kbd>
        </span>
      </div>
      {startError && (
        <p className="ft-new-hint" data-error role="alert">
          <Icon name="circle-x" size="sm" />
          {startError}
        </p>
      )}
    </form>
  );
}

function FieldHint({
  id,
  error,
  children,
}: {
  id: string;
  error: string | null;
  children: string;
}) {
  return error ? (
    <span id={id} className="ft-new-hint" data-error>
      <Icon name="circle-x" size="sm" />
      {error}
    </span>
  ) : (
    <span id={id} className="ft-new-hint">
      {children}
    </span>
  );
}

function SentCard({
  sent,
  project,
  panelOpen,
  onOpenPanel,
  onAnother,
}: {
  sent: SentRequest;
  project: string;
  panelOpen: boolean;
  onOpenPanel: () => void;
  onAnother: () => void;
}) {
  const features = useFeatures(project || null);
  // While waiting, reread the records often (the API rereads the hub's files): the same query.
  useApi("/api/v1/features", { query: { project: project || null } }, { refetchInterval: 3_000 });
  const items = (features.data?.items ?? []).filter((f) => f.project === project);
  const created = items.find((f) => (sent.slug ? f.slug === sent.slug : !sent.known.has(f.slug)));

  return (
    <>
      <section className="ah-card ft-new-sent" aria-label="Sent to Claude">
        <h2 className="ah-h3">Sent to Claude</h2>
        {sent.idea.trim() !== "" && <p className="ft-new-sent-idea">{sent.idea.trim()}</p>}
        <AttachmentList images={sent.images} files={sent.files} label="Sent with the request" />
        <p className="ah-small ah-muted">
          Issue: {sent.issue || "none"} · Slug: {sent.slug || "Claude picks"} · Size:{" "}
          {sizeLabel(sent.size)}
        </p>
        <div role="status" className="ft-new-status">
          {created ? (
            <>
              <Icon name="circle-check" className="ft-new-done" />
              <span>
                <span className="ah-mono">{created.slug}</span> has its record.
              </span>
              <AppLink href={featureHref(created)}>Open {created.slug}</AppLink>
            </>
          ) : (
            <>
              <Icon name="message-square" />
              <span>Claude is working on the brief with you in the panel.</span>
              {!panelOpen && (
                <Button size="sm" onClick={onOpenPanel}>
                  Open the panel
                </Button>
              )}
              <AppLink href={`/agent-sessions/${encodeURIComponent(sent.sessionId)}`}>
                Open the full chat
              </AppLink>
            </>
          )}
        </div>
      </section>
      <div>
        <Button variant="ghost" icon="plus" onClick={onAnother}>
          Start another feature
        </Button>
      </div>
    </>
  );
}
