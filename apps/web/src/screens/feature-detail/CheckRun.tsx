/* "Check it yourself": an AC's command and a split "Run" button (playground). By default Claude
   runs it in a chat and explains the result; the arrow offers running it in a terminal here. */
import { useMutation, useMutationState, type MutationState } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { components } from "../../api/schema";
import {
  AppLink,
  Button,
  CodeBlock,
  Icon,
  IconButton,
  MenuItem,
  Popover,
  StatusBadge,
  type Status,
} from "../../components";
import { ApiProblem, apiCommand, useApi } from "../../lib/api";
import { fmtAgo } from "../../lib/format";
import { useNow } from "../../lib/clock";
import {
  SESSIONS_OFF_TYPE,
  agentSessionHref,
  sessionControlUnavailable,
} from "../sessions-list/control";
import { useAgentCapabilities, useCreateAgentSession, useWorkdirs } from "../sessions-list/queries";

type Detail = components["schemas"]["FeatureDetail"];
type AcRow = components["schemas"]["AcRow"];
type AcCheckRun = components["schemas"]["AcCheckRun"];
type AgentSessionStatus = components["schemas"]["AgentSessionStatus"];

export type Via = "claude" | "terminal";
const VIA_KEY = "ah.ac-check.via";
const RUN_TIMEOUT = "10 min";
const LOCKED =
  "Locked in this browser. Open the link hub web printed when it started (it ends with ?token=…) once.";
const OFF = "Checks cannot run from the agent-hub container. Run hub web on your machine.";

const VIA: Record<Via, { label: string; icon: "message-square" | "terminal"; hint: string }> = {
  claude: {
    label: "Run with Claude",
    icon: "message-square",
    hint: "Opens a chat: Claude runs the command and explains the result.",
  },
  terminal: {
    label: "Run in terminal",
    icon: "terminal",
    hint: "Runs the command here and shows its exit code and output.",
  },
};

function readJson(key: string): unknown {
  try {
    const text = window.localStorage.getItem(key);
    return text ? (JSON.parse(text) as unknown) : null;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Without storage the choice or the run is only forgotten on reload.
  }
}

function seconds(ms: number): string {
  return ms < 1000 ? `${String(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function clock(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m)}:${String(s).padStart(2, "0")}`;
}

/** Why nothing can run from this page, read before any click: a locked browser or the container. */
function runBlocked(problem: ApiProblem | null | undefined): string | null {
  if (problem?.status === 401) return LOCKED;
  if (problem?.status === 404 && problem.type === SESSIONS_OFF_TYPE) return OFF;
  return null;
}

/** Seconds since `start`, ticking while `on`. */
function useElapsed(on: boolean, start: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(id);
    };
  }, [on]);
  return start === null ? 0 : Math.max(0, Math.floor((now - start) / 1000));
}

function outputLines(text: string): number {
  return text === "" ? 0 : text.replace(/\n$/, "").split("\n").length;
}

/* ---------- In a terminal: the server runs the recorded command ---------- */

/** The terminal run of one AC, kept in the mutation cache so it survives the card closing. */
function useTerminalRun(ac: AcRow, detail: Detail) {
  const key = ["ac-check", detail.project, detail.slug, ac.id];
  const run = useMutation<AcCheckRun, ApiProblem>({
    mutationKey: key,
    gcTime: 30 * 60_000,
    mutationFn: () =>
      apiCommand("/api/v1/features/{project}/{slug}/acs/{ac}/check-runs", {
        path: { project: detail.project, slug: detail.slug, ac: ac.id },
      }),
  });
  const runs = useMutationState({
    filters: { mutationKey: key },
    select: (m) => m.state as MutationState<AcCheckRun, ApiProblem>,
  });
  const last = runs.at(-1);
  const pending = last?.status === "pending";
  return {
    start: () => {
      if (!pending) run.mutate();
    },
    pending,
    submittedAt: pending ? last.submittedAt : null,
    result: last?.status === "success" ? last.data : undefined,
    failure: last?.status === "error" ? last.error : null,
  };
}

function TerminalResult({ ac, result }: { ac: AcRow; result: AcCheckRun }) {
  const lines = outputLines(result.output);
  const [shownAt] = useState(() =>
    new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  );
  return (
    <div className="ah-ac-run">
      <div className="ah-row ah-wrap ah-small" style={{ gap: 8 }}>
        <span className="ah-muted">This run · in terminal</span>
        <StatusBadge
          status={result.passed ? "passed" : "failed"}
          label={
            result.passed
              ? "Passed"
              : result.timed_out
                ? `Timed out after ${RUN_TIMEOUT}`
                : `Failed · exit ${String(result.exit_code)}`
          }
        />
        <span className="ah-subtle">
          {seconds(result.duration_ms)} · <span className="ah-mono">{result.repo}</span>
          {result.branch && (
            <>
              {" "}
              on <span className="ah-mono">{result.branch}</span>
            </>
          )}
          {result.commit && (
            <>
              {" "}
              @ <span className="ah-mono">{result.commit}</span>
            </>
          )}{" "}
          · {shownAt}
        </span>
      </div>
      <details className="ah-ac-run-out" open={!result.passed}>
        <summary>
          Output · {lines} line{lines === 1 ? "" : "s"}
        </summary>
        {result.truncated && (
          <div className="ah-small ah-subtle">Long output: only its last 200 KB is shown.</div>
        )}
        {/* The output scrolls, so the keyboard must reach it (axe scrollable-region-focusable). */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
        <pre tabIndex={0} aria-label={`Output of ${ac.id}'s check`}>
          {result.output || "(no output)"}
        </pre>
      </details>
    </div>
  );
}

/* ---------- With Claude: a chat in the repo's folder ---------- */

interface StoredChat {
  id: string;
  started_at: string;
}

const CHAT_LOOK: Record<AgentSessionStatus, { status: Status; label: string; note?: string }> = {
  running: { status: "running", label: "Claude is running the check" },
  waiting_permission: {
    status: "waiting",
    label: "Waiting for you",
    note: "Claude asks before running the command. Answer in the chat.",
  },
  idle: { status: "done", label: "Claude answered", note: "The result and why are in the chat." },
  ended: { status: "ended", label: "Ended" },
  failed: { status: "failed", label: "Failed" },
};
const IN_FLIGHT: readonly AgentSessionStatus[] = ["running", "waiting_permission"];

/** What Claude is asked: run exactly the recorded command, report, explain, edit nothing. */
export function checkPrompt(ac: AcRow, slug: string, command: string): string {
  return [
    `Run the check of ${ac.id} (feature ${slug}${ac.repo ? `, repo ${ac.repo}` : ""}) and tell me whether it passes.`,
    "",
    `Criterion: ${ac.description}`,
    "",
    `Command, as brain/features/${slug}/features.json records it:`,
    "```",
    command,
    "```",
    "",
    `Run exactly that command${ac.repo ? ` in the ${ac.repo} checkout` : ""}. Then report in a few lines: passed or failed, the exit code and the part of the output that matters. If it fails, say why: the code is not on this branch, the environment, or a real failure of the criterion.`,
    "Do not edit any file and do not record evidence: /evaluate does that.",
  ].join("\n");
}

function useClaudeRun(ac: AcRow, detail: Detail, command: string) {
  const key = `ah.ac-check.chat:${detail.project}/${detail.slug}/${ac.id}`;
  const [stored, setStored] = useState<StoredChat | null>(() => readJson(key) as StoredChat | null);
  const capabilities = useAgentCapabilities();
  const unavailable = sessionControlUnavailable(capabilities.error, capabilities.data);
  const canDrive = capabilities.data !== undefined && unavailable === null;
  const workdirs = useWorkdirs(detail.project, canDrive);
  const items = workdirs.data?.items ?? [];
  const wanted = ac.repo?.toLowerCase();
  const folder =
    items.find(
      (w) => w.kind === "repo" && wanted !== undefined && w.repo?.toLowerCase() === wanted,
    ) ??
    items.find((w) => w.kind === "hub") ??
    null;
  const reason = unavailable
    ? `${unavailable.title}.`
    : !canDrive
      ? "Checking whether this machine can drive Claude…"
      : workdirs.isPending
        ? "Looking for the repo's folder…"
        : folder === null
          ? `Project ${detail.project} has no folder for Claude to work in.`
          : null;
  const create = useCreateAgentSession();
  const session = useApi(
    "/api/v1/agent-sessions/{agent_session_id}",
    { path: { agent_session_id: stored?.id ?? "" } },
    {
      enabled: stored !== null,
      retry: false,
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        return status === undefined || IN_FLIGHT.includes(status) ? 3_000 : false;
      },
    },
  );
  const gone = session.error instanceof ApiProblem && session.error.status === 404;
  const chat = gone ? null : stored;
  useEffect(() => {
    if (gone) writeJson(key, null);
  }, [gone, key]);
  const status = session.data?.status;
  return {
    chat,
    status,
    inFlight: chat !== null && (status === undefined || IN_FLIGHT.includes(status)),
    starting: create.isPending,
    failure: create.error,
    reason,
    start: async () => {
      if (folder === null || create.isPending) return;
      const created = await create.mutateAsync({
        project: detail.project,
        workdir_id: folder.workdir_id,
        mode: "default",
        fork: false,
        prompt: checkPrompt(ac, detail.slug, command),
      });
      const next = { id: created.id, started_at: new Date().toISOString() };
      writeJson(key, next);
      setStored(next);
    },
    forget: () => {
      writeJson(key, null);
      setStored(null);
    },
  };
}

function ClaudeResult({
  chat,
  status,
  inFlight,
  onForget,
}: {
  chat: StoredChat;
  status: AgentSessionStatus | undefined;
  inFlight: boolean;
  onForget: () => void;
}) {
  const now = useNow(30_000);
  const look = status ? CHAT_LOOK[status] : null;
  const waiting = status === "waiting_permission";
  return (
    <div className="ah-ac-run">
      <div className="ah-row ah-wrap ah-small" style={{ gap: 8 }}>
        <span className="ah-muted">This run · with Claude</span>
        <StatusBadge status={look?.status ?? "queued"} label={look?.label ?? "Starting…"} />
        <span className="ah-subtle">
          started {fmtAgo(Math.max(0, now - Date.parse(chat.started_at)) / 1000)}
        </span>
        <span className="ah-grow" />
        <AppLink
          className={waiting ? "ah-btn ah-btn-sm ah-btn-primary" : "ah-btn ah-btn-sm"}
          href={agentSessionHref(chat.id)}
        >
          <Icon name={waiting ? "hand" : "message-square"} size="sm" />
          {waiting ? "Answer in chat" : "Open chat"}
        </AppLink>
        {!inFlight && (
          <IconButton size="sm" icon="x" label="Clear this Claude run" onClick={onForget} />
        )}
      </div>
      {look?.note && <div className="ah-small ah-muted">{look.note}</div>}
    </div>
  );
}

/* ---------- The split button and the section ---------- */

export function CheckRun({ ac, detail, command }: { ac: AcRow; detail: Detail; command: string }) {
  const [via, setVia] = useState<Via>(() =>
    readJson(VIA_KEY) === "terminal" ? "terminal" : "claude",
  );
  const [menu, setMenu] = useState(false);
  const picker = useRef<HTMLSpanElement>(null);
  const terminal = useTerminalRun(ac, detail);
  const claude = useClaudeRun(ac, detail, command);
  const capabilities = useAgentCapabilities();
  const locked = runBlocked(capabilities.error);
  const elapsed = useElapsed(terminal.pending, terminal.submittedAt);
  const where = ac.repo ?? "the repo";

  useEffect(() => {
    if (!menu) return;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent && event.key !== "Escape") return;
      if (event instanceof MouseEvent && picker.current?.contains(event.target as Node)) return;
      setMenu(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menu]);

  const blockedOf = (v: Via): string | null => locked ?? (v === "claude" ? claude.reason : null);
  const busyOf = (v: Via): boolean =>
    v === "claude" ? claude.starting || claude.inFlight : terminal.pending;
  const run = (v: Via) => {
    if (blockedOf(v) !== null || busyOf(v)) return;
    if (v === "claude") void claude.start().catch(() => undefined);
    else terminal.start();
  };
  const choose = (v: Via) => {
    setVia(v);
    writeJson(VIA_KEY, v);
    setMenu(false);
    run(v);
  };

  const blocked = blockedOf(via);
  const busy = busyOf(via);
  const look = VIA[via];
  const label = busy
    ? via === "claude"
      ? claude.starting
        ? "Starting…"
        : "Claude is running…"
      : "Running…"
    : look.label;

  const announce = terminal.pending
    ? `Running ${ac.id}'s check in the terminal…`
    : terminal.result
      ? terminal.result.passed
        ? `${ac.id}'s check passed, ${seconds(terminal.result.duration_ms)}.`
        : terminal.result.timed_out
          ? `${ac.id}'s check timed out after ${RUN_TIMEOUT}.`
          : `${ac.id}'s check failed, exit ${String(terminal.result.exit_code)}, ${seconds(terminal.result.duration_ms)}.`
      : claude.chat && claude.status
        ? `${ac.id}'s check with Claude: ${CHAT_LOOK[claude.status].label}.`
        : "";

  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <CodeBlock code={command} prompt="$" wrap label={`Verification of ${ac.id}`} />
      <div className="ah-row ah-wrap" style={{ gap: 10 }}>
        <span className="ah-split" ref={picker}>
          <Button
            size="sm"
            variant="primary"
            icon={look.icon}
            disabled={blocked !== null}
            aria-disabled={busy || undefined}
            aria-label={blocked ? `${look.label}. ${blocked}` : undefined}
            title={blocked ?? look.hint}
            onClick={() => {
              run(via);
            }}
          >
            {label}
          </Button>
          <button
            type="button"
            className="ah-btn ah-btn-sm ah-btn-primary ah-split-caret"
            aria-label="Choose how to run the check"
            aria-haspopup="dialog"
            aria-expanded={menu}
            onClick={() => {
              setMenu(!menu);
            }}
          >
            <Icon name="chevron-down" size="sm" />
          </button>
          <Popover
            open={menu}
            label="How to run the check"
            className="ah-split-menu"
            style={{ top: "calc(100% + var(--space-1))", left: 0, minWidth: 320 }}
          >
            {(["claude", "terminal"] as const).map((v) => (
              <MenuItem
                key={v}
                icon={VIA[v].icon}
                selected={v === via}
                hint={v === via ? <Icon name="check" size="sm" /> : undefined}
                onClick={() => {
                  choose(v);
                }}
              >
                <span className="ah-stack" style={{ gap: 0 }}>
                  <span>
                    {VIA[v].label}
                    {v === "claude" && <span className="ah-subtle"> · default</span>}
                  </span>
                  <span className="ah-small ah-subtle">{blockedOf(v) ?? VIA[v].hint}</span>
                </span>
              </MenuItem>
            ))}
          </Popover>
        </span>
        {terminal.pending ? (
          <span className="ah-row ah-small ah-muted" style={{ gap: 8 }}>
            <StatusBadge status="running" label={`Running · ${clock(elapsed)}`} />
            <span>
              in <span className="ah-mono">{where}</span>. Stops after {RUN_TIMEOUT}.
            </span>
          </span>
        ) : (
          <span className="ah-small ah-muted">
            {blocked ?? (
              <>
                {look.hint} <span className="ah-subtle">Not recorded as evidence.</span>
              </>
            )}
          </span>
        )}
      </div>
      <div className="ah-sr" role="status" aria-live="polite">
        {announce}
      </div>
      {claude.failure && (
        <div className="ah-small" style={{ color: "var(--failed)" }} role="alert">
          <Icon name="circle-alert" size="sm" /> Claude could not start:{" "}
          {claude.failure.detail ?? claude.failure.title}
        </div>
      )}
      {terminal.failure && (
        <div className="ah-small" style={{ color: "var(--failed)" }} role="alert">
          <Icon name="circle-alert" size="sm" /> The check could not start:{" "}
          {runBlocked(terminal.failure) ?? terminal.failure.detail ?? terminal.failure.title}
        </div>
      )}
      {claude.chat && (
        <ClaudeResult
          chat={claude.chat}
          status={claude.status}
          inFlight={claude.inFlight}
          onForget={claude.forget}
        />
      )}
      {terminal.result && !terminal.pending && <TerminalResult ac={ac} result={terminal.result} />}
      {(claude.chat ?? terminal.result) && (
        <div className="ah-small ah-subtle">
          Not recorded. <span className="ah-mono">/evaluate</span> records evidence.
        </div>
      )}
    </div>
  );
}
