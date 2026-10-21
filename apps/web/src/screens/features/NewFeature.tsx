import "../agent-session/agent-session.css";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import {
  AppLink,
  AttachButton,
  AttachmentList,
  Banner,
  Button,
  EmptyState,
  Icon,
  Kbd,
  Skeleton,
  useAttachmentDrop,
  useMessageAttachments,
  type AttachedFile,
  type AttachedImage,
} from "../../components";
import { ApiProblem, useApi } from "../../lib/api";
import { cx } from "../../lib/cx";
import { useScope } from "../../lib/scope";
import { useAutoGrow } from "../../lib/useAutoGrow";
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

/* New feature: the brief (text, images, PDFs, text files) is the screen, the options sit beside
 * it. One press starts the conversation in the project's hub folder and opens the Discuss panel
 * on it: Claude runs the hub's golden path with the owner, from the brief to the spec. The page
 * then watches the feature records for the new one. */

const KEBAB = /^[a-z][a-z0-9-]*$/;
const ISSUE = /^[A-Za-z][A-Za-z0-9]*-\d+$/;
const MIN_IDEA = 10;
/** The brief grows with its text up to this share of the viewport, then scrolls. */
const BRIEF_HEIGHT_SHARE = 0.5;

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
const sizeLabel = (size: string) => SIZES.find((option) => option.id === size)?.label ?? size;

const NEXT_STEPS = [
  "Claude reads your brief and what you attached.",
  "It asks one question at a time, in the panel.",
  "It drafts the spec and shows you each file before writing it.",
];

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
  // A new form after "Start another feature" takes focus in its brief.
  const [round, setRound] = useState(0);
  const { open, setOpen } = useDiscuss();
  useDiscussTarget(target);

  const breadcrumbs = (
    <Breadcrumbs items={[{ label: "Features", href: "/features" }, { label: "New" }]} />
  );
  if (projectsQuery.data && projects.length === 0) {
    return (
      <div className="ft-new">
        {breadcrumbs}
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
      {breadcrumbs}
      <header className="ft-new-head">
        <div>
          <h1 className="ah-h1">New feature</h1>
          <p className="ft-new-lead">Describe what to build and attach what Claude should see.</p>
        </div>
        {projectsQuery.isPending ? (
          <Skeleton width={110} height={32} radius={999} />
        ) : (
          projects.length > 1 &&
          !sent && <ProjectSelect projects={projects} value={chosenProject} onChange={setProject} />
        )}
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
            setOpen(false);
            setSent(null);
            setTarget(null);
            setRound((n) => n + 1);
          }}
        />
      ) : chosenProject === "" ? (
        // The brief's draft is kept per project: the form waits for it to be known.
        <div className="ft-new-form" aria-hidden="true">
          <Skeleton height={300} radius={28} />
          <Skeleton height={430} radius={12} />
        </div>
      ) : (
        <BriefForm
          key={`${chosenProject}:${String(round)}`}
          project={chosenProject}
          focusOnOpen={round > 0}
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
  // The project pill of New session: the site's way to say where a request runs.
  return (
    <label className="as-pill as-new-pill ft-new-project">
      <Icon name="folder-kanban" size="sm" />
      <select
        aria-label="Project"
        className="as-pill-select"
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
      <span className="as-pill-value" aria-hidden="true">
        {value}
      </span>
      <Icon name="chevron-down" size="sm" className="as-pill-caret" />
    </label>
  );
}

function BriefForm({
  project,
  focusOnOpen,
  onStarted,
}: {
  project: string;
  focusOnOpen: boolean;
  onStarted: (request: SentRequest, target: DiscussTarget) => void;
}) {
  const { text: idea, setText: setIdea, accepted } = useDraft(`feature-new.${project}`);
  const [issueInput, setIssueInput] = useState("");
  const [size, setSize] = useState("");
  const [slug, setSlug] = useState("");
  const [attachError, setAttachError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const issueField = useRef<HTMLInputElement | null>(null);
  const slugField = useRef<HTMLInputElement | null>(null);
  const focusBox = () => box.current?.focus({ preventScroll: true });
  const discussion = useStartDiscussion(project || null);
  const attachments = useMessageAttachments({
    acceptsImages: true,
    acceptsFiles: true,
    onError: setAttachError,
  });
  const { dragging, dropProps } = useAttachmentDrop(attachments, { onAdded: focusBox });
  useAutoGrow(box, idea, BRIEF_HEIGHT_SHARE);
  useEffect(() => {
    if (focusOnOpen) box.current?.focus({ preventScroll: true });
  }, [focusOnOpen]);
  const features = useFeatures(project || null);
  const items = (features.data?.items ?? []).filter((f) => f.project === project);
  const ids = {
    idea: useId(),
    issue: useId(),
    issueHint: useId(),
    slug: useId(),
    slugHint: useId(),
    size: useId(),
    sizeHint: useId(),
    reason: useId(),
    error: useId(),
    options: useId(),
    next: useId(),
  };

  // The issue is read as typed; it is normalized only where it is used.
  const issue = issueInput.trim().toUpperCase();
  const badSlug = slug !== "" && !KEBAB.test(slug);
  const badIssue = issue !== "" && !ISSUE.test(issue);
  const taken = slug !== "" && items.some((f) => f.slug === slug);
  const hasIdea = idea.trim().length >= MIN_IDEA;
  const hasIssue = issue !== "" && !badIssue;
  // The first reason that holds, said next to the button (and read with it).
  const why =
    discussion.unavailable !== null
      ? `${discussion.unavailable.title}.`
      : attachments.reading > 0
        ? "Wait for the files to be read."
        : !hasIdea && !hasIssue
          ? attachments.count > 0
            ? "Add a sentence on what to build with the attachments."
            : "Write at least a sentence, or give an issue."
          : badIssue
            ? "Fix the issue id in Options."
            : badSlug || taken
              ? "Fix the slug in Options."
              : discussion.reason;
  const ready = why === null && !discussion.pending;

  /** A press while not ready says why where it can be fixed: focus goes to the field at fault. */
  const focusFault = () => {
    if (!hasIdea && !hasIssue) focusBox();
    else if (badIssue) issueField.current?.focus();
    else if (badSlug || taken) slugField.current?.focus();
  };

  const start = () => {
    if (discussion.pending) return;
    setAttachError(null); // An old refusal must not hide what this press says.
    if (!ready) {
      focusFault();
      return;
    }
    const target: DiscussTarget = {
      key: newFeatureKey(project),
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
        : "Describe the feature: who it is for, what they should be able to do, and why.";

  const startError =
    discussion.error instanceof ApiProblem
      ? (discussion.error.detail ?? discussion.error.title)
      : discussion.error
        ? "Could not start the conversation. Try again."
        : null;

  const errors = [attachError, startError].filter((error) => error !== null);

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
      <div className="ft-new-main">
        {discussion.unavailable && (
          <Banner tone="warning" boxed>
            <b>{discussion.unavailable.title}.</b> {discussion.unavailable.detail}
          </Banner>
        )}
        <label htmlFor={ids.idea} className="ft-new-label">
          What do you want to build?
        </label>
        {/* Files dropped anywhere on the box join the brief; the keyboard has Attach. A press on
            the box's empty space puts the caret in the text, so the whole box reads as one field. */}
        {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
        <div
          className={cx("as-composer ft-new-brief", dragging && "as-composer-drop")}
          onMouseDown={(event) => {
            const spot = event.target as HTMLElement;
            if (spot.closest("button, a, input, textarea, label, li")) return;
            event.preventDefault();
            focusBox();
          }}
          {...dropProps}
        >
          <AttachmentList
            images={attachments.images}
            files={attachments.files}
            reading={attachments.reading}
            label="Attached to this request"
            onRemoveImage={(key) => {
              attachments.removeImage(key);
              setAttachError(null);
              focusBox();
            }}
            onRemoveFile={(key) => {
              attachments.removeFile(key);
              setAttachError(null);
              focusBox();
            }}
            onReplaceImage={attachments.replaceImage}
          />
          <textarea
            id={ids.idea}
            ref={box}
            className="ah-input as-composer-input ft-new-idea"
            rows={8}
            value={idea}
            placeholder={placeholder}
            aria-describedby={errors.length > 0 ? `${ids.error} ${ids.reason}` : ids.reason}
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
          {/* The chat composer's bottom bar: Attach on the left, Start on the right. */}
          <div className="as-composer-bar">
            <AttachButton attachments={attachments} onAdded={focusBox} className="ft-new-attach" />
            <span className="ah-small ah-subtle ft-new-drop-note">
              Paste or drop images, PDFs and text files
            </span>
            <span className="ft-new-kbd" aria-hidden="true">
              <Kbd>Ctrl</Kbd>/<Kbd>⌘</Kbd> <Kbd>Enter</Kbd>
            </span>
            <Button
              type="submit"
              variant="primary"
              icon="message-square"
              className="ft-new-start"
              aria-disabled={!ready || undefined}
              aria-busy={discussion.pending || undefined}
              aria-describedby={ids.reason}
              aria-keyshortcuts="Control+Enter Meta+Enter"
            >
              {discussion.pending ? "Starting…" : "Start with Claude"}
            </Button>
          </div>
          {errors.length > 0 && (
            <div id={ids.error} className="as-error ft-new-error" role="alert">
              {errors.map((error) => (
                <p key={error} className="ah-small">
                  <Icon name="circle-x" size="sm" />
                  {error}
                </p>
              ))}
            </div>
          )}
        </div>
        <p id={ids.reason} className="ft-new-hint ft-new-reason" aria-live="polite">
          {discussion.pending
            ? "Starting the conversation in the hub folder…"
            : (why ?? "Opens the Discuss panel. Claude asks before writing any file.")}
        </p>
      </div>

      <aside className="ft-new-side" aria-labelledby={ids.options}>
        <section className="ah-card ft-new-card">
          <header className="ft-new-card-head">
            <h2 id={ids.options} className="ah-h3">
              Options
            </h2>
            <span className="ah-small ah-subtle">All optional</span>
          </header>
          <div className="ft-new-card-body">
            <div className="ft-new-field">
              <label htmlFor={ids.issue} className="ft-new-label">
                Start from an issue
              </label>
              <input
                id={ids.issue}
                ref={issueField}
                className="ah-input ah-mono"
                placeholder="None"
                value={issueInput}
                aria-invalid={badIssue || undefined}
                aria-describedby={ids.issueHint}
                onChange={(event) => {
                  setIssueInput(event.target.value);
                }}
              />
              <FieldHint id={ids.issueHint} error={badIssue ? "An issue id, like DEMO-1600." : null}>
                Like DEMO-1600. Claude reads its brief first.
              </FieldHint>
            </div>
            <div className="ft-new-field">
              <label htmlFor={ids.slug} className="ft-new-label">
                Slug
              </label>
              <input
                id={ids.slug}
                ref={slugField}
                className="ah-input ah-mono"
                placeholder="Claude picks one"
                value={slug}
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
                Like orders-csv-export.
              </FieldHint>
            </div>
            <div className="ft-new-field">
              <label htmlFor={ids.size} className="ft-new-label">
                Size
              </label>
              <span className="ft-new-select">
                <select
                  id={ids.size}
                  className="ah-input ft-new-select-input"
                  value={size}
                  aria-describedby={ids.sizeHint}
                  onChange={(event) => {
                    setSize(event.target.value);
                  }}
                >
                  {SIZES.map((option) => (
                    <option key={option.id || "ask"} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <Icon name="chevron-down" size="sm" className="ft-new-select-caret" />
              </span>
              <p id={ids.sizeHint} className="ft-new-hint">
                {SIZES.find((option) => option.id === size)?.hint}
              </p>
            </div>
          </div>
        </section>
      </aside>

      <section className="ft-new-next" aria-labelledby={ids.next}>
        <h2 id={ids.next} className="ft-new-label">
          What happens next
        </h2>
        <ol>
          {NEXT_STEPS.map((step, index) => (
            <li key={step}>
              <span className="ft-new-step" aria-hidden="true">
                {index + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
      </section>
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
  // Closing the panel leaves focus on the button that opens it again.
  const openSpot = useRef<HTMLSpanElement | null>(null);
  const wasOpen = useRef(panelOpen);
  useEffect(() => {
    if (wasOpen.current && !panelOpen) openSpot.current?.querySelector("button")?.focus();
    wasOpen.current = panelOpen;
  }, [panelOpen]);

  return (
    <div className="ft-new-sent-wrap">
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
              <span ref={openSpot}>
                {!panelOpen && (
                  <Button size="sm" onClick={onOpenPanel}>
                    Open the panel
                  </Button>
                )}
              </span>
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
    </div>
  );
}
