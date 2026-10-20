import { useId, useState } from "react";

import { AppLink, Button, Icon } from "../../components";
import { useApi } from "../../lib/api";
import { useScope } from "../../lib/scope";
import { writeStored } from "../../lib/storage";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { useDiscuss, useDiscussTarget, type DiscussTarget } from "../../shell/discuss";
import { featureHref } from "./FeatureChip";
import { useFeatures } from "./queries";

/* New feature: a short form that writes the request, and Claude (the Discuss panel, in the hub
 * folder) runs the hub's golden path with the owner, from the brief to the spec. The page watches
 * the feature records for the new one. */

const KEBAB = /^[a-z][a-z0-9-]*$/;
const ISSUE = /^[A-Za-z][A-Za-z0-9]*-\d+$/;

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

const BRIEF = [
  "This is the start of a new feature, run on the hub's golden path: the `feature` skill of this hub (`plugin/hub-workflow/skills/feature/SKILL.md`, or `.claude/skills/feature/SKILL.md` when the plugin is not there). Read it first and follow it here, in this conversation, from step 0 (the brief).",
  "Ask me one question at a time, as the skill says, and stop at each of its gates for my approval. Writing the files the skill asks for (the tracker issue's brief, `brain/features/<slug>/spec.md`, its summary) is part of this request; show me each one before it is written.",
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

/** `/features/new`: say the idea, then Claude walks the golden path with you in the panel. */
export function NewFeatureScreen() {
  const [scope] = useScope();
  const projectsQuery = useApi("/api/v1/projects");
  const projects = (projectsQuery.data?.items ?? []).map((item) => item.name);
  const [project, setProject] = useState<string>(scope ?? "");
  const chosenProject = project || (projects[0] ?? "");
  const [idea, setIdea] = useState("");
  const [issue, setIssue] = useState("");
  const [size, setSize] = useState("");
  const [slug, setSlug] = useState("");
  const [target, setTarget] = useState<DiscussTarget | null>(null);
  // The slugs there were when Claude was asked: the first one after that is the new feature.
  const [known, setKnown] = useState<ReadonlySet<string>>(() => new Set());
  const { setOpen } = useDiscuss();
  const ids = {
    project: useId(),
    idea: useId(),
    issue: useId(),
    size: useId(),
    slug: useId(),
    slugHint: useId(),
    issueHint: useId(),
  };

  const features = useFeatures(chosenProject || null);
  // Once asked, reread the records often (the API rereads the hub's files): the same query, faster.
  useApi(
    "/api/v1/features",
    { query: { project: chosenProject || null } },
    { enabled: target !== null, refetchInterval: 3_000 },
  );
  const items = (features.data?.items ?? []).filter((f) => f.project === chosenProject);
  // Once asked, the first record that was not there before is the new feature (or the slug asked).
  const created = target
    ? items.find((f) => (slug ? f.slug === slug : !known.has(f.slug)))
    : undefined;

  useDiscussTarget(target);

  const badSlug = slug !== "" && !KEBAB.test(slug);
  const badIssue = issue !== "" && !ISSUE.test(issue);
  const taken = slug !== "" && target === null && items.some((f) => f.slug === slug);
  const ready =
    chosenProject !== "" &&
    (idea.trim().length >= 10 || (issue !== "" && !badIssue)) &&
    !badSlug &&
    !badIssue &&
    !taken;

  const ask = () => {
    const message = composeFeatureMessage({ idea, issue, size, slug });
    const key = newFeatureKey(chosenProject);
    setKnown(new Set(items.map((f) => f.slug)));
    // The panel's composer starts with the request; the owner reads it and sends.
    writeStored(`ah.chat.draft.discuss.${key}`, JSON.stringify(message));
    setTarget({
      key,
      project: chosenProject,
      kind: "New feature",
      title: slug || issue || "a new feature",
      brief: BRIEF,
      openOnArrive: true,
      starters: [{ label: "Start it", message }],
    });
    setOpen(true);
  };

  return (
    <div style={{ padding: "16px 32px 40px", minHeight: "100%" }} className="ah-stack">
      <Breadcrumbs items={[{ label: "Features", href: "/features" }, { label: "New" }]} />
      <h1 className="ah-h1">New feature</h1>
      <p className="ah-muted" style={{ margin: 0, maxWidth: 760 }}>
        Say what you want to build. Claude starts the golden path with you in the panel: it writes
        the brief, asks one question at a time, proposes a size and drafts the spec. It stops for
        your approval at each gate, and you see each file before it is written.
      </p>
      <form
        aria-label="New feature"
        className="ah-card ah-card-body ah-stack"
        style={{ gap: 16, maxWidth: 900 }}
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) ask();
        }}
      >
        {projects.length > 1 && (
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={ids.project} className="ah-small">
              Project
            </label>
            <select
              id={ids.project}
              className="ah-input"
              value={chosenProject}
              onChange={(event) => {
                setProject(event.target.value);
              }}
            >
              {projects.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="ah-stack" style={{ gap: 4 }}>
          <label htmlFor={ids.idea} className="ah-small">
            What do you want to build?
          </label>
          <textarea
            id={ids.idea}
            className="ah-input"
            rows={5}
            value={idea}
            placeholder="Owners can export the orders of a period as CSV from the admin portal, with the same filters as the list."
            onChange={(event) => {
              setIdea(event.target.value);
            }}
            style={{ resize: "vertical", fontFamily: "inherit", height: "auto", minHeight: 110 }}
          />
        </div>
        <div className="ah-row ah-wrap" style={{ gap: 16, alignItems: "flex-start" }}>
          <div className="ah-stack ah-grow" style={{ gap: 4, minWidth: 180 }}>
            <label htmlFor={ids.issue} className="ah-small">
              Tracker issue (optional)
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
            <span
              id={ids.issueHint}
              className="ah-small"
              style={{ color: badIssue ? "var(--failed)" : "var(--text-subtle)" }}
            >
              {badIssue
                ? "An issue id, like DEMO-1600."
                : "Left empty, Claude writes the brief with you and creates it."}
            </span>
          </div>
          <div className="ah-stack ah-grow" style={{ gap: 4, minWidth: 180 }}>
            <label htmlFor={ids.slug} className="ah-small">
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
            <span
              id={ids.slugHint}
              className="ah-small"
              style={{ color: badSlug || taken ? "var(--failed)" : "var(--text-subtle)" }}
            >
              {badSlug
                ? "Lowercase letters, digits and dashes, starting with a letter."
                : taken
                  ? "A feature with this slug already exists."
                  : "Left empty, Claude picks one."}
            </span>
          </div>
          <div className="ah-stack ah-grow" style={{ gap: 4, minWidth: 180 }}>
            <label htmlFor={ids.size} className="ah-small">
              Size
            </label>
            <select
              id={ids.size}
              className="ah-input"
              value={size}
              onChange={(event) => {
                setSize(event.target.value);
              }}
            >
              {SIZES.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
            <span className="ah-small ah-subtle">
              {SIZES.find((option) => option.id === size)?.hint}
            </span>
          </div>
        </div>
        <div className="ah-row" style={{ gap: 12 }}>
          <Button type="submit" variant="primary" icon="message-square" disabled={!ready}>
            Start with Claude
          </Button>
          {target && !created && (
            <span role="status" className="ah-small ah-subtle">
              Claude has your request in the panel: send it, then answer its questions there. This
              page notices the feature as soon as its record is written.
            </span>
          )}
        </div>
        {created && (
          <div role="status" className="ah-row ah-small" style={{ gap: 8 }}>
            <Icon name="circle-check" style={{ color: "var(--done, var(--accent))" }} />
            <span>
              <span className="ah-mono">{created.slug}</span> has its record.
            </span>
            <AppLink href={featureHref(created)}>Open the feature</AppLink>
          </div>
        )}
      </form>
    </div>
  );
}
