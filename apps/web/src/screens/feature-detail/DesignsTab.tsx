import { Link } from "react-router";

import type { components } from "../../api/schema";
import { EmptyState, Icon, StatusBadge } from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { NoteView } from "../brain/NoteView";
import "./designs.css";

type UxDesign = components["schemas"]["UxDesignView"];

/** The design `?design=` names (its screen), else the first one. */
export function pickDesign(designs: readonly UxDesign[], screen: string | null): UxDesign | null {
  return designs.find((d) => d.screen === screen) ?? designs[0] ?? null;
}

/** "Brand services (list)" stays whole; a long title is cut at its first colon or parenthesis. */
function shortTitle(design: UxDesign): string {
  return design.title.length > 48
    ? (design.title.split(/[:(]/)[0]?.trim() ?? design.title)
    : design.title;
}

/**
 * The feature's UX designs (`ux-<new|change>-<screen>.md`), one screen at a time: the list of
 * screens on the left, the chosen design on the right as the agents wrote it. Reviewing is the
 * Discuss panel's job: select any part of a design and it is quoted into the feature's
 * conversation, with the session that wrote it.
 */
export function DesignsTab({
  project,
  designs,
  selected,
  onSelect,
}: {
  project: string;
  designs: readonly UxDesign[];
  selected: UxDesign | null;
  onSelect: (screen: string) => void;
}) {
  if (designs.length === 0 || !selected) {
    return (
      <div className="ah-card">
        <EmptyState icon="layout-dashboard" title="No UX designs yet.">
          The ux-designer agent writes one{" "}
          <span className="ah-mono">ux-&lt;new|change&gt;-&lt;screen&gt;.md</span> per screen the
          feature creates or changes, after the spec is approved.
        </EmptyState>
      </div>
    );
  }
  const approved = designs.filter((d) => d.approved).length;
  return (
    <div className="ah-stack" style={{ gap: 10 }}>
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        {designs.length} screen{designs.length === 1 ? "" : "s"} · {approved} approved. Select any
        part of a design to discuss it with Claude.
      </p>
      <div className="ah-designs">
        <nav className="ah-designs-nav" aria-label="Designed screens">
          {designs.map((design) => (
            <button
              key={design.path}
              type="button"
              className="ah-designs-item"
              aria-current={design.path === selected.path ? "true" : undefined}
              title={`brain/${design.path}`}
              onClick={() => {
                onSelect(design.screen);
              }}
            >
              <span className="ah-designs-item-title">{shortTitle(design)}</span>
              <span className="ah-row" style={{ gap: 6 }}>
                <span className="ah-fm-chip">{design.change === "change" ? "change" : "new"}</span>
                <span className="ah-mono ah-small ah-muted">{design.screen}</span>
                {design.approved && (
                  <Icon name="check" size="sm" title="Approved" style={{ marginLeft: "auto" }} />
                )}
              </span>
            </button>
          ))}
        </nav>
        <div className="ah-card ah-pad ah-stack ah-designs-body" style={{ gap: 12 }}>
          <div className="ah-row ah-wrap" style={{ gap: 8 }}>
            <Icon name="layout-dashboard" size="sm" />
            <span className="ah-mono ah-small">brain/{selected.path}</span>
            <StatusBadge
              status={selected.approved ? "done" : "waiting"}
              label={selected.approved ? "Approved" : "Draft"}
              quiet
            />
            <span className="ah-grow" />
            <Link className="ah-small" to={brainRoute(project, selected.path)}>
              Open in Brain
            </Link>
          </div>
          <NoteView
            key={selected.path}
            project={project}
            path={selected.path}
            missing={`No ${selected.path} yet.`}
            foldFrontmatter={{}}
          />
        </div>
      </div>
    </div>
  );
}
