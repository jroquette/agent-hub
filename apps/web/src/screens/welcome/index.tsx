import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import type { components } from "../../api/schema";
import { Button, CodeBlock, Icon, StatusBadge, Tooltip } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo } from "../../lib/format";
import { RegisterHubForm } from "../settings/RegisterHubForm";
import { useFirstSession, useHubs, useServerStatus, useSettings } from "./queries";

type HubView = components["schemas"]["HubView"];
type StepState = "done" | "open" | "future";

/** Placeholder for commands before a hub is registered (spec 22). */
const NO_HUB_PATH = "<path-to-your-hub>";

function Check({ ok, children }: { ok?: boolean; children: ReactNode }) {
  return (
    <div
      className="ah-row ah-small"
      role="status"
      aria-live="polite"
      style={{ gap: 8, color: ok ? "var(--done)" : "var(--text-muted)" }}
    >
      <Icon name={ok ? "circle-check" : "loader"} size="sm" />
      <span>{children}</span>
    </div>
  );
}

interface StepProps {
  n: number;
  title: string;
  state: StepState;
  badge: ReactNode;
  detected?: ReactNode;
  children?: ReactNode;
}

/** One step: done steps collapse to what was detected, future ones stay visible but muted. */
function Step({ n, title, state, badge, detected, children }: StepProps) {
  const done = state === "done";
  const open = state === "open";
  return (
    <li
      className="ah-card"
      style={{
        listStyle: "none",
        padding: "16px 20px",
        opacity: state === "future" ? 0.6 : 1,
        borderColor: open ? "var(--accent)" : undefined,
      }}
      aria-current={open ? "step" : undefined}
    >
      <div className="ah-row" style={{ gap: 14 }}>
        <span
          aria-hidden="true"
          style={{
            width: 32,
            height: 32,
            borderRadius: 999,
            display: "grid",
            placeItems: "center",
            fontWeight: 600,
            fontSize: 15,
            background: done
              ? "var(--done-soft)"
              : open
                ? "var(--accent-soft)"
                : "var(--surface-sunken)",
            color: done ? "var(--done)" : open ? "var(--accent)" : "var(--text-muted)",
          }}
        >
          {done ? <Icon name="check" /> : n}
        </span>
        <h2 className="ah-h3 ah-grow">{title}</h2>
        {badge}
      </div>
      {done && detected && (
        <div className="ah-small" style={{ margin: "6px 0 0 46px", color: "var(--text-muted)" }}>
          {detected}
        </div>
      )}
      {!done && children && (
        <div className="ah-stack" style={{ gap: 10, margin: "12px 0 0 46px" }}>
          {children}
        </div>
      )}
    </li>
  );
}

function hubLine(hub: HubView): ReactNode {
  const head = `${hub.path} · ${hub.project ?? "unknown project"}`;
  if (!hub.valid) {
    const first = hub.validation_errors[0];
    return `${head} · hub.json does not match the schema${first ? `: ${first.message}` : ""}`;
  }
  const lags = hub.lock_version !== null && hub.lock_version !== hub.platform_pin;
  return (
    <>
      {head} · platform {hub.platform_pin ?? "not pinned"}
      {lags ? (
        <>
          {" "}
          pinned, {hub.lock_version} synced (sync pending) · run{" "}
          <span className="ah-mono">./hub sync</span> later
        </>
      ) : (
        " · hub.json valid"
      )}{" "}
      · <Link to="/settings/hubs">Add another hub</Link>
    </>
  );
}

/** First run (spec 22, Screen 1, D27): three steps, each turning green when the app sees it work. */
export function WelcomeScreen() {
  const navigate = useNavigate();
  const now = useNow(1000);
  const hubs = useHubs();
  const server = useServerStatus();
  const settings = useSettings();
  const hub = hubs.data?.items[0];
  const registered = hub !== undefined;
  const running = server.isSuccess;
  const sessions = useFirstSession(registered && running);
  const session = sessions.data?.items[0];
  const started = session !== undefined;

  const doneList = [registered, running, started];
  const firstOpen = doneList.indexOf(false);
  const stateOf = (i: number): StepState =>
    doneList[i] ? "done" : i === firstOpen ? "open" : "future";
  const allDone = firstOpen === -1;
  const hubPath = hub?.path ?? NO_HUB_PATH;
  const address = `127.0.0.1:${String(settings.data?.port ?? 7420)}`;
  const checkedAgo = server.errorUpdatedAt
    ? fmtAgo(Math.max(1, (now - server.errorUpdatedAt) / 1000))
    : null;

  return (
    <div style={{ padding: "48px 32px 40px" }}>
      <div className="ah-stack" style={{ maxWidth: 880, margin: "0 auto", gap: 20 }}>
        <div className="ah-stack" style={{ gap: 6 }}>
          <h1 className="ah-h1" style={{ fontSize: 30, lineHeight: "38px" }}>
            {allDone ? "You are set up" : "Set up agent-hub on this machine"}
          </h1>
          <p className="ah-muted" style={{ margin: 0 }}>
            {allDone
              ? "agent-hub is receiving events. Your first session is recorded."
              : "Three steps. Each one turns green when the app sees it work."}
          </p>
        </div>
        <ol
          className="ah-stack"
          style={{ gap: 12, margin: 0, padding: 0 }}
          aria-label="Setup steps"
        >
          <Step
            n={1}
            title="Register your hub"
            state={stateOf(0)}
            badge={
              registered ? (
                <StatusBadge status="done" label="Done" />
              ) : (
                <StatusBadge status="waiting" label="To do" />
              )
            }
            detected={hub && hubLine(hub)}
          >
            <RegisterHubForm
              label="Hub path"
              helper="The absolute path of the folder that contains hub.json."
              placeholder="/home/you/code/agent-hub-hub"
              primary
            />
          </Step>
          <Step
            n={2}
            title="Keep hub web running"
            state={stateOf(1)}
            badge={
              running ? (
                <StatusBadge status="done" label="Done" />
              ) : (
                <StatusBadge status="live" label="Waiting…" />
              )
            }
            detected={
              server.data && (
                <span>
                  agent-hub is running at <span className="ah-mono">{address}</span> · db{" "}
                  <span className="ah-mono">{server.data.db_path}</span>
                </span>
              )
            }
          >
            <p style={{ margin: 0 }}>
              hub web receives events from Claude Code hooks, stores them locally and serves this
              app. Start it with:
            </p>
            <div style={{ maxWidth: 560 }}>
              <CodeBlock code="hub web" />
            </div>
            <Check>
              Check: agent-hub reachable at {address} · not yet
              {checkedAgo ? ` (checked ${checkedAgo})` : ""}
            </Check>
          </Step>
          <Step
            n={3}
            title="Start a Claude Code session in the hub"
            state={stateOf(2)}
            badge={
              started ? (
                <StatusBadge status="done" label="Done" />
              ) : stateOf(2) === "open" ? (
                <StatusBadge status="live" label="Listening…" />
              ) : (
                <StatusBadge status="idle" label="Not started" />
              )
            }
            detected={
              session && (
                <span className="ah-row" style={{ gap: 6 }}>
                  <Icon name="circle-check" size="sm" style={{ color: "var(--done)" }} />
                  <span>
                    Session{" "}
                    <Link className="ah-mono" to={`/sessions/${session.id}`}>
                      {session.id.replace(/-/g, "").slice(0, 8)}
                    </Link>{" "}
                    started {fmtAgo(Math.max(1, (now - Date.parse(session.started_at)) / 1000))} in{" "}
                    {session.project} ({session.agent})
                  </span>
                </span>
              )
            }
          >
            <div style={{ maxWidth: 560 }}>
              <CodeBlock code={`cd ${hubPath} && claude`} />
            </div>
            <div className="ah-small ah-muted">or, with every repo attached:</div>
            <div style={{ maxWidth: 560 }}>
              <CodeBlock code={`cd ${hubPath} && ./agent`} />
            </div>
            <div className="ah-small ah-muted">
              The hub&apos;s hooks send events to hub web. Sessions started outside the hub
              directory do not load them.
            </div>
            {stateOf(2) === "open" ? (
              <Check>Check: first event from this hub · listening for the first event…</Check>
            ) : (
              <div className="ah-small ah-subtle">
                Check: first event from this hub · waiting for the steps above
              </div>
            )}
          </Step>
        </ol>
        <div className="ah-row ah-wrap" style={{ gap: 12, alignItems: "flex-start" }}>
          <p className="ah-small ah-muted ah-grow" style={{ margin: 0 }}>
            Your data stays on this machine. Secrets are redacted before storage.
            <br />
            Only metadata is kept: no prompt, output or file content.{" "}
            <Link to="/settings/privacy">Privacy settings</Link>
          </p>
          <Link className="ah-btn ah-btn-ghost" to="/">
            Skip for now
          </Link>
          <Tooltip label={allDone ? undefined : "Finish the three steps first, or skip for now."}>
            <Button
              variant="primary"
              iconRight="arrow-right"
              disabled={!allDone}
              onClick={() => {
                void navigate("/");
              }}
            >
              Go to Portfolio
            </Button>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
