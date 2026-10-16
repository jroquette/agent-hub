import { Fragment, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  Button,
  CodeBlock,
  DerivedLabel,
  EmptyState,
  Icon,
  IconButton,
  ProblemError,
  SegmentedControl,
  Skeleton,
  copyText,
  useCopied,
  type IconName,
} from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { safeHref } from "../../lib/safeHref";
import { useDiscuss, type DiscussReference } from "../../shell/discuss";
import { FilterMenu } from "../features/parts";
import { useProjectRepos } from "../project-overview/queries";
import { useAcCitations, type AcCitations, type Citation } from "./acCitations";
import {
  parseEvidence,
  resultLine,
  resultPassed,
  shortSha,
  type EvidenceFacts,
} from "./acEvidence";
import "./criteria.css";

type Detail = components["schemas"]["FeatureDetail"];
type AcRow = components["schemas"]["AcRow"];
type EvalRecord = components["schemas"]["EvalRecord"];

export type Pass = "yes" | "owner" | "none";
const PASS: Record<Pass, { icon: IconName; tone: string; label: string; title: string }> = {
  yes: { icon: "circle-check", tone: "done", label: "Passes", title: "Its check passes" },
  owner: { icon: "hand", tone: "waiting", label: "Owner step", title: "Waits on a manual check" },
  none: { icon: "circle-dashed", tone: "idle", label: "Not passing", title: "Not passing yet" },
};
export const passOf = (ac: AcRow): Pass => (ac.passes ? "yes" : ac.manual ? "owner" : "none");

/** Rows shown before "Show all": the first seven and the last two (spec 17). */
const HEAD_ROWS = 7;
const TAIL_ROWS = 2;

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

/** Sends one criterion to the feature's Discuss conversation; a labelled button, not an icon. */
function DiscussAc({ ac, slug, long }: { ac: AcRow; slug: string; long?: boolean }) {
  const { addReference, references } = useDiscuss();
  const pointed = references.some((r) => r.id === `ac:${ac.id}`);
  return (
    <Button
      size="sm"
      variant={long ? "default" : "ghost"}
      icon={pointed ? "check" : "message-square"}
      aria-label={pointed ? `${ac.id} is in the next message` : `Discuss ${ac.id} with Claude`}
      title={
        pointed
          ? `${ac.id} is attached to your next message in the Discuss panel`
          : `Attach ${ac.id} to a message for Claude in the Discuss panel`
      }
      aria-pressed={pointed}
      onClick={() => {
        addReference(acReference(ac, slug));
      }}
    >
      {pointed ? "In next message" : long ? `Discuss ${ac.id} with Claude` : "Discuss"}
    </Button>
  );
}

/** The repo's GitHub URL for a commit or a pull request, when the hub knows the repo. */
type GithubOf = (repo: string | null) => string | null;
function useGithubOf(project: string, fallbackRepo: string | null): GithubOf {
  const repos = useProjectRepos(project);
  return (repo) => {
    const name = (repo ?? fallbackRepo)?.toLowerCase();
    const found = repos.data?.items.find(
      (r) => r.name.toLowerCase() === name || r.dir.toLowerCase() === name,
    );
    return found?.github ? `https://github.com/${found.github}` : null;
  };
}

function ExternalA({ href, children }: { href: string | null; children: ReactNode }) {
  const safe = safeHref(href);
  if (!safe) return <>{children}</>;
  return (
    <a href={safe} target="_blank" rel="noreferrer" className="ah-row" style={{ gap: 2 }}>
      {children}
      <Icon name="arrow-up-right" size="sm" />
    </a>
  );
}

/** The eval record a path or delivery name points at, among the feature's evals. */
function evalFor(evals: readonly EvalRecord[], file: string): EvalRecord | undefined {
  const lower = file.toLowerCase();
  return evals.find(
    (e) => e.path.toLowerCase().endsWith(`/${lower}`) || e.delivery.toLowerCase() === lower,
  );
}

/** The latest eval that names this AC in its scope ("all" counts). */
function latestEvalOf(evals: readonly EvalRecord[], id: string): EvalRecord | undefined {
  return [...evals]
    .filter((e) => e.acs === "all" || e.acs.includes(id))
    .sort((a, b) => (b.evaluated_at ?? "").localeCompare(a.evaluated_at ?? ""))[0];
}

function EvalLink({ record }: { record: EvalRecord }) {
  return (
    <Link to={`?doc=eval&eval=${encodeURIComponent(record.delivery)}`}>
      eval {record.delivery}
      {record.verdict ? ` · ${record.verdict}` : ""}
    </Link>
  );
}

/* ---------- Row cells ---------- */

function StatusCell({ ac }: { ac: AcRow }) {
  const pass = PASS[passOf(ac)];
  return (
    <span className="ah-pass" style={{ color: `var(--${pass.tone})` }} title={pass.title}>
      <Icon name={pass.icon} size="sm" />
      {pass.label}
    </span>
  );
}

/** The row's evidence at a glance: the result, then where and when it ran. */
function EvidenceSummary({ ac, facts }: { ac: AcRow; facts: EvidenceFacts | null }) {
  if (!ac.evidence || !facts) {
    return <span className="ah-subtle ah-small">No evidence yet</span>;
  }
  const line = resultLine(facts.result);
  const green = resultPassed(facts.result);
  const commit = facts.commits[0];
  const where = [
    commit ? `${commit.repo ? `${commit.repo} ` : ""}@${shortSha(commit.sha)}` : null,
    facts.date,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span className="ah-ac-ev">
      {facts.standing ? (
        <span className="ah-ac-ev-main">
          <Icon name="info" size="sm" />
          {facts.standing === "superseded"
            ? "Superseded"
            : facts.standing === "dropped"
              ? "Dropped"
              : "Partly proven"}
        </span>
      ) : line ? (
        <span
          className="ah-ac-ev-main"
          style={{ color: green === false ? "var(--failed)" : undefined }}
        >
          <Icon name={green === false ? "circle-x" : "check-check"} size="sm" />
          {line}
        </span>
      ) : (
        <span className="ah-ac-ev-main">
          <Icon name="file-text" size="sm" />
          Recorded note
        </span>
      )}
      {where && <span className="ah-subtle ah-mono">{where}</span>}
    </span>
  );
}

function CitedCell({ citations, loading }: { citations: readonly Citation[]; loading: boolean }) {
  if (loading && citations.length === 0) return <Skeleton width={48} />;
  if (citations.length === 0) return <span className="ah-subtle ah-small">—</span>;
  const mentions = citations.reduce((sum, c) => sum + c.count, 0);
  return (
    <span className="ah-small" title={citations.map((c) => docLabel(c.path)).join(", ")}>
      <Icon name="link" size="sm" /> {citations.length} doc{citations.length === 1 ? "" : "s"}
      <span className="ah-subtle"> · {mentions}×</span>
    </span>
  );
}

/* ---------- Expanded card ---------- */

function Section({
  title,
  icon,
  aside,
  children,
}: {
  title: string;
  icon: IconName;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="ah-ac-sec" aria-label={title}>
      <h4 className="ah-ac-sec-h">
        <Icon name={icon} size="sm" />
        {title}
        {aside && <span className="ah-ac-sec-aside">{aside}</span>}
      </h4>
      <div className="ah-ac-sec-body">{children}</div>
    </section>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function HowProven({
  ac,
  facts,
  detail,
  githubOf,
}: {
  ac: AcRow;
  facts: EvidenceFacts | null;
  detail: Detail;
  githubOf: GithubOf;
}) {
  const latest = latestEvalOf(detail.evals, ac.id);
  if (!ac.evidence || !facts) {
    return (
      <div className="ah-small">
        <span className="ah-subtle">No evidence recorded yet.</span>{" "}
        {ac.manual
          ? "A manual owner step: it is proven by hand and recorded in the eval."
          : "It is written by /evaluate when the check is run."}
        {latest && (
          <>
            {" "}
            Latest eval in scope: <EvalLink record={latest} />.
          </>
        )}
      </div>
    );
  }
  const evals = [
    ...facts.evalFiles.map((f) => evalFor(detail.evals, f.replace(/^evals\//, ""))),
    ...facts.evalDeliveries.map((d) => evalFor(detail.evals, d)),
  ].filter((e, i, all): e is EvalRecord => e !== undefined && all.indexOf(e) === i);
  const line = resultLine(facts.result);
  const green = resultPassed(facts.result);
  return (
    <div className="ah-stack" style={{ gap: 10 }}>
      <dl className="ah-ac-facts">
        {line && (
          <Fact label="Result">
            <span style={{ color: green === false ? "var(--failed)" : "var(--done)" }}>
              <Icon name={green === false ? "circle-x" : "circle-check"} size="sm" /> {line}
            </span>
          </Fact>
        )}
        {facts.commits.length > 0 && (
          <Fact label="Code tested">
            <span className="ah-row ah-wrap" style={{ gap: 10 }}>
              {facts.commits.map((c) => {
                const gh = githubOf(c.repo);
                return (
                  <ExternalA key={`${c.repo ?? ""}@${c.sha}`} href={gh && `${gh}/commit/${c.sha}`}>
                    <span className="ah-mono">
                      {c.repo ?? ac.repo ?? "repo"} @ {shortSha(c.sha)}
                    </span>
                  </ExternalA>
                );
              })}
            </span>
          </Fact>
        )}
        {facts.prs.length > 0 && (
          <Fact label="Pull request">
            <span className="ah-row ah-wrap" style={{ gap: 10 }}>
              {facts.prs.map((p) => {
                const gh = githubOf(p.repo);
                return (
                  <ExternalA key={p.number} href={gh && `${gh}/pull/${p.number}`}>
                    {p.repo ? `${p.repo} ` : ""}#{p.number}
                  </ExternalA>
                );
              })}
            </span>
          </Fact>
        )}
        {facts.date && <Fact label="When">{facts.date}</Fact>}
        {facts.environments.length > 0 && (
          <Fact label="Ran in">
            <span className="ah-mono">
              {facts.environments.map((e) => `DataMode=${e}`).join(", ")}
            </span>
          </Fact>
        )}
        {facts.redOnBase && (
          <Fact label="Failed before">
            <span title="The same check failed on the code before this change, so it really tests the change">
              {facts.redOnBase}
            </span>
          </Fact>
        )}
        {(evals.length > 0 || latest) && (
          <Fact label="Eval record">
            <span className="ah-row ah-wrap" style={{ gap: 10 }}>
              {evals.map((e) => (
                <EvalLink key={e.path} record={e} />
              ))}
              {latest && !evals.includes(latest) && (
                <span>
                  <span className="ah-subtle">latest in scope: </span>
                  <EvalLink record={latest} />
                </span>
              )}
            </span>
          </Fact>
        )}
      </dl>
      {ac.passes && facts.ownerCheckOpen && (
        <div className="ah-ac-note">
          <Icon name="hand" size="sm" />
          The evidence says a manual check is still an owner step.
        </div>
      )}
      <details className="ah-ac-raw">
        <summary>Full evidence as recorded in features.json</summary>
        <p>{ac.evidence}</p>
      </details>
    </div>
  );
}

const DOC_LABELS: Readonly<Record<string, string>> = {
  "spec.md": "Spec",
  "research.md": "Research",
  "plan.md": "Plan",
  "issues.md": "Ticket plan",
  "eval.md": "Eval (legacy)",
};

/** "Spec", "Plan", "Eval · demo-1552", "Review · DEMO-1552". */
export function docLabel(path: string): string {
  const name = path.split("/").pop() ?? path;
  const stem = name.replace(/\.md$/, "");
  if (path.includes("/evals/")) return `Eval · ${stem}`;
  if (path.includes("/reviews/")) return `Review · ${stem}`;
  return DOC_LABELS[name] ?? name;
}

const RECORD_TAB: Readonly<Record<string, string>> = {
  "spec.md": "spec",
  "research.md": "research",
  "plan.md": "plan",
};

/** Where a citation opens: the record's tab at its section, the eval tab, or the brain note. */
function citationTarget(c: Citation, detail: Detail): string {
  const name = c.path.split("/").pop() ?? "";
  const hash = c.section ? `#${encodeURIComponent(c.section)}` : "";
  const tab = RECORD_TAB[name];
  if (tab) return `?doc=${tab}${hash}`;
  if (c.path.includes("/evals/")) {
    const record = detail.evals.find((e) => e.path === c.path);
    if (record) return `?doc=eval&eval=${encodeURIComponent(record.delivery)}`;
  }
  return brainRoute(detail.project, c.path, c.section);
}

function CitationList({
  citations,
  loading,
  detail,
}: {
  citations: readonly Citation[];
  loading: boolean;
  detail: Detail;
}) {
  if (loading && citations.length === 0) {
    return (
      <div className="ah-stack" style={{ gap: 6 }} aria-busy="true">
        <Skeleton width="60%" />
        <Skeleton width="45%" />
      </div>
    );
  }
  if (citations.length === 0) {
    return <span className="ah-subtle ah-small">Not cited in the feature's other documents.</span>;
  }
  return (
    <ul className="ah-ac-cites">
      {citations.map((c) => (
        <li key={c.path}>
          <Link to={citationTarget(c, detail)} className="ah-ac-cite-doc">
            <Icon name="file-text" size="sm" />
            {docLabel(c.path)}
          </Link>
          {c.section && <span className="ah-subtle"> › {c.section}</span>}
          {c.count > 1 && <span className="ah-subtle"> · {c.count} mentions</span>}
          <div className="ah-ac-cite-snip">{c.snippet}</div>
        </li>
      ))}
    </ul>
  );
}

/** A Given / When / Then description as three labelled lines; any other text as a paragraph. */
function WhatMustBeTrue({ text }: { text: string }) {
  const m = /^Given (.*?), when (.*?), then (.*)$/.exec(text);
  if (!m) return <p className="ah-ac-text">{text}</p>;
  return (
    <dl className="ah-ac-facts ah-ac-gwt">
      {(
        [
          ["Given", m[1]],
          ["When", m[2]],
          ["Then", m[3]],
        ] as const
      ).map(([k, v]) => (
        <Fragment key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

function AcCard({
  ac,
  detail,
  citations,
  githubOf,
}: {
  ac: AcRow;
  detail: Detail;
  citations: AcCitations;
  githubOf: GithubOf;
}) {
  const facts = ac.evidence ? parseEvidence(ac.evidence) : null;
  const [copied, markCopied] = useCopied();
  const list = citations.byAc.get(ac.id) ?? [];
  return (
    <div className="ah-ac-card">
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <span className="ah-mono" style={{ fontWeight: 600 }}>
          {ac.id}
        </span>
        <StatusCell ac={ac} />
        <span className="ah-grow" />
        <Button
          size="sm"
          variant="ghost"
          icon={copied ? "check" : "link"}
          onClick={() => {
            const url = new URL(window.location.href);
            url.searchParams.set("doc", "acs");
            url.searchParams.set("ac", ac.id);
            url.hash = "";
            copyText(url.toString());
            markCopied();
          }}
        >
          {copied ? "Copied" : "Copy link"}
        </Button>
        <DiscussAc ac={ac} slug={detail.slug} long />
      </div>
      <Section title="What must be true" icon="list-checks">
        <WhatMustBeTrue text={ac.description} />
        {ac.repo && (
          <div className="ah-small ah-subtle">
            In <span className="ah-mono">{ac.repo}</span>
          </div>
        )}
      </Section>
      <Section
        title="How it was proven"
        icon="flask-conical"
        aside={
          facts && (
            <DerivedLabel how="Read by agent-hub from the evidence text in features.json; the full text is below.">
              read from the evidence text
            </DerivedLabel>
          )
        }
      >
        <HowProven ac={ac} facts={facts} detail={detail} githubOf={githubOf} />
      </Section>
      <Section title="Check it yourself" icon="terminal">
        {ac.command && !ac.manual ? (
          <CodeBlock code={ac.command} prompt="$" wrap label={`Verification of ${ac.id}`} />
        ) : ac.command ? (
          <div className="ah-small">
            <span className="ah-muted">Manual owner step: </span>
            {ac.command} <Link to="?doc=eval">See the eval</Link>
          </div>
        ) : (
          <span className="ah-subtle ah-small">No verification recorded.</span>
        )}
      </Section>
      <Section
        title="Where it is cited"
        icon="link"
        aside={
          list.length > 0 && (
            <span className="ah-subtle">
              {list.length} of {citations.documents} documents
            </span>
          )
        }
      >
        <CitationList citations={list} loading={citations.loading} detail={detail} />
      </Section>
    </div>
  );
}

/* ---------- The tab ---------- */

export function CriteriaTab({ detail }: { detail: Detail }) {
  const [params, setParams] = useSearchParams();
  const asked = params.get("ac");
  const [filter, setFilter] = useState<"all" | Pass>("all");
  const [repo, setRepo] = useState<string | null>(null);
  const [all, setAll] = useState(asked !== null);
  const [open, setOpen] = useState<string | null>(
    asked ?? detail.ac_rows.find((ac) => passOf(ac) === "owner")?.id ?? null,
  );
  const [copied, markCopied] = useCopied();
  const rows = detail.ac_rows;
  const citations = useAcCitations(
    detail.project,
    detail.slug,
    rows.map((ac) => ac.id),
  );
  const githubOf = useGithubOf(detail.project, null);

  useEffect(() => {
    if (asked === null) return;
    const row = document.getElementById(`ac-row-${asked}`);
    // jsdom has no scrollIntoView.
    if (row && "scrollIntoView" in row) row.scrollIntoView({ block: "center" });
  }, [asked]);

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
  const COLS = 6;
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
            { id: "none", label: `Not passing ${String(count("none"))}` },
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
      <p className="ah-small ah-muted ah-ac-hint">
        <Icon name="message-square" size="sm" /> Each criterion has a <b>Discuss</b> button: it
        attaches that criterion to your next message for Claude in the panel on the right. Open a
        row to see how it was proven and where it is cited.
      </p>
      <div className="ah-table-wrap">
        <table className="ah-table ah-actable ah-actable-v2" aria-label="Acceptance criteria">
          <thead>
            <tr>
              <th scope="col" style={{ width: 36 }}>
                <span className="ah-sr">Details</span>
              </th>
              <th scope="col" style={{ width: 120 }}>
                Status
              </th>
              <th scope="col">Criterion</th>
              <th scope="col" style={{ width: 230 }}>
                Evidence
              </th>
              <th scope="col" style={{ width: 110 }}>
                Cited in
              </th>
              <th scope="col" style={{ width: 132 }}>
                <span className="ah-sr">Discuss</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((ac, i) => {
              const expanded = open === ac.id;
              const facts = ac.evidence ? parseEvidence(ac.evidence) : null;
              return (
                <Fragment key={ac.id}>
                  {folded && i === HEAD_ROWS && (
                    <tr style={{ cursor: "default" }}>
                      <td
                        colSpan={COLS}
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
                    id={`ac-row-${ac.id}`}
                    className="ah-ac-row"
                    data-owner={passOf(ac) === "owner" || undefined}
                    data-open={expanded || undefined}
                    data-asked={asked === ac.id || undefined}
                    onClick={(event) => {
                      if ((event.target as HTMLElement).closest("button, a")) return;
                      toggle(ac.id);
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
                    <td>
                      <StatusCell ac={ac} />
                    </td>
                    <td className="ah-ac-desc">
                      <div className="ah-ac-crit">
                        <span className="ah-ac-id ah-mono">{ac.id}</span>
                        {ac.repo && <span className="ah-fm-chip">{ac.repo}</span>}
                      </div>
                      <div className="ah-ac-clamp" data-open={expanded || undefined}>
                        {ac.description}
                      </div>
                    </td>
                    <td>
                      <EvidenceSummary ac={ac} facts={facts} />
                    </td>
                    <td>
                      <CitedCell
                        citations={citations.byAc.get(ac.id) ?? []}
                        loading={citations.loading}
                      />
                    </td>
                    <td>
                      <DiscussAc ac={ac} slug={detail.slug} />
                    </td>
                  </tr>
                  {expanded && (
                    <tr style={{ cursor: "default" }} className="ah-ac-detail-row">
                      <td />
                      <td colSpan={COLS - 1}>
                        <AcCard ac={ac} detail={detail} citations={citations} githubOf={githubOf} />
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
