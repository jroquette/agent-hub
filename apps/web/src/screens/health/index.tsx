import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Button,
  CodeBlock,
  ConfirmDialog,
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
import { useFindings, useFixHub, useHubs, useLiveFindings } from "./queries";

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
/** A rule group with more findings than this is split by file, so 174 cards become a few rows. */
const SPLIT_BY_FILE_ABOVE = 10;
/** Rows a file shows before "Show N more". */
const FILE_ROWS_FIRST = 20;
/** The rules `hub doctor --fix` fixes without a person, and what it does for each. */
const AUTO_FIX: Record<string, string> = {
  "brain.leak":
    "rewrites the brain note, never a repo: a promoted draft becomes a short stub pointing at the repo file, and other copied lines become one pointer line each.",
};
const FIX_KINDS = ["auto", "person"] as const;
type FixKind = (typeof FIX_KINDS)[number];
const FIX_LABEL: Record<FixKind, string> = { auto: "Auto-fixable", person: "Needs a person" };
const fixKind = (f: Finding): FixKind => (f.rule in AUTO_FIX ? "auto" : "person");
/** `brain/x.md` from "line also in the brain at brain/x.md:3" (brain.leak's message). */
const brainSource = (f: Finding) => /in the brain at (.+):\d+$/.exec(f.message)?.[1] ?? null;

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

function hubCommand(hubs: HubView[], args: string): string {
  const hub = hubs.length === 1 ? hubs[0] : undefined;
  return hub ? `cd ${hub.path} && ./hub ${args}` : `./hub ${args}`;
}

type FixResult = components["schemas"]["DoctorFixResult"];

/** What the last fix did: the files it wrote and what the check after it found. */
function FixOutcome({ result }: { result: FixResult }) {
  if (!result.ok) {
    return (
      <div className="ah-small" role="alert" style={{ color: "var(--failed)" }}>
        The fix did not run (exit {result.exit_code}). Nothing was written.{" "}
        {result.output.join(" ")}
      </div>
    );
  }
  const left =
    result.errors_left === null
      ? ""
      : ` Doctor ran again: ${plural(result.errors_left, "error")}, ${plural(result.warnings_left ?? 0, "warning")} left.`;
  return (
    <div className="ah-stack ah-small" role="status" aria-label="Fix result" style={{ gap: 4 }}>
      <span>
        <Icon name="circle-check" size="sm" style={{ color: "var(--done)" }} />{" "}
        {result.changed_files.length === 0
          ? "Nothing to fix: no file changed."
          : `Fixed ${plural(result.changed_files.length, "file")}.`}
        {left} Not committed: review with <span className="ah-mono">git diff brain/</span>, then
        open the hub PR.
      </span>
      {result.output.length > 0 && (
        <ul className="ah-muted" style={{ margin: 0, paddingLeft: 20 }}>
          {result.output.map((line) => (
            <li key={line} className="ah-mono" style={{ overflowWrap: "anywhere" }}>
              {line}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Under the summary: how many findings are fixed without a person, the button and the command. */
function FixStrip({ all, hubs }: { all: Finding[]; hubs: HubView[] }) {
  const fix = useFixHub();
  const [asking, setAsking] = useState(false);
  const hub = hubs.length === 1 ? hubs[0] : undefined;
  const result = hub && fix.data?.hub_id === hub.id ? fix.data : undefined;
  const auto = all.filter((f) => fixKind(f) === "auto");
  if (all.length === 0 && !result) return null;
  const person = all.length - auto.length;
  if (auto.length === 0) {
    return (
      <div className="ah-stack" style={{ gap: 6 }}>
        {result && <FixOutcome result={result} />}
        {all.length > 0 && (
          <div className="ah-small ah-muted ah-row" style={{ gap: 8 }}>
            <Icon name="file-pen" size="sm" />
            No finding can be fixed automatically. Each one needs a person.
          </div>
        )}
      </div>
    );
  }
  const files = new Set(auto.map((f) => brainSource(f) ?? f.path)).size;
  return (
    <section
      className="ah-card ah-stack"
      aria-label="Automatic fixes"
      style={{ padding: "12px 16px", gap: 8 }}
    >
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <Icon name="file-pen" size="sm" style={{ color: "var(--accent)" }} />
        <b style={{ fontWeight: 600 }}>
          {auto.length} of {all.length} findings can be fixed automatically
        </b>
        {person > 0 && <span className="ah-muted">· {person} need a person</span>}
        <span className="ah-grow" />
        {hub ? (
          <Button
            variant="primary"
            icon="file-pen"
            disabled={fix.isPending}
            onClick={() => {
              fix.reset();
              setAsking(true);
            }}
          >
            {fix.isPending ? "Fixing…" : `Fix ${plural(auto.length, "finding")}`}
          </Button>
        ) : (
          <Tooltip label="Pick one project in the top bar to fix its hub from here.">
            <span className="ah-small ah-subtle">Pick a project to fix</span>
          </Tooltip>
        )}
      </div>
      <div className="ah-small ah-muted">
        One fix handles them all, from {plural(files, "brain file")}. It writes only{" "}
        <span className="ah-mono">brain/</span>, never a repo, commits nothing and checks again.
        Review with <span className="ah-mono">git diff brain/</span>, then open the hub PR.
      </div>
      <CodeBlock code={hubCommand(hubs, "doctor --fix")} label="Fix command" />
      {result && <FixOutcome result={result} />}
      {fix.error && (
        <span className="ah-small" role="alert" style={{ color: "var(--failed)" }}>
          {fix.error.detail ?? fix.error.title}
        </span>
      )}
      {asking && hub && (
        <ConfirmDialog
          title={`Fix ${plural(auto.length, "finding")} in ${hub.project ?? hub.path}?`}
          tone="primary"
          consequences={[
            `Rewrites ${plural(files, "brain file")}: a promoted draft becomes a stub pointing at the repo file, other copied lines become pointers.`,
            "Writes only brain/ in the hub checkout, never a code repo.",
            "Nothing is committed: the draft text stays in git history, and you review the diff before the hub PR.",
            "Doctor runs again right after, so the list shows what is left.",
          ]}
          confirmLabel={fix.isPending ? "Fixing…" : "Fix"}
          pending={fix.isPending}
          onCancel={() => {
            setAsking(false);
          }}
          onConfirm={() => {
            fix.mutate(hub.id, {
              onSettled: () => {
                setAsking(false);
              },
            });
          }}
        />
      )}
    </section>
  );
}

/** One file of a large group: a row with its count, its findings on demand. */
function FileRow({
  path,
  findings,
  showProject,
}: {
  path: string;
  findings: Finding[];
  showProject: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  const source = findings[0] ? brainSource(findings[0]) : null;
  const rows = all ? findings : findings.slice(0, FILE_ROWS_FIRST);
  return (
    <div style={{ borderTop: "1px solid var(--border)" }}>
      <button
        type="button"
        className="ah-row ah-small"
        onClick={() => {
          setOpen(!open);
        }}
        aria-expanded={open}
        style={{
          width: "100%",
          padding: "8px 16px 8px 36px",
          border: 0,
          background: "none",
          font: "inherit",
          color: "var(--text)",
          cursor: "pointer",
          textAlign: "left",
          gap: 8,
        }}
      >
        <Icon
          name={open ? "chevron-down" : "chevron-right"}
          size="sm"
          style={{ color: "var(--text-subtle)" }}
        />
        <span className="ah-mono" style={{ overflowWrap: "anywhere" }}>
          {path}
        </span>
        <span className="ah-muted">{plural(findings.length, "line")}</span>
        {source && <span className="ah-subtle">· from {source}</span>}
      </button>
      {open && (
        <div style={{ paddingLeft: 20 }}>
          {rows.map((f, i) => (
            <FindingBlock key={`${location(f)}-${String(i)}`} f={f} showProject={showProject} />
          ))}
          {rows.length < findings.length && (
            <div style={{ padding: "4px 16px 10px 44px" }}>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setAll(true);
                }}
              >
                Show {findings.length - rows.length} more lines
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function byFile(findings: Finding[]): [string, Finding[]][] {
  const files = new Map<string, Finding[]>();
  for (const f of findings) {
    const path = f.path ?? "(no file)";
    files.set(path, [...(files.get(path) ?? []), f]);
  }
  return [...files.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
}

function GroupCard({
  group,
  open,
  onToggle,
  showProject,
  hubs,
}: {
  group: Group;
  open: boolean;
  onToggle: () => void;
  showProject: boolean;
  hubs: HubView[];
}) {
  const projects = [...new Set(group.findings.map((f) => f.project))];
  const autoFix = AUTO_FIX[group.rule];
  const split = group.findings.length > SPLIT_BY_FILE_ABOVE;
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
        <StatusBadge
          status={autoFix ? "done" : "idle"}
          label={autoFix ? "Auto-fix" : "Needs a person"}
          quiet
        />
        <span className="ah-fm-chip">
          <i>area</i> {areaOf(group.rule)}
        </span>
      </button>
      {open && autoFix && (
        <div className="ah-stack ah-small" style={{ padding: "10px 16px 10px 44px", gap: 6 }}>
          <span>
            <b style={{ fontWeight: 600 }}>How to fix all {group.findings.length}</b>{" "}
            <span className="ah-mono">./hub doctor --fix</span> {autoFix}
          </span>
          <CodeBlock
            code={hubCommand(hubs, `doctor --fix --only ${group.rule}`)}
            label={`Fix every ${group.rule} finding`}
          />
        </div>
      )}
      {open &&
        (split
          ? byFile(group.findings).map(([path, items]) => (
              <FileRow key={path} path={path} findings={items} showProject={showProject} />
            ))
          : group.findings.map((f, i) => (
              <FindingBlock key={`${location(f)}-${String(i)}`} f={f} showProject={showProject} />
            )))}
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
  const [fixes, setFixes] = useState<Record<string, boolean>>({});
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const all = findings.data?.items ?? [];
  const scopedHubs = (hubs.data?.items ?? []).filter(
    (hub) => scope === null || hub.project === scope,
  );
  const counts: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
  for (const f of all) counts[f.severity] += 1;
  const anySev = SEVERITIES.some((s) => sev[s]);
  const anyArea = Object.values(areas).some(Boolean);
  const anyFix = Object.values(fixes).some(Boolean);
  const shown = all.filter(
    (f) =>
      (!anySev || sev[f.severity]) &&
      (!anyArea || areas[areaOf(f.rule)]) &&
      (!anyFix || fixes[fixKind(f)]),
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
      id: "fix",
      title: "Fix",
      options: FIX_KINDS.map((k) => ({
        id: k,
        label: FIX_LABEL[k],
        count: all.filter((f) => fixKind(f) === k).length,
        checked: Boolean(fixes[k]),
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
    if (facet === "fix") setFixes((x) => ({ ...x, [option]: !x[option] }));
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
            setFixes({});
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
        hubs={scopedHubs}
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
      {findings.isSuccess && hubs.isSuccess && <FixStrip all={all} hubs={scopedHubs} />}
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
                  <span className="ah-mono">./hub doctor --fix</span> writes the hub checkout, never
                  a repo; you review it and open the hub PR. <Kbd>Ctrl K</Kbd> to search.
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
