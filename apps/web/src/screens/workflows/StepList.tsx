import type { ReactNode } from "react";

import { Icon } from "../../components";
import type { WorkflowNode } from "./queries";
import { STEP_KINDS, stepKind } from "./steps";

/* A workflow as a numbered list of steps in plain words: what each step is, what it does, the
 * agent's prompt or the command, and a repeat's body steps. Read from the document as written. */

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

function What({ node }: { node: Doc }): ReactNode {
  const type = String(node.type);
  const kind = stepKind(type);
  if (kind === "agent") {
    const prompt = text(node.prompt);
    const file = text(node.prompt_file);
    const model = text(node.model);
    return (
      <>
        {(model !== null || type === "loop") && (
          <span className="ah-small ah-subtle">
            {model && <>Model tier {model}. </>}
            {type === "loop" &&
              `Repeats its turn up to ${String(node.max_iterations)} times until done.`}
          </span>
        )}
        {file && (
          <span className="ah-small ah-subtle">
            Its prompt is the file <span className="ah-mono">prompts/{file}</span>.
          </span>
        )}
        {prompt && (
          <details>
            <summary className="ah-small" style={{ cursor: "pointer", color: "var(--accent)" }}>
              Read the prompt
            </summary>
            <pre
              className="ah-code ah-small"
              style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto", marginTop: 6 }}
            >
              {prompt}
            </pre>
          </details>
        )}
      </>
    );
  }
  if (kind === "command") {
    const line = commandLine(node);
    return line ? (
      <code
        className="ah-mono ah-small ah-subtle"
        style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}
      >
        $ {line}
      </code>
    ) : null;
  }
  if (kind === "approval") {
    const message = text(node.message);
    return message ? <span className="ah-small">You are asked: “{message}”</span> : null;
  }
  if (kind === "include") {
    return (
      <span className="ah-small ah-subtle">
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
  children,
}: {
  number: string;
  node: Doc;
  after: string[];
  /** A repeat's body ids are `<group>__<id>`: shown without it. */
  prefix?: string;
  children?: ReactNode;
}) {
  const bare = (id: string) => (prefix && id.startsWith(prefix) ? id.slice(prefix.length) : id);
  const type = String(node.type);
  const kind = STEP_KINDS[stepKind(type)];
  const description = text(node.description);
  const conditional = text(node.when);
  return (
    <li className="ah-row" style={{ gap: 12, alignItems: "flex-start" }}>
      <span
        aria-hidden
        className="ah-mono ah-small"
        style={{
          flex: "none",
          minWidth: 28,
          height: 28,
          padding: "0 6px",
          borderRadius: 14,
          display: "grid",
          placeItems: "center",
          background: "var(--surface-2, var(--surface))",
          border: "1px solid var(--border)",
        }}
      >
        {number}
      </span>
      <div className="ah-stack ah-grow" style={{ gap: 4, minWidth: 0, paddingTop: 3 }}>
        <span className="ah-row ah-wrap" style={{ gap: 8 }}>
          <span className="ah-badge ah-badge-quiet" title={kind.hint}>
            <Icon name={kind.icon} />
            {type === "loop_group"
              ? "Rounds"
              : `${(kind.one[0] ?? "").toUpperCase()}${kind.one.slice(1)}`}
          </span>
          <span className="ah-mono" style={{ fontWeight: 600 }}>
            {bare(String(node.id))}
          </span>
          {after.length > 0 && (
            <span className="ah-small ah-subtle">
              after <span className="ah-mono">{after.map(bare).join(", ")}</span>
            </span>
          )}
          {conditional && (
            <span className="ah-small ah-subtle" title={conditional}>
              only when a condition holds
            </span>
          )}
        </span>
        {description && <span>{description}</span>}
        <What node={node} />
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

function Body({ group, prefix }: { group: Doc; prefix: string }) {
  const body = docNodes(group.nodes);
  const until = text(group.until_when) ?? (Array.isArray(group.until_bash) ? "a check" : null);
  return (
    <div
      className="ah-stack"
      style={{
        gap: 10,
        marginTop: 6,
        padding: "12px 14px",
        border: "1px dashed var(--border-strong, var(--border))",
        borderRadius: "var(--radius-md)",
      }}
    >
      <span className="ah-small ah-subtle">
        Each round runs these steps; at most {String(group.max_iterations)} rounds
        {until ? ", stopping as soon as they pass" : ""}.
        {group.fresh_context === true
          ? " Each round starts the agents afresh."
          : " The agents remember the previous round."}
      </span>
      <ol className="ah-stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: 14 }}>
        {body.map((node, index) => (
          <Step
            key={String(node.id)}
            number={`${prefix}.${String(index + 1)}`}
            node={node}
            prefix={`${String(group.id)}__`}
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
  return (
    <ol
      aria-label="Steps"
      className="ah-stack"
      style={{ listStyle: "none", margin: 0, padding: 0, gap: 18 }}
    >
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
            {node.type === "loop_group" && <Body group={node} prefix={number} />}
          </Step>
        );
      })}
    </ol>
  );
}
