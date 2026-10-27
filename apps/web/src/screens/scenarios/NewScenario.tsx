import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useNavigate } from "react-router";

import { AppLink, Button, EmptyState, Icon } from "../../components";
import { apiPut, useApi, type ApiProblem } from "../../lib/api";
import { useScope } from "../../lib/scope";
import { writeStored } from "../../lib/storage";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { useDiscuss, useDiscussTarget, type DiscussTarget } from "../../shell/discuss";
import { NEW_SCENARIO_BRIEF } from "./brief";
import { Page } from "./parts";
import { scenarioHref, useScenarios } from "./queries";

/* New scenario: a guided form that writes the request, and Claude (the Discuss panel, in the
 * hub folder) writes the scenario and the actions it needs, then checks that they load. The page
 * watches the scenario catalog for the new name, as New workflow does for workflows. */

const KEBAB = /^[a-z][a-z0-9-]*$/;
const NEW_PACK = "__new__";

const EXAMPLES: readonly { label: string; text: string }[] = [
  {
    label: "Create, then wait for a state",
    text: "Create a test record through the service's API, wait until it shows as processed, then check that the expected file was produced.",
  },
  {
    label: "Health check",
    text: "Call each service's health endpoint and expect every one to answer OK within 30 seconds.",
  },
  {
    label: "Queue round trip",
    text: "Send a message to the queue, then wait until the consumer has processed it and its result is stored.",
  },
];

function composeMessage(fields: {
  name: string;
  what: string;
  environment: string;
  pack: string;
}): string {
  const lines = ["Create a new scenario in this hub."];
  lines.push(
    fields.name
      ? `Name: ${fields.name}`
      : "Name: pick a short kebab-case name and tell me which one.",
  );
  lines.push(
    fields.pack
      ? `Pack: ${fields.pack} (scenarios/${fields.pack}/, actions/${fields.pack}/)`
      : "Pack: pick a fitting pack (an existing one if it fits) and tell me which one.",
  );
  if (fields.environment) lines.push(`Environment: ${fields.environment}`);
  lines.push("", "What it should check:", fields.what.trim());
  return lines.join("\n");
}

/** `/scenarios/new`: describe the scenario, then Claude writes it into the hub. */
export function NewScenarioScreen() {
  const [scope] = useScope();
  const projectsQuery = useApi("/api/v1/projects");
  const projects = (projectsQuery.data?.items ?? []).map((item) => item.name);
  const [project, setProject] = useState<string>(scope ?? "");
  const chosenProject = project || (projects[0] ?? "");
  const [name, setName] = useState("");
  const [what, setWhat] = useState("");
  const [environment, setEnvironment] = useState("");
  const [packChoice, setPackChoice] = useState("");
  const [newPack, setNewPack] = useState("");
  const [target, setTarget] = useState<DiscussTarget | null>(null);
  const { setOpen } = useDiscuss();
  const ids = {
    project: useId(),
    name: useId(),
    what: useId(),
    environment: useId(),
    pack: useId(),
    newPack: useId(),
    hint: useId(),
  };

  const config = useApi(
    "/api/v1/projects/{project}/config",
    { path: { project: chosenProject } },
    { enabled: chosenProject !== "" },
  );
  const environments = config.data?.environments.environments ?? [];

  // The packs this project's scenarios already use; once asked, watch for the new scenario.
  const catalog = useScenarios(chosenProject || null);
  const packs = [...new Set((catalog.data?.items ?? []).map((item) => item.pack))].sort();
  const watched = useApi(
    "/api/v1/scenarios",
    { query: { project: chosenProject || null } },
    { enabled: target !== null, refetchInterval: 3_000 },
  );
  const created =
    target && name ? watched.data?.items.find((item) => item.name === name) : undefined;

  useDiscussTarget(target);

  const pack = packChoice === NEW_PACK ? newPack : packChoice;
  const badName = name !== "" && !KEBAB.test(name);
  const badPack = packChoice === NEW_PACK && newPack !== "" && !KEBAB.test(newPack);
  const ready = chosenProject !== "" && what.trim().length >= 10 && !badName && !badPack;

  // A blank scenario, written as blocks: one stage holding one manual block to replace, written
  // by the builder's save (no Claude).
  const navigate = useNavigate();
  const blankReady = chosenProject !== "" && KEBAB.test(name) && KEBAB.test(pack);
  const blank = useMutation<unknown, ApiProblem>({
    mutationFn: () =>
      apiPut(
        "/api/v1/scenarios/{project}/{name}",
        {
          pack,
          base_content_hash: null,
          document: {
            version: 2,
            kind: "scenario",
            name,
            description: what.trim() || `What ${name} checks`,
            stages: [
              {
                name: "First stage",
                steps: [{ you: "Replace this block with the first step of the scenario." }],
              },
            ],
          },
        },
        { path: { project: chosenProject, name } },
      ),
    onSuccess: () => {
      void navigate(scenarioHref(chosenProject, name));
    },
  });

  const ask = () => {
    const message = composeMessage({ name, what, environment, pack });
    const key = `scenario-new:${chosenProject}:${String(Date.now())}`;
    // The panel's composer starts with the request; the owner reads it and sends.
    writeStored(`ah.chat.draft.discuss.${key}`, JSON.stringify(message));
    setTarget({
      key,
      project: chosenProject,
      kind: "New scenario",
      title: name || "a new scenario",
      brief: NEW_SCENARIO_BRIEF,
      openOnArrive: true,
      starters: [{ label: "Create it", message }],
    });
    setOpen(true);
  };

  const breadcrumbs = (
    <Breadcrumbs items={[{ label: "Scenarios", href: "/scenarios" }, { label: "New" }]} />
  );
  if (projectsQuery.data && projects.length === 0) {
    return (
      <Page>
        {breadcrumbs}
        <div className="ah-card">
          <EmptyState icon="folder" title="No project yet." command="./hub init">
            A scenario lives in a project&apos;s hub. Add a hub first.
          </EmptyState>
        </div>
      </Page>
    );
  }

  return (
    <Page>
      {breadcrumbs}
      <h1 className="ah-h1">New scenario</h1>
      <p className="ah-muted" style={{ margin: 0, maxWidth: 760 }}>
        Say what the scenario should drive and check, in your own words. Claude turns it into steps
        (actions, expectations, your approvals), writes the files in the hub and checks that they
        load. You see each file change before it is written.
      </p>
      <div className="ah-row ah-wrap" style={{ gap: 24, alignItems: "flex-start" }}>
        <form
          aria-label="New scenario"
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
                  setEnvironment("");
                  setPackChoice("");
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
              What should it check?
            </label>
            <textarea
              id={ids.what}
              className="ah-input"
              rows={5}
              value={what}
              placeholder="Create a test order, wait until it is paid, then check that its invoice exists."
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
          <div className="ah-row ah-wrap" style={{ gap: 16, alignItems: "flex-start" }}>
            <div className="ah-stack ah-grow" style={{ gap: 4, minWidth: 200 }}>
              <label htmlFor={ids.environment} className="ah-small">
                Environment
              </label>
              <select
                id={ids.environment}
                className="ah-input"
                value={environment}
                onChange={(event) => {
                  setEnvironment(event.target.value);
                }}
              >
                <option value="">Chosen when you plan it</option>
                {environments.map((env) => (
                  <option key={env.name} value={env.name}>
                    {env.name} · {env.production ? "production" : `access ${env.access}`}
                  </option>
                ))}
              </select>
              <span className="ah-small ah-subtle">
                {environments.length === 0
                  ? "No environment declared yet: add one in Environments to run it."
                  : "Where it runs by default; a plan can pick another."}
              </span>
            </div>
            <div className="ah-stack ah-grow" style={{ gap: 4, minWidth: 200 }}>
              <label htmlFor={ids.pack} className="ah-small">
                Pack
              </label>
              <select
                id={ids.pack}
                className="ah-input"
                value={packChoice}
                onChange={(event) => {
                  setPackChoice(event.target.value);
                }}
              >
                <option value="">Claude picks one</option>
                {packs.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
                <option value={NEW_PACK}>A new pack…</option>
              </select>
              {packChoice === NEW_PACK && (
                <>
                  <label htmlFor={ids.newPack} className="ah-sr">
                    New pack name
                  </label>
                  <input
                    id={ids.newPack}
                    className="ah-input ah-mono"
                    value={newPack}
                    placeholder="orders"
                    aria-invalid={badPack || undefined}
                    onChange={(event) => {
                      setNewPack(event.target.value.trim());
                    }}
                  />
                </>
              )}
              <span
                className="ah-small"
                style={{ color: badPack ? "var(--failed)" : "var(--text-subtle)" }}
              >
                {badPack
                  ? "Lowercase letters, digits and dashes, starting with a letter."
                  : "A folder that groups scenarios with the actions they call."}
              </span>
            </div>
          </div>
          <div className="ah-stack" style={{ gap: 4, maxWidth: 420 }}>
            <label htmlFor={ids.name} className="ah-small">
              Name (optional)
            </label>
            <input
              id={ids.name}
              className="ah-input ah-mono"
              value={name}
              placeholder="record-roundtrip"
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
          <div className="ah-row" style={{ gap: 12 }}>
            <Button type="submit" variant="primary" icon="message-square" disabled={!ready}>
              Create with Claude
            </Button>
            <Button
              icon="puzzle"
              disabled={!blankReady || blank.isPending}
              title={
                blankReady
                  ? "An empty scenario you build with blocks"
                  : "Name it and choose its pack first"
              }
              onClick={() => {
                blank.mutate();
              }}
            >
              {blank.isPending ? "Creating…" : "Create it blank and build with blocks"}
            </Button>
            {blank.error && (
              <span role="alert" className="ah-small" style={{ color: "var(--failed)" }}>
                {blank.error.detail ?? blank.error.title}
              </span>
            )}
            {target && !created && (
              <span role="status" className="ah-small ah-subtle">
                Claude has your request in the panel: send it, then follow along there.
                {name && " This page notices the scenario as soon as its file loads."}
              </span>
            )}
          </div>
          {created && (
            <div role="status" className="ah-row ah-small" style={{ gap: 8 }}>
              <Icon name="circle-check" style={{ color: "var(--done, var(--accent))" }} />
              <span>
                <span className="ah-mono">{created.name}</span> loads.
              </span>
              <AppLink href={scenarioHref(created.project, created.name)}>
                Open it and plan it
              </AppLink>
            </div>
          )}
        </form>
        <aside className="ah-card ah-card-body ah-stack" style={{ gap: 10, flex: "0 1 300px" }}>
          <h2 className="ah-h3" style={{ margin: 0 }}>
            How a scenario runs
          </h2>
          <p className="ah-small ah-subtle" style={{ margin: 0 }}>
            Each step calls an <b>action</b>: a small script that reads or changes one thing in the
            environment.
          </p>
          <p className="ah-small ah-subtle" style={{ margin: 0 }}>
            An <b>expect</b> step repeats an action until what it sees is right, or times out.
          </p>
          <p className="ah-small ah-subtle" style={{ margin: 0 }}>
            Writes ask you first unless the environment allows them; production only ever reads.
          </p>
          <p className="ah-small ah-subtle" style={{ margin: 0 }}>
            New actions are drafts until committed: plan works, a run waits for the commit.
          </p>
        </aside>
      </div>
    </Page>
  );
}
