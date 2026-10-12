import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Banner,
  Button,
  DataTable,
  DerivedLabel,
  EmptyState,
  Icon,
  IconButton,
  IssueLink,
  ProblemError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Tabs,
  Tooltip,
  copyText,
  useCopied,
  type IconName,
} from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { fmtClock, middleTruncate } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useCollectorState } from "../../shell/GlobalStream";
import {
  AcBar,
  FilterMenu,
  PHASES,
  VERDICT_STATUS,
  stepStates,
  type StepState,
} from "../features/parts";
import { NoteView } from "../brain/NoteView";
import { NotFoundBody } from "../not-found";
import { useFeature } from "./queries";

type Detail = components["schemas"]["FeatureDetail"];
type AcRow = components["schemas"]["AcRow"];

type Pass = "yes" | "owner" | "none";
const PASS: Record<Pass, { icon: IconName; tone: string; label: string; title: string }> = {
  yes: { icon: "circle-check", tone: "done", label: "yes", title: "Passes by command" },
  owner: { icon: "hand", tone: "waiting", label: "owner", title: "Manual owner step" },
  none: { icon: "circle-dashed", tone: "idle", label: "--", title: "Not passing yet" },
};
const passOf = (ac: AcRow): Pass => (ac.passes ? "yes" : ac.manual ? "owner" : "none");

type RecordName = components["schemas"]["FeatureRecordName"];

/** The record tabs, in golden-path order, each read from `brain/features/<slug>/<name>.md` (D3). */
const RECORDS: Readonly<
  Partial<Record<string, { name: RecordName; label: string; missing: string }>>
> = {
  spec: { name: "spec", label: "Spec", missing: "Specs are written by /feature in the hub." },
  research: {
    name: "research",
    label: "Research",
    missing: "Allowed for size spike. Research is written by /research in the hub.",
  },
  plan: { name: "plan", label: "Plan", missing: "Plans are written by /create-plan in the hub." },
  eval: {
    name: "eval",
    label: "Eval",
    missing: "The evaluator agent writes eval.md at the end of the golden path.",
  },
};

/** An AC description as a sentence, so the callout's next sentence reads on. */
function ownerLine(text: string | undefined): string {
  if (!text) return "";
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

/** Rows shown before "Show all": the first seven and the last two (spec 17). */
const HEAD_ROWS = 7;
const TAIL_ROWS = 2;

const STEP_META: Record<string, (d: Detail, state: StepState) => string> = {
  spec: (_, s) => (s === "skipped" ? "skipped · no spec.md" : "spec.md"),
  research: (_, s) => (s === "skipped" ? "skipped · no research.md" : "research.md"),
  plan: (_, s) => (s === "skipped" ? "skipped · no plan.md" : "plan.md"),
  tickets: (d, s) =>
    s === "skipped" ? "skipped · no issues.md" : `${String(d.issues.length)} issues`,
  implement: (d) => (d.acs ? `${String(d.acs.passing)} ACs passing` : "no features.json"),
  review: () => "needs runs; not tracked in this version",
  evaluate: (d) => d.verdict ?? "no eval.md",
  shipped: () => "GitHub not connected",
};

function Stepper({ detail }: { detail: Detail }) {
  const states = stepStates(detail);
  return (
    <ol
      className="ah-golden"
      style={{ listStyle: "none", margin: 0, padding: 0 }}
      aria-label="Golden path"
    >
      {PHASES.map((p, i) => {
        const state = states[i] ?? "pending";
        const dashed = state === "skipped" || state === "unknown";
        return (
          <li key={p.id} className="ah-golden-step" data-state={state}>
            {/* Only the dot fades: faded meta text would fail the contrast check (axe). */}
            <span
              className="ah-golden-dot"
              style={dashed ? { borderStyle: "dashed", opacity: 0.7 } : undefined}
            >
              {state === "done" && <Icon name="check" />}
            </span>
            <span className="ah-golden-name">{p.label}</span>
            <span className="ah-golden-meta" style={{ fontSize: 11 }}>
              {STEP_META[p.id]?.(detail, state)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function Cmd({ code }: { code: string }) {
  const [copied, markCopied] = useCopied();
  return (
    <span className="ah-row" style={{ gap: 4, justifyContent: "space-between" }}>
      <code
        className="ah-mono"
        title={code}
        style={{
          fontSize: 12,
          background: "var(--code-bg)",
          padding: "2px 6px",
          borderRadius: "var(--radius-sm)",
          whiteSpace: "nowrap",
        }}
      >
        {middleTruncate(code, 34)}
      </code>
      <IconButton
        size="sm"
        icon={copied ? "check" : "copy"}
        label={copied ? "Copied" : "Copy command"}
        onClick={() => {
          copyText(code);
          markCopied();
        }}
      />
    </span>
  );
}

function Gwt({ text }: { text: string }) {
  const m = /^Given (.*?), when (.*?), then (.*)$/.exec(text);
  if (!m) return <div className="ah-small">{text}</div>;
  return (
    <dl
      className="ah-small"
      style={{ display: "grid", gridTemplateColumns: "56px 1fr", gap: "2px 8px", margin: 0 }}
    >
      {(
        [
          ["Given", m[1]],
          ["When", m[2]],
          ["Then", m[3]],
        ] as const
      ).map(([k, v]) => (
        <Fragment key={k}>
          <dt style={{ fontWeight: 600 }}>{k}</dt>
          <dd style={{ margin: 0 }}>{v}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

/** A copyable verification command, shown whole (the row shows it truncated). */
function Verification({ ac }: { ac: AcRow }) {
  const [copied, markCopied] = useCopied();
  if (!ac.command) {
    return <span className="ah-subtle">No verification recorded.</span>;
  }
  const code = ac.command;
  return (
    <span className="ah-row" style={{ gap: 4, alignItems: "flex-start" }}>
      <code
        className="ah-mono"
        style={{
          fontSize: 12,
          background: "var(--code-bg)",
          padding: "2px 6px",
          borderRadius: "var(--radius-sm)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
        }}
      >
        {code}
      </code>
      <IconButton
        size="sm"
        icon={copied ? "check" : "copy"}
        label={copied ? "Copied" : `Copy the verification of ${ac.id}`}
        onClick={() => {
          copyText(code);
          markCopied();
        }}
      />
    </span>
  );
}

/** An expanded AC row (AC-201.37): its text, its verification command (copyable) and evidence. */
function AcDetail({ ac }: { ac: AcRow }) {
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <Gwt text={ac.description} />
      <dl
        className="ah-small"
        style={{ display: "grid", gridTemplateColumns: "88px 1fr", gap: "6px 8px", margin: 0 }}
      >
        <dt style={{ fontWeight: 600 }}>Verification</dt>
        <dd style={{ margin: 0 }}>
          {ac.manual && <span className="ah-muted">Manual owner step. </span>}
          <Verification ac={ac} />
        </dd>
        <dt style={{ fontWeight: 600 }}>Evidence</dt>
        <dd style={{ margin: 0 }}>
          {ac.evidence ?? <span className="ah-subtle">No evidence recorded yet.</span>}
        </dd>
      </dl>
    </div>
  );
}

/** "# AC-1\ncommand" for every non-manual command, deduplicated (spec 17). */
export function allCommands(rows: AcRow[]): string {
  const seen = new Set<string>();
  return rows
    .flatMap((ac) => {
      if (ac.manual || !ac.command || seen.has(ac.command)) return [];
      seen.add(ac.command);
      return [`# ${ac.id}`, ac.command];
    })
    .join("\n");
}

function AcTab({ detail }: { detail: Detail }) {
  const [params, setParams] = useSearchParams();
  const asked = params.get("ac");
  const [filter, setFilter] = useState<"all" | Pass>("all");
  const [repo, setRepo] = useState<string | null>(null);
  const [all, setAll] = useState(asked !== null);
  const [open, setOpen] = useState<string | null>(
    asked ?? detail.ac_rows.find((ac) => passOf(ac) === "owner")?.id ?? null,
  );
  const [copied, markCopied] = useCopied();
  if (detail.problem) {
    return (
      <ProblemError
        title="features.json could not be parsed"
        detail={`${detail.problem}. Fix it in a hub PR; the rest of the record is shown.`}
      />
    );
  }
  if (!detail.acs) {
    return (
      <div className="ah-card">
        <EmptyState icon="list-checks" title="No features.json yet.">
          Acceptance criteria are tracked once <span className="ah-mono">/create-plan</span> writes
          it.
        </EmptyState>
      </div>
    );
  }
  const rows = detail.ac_rows;
  const count = (p: Pass) => rows.filter((ac) => passOf(ac) === p).length;
  const repos = [...new Set(rows.flatMap((ac) => (ac.repo ? [ac.repo] : [])))];
  const filtered = rows.filter(
    (ac) => (filter === "all" || passOf(ac) === filter) && (repo === null || ac.repo === repo),
  );
  const folded =
    !all && filter === "all" && repo === null && filtered.length > HEAD_ROWS + TAIL_ROWS;
  const shown = folded
    ? [...filtered.slice(0, HEAD_ROWS), ...filtered.slice(-TAIL_ROWS)]
    : filtered;
  const toggle = (id: string) => {
    setOpen(open === id ? null : id);
    if (asked !== null) {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.delete("ac");
          return next;
        },
        { replace: true },
      );
    }
  };
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      <div className="ah-row ah-wrap">
        <SegmentedControl
          label="Filter acceptance criteria"
          value={filter}
          onChange={(id) => {
            setFilter(id as "all" | Pass);
          }}
          options={[
            { id: "all", label: `All ${String(rows.length)}` },
            { id: "yes", label: `Passing ${String(count("yes"))}` },
            { id: "owner", label: `Owner step ${String(count("owner"))}` },
            { id: "none", label: `Not verified ${String(count("none"))}` },
          ]}
        />
        {repos.length > 1 && (
          <FilterMenu
            label="Repo"
            value={repo}
            options={repos.map((r) => ({ id: r, label: r }))}
            onChange={setRepo}
          />
        )}
        <span className="ah-grow" />
        <Button
          size="sm"
          icon={copied ? "check" : "copy"}
          title="Copies the non-manual commands, one per line, each under its AC id"
          aria-label="Copy all commands"
          onClick={() => {
            copyText(allCommands(rows));
            markCopied();
          }}
        >
          {copied ? "Copied" : "Copy all commands"}
        </Button>
      </div>
      <div className="ah-table-wrap">
        <table className="ah-table ah-actable" aria-label="Acceptance criteria">
          <thead>
            <tr>
              <th scope="col" style={{ width: 36 }}>
                <span className="ah-sr">Details</span>
              </th>
              <th scope="col" style={{ width: 96 }}>
                ID
              </th>
              <th scope="col">Description</th>
              <th scope="col" style={{ width: 110 }}>
                Repo
              </th>
              <th scope="col" style={{ width: 92 }}>
                Passes
              </th>
              <th scope="col" style={{ width: 176 }}>
                Evidence
              </th>
              <th scope="col" style={{ width: 300 }}>
                Verify
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((ac, i) => {
              const pass = PASS[passOf(ac)];
              const expanded = open === ac.id;
              return (
                <Fragment key={ac.id}>
                  {folded && i === HEAD_ROWS && (
                    <tr style={{ cursor: "default" }}>
                      <td
                        colSpan={7}
                        style={{ textAlign: "center", background: "var(--surface-sunken)" }}
                      >
                        <button
                          type="button"
                          className="ah-btn ah-btn-sm ah-btn-ghost"
                          onClick={() => {
                            setAll(true);
                          }}
                        >
                          <Icon name="chevron-down" size="sm" />
                          Show all {rows.length} ({filtered.length - shown.length} more)
                        </button>
                      </td>
                    </tr>
                  )}
                  <tr
                    style={{
                      cursor: "default",
                      background: passOf(ac) === "owner" ? "var(--waiting-soft)" : undefined,
                    }}
                  >
                    <td>
                      <IconButton
                        size="sm"
                        icon={expanded ? "chevron-down" : "chevron-right"}
                        label={`${expanded ? "Collapse" : "Expand"} ${ac.id}`}
                        aria-expanded={expanded}
                        onClick={() => {
                          toggle(ac.id);
                        }}
                      />
                    </td>
                    <td className="ah-mono" style={{ fontSize: 12 }}>
                      {ac.id}
                    </td>
                    <td
                      className="ah-ac-desc"
                      style={{
                        whiteSpace: expanded ? "normal" : "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        maxWidth: 360,
                      }}
                    >
                      {ac.description}
                    </td>
                    <td className="ah-mono ah-small">{ac.repo ?? "—"}</td>
                    <td>
                      <span
                        className="ah-pass"
                        style={{ color: `var(--${pass.tone})` }}
                        title={pass.title}
                      >
                        <Icon name={pass.icon} size="sm" />
                        {pass.label}
                      </span>
                    </td>
                    <td
                      className="ah-small"
                      title={ac.evidence ?? undefined}
                      style={{ maxWidth: 176, overflow: "hidden", textOverflow: "ellipsis" }}
                    >
                      {ac.evidence ?? <span className="ah-subtle">—</span>}
                    </td>
                    <td>
                      {ac.command && !ac.manual ? (
                        <Cmd code={ac.command} />
                      ) : (
                        <span className="ah-small">manual · see eval.md</span>
                      )}
                    </td>
                  </tr>
                  {expanded && (
                    <tr style={{ cursor: "default" }}>
                      <td />
                      <td
                        colSpan={6}
                        style={{
                          whiteSpace: "normal",
                          padding: "10px 12px 14px",
                          background: "var(--surface-sunken)",
                        }}
                      >
                        <AcDetail ac={ac} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        <div className="ah-table-foot">
          <span>
            Showing {shown.length} of {rows.length} · from{" "}
            <span className="ah-mono">brain/features/{detail.slug}/features.json</span>
          </span>
        </div>
      </div>
    </div>
  );
}

function Verdict({ detail }: { detail: Detail }) {
  if (!detail.verdict) return null;
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <StatusBadge status={VERDICT_STATUS[detail.verdict]} label={detail.verdict} />
      {detail.verdict_line && (
        <blockquote
          className="ah-mono ah-small"
          style={{
            margin: 0,
            background: "var(--surface-sunken)",
            borderLeft: "2px solid var(--border-strong)",
            padding: "6px 12px",
            borderRadius: "var(--radius-sm)",
          }}
        >
          {detail.verdict_line}
        </blockquote>
      )}
    </div>
  );
}

/** A record tab (Spec, Research, Plan, Eval): the note itself, read through the brain route (D3). */
function RecordTab({ detail, tab }: { detail: Detail; tab: string }) {
  const meta = RECORDS[tab];
  if (!meta) return null;
  const file = `${meta.name}.md`;
  const record = detail.records.find((r) => r.name === meta.name);
  const verdict = meta.name === "eval" ? <Verdict detail={detail} /> : null;
  if (!record?.present) {
    return (
      <div className="ah-card">
        <EmptyState icon="file-text" title={`No ${file} yet.`}>
          {meta.missing}
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="ah-card ah-pad ah-stack" style={{ gap: 12 }}>
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <Icon name="file-text" size="sm" />
        <span className="ah-mono ah-small">brain/{record.path}</span>
        <span className="ah-grow" />
        <Link className="ah-small" to={brainRoute(detail.project, record.path)}>
          Open in Brain
        </Link>
      </div>
      {verdict}
      <NoteView
        key={record.path}
        project={detail.project}
        path={record.path}
        missing={`No ${file} yet.`}
      />
    </div>
  );
}

function IssuesTab({ detail }: { detail: Detail }) {
  return (
    <DataTable
      caption="Issues"
      rowKey={(key) => key}
      rows={detail.issues}
      empty={<EmptyState icon="list-todo" title="No issues listed for this feature." />}
      columns={[
        { id: "issue", label: "Issue", render: (key) => <IssueLink id={key} /> },
        {
          id: "title",
          label: "Title",
          render: () => (
            <Tooltip label="Linear is not connected in this version.">
              <span className="ah-subtle">—</span>
            </Tooltip>
          ),
        },
      ]}
      footer="From spec.md and features.json · Linear and GitHub are not connected in this version"
    />
  );
}

function Loading() {
  return (
    <div style={{ padding: "16px 32px" }} className="ah-stack" aria-busy="true">
      <Skeleton width={320} height={28} />
      <Skeleton width={620} />
      <div className="ah-row" style={{ gap: 0, margin: "16px 0" }}>
        {PHASES.map((p) => (
          <div key={p.id} className="ah-grow ah-stack">
            <Skeleton width={16} height={16} radius={8} />
            <Skeleton width="60%" />
          </div>
        ))}
      </div>
      {Array.from({ length: 10 }, (_, i) => (
        <Skeleton key={i} height={28} />
      ))}
    </div>
  );
}

/** Feature detail (spec 17, D23): golden path, owner steps, acceptance criteria. */
export function FeatureDetailScreen() {
  const { project = "", slug = "" } = useParams();
  const feature = useFeature(project, slug);
  const [params, setParams] = useSearchParams();
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();
  const tab = params.get("doc") ?? "acs";

  if (feature.isError) {
    if (feature.error.status === 404) {
      return <NotFoundBody line={`No feature ${slug} in ${project}.`} query={slug} />;
    }
    return (
      <div style={{ padding: "16px 32px" }} className="ah-stack">
        <h1 className="ah-h1 ah-mono">{slug}</h1>
        <div style={{ maxWidth: 720 }}>
          <ProblemError
            title={feature.error.title}
            detail={feature.error.detail}
            status={feature.error.status}
            onRetry={() => void feature.refetch()}
          />
        </div>
      </div>
    );
  }
  if (feature.isPending) return <Loading />;

  const detail = feature.data;
  const owners = detail.ac_rows.filter((ac) => passOf(ac) === "owner");
  const setTab = (id: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id === "acs") next.delete("doc");
        else next.set("doc", id);
        return next;
      },
      { replace: true },
    );
  };
  const tabs = [
    ...Object.entries(RECORDS).map(([id, meta]) => ({ id, label: meta?.label ?? id })),
    { id: "acs", label: "Criteria", count: detail.acs?.total },
    { id: "issues", label: "Issues", count: detail.issues.length },
  ];
  let body: ReactNode;
  if (tab === "issues") body = <IssuesTab detail={detail} />;
  else if (RECORDS[tab]) body = <RecordTab detail={detail} tab={tab} />;
  else body = <AcTab detail={detail} />;

  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <div className="ah-stack" style={{ gap: 6 }}>
        <div className="ah-row ah-wrap" style={{ gap: 12 }}>
          <h1 className="ah-h1">{detail.slug}</h1>
          {detail.verdict && (
            <StatusBadge
              status={VERDICT_STATUS[detail.verdict]}
              label={detail.verdict}
              title="Verdict from eval.md"
            />
          )}
          {detail.size && <span className="ah-fm-chip">{detail.size}</span>}
          <span className="ah-small ah-muted">
            {detail.project}
            {detail.repos.length && detail.repos.join(",") !== detail.project
              ? ` · ${detail.repos.join(", ")}`
              : ""}
          </span>
          <span className="ah-grow" />
          {state === "offline" && <AsOfStamp stale time={fmtClock(asOf, tz)} />}
        </div>
        <div className="ah-row ah-wrap ah-small" style={{ gap: 14 }}>
          {detail.issues.length > 0 && (
            <span className="ah-row" style={{ gap: 8 }}>
              {detail.issues.map((key) => (
                <IssueLink key={key} id={key} />
              ))}
            </span>
          )}
          <Tooltip label="GitHub is not connected in this version.">
            <span className="ah-row ah-subtle" style={{ gap: 4 }}>
              <Icon name="git-pull-request" size="sm" />
              PR —
            </span>
          </Tooltip>
          {detail.acs && (
            <>
              <span style={{ width: 1, height: 16, background: "var(--border)" }} />
              <AcBar acs={detail.acs} width={180} ownerIds={owners.map((ac) => ac.id)} />
            </>
          )}
        </div>
      </div>
      <div className="ah-card" style={{ padding: "16px 20px 14px" }}>
        <div className="ah-row" style={{ marginBottom: 10 }}>
          <b className="ah-small">Golden path</b>
          <DerivedLabel how="Each step is derived from the record's files; review needs runs and shipped needs GitHub, not connected in this version.">
            Phase · derived from the record files
          </DerivedLabel>
        </div>
        <Stepper detail={detail} />
      </div>
      {owners.length > 0 && (
        <Banner tone="warning" boxed icon="hand">
          <b>
            {owners.length} owner step{owners.length === 1 ? "" : "s"} left:{" "}
            {owners.map((ac) => ac.id).join(", ")}
          </b>{" "}
          {ownerLine(owners[0]?.description)} Recorded in features.json as passes:false (manual
          owner step).
        </Banner>
      )}
      <Tabs
        tabs={tabs}
        value={RECORDS[tab] || tab === "issues" ? tab : "acs"}
        onChange={setTab}
        label="Feature record"
      />
      <div style={{ paddingTop: 4 }}>{body}</div>
    </div>
  );
}
