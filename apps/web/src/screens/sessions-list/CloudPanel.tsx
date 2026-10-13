import "../agent-session/agent-session.css";

import { useId, useState } from "react";

import type { components } from "../../api/schema";
import { Button, CodeBlock, Icon, Time } from "../../components";
import type { ApiProblem } from "../../lib/api";
import { claudeCodeHref } from "../../lib/safeHref";
import { workdirText } from "./NewSessionDialog";

type Schemas = components["schemas"];
export type CloudSession = Schemas["CloudSession"];
export type StartCloud = Schemas["StartCloud"];
export type DriverCapabilities = Schemas["DriverCapabilities"];
export type Workdir = Schemas["Workdir"];

/** A cloud task's limit (64 KiB of UTF-8, plan "Inputs, bounds and budget"). */
export const MAX_TASK_BYTES = 64 * 1024;
export const LIMITED_CONTROL = "cloud: limited control";

/** Why a cloud task cannot be sent, or null: empty, too large, or read as a flag (S6). */
export function taskProblem(task: string): string | null {
  if (task.trim() === "") return "Describe the task.";
  if (task.trimStart().startsWith("-")) return "A task cannot start with “-”.";
  if (new TextEncoder().encode(task).length > MAX_TASK_BYTES) return "Too long: at most 64 KiB.";
  return null;
}

function problemText(error: ApiProblem): string {
  return error.detail ? `${error.title}: ${error.detail}` : error.title;
}

function FollowUp({
  cloudId,
  onFollowUp,
}: {
  cloudId: string;
  onFollowUp: (cloudId: string, text: string) => Promise<unknown> | undefined;
}) {
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const fieldId = useId();
  const problem = text === "" ? null : taskProblem(text);
  return (
    <form
      className="ah-stack"
      style={{ gap: 4 }}
      onSubmit={(event) => {
        event.preventDefault();
        if (problem || text.trim() === "" || state === "sending") return;
        setState("sending");
        void Promise.resolve()
          .then(() => onFollowUp(cloudId, text))
          .then(
            () => {
              setText("");
              setState("sent");
            },
            () => {
              setState("failed");
            },
          );
      }}
    >
      <label htmlFor={fieldId} className="ah-small">
        One-shot follow-up
      </label>
      <div className="ah-row" style={{ gap: 6 }}>
        <input
          id={fieldId}
          className="ah-input ah-grow"
          value={text}
          aria-invalid={problem !== null}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <Button type="submit" size="sm" disabled={problem !== null || text.trim() === ""}>
          {state === "sending" ? "Sending…" : "Send"}
        </Button>
      </div>
      {problem && <span className="ah-small as-error">{problem}</span>}
      {state === "sent" && (
        <span className="ah-small" role="status">
          Sent. Follow the answer in claude.ai.
        </span>
      )}
      {state === "failed" && (
        <span className="ah-small as-error" role="alert">
          Could not send the follow-up. Try again.
        </span>
      )}
    </form>
  );
}

function CloudItem({
  session,
  onFollowUp,
}: {
  session: CloudSession;
  onFollowUp: ((cloudId: string, text: string) => Promise<unknown> | undefined) | undefined;
}) {
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
        {session.followups > 0 && ` ${String(session.followups)} follow-up(s) sent.`}
      </span>
      {onFollowUp && <FollowUp cloudId={session.cloud_id} onFollowUp={onFollowUp} />}
    </li>
  );
}

export interface CloudPanelProps {
  capabilities: DriverCapabilities;
  project: string;
  workdirs: readonly Workdir[];
  /** `GET /agent-sessions/cloud`: the cloud starts, newest first. */
  sessions: readonly CloudSession[];
  pending?: boolean | undefined;
  error?: ApiProblem | null | undefined;
  /** Starts a cloud session (`POST /agent-sessions/cloud`); without it no start form shows. */
  onStart?: ((body: StartCloud) => void) | undefined;
  /** Sends a one-shot follow-up; offered only when the CLI supports it (`cloud_followup`). */
  onFollowUp?: ((cloudId: string, text: string) => Promise<unknown> | undefined) | undefined;
}

/**
 * "Start in the cloud" (D8, AC-165.46): with the CLI's cloud capability, a task form and each
 * start's claude.ai/code link, `claude --teleport` command and the "cloud: limited control"
 * label; without it, guidance only. Links are only ever `https://claude.ai/code/…` (AC-165.40).
 */
export function CloudPanel({
  capabilities,
  project,
  workdirs,
  sessions,
  pending = false,
  error,
  onStart,
  onFollowUp,
}: CloudPanelProps) {
  const [task, setTask] = useState("");
  const [workdirId, setWorkdirId] = useState(workdirs[0]?.workdir_id ?? "");
  const titleId = useId();
  const taskId = useId();
  const workdirField = useId();
  const problem = task === "" ? null : taskProblem(task);
  const ready = !pending && workdirId !== "" && task !== "" && problem === null;

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
            A cloud session runs on claude.ai. From here you can start it, open it and teleport it:{" "}
            <span className="as-limited">{LIMITED_CONTROL}</span>
          </p>
          {onStart && (
            <form
              className="ah-stack"
              style={{ gap: 6 }}
              onSubmit={(event) => {
                event.preventDefault();
                if (ready) onStart({ project, workdir_id: workdirId, task });
              }}
            >
              <label htmlFor={workdirField} className="ah-small">
                From folder
              </label>
              <select
                id={workdirField}
                className="ah-input"
                value={workdirId}
                disabled={pending}
                onChange={(event) => {
                  setWorkdirId(event.target.value);
                }}
              >
                {workdirs.map((w) => (
                  <option key={w.workdir_id} value={w.workdir_id}>
                    {workdirText(w)}
                  </option>
                ))}
              </select>
              <label htmlFor={taskId} className="ah-small">
                Task
              </label>
              <textarea
                id={taskId}
                className="ah-input as-composer-input"
                rows={3}
                value={task}
                disabled={pending}
                aria-invalid={problem !== null}
                onChange={(event) => {
                  setTask(event.target.value);
                }}
              />
              {problem && <span className="ah-small as-error">{problem}</span>}
              <div className="ah-row" style={{ gap: 6 }}>
                <Button type="submit" variant="primary" disabled={!ready}>
                  {pending ? "Starting…" : "Start in the cloud"}
                </Button>
                {pending && (
                  <span className="ah-small" role="status">
                    Starting the cloud session… This can take up to a minute.
                  </span>
                )}
              </div>
              {error && !pending && (
                <p className="ah-small as-error" role="alert">
                  {problemText(error)}
                </p>
              )}
            </form>
          )}
          {sessions.length > 0 && (
            <ul className="as-list" aria-label="Cloud sessions">
              {sessions.map((session) => (
                <CloudItem
                  key={session.id}
                  session={session}
                  onFollowUp={capabilities.cloud_followup ? onFollowUp : undefined}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
