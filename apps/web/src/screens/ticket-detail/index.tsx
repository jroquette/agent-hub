/* Ticket detail: what was done to solve one tracker issue, read from the sessions that worked on
 * it: the code they changed (commits, files, pull requests), each session and what it did, and,
 * for a feature's ticket, the feature's records. */
import "../features/features.css";
import "./ticket-detail.css";

import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  DerivedLabel,
  EmptyState,
  Icon,
  ProblemError,
  Skeleton,
  StatusBadge,
  Tabs,
} from "../../components";
import { useApi } from "../../lib/api";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtDateTime, fmtMoney } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { repoState } from "../agent-session/repoChanges";
import { useTicketLookup } from "../features/queries";
import { badgeOf } from "../sessions-list/badge";
import { rowHref } from "../sessions-list/drivenRows";
import { useSessionSummary } from "../session-detail/queries";
import { KINDS, ticketsOf, type Session, type TicketRow } from "../tickets/model";

type RepoChanges = components["schemas"]["RepoChanges"];

const REFRESH_MS = 10_000;
/** How many of the ticket's sessions the page reads (the API's page limit). */
export const TICKET_SESSIONS_READ = 100;

type TabId = "changes" | "sessions" | "feature";

const plural = (n: number, word: string) => `${String(n)} ${word}${n === 1 ? "" : "s"}`;

export function featureTicketHref(row: TicketRow, doc = "tickets"): string | null {
  if (!row.feature) return null;
  const base = `/features/${encodeURIComponent(row.feature.project)}/${encodeURIComponent(row.feature.slug)}`;
  const query = new URLSearchParams({ doc });
  if (doc === "tickets") query.set("ticket", row.issue);
  return `${base}?${query.toString()}`;
}

/** One ticket: the code its sessions changed, each session, and its feature's records. */
export function TicketDetailScreen() {
  const { project = "", issue: rawIssue = "" } = useParams();
  const issue = rawIssue.toUpperCase();
  const sessions = useApi(
    "/api/v1/sessions",
    {
      query: { project, issue, limit: TICKET_SESSIONS_READ, sort: "-last_activity_at" },
    },
    { refetchInterval: REFRESH_MS },
  );
  const lookup = useTicketLookup(project);
  const row = useMemo(
    () => ticketsOf(sessions.data?.items ?? [], lookup).find((r) => r.issue === issue) ?? null,
    [sessions.data, lookup, issue],
  );
  const [params, setParams] = useSearchParams();
  const tabs: { id: TabId; label: string; count?: number }[] = [
    { id: "changes", label: "Changes" },
    { id: "sessions", label: "Sessions", ...(row ? { count: row.sessions } : {}) },
    ...(row?.feature ? [{ id: "feature" as const, label: "Feature" }] : []),
  ];
  const asked = params.get("tab");
  const tab: TabId = tabs.some((t) => t.id === asked) ? (asked as TabId) : "changes";

  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <nav className="ah-small" aria-label="Breadcrumb">
        <Link to="/tickets" className="ah-muted">
          Tickets
        </Link>
        <span className="ah-subtle"> / {issue}</span>
      </nav>
      {sessions.isError && !sessions.data ? (
        <ProblemError
          title={sessions.error.title}
          detail={sessions.error.detail}
          status={sessions.error.status}
          onRetry={() => void sessions.refetch()}
        />
      ) : !sessions.isSuccess ? (
        <div className="ah-stack">
          <Skeleton width="30%" height={28} />
          <Skeleton width="60%" />
        </div>
      ) : row === null ? (
        <div className="ah-card">
          <EmptyState icon="list-todo" title={`No session worked on ${issue} yet.`}>
            A ticket shows here once a session names it: in its first prompt (
            <span className="ah-mono">/fix {issue}</span>), its branch or its worktree.
          </EmptyState>
        </div>
      ) : (
        <>
          <TicketHeader row={row} />
          <Tabs
            label="Ticket"
            tabs={tabs}
            value={tab}
            onChange={(id) => {
              setParams(
                (current) => {
                  const next = new URLSearchParams(current);
                  if (id === "changes") next.delete("tab");
                  else next.set("tab", id);
                  return next;
                },
                { replace: true },
              );
            }}
          />
          <div role="tabpanel" aria-label={tabs.find((t) => t.id === tab)?.label}>
            {tab === "changes" && <ChangesTab row={row} />}
            {tab === "sessions" && <SessionsTab row={row} />}
            {tab === "feature" && <FeatureTab row={row} />}
          </div>
        </>
      )}
    </div>
  );
}

function TicketHeader({ row }: { row: TicketRow }) {
  const kind = KINDS.find((k) => k.id === row.kind)?.label ?? row.kind;
  const featureHref = featureTicketHref(row);
  const prs = uniquePrs(row.sessionList);
  const now = useNow(30_000);
  const ago = fmtAgo(Math.max(0, (now - Date.parse(row.lastActivityAt)) / 1000));
  const state =
    row.group === "needs"
      ? (row.latest.waiting_reason ?? "waits on you")
      : row.group === "active"
        ? `in progress, active ${ago}`
        : `ended ${row.latest.outcome ?? ""} ${ago}`.replace(/\s+/g, " ");
  return (
    <header className="ah-stack" style={{ gap: 8 }}>
      <div className="ah-row ah-wrap" style={{ gap: 10, alignItems: "baseline" }}>
        <h1 className="ah-h1 ah-mono">{row.issue}</h1>
        {row.title && <span className="td-title">{row.title}</span>}
      </div>
      <div className="ah-row ah-wrap" style={{ gap: 6 }}>
        <span className="ft-row-tag">{kind}</span>
        {row.feature && featureHref && (
          <Link to={featureHref} className="ft-row-tag" title="Open the ticket in its feature">
            {row.feature.slug}
          </Link>
        )}
        <span className="ft-row-tag">{row.project}</span>
        {row.repos.map((repo) => (
          <span key={repo} className="ft-row-tag">
            {repo}
          </span>
        ))}
      </div>
      <p className="ah-small ah-muted td-facts">
        <span>{row.workflows.length ? row.workflows.join(" → ") : "no skill"}</span>
        <span>{plural(row.sessions, "session")}</span>
        <span>{fmtMoney(row.costUsd)}</span>
        <span>{state}</span>
        {prs.map((pr) => (
          <a key={pr.url} href={pr.url} target="_blank" rel="noreferrer">
            PR #{pr.number} {pr.state}
          </a>
        ))}
        <DerivedLabel how="Read from the sessions whose first prompt, branch or worktree names this issue, and from git in the folders they worked in.">
          derived
        </DerivedLabel>
      </p>
    </header>
  );
}

function uniquePrs(sessions: readonly Session[]) {
  const seen = new Map<string, NonNullable<Session["pr"]>>();
  for (const session of sessions) {
    if (session.pr && !seen.has(session.pr.url)) seen.set(session.pr.url, session.pr);
  }
  return [...seen.values()];
}

/** The code each session changed, as git reads its folders now (or the commits it recorded). */
function ChangesTab({ row }: { row: TicketRow }) {
  const driven = row.sessionList.filter((s) => s.agent_session_id);
  const outside = row.sessions - driven.length;
  if (driven.length === 0) {
    return (
      <div className="ah-card">
        <EmptyState icon="git-branch" title="No changes read for this ticket.">
          Git is read for the sessions hub web drives; {plural(outside, "session")} of this ticket
          ran outside it. Their pull request, when they opened one, is linked above.
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="ah-stack" style={{ gap: 16 }}>
      {driven.map((session) => (
        <SessionChanges key={session.id} session={session} />
      ))}
      {outside > 0 && (
        <p className="ah-small ah-subtle">
          {plural(outside, "session")} ran outside hub web: git is not read for{" "}
          {outside === 1 ? "it" : "them"}.
        </p>
      )}
    </div>
  );
}

function SessionChanges({ session }: { session: Session }) {
  const id = session.agent_session_id ?? "";
  const changes = useApi(
    "/api/v1/agent-sessions/{agent_session_id}/repo-changes",
    { path: { agent_session_id: id } },
    { retry: false, staleTime: 30_000 },
  );
  const { tz } = usePreferences();
  return (
    <section className="ft-card td-changes" aria-label={`Changes of the session ${session.id}`}>
      <div className="td-changes-head">
        <SessionTitle session={session} />
        <span className="ah-small ah-subtle">started {fmtDateTime(session.started_at, tz)}</span>
        <Link to={rowHref(session)} className="ah-small td-open">
          Review in the session <Icon name="chevron-right" size="sm" />
        </Link>
      </div>
      {changes.isPending ? (
        <div className="td-pad">
          <Skeleton width="50%" />
        </div>
      ) : changes.isError ? (
        <p className="td-pad ah-small ah-subtle">Changes not read: {changes.error.title}</p>
      ) : changes.data.repos.length === 0 ? (
        <p className="td-pad ah-small ah-subtle">This session changed no repository.</p>
      ) : (
        changes.data.repos.map((repo) => <RepoBlock key={repo.root} repo={repo} />)
      )}
      {changes.data?.warnings.map((warning) => (
        <p key={warning} className="td-pad ah-small ah-subtle">
          Not read: {warning}
        </p>
      ))}
    </section>
  );
}

function RepoBlock({ repo }: { repo: RepoChanges }) {
  const state = repoState(repo);
  const added = repo.files.reduce((sum, f) => sum + f.added, 0);
  const removed = repo.files.reduce((sum, f) => sum + f.removed, 0);
  const relative = (path: string) =>
    path.startsWith(`${repo.root}/`) ? path.slice(repo.root.length + 1) : path;
  return (
    <div className="td-repo">
      <div className="td-repo-head ah-small">
        <b>{repo.label}</b>
        {repo.branch && <span className="ah-mono ah-muted">{repo.branch}</span>}
        {repo.base && <span className="ah-subtle">against {repo.base}</span>}
        {repo.pull_request && (
          <a href={repo.pull_request.url} target="_blank" rel="noreferrer">
            PR #{repo.pull_request.number} {repo.pull_request.state.toLowerCase()}
          </a>
        )}
        <span data-tone={state.tone} className="td-state">
          {state.text}
        </span>
      </div>
      {repo.commits.length > 0 && (
        <div className="td-list">
          <h3 className="td-list-title">
            {plural(repo.commits.length, "commit")}
            {repo.truncated ? "+" : ""}
          </h3>
          <ul>
            {repo.commits.map((commit) => (
              <li key={commit.sha} className="td-commit">
                <span className="ah-mono ah-subtle">{commit.sha.slice(0, 7)}</span>
                <span className="td-ellipsis">{commit.subject}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {repo.files.length > 0 && (
        <div className="td-list">
          <h3 className="td-list-title">
            {plural(repo.files.length, "file")} · <span className="td-added">+{added}</span>{" "}
            <span className="td-removed">−{removed}</span>
          </h3>
          <ul>
            {repo.files.map((file) => (
              <li key={file.path} className="td-file">
                <span className="td-ellipsis ah-mono" title={file.path}>
                  {relative(file.path)}
                </span>
                <span className="ah-subtle">{file.status}</span>
                <span className="td-added">+{file.added}</span>
                <span className="td-removed">−{file.removed}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SessionTitle({ session }: { session: Session }) {
  const [status, label] = badgeOf(session);
  return (
    <span className="ah-row" style={{ gap: 8, minWidth: 0 }}>
      <StatusBadge status={status} label={label} quiet />
      <span className="td-ellipsis">
        {session.label?.title ?? session.label?.workflow ?? "Untitled session"}
      </span>
    </span>
  );
}

/** Each session of the ticket, oldest first: what it ran and what it did. */
function SessionsTab({ row }: { row: TicketRow }) {
  const oldestFirst = [...row.sessionList].reverse();
  return (
    <ol className="td-timeline">
      {oldestFirst.map((session) => (
        <SessionEntry key={session.id} session={session} />
      ))}
    </ol>
  );
}

function SessionEntry({ session }: { session: Session }) {
  const ended = session.status === "ended";
  const summary = useSessionSummary(session.id, ended);
  const { tz } = usePreferences();
  const facts = [
    `started ${fmtDateTime(session.started_at, tz)}`,
    (session.label?.workflows ?? []).join(" → ") || null,
    plural(session.turns, "turn"),
    session.files_touched ? plural(session.files_touched, "file") + " touched" : null,
    session.cost_usd != null ? fmtMoney(session.cost_usd) : null,
  ].filter(Boolean);
  return (
    <li className="ft-card td-entry">
      <div className="td-changes-head">
        <SessionTitle session={session} />
        <Link to={rowHref(session)} className="ah-small td-open">
          Open <Icon name="chevron-right" size="sm" />
        </Link>
      </div>
      <p className="td-pad ah-small ah-muted">{facts.join(" · ")}</p>
      {!ended ? (
        <p className="td-pad ah-small ah-subtle">What it did shows when the session ends.</p>
      ) : summary.isPending ? (
        <div className="td-pad">
          <Skeleton width="40%" />
        </div>
      ) : summary.isError ? null : (
        <ul className="td-pad td-summary">
          {summary.data.lines.map((line) => (
            <li key={line.event_id}>{line.text}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** The feature the ticket belongs to: its records, and the ticket's panel there. */
function FeatureTab({ row }: { row: TicketRow }) {
  if (!row.feature) return null;
  const records = [
    {
      doc: "tickets",
      label: "The ticket in the feature",
      hint: "plan slice, context brief, preflight, change requests",
    },
    { doc: "spec", label: "Spec", hint: "what the feature must do" },
    { doc: "research", label: "Research", hint: "how the code works today" },
    { doc: "plan", label: "Plan", hint: "the tasks, contract first" },
    { doc: "acs", label: "Criteria", hint: "the acceptance criteria and their evidence" },
  ];
  return (
    <div className="ft-card">
      <ul className="ft-rows">
        {records.map((record) => (
          <li key={record.doc} className="td-record">
            <Link to={featureTicketHref(row, record.doc) ?? "#"}>{record.label}</Link>
            <span className="ah-small ah-subtle">{record.hint}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
