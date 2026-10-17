import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Button,
  CodeBlock,
  EmptyState,
  FilterRail,
  FindingRow,
  Icon,
  Kbd,
  ProblemError,
  Skeleton,
  StatusBadge,
  Tooltip,
  copyText,
  useCopied,
  type Facet,
  type IconName,
  type Status,
} from "../../components";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { useCollectorState } from "../../shell/GlobalStream";
import { useFindings, useHubs, useLiveFindings } from "./queries";

type Finding = components["schemas"]["FindingView"];
type Severity = components["schemas"]["Severity"];
type HubView = components["schemas"]["HubView"];
type LockState = components["schemas"]["LockState"];

const SEVERITIES: readonly Severity[] = ["error", "warning", "info"];
const SEV: Record<Severity, { icon: IconName; tone: string; rank: number }> = {
  error: { icon: "circle-x", tone: "failed", rank: 0 },
  warning: { icon: "triangle-alert", tone: "waiting", rank: 1 },
  info: { icon: "info", tone: "idle", rank: 2 },
};
const SEV_TIP: Record<Severity, string> = {
  error: "Breaks the hub or a gate. Fix before the next run.",
  warning: "Works today, likely to cause a problem. Fix soon.",
  info: "For your information. No action required.",
};
/** The closed list of areas (spec 16); a rule's area is its prefix. */
const AREAS = ["config", "lock", "links", "instructions", "brain", "secrets", "settings"];
const LOCK: Record<LockState, [Status, string]> = {
  in_sync: ["done", "In sync"],
  drift: ["waiting", "Drift"],
  sync_pending: ["waiting", "Sync pending"],
  not_adopted: ["idle", "Not adopted"],
};
/** Groups open by default only while the list is short (spec 16). */
const OPEN_WARNINGS_UP_TO = 10;

const areaOf = (rule: string) => rule.split(".")[0] ?? rule;
const plural = (n: number, word: string) =>
  `${String(n)} ${word}${n === 1 || word === "info" ? "" : "s"}`;
const location = (f: Finding) => (f.path ? `${f.path}${f.line ? `:${String(f.line)}` : ""}` : "");

/** `- [warning] brain.memory .gitignore: message. Fix: fix` (spec 16). */
export function findingMarkdown(f: Finding): string {
  const where = location(f);
  return `- [${f.severity}] ${f.rule}${where ? ` ${where}` : ""}: ${f.message.replace(/\.$/, "")}. Fix: ${f.fix}`;
}

/** Commands quoted in a fix (`./hub sync`), shown as copyable blocks. */
function commandsIn(fix: string): string[] {
  return [...fix.matchAll(/`([^`]+)`/g)].flatMap((m) => (m[1] ? [m[1]] : []));
}

interface Group {
  rule: string;
  worst: Severity;
  findings: Finding[];
}

function groupByRule(findings: Finding[]): Group[] {
  const byRule = new Map<string, Finding[]>();
  for (const f of findings) byRule.set(f.rule, [...(byRule.get(f.rule) ?? []), f]);
  return [...byRule.entries()]
    .map(([rule, items]) => ({
      rule,
      findings: items,
      worst: items.reduce<Severity>(
        (w, f) => (SEV[f.severity].rank < SEV[w].rank ? f.severity : w),
        "info",
      ),
    }))
    .sort(
      (a, b) =>
        SEV[a.worst].rank - SEV[b.worst].rank ||
        b.findings.length - a.findings.length ||
        a.rule.localeCompare(b.rule),
    );
}

function countText(findings: Finding[]): string {
  return SEVERITIES.flatMap((s) => {
    const n = findings.filter((f) => f.severity === s).length;
    return n ? [plural(n, s)] : [];
  }).join(" · ");
}

function SevIcon({ s }: { s: Severity }) {
  return <Icon name={SEV[s].icon} size="sm" style={{ color: `var(--${SEV[s].tone})` }} />;
}

function CopyButton({
  label,
  text,
  quiet = true,
}: {
  label: string;
  text: string;
  quiet?: boolean;
}) {
  const [copied, markCopied] = useCopied();
  return (
    <Button
      size="sm"
      variant={quiet ? "ghost" : "default"}
      icon={copied ? "check" : "copy"}
      aria-label={label}
      onClick={() => {
        copyText(text);
        markCopied();
      }}
    >
      {copied ? "Copied" : label}
    </Button>
  );
}

function FindingBlock({ f, showProject }: { f: Finding; showProject: boolean }) {
  const commands = commandsIn(f.fix);
  return (
    <div style={{ borderTop: "1px solid var(--border)" }}>
      <FindingRow
        f={{
          severity: f.severity,
          rule: f.rule,
          path: f.path,
          line: f.line,
          message: f.message,
          // Quoted commands get their own copyable block below.
          fix: f.fix.replace(/`/g, ""),
        }}
      />
      {commands.length > 0 && (
        <div className="ah-stack" style={{ padding: "0 16px 0 48px", marginTop: -6, gap: 6 }}>
          {commands.map((command) => (
            <CodeBlock key={command} code={command} />
          ))}
        </div>
      )}
      <div className="ah-row ah-small" style={{ padding: "4px 16px 10px 44px", gap: 8 }}>
        <CopyButton label="Copy fix" text={f.fix} />
        <CopyButton label="Copy finding as Markdown" text={findingMarkdown(f)} />
        {f.rule === "platform.version" && (
          <Link to="/settings/hubs" className="ah-btn ah-btn-primary ah-btn-sm">
            <Icon name="refresh-cw" size="sm" />
            Sync in Settings
          </Link>
        )}
        <span className="ah-grow" />
        {showProject && <span className="ah-subtle">{f.project}</span>}
      </div>
    </div>
  );
}

function GroupCard({
  group,
  open,
  onToggle,
  showProject,
}: {
  group: Group;
  open: boolean;
  onToggle: () => void;
  showProject: boolean;
}) {
  const projects = [...new Set(group.findings.map((f) => f.project))];
  return (
    <section className="ah-card" style={{ overflow: "visible" }} aria-label={group.rule}>
      <button
        type="button"
        className="ah-row"
        onClick={onToggle}
        aria-expanded={open}
        style={{
          width: "100%",
          padding: "10px 16px",
          border: 0,
          background: "none",
          font: "inherit",
          color: "var(--text)",
          cursor: "pointer",
          borderBottom: open ? "1px solid var(--border)" : 0,
        }}
      >
        <Icon
          name={open ? "chevron-down" : "chevron-right"}
          size="sm"
          style={{ color: "var(--text-subtle)" }}
        />
        <SevIcon s={group.worst} />
        <span className="ah-rule" style={{ fontSize: 13 }}>
          {group.rule}
        </span>
        <span className="ah-small ah-muted">{countText(group.findings)}</span>
        <span className="ah-grow" />
        {showProject && <span className="ah-small ah-subtle">{projects.join(", ")}</span>}
        <span className="ah-fm-chip">
          <i>area</i> {areaOf(group.rule)}
        </span>
      </button>
      {open &&
        group.findings.map((f, i) => (
          <FindingBlock key={`${location(f)}-${String(i)}`} f={f} showProject={showProject} />
        ))}
    </section>
  );
}

function PlatformLine({ hub, named }: { hub: HubView; named: boolean }) {
  const lock = hub.lock_state ? LOCK[hub.lock_state] : null;
  const pending = hub.lock_version !== null && hub.lock_version !== hub.platform_pin;
  return (
    <span className="ah-row ah-wrap" style={{ gap: 8 }}>
      {named && <b style={{ fontWeight: 500 }}>{hub.project ?? hub.path}</b>}
      <span>
        <span className="ah-subtle">Platform </span>
        <span className="ah-mono">{hub.lock_version ?? "—"}</span> synced · pinned{" "}
        <span className="ah-mono">{hub.platform_pin ?? "—"}</span>
      </span>
      {pending && hub.lock_state !== "sync_pending" && (
        <StatusBadge
          status="waiting"
          label="Sync pending"
          title={`hub.lock ${hub.lock_version ?? ""}, hub.json platform.version ${hub.platform_pin ?? ""}`}
        />
      )}
      {lock && (
        <>
          <span className="ah-subtle">Lock</span>
          <StatusBadge status={lock[0]} label={lock[1]} />
        </>
      )}
      {hub.modules.length > 0 && (
        <span className="ah-subtle">Modules {hub.modules.join(" · ")}</span>
      )}
    </span>
  );
}

function Summary({
  counts,
  sev,
  onSev,
  hubs,
  loading,
}: {
  counts: Record<Severity, number>;
  sev: Record<Severity, boolean>;
  onSev: (s: Severity) => void;
  hubs: HubView[];
  loading: boolean;
}) {
  const command =
    hubs.length === 1 && hubs[0] ? `cd ${hubs[0].path} && ./hub doctor` : "./hub doctor";
  if (loading) {
    return (
      <div className="ah-card ah-pad ah-stack" aria-busy="true">
        <Skeleton width={420} height={20} />
        <Skeleton width={560} />
      </div>
    );
  }
  return (
    <div className="ah-card" style={{ padding: "12px 16px" }}>
      <div className="ah-row ah-wrap" style={{ gap: 16 }}>
        <div className="ah-row" role="group" aria-label="Findings by severity" style={{ gap: 8 }}>
          {SEVERITIES.map((s) => (
            <Tooltip key={s} label={`${SEV_TIP[s]} Click to filter.`}>
              <button
                type="button"
                onClick={() => {
                  onSev(s);
                }}
                aria-pressed={sev[s]}
                className="ah-row"
                style={{
                  border: 0,
                  background: sev[s] ? "var(--surface-sunken)" : "none",
                  borderRadius: "var(--radius-md)",
                  padding: "2px 8px",
                  font: "inherit",
                  color: "var(--text)",
                  cursor: "pointer",
                }}
              >
                {s === "error" && counts.error === 0 ? (
                  <Icon name="circle-check" style={{ color: "var(--done)" }} />
                ) : (
                  <Icon name={SEV[s].icon} style={{ color: `var(--${SEV[s].tone})` }} />
                )}
                <span
                  style={{ fontSize: 20, lineHeight: "28px", fontWeight: 600 }}
                  className="ah-num"
                >
                  {counts[s]}
                </span>{" "}
                <span className="ah-muted">{plural(counts[s], s).replace(/^\d+ /, "")}</span>
              </button>
            </Tooltip>
          ))}
        </div>
        <span style={{ width: 1, alignSelf: "stretch", background: "var(--border)" }} />
        <span className="ah-small">
          <span className="ah-subtle">Checked on request, cached up to 15 min · </span>
          <span className="ah-mono">./hub doctor</span> · exit {counts.error ? 1 : 0}
        </span>
        <span className="ah-grow" />
        <CopyButton label="Copy re-run command" text={command} quiet={false} />
        <Button size="sm" variant="primary" icon="play" phase="P4">
          Run doctor
        </Button>
      </div>
      {hubs.length > 0 && (
        <div
          className="ah-stack ah-small"
          style={{ gap: 6, marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--border)" }}
        >
          {hubs.map((hub) => (
            <PlatformLine key={hub.id} hub={hub} named={hubs.length > 1} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Health (spec 16, D22): doctor findings grouped by rule, "How to fix" first. */
export function HealthScreen() {
  const [scope] = useScope();
  const findings = useFindings(scope);
  const hubs = useHubs();
  useLiveFindings();
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();
  const [sev, setSev] = useState<Record<Severity, boolean>>({
    error: true,
    warning: true,
    info: false,
  });
  const [areas, setAreas] = useState<Record<string, boolean>>({});
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const all = findings.data?.items ?? [];
  const scopedHubs = (hubs.data?.items ?? []).filter(
    (hub) => scope === null || hub.project === scope,
  );
  const counts: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
  for (const f of all) counts[f.severity] += 1;
  const anySev = SEVERITIES.some((s) => sev[s]);
  const anyArea = Object.values(areas).some(Boolean);
  const shown = all.filter(
    (f) => (!anySev || sev[f.severity]) && (!anyArea || areas[areaOf(f.rule)]),
  );
  const groups = groupByRule(shown);
  const openByDefault = (g: Group) =>
    g.worst === "error" || (g.worst === "warning" && all.length <= OPEN_WARNINGS_UP_TO);
  const isOpen = (g: Group) => toggled[g.rule] ?? openByDefault(g);
  const areaList = [...new Set([...AREAS, ...all.map((f) => areaOf(f.rule))])];
  const showProject = scope === null && new Set(all.map((f) => f.project)).size > 1;
  const firstHub = scopedHubs[0];
  const rerun =
    scopedHubs.length === 1 && firstHub ? `cd ${firstHub.path} && ./hub doctor` : "./hub doctor";

  const facets: Facet[] = [
    {
      id: "severity",
      title: "Severity",
      options: SEVERITIES.map((s) => ({
        id: s,
        label: s.charAt(0).toUpperCase() + s.slice(1),
        count: counts[s],
        checked: sev[s],
        icon: <SevIcon s={s} />,
      })),
    },
    {
      id: "area",
      title: "Area",
      options: areaList.map((a) => ({
        id: a,
        label: a,
        count: all.filter((f) => areaOf(f.rule) === a).length,
        checked: Boolean(areas[a]),
      })),
    },
  ];
  const toggle = (facet: string, option: string) => {
    if (facet === "severity") setSev((s) => ({ ...s, [option]: !s[option as Severity] }));
    if (facet === "area") setAreas((a) => ({ ...a, [option]: !a[option] }));
  };
  const setAll = (open: boolean) => {
    setToggled(Object.fromEntries(groups.map((g) => [g.rule, open])));
  };

  let body: ReactNode;
  if (findings.isError) {
    body = (
      <ProblemError
        title={findings.error.title}
        detail={findings.error.detail}
        status={findings.error.status}
        instance={findings.error.instance}
        onRetry={() => void findings.refetch()}
      />
    );
  } else if (findings.isPending) {
    body = Array.from({ length: 3 }, (_, i) => (
      <div key={i} className="ah-card ah-pad ah-stack" aria-busy="true">
        <Skeleton width={260} height={14} />
        <Skeleton width="70%" />
        <Skeleton height={40} radius={6} />
      </div>
    ));
  } else if (all.length === 0) {
    body = (
      <div className="ah-card">
        <EmptyState
          icon="circle-check"
          title="No findings. The hub passed every doctor check."
          command={rerun}
        >
          Re-run after changing hub.json or upgrading the platform.
        </EmptyState>
      </div>
    );
  } else if (groups.length === 0) {
    body = (
      <div className="ah-small ah-muted">
        No findings match these filters.{" "}
        <button
          type="button"
          className="ah-btn ah-btn-sm ah-btn-ghost"
          onClick={() => {
            setSev({ error: true, warning: true, info: true });
            setAreas({});
          }}
        >
          Clear filters
        </button>
      </div>
    );
  } else {
    body = groups.map((g) => (
      <GroupCard
        key={g.rule}
        group={g}
        open={isOpen(g)}
        showProject={showProject}
        onToggle={() => {
          setToggled((t) => ({ ...t, [g.rule]: !isOpen(g) }));
        }}
      />
    ));
  }

  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 className="ah-h1">Health</h1>
        <span className="ah-subtle ah-small" style={{ marginTop: 8 }}>
          {scope
            ? `Doctor checks on the ${scope} hub${firstHub ? ` · ${firstHub.path}` : ""}`
            : "Doctor checks on every registered hub"}
        </span>
        <span className="ah-grow" />
        {state === "offline" && <AsOfStamp stale time={fmtClock(asOf, tz)} />}
      </div>
      <Summary
        counts={counts}
        sev={sev}
        onSev={(s) => {
          toggle("severity", s);
        }}
        hubs={scopedHubs}
        loading={findings.isPending}
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "220px 1fr",
          gap: 24,
          alignItems: "start",
          marginTop: 4,
        }}
      >
        <div>
          {findings.isPending ? (
            <Skeleton lines={10} />
          ) : (
            <FilterRail
              facets={facets}
              onToggle={toggle}
              footer={
                <div className="ah-small ah-subtle" style={{ marginTop: 12 }}>
                  Fixes are made by a person in a hub PR. <Kbd>Ctrl K</Kbd> to search.
                </div>
              }
            />
          )}
        </div>
        <div className="ah-stack" style={{ gap: 16, minWidth: 0 }}>
          <div className="ah-row">
            <h2 className="ah-h3">Findings, grouped by rule</h2>
            {findings.isSuccess && (
              <span className="ah-subtle ah-small">
                {shown.length} of {all.length} shown
              </span>
            )}
            <span className="ah-grow" />
            {groups.length > 0 && (
              <Fragment>
                <Button
                  size="sm"
                  variant="ghost"
                  icon="chevron-down"
                  onClick={() => {
                    setAll(true);
                  }}
                >
                  Expand all
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  icon="chevron-up"
                  onClick={() => {
                    setAll(false);
                  }}
                >
                  Collapse all
                </Button>
              </Fragment>
            )}
          </div>
          {body}
        </div>
      </div>
    </div>
  );
}
