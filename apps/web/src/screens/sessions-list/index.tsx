import "./sessions-list.css";

import { useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";

import {
  AsOfStamp,
  Button,
  DataTable,
  EmptyState,
  FilterChip,
  FilterRail,
  Icon,
  IdChip,
  IssueLink,
  Popover,
  ProblemError,
  SavedViewMenu,
  SegmentedControl,
  SessionLabel,
  Skeleton,
  StatusBadge,
  Tooltip,
  VIRTUAL_THRESHOLD,
  type DataTableColumn,
  type Facet,
  type Status,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtClock, fmtDuration, fmtInt, fmtMoney, fmtTokens } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { readStored, writeStored } from "../../lib/storage";
import { useCollectorState } from "../../shell/GlobalStream";
import {
  FILTER_KEYS,
  OUTCOMES,
  PERIODS,
  STATUSES,
  TOOLS,
  badDecimal,
  chipsOf,
  periodOf,
  sortOf,
  type Period,
} from "./filters";
import { CloudSessions, DrivenBanner, NewSessionControl, useDriving } from "./DrivenControls";
import { rowHref, withDriven } from "./drivenRows";
import {
  useAgentSessions,
  useProjects,
  useSectionPages,
  useSectionRefresh,
  type Session,
} from "./queries";
import { SECTIONS, placeDriven, sectionCount, sectionQueries, type SectionId } from "./sections";
import { SessionSection, useCollapsed } from "./SessionSection";
import { useScrollAnchor } from "./useScrollAnchor";

const COLUMNS_KEY = "ah.sessions.columns";
/** A section past VIRTUAL_THRESHOLD rows scrolls inside this height (as the learnings table). */
const SECTION_MAX_HEIGHT = 640;
const DENSITY_KEY = "ah.sessions.density";
const short = (id: string) => id.replace(/-/g, "").slice(0, 8);
/** The session's issue: the label's (S1), else the run's. */
const issueOf = (s: Session) => s.label?.issue ?? s.issue ?? null;

/** Built-in saved views (spec 14): each is a set of URL filters. */
const VIEWS: { name: string; params: Record<string, string> }[] = [
  { name: "Default", params: {} },
  { name: "Live now", params: { status: "live", period: "All" } },
  { name: "Errors this week", params: { outcome: "error", period: "7 d" } },
  { name: "Guard denials", params: { guard_denial: "1", period: "30 d" } },
  { name: "Expensive sessions", params: { sort: "-cost", period: "30 d" } },
];

const OUTCOME_BADGE: Record<NonNullable<Session["outcome"]>, [Status, string]> = {
  done: ["done", "Done"],
  stopped: ["stopped", "Stopped"],
  blocked: ["blocked", "Blocked"],
  error: ["error", "Error"],
};

function badgeOf(session: Session): [Status, string] {
  if (session.status === "live") return ["live", "Live"];
  if (session.status === "waiting") return ["waiting", "Waiting"];
  if (session.status === "idle") return ["idle", "Idle"];
  if (session.outcome) return OUTCOME_BADGE[session.outcome];
  return ["ended", session.end_inferred ? "Ended · no end event" : "Ended"];
}

function tokensTotal(session: Session): number | null {
  const tokens = session.tokens;
  return tokens ? tokens.input + tokens.output + tokens.cache_read + tokens.cache_write : null;
}

function tokensTip(session: Session): string {
  const tokens = session.tokens;
  if (!tokens) return "No token usage in the transcript yet.";
  return `Input ${fmtInt(tokens.input)} · output ${fmtInt(tokens.output)} · cache read ${fmtInt(tokens.cache_read)} · cache write ${fmtInt(tokens.cache_write)}`;
}

function zeroSubtle(value: number, danger = false): ReactNode {
  return (
    <span
      style={
        value === 0
          ? { color: "var(--text-subtle)" }
          : danger
            ? { color: "var(--failed)" }
            : undefined
      }
    >
      {fmtInt(value)}
    </span>
  );
}

/** A session's duration; only a running one reads the second clock, so a tick re-renders just its cell. */
function Elapsed({ session }: { session: Session }) {
  return session.ended_at ? (
    fmtDuration((Date.parse(session.ended_at) - Date.parse(session.started_at)) / 1000)
  ) : (
    <RunningFor start={session.started_at} />
  );
}

function RunningFor({ start }: { start: string }) {
  const now = useNow(1000);
  return fmtDuration((now - Date.parse(start)) / 1000);
}

interface ColumnDef {
  id: string;
  label: string;
  on: boolean;
  sort?: "started_at" | "last_activity_at" | "cost" | undefined;
  column: (ctx: { tz: "local" | "utc" }) => DataTableColumn<Session>;
}

const COLUMN_DEFS: ColumnDef[] = [
  {
    id: "started",
    label: "Started",
    on: true,
    sort: "started_at",
    column: ({ tz }) => ({
      id: "started",
      label: "Started",
      sortable: true,
      render: (s) => (
        <span className="ah-mono" style={{ fontSize: 12 }} title={s.started_at}>
          {new Date(s.started_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}{" "}
          {fmtClock(s.started_at, tz)}
        </span>
      ),
    }),
  },
  {
    id: "duration",
    label: "Duration",
    on: true,
    column: () => ({
      id: "duration",
      label: "Duration",
      align: "right",
      render: (s) => <Elapsed session={s} />,
    }),
  },
  {
    id: "project",
    label: "Project",
    on: true,
    column: () => ({ id: "project", label: "Project", render: (s) => s.project }),
  },
  {
    id: "repo",
    label: "Repo",
    on: true,
    column: () => ({
      id: "repo",
      label: "Repo",
      render: (s) => (
        <span className="ah-mono" style={{ fontSize: 12 }}>
          {s.repo ?? "—"}
        </span>
      ),
    }),
  },
  {
    id: "session",
    label: "Session",
    on: true,
    column: () => ({
      id: "session",
      label: "Session",
      render: (s) => (
        <span style={{ display: "inline-block", maxWidth: 240, verticalAlign: "middle" }}>
          <SessionLabel session={s} />
        </span>
      ),
    }),
  },
  {
    id: "issue",
    label: "Issue / run",
    on: true,
    column: () => ({
      id: "issue",
      label: "Issue / run",
      render: (s) => (
        <span className="ah-row" style={{ gap: 6 }}>
          {issueOf(s) ? <IssueLink id={issueOf(s) ?? ""} /> : null}
          {s.run_id ? (
            <Tooltip
              label={`Run ${s.run_id}${s.step ? ` · step ${s.step}` : ""}${s.attempt ? ` #${String(s.attempt)}` : ""}`}
            >
              <span className="ah-mono ah-small ah-subtle">run {short(s.run_id)}</span>
            </Tooltip>
          ) : (
            <span className="ah-small ah-subtle">no run</span>
          )}
        </span>
      ),
    }),
  },
  {
    id: "outcome",
    label: "Outcome",
    on: true,
    column: () => ({
      id: "outcome",
      label: "Outcome",
      render: (s) => {
        const [status, label] = badgeOf(s);
        return <StatusBadge status={status} label={label} />;
      },
    }),
  },
  {
    id: "turns",
    label: "Turns",
    on: true,
    column: () => ({ id: "turns", label: "Turns", align: "right", render: (s) => fmtInt(s.turns) }),
  },
  {
    id: "tokens",
    label: "Tokens",
    on: true,
    column: () => ({
      id: "tokens",
      label: "Tokens",
      align: "right",
      render: (s) => <span title={tokensTip(s)}>{fmtTokens(tokensTotal(s))}</span>,
    }),
  },
  {
    id: "cost",
    label: "Cost",
    on: true,
    sort: "cost",
    column: () => ({
      id: "cost",
      label: "Cost",
      align: "right",
      sortable: true,
      hint: "Estimated from transcript",
      render: (s) => (
        <span title={s.cost_unknown_reason ?? `${fmtMoney(s.cost_usd, 4)} USD · estimated`}>
          {fmtMoney(s.cost_usd, 4)}
        </span>
      ),
    }),
  },
  {
    id: "files",
    label: "Files",
    on: true,
    column: () => ({
      id: "files",
      label: "Files",
      align: "right",
      render: (s) => zeroSubtle(s.files_touched),
    }),
  },
  {
    id: "errors",
    label: "Errors",
    on: true,
    column: () => ({
      id: "errors",
      label: "Errors",
      align: "right",
      hint: "Tool errors and guard denials",
      render: (s) => zeroSubtle(s.errors + s.guard_denials, true),
    }),
  },
  {
    id: "transcript",
    label: "Transcript",
    on: true,
    column: () => ({
      id: "transcript",
      label: "Transcript",
      render: (s) => (
        <span className="ah-small ah-muted">{s.has_transcript ? "local file" : "—"}</span>
      ),
    }),
  },
  {
    id: "id",
    label: "Session id",
    on: false,
    column: () => ({ id: "id", label: "Session id", render: (s) => <IdChip id={s.id} /> }),
  },
  {
    id: "model",
    label: "Model",
    on: false,
    column: () => ({
      id: "model",
      label: "Model",
      render: (s) => <span className="ah-mono ah-small">{s.model ?? "—"}</span>,
    }),
  },
  {
    id: "last",
    label: "Last activity",
    on: false,
    sort: "last_activity_at",
    column: ({ tz }) => ({
      id: "last",
      label: "Last activity",
      sortable: true,
      render: (s) => (
        <span className="ah-mono" style={{ fontSize: 12 }}>
          {fmtClock(s.last_activity_at, tz)}
        </span>
      ),
    }),
  },
  {
    id: "guard",
    label: "Guard denials",
    on: false,
    column: () => ({
      id: "guard",
      label: "Guard denials",
      align: "right",
      render: (s) => zeroSubtle(s.guard_denials),
    }),
  },
  {
    id: "resumed",
    label: "Resumed",
    on: false,
    column: () => ({
      id: "resumed",
      label: "Resumed",
      align: "right",
      render: (s) => (s.segments.length > 1 ? `${String(s.segments.length)} segments` : ""),
    }),
  },
];

/** Comfortable density: two-line cells, as the design's default view (spec 14). */
const COMFORTABLE: ColumnDef[] = [
  {
    id: "started",
    label: "Started",
    on: true,
    sort: "started_at",
    column: ({ tz }) => ({
      id: "started",
      label: "Started",
      sortable: true,
      render: (s) => (
        <div className="ah-stack" style={{ gap: 0, padding: "4px 0" }}>
          <span className="ah-mono" style={{ fontSize: 12 }} title={s.started_at}>
            {new Date(s.started_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}{" "}
            {fmtClock(s.started_at, tz)}
          </span>
          <span className="ah-small ah-subtle">
            <Elapsed session={s} />
          </span>
        </div>
      ),
    }),
  },
  {
    id: "session",
    label: "Session",
    on: true,
    column: () => ({
      id: "session",
      label: "Session",
      render: (s) => (
        <div style={{ maxWidth: 260, padding: "4px 0" }}>
          <SessionLabel session={s} />
        </div>
      ),
    }),
  },
  ...COLUMN_DEFS.filter((def) => def.id === "project"),
  {
    id: "issue",
    label: "Issue / run",
    on: true,
    column: () => ({
      id: "issue",
      label: "Issue / run",
      render: (s) => (
        <div className="ah-stack" style={{ gap: 0 }}>
          {issueOf(s) ? (
            <IssueLink id={issueOf(s) ?? ""} />
          ) : (
            <span className="ah-small ah-subtle">no issue</span>
          )}
          {s.run_id ? (
            <span
              className="ah-mono ah-small ah-subtle"
              title={`Run ${s.run_id}${s.step ? ` · step ${s.step}` : ""}`}
            >
              run {short(s.run_id)}
            </span>
          ) : (
            <span className="ah-small ah-subtle">no run</span>
          )}
        </div>
      ),
    }),
  },
  ...COLUMN_DEFS.filter((def) => def.id === "outcome"),
  {
    id: "turns",
    label: "Turns · tok.",
    on: true,
    column: () => ({
      id: "turns",
      label: "Turns · tok.",
      align: "right",
      render: (s) => (
        <div className="ah-stack" style={{ gap: 0, alignItems: "flex-end" }}>
          <span>{fmtInt(s.turns)}</span>
          <span
            className="ah-subtle"
            style={{ fontSize: 12, whiteSpace: "nowrap" }}
            title={tokensTip(s)}
          >
            {fmtTokens(tokensTotal(s))}
          </span>
        </div>
      ),
    }),
  },
  ...COLUMN_DEFS.filter((def) => def.id === "cost"),
  {
    id: "fe",
    label: "Files · err",
    on: true,
    column: () => ({
      id: "fe",
      label: "Files · err",
      align: "right",
      hint: "Files touched (edits, no reads) · tool errors and guard denials",
      render: (s) => (
        <span className="ah-row" style={{ gap: 0, justifyContent: "flex-end" }}>
          <span style={{ width: 28 }}>{zeroSubtle(s.files_touched)}</span>
          <span style={{ width: 28 }}>{zeroSubtle(s.errors + s.guard_denials, true)}</span>
        </span>
      ),
    }),
  },
  ...COLUMN_DEFS.filter((def) => def.id === "transcript"),
];

function storedColumns(): Set<string> {
  const stored = readStored(COLUMNS_KEY);
  // "agent" was the Agent column before AGH-201; the Session column replaces it.
  if (stored) return new Set(stored.split(",").map((id) => (id === "agent" ? "session" : id)));
  return new Set(COLUMN_DEFS.filter((def) => def.on).map((def) => def.id));
}

function ColumnChooser({
  chosen,
  onChange,
}: {
  chosen: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <Button
        size="sm"
        icon="columns-3"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        Columns
      </Button>
      <Popover
        open={open}
        label="Columns"
        style={{ top: 32, right: 0, width: 240, maxHeight: 420, overflow: "auto" }}
      >
        {COLUMN_DEFS.map((def) => (
          <label key={def.id} className="ah-facet-opt">
            <input
              type="checkbox"
              className="ah-check"
              checked={chosen.has(def.id)}
              onChange={() => {
                const next = new Set(chosen);
                if (next.has(def.id)) next.delete(def.id);
                else next.add(def.id);
                onChange(next);
              }}
            />
            {def.label}
          </label>
        ))}
        <div className="ah-menu-sep" />
        <Button
          size="sm"
          variant="ghost"
          icon="rotate-ccw"
          onClick={() => {
            onChange(new Set(COLUMN_DEFS.filter((def) => def.on).map((def) => def.id)));
          }}
        >
          Reset to default
        </Button>
      </Popover>
    </div>
  );
}

function csvOf(rows: Session[]): string {
  const head = [
    "id",
    "started_at",
    "ended_at",
    "project",
    "repo",
    "branch",
    "issue",
    "workflow",
    "run_id",
    "status",
    "outcome",
    "turns",
    "cost_usd",
    "files_touched",
    "errors",
    "guard_denials",
  ];
  const cell = (value: string | number | null | undefined) => {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = rows.map((s) =>
    [
      s.id,
      s.started_at,
      s.ended_at,
      s.project,
      s.repo,
      s.label?.branch,
      issueOf(s),
      s.label?.workflow,
      s.run_id,
      s.status,
      s.outcome,
      s.turns,
      s.cost_usd,
      s.files_touched,
      s.errors,
      s.guard_denials,
    ]
      .map(cell)
      .join(","),
  );
  return [head.join(","), ...lines].join("\n");
}

function download(name: string, text: string): void {
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function currentView(params: URLSearchParams): string {
  const keys: string[] = [...FILTER_KEYS, "sort"];
  const view = VIEWS.find((candidate) =>
    keys.every((key) => (params.get(key) ?? "") === (candidate.params[key] ?? "")),
  );
  return view?.name ?? "Unsaved view";
}

/** The stale stamp while the collector is offline; its second clock re-renders only this stamp. */
function OfflineStamp({ tz }: { tz: "local" | "utc" }) {
  const collector = useCollectorState();
  return collector.state === "offline" ? (
    <AsOfStamp stale time={fmtClock(collector.asOf, tz)} source="collector heartbeat" />
  ) : null;
}

/** Sessions: "Which sessions happened, and which one do I need to look at?" (spec 14). */
export function SessionsListScreen() {
  const [params, setParams] = useSearchParams();
  const [scope] = useScope();
  const navigate = useNavigate();
  const { tz } = usePreferences();
  const [anchor] = useState(() => Date.now());
  const queries = useMemo(() => sectionQueries(params, scope, anchor), [params, scope, anchor]);
  const sections = useSectionPages(queries);
  const [collapsed, toggleCollapsed] = useCollapsed();
  // The same query as the driven rows' list: its poll also refreshes the sections (AC-234.9).
  const agentsUpdatedAt = useAgentSessions(scope).dataUpdatedAt;
  const askedIds = SECTIONS.map((section) => section.id).filter((id) => queries[id] !== null);
  const screenRef = useRef<HTMLDivElement>(null);
  const arm = useScrollAnchor(
    screenRef,
    Object.fromEntries(
      askedIds.map((id) => [
        id,
        { at: sections[id].dataUpdatedAt, fetching: sections[id].isFetching },
      ]),
    ),
  );
  useSectionRefresh(
    scope,
    askedIds.map((id) => ({
      id,
      collapsed: collapsed.has(id),
      fetching: sections[id].isFetching,
      refetch: sections[id].refetch,
    })),
    agentsUpdatedAt,
    arm,
  );
  const projects = useProjects();
  const driving = useDriving(
    scope,
    (projects.data?.items ?? []).map((project) => project.name),
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [columns, setColumns] = useState(storedColumns);
  const [density, setDensity] = useState(() =>
    readStored(DENSITY_KEY) === "compact" ? "compact" : "comfortable",
  );
  const [costDraft, setCostDraft] = useState({
    min: params.get("cost_min") ?? "",
    max: params.get("cost_max") ?? "",
  });

  const update = (changes: Record<string, string | null>) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  };
  const clearFilters = () => {
    update(Object.fromEntries(FILTER_KEYS.map((key) => [key, null])));
    setCostDraft({ min: "", max: "" });
  };

  const chips = chipsOf(params);
  const observed = Object.fromEntries(
    SECTIONS.map(({ id }) => [id, (sections[id].data?.pages ?? []).flatMap((page) => page.items)]),
  ) as Record<SectionId, Session[]>;
  // A driven session without a twin has none of the observed fields a filter (beyond status and period) reads.
  const narrowed = chips.some((chip) => chip.key !== "period" && chip.key !== "status");
  const driven = (driving.list.data?.items ?? []).filter(
    (a) => Boolean(a.observed_session_id) || !narrowed,
  );
  const placed = placeDriven(
    observed,
    driven,
    new Set(SECTIONS.filter(({ id }) => queries[id] !== null).map(({ id }) => id)),
    queries.ended?.from ?? null,
  );
  const asked = SECTIONS.flatMap((section) => {
    if (queries[section.id] === null) return [];
    const pages = sections[section.id];
    const { rows } = placed[section.id];
    const count = sectionCount(pages.data?.pages[0]?.total_estimate ?? 0, placed[section.id]);
    return [{ ...section, pages, rows, count }];
  });
  const rows = asked.flatMap((section) => observed[section.id]);
  const shown = asked.reduce((sum, section) => sum + section.rows.length, 0);
  const total = asked.reduce((sum, section) => sum + section.count, 0);
  const pending = asked.some((section) => section.pages.isPending);
  const hasNextPage = asked.some((section) => section.pages.hasNextPage);
  const period: Period = periodOf(params);
  const sort = sortOf(params);
  const visible = useMemo(
    () =>
      density === "compact"
        ? COLUMN_DEFS.filter((def) => columns.has(def.id) && !(def.id === "project" && scope))
        : COMFORTABLE.filter((def) => !(def.id === "project" && scope)),
    [density, columns, scope],
  );
  const tableColumns = useMemo(
    () => visible.map((def) => withDriven(def.column({ tz }), tz)),
    [visible, tz],
  );
  const sortColumn = visible.find((def) => def.sort === sort.replace("-", ""));
  const projectCount = new Set(rows.map((s) => s.project)).size;
  const filtered = chips.some((chip) => chip.key !== "period");
  const costError = badDecimal(costDraft.min) || badDecimal(costDraft.max);

  const facets: Facet[] = [
    {
      id: "status",
      title: "Status",
      options: STATUSES.map((status) => ({
        id: status,
        label: status,
        checked: params.get("status") === status,
      })),
    },
    {
      id: "outcome",
      title: "Outcome",
      options: OUTCOMES.map((outcome) => ({
        id: outcome,
        label: outcome,
        checked: params.get("outcome") === outcome,
      })),
    },
    {
      id: "repo",
      title: "Repo",
      input: (
        <div className="ah-search">
          <Icon name="book" size="sm" />
          <input
            className="ah-input ah-mono"
            aria-label="Repo"
            placeholder="repo dir"
            defaultValue={params.get("repo") ?? ""}
            style={{ height: 28, fontSize: 12 }}
            onBlur={(event) => {
              update({ repo: event.target.value.trim() });
            }}
          />
        </div>
      ),
    },
    {
      id: "agent",
      title: "Agent type",
      input: (
        <div className="ah-search">
          <Icon name="network" size="sm" />
          <input
            className="ah-input ah-mono"
            aria-label="Agent type"
            placeholder="subagent type, e.g. Explore"
            defaultValue={params.get("agent") ?? ""}
            style={{ height: 28, fontSize: 12 }}
            onBlur={(event) => {
              update({ agent: event.target.value.trim() });
            }}
          />
        </div>
      ),
    },
    {
      id: "workflow",
      title: "Workflow",
      options: [
        {
          id: "issue-to-pr",
          label: "issue-to-pr",
          mono: true,
          checked: params.get("workflow") === "issue-to-pr",
        },
      ],
    },
    {
      id: "cost",
      title: "Cost range",
      input: (
        <div className="ah-stack" style={{ gap: 4 }}>
          <div className="ah-row" style={{ gap: 6 }}>
            {(["min", "max"] as const).map((bound) => (
              <input
                key={bound}
                className="ah-input"
                aria-label={bound === "min" ? "Minimum cost" : "Maximum cost"}
                aria-invalid={badDecimal(costDraft[bound]) || undefined}
                placeholder={`$ ${bound}`}
                value={costDraft[bound]}
                style={{
                  height: 28,
                  width: 96,
                  borderColor: badDecimal(costDraft[bound]) ? "var(--failed)" : undefined,
                }}
                onChange={(event) => {
                  setCostDraft({ ...costDraft, [bound]: event.target.value });
                }}
                onBlur={(event) => {
                  if (!badDecimal(event.target.value))
                    update({ [`cost_${bound}`]: event.target.value.trim() });
                }}
              />
            ))}
          </div>
          {costError && (
            <span className="ah-small" style={{ color: "var(--failed)" }}>
              Use a decimal with a dot, e.g. 1.5
            </span>
          )}
        </div>
      ),
    },
    {
      id: "file",
      title: "Touched file",
      input: (
        <div className="ah-search">
          <Icon name="file-text" size="sm" />
          <input
            className="ah-input ah-mono"
            aria-label="Touched file (path or glob)"
            placeholder="path or glob"
            defaultValue={params.get("file") ?? ""}
            style={{ height: 28, fontSize: 12 }}
            onBlur={(event) => {
              update({ file: event.target.value.trim() });
            }}
          />
        </div>
      ),
    },
    {
      id: "tool",
      title: "Used tool",
      input: (
        <div className="ah-row ah-wrap" style={{ gap: 4 }}>
          {TOOLS.map((tool) => (
            <FilterChip
              key={tool}
              value={tool}
              active={params.get("tool") === tool}
              onClick={() => {
                update({ tool: params.get("tool") === tool ? null : tool });
              }}
            />
          ))}
        </div>
      ),
    },
    {
      id: "flags",
      title: "Flags",
      options: [
        {
          id: "guard_denial",
          label: "Had a guard denial",
          checked: params.get("guard_denial") === "1",
          icon: <Icon name="shield-x" size="sm" style={{ color: "var(--guard)" }} />,
        },
      ],
    },
  ];
  if (!scope && (projects.data?.items.length ?? 0) > 1) {
    facets.unshift({
      id: "project",
      title: "Project",
      input: (
        <span className="ah-small ah-subtle">
          Use the project switcher in the top bar to scope this list.
        </span>
      ),
    });
  }

  const countLine = pending
    ? "Loading sessions…"
    : `Showing ${fmtInt(shown)}${hasNextPage ? ` of ~${fmtInt(total)}` : ""} · Ended: ${period === "All" ? "all time" : `last ${period}`} · ${String(projectCount)} ${projectCount === 1 ? "project" : "projects"}`;
  const compareOk = selected.length === 2;
  const allEmpty =
    !pending && asked.every((section) => !section.pages.error && section.rows.length === 0);
  const neverAny = !filtered && allEmpty;

  const empty = neverAny ? (
    <EmptyState
      icon="square-terminal"
      title="No sessions yet."
      action={
        period === "All" ? undefined : (
          <Button
            variant="ghost"
            onClick={() => {
              update({ period: "All" });
            }}
          >
            Show all time
          </Button>
        )
      }
    >
      Each Claude Code session in a registered hub is listed here after its first event.
    </EmptyState>
  ) : (
    <EmptyState
      icon="list-filter"
      title="No sessions match these filters."
      action={
        <div className="ah-row" style={{ gap: 8 }}>
          <Button icon="x" onClick={clearFilters}>
            Clear filters
          </Button>
          {period !== "30 d" && period !== "All" && (
            <Button
              variant="ghost"
              onClick={() => {
                update({ period: "30 d" });
              }}
            >
              Widen to 30 d
            </Button>
          )}
        </div>
      }
    />
  );

  const sectionBody = ({ title, pages, rows: sectionRows, count }: (typeof asked)[number]) => {
    if (pages.error) {
      return (
        <div className="ah-stack" style={{ gap: 8 }}>
          <ProblemError
            title={`Could not load ${title.toLowerCase()} sessions`}
            detail={pages.error.detail}
            status={pages.error.status}
            type={pages.error.type}
            instance={pages.error.instance}
            onRetry={() => {
              void pages.refetch();
            }}
          />
          <div>
            <Button size="sm" variant="ghost" icon="x" onClick={clearFilters}>
              Clear filters
            </Button>
          </div>
        </div>
      );
    }
    // A light placeholder: four skeleton tables at once made role queries crawl under coverage.
    if (pages.isPending) return <Skeleton lines={2} />;
    const keys = new Set(sectionRows.map((s) => s.id));
    // Past the threshold a section scrolls in its own window, so only the rows in view render.
    const bounded = sectionRows.length > VIRTUAL_THRESHOLD;
    return (
      <DataTable
        caption={`${title} sessions`}
        maxHeight={bounded ? SECTION_MAX_HEIGHT : undefined}
        scrollLabel={bounded ? `Scrollable ${title.toLowerCase()} sessions` : undefined}
        columns={tableColumns}
        rows={sectionRows}
        rowKey={(s) => s.id}
        density={density === "compact" ? "compact" : undefined}
        sort={
          sortColumn ? { id: sortColumn.id, dir: sort.startsWith("-") ? "desc" : "asc" } : undefined
        }
        onSort={(id) => {
          const def = COLUMN_DEFS.find((column) => column.id === id);
          if (!def?.sort) return;
          const desc = `-${def.sort}`;
          update({ sort: sort === desc ? def.sort : desc === "-started_at" ? null : desc });
        }}
        selectable
        selected={selected.filter((id) => keys.has(id))}
        onSelect={(id) => {
          setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
        }}
        onSelectAll={(checked) => {
          const others = selected.filter((id) => !keys.has(id));
          setSelected(checked ? [...others, ...keys] : others);
        }}
        onRowClick={(s) => {
          void navigate(rowHref(s));
        }}
        footer={
          sectionRows.length > 0 ? (
            <>
              <span>
                {pages.hasNextPage
                  ? `Showing ${fmtInt(sectionRows.length)} of ~${fmtInt(count)}`
                  : `Showing all ${fmtInt(sectionRows.length)}`}
              </span>
              {/* On placeholder pages TanStack would refetch page 1, not the next one. */}
              {pages.hasNextPage && !pages.isPlaceholderData && (
                <Button
                  size="sm"
                  disabled={pages.isFetchingNextPage}
                  onClick={() => {
                    void pages.fetchNextPage();
                  }}
                >
                  Load more
                </Button>
              )}
              <span className="ah-row" style={{ gap: 4 }}>
                <Icon name="link" size="sm" />
                Filters are in the URL
              </span>
            </>
          ) : undefined
        }
      />
    );
  };

  // Empty sections are hidden; when all are, one empty state shows (spec 14).
  const body = allEmpty ? (
    empty
  ) : (
    <div className="ah-stack sl-sections">
      {asked
        .filter(
          (section) =>
            section.pages.isPending || section.pages.error !== null || section.rows.length > 0,
        )
        .map((section) => (
          <SessionSection
            key={section.id}
            id={section.id}
            title={section.title}
            // No count while loading, or when the query failed before returning any page.
            count={
              section.pages.isPending || (section.pages.error && !section.pages.data)
                ? null
                : section.count
            }
            approximate={section.pages.hasNextPage}
            updating={section.pages.isPlaceholderData}
            collapsed={collapsed.has(section.id)}
            onToggle={() => {
              toggleCollapsed(section.id);
            }}
          >
            {sectionBody(section)}
          </SessionSection>
        ))}
    </div>
  );

  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack" ref={screenRef}>
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <h1 className="ah-h1">Sessions</h1>
        <OfflineStamp tz={tz} />
        <span className="ah-grow" />
        <SavedViewMenu
          views={VIEWS.map((view) => ({ name: view.name }))}
          current={currentView(params)}
          onPick={(name) => {
            const view = VIEWS.find((candidate) => candidate.name === name);
            if (!view) return;
            update({
              ...Object.fromEntries(FILTER_KEYS.map((key) => [key, null])),
              sort: null,
              ...view.params,
            });
          }}
        />
        <ColumnChooser
          chosen={columns}
          onChange={(next) => {
            writeStored(COLUMNS_KEY, [...next].join(","));
            writeStored(DENSITY_KEY, "compact");
            setColumns(next);
            setDensity("compact");
          }}
        />
        <SegmentedControl
          label="Density"
          value={density}
          onChange={(id) => {
            writeStored(DENSITY_KEY, id);
            setDensity(id === "compact" ? "compact" : "comfortable");
          }}
          options={[
            { id: "comfortable", icon: "list", title: "Comfortable rows" },
            { id: "compact", icon: "list-filter", title: "Compact rows" },
          ]}
        />
        <SegmentedControl
          label="Period"
          value={period}
          onChange={(id) => {
            update({ period: id === "7 d" ? null : id });
          }}
          options={PERIODS}
        />
        <NewSessionControl driving={driving} />
      </div>
      <DrivenBanner driving={driving} />
      <div className="ah-row ah-wrap" style={{ gap: 12, minHeight: 28 }}>
        <span className="ah-muted">{countLine}</span>
        <span className="ah-grow" />
        {selected.length > 0 && (
          <>
            <span className="ah-small">
              Selected <b>{selected.length}</b>
            </span>
            <Button
              size="sm"
              variant={compareOk ? "primary" : "default"}
              icon="git-compare"
              phase="P3"
            >
              Compare 2 sessions
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setSelected([]);
              }}
            >
              Clear
            </Button>
          </>
        )}
        <Button
          size="sm"
          variant="ghost"
          icon="arrow-down"
          disabled={rows.length === 0}
          onClick={() => {
            download(`sessions-${new Date().toISOString().slice(0, 10)}.csv`, csvOf(rows));
          }}
        >
          Export CSV
        </Button>
      </div>
      {chips.length > 0 && (
        <div className="ah-row ah-wrap" style={{ gap: 6 }}>
          {chips.map((chip) => (
            <FilterChip
              key={chip.key}
              k={chip.label}
              value={chip.value}
              onRemove={() => {
                update({ [chip.key]: null });
                if (chip.key === "cost_min" || chip.key === "cost_max") {
                  setCostDraft({ ...costDraft, [chip.key === "cost_min" ? "min" : "max"]: "" });
                }
              }}
            />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
        <div style={{ position: "relative", width: 232, flex: "none" }}>
          <div className="ah-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <span className="ah-small" style={{ fontWeight: 500 }}>
              {filtered
                ? `${String(chips.filter((chip) => chip.key !== "period").length)} filters`
                : "Filters"}
            </span>
            <Button size="sm" variant="ghost" onClick={clearFilters}>
              Clear all
            </Button>
          </div>
          <FilterRail
            facets={facets}
            onToggle={(facet, option) => {
              if (facet === "flags")
                update({ guard_denial: params.get("guard_denial") === "1" ? null : "1" });
              else update({ [facet]: params.get(facet) === option ? null : option });
            }}
          />
        </div>
        <div className="ah-grow sl-table ah-stack" style={{ minWidth: 0 }}>
          {body}
          <CloudSessions driving={driving} />
        </div>
      </div>
    </div>
  );
}
