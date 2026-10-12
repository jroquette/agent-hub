import { observeElementRect, useVirtualizer } from "@tanstack/react-virtual";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Banner,
  Button,
  EmptyState,
  FilterRail,
  Icon,
  Kbd,
  Minimap,
  ProblemError,
  SegmentedControl,
  Skeleton,
  type Facet as RailFacet,
} from "../../components";
import { fmtClock, fmtInt } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import type { ApiProblem } from "../../lib/api";
import {
  LONG_SESSION_EVENTS,
  flattenTrace,
  minimapOf,
  type Facet,
  type FlatRow,
  type Trace,
} from "./timeline";
import { TraceRow } from "./TraceRow";

const TYPE_FACETS: [Facet, string][] = [
  ["prompt", "Prompts"],
  ["message", "Messages"],
  ["reasoning", "Reasoning"],
  ["tool", "Tools"],
  ["gate", "Gates"],
  ["decision", "Decisions"],
  ["learning", "Learnings"],
  ["guard", "Guard"],
  ["lifecycle", "Lifecycle"],
  ["error", "Errors"],
];
const ROW_SIZE: Record<FlatRow["t"], number> = {
  turn: 30,
  turnSummary: 40,
  event: 36,
  group: 36,
  lane: 40,
  hidden: 28,
  gap: 28,
};
const FALLBACK_RECT = { width: 960, height: 640 };
const MINIMAP_BINS = 120;
const DIGEST_MS = 10_000;

function rowAt(row: FlatRow | undefined): string | null {
  if (!row) return null;
  switch (row.t) {
    case "turn":
    case "turnSummary":
      return row.turn.at;
    case "event":
      return row.row.at;
    case "group":
      return row.group.at;
    case "lane":
      return row.lane.at;
    default:
      return null;
  }
}

function toggled<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

function typingIn(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

export interface TimelineTabProps {
  sessionId: string;
  trace: Trace;
  eventCount: number;
  live: boolean;
  loading: boolean;
  error: { problem: ApiProblem; from: number; retry: () => void } | null;
  /** Events that arrived over the stream so far. */
  liveCount: number;
  /** Ids of rows that arrived over the stream (they fade in). */
  newIds: ReadonlySet<string>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  initialFollow: boolean;
  /** URL-backed view state. */
  query: string;
  onQuery: (q: string) => void;
  /** Clears the search and the errors-only toggle in one URL update. */
  onClearView: () => void;
  errorsOnly: boolean;
  onErrorsOnly: (on: boolean) => void;
  axis: "time" | "turn";
  onAxis: (axis: "time" | "turn") => void;
  focusLane: string | null;
}

/** The trace: filters, virtualised turns with groups and lanes, minimap, follow tail (spec 10). */
export function TimelineTab(props: TimelineTabProps) {
  const { trace, live, selected, query, errorsOnly, axis } = props;
  const { tz } = usePreferences();
  const [rail, setRail] = useState(true);
  const [types, setTypes] = useState<ReadonlySet<Facet>>(new Set());
  const [tools, setTools] = useState<ReadonlySet<string>>(new Set());
  const [lanes, setLanes] = useState<ReadonlySet<string>>(new Set());
  const [openTurns, setOpenTurns] = useState<ReadonlySet<number>>(new Set());
  const [openGroups, setOpenGroups] = useState<ReadonlySet<string>>(new Set());
  const [openRows, setOpenRows] = useState<ReadonlySet<string>>(
    () => new Set(selected ? [selected] : []),
  );
  const [openLanes, setOpenLanes] = useState<ReadonlySet<string>>(
    () => new Set(props.focusLane ? [props.focusLane] : []),
  );
  const [closedLanes, setClosedLanes] = useState<ReadonlySet<string>>(new Set());
  const [following, setFollowing] = useState(props.initialFollow);
  const [seenLive, setSeenLive] = useState(props.liveCount);
  const [matchIndex, setMatchIndex] = useState(0);
  const [digest, setDigest] = useState("");
  const long = props.eventCount >= LONG_SESSION_EVENTS;

  // A deep link inside a collapsed turn, group or lane opens them (spec 10, Interactions).
  const location = useMemo(() => {
    if (!selected) return null;
    for (const turn of trace.turns) {
      for (const item of turn.items) {
        const entries = item.kind === "lane" ? item.items : [item];
        for (const entry of entries) {
          const rows = entry.kind === "group" ? entry.items : [entry];
          if (rows.some((row) => row.id === selected)) {
            return {
              turn: turn.n,
              group: entry.kind === "group" ? entry.id : null,
              lane: item.kind === "lane" ? item.id : null,
            };
          }
        }
      }
    }
    return null;
  }, [trace, selected]);

  const view = useMemo(() => {
    const turnsOpen = new Set(openTurns);
    const groupsOpen = new Set(openGroups);
    const lanesOpen = new Set(openLanes);
    if (location) {
      turnsOpen.add(location.turn);
      if (location.group) groupsOpen.add(location.group);
      if (location.lane) lanesOpen.add(location.lane);
    }
    return {
      long,
      openTurns: turnsOpen,
      openGroups: groupsOpen,
      openLanes: lanesOpen,
      closedLanes,
      lanesOpenByDefault: live,
      errorsOnly,
      types,
      tools,
      lanes,
      query,
    };
  }, [
    long,
    openTurns,
    openGroups,
    openLanes,
    closedLanes,
    live,
    errorsOnly,
    types,
    tools,
    lanes,
    query,
    location,
  ]);
  const rows = useMemo(() => flattenTrace(trace, view), [trace, view]);
  const matches = useMemo(
    () => (query.trim() ? rows.flatMap((row, i) => (row.t === "event" ? [i] : [])) : []),
    [rows, query],
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  // The virtualizer is read during render only; nothing memoizes its functions.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => ROW_SIZE[rows[index]?.t ?? "event"],
    getItemKey: (index) => rows[index]?.key ?? index,
    overscan: 8,
    initialRect: FALLBACK_RECT,
    observeElementRect: (instance, report) =>
      observeElementRect(instance, (rect) => {
        report(rect.height > 0 ? rect : FALLBACK_RECT);
      }),
    // An element not laid out yet (or jsdom) measures 0: keep the estimate then.
    measureElement: (element, _entry, instance) => {
      const height = element.getBoundingClientRect().height;
      const index = Number(element.getAttribute("data-index"));
      return height > 0 ? height : instance.options.estimateSize(index);
    },
  });
  const items = virtualizer.getVirtualItems();

  const programmatic = useRef(false);
  const toEnd = useCallback(() => {
    if (rows.length === 0) return;
    programmatic.current = true;
    virtualizer.scrollToIndex(rows.length - 1, { align: "end" });
    requestAnimationFrame(() => {
      programmatic.current = false;
    });
  }, [rows.length, virtualizer]);

  // Follow tail: new rows keep the trace pinned to the bottom.
  useEffect(() => {
    if (following) toEnd();
  }, [following, rows.length, toEnd]);
  useEffect(() => {
    if (following) setSeenLive(props.liveCount);
  }, [following, props.liveCount]);

  // Scroll to a selected event once it is in the rows.
  const scrolledTo = useRef<string | null>(null);
  useEffect(() => {
    if (!selected || scrolledTo.current === selected) return;
    const index = rows.findIndex((row) => row.t === "event" && row.row.id === selected);
    if (index >= 0) {
      scrolledTo.current = selected;
      setFollowing(false);
      virtualizer.scrollToIndex(index, { align: "center" });
    }
  }, [selected, rows, virtualizer]);

  // A polite digest at most every 10 s, never per event (spec 10, Accessibility).
  const lastDigest = useRef(0);
  const announced = useRef(props.liveCount);
  useEffect(() => {
    const fresh = props.liveCount - announced.current;
    if (fresh <= 0 || Date.now() - lastDigest.current < DIGEST_MS) return;
    announced.current = props.liveCount;
    lastDigest.current = Date.now();
    const last = [...rows].reverse().find((row) => row.t === "event");
    const latest =
      last?.t === "event" ? ` Latest: ${last.row.tool ?? last.row.label} ${last.row.text}.` : "";
    setDigest(`${String(fresh)} new ${fresh === 1 ? "event" : "events"}.${latest}`);
  }, [props.liveCount, rows]);

  const onScroll = () => {
    const element = scrollRef.current;
    if (!element || programmatic.current) return;
    const fromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    if (fromBottom > ROW_SIZE.event * 1.5 && following) setFollowing(false);
  };
  const followAgain = () => {
    setFollowing(true);
    toEnd();
  };

  const jumpToMatch = useCallback(
    (step: number) => {
      if (matches.length === 0) return;
      const next = (matchIndex + step + matches.length) % matches.length;
      setMatchIndex(next);
      const index = matches[next] ?? 0;
      const row = rows[index];
      if (row?.t === "event") props.onSelect(row.row.id);
      virtualizer.scrollToIndex(index, { align: "center" });
    },
    [matches, matchIndex, rows, props, virtualizer],
  );

  const searchRef = useRef<HTMLInputElement>(null);
  const latestKeys = useRef({ followAgain, jumpToMatch, rows, selected, live, following });
  latestKeys.current = { followAgain, jumpToMatch, rows, selected, live, following };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
          event.preventDefault();
          searchRef.current?.focus();
        }
        return;
      }
      if (typingIn(event.target)) return;
      const keys = latestKeys.current;
      const eventRows = keys.rows.flatMap((row) => (row.t === "event" ? [row.row] : []));
      const at = eventRows.findIndex((row) => row.id === keys.selected);
      const move = (target: (typeof eventRows)[number] | undefined) => {
        if (!target) return;
        event.preventDefault();
        props.onSelect(target.id);
        const index = keys.rows.findIndex((row) => row.t === "event" && row.row.id === target.id);
        virtualizer.scrollToIndex(index, { align: "center" });
      };
      if (event.key === "j") move(eventRows[at + 1]);
      else if (event.key === "k") move(eventRows[Math.max(0, at - 1)]);
      else if (event.key === "e")
        move(eventRows.slice(at + 1).find((row) => row.cat === "error" || row.cat === "guard"));
      else if (event.key === "d")
        move(eventRows.slice(at + 1).find((row) => row.cat === "decision"));
      else if (event.key === "n") keys.jumpToMatch(1);
      else if (event.key === "N") keys.jumpToMatch(-1);
      else if (event.key === "/") {
        event.preventDefault();
        searchRef.current?.focus();
      } else if (event.key === "G" && event.shiftKey) {
        keys.followAgain();
      } else if (event.key === "f" && keys.live) {
        if (keys.following) setFollowing(false);
        else keys.followAgain();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [props, virtualizer]);

  // About one bin per two rows, so a short session still reads as a density strip.
  const bins = Math.min(MINIMAP_BINS, Math.max(8, Math.ceil(trace.total / 2)));
  const minimap = useMemo(() => minimapOf(trace, axis, bins), [trace, axis, bins]);
  const first = items[0]?.index ?? 0;
  const lastIndex = items[items.length - 1]?.index ?? 0;
  const span = Math.max(1, rows.length);
  const viewBox = { top: first / span, height: Math.max(0.02, (lastIndex - first + 1) / span) };
  const jump = (fraction: number) => {
    const start = trace.start ? Date.parse(trace.start) : 0;
    const end = trace.end ? Date.parse(trace.end) : 0;
    const target =
      axis === "time"
        ? start + fraction * (end - start)
        : (trace.turns[Math.round(fraction * (trace.turns.length - 1))]?.at ?? "");
    const wanted = typeof target === "number" ? target : Date.parse(target);
    const index = rows.findIndex((row) => {
      const at = rowAt(row);
      return at !== null && Date.parse(at) >= wanted;
    });
    setFollowing(false);
    virtualizer.scrollToIndex(index < 0 ? rows.length - 1 : index, { align: "start" });
  };

  const railFacets: RailFacet[] = [
    {
      id: "type",
      title: "Type",
      options: TYPE_FACETS.filter(([facet]) => trace.counts[facet] > 0).map(([facet, label]) => ({
        id: facet,
        label,
        count: trace.counts[facet],
        checked: types.has(facet),
      })),
    },
    {
      id: "tool",
      title: "Tool",
      options: Object.entries(trace.tools)
        .sort((a, b) => b[1] - a[1])
        .map(([tool, count]) => ({ id: tool, label: tool, count, checked: tools.has(tool) })),
    },
    {
      id: "lane",
      title: "Lane",
      options: [
        { id: "main", label: "Main", checked: lanes.has("main") },
        ...trace.lanes.map((lane) => ({
          id: lane.id,
          label: lane.agent,
          mono: true,
          checked: lanes.has(lane.id),
        })),
      ],
    },
  ];
  const resetFilters = () => {
    setTypes(new Set());
    setTools(new Set());
    setLanes(new Set());
    props.onClearView();
  };
  const filtered = types.size + tools.size + lanes.size > 0 || errorsOnly || query.trim() !== "";
  const visibleEvents = rows.filter((row) => row.t === "event").length;
  const newEvents = Math.max(0, props.liveCount - seenLive);
  const onlyStart = trace.total <= 1 && !props.loading;
  const lastTurn = trace.turns[trace.turns.length - 1]?.n ?? 1;

  return (
    <div className="sd-timeline" data-rail={rail ? "open" : "closed"}>
      {rail && (
        <div>
          <div className="ah-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <span className="ah-overline">Filters</span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setRail(false);
              }}
              aria-label="Collapse filters"
            >
              <Icon name="chevron-left" size="sm" />
            </Button>
          </div>
          <FilterRail
            facets={railFacets}
            onToggle={(facet, option) => {
              if (facet === "type") setTypes((set) => toggled(set, option as Facet));
              else if (facet === "tool") setTools((set) => toggled(set, option));
              else setLanes((set) => toggled(set, option));
            }}
            footer={
              <Button size="sm" variant="ghost" icon="rotate-ccw" onClick={resetFilters}>
                Reset
              </Button>
            }
          />
        </div>
      )}
      <div style={{ minWidth: 0, position: "relative" }}>
        <div className="ah-row ah-wrap" style={{ gap: 8, marginBottom: 12 }}>
          {!rail && (
            <Button
              size="sm"
              icon="funnel"
              onClick={() => {
                setRail(true);
              }}
            >
              Filters{filtered ? ` (${String(types.size + tools.size + lanes.size)})` : ""}
            </Button>
          )}
          <div className="ah-search" style={{ width: 240 }}>
            <Icon name="search" size="sm" />
            <input
              ref={searchRef}
              className="ah-input"
              placeholder="Search in session"
              aria-label="Search in session (Ctrl F)"
              value={query}
              style={{ height: 28 }}
              onChange={(event) => {
                setMatchIndex(0);
                props.onQuery(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") jumpToMatch(event.shiftKey ? -1 : 1);
              }}
            />
          </div>
          {query.trim() !== "" && (
            <span className="ah-small ah-muted" aria-live="polite">
              {matches.length > 0
                ? `${String(Math.min(matchIndex + 1, matches.length))} of ${String(matches.length)}`
                : `No match for "${query}" in this session.`}
            </span>
          )}
          <label className="ah-row ah-small" style={{ gap: 6 }}>
            <input
              type="checkbox"
              className="ah-check"
              checked={errorsOnly}
              onChange={() => {
                props.onErrorsOnly(!errorsOnly);
              }}
            />
            Errors and decisions only
          </label>
          <span className="ah-grow" />
          <SegmentedControl
            label="Time axis (a)"
            value={axis}
            onChange={(id) => {
              props.onAxis(id === "turn" ? "turn" : "time");
            }}
            options={[
              { id: "time", label: "Time", icon: "clock" },
              { id: "turn", label: "Turn", icon: "hash" },
            ]}
          />
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setOpenGroups(
                new Set(rows.flatMap((row) => (row.t === "group" ? [row.group.id] : []))),
              );
              setOpenRows(
                new Set(
                  items.flatMap((item) => {
                    const row = rows[item.index];
                    return row?.t === "event" ? [row.row.id] : [];
                  }),
                ),
              );
            }}
          >
            Expand all
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setOpenGroups(new Set());
              setOpenRows(new Set());
            }}
          >
            Collapse all
          </Button>
          {live && (
            <Button
              size="sm"
              variant={following ? "primary" : "default"}
              icon="arrow-down"
              aria-pressed={following}
              onClick={() => {
                if (following) setFollowing(false);
                else followAgain();
              }}
            >
              {following ? "Following live" : "Follow live"}
            </Button>
          )}
        </div>
        {long && (
          <div style={{ marginBottom: 12 }}>
            <Banner tone="info" boxed>
              Long session · {fmtInt(props.eventCount)} events in {fmtInt(trace.turns.length)}{" "}
              {trace.turns.length === 1 ? "turn" : "turns"}. Turns are collapsed; expand a turn or
              use search and the minimap.
            </Banner>
          </div>
        )}
        {props.error && (
          <div style={{ marginBottom: 12 }}>
            <ProblemError
              compact
              title={`Could not load events ${String(props.error.from + 1)}–${String(props.error.from + 200)}.`}
              detail={props.error.problem.detail ?? props.error.problem.title}
              onRetry={props.error.retry}
            />
          </div>
        )}
        {props.loading && trace.total === 0 ? (
          <div className="ah-stack" aria-busy="true">
            {Array.from({ length: 12 }, (_, i) => (
              <div key={i} className="ah-row" style={{ gap: 12, height: 36 }}>
                <Skeleton width={56} />
                <Skeleton width={24} height={24} radius={6} />
                <Skeleton width={`${String(40 + ((i * 17) % 45))}%`} />
              </div>
            ))}
          </div>
        ) : (
          <div
            ref={scrollRef}
            className="sd-trace ah-tl"
            role="region"
            aria-busy={props.loading || live}
            aria-label="Session timeline"
            onScroll={onScroll}
            // The trace scrolls on its own; keyboard users reach it to scroll.
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
            tabIndex={0}
          >
            <div className="sd-trace-inner" style={{ height: virtualizer.getTotalSize() }}>
              {items.map((item) => {
                const row = rows[item.index];
                if (!row) return null;
                return (
                  <div
                    key={item.key}
                    data-index={item.index}
                    ref={virtualizer.measureElement}
                    className="sd-row"
                    style={{ transform: `translateY(${String(item.start)}px)` }}
                  >
                    <TraceRow
                      row={row}
                      axis={axis}
                      tz={tz}
                      sessionId={props.sessionId}
                      selected={selected}
                      openRows={openRows}
                      newIds={props.newIds}
                      laneLive={live && row.t === "lane" && row.lane.end === trace.end}
                      onSelect={(id) => {
                        setOpenRows((set) => new Set(set).add(id));
                        props.onSelect(id);
                      }}
                      onToggleRow={(id, open) => {
                        setOpenRows((set) => {
                          const next = new Set(set);
                          if (open) next.add(id);
                          else next.delete(id);
                          return next;
                        });
                      }}
                      onToggleGroup={(id) => {
                        setOpenGroups((set) => toggled(set, id));
                      }}
                      onToggleLane={(id, open) => {
                        if (open) {
                          setOpenLanes((set) => new Set(set).add(id));
                          setClosedLanes((set) => {
                            const next = new Set(set);
                            next.delete(id);
                            return next;
                          });
                        } else {
                          setClosedLanes((set) => new Set(set).add(id));
                          setOpenLanes((set) => {
                            const next = new Set(set);
                            next.delete(id);
                            return next;
                          });
                        }
                      }}
                      onOpenTurn={(n) => {
                        setOpenTurns((set) => new Set(set).add(n));
                      }}
                      onShowHidden={resetFilters}
                    />
                  </div>
                );
              })}
            </div>
            {onlyStart && (
              <EmptyState icon="circle-dashed" title="No events yet">
                Tool calls appear within a second; messages appear after each turn.
              </EmptyState>
            )}
            {!onlyStart && filtered && visibleEvents === 0 && (
              <EmptyState
                icon="list-filter"
                title="No events match these filters."
                action={
                  <Button size="sm" icon="x" onClick={resetFilters}>
                    Reset filters
                  </Button>
                }
              >
                {fmtInt(trace.total)} events are hidden.
              </EmptyState>
            )}
            {props.loading && (
              <div className="ah-stack" style={{ padding: "8px 0" }} aria-hidden="true">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} height={24} delay={0} />
                ))}
              </div>
            )}
          </div>
        )}
        {live && !following && newEvents > 0 && (
          <div className="sd-pill-wrap" style={{ right: 0 }}>
            <button type="button" className="ah-newpill" onClick={followAgain}>
              <Icon name="arrow-down" size="sm" />
              {fmtInt(newEvents)} new {newEvents === 1 ? "event" : "events"}
            </button>
          </div>
        )}
        {live && !following && (
          <div className="ah-small ah-subtle" style={{ marginTop: 6 }}>
            Press <Kbd>f</Kbd> to follow again.
          </div>
        )}
        <div className="ah-sr" aria-live="polite" aria-atomic="true">
          {digest}
        </div>
      </div>
      <div className="sd-minimap">
        <span className="ah-overline">
          {axis === "time" ? (trace.start ? fmtClock(trace.start, tz) : "—") : "T1"}
        </span>
        <Minimap
          bins={minimap.bins}
          marks={minimap.marks}
          view={viewBox}
          height={430}
          onJump={jump}
        />
        <span className="ah-overline">
          {axis === "time" ? (trace.end ? fmtClock(trace.end, tz) : "—") : `T${String(lastTurn)}`}
        </span>
      </div>
    </div>
  );
}
