import { Link, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import { EmptyState, Icon, SegmentedControl, StatusBadge } from "../../components";
import { brainRoute } from "../../lib/brainLinks";
import { NoteView } from "../brain/NoteView";
import { MockupView } from "./MockupView";
import "./designs.css";

type UxDesign = components["schemas"]["UxDesignView"];

/** A design's own name, unique in its feature: its file name without `.md` (`ux-new-orders`). */
export function designStem(design: UxDesign): string {
  return design.path.slice(design.path.lastIndexOf("/") + 1).replace(/\.md$/, "");
}

/**
 * The design `?design=` names: by its file (two designs may draw the same screen), else by its
 * screen (the older links), else the first one.
 */
export function pickDesign(designs: readonly UxDesign[], name: string | null): UxDesign | null {
  return (
    designs.find((d) => designStem(d) === name) ??
    designs.find((d) => d.screen === name) ??
    designs[0] ??
    null
  );
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
  slug,
  designs,
  selected,
  onSelect,
}: {
  project: string;
  slug: string;
  designs: readonly UxDesign[];
  selected: UxDesign | null;
  /** Gets the chosen design's `designStem`. */
  onSelect: (design: string) => void;
}) {
  const [params, setParams] = useSearchParams();
  const view = params.get("view");
  const setView = (id: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id === "spec") next.set("view", "spec");
        else next.delete("view");
        return next;
      },
      { replace: true },
    );
  };
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
  const mockup = selected.mockup ?? null;
  // A design with a mockup opens on it; `?view=spec` shows the written design instead.
  const showMockup = mockup !== null && view !== "spec";
  const folder = selected.path.slice(0, selected.path.lastIndexOf("/") + 1);
  return (
    <div className="ah-stack" style={{ gap: 10 }}>
      <p className="ah-small ah-muted" style={{ margin: 0 }}>
        {designs.length} screen{designs.length === 1 ? "" : "s"} · {approved} approved. Pin any
        point of a mockup, or select any text of a written design, to discuss it with Claude.
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
                onSelect(designStem(design));
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
            {mockup !== null && (
              <SegmentedControl
                label="Show the design"
                value={showMockup ? "mockup" : "spec"}
                onChange={(id) => {
                  setView(id);
                }}
                options={[
                  {
                    id: "mockup",
                    label: "Mockup",
                    icon: "layout-dashboard",
                    title: "The screen drawn as a page",
                  },
                  {
                    id: "spec",
                    label: "Written design",
                    icon: "file-text",
                    title: "The design as the agents wrote it: layout, states, components, copy",
                  },
                ]}
              />
            )}
            <Link className="ah-small" to={brainRoute(project, selected.path)}>
              Open in Brain
            </Link>
          </div>
          {showMockup ? (
            <MockupView
              key={mockup}
              project={project}
              slug={slug}
              name={mockup}
              source={`brain/${folder}${mockup}`}
              screen={selected.screen}
            />
          ) : (
            <NoteView
              key={selected.path}
              project={project}
              path={selected.path}
              missing={`No ${selected.path} yet.`}
              foldFrontmatter={{}}
            />
          )}
        </div>
      </div>
    </div>
  );
}
