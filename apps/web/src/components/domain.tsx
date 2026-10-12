import { Fragment, useState } from "react";
import type { ReactNode } from "react";

import { fmtDuration, fmtMoney, fmtTokens } from "../lib/format";
import { AppLink, IconButton, IdChip, IssueLink, Tooltip, Button, type Phase } from "./core";
import { Sparkline } from "./data";
import { Icon, type IconName } from "./Icon";
import {
  BudgetBar,
  MiniStageBar,
  ProvenanceBadge,
  StatusBadge,
  type Provenance,
  type Stage,
  type Status,
} from "./status";
import { CodeBlock } from "./trace";

const NOT_CONNECTED = (source: string) => `${source} is not connected in this version.`;

/* ---------- Session tile (Live sessions) ---------- */
export interface LiveSession {
  id: string;
  status: "live" | "waiting" | "idle" | "ended";
  outcome?: Status | undefined;
  outcomeLabel?: string | undefined;
  reason?: string | undefined;
  reasonIcon?: IconName | undefined;
  /** What the session is about: "DEMO-1511 · /feature" (never the agent; see SessionLabel). */
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
  lastActionNode?: ReactNode;
  lastIcon?: IconName | undefined;
  lastAgo?: string | undefined;
  /** Seconds. */
  elapsed: number;
  turns: number;
  tokens: number;
  files: number;
  /** USD, null when unknown. */
  cost: number | null;
  budget?: number | null | undefined;
  projection?: string | undefined;
  /** The owner-facing problems line: "2 problems, handled by the agent" or "Needs you: …". */
  problems?: string | null | undefined;
  /** A problem needs the owner: the only case that edges the tile in red (AC-201.14). */
  needsYou?: boolean | undefined;
  denials?: number | undefined;
  /** Events per 5 s over the last 60 s. */
  activity?: number[] | undefined;
}

export interface SessionTileProps {
  s: LiveSession;
  onOpen?: (() => void) | undefined;
  hoverEvents?: { time: string; icon: IconName; text: string }[] | undefined;
}
export function SessionTile({ s, onOpen, hoverEvents }: SessionTileProps) {
  const [hover, setHover] = useState(false);
  const badgeStatus: Status = s.status === "ended" ? (s.outcome ?? "ended") : s.status;
  return (
    // Tiles open on click or Enter; the screen adds arrow-key grid navigation (spec 01).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <article
      className="ah-tile"
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
      <div className="ah-tile-action" title={s.lastAction}>
        <Icon
          name={s.lastIcon ?? "terminal"}
          size="sm"
          style={{ color: "var(--ev-tool)", flex: "none", alignSelf: "center" }}
        />
        <span>{s.lastActionNode ?? s.lastAction}</span>
        <span className="ah-subtle ah-small" style={{ flex: "none", marginLeft: "auto" }}>
          {s.lastAgo}
        </span>
      </div>
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
          Elapsed<b>{fmtDuration(s.elapsed)}</b>
        </span>
        <span>
          Turns<b>{s.turns}</b>
        </span>
        <span>
          Tokens<b>{fmtTokens(s.tokens)}</b>
        </span>
        <span>
          Files<b>{s.files}</b>
        </span>
      </div>
      {s.budget ? (
        <BudgetBar
          spent={s.cost ?? 0}
          budget={s.budget}
          label="Run budget"
          projection={s.projection}
        />
      ) : (
        <div className="ah-budget-label">
          <span>Cost so far</span>
          <b className="ah-num">{fmtMoney(s.cost)}</b>
        </div>
      )}
      <div className="ah-tile-foot">
        <Sparkline
          data={s.activity ?? [0]}
          bars
          width={120}
          height={18}
          label="Events per 5 s, last 60 s"
        />
        <span className="ah-subtle ah-small">events · 60 s</span>
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
export interface GoldenStep {
  name: string;
  state: "done" | "current" | "pending";
  date?: string | null | undefined;
  by?: string | undefined;
}
export function GoldenPathStepper({ steps }: { steps: GoldenStep[] }) {
  return (
    <ol className="ah-golden" style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {steps.map((step) => (
        <li key={step.name} className="ah-golden-step" data-state={step.state}>
          <span className="ah-golden-dot">{step.state === "done" && <Icon name="check" />}</span>
          <span className="ah-golden-name">{step.name}</span>
          <span className="ah-golden-meta">
            {step.date ?? (step.state === "current" ? "In progress" : "—")}
          </span>
          {step.by && (
            <span className="ah-golden-meta ah-mono" style={{ fontSize: 11 }}>
              {step.by}
            </span>
          )}
        </li>
      ))}
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
