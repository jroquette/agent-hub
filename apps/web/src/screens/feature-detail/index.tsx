import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  AsOfStamp,
  Banner,
  Button,
  DerivedLabel,
  EmptyState,
  GoldenPathStepper,
  Icon,
  IconButton,
  IssueLink,
  ProblemError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Tabs,
  copyText,
  useCopied,
  type IconName,
} from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { fmtClock, middleTruncate } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { linearHref } from "../../lib/safeHref";
import { useCollectorState } from "../../shell/GlobalStream";
import {
  DiscussButton,
  useDiscuss,
  useDiscussTarget,
  type DiscussReference,
  type DiscussTarget,
} from "../../shell/discuss";
import { AcBar, FilterMenu, PHASES, VERDICT_STATUS } from "../features/parts";
import { NoteView } from "../brain/NoteView";
import { NotFoundBody } from "../not-found";
import { EvalTab, pickEval } from "./EvalTab";
import { StateBadge } from "./PlanningView";
import { TicketsTab } from "./TicketsTab";
import { useFeature, useFeatureTickets } from "./queries";

type Detail = components["schemas"]["FeatureDetail"];
type AcRow = components["schemas"]["AcRow"];
type TicketRow = components["schemas"]["TicketRow"];

type Pass = "yes" | "owner" | "none";
const PASS: Record<Pass, { icon: IconName; tone: string; label: string; title: string }> = {
  yes: { icon: "circle-check", tone: "done", label: "yes", title: "Passes by command" },
  owner: { icon: "hand", tone: "waiting", label: "owner", title: "Manual owner step" },
  none: { icon: "circle-dashed", tone: "idle", label: "--", title: "Not passing yet" },
};
const passOf = (ac: AcRow): Pass => (ac.passes ? "yes" : ac.manual ? "owner" : "none");

type RecordName = components["schemas"]["FeatureRecordName"];

/** The record tabs read from `brain/features/<slug>/<name>.md` (D3), in golden-path order. */
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
};

type FeaturePhase = components["schemas"]["FeaturePhase"];

/**
 * The tab where each phase's work is: a record while it is being written, the tickets while
 * they are built and reviewed, the criteria once it is evaluated or shipped. It is the tab a
 * feature opens on, and the one a golden path step opens.
 */
const PHASE_TAB: Record<FeaturePhase, string> = {
  spec: "spec",
  research: "research",
  plan: "plan",
  tickets: "tickets",
  implement: "tickets",
  review: "tickets",
  evaluate: "acs",
  shipped: "acs",
};

/** The step's tab when the golden path opens it: Evaluate shows its eval records. */
const STEP_TAB: Record<FeaturePhase, string> = { ...PHASE_TAB, evaluate: "eval" };

/** The tab of `?doc=`: a record, `eval`, `tickets` or Criteria (`acs`); else the phase's tab. */
function tabOf(doc: string | null, phase: FeaturePhase | undefined): string {
  if (doc === "issues") return "tickets"; // the old Issues tab's deep links (AC-136.28)
  if (doc === "acs" || doc === "eval" || doc === "tickets" || (doc !== null && RECORDS[doc])) {
    return doc;
  }
  return phase ? PHASE_TAB[phase] : "acs";
}

/** An AC description as a sentence, so the callout's next sentence reads on. */
function ownerLine(text: string | undefined): string {
  if (!text) return "";
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

/** Rows shown before "Show all": the first seven and the last two (spec 17). */
const HEAD_ROWS = 7;
const TAIL_ROWS = 2;

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

/** One criterion as a Discuss reference: its text, how it is verified and where it stands. */
export function acReference(ac: AcRow, slug: string): DiscussReference {
  const lines = [
    `${ac.id}${ac.repo ? ` (${ac.repo})` : ""}: ${ac.description}`,
    `Passes: ${ac.passes ? "yes" : ac.manual ? "manual owner step" : "not yet"}.`,
    ac.command ? `Verify: ${ac.command}` : "",
    ac.evidence ? `Evidence: ${ac.evidence}` : "",
  ];
  return {
    id: `ac:${ac.id}`,
    label: ac.id,
    source: `brain/features/${slug}/features.json`,
    quote: lines.filter(Boolean).join("\n"),
  };
}

/** Points the feature's Discuss conversation at one criterion. */
function DiscussAc({ ac, slug }: { ac: AcRow; slug: string }) {
  const { addReference, references } = useDiscuss();
  const pointed = references.some((r) => r.id === `ac:${ac.id}`);
  return (
    <IconButton
      size="sm"
      icon="message-square"
      label={pointed ? `${ac.id} is in the next message` : `Discuss ${ac.id} with Claude`}
      aria-pressed={pointed}
      onClick={() => {
        addReference(acReference(ac, slug));
      }}
    />
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
              <th scope="col" style={{ width: 40 }}>
                <span className="ah-sr">Discuss</span>
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
                        colSpan={8}
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
                    <td>
                      <DiscussAc ac={ac} slug={detail.slug} />
                    </td>
                  </tr>
                  {expanded && (
                    <tr style={{ cursor: "default" }}>
                      <td />
                      <td
                        colSpan={7}
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

/** A record tab (Spec, Research, Plan): the note itself, read through the brain route (D3). */
function RecordTab({ detail, tab }: { detail: Detail; tab: string }) {
  const meta = RECORDS[tab];
  if (!meta) return null;
  const file = `${meta.name}.md`;
  const record = detail.records.find((r) => r.name === meta.name);
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
      <NoteView
        key={record.path}
        project={detail.project}
        path={record.path}
        missing={`No ${file} yet.`}
      />
    </div>
  );
}

/**
 * The feature's tickets as header chips: each id links to Linear, with its title on hover and its
 * status in Linear once the tickets route answered (its cached answer); until then the ids alone.
 */
function TicketChips({ ids, rows }: { ids: readonly string[]; rows: readonly TicketRow[] }) {
  if (ids.length === 0) return null;
  return (
    <span
      className="ah-row ah-wrap"
      style={{ gap: 12 }}
      role="group"
      aria-label="Tickets of this feature"
    >
      {ids.map((id) => {
        const row = rows.find((r) => r.id === id || r.ref === id);
        return (
          <span key={id} className="ah-row" style={{ gap: 6 }}>
            <IssueLink id={id} title={row?.title} href={linearHref(row?.url)} />
            {row?.state && <StateBadge row={row} />}
          </span>
        );
      })}
    </span>
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

const TAB_LABEL: Readonly<Record<string, string>> = {
  spec: "spec",
  research: "research",
  plan: "plan",
  eval: "eval",
  acs: "acceptance criteria",
  tickets: "ticket plan",
};

/**
 * What the Discuss panel talks about on this screen: one conversation per feature, opened with the
 * panel on arrival. Claude reads every record of the feature before answering, and the brief adds
 * what the screen shows on top of the files: the phase, the criteria not passing, the tickets.
 */
function featureDiscussTarget(
  detail: Detail | undefined,
  tab: string,
  evalPath: string | undefined,
): DiscussTarget | null {
  if (!detail) return null;
  const folder = `brain/features/${detail.slug}`;
  const record = detail.records.find((r) => r.name === RECORDS[tab]?.name && r.present);
  const path = record
    ? `brain/${record.path}`
    : tab === "acs"
      ? `${folder}/features.json`
      : tab === "eval" && evalPath
        ? `brain/${evalPath}`
        : null;
  const files = [
    ...detail.records.filter((r) => r.present).map((r) => `brain/${r.path}`),
    `${folder}/features.json`,
    ...detail.evals.map((e) => `brain/${e.path}`),
  ];
  const open = detail.ac_rows.filter((ac) => !ac.passes);
  const describe = (ac: AcRow) => `${ac.id}${ac.manual ? " (owner step)" : ""}: ${ac.description}`;
  return {
    key: `feature:${detail.project}:${detail.slug}`,
    project: detail.project,
    kind: `Feature ${TAB_LABEL[tab] ?? tab}`,
    title: detail.slug,
    path,
    openOnArrive: true,
    brief: [
      `The whole feature record lives in \`${folder}/\`. Before answering, read all of it: ${[...new Set(files)].join(", ")}.`,
      detail.problem ? `The problem it solves: ${detail.problem}` : "",
      `Size: ${detail.size ?? "not set"}. Repos: ${detail.repos.join(", ") || "none"}. Current phase: ${detail.phase}.`,
      detail.acs
        ? `Acceptance criteria: ${String(detail.acs.passing)} of ${String(detail.acs.total)} passing.${open.length ? ` Not passing yet: ${open.map(describe).join("; ")}.` : ""}`
        : "",
      detail.issues.length ? `Its Linear tickets: ${detail.issues.join(", ")}.` : "",
      `I am looking at its ${TAB_LABEL[tab] ?? tab} tab.`,
      "When a change touches several records (spec, plan, criteria), keep them consistent with each other.",
    ]
      .filter(Boolean)
      .join(" "),
  };
}

/** Feature detail (spec 17, D23): golden path, owner steps, acceptance criteria. */
export function FeatureDetailScreen() {
  const { project = "", slug = "" } = useParams();
  const feature = useFeature(project, slug);
  const [params, setParams] = useSearchParams();
  const { state, asOf } = useCollectorState();
  const { tz } = usePreferences();
  const tab = tabOf(params.get("doc"), feature.data?.phase);
  const tickets = useFeatureTickets(project, slug, tab === "tickets" && feature.isSuccess);
  const selectedEval = pickEval(feature.data?.evals ?? [], params.get("eval"));
  useDiscussTarget(featureDiscussTarget(feature.data, tab, selectedEval?.path));

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
        if (id === PHASE_TAB[detail.phase]) next.delete("doc");
        else next.set("doc", id);
        return next;
      },
      { replace: true },
    );
  };
  const tabs = [
    ...Object.entries(RECORDS).map(([id, meta]) => ({ id, label: meta?.label ?? id })),
    { id: "eval", label: "Eval" },
    { id: "acs", label: "Criteria", count: detail.acs?.total },
    {
      id: "tickets",
      label: "Tickets",
      count: tickets.data?.tickets.length ?? detail.issues.length,
    },
  ];
  let body: ReactNode;
  if (tab === "tickets") {
    body = (
      <TicketsTab
        data={tickets.data}
        error={tickets.isError ? tickets.error : null}
        onRefresh={() => void tickets.refetch()}
        refreshing={tickets.isFetching}
        acPasses={Object.fromEntries(detail.ac_rows.map((ac) => [ac.id, ac.passes]))}
      />
    );
  } else if (tab === "eval") {
    body = (
      <EvalTab
        project={detail.project}
        slug={detail.slug}
        tickets={detail.issues}
        evals={detail.evals}
        selected={selectedEval}
        onSelect={(delivery) => {
          setParams(
            (current) => {
              const next = new URLSearchParams(current);
              next.set("eval", delivery);
              return next;
            },
            { replace: true },
          );
        }}
      />
    );
  } else if (RECORDS[tab]) body = <RecordTab detail={detail} tab={tab} />;
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
          <DiscussButton />
          {state === "offline" && <AsOfStamp stale time={fmtClock(asOf, tz)} />}
        </div>
        <div className="ah-row ah-wrap ah-small" style={{ gap: 14 }}>
          <TicketChips ids={detail.issues} rows={tickets.data?.tickets ?? []} />
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
          <DerivedLabel how="Each step is derived from the record files, the tickets' status in Linear when it was read, and the review and eval records; Shipped needs GitHub, not connected in this version.">
            Phase · derived from the record and the tickets
          </DerivedLabel>
        </div>
        <GoldenPathStepper
          steps={detail.golden_path.steps}
          onSelect={(step) => {
            setTab(STEP_TAB[step]);
          }}
          selectLabel={(step) => `Open the ${TAB_LABEL[STEP_TAB[step]] ?? step} of ${step}`}
        />
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
      <Tabs tabs={tabs} value={tab} onChange={setTab} label="Feature record" />
      <div style={{ paddingTop: 4 }}>{body}</div>
    </div>
  );
}
