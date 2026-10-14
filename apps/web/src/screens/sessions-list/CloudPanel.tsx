import "../agent-session/agent-session.css";

import { useId, useState } from "react";

import type { components } from "../../api/schema";
import { CodeBlock, Icon, Time } from "../../components";
import { claudeCodeHref } from "../../lib/safeHref";

type Schemas = components["schemas"];
export type CloudSession = Schemas["CloudSession"];
export type DriverCapabilities = Schemas["DriverCapabilities"];

/** A cloud task's limit (64 KiB of UTF-8, plan "Inputs, bounds and budget"). */
export const MAX_TASK_BYTES = 64 * 1024;
export const LIMITED_CONTROL = "cloud: limited control";
/** The start command before a valid task is typed. */
export const COMMAND_TEMPLATE = 'claude --cloud "<task>"';
export const LINK_RULE = "Only https://claude.ai/code/ links open from here.";

/** Why a cloud task cannot be put in the command, or null: empty, too large, or a flag (S6). */
export function taskProblem(task: string): string | null {
  if (task.trim() === "") return "Describe the task.";
  if (task.trimStart().startsWith("-")) return "A task cannot start with “-”.";
  if (new TextEncoder().encode(task).length > MAX_TASK_BYTES) return "Too long: at most 64 KiB.";
  return null;
}

/** `text` as one POSIX shell word: single quotes, each `'` written as `'\''`, so no `$`,
 * backquote, `!` or quote inside it is ever read by the shell. */
export function shellQuote(text: string): string {
  return `'${text.replaceAll("'", "'\\''")}'`;
}

/** The terminal command that starts a cloud session with `task` (A11). */
export function cloudCommand(task: string): string {
  return `claude --cloud ${shellQuote(task)}`;
}

function CloudItem({ session }: { session: CloudSession }) {
  const href = claudeCodeHref(session.url);
  return (
    <li className="as-cloud-item">
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <b>{session.title ?? session.cloud_id}</b>
        <span className="as-limited">{LIMITED_CONTROL}</span>
        <span className="ah-grow" />
        <span className="ah-small ah-subtle">
          <Time iso={session.created_at} />
        </span>
      </div>
      {href ? (
        <a href={href} target="_blank" rel="noreferrer" className="ah-row" style={{ gap: 4 }}>
          Open in claude.ai <Icon name="external-link" size="sm" />
          <span className="ah-sr">(opens in a new tab)</span>
        </a>
      ) : (
        <span className="ah-small ah-muted">
          No link: the session address is not a claude.ai/code URL.
        </span>
      )}
      <CodeBlock code={session.teleport_command} label="Teleport command" />
      <span className="ah-small ah-subtle">
        Run it in a terminal to continue this session on your machine.
      </span>
    </li>
  );
}

export interface CloudPanelProps {
  capabilities: DriverCapabilities;
  /** `GET /agent-sessions/cloud`: the cloud sessions recorded here, newest first. */
  sessions: readonly CloudSession[];
}

/**
 * "Start in the cloud" (D8, AC-165.46, spec A11): `claude --cloud` needs an interactive
 * terminal, so the app never starts a cloud session. With the CLI's cloud capability it shows
 * guidance only: the start command to copy (the task quoted for the shell), the
 * `claude --teleport <id>` form and the link rule; without it, how to get one. Links are only
 * ever `https://claude.ai/code/…` (AC-165.40).
 */
export function CloudPanel({ capabilities, sessions }: CloudPanelProps) {
  const [task, setTask] = useState("");
  const titleId = useId();
  const taskId = useId();
  const problem = task === "" ? null : taskProblem(task);
  const valid = task !== "" && problem === null;

  return (
    <section className="as-cloud" aria-labelledby={titleId}>
      <h2 id={titleId} className="ah-h3">
        Start in the cloud
      </h2>
      {!capabilities.cloud ? (
        <p className="ah-muted" style={{ margin: 0 }}>
          This claude does not offer cloud sessions (no <code>--cloud</code> in its help). Start one
          at claude.ai/code, then run <code>claude --teleport &lt;id&gt;</code> in a terminal to
          continue it on your machine.
        </p>
      ) : (
        <>
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            A cloud session runs on claude.ai and starts in a terminal: <code>claude --cloud</code>{" "}
            needs one, so it is not started from here.{" "}
            <span className="as-limited">{LIMITED_CONTROL}</span>
          </p>
          <label htmlFor={taskId} className="ah-small">
            Task
          </label>
          <textarea
            id={taskId}
            className="ah-input as-composer-input"
            rows={3}
            value={task}
            aria-invalid={problem !== null}
            onChange={(event) => {
              setTask(event.target.value);
            }}
          />
          {problem && <span className="ah-small as-error">{problem}</span>}
          <CodeBlock
            code={valid ? cloudCommand(task) : COMMAND_TEMPLATE}
            label="Cloud start command"
            noCopy={!valid}
            wrap
          />
          <p className="ah-small ah-subtle" style={{ margin: 0 }}>
            Run it in a terminal in the session&apos;s folder, then open the session at
            claude.ai/code or bring it to this machine with{" "}
            <code>claude --teleport &lt;id&gt;</code>. {LINK_RULE}
          </p>
          {sessions.length > 0 && (
            <ul className="as-list" aria-label="Cloud sessions">
              {sessions.map((session) => (
                <CloudItem key={session.id} session={session} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
