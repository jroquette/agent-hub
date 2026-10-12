import "./session-detail.css";

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Banner, Button, AppLink, ProblemError, Skeleton, Tabs } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtClock, fmtDuration } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useShell } from "../../shell/AppShell";
import { useCollectorState } from "../../shell/GlobalStream";
import { CostTab } from "./CostTab";
import { FilesTab } from "./FilesTab";
import { Header } from "./Header";
import { useSession, useSessionEvents, type Session } from "./queries";
import { RawTab } from "./RawTab";
import { SummaryCard } from "./SummaryCard";
import { buildTrace } from "./timeline";
import { TimelineTab } from "./TimelineTab";

const TABS = ["timeline", "files", "cost", "raw"] as const;
type Tab = (typeof TABS)[number];

function isTab(value: string | null): value is Tab {
  return TABS.includes(value as Tab);
}

function LoadingBody() {
  return (
    <div className="sd-body ah-stack" aria-busy="true">
      <h1 className="ah-sr">Session detail</h1>
      <Skeleton width={360} height={24} />
      <Skeleton width={720} height={14} />
      <Skeleton height={88} radius={8} />
      {Array.from({ length: 12 }, (_, i) => (
        <div key={i} className="ah-row" style={{ gap: 12, height: 36 }}>
          <Skeleton width={56} />
          <Skeleton width={24} height={24} radius={6} />
          <Skeleton width={`${String(40 + ((i * 17) % 45))}%`} />
        </div>
      ))}
    </div>
  );
}

/** Session detail: "What did this agent do, in what order, and why?" (spec 10). */
export function SessionDetailScreen() {
  const { sessionId = "" } = useParams();
  const session = useSession(sessionId);
  const { openPalette } = useShell();
  if (session.isPending) return <LoadingBody />;
  if (session.error) {
    const notFound = session.error.status === 404;
    return (
      <div className="sd-body" style={{ maxWidth: 760 }}>
        <h1 className="ah-sr">Session detail</h1>
        <ProblemError
          title={notFound ? "Session not found" : "Could not load session"}
          detail={
            notFound
              ? `No session has the id ${sessionId} in the registered hubs. It may belong to a hub that was removed.`
              : session.error.detail
          }
          status={session.error.status}
          type={session.error.type}
          instance={session.error.instance}
          onRetry={
            notFound
              ? undefined
              : () => {
                  void session.refetch();
                }
          }
        />
        {notFound && (
          <div className="ah-row" style={{ gap: 8, marginTop: 12 }}>
            <Button
              size="sm"
              icon="search"
              onClick={() => {
                openPalette(sessionId);
              }}
            >
              Open command palette
            </Button>
            <AppLink className="ah-btn ah-btn-sm ah-btn-ghost" href="/">
              Go to Portfolio
            </AppLink>
          </div>
        )}
      </div>
    );
  }
  return <SessionDetailBody session={session.data} />;
}

function SessionDetailBody({ session }: { session: Session }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { tz } = usePreferences();
  const now = useNow(1000);
  const collector = useCollectorState();
  const live = session.status !== "ended";
  const events = useSessionEvents(session.id, live);
  const trace = useMemo(() => buildTrace(events.events), [events.events]);
  const tabParam = params.get("tab");
  const tab: Tab = isTab(tabParam) ? tabParam : "timeline";
  const selected = params.get("event");
  const [initialFollow] = useState(() => params.get("follow") === "1" || (live && !selected));

  const setParam = (changes: Record<string, string | null>, push = false) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: !push },
    );
  };
  const jump = (eventId: string) => {
    setParam({ tab: null, event: eventId });
  };

  const newIds = useMemo(
    () =>
      new Set(
        events.events.slice(events.events.length - events.liveCount).map((event) => event.event_id),
      ),
    [events.events, events.liveCount],
  );
  const times = useMemo(
    () => new Map(events.events.map((event) => [event.event_id, event.timestamp])),
    [events.events],
  );

  // "Session ended: done. Summary available." once, politely, when it ends while watched.
  const [announcement, setAnnouncement] = useState("");
  const wasLive = useRef(live);
  useEffect(() => {
    if (wasLive.current && !live) {
      setAnnouncement(`Session ended: ${session.outcome ?? "ended"}. Summary available.`);
    }
    wasLive.current = live;
  }, [live, session.outcome]);

  // 1–4 switch tabs (spec 01 keyboard map).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
        return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const index = Number(event.key) - 1;
      const next = TABS[index];
      if (next) {
        setParams(
          (current) => {
            const copy = new URLSearchParams(current);
            if (next === "timeline") copy.delete("tab");
            else copy.set("tab", next);
            return copy;
          },
          { replace: false },
        );
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [setParams]);

  const streamDown = live && !events.health.open && events.health.closedSince !== null;
  const staleSince =
    collector.state === "offline" || streamDown
      ? new Date(events.health.lastMessageAt || collector.asOf.getTime())
      : null;
  const lastActivity = fmtClock(session.last_activity_at, tz);
  const waitingFor = Math.max(1, Math.round((now - Date.parse(session.last_activity_at)) / 60_000));

  return (
    <>
      <Header session={session} now={now} staleSince={staleSince} />
      <div className="sd-body ah-stack">
        {session.status === "waiting" && (
          <Banner
            tone="warning"
            icon="hand"
            boxed
            action={
              <AppLink className="ah-btn ah-btn-sm" href="/approvals">
                Open Approvals
              </AppLink>
            }
          >
            Waiting for approval{session.issue ? ` · ${session.issue}` : ""} ·{" "}
            {fmtDuration(waitingFor * 60)} · Approve in the terminal session or open Approvals
          </Banner>
        )}
        {session.status === "idle" && (
          <div className="sd-divider">No activity since {lastActivity}</div>
        )}
        {session.status === "ended" && session.end_inferred && (
          <div className="sd-divider">
            Ended · no end event received (last activity {lastActivity})
          </div>
        )}
        <SummaryCard
          session={session}
          onJump={jump}
          timeOf={(id) => {
            const at = times.get(id);
            return at ? fmtClock(at, tz, true) : null;
          }}
        />
        <Tabs
          label="Session views"
          value={tab}
          onChange={(id) => {
            setParam({ tab: id === "timeline" ? null : id }, true);
          }}
          tabs={[
            { id: "timeline", label: "Timeline", count: trace.total },
            { id: "files", label: "Files and diffs", count: session.files_touched },
            { id: "cost", label: "Cost" },
            { id: "raw", label: "Raw events", count: events.events.length },
          ]}
        />
        <div style={{ paddingTop: 8 }} role="tabpanel" aria-label={tab}>
          {tab === "timeline" && (
            <TimelineTab
              sessionId={session.id}
              trace={trace}
              eventCount={events.events.length}
              live={live}
              loading={events.loading}
              error={events.error}
              liveCount={events.liveCount}
              newIds={newIds}
              selected={selected}
              onSelect={(id) => {
                setParam({ event: id });
              }}
              initialFollow={initialFollow}
              query={params.get("q") ?? ""}
              onQuery={(q) => {
                setParam({ q });
              }}
              onClearView={() => {
                setParam({ q: null, errors: null });
              }}
              errorsOnly={params.get("errors") === "1"}
              onErrorsOnly={(on) => {
                setParam({ errors: on ? "1" : null });
              }}
              axis={params.get("axis") === "turn" ? "turn" : "time"}
              onAxis={(axis) => {
                setParam({ axis: axis === "turn" ? "turn" : null });
              }}
              focusLane={params.get("lane")}
            />
          )}
          {tab === "files" && (
            <FilesTab
              sessionId={session.id}
              events={events.events}
              onJump={(id) => {
                void navigate(
                  `/sessions/${encodeURIComponent(session.id)}?event=${encodeURIComponent(id)}`,
                );
              }}
            />
          )}
          {tab === "cost" && <CostTab sessionId={session.id} />}
          {tab === "raw" && <RawTab events={events.events} timelineRows={trace.total} />}
        </div>
        <div className="ah-sr" aria-live="polite" aria-atomic="true">
          {announcement}
        </div>
      </div>
    </>
  );
}
