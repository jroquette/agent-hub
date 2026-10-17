import { useId, useState } from "react";

import { AppLink, Button, Icon } from "../../components";
import { writeStored } from "../../lib/storage";
import { useScope } from "../../lib/scope";
import { useApi } from "../../lib/api";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { useDiscuss, useDiscussTarget, type DiscussTarget } from "../../shell/discuss";
import { STEP_KINDS, type StepKind } from "./steps";

/* New workflow: a guided form that writes the request, and Claude (the Discuss panel, in the
 * hub folder) writes the YAML and validates it. The page watches the catalog for the new name. */

const KEBAB = /^[a-z][a-z0-9-]*$/;

const EXAMPLES: readonly { label: string; text: string }[] = [
  {
    label: "Fix a failing test",
    text: "Given a failing test name, an AI agent finds the cause and fixes it, then the repo's tests run; repeat until they pass, at most 3 rounds.",
  },
  {
    label: "Review a branch",
    text: "Given a branch, two AI agents review it (one for the spec, one for code quality), then a script joins their verdicts into one report.",
  },
  {
    label: "Release notes",
    text: "Given a version tag, collect the merged PRs since the last tag with git, an AI agent writes the release notes, then I approve them before they are saved.",
  },
];

const OPTIONS: readonly { id: string; kind: StepKind; label: string; ask: string }[] = [
  {
    id: "approval",
    kind: "approval",
    label: "Ask for my approval before it finishes",
    ask: "Pause for my approval (an approval step) before the last step.",
  },
  {
    id: "rounds",
    kind: "repeat",
    label: "Repeat until the checks pass",
    ask: "Repeat the work and its check in rounds (a loop_group), at most 3, until the check passes.",
  },
  {
    id: "pr",
    kind: "command",
    label: "Open a pull request at the end",
    ask: "End by committing and opening a pull request with the hub step commands, as the built-in deliver does.",
  },
];

const BRIEF = [
  "Workflows are YAML files at `workflows/<pack>/<name>.yaml` in this hub folder (a pack is a folder; long prompts go in `workflows/<pack>/prompts/`, scripts in `workflows/<pack>/scripts/`).",
  "Format (agent-hub workflow schema v1): `version: 1`, `name` (kebab-case, the file stem), `description` (one line for people), `revision: 1`, `inputs` (name → {type, required, description}), `nodes` (each has `id`, `type`, optional `description`, `depends_on`, `when`).",
  "Node types: `agent` (one Claude session: `prompt` or `prompt_file`), `shell` (`command` argv list, no shell), `script` (`runtime` sh|python, `script`), `loop` (an agent turn repeated, `max_iterations` + `until`/`until_field`/`until_bash`), `loop_group` (`nodes` body repeated, `max_iterations` + `until_when`/`until_bash`), `approval` (`message`, pauses for the owner), `wait`, `halt`, `include` (another workflow of the pack).",
  "Inputs are read as `$INPUTS.<name>`, a node's output as `$<id>.output`. Give every node a one-line `description`: the web app shows it to the owner.",
  "Look at the existing ones first (`hub workflow list`), reuse their patterns, and check yours with `hub workflow validate <name>` until it reports no problem. Then say in two or three lines what it does, step by step.",
].join("\n");

function composeMessage(fields: {
  name: string;
  what: string;
  base: string;
  options: readonly string[];
}): string {
  const lines = ["Create a new workflow in this hub."];
  lines.push(
    fields.name
      ? `Name: ${fields.name}`
      : "Name: pick a short kebab-case name and tell me which one.",
  );
  lines.push("", "What it should do:", fields.what.trim());
  if (fields.base) {
    lines.push(
      "",
      `Start from a copy of the workflow \`${fields.base}\` and adapt it (a new name; do not change the original).`,
    );
  }
  const asks = OPTIONS.filter((o) => fields.options.includes(o.id)).map((o) => `- ${o.ask}`);
  if (asks.length > 0) lines.push("", "It should also:", ...asks);
  return lines.join("\n");
}

/** `/workflows/new`: describe the workflow, then Claude writes it into the hub. */
export function NewWorkflowScreen() {
  const [scope] = useScope();
  const catalog = useApi("/api/v1/workflows", { query: { project: null } });
  const items = catalog.data?.items ?? [];
  const projects = [...new Set(items.map((item) => item.project))];
  const [project, setProject] = useState<string>(scope ?? "");
  const chosenProject = project || (projects[0] ?? "");
  const [name, setName] = useState("");
  const [what, setWhat] = useState("");
  const [base, setBase] = useState("");
  const [options, setOptions] = useState<string[]>([]);
  const [target, setTarget] = useState<DiscussTarget | null>(null);
  const { setOpen } = useDiscuss();
  const ids = { project: useId(), name: useId(), what: useId(), base: useId(), hint: useId() };

  // Once asked, watch the catalog for the new workflow (the API rereads the hub's files).
  const watched = useApi(
    "/api/v1/workflows",
    { query: { project: chosenProject || null } },
    { enabled: target !== null, refetchInterval: 3_000 },
  );
  const created =
    target && name ? watched.data?.items.find((item) => item.name === name) : undefined;

  useDiscussTarget(target);

  const badName = name !== "" && !KEBAB.test(name);
  const ready = chosenProject !== "" && what.trim().length >= 10 && !badName;
  const bases = items.filter((item) => item.project === chosenProject);

  const ask = () => {
    const message = composeMessage({ name, what, base, options });
    const key = `workflow-new:${chosenProject}:${String(Date.now())}`;
    // The panel's composer starts with the request; the owner reads it and sends.
    writeStored(`ah.chat.draft.discuss.${key}`, JSON.stringify(message));
    setTarget({
      key,
      project: chosenProject,
      kind: "New workflow",
      title: name || "a new workflow",
      brief: BRIEF,
      openOnArrive: true,
      starters: [{ label: "Create it", message }],
    });
    setOpen(true);
  };

  return (
    <div style={{ padding: "16px 32px 40px", minHeight: "100%" }} className="ah-stack">
      <Breadcrumbs items={[{ label: "Workflows", href: "/workflows" }, { label: "New" }]} />
      <h1 className="ah-h1">New workflow</h1>
      <p className="ah-muted" style={{ margin: 0, maxWidth: 760 }}>
        Say what the workflow should do in your own words. Claude turns it into steps (AI agents,
        commands, your approvals), writes the file in the hub and checks that it loads. You see each
        file change before it is written.
      </p>
      <div className="ah-row ah-wrap" style={{ gap: 24, alignItems: "flex-start" }}>
        <form
          aria-label="New workflow"
          className="ah-card ah-card-body ah-stack"
          style={{ gap: 16, flex: "1 1 520px", maxWidth: 900 }}
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
                  setBase("");
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
            <label htmlFor={ids.what} className="ah-small">
              What should it do?
            </label>
            <textarea
              id={ids.what}
              className="ah-input"
              rows={5}
              value={what}
              placeholder="Given an issue, an AI agent implements it, the tests run, and I approve before a PR is opened."
              onChange={(event) => {
                setWhat(event.target.value);
              }}
              style={{ resize: "vertical", fontFamily: "inherit", height: "auto", minHeight: 110 }}
            />
            <span className="ah-row ah-wrap" style={{ gap: 6 }}>
              <span className="ah-small ah-subtle">Examples:</span>
              {EXAMPLES.map((example) => (
                <Button
                  key={example.label}
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setWhat(example.text);
                  }}
                >
                  {example.label}
                </Button>
              ))}
            </span>
          </div>
          <fieldset className="ah-stack" style={{ gap: 6, border: 0, padding: 0, margin: 0 }}>
            <legend className="ah-small" style={{ marginBottom: 6 }}>
              Also
            </legend>
            {OPTIONS.map((option) => (
              <label key={option.id} className="ah-row ah-small" style={{ gap: 8 }}>
                <input
                  type="checkbox"
                  checked={options.includes(option.id)}
                  onChange={(event) => {
                    setOptions((current) =>
                      event.target.checked
                        ? [...current, option.id]
                        : current.filter((id) => id !== option.id),
                    );
                  }}
                />
                <Icon name={STEP_KINDS[option.kind].icon} size="sm" />
                {option.label}
              </label>
            ))}
          </fieldset>
          <div className="ah-row ah-wrap" style={{ gap: 16, alignItems: "flex-start" }}>
            <div className="ah-stack ah-grow" style={{ gap: 4, minWidth: 200 }}>
              <label htmlFor={ids.name} className="ah-small">
                Name (optional)
              </label>
              <input
                id={ids.name}
                className="ah-input ah-mono"
                value={name}
                placeholder="fix-failing-test"
                aria-invalid={badName || undefined}
                aria-describedby={ids.hint}
                onChange={(event) => {
                  setName(event.target.value.trim());
                }}
              />
              <span
                id={ids.hint}
                className="ah-small"
                style={{ color: badName ? "var(--failed)" : "var(--text-subtle)" }}
              >
                {badName
                  ? "Lowercase letters, digits and dashes, starting with a letter."
                  : "Left empty, Claude picks one."}
              </span>
            </div>
            <div className="ah-stack ah-grow" style={{ gap: 4, minWidth: 200 }}>
              <label htmlFor={ids.base} className="ah-small">
                Start from
              </label>
              <select
                id={ids.base}
                className="ah-input"
                value={base}
                onChange={(event) => {
                  setBase(event.target.value);
                }}
              >
                <option value="">Nothing (from scratch)</option>
                {bases.map((item) => (
                  <option key={item.name} value={item.name}>
                    A copy of {item.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="ah-row" style={{ gap: 12 }}>
            <Button type="submit" variant="primary" icon="message-square" disabled={!ready}>
              Create with Claude
            </Button>
            {target && !created && (
              <span role="status" className="ah-small ah-subtle">
                Claude has your request in the panel: send it, then follow along there.
                {name && " This page notices the workflow as soon as its file loads."}
              </span>
            )}
          </div>
          {created && (
            <div role="status" className="ah-row ah-small" style={{ gap: 8 }}>
              <Icon name="circle-check" style={{ color: "var(--done, var(--accent))" }} />
              <span>
                <span className="ah-mono">{created.name}</span> loads.
              </span>
              <AppLink
                href={`/workflows/${encodeURIComponent(created.project)}/${encodeURIComponent(created.name)}`}
              >
                See its steps
              </AppLink>
            </div>
          )}
        </form>
        <aside className="ah-card ah-card-body ah-stack" style={{ gap: 10, flex: "0 1 300px" }}>
          <h2 className="ah-h3" style={{ margin: 0 }}>
            Building blocks
          </h2>
          {(["agent", "command", "approval", "repeat", "wait"] as const).map((kind) => (
            <div key={kind} className="ah-row" style={{ gap: 8, alignItems: "flex-start" }}>
              <Icon name={STEP_KINDS[kind].icon} style={{ marginTop: 2 }} />
              <span className="ah-small ah-subtle">{STEP_KINDS[kind].hint}</span>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
}
