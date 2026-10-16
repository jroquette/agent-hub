import { Fragment, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import type { components } from "../api/schema";

import { useNow } from "../lib/clock";
import { fmtDuration, fmtMoney, fmtTokens } from "../lib/format";
import { AppLink, IconButton, IdChip, IssueLink, Tooltip, Button, type Phase } from "./core";
import { Sparkline } from "./data";
import { Icon, type IconName } from "./Icon";
import {
  MiniStageBar,
  ProvenanceBadge,
  StatusBadge,
  type Provenance,
  type Stage,
  type Status,
} from "./status";
import { CodeBlock } from "./trace";

const NOT_CONNECTED = (source: string) => `${source} is not connected in this version.`;

/* ---------- Session tile (the Sessions grid) ---------- */
export interface LiveSession {
  id: string;
  status: "live" | "waiting" | "idle" | "ended";
  outcome?: Status | undefined;
  outcomeLabel?: string | undefined;
  reason?: string | undefined;
  reasonIcon?: IconName | undefined;
  /** What the session is about: "TIP-1511 · /feature" (never the agent; see SessionLabel). */
  title: string;
  /** "repo · branch" or the short id, under the title. */
  detail?: string | null | undefined;
  subagent?: boolean | undefined;
  project: string;
  repo: string | null;
  issue?: string | null | undefined;
  issueTitle?: string | null | undefined;
  step?: string | null | undefined;
  lastAction: string;
  lastIcon?: IconName | undefined;
  lastAgo?: string | undefined;
  /** A gate keeps failing: shown under the last action, never a red edge alone. */
  notice?: string | null | undefined;
  /** Where a waiting session is answered: its chat or the approvals. */
  link?: { href: string; label: string } | null | undefined;
  /** Driven from hub web: a "Chat" badge. */
  chat?: boolean | undefined;
  /** Seconds. */
  elapsed: number;
  /** Null when the source does not know it (a driven session without an observed twin): "—". */
  turns: number | null;
  tokens: number;
  files: number | null;
  /** USD, null when unknown. */
  cost: number | null;
  /** The owner-facing problems line: "2 problems, handled by the agent" or "Needs you: …". */
  problems?: string | null | undefined;
  /** A problem needs the owner: the only case that edges the tile in red (AC-201.14). */
  needsYou?: boolean | undefined;
  denials?: number | undefined;
  /** Events per 5 s over the last 60 s. */
  activity?: number[] | undefined;
}

/** The tile fields that change with the clock. */
export type TileTimes = Pick<LiveSession, "elapsed" | "lastAction" | "lastAgo">;

export interface SessionTileProps {
  s: LiveSession;
  /**
   * A running tile's times at `now`: only the parts that show them read the second clock, so a tick
   * re-renders those, not the tile. Without it the tile shows `s` as given.
   */
  times?: ((now: number) => TileTimes) | undefined;
  onOpen?: (() => void) | undefined;
  hoverEvents?: { time: string; icon: IconName; text: string }[] | undefined;
}

/** Renders `children` with the times at each second. */
function Ticking({
  times,
  children,
}: {
  times: (now: number) => TileTimes;
  children: (t: TileTimes) => ReactNode;
}) {
  return children(times(useNow(1000)));
}

function TileAction({ s, t }: { s: LiveSession; t: TileTimes }) {
  return (
    <div className="ah-tile-action" title={t.lastAction}>
      <Icon
        name={s.lastIcon ?? "terminal"}
        size="sm"
        style={{ color: "var(--ev-tool)", flex: "none", alignSelf: "center" }}
      />
      <span>{t.lastAction}</span>
      <span className="ah-subtle ah-small" style={{ flex: "none", marginLeft: "auto" }}>
        {t.lastAgo}
      </span>
    </div>
  );
}

export function SessionTile({ s, times, onOpen, hoverEvents }: SessionTileProps) {
  const [hover, setHover] = useState(false);
  const badgeStatus: Status = s.status === "ended" ? (s.outcome ?? "ended") : s.status;
  return (
    // Tiles open on click or Enter; the screen adds arrow-key grid navigation (spec 01).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <article
      className="ah-tile"
      data-key={s.id}
      data-status={s.status}
      data-trouble={s.needsYou ? "true" : undefined}
      // Tiles are a keyboard grid (spec 01): Enter opens the focused tile.
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) onOpen?.();
      }}
      onMouseEnter={() => {
        setHover(true);
      }}
      onMouseLeave={() => {
        setHover(false);
      }}
      aria-label={`${s.title} in ${s.project}, ${s.status}`}
    >
      <div className="ah-tile-head">
        <StatusBadge
          status={badgeStatus}
          label={
            s.status === "ended" ? `Ended · ${s.outcomeLabel ?? s.outcome ?? "done"}` : undefined
          }
        />
        <span className="ah-grow" />
        {s.issue && <IssueLink id={s.issue} title={s.issueTitle} />}
        <IconButton size="sm" icon="ellipsis" label="Session actions" />
      </div>
      <div className="ah-row" style={{ gap: 6, minWidth: 0 }}>
        <Icon
          name={s.subagent ? "network" : "square-terminal"}
          size="sm"
          style={{ color: "var(--text-subtle)" }}
        />
        <span className="ah-tile-agent" title={s.title}>
          {s.title}
        </span>
        {s.chat && (
          <span className="ah-badge" title="Started from hub web: opens the chat">
            Chat
          </span>
        )}
      </div>
      {s.detail && (
        <div className="ah-mono ah-small ah-subtle ah-tile-detail" title={s.detail}>
          {s.detail}
        </div>
      )}
      <div className="ah-tile-proj">
        {s.project} › {s.repo ?? "—"}
        {s.step ? ` · run step ${s.step}` : ""}
      </div>
      {s.status === "waiting" && (
        <div className="ah-tile-reason">
          <Icon name={s.reasonIcon ?? "hand"} size="sm" />
          {s.reason}
        </div>
      )}
      {times ? (
        <Ticking times={times}>{(t) => <TileAction s={s} t={t} />}</Ticking>
      ) : (
        <TileAction s={s} t={s} />
      )}
      {s.notice && (
        <div className="ah-row ah-small" style={{ gap: 4, color: "var(--text-muted)" }}>
          <Icon name="circle-x" size="sm" />
          {s.notice}
        </div>
      )}
      {s.link && (
        <AppLink
          href={s.link.href}
          className="ah-small"
          style={{ fontWeight: 500, alignSelf: "flex-start" }}
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          {s.link.label}
        </AppLink>
      )}
      {s.problems && (
        <div
          className="ah-row ah-small"
          style={{ gap: 4, minWidth: 0, color: s.needsYou ? "var(--failed)" : "var(--text-muted)" }}
          title={s.problems}
        >
          <Icon
            name={s.needsYou ? "circle-x" : "circle-check"}
            size="sm"
            style={{ flex: "none" }}
          />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {s.problems}
          </span>
        </div>
      )}
      <div className="ah-tile-stats">
        <span>
          Elapsed
          <b>
            {times ? (
              <Ticking times={times}>{(t) => fmtDuration(t.elapsed)}</Ticking>
            ) : (
              fmtDuration(s.elapsed)
            )}
          </b>
        </span>
        <span>
          Turns<b>{s.turns ?? "—"}</b>
        </span>
        <span>
          Tokens<b>{fmtTokens(s.tokens)}</b>
        </span>
        <span>
          Files<b>{s.files ?? "—"}</b>
        </span>
      </div>
      <div className="ah-budget-label">
        <span>Cost so far</span>
        <b className="ah-num">{fmtMoney(s.cost)}</b>
      </div>
      <div className="ah-tile-foot">
        {s.status !== "ended" && (
          <>
            <Sparkline
              data={s.activity ?? [0]}
              bars
              width={120}
              height={18}
              label="Events per 5 s, last 60 s"
            />
            <span className="ah-subtle ah-small">events · 60 s</span>
          </>
        )}
        <span className="ah-grow" />
        {s.denials !== undefined && s.denials > 0 && (
          <span
            className="ah-row ah-small"
            style={{ gap: 4, color: "var(--guard)" }}
            title={`${String(s.denials)} guard ${s.denials === 1 ? "denial" : "denials"}`}
          >
            <Icon name="shield-x" size="sm" />
            {s.denials}
          </span>
        )}
      </div>
      {hover && hoverEvents && (
        <div
          className="ah-pop"
          style={{ top: "100%", left: 0, right: 0, marginTop: 6, padding: 8 }}
        >
          <div className="ah-overline" style={{ padding: "0 4px 4px" }}>
            Last 5 events
          </div>
          {hoverEvents.map((e, i) => (
            <div key={i} className="ah-row ah-small" style={{ height: 24, padding: "0 4px" }}>
              <span className="ah-mono ah-subtle" style={{ width: 60 }}>
                {e.time}
              </span>
              <Icon name={e.icon} size="sm" style={{ color: "var(--text-subtle)" }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {e.text}
              </span>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

/* ---------- Needs you: few items, verb first, age, direct link ---------- */
export type NeedsYouKind = "approval" | "failed" | "waiting" | "blocked" | "doctor" | "learning";
const NEED_ICON: Record<NeedsYouKind, [IconName, string]> = {
  approval: ["stamp", "waiting"],
  failed: ["circle-x", "failed"],
  waiting: ["hand", "waiting"],
  blocked: ["octagon-x", "blocked"],
  doctor: ["stethoscope", "failed"],
  learning: ["sprout", "learning"],
};
export interface NeedsYouEntry {
  kind: NeedsYouKind;
  verb: string;
  context: string;
  age: string;
  href: string;
}
export interface NeedsYouListProps {
  items: NeedsYouEntry[];
  more?: number;
  moreLabel?: string | undefined;
  moreHref?: string | undefined;
  liveCount?: number;
  loading?: boolean | undefined;
  /** "Since your last visit · 08:12". */
  since?: string | undefined;
}
export function NeedsYouList({
  items,
  more = 0,
  moreLabel,
  moreHref = "/approvals",
  liveCount = 0,
  loading,
  since,
}: NeedsYouListProps) {
  return (
    <section className="ah-needs" aria-labelledby="needs-title">
      <div className="ah-needs-head">
        <h2 id="needs-title" className="ah-h3">
          Needs you
        </h2>
        {items.length > 0 && (
          <span className="ah-nav-count" data-tone="waiting">
            {items.length + more}
          </span>
        )}
        <span className="ah-grow" />
        {since && <span className="ah-subtle ah-small">{since}</span>}
      </div>
      {items.length === 0 && !loading && (
        <div className="ah-needs-empty">
          <Icon name="circle-check" />
          <span>
            <b style={{ color: "var(--text)", fontWeight: 500 }}>Nothing needs you.</b> {liveCount}{" "}
            {liveCount === 1 ? "session" : "sessions"} running.
          </span>
        </div>
      )}
      {items.map((item, i) => {
        const [icon, tone] = NEED_ICON[item.kind];
        return (
          <AppLink key={i} className="ah-needs-item" data-tone={tone} href={item.href}>
            <Icon name={icon} />
            <span className="ah-row" style={{ minWidth: 0, gap: 8 }}>
              <span className="ah-needs-verb">{item.verb}</span>
              <span
                className="ah-subtle ah-small"
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              >
                {item.context}
              </span>
            </span>
            <span className="ah-needs-age">{item.age}</span>
            <Icon name="chevron-right" size="sm" style={{ color: "var(--text-subtle)" }} />
          </AppLink>
        );
      })}
      {more > 0 && (
        <AppLink
          className="ah-needs-item"
          href={moreHref}
          style={{ gridTemplateColumns: "20px 1fr auto" }}
        >
          <span />
          <span className="ah-small ah-muted">{moreLabel ?? `${String(more)} more`}</span>
          <Icon name="chevron-right" size="sm" />
        </AppLink>
      )}
    </section>
  );
}

/* ---------- Project card ---------- */
export interface ProjectCardData {
  name: string;
  hub: string;
  team: string;
  version: string;
  lockVersion?: string | null | undefined;
  syncPending?: boolean | undefined;
  repos: string[];
  health: "ok" | "warning" | "error" | null;
  healthLabel: string;
  live: number;
  runsInProgress: number;
  stages: Partial<Record<Stage, number>>;
  failedNow?: number | undefined;
  /** Null: GitHub is not connected. */
  prs: number | null;
  ciLabel?: string | undefined;
  ciTone?: string | undefined;
  failed7d: number;
  /** Null: Linear is not connected. */
  ready: number | null;
  cost: number | null;
  costDelta?: string | undefined;
  costDeltaTone?: "good" | "bad" | "neutral" | undefined;
  costSpark: number[];
  costPrev?: number[] | undefined;
}
const HEALTH_COLOR = { ok: "var(--done)", warning: "var(--waiting)", error: "var(--failed)" };
export function ProjectCard({ p, onOpen }: { p: ProjectCardData; onOpen?: () => void }) {
  return (
    // Cards open their project on click or Enter, as in the design.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <article
      className="ah-pcard"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      aria-label={`Project ${p.name}`}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) onOpen?.();
      }}
    >
      <div className="ah-row">
        <Tooltip label={p.healthLabel}>
          <span
            className="ah-health"
            role="img"
            style={{ background: p.health ? HEALTH_COLOR[p.health] : "var(--idle)" }}
            aria-label={p.healthLabel}
          />
        </Tooltip>
        <h3 className="ah-h3" style={{ fontSize: 15 }}>
          {p.name}
        </h3>
        <span className="ah-mono ah-subtle ah-small">{p.team}</span>
        <span className="ah-grow" />
        <span className="ah-mono ah-small ah-subtle">v{p.version}</span>
        {p.syncPending && (
          <span
            className="ah-badge ah-badge-waiting"
            title={`hub.lock ${p.lockVersion ?? "—"}, pin ${p.version}`}
          >
            <Icon name="refresh-cw" />
            Sync pending
          </span>
        )}
      </div>
      <div className="ah-pcard-grid">
        <div>
          <div className="ah-pcard-k">Live sessions</div>
          <div className="ah-pcard-v">
            {p.live > 0 && <span className="ah-dot ah-pulse" style={{ color: "var(--live)" }} />}
            {p.live}
          </div>
        </div>
        <div style={{ gridColumn: "span 2" }}>
          <div className="ah-pcard-k">Runs in progress · {p.runsInProgress}</div>
          <div className="ah-pcard-v" style={{ height: 20 }}>
            <MiniStageBar counts={p.stages} failed={p.failedNow ?? 0} />
          </div>
        </div>
        <div>
          <div className="ah-pcard-k">Open PRs</div>
          <div className="ah-pcard-v" title={p.prs === null ? NOT_CONNECTED("GitHub") : undefined}>
            {p.prs ?? "—"}
            {p.ciLabel && (
              <span
                className="ah-small"
                style={{
                  fontFamily: "var(--font-sans)",
                  fontWeight: 400,
                  color: p.ciTone ? `var(--${p.ciTone})` : "var(--text-subtle)",
                }}
              >
                {p.ciLabel}
              </span>
            )}
          </div>
        </div>
        <div>
          <div className="ah-pcard-k">Failed runs · 7 d</div>
          <div className="ah-pcard-v" style={{ color: p.failed7d ? "var(--failed)" : undefined }}>
            {p.failed7d}
          </div>
        </div>
        <div>
          <div className="ah-pcard-k">Ready issues</div>
          <div
            className="ah-pcard-v"
            title={p.ready === null ? NOT_CONNECTED("Linear") : undefined}
          >
            {p.ready ?? "—"}
          </div>
        </div>
        <div style={{ gridColumn: "span 3" }}>
          <div className="ah-pcard-k">Cost this week vs last</div>
          <div className="ah-row" style={{ justifyContent: "space-between" }}>
            <div className="ah-pcard-v">
              {fmtMoney(p.cost)}
              {p.costDelta && (
                <span className="ah-delta" data-tone={p.costDeltaTone ?? "neutral"}>
                  {p.costDelta}
                </span>
              )}
            </div>
            <Sparkline
              data={p.costSpark.length ? p.costSpark : [0]}
              prev={p.costPrev}
              width={120}
              height={22}
              label="Daily cost, this week vs last week"
            />
          </div>
        </div>
      </div>
      <div
        className="ah-row ah-small ah-subtle"
        style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}
      >
        <Icon name="book" size="sm" />
        {p.repos.join(" · ")}
        <span className="ah-grow" />
        <span>{p.hub}</span>
      </div>
    </article>
  );
}

/* ---------- Activity feed ---------- */
export type ActivityKind = "merged" | "reported" | "learning" | "doctor" | "failed" | "approval";
const FEED_ICON: Record<ActivityKind, [IconName, string]> = {
  merged: ["git-merge", "done"],
  reported: ["flag", "done"],
  learning: ["sprout", "ev-learning"],
  doctor: ["stethoscope", "failed"],
  failed: ["circle-x", "failed"],
  approval: ["stamp", "waiting"],
};
export interface ActivityEntry {
  kind: ActivityKind;
  text: string;
  node?: ReactNode;
  project: string;
  age: string;
}
export function ActivityFeed({ items }: { items: ActivityEntry[] }) {
  return (
    <ul className="ah-feed">
      {items.map((item, i) => {
        const [icon, color] = FEED_ICON[item.kind];
        return (
          <li key={i}>
            <Icon name={icon} size="sm" style={{ color: `var(--${color})` }} />
            <span>
              {item.node ?? item.text}
              <div className="ah-subtle" style={{ fontSize: 12 }}>
                {item.project}
              </div>
            </span>
            <span className="ah-mono ah-subtle" style={{ fontSize: 12 }}>
              {item.age}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------- Frontmatter chips and AC tables (notes render through Markdown.tsx) ---------- */
export interface Frontmatter {
  type?: string | undefined;
  status?: string | undefined;
  repos?: string[] | undefined;
  last_verified?: string | undefined;
  daysSinceVerified?: number | undefined;
  provenance?: Provenance | undefined;
}

export function FrontmatterChips({ fm }: { fm: Frontmatter }) {
  const stale = (fm.daysSinceVerified ?? 0) > 60;
  return (
    <div className="ah-fm">
      {fm.type && (
        <span className="ah-fm-chip">
          <i>type</i>
          {fm.type}
        </span>
      )}
      {fm.status && (
        <span className="ah-fm-chip">
          <i>status</i>
          {fm.status}
        </span>
      )}
      {fm.repos && (
        <span className="ah-fm-chip">
          <i>repos</i>
          {fm.repos.join(", ")}
        </span>
      )}
      {fm.last_verified && (
        <span
          className="ah-fm-chip"
          data-tone={stale ? "stale" : undefined}
          title={
            stale ? `Not verified for ${String(fm.daysSinceVerified)} days (over 60)` : undefined
          }
        >
          {stale && <Icon name="clock" size="sm" />}
          <i>last verified</i>
          {fm.last_verified}
        </span>
      )}
      {fm.provenance && <ProvenanceBadge provenance={fm.provenance} />}
    </div>
  );
}

export interface AcRowData {
  id: string;
  description: string;
  repo: string | null;
  passes: boolean;
  manual?: boolean | undefined;
  evidence?: string | null | undefined;
  command?: string | null | undefined;
}
export function AcTable({ acs }: { acs: AcRowData[] }) {
  return (
    <div className="ah-table-wrap">
      <table className="ah-table ah-actable">
        <thead>
          <tr>
            <th scope="col" style={{ width: 92 }}>
              AC
            </th>
            <th scope="col">Description</th>
            <th scope="col">Repo</th>
            <th scope="col">Passes</th>
            <th scope="col">Evidence</th>
            <th scope="col">Verify with</th>
          </tr>
        </thead>
        <tbody>
          {acs.map((ac) => (
            <tr key={ac.id} style={{ cursor: "default" }}>
              <td className="ah-mono" style={{ fontSize: 12 }}>
                {ac.id}
              </td>
              <td className="ah-ac-desc">{ac.description}</td>
              <td className="ah-mono ah-small">{ac.repo ?? "—"}</td>
              <td>
                {ac.passes ? (
                  <span className="ah-pass ah-pass-yes">
                    <Icon name="circle-check" size="sm" />
                    Passes
                  </span>
                ) : ac.manual ? (
                  <span className="ah-pass" style={{ color: "var(--waiting)" }}>
                    <Icon name="hand" size="sm" />
                    Owner step
                  </span>
                ) : (
                  <span className="ah-pass ah-pass-no">
                    <Icon name="circle-x" size="sm" />
                    Fails
                  </span>
                )}
              </td>
              <td className="ah-small ah-muted" style={{ whiteSpace: "normal", minWidth: 140 }}>
                {ac.evidence}
              </td>
              <td style={{ minWidth: 220 }}>
                {ac.command ? (
                  <CodeBlock code={ac.command} prompt="" />
                ) : (
                  <span className="ah-subtle ah-small">Manual</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Approval panel: material + consequences + P4 actions ---------- */
export interface ApprovalData {
  title: string;
  waiting: string;
  kindLabel: string;
  issue?: string | null | undefined;
  requestedBy: string;
  session: string;
  project: string;
  repo: string | null;
  changes: { icon?: IconName | undefined; text: ReactNode }[];
}
export interface ApprovalPanelProps {
  a: ApprovalData;
  /** "P2": answer in the terminal (hint); "P4": the action bar, disabled until Phase 4 (D21). */
  phase?: "P2" | Phase;
  children?: ReactNode;
}
export function ApprovalPanel({ a, phase = "P2", children }: ApprovalPanelProps) {
  return (
    <section className="ah-approval" aria-label={a.title}>
      <div className="ah-approval-head">
        <div className="ah-row">
          <StatusBadge status="waiting" label={`Waiting ${a.waiting}`} />
          <span className="ah-subtle ah-small">{a.kindLabel}</span>
          <span className="ah-grow" />
          {a.issue && <IssueLink id={a.issue} />}
        </div>
        <h2 className="ah-h2">{a.title}</h2>
        <div className="ah-row ah-small ah-subtle ah-wrap">
          Requested by{" "}
          <span className="ah-mono" style={{ color: "var(--text)" }}>
            {a.requestedBy}
          </span>{" "}
          in session <IdChip id={a.session} /> · {a.project} › {a.repo ?? "—"}
        </div>
      </div>
      <div className="ah-approval-body">
        <h3 className="ah-h3" style={{ fontSize: 14, marginBottom: 8 }}>
          What changes if you approve
        </h3>
        <ul className="ah-changes">
          {a.changes.map((change, i) => (
            <li key={i}>
              <Icon
                name={change.icon ?? "arrow-right"}
                size="sm"
                style={{ color: "var(--text-subtle)", marginTop: 2 }}
              />
              <span>{change.text}</span>
            </li>
          ))}
        </ul>
        <div style={{ marginTop: 16 }}>{children}</div>
      </div>
      <div className="ah-approval-foot">
        {phase === "P2" ? (
          <div className="ah-approve-hint">
            <Icon name="square-terminal" size="sm" style={{ marginTop: 2 }} />
            <span>
              Approve in the terminal session that asked: answer the prompt in{" "}
              <span className="ah-mono" style={{ color: "var(--text)" }}>
                {a.repo ?? a.project}
              </span>{" "}
              (session {a.session.replace(/-/g, "").slice(0, 8)}). Approving here arrives in Phase
              4.
            </span>
          </div>
        ) : (
          <Fragment>
            <Button variant="primary" icon="check" phase={phase}>
              Approve plan
            </Button>
            <Button icon="message-square" phase={phase}>
              Request changes
            </Button>
            <span className="ah-grow" />
            <Button variant="danger" icon="x" phase={phase}>
              Reject
            </Button>
          </Fragment>
        )}
      </div>
    </section>
  );
}

/* ---------- Golden path stepper (Features) ---------- */
export type GoldenStep = components["schemas"]["GoldenStep"];
type GoldenStepState = components["schemas"]["StepState"];
type FeaturePhase = components["schemas"]["FeaturePhase"];

export const GOLDEN_STEP_LABEL: Record<FeaturePhase, string> = {
  spec: "Spec",
  research: "Research",
  plan: "Plan",
  tickets: "Tickets",
  implement: "Implement",
  review: "Review",
  evaluate: "Evaluate",
  shipped: "Shipped",
};

/** Each state as text, so no state is told by color alone (AC-136.32). */
export const GOLDEN_STATE_TEXT: Record<GoldenStepState, string> = {
  done: "Done",
  partial: "Partial",
  current: "In progress",
  pending: "Not reached",
  skipped: "Skipped",
  unknown: "Unknown",
  blocked: "Blocked",
};

const GOLDEN_STATE_ICON: Partial<Record<GoldenStepState, IconName>> = {
  done: "check",
  blocked: "octagon-x",
  unknown: "circle-dashed",
};

/**
 * The steps as shown: a step the server marks done after a gate that is neither done nor skipped
 * is shown `blocked`, naming that gate, so the stepper never claims a step done after an
 * incomplete one (S8, AC-136.17).
 */
export function shownGoldenSteps(steps: readonly GoldenStep[]): GoldenStep[] {
  let gate: GoldenStep | null = null;
  return steps.map((step) => {
    if (gate && step.state === "done") {
      return { ...step, state: "blocked", reason: `${GOLDEN_STEP_LABEL[gate.name]} is not done` };
    }
    if (!gate && step.state !== "done" && step.state !== "skipped") gate = step;
    return step;
  });
}

/** "Evaluate: partial · partial: covers 3 of 36 ACs (Implement is not done)". */
export function goldenStepSummary(step: GoldenStep): string {
  const progress = step.progress
    ? `${String(step.progress.done)}/${String(step.progress.total)}`
    : null;
  const meta = step.meta ?? progress;
  const head = `${GOLDEN_STEP_LABEL[step.name]}: ${GOLDEN_STATE_TEXT[step.state].toLowerCase()}`;
  const reason = step.state !== "done" && step.reason ? ` (${step.reason})` : "";
  return `${head}${meta ? ` · ${meta}` : ""}${reason}`;
}

function progressPercent(step: GoldenStep): number | null {
  if (!step.progress || step.progress.total <= 0) return null;
  return Math.round(
    (100 * Math.min(step.progress.done, step.progress.total)) / step.progress.total,
  );
}

const DOT_STYLE: Partial<Record<GoldenStepState, CSSProperties>> = {
  partial: {
    background: "linear-gradient(90deg, var(--done) 50%, var(--surface) 50%)",
    borderColor: "var(--done)",
  },
  blocked: { borderColor: "var(--blocked)", color: "var(--blocked)" },
  skipped: { borderStyle: "dashed", opacity: 0.7 },
  unknown: { borderStyle: "dashed", opacity: 0.7 },
};

/**
 * The golden path of a feature as the server computes it (S8): each step's name, its state as
 * text, its meta, its progress and the reason it is not done.
 */
export function GoldenPathStepper({
  steps,
  label = "Golden path",
  onSelect,
  selectLabel,
}: {
  steps: readonly GoldenStep[];
  label?: string | undefined;
  /** Makes each step's name a button (e.g. to open the tab that holds its evidence). */
  onSelect?: ((step: FeaturePhase) => void) | undefined;
  /** The accessible name of a step's button; "Open <step>" by default. */
  selectLabel?: ((step: FeaturePhase) => string) | undefined;
}) {
  return (
    <ol
      className="ah-golden"
      style={{ listStyle: "none", margin: 0, padding: 0 }}
      aria-label={label}
    >
      {shownGoldenSteps(steps).map((step) => {
        const icon = GOLDEN_STATE_ICON[step.state];
        const percent = progressPercent(step);
        const count = step.progress
          ? `${String(step.progress.done)}/${String(step.progress.total)}`
          : null;
        return (
          <li key={step.name} className="ah-golden-step" data-state={step.state}>
            {/* Only the dot fades: faded text would fail the contrast check (axe). */}
            <span className="ah-golden-dot" style={DOT_STYLE[step.state]} aria-hidden="true">
              {icon && <Icon name={icon} />}
            </span>
            {onSelect ? (
              <button
                type="button"
                className="ah-golden-name ah-golden-select"
                aria-label={selectLabel?.(step.name) ?? `Open ${GOLDEN_STEP_LABEL[step.name]}`}
                onClick={() => {
                  onSelect(step.name);
                }}
              >
                {GOLDEN_STEP_LABEL[step.name]}
              </button>
            ) : (
              <span className="ah-golden-name">{GOLDEN_STEP_LABEL[step.name]}</span>
            )}
            <span className="ah-golden-meta" style={{ fontSize: 11, fontWeight: 500 }}>
              {GOLDEN_STATE_TEXT[step.state]}
            </span>
            {(step.meta ?? count) && (
              <span className="ah-golden-meta" style={{ fontSize: 11 }}>
                {step.meta ?? count}
              </span>
            )}
            {percent !== null && step.state !== "done" && (
              <span
                aria-hidden="true"
                data-progress={percent}
                style={{
                  display: "block",
                  height: 3,
                  marginRight: 8,
                  borderRadius: 2,
                  background: `linear-gradient(90deg, var(--done) ${String(percent)}%, var(--surface-sunken) ${String(percent)}%)`,
                }}
              />
            )}
            {step.reason && step.state !== "done" && (
              <span className="ah-golden-meta" style={{ fontSize: 11, color: "var(--text-muted)" }}>
                {step.reason}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/* ---------- Doctor finding ---------- */
export type Severity = "error" | "warning" | "info";
const SEVERITY: Record<Severity, { icon: IconName; color: string }> = {
  error: { icon: "circle-x", color: "failed" },
  warning: { icon: "triangle-alert", color: "waiting" },
  info: { icon: "info", color: "live" },
};
export interface FindingData {
  severity: Severity;
  rule: string;
  ruleHelp?: string | undefined;
  path?: string | null | undefined;
  line?: number | null | undefined;
  href?: string | undefined;
  message: string;
  fix: string;
}
export function FindingRow({ f }: { f: FindingData }) {
  const look = SEVERITY[f.severity];
  const location = f.path ? `${f.path}${f.line ? `:${String(f.line)}` : ""}` : null;
  return (
    <div className="ah-finding" data-sev={f.severity}>
      <Icon name={look.icon} title={f.severity} />
      <div className="ah-stack" style={{ gap: 2 }}>
        <div className="ah-row ah-wrap">
          <span
            className="ah-caption"
            style={{ color: `var(--${look.color})`, textTransform: "capitalize" }}
          >
            {f.severity}
          </span>
          <Tooltip label={f.ruleHelp}>
            <span className="ah-rule">{f.rule}</span>
          </Tooltip>
          {location &&
            (f.href ? (
              <AppLink className="ah-mono ah-small" href={f.href}>
                {location}
              </AppLink>
            ) : (
              <span className="ah-mono ah-small">{location}</span>
            ))}
        </div>
        <div>{f.message}</div>
        <div className="ah-fix">
          <b>How to fix</b>
          <span>{f.fix}</span>
        </div>
      </div>
    </div>
  );
}
