/* A skill's or agent's frontmatter as read (D4, AC-164.17): pairs in file order, unknown keys flagged. */
import "./SkillDetail.css";

import { Icon } from "../../components";
import type { components } from "../../api/schema";

type FrontmatterPair = components["schemas"]["FrontmatterPair"];
export type FrontmatterValue = FrontmatterPair["value"];

/** A value as one line: a list joined by commas, a map as `key: value; …`. */
export function frontmatterText(value: FrontmatterValue): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.join(", ");
  return Object.entries(value)
    .map(([key, item]) => `${key}: ${item}`)
    .join("; ");
}

function ValueCell({ value }: { value: FrontmatterValue }) {
  if (typeof value === "string") return <span className="ah-skill-fm-text">{value}</span>;
  if (Array.isArray(value)) {
    return (
      <ul className="ah-skill-fm-list">
        {value.map((item, i) => (
          <li key={i} className="ah-fm-chip">
            {item}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <dl className="ah-skill-fm-map">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt className="ah-mono">{key}:</dt> <dd>{item}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The frontmatter table; an unknown key reads "not understood by Claude Code" (advice, no error). */
export function FrontmatterTable({ pairs }: { pairs: readonly FrontmatterPair[] }) {
  if (pairs.length === 0) {
    return (
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        No frontmatter was read from this file; see Diagnostics when it could not be parsed.
      </p>
    );
  }
  return (
    <div className="ah-table-wrap">
      <table className="ah-table ah-skill-fm">
        <caption className="ah-sr">Frontmatter</caption>
        <thead>
          <tr>
            <th scope="col">Key</th>
            <th scope="col">Value</th>
            <th scope="col">
              <span className="ah-sr">Note</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {pairs.map((pair, i) => (
            <tr key={`${pair.key}-${String(i)}`}>
              <td className="ah-mono">{pair.key}</td>
              <td>
                <ValueCell value={pair.value} />
              </td>
              <td>
                {!pair.known && (
                  <span className="ah-skill-note">
                    <Icon name="info" size="sm" />
                    not understood by Claude Code
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
