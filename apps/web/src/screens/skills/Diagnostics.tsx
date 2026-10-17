/* An item's diagnostics (D5, P6): informational findings by text and icon, never by color alone. */
import "./SkillDetail.css";

import { Icon } from "../../components";
import type { components } from "../../api/schema";

type Diagnostic = components["schemas"]["Diagnostic"];

const LOOK = {
  warning: { icon: "triangle-alert", label: "Warning" },
  info: { icon: "info", label: "Info" },
} as const;

/** The list of findings, warnings first; none of them stops Claude Code from loading the item.
 * Nothing at all when there is none: the header's health chip says so. */
export function Diagnostics({ diagnostics }: { diagnostics: readonly Diagnostic[] }) {
  if (diagnostics.length === 0) return null;
  const ordered = [...diagnostics].sort(
    (a, b) => Number(b.severity === "warning") - Number(a.severity === "warning"),
  );
  return (
    <section className="ah-card ah-skill-section" aria-labelledby="skill-diagnostics">
      <div className="ah-card-head">
        <h2 id="skill-diagnostics" className="ah-h3" tabIndex={-1}>
          Diagnostics <span className="ah-count">{diagnostics.length}</span>
        </h2>
      </div>
      <div className="ah-card-body">
        <p className="ah-small ah-muted" style={{ margin: "0 0 8px" }}>
          Advice from the Agent Skills rules and this hub; a finding never blocks the item.
        </p>
        <ul className="ah-skill-diags" aria-label="Diagnostics">
          {ordered.map((finding, i) => {
            const look = LOOK[finding.severity];
            return (
              <li key={`${finding.code}-${String(i)}`} data-sev={finding.severity}>
                <Icon name={look.icon} size="sm" />
                <span className="ah-caption">{look.label}</span>
                <span className="ah-skill-diag-msg">{finding.message}</span>
                <span className="ah-mono ah-small ah-muted">{finding.code}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
