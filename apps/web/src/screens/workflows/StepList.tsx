import type { ReactNode } from "react";

import { CodeBlock, CopyButton, Icon } from "../../components";
import type { WorkflowNode } from "./queries";
import { STEP_KINDS, stepKind } from "./steps";

/* A workflow as a numbered timeline of steps in plain words: what each step does, what kind it is,
 * what it waits for and when it runs, the agent's prompt or the command, and a repeat's rounds.
 * Read from the document as written. */

type Doc = Record<string, unknown>;

function isDoc(value: unknown): value is Doc {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function docNodes(value: unknown): Doc[] {
  return Array.isArray(value) ? value.filter(isDoc) : [];
}

/** A command as one line: `hub step worktree --issue $INPUTS.issue`. */
function commandLine(node: Doc): string | null {
  if (Array.isArray(node.command)) return node.command.map(String).join(" ");
  const script = text(node.script);
  if (script) {
    const args = Array.isArray(node.args) ? ` ${node.args.map(String).join(" ")}` : "";
    return `${node.runtime === "python" ? "uv run" : "sh"} scripts/${script}${args}`;
  }
  return null;
}

/** The kind's label on a step: "AI agent", "Command", "Rounds, up to 3". */
function kindLabel(node: Doc): string {
  if (node.type === "loop_group") return `Rounds, up to ${String(node.max_iterations)}`;
  const one = STEP_KINDS[stepKind(String(node.type))].one;
  return `${(one[0] ?? "").toUpperCase()}${one.slice(1)}`;
}

function What({ node, id }: { node: Doc; id: string }): ReactNode {
  const type = String(node.type);
  const kind = stepKind(type);
  if (kind === "agent") {
    const prompt = text(node.prompt);
    const file = text(node.prompt_file);
    const model = text(node.model);
    return (
      <>
        {(model !== null || type === "loop" || file !== null) && (
          <span className="wf-step-note">
            {model && <>Model tier {model}. </>}
            {type === "loop" &&
              `Repeats its turn up to ${String(node.max_iterations)} times until done. `}
            {file && (
              <>
                Its prompt is the file <span className="ah-mono">prompts/{file}</span>.
              </>
            )}
          </span>
        )}
        {prompt && (
          <details className="wf-prompt">
            <summary>
              <Icon name="chevron-right" />
              Read the prompt
            </summary>
            <div className="wf-prompt-body">
              {/* A long prompt scrolls inside its box, so the keyboard must reach it (axe). */}
              {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
              <pre className="ah-code" tabIndex={0}>
                {prompt}
              </pre>
              <CopyButton text={prompt} label="Copy prompt" />
            </div>
          </details>
        )}
      </>
    );
  }
  if (kind === "command") {
    const line = commandLine(node);
    return line ? <CodeBlock code={line} wrap label={`Command of ${id}`} /> : null;
  }
  if (kind === "approval") {
    const message = text(node.message);
    return message ? <span>You are asked: “{message}”</span> : null;
  }
  if (kind === "include") {
    return (
      <span className="wf-step-note">
        Runs the steps of <span className="ah-mono">{String(node.include)}</span>.
      </span>
    );
  }
  return null;
}

function Step({
  number,
  node,
  after,
  prefix = "",
  inRounds = false,
  children,
}: {
  number: string;
  node: Doc;
  after: string[];
  /** A repeat's body ids are `<group>__<id>`: shown without it. */
  prefix?: string;
  inRounds?: boolean;
  children?: ReactNode;
}) {
  const bare = (id: string) => (prefix && id.startsWith(prefix) ? id.slice(prefix.length) : id);
  const id = bare(String(node.id));
  const kindName = stepKind(String(node.type));
  const kind = STEP_KINDS[kindName];
  const description = text(node.description);
  const condition = text(node.when);
  return (
    <li className="wf-step" data-kind={kindName} data-nav-row tabIndex={-1}>
      <span aria-hidden className="wf-step-node">
        {number}
      </span>
      <div className="wf-step-body">
        <span className={description ? "wf-step-title" : "wf-step-title ah-mono"}>
          <span className="ah-sr">Step {number}: </span>
          {description ?? id}
        </span>
        <span className="wf-step-kind" title={kind.hint}>
          <Icon name={kind.icon} />
          {kindLabel(node)}
          {description && (
            <>
              <span aria-hidden>·</span>
              <span className="ah-mono">{id}</span>
            </>
          )}
          {after.length > 0 && (
            <>
              <span aria-hidden>·</span>
              Waits for{" "}
              {after.map((dep) => (
                <span key={dep} className="ah-fm-chip ah-mono">
                  {bare(dep)}
                </span>
              ))}
            </>
          )}
        </span>
        {condition && (
          <span className="wf-step-cond">
            <Icon name="split" />
            <span className="wf-step-cond-label">Only when</span> <code>{condition}</code>
          </span>
        )}
        {inRounds && node.context === "fresh" && (
          <span className="wf-step-note">
            <Icon name="rotate-ccw" /> Starts afresh each round
          </span>
        )}
        <What node={node} id={id} />
        {children}
      </div>
    </li>
  );
}

/** The `after` of a step: what it waits for, when that is not simply the step before it. */
function waitsFor(node: Doc, previous: string | undefined): string[] {
  const deps = Array.isArray(node.depends_on) ? node.depends_on.map(String) : [];
  return deps.length === 1 && deps[0] === previous ? [] : deps;
}

function Rounds({ group, prefix }: { group: Doc; prefix: string }) {
  const body = docNodes(group.nodes);
  const max = String(group.max_iterations);
  const untilWhen = text(group.until_when);
  const untilBash = Array.isArray(group.until_bash) ? group.until_bash.map(String).join(" ") : null;
  return (
    <div className="wf-rounds">
      <div className="wf-rounds-rule">
        <span className="wf-step-cond">
          <Icon name="flag" />
          {untilWhen ? (
            <>
              <span className="wf-step-cond-label">Stops when</span> <code>{untilWhen}</code>
            </>
          ) : untilBash ? (
            <>
              <span className="wf-step-cond-label">Stops when</span> <code>{untilBash}</code>{" "}
              <span>passes.</span>
            </>
          ) : (
            <span>Runs all {max} rounds.</span>
          )}
        </span>
        {(untilWhen !== null || untilBash !== null) && (
          <span className="wf-step-note">
            If round {max} ends without stopping, this step fails.
          </span>
        )}
        <span className="wf-step-note">
          {group.fresh_context === true
            ? "Each round starts the agents afresh."
            : "The agents remember the previous round."}
        </span>
      </div>
      <ol aria-label={`Steps of ${String(group.id)}`} className="wf-steps">
        {body.map((node, index) => (
          <Step
            key={String(node.id)}
            number={`${prefix}.${String(index + 1)}`}
            node={node}
            prefix={`${String(group.id)}__`}
            inRounds
            after={waitsFor(node, index > 0 ? String(body[index - 1]?.id) : undefined)}
          />
        ))}
      </ol>
    </div>
  );
}

/** The workflow's steps in run order (`layers`), with the document's details of each. */
export function StepList({ layers, document }: { layers: WorkflowNode[][]; document: Doc }) {
  const written = new Map(docNodes(document.nodes).map((node) => [String(node.id), node]));
  const order = layers.flat();
  if (order.length === 0) {
    return (
      <p className="ah-muted" style={{ margin: 0 }}>
        This workflow has no steps.
      </p>
    );
  }
  return (
    <ol aria-label="Steps" className="wf-steps">
      {order.map((view, index) => {
        const node: Doc = written.get(view.id) ?? { ...view };
        const number = String(index + 1);
        return (
          <Step
            key={view.id}
            number={number}
            node={node}
            after={waitsFor(node, order[index - 1]?.id)}
          >
            {node.type === "loop_group" && <Rounds group={node} prefix={number} />}
          </Step>
        );
      })}
    </ol>
  );
}
