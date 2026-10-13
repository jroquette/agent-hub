import type { ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import { EmptyState, StatusBadge } from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { VERDICT_STATUS } from "../features/parts";

type EvalRecord = components["schemas"]["EvalRecord"];

function Ids({ ids }: { ids: readonly string[] }) {
  if (ids.length === 0) return <span className="ah-subtle">—</span>;
  return <span className="ah-mono ah-small">{ids.join(", ")}</span>;
}

function Scope({ acs }: { acs: EvalRecord["acs"] }) {
  if (acs === "all") return <span>All ACs</span>;
  if (acs.length === 0) return <span className="ah-subtle">—</span>;
  return (
    <span title={acs.join(", ")}>
      {acs.length} AC{acs.length === 1 ? "" : "s"}
    </span>
  );
}

function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}

export interface EvalTabProps {
  project: string;
  /** `FeatureDetail.evals`: one per delivery, as the server orders them. */
  evals: readonly EvalRecord[];
}

/**
 * The Eval tab (AC-136.32): every delivery's eval, never only the last one, with its verdict,
 * scope (tickets, ACs, PRs, commit), date and a link to its note.
 */
export function EvalTab({ project, evals }: EvalTabProps) {
  if (evals.length === 0) {
    return (
      <div className="ah-card">
        <EmptyState icon="flask-conical" title="No evals yet.">
          The evaluator agent writes one note per delivery in{" "}
          <span className="ah-mono">evals/&lt;delivery&gt;.md</span>.
        </EmptyState>
      </div>
    );
  }
  const columns: { label: string; width?: number; cell: (e: EvalRecord) => ReactNode }[] = [
    {
      label: "Delivery",
      width: 150,
      cell: (e) => (
        <span className="ah-stack" style={{ gap: 2 }}>
          <b className="ah-mono" style={{ fontWeight: 500 }}>
            {e.delivery}
          </b>
          {e.legacy && <span className="ah-small ah-muted">legacy</span>}
        </span>
      ),
    },
    {
      label: "Verdict",
      width: 200,
      cell: (e) =>
        e.problem ? (
          <span className="ah-small" style={{ color: "var(--failed)" }}>
            Unreadable: {e.problem}
          </span>
        ) : e.verdict ? (
          <StatusBadge status={VERDICT_STATUS[e.verdict]} label={e.verdict} />
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
    { label: "Tickets", cell: (e) => <Ids ids={e.tickets} /> },
    { label: "ACs", width: 90, cell: (e) => <Scope acs={e.acs} /> },
    { label: "PRs", cell: (e) => <Ids ids={e.prs} /> },
    {
      label: "Commit",
      width: 90,
      cell: (e) =>
        e.commit ? (
          <span className="ah-mono ah-small">{e.commit}</span>
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
    {
      label: "Evaluated",
      width: 110,
      cell: (e) =>
        e.evaluated_at ? (
          <span className="ah-small">{e.evaluated_at}</span>
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
    {
      label: "Note",
      width: 140,
      cell: (e) => (
        <Link
          className="ah-mono ah-small"
          to={brainRoute(project, e.path)}
          aria-label={`${fileName(e.path)}, the eval of ${e.delivery}`}
          title={`brain/${e.path}`}
        >
          {fileName(e.path)}
        </Link>
      ),
    },
  ];
  return (
    <div className="ah-table-wrap">
      <table className="ah-table" aria-label="Evals">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.label} scope="col" style={c.width ? { width: c.width } : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {evals.map((e) => (
            <tr key={e.path} style={{ cursor: "default" }}>
              {columns.map((c) => (
                <td key={c.label} style={{ whiteSpace: "normal" }}>
                  {c.cell(e)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="ah-table-foot">
        <span>
          {evals.length} eval{evals.length === 1 ? "" : "s"} · the latest eval that names an AC
          decides it
        </span>
      </div>
    </div>
  );
}
