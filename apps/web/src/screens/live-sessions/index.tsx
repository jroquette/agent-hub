import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";

import {
  AppLink,
  AsOfStamp,
  Button,
  EmptyState,
  Icon,
  ProblemError,
  SegmentedControl,
  SessionTile,
  Skeleton,
  StatusBadge,
  Tooltip,
  sessionIdentity,
  type IconName,
  type LiveSession,
  type Status,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtClock, fmtDuration, fmtMoney, toNumber } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { useCollectorState } from "../../shell/GlobalStream";
import { useAllLiveTiles, useLiveTiles, type LiveTile } from "./queries";
import {
  GROUPINGS,
  GROUP_CAP,
  MANY_TILES,
  groupCounts,
  groupTiles,
  isGrouping,
  problemsLine,
  splitTiles,
  troubled,
  type Grouping,
  type TileGroup,
} from "./tiles";

const GRID = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(min(340px, 100%), 1fr))",
  gap: "var(--space-4)",
  alignItems: "start",
} as const;
const PAD = { padding: "16px 32px 40px", position: "relative", minHeight: "100%" } as const;
const ANNOUNCE_MS = 15_000;

const TOOL_ICON: Record<string, IconName> = {
  Read: "file-text",
  Edit: "file-pen",
  Write: "file-plus",
  Bash: "terminal",
  Grep: "text-search",
  Glob: "folder-search",
  Agent: "network",
  WebFetch: "globe",
};
const OUTCOME: Record<NonNullable<LiveTile["outcome"]>, Status> = {
  done: "done",
  stopped: "stopped",
  blocked: "blocked",
  error: "error",
};
const short = (id: string) => id.replace(/-/g, "").slice(0, 8);

function elapsed(tile: LiveTile, now: number): number {
  const end = tile.ended_at ? Date.parse(tile.ended_at) : now;
  return Math.max(0, (end - Date.parse(tile.started_at)) / 1000);
}

/** The design's tile view model from the API tile (spec 11, "Tile anatomy"). */
function tileModel(tile: LiveTile, now: number, grouping: Grouping): LiveSession {
  const ago = (now - Date.parse(tile.last_activity_at)) / 1000;
  const runLine = tile.run_id
    ? `Run ${tile.issue ?? short(tile.run_id)}${tile.step ? ` › ${tile.step}` : ""}${tile.attempt ? ` · attempt ${String(tile.attempt)}` : ""}`
    : "no run";
  const waitingMinutes = Math.max(1, Math.round(ago / 60));
  const action =
    tile.status === "waiting"
      ? `Waiting ${String(waitingMinutes)} min${tile.waiting_reason === "Guard ask" ? " · a guard ask has no timeout" : ""}`
      : tile.status === "idle"
        ? `Last: ${tile.last_action ?? "no tool call yet"} · ${fmtAgo(ago)}`
        : (tile.last_action ?? "Starting");
  const node: ReactNode = (
    <>
      <div style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{action}</div>
      {tile.failing_notice && (
        <div
          className="ah-row ah-small"
          style={{ gap: 4, color: "var(--text-muted)", marginTop: 2 }}
        >
          <Icon name="circle-x" size="sm" />
          {tile.failing_notice}
        </div>
      )}
      {tile.status === "waiting" && (
        <AppLink
          href="/approvals"
          className="ah-small"
          style={{ fontWeight: 500 }}
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          Open approval
        </AppLink>
      )}
    </>
  );
  const identity = sessionIdentity(tile);
  return {
    id: tile.id,
    status: tile.status,
    outcome: tile.outcome ? OUTCOME[tile.outcome] : undefined,
    reason: tile.waiting_reason ? `Waiting · ${tile.waiting_reason}` : undefined,
    title: identity.title,
    detail: identity.detail,
    subagent: tile.is_subagent,
    project: tile.project,
    repo: `${tile.repo ?? "—"} · ${runLine}`,
    lastAction: action,
    lastActionNode: node,
    lastIcon: tile.last_tool ? (TOOL_ICON[tile.last_tool] ?? "terminal") : "activity",
    lastAgo: tile.status === "live" ? fmtAgo(ago) : "",
    elapsed: elapsed(tile, now),
    turns: tile.turns,
    tokens: tile.tokens_total,
    files: tile.files_touched,
    cost: toNumber(tile.cost_usd),
    budget: grouping === "run" ? null : toNumber(tile.budget_usd),
    problems: problemsLine(tile),
    needsYou: troubled(tile),
    denials: tile.guard_denials,
    activity: tile.status === "idle" ? undefined : tile.sparkline_60s,
  };
}

function Tile({
  tile,
  now,
  grouping,
  staleAt,
}: {
  tile: LiveTile;
  now: number;
  grouping: Grouping;
  staleAt: string | null;
}) {
  const navigate = useNavigate();
  return (
    <div style={{ position: "relative", minWidth: 0 }} data-stale={staleAt ? "true" : undefined}>
      <SessionTile
        s={tileModel(tile, now, grouping)}
        onOpen={() => {
          void navigate(`/sessions/${encodeURIComponent(tile.id)}?follow=1`);
        }}
      />
      {staleAt && (
        <span
          style={{
            position: "absolute",
            right: 48,
            top: -10,
            background: "var(--surface)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          <AsOfStamp stale time={staleAt} />
        </span>
      )}
    </div>
  );
}

function SectionLabel({
  icon,
  tone,
  children,
}: {
  icon?: IconName;
  tone?: string;
  children: ReactNode;
}) {
  return (
    <h2
      className="ah-row ah-caption"
      style={{ gap: 6, margin: "0 0 8px", color: tone ? `var(--${tone})` : "var(--text-muted)" }}
    >
      {icon && <Icon name={icon} size="sm" />}
      {children}
    </h2>
  );
}

function EndedRow({ tile, now }: { tile: LiveTile; now: number }) {
  const navigate = useNavigate();
  const outcome = tile.outcome ? OUTCOME[tile.outcome] : "ended";
  const open = () => {
    void navigate(`/sessions/${encodeURIComponent(tile.id)}`);
  };
  const endedAgo = tile.ended_at ? fmtAgo((now - Date.parse(tile.ended_at)) / 1000) : "";
  const { title, detail } = sessionIdentity(tile);
  return (
    <div
      className="ah-tile"
      data-status="ended"
      role="link"
      tabIndex={0}
      aria-label={`${title} in ${tile.project}, ended ${endedAgo}`}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === "Enter") open();
      }}
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        padding: "8px 16px",
        flexWrap: "wrap",
      }}
    >
      <Icon
        name={tile.is_subagent ? "network" : "square-terminal"}
        size="sm"
        style={{ color: "var(--text-subtle)" }}
      />
      <span className="ah-mono" style={{ fontSize: 13 }}>
        {title}
      </span>
      {detail && <span className="ah-mono ah-small ah-subtle">{detail}</span>}
      <span className="ah-small ah-muted">{tile.project}</span>
      <StatusBadge
        status={outcome}
        label={tile.outcome ? `Ended · ${tile.outcome}` : "Ended · no end event"}
      />
      <span className="ah-small ah-muted ah-num" style={{ fontWeight: 400 }}>
        {fmtDuration(elapsed(tile, now))}
      </span>
      <span className="ah-small ah-num">{fmtMoney(tile.cost_usd)}</span>
      <span className="ah-grow" />
      <span className="ah-small ah-subtle">
        ended {endedAgo} · leaves this list 2 min after it ends
      </span>
    </div>
  );
}

function TileSkeleton() {
  return (
    <div className="ah-tile" style={{ cursor: "default", gap: 10 }}>
      <Skeleton width="55%" height={16} />
      <Skeleton width="80%" />
      <Skeleton width="70%" />
      <Skeleton lines={2} />
      <Skeleton height={4} />
    </div>
  );
}

function GroupSection({
  group,
  grouping,
  now,
  staleAt,
  capped,
}: {
  group: TileGroup;
  grouping: Grouping;
  now: number;
  staleAt: string | null;
  capped: boolean;
}) {
  const [all, setAll] = useState(false);
  const shown = capped && !all ? group.tiles.slice(0, GROUP_CAP) : group.tiles;
  const hidden = group.tiles.length - shown.length;
  return (
    <section aria-label={group.label}>
      {grouping !== "flat" && (
        <div className="ah-caption ah-muted" style={{ margin: "0 0 8px" }}>
          {group.label} ·{" "}
          {grouping === "workflow" || group.key === ""
            ? group.tiles.length
            : groupCounts(group.tiles)}
        </div>
      )}
      <div style={GRID}>
        {shown.map((tile) => (
          <Tile key={tile.id} tile={tile} now={now} grouping={grouping} staleAt={staleAt} />
        ))}
      </div>
      {hidden > 0 && (
        <Button
          size="sm"
          variant="ghost"
          style={{ marginTop: 8 }}
          onClick={() => {
            setAll(true);
          }}
        >
          Show {hidden} more in {group.label}
        </Button>
      )}
    </section>
  );
}

/** Polite, rate-limited digests: a new waiting session or an end, never routine changes. */
function useDigest(tiles: LiveTile[]): string {
  const [message, setMessage] = useState("");
  const known = useRef<{ waiting: Set<string>; ended: Set<string> } | null>(null);
  const last = useRef(0);
  useEffect(() => {
    const waiting = tiles.filter((tile) => tile.group === "waiting");
    const ended = tiles.filter((tile) => tile.group === "ended_recently");
    const before = known.current;
    known.current = {
      waiting: new Set(waiting.map((tile) => tile.id)),
      ended: new Set(ended.map((tile) => tile.id)),
    };
    if (!before || Date.now() - last.current < ANNOUNCE_MS) return;
    const newWaiting = waiting.filter((tile) => !before.waiting.has(tile.id));
    const newEnded = ended.filter((tile) => !before.ended.has(tile.id));
    const parts = [
      ...newWaiting.map(
        (tile) => `1 session waiting for approval: ${sessionIdentity(tile).title}.`,
      ),
      ...newEnded.map(
        (tile) => `Session ended: ${sessionIdentity(tile).title}, ${tile.outcome ?? "ended"}.`,
      ),
    ];
    if (parts.length > 0) {
      last.current = Date.now();
      setMessage(parts.join(" "));
    }
  }, [tiles]);
  return message;
}

function PageHeader({
  counts,
  grouping,
  onGrouping,
  note,
}: {
  counts: { running: number; waiting: number; subagents: number } | null;
  grouping: Grouping | null;
  onGrouping: (grouping: Grouping) => void;
  note: ReactNode;
}) {
  return (
    <div className="ah-row ah-wrap" style={{ gap: 16, marginBottom: 16 }}>
      <h1 className="ah-h1">Live sessions</h1>
      {counts && (
        <Tooltip
          label={`Parent sessions only${counts.subagents ? `, plus ${String(counts.subagents)} ${counts.subagents === 1 ? "subagent" : "subagents"}` : ""}`}
        >
          <span className="ah-row" style={{ gap: 10, color: "var(--text-muted)" }}>
            <span>
              <b className="ah-num" style={{ color: "var(--text)" }}>
                {counts.running}
              </b>{" "}
              running
            </span>
            <span aria-hidden="true">·</span>
            <span style={{ color: "var(--waiting)" }}>
              <b className="ah-num">{counts.waiting}</b> waiting
            </span>
          </span>
        </Tooltip>
      )}
      {note}
      <span className="ah-grow" />
      {grouping && (
        <>
          <span className="ah-small ah-subtle">Group</span>
          <SegmentedControl
            label="Group sessions by (v)"
            value={grouping}
            onChange={(id) => {
              if (isGrouping(id)) onGrouping(id);
            }}
            options={GROUPINGS}
          />
        </>
      )}
    </div>
  );
}

/** Live sessions: "What are the agents doing right now, and does any of them need me?" (spec 11). */
export function LiveSessionsScreen() {
  const [scope, setScope] = useScope();
  const [params, setParams] = useSearchParams();
  const { tz } = usePreferences();
  const now = useNow(1000);
  const collector = useCollectorState();
  const { query } = useLiveTiles(scope);
  const tiles = query.data?.items ?? [];
  const scopedEmpty = scope !== null && query.data !== undefined && tiles.length === 0;
  const others = useAllLiveTiles(scopedEmpty);
  const digest = useDigest(tiles);
  const groupParam = params.get("group");
  const grouping: Grouping = isGrouping(groupParam) ? groupParam : "repo";
  const setGrouping = (next: Grouping) => {
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        if (next === "repo") copy.delete("group");
        else copy.set("group", next);
        return copy;
      },
      { replace: true },
    );
  };

  // `v` cycles the grouping (spec 11, Interactions).
  const latest = useRef({ grouping, setGrouping });
  useEffect(() => {
    latest.current = { grouping, setGrouping };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.key !== "v" || event.ctrlKey || event.metaKey || event.altKey) return;
      if (target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
        return;
      const index = GROUPINGS.findIndex((option) => option.id === latest.current.grouping);
      const next = GROUPINGS[(index + 1) % GROUPINGS.length];
      if (next) latest.current.setGrouping(next.id);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  if (query.isPending) {
    return (
      <div style={PAD} aria-busy="true">
        <PageHeader
          counts={null}
          grouping={grouping}
          onGrouping={setGrouping}
          note={<Skeleton width={180} height={16} />}
        />
        {[0, 1].map((group) => (
          <div key={group} style={{ marginBottom: 24 }}>
            <Skeleton width={180} height={12} style={{ marginBottom: 12 }} />
            <div style={GRID}>
              {[0, 1, 2].map((i) => (
                <TileSkeleton key={i} />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (query.error) {
    return (
      <div style={PAD}>
        <PageHeader counts={null} grouping={null} onGrouping={setGrouping} note={null} />
        <div style={{ maxWidth: 720 }}>
          <ProblemError
            title="Could not load live sessions"
            detail={query.error.detail}
            status={query.error.status}
            type={query.error.type}
            instance={query.error.instance}
            onRetry={() => {
              void query.refetch();
            }}
          />
        </div>
      </div>
    );
  }

  const { waiting, running, ended } = splitTiles(tiles);
  const parents = (list: LiveTile[]) => list.filter((tile) => !tile.is_subagent);
  const counts = {
    running: parents(running).length,
    waiting: parents(waiting).length,
    subagents: [...running, ...waiting].filter((tile) => tile.is_subagent).length,
  };
  const offline = collector.state === "offline";
  const staleAt = offline ? fmtClock(collector.asOf, tz) : null;
  const note = offline ? (
    <AsOfStamp stale time={fmtClock(collector.asOf, tz)} source="collector heartbeat" />
  ) : collector.state === "delayed" ? (
    <span className="ah-small" style={{ color: "var(--waiting)" }}>
      Delayed · updates may lag (last update {fmtAgo((now - collector.asOf.getTime()) / 1000)})
    </span>
  ) : null;

  if (waiting.length + running.length === 0) {
    return (
      <div style={PAD}>
        <PageHeader counts={null} grouping={null} onGrouping={setGrouping} note={note} />
        {ended.length > 0 ? (
          <>
            <p className="ah-muted">No session is running. Recently ended:</p>
            <section aria-label="Ended in the last 2 min" className="ah-stack" style={{ gap: 8 }}>
              <SectionLabel icon="circle-stop">Ended in the last 2 min</SectionLabel>
              {ended.map((tile) => (
                <EndedRow key={tile.id} tile={tile} now={now} />
              ))}
            </section>
          </>
        ) : scopedEmpty ? (
          <EmptyState
            icon="radio"
            title={`Nothing running in ${scope}. ${String(others.data?.items.length ?? 0)} sessions are running in other projects.`}
            action={
              <Button
                size="sm"
                onClick={() => {
                  setScope(null);
                }}
              >
                Show all projects
              </Button>
            }
          />
        ) : (
          <div style={{ paddingTop: 48 }}>
            <EmptyState
              icon="radio"
              title="No session is running"
              command="cd ~/agent-hub-hub && claude"
              action={<AppLink href="/sessions">See recent sessions</AppLink>}
            >
              Sessions appear here when Claude Code starts in a hub with the collector on.
            </EmptyState>
          </div>
        )}
      </div>
    );
  }

  const groups = groupTiles(running, grouping);
  const capped = tiles.length > MANY_TILES;
  return (
    <div style={PAD}>
      <PageHeader counts={counts} grouping={grouping} onGrouping={setGrouping} note={note} />
      {waiting.length > 0 && (
        <section style={{ marginBottom: 24 }} aria-label="Waiting for you">
          <SectionLabel icon="hand" tone="waiting">
            Waiting for you · {waiting.length}
          </SectionLabel>
          <div style={GRID}>
            {waiting.map((tile) => (
              <Tile key={tile.id} tile={tile} now={now} grouping={grouping} staleAt={staleAt} />
            ))}
          </div>
        </section>
      )}
      <section aria-label="Running sessions" className="ah-stack" style={{ gap: 20 }}>
        {groups.map((group) => (
          <GroupSection
            key={group.key}
            group={group}
            grouping={grouping}
            now={now}
            staleAt={staleAt}
            capped={capped}
          />
        ))}
      </section>
      {ended.length > 0 && (
        <section
          style={{ marginTop: 24 }}
          aria-label="Ended in the last 2 min"
          className="ah-stack"
        >
          <SectionLabel icon="circle-stop">Ended in the last 2 min</SectionLabel>
          {ended.map((tile) => (
            <EndedRow key={tile.id} tile={tile} now={now} />
          ))}
        </section>
      )}
      <div className="ah-sr" aria-live="polite" aria-atomic="true">
        {digest}
      </div>
    </div>
  );
}
