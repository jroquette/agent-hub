import { NavLink, useMatch } from "react-router";

import { Kbd, PhaseTag, type Phase } from "../components/core";
import { Icon, type IconName } from "../components/Icon";
import { useScope } from "../lib/scope";

/** Badge counts from the global stream's `counts` message. */
export interface SidebarCounts {
  live?: number | undefined;
  learnings?: number | undefined;
  health?: number | undefined;
}

type CountKey = keyof SidebarCounts;

const BRAIN_ID = "brain";
/** Where Brain goes with All projects in scope: a project picker. */
const BRAIN_PICKER = "/knowledge/brain";

/**
 * Brain's destination: the Brain of the project whose brain is open, else of the project in scope,
 * else the picker.
 */
export function brainLink(open: string | null, scope: string | null): string {
  const project = open ?? scope;
  return project === null ? BRAIN_PICKER : `/projects/${encodeURIComponent(project)}/brain`;
}

const SKILLS_ID = "skills";
/** Where Skills goes with All projects in scope: a project picker (AGH-164). */
const SKILLS_PICKER = "/knowledge/skills";

/**
 * Skills' destination: the catalog of the project whose skills are open, else of the project in
 * scope, else the picker.
 */
export function skillsLink(open: string | null, scope: string | null): string {
  const project = open ?? scope;
  return project === null ? SKILLS_PICKER : `/projects/${encodeURIComponent(project)}/skills`;
}

interface NavItem {
  id: string;
  label: string;
  to: string;
  icon: IconName;
  countKey?: CountKey;
  /** How the count reads in the accessible name, e.g. "waiting". */
  countNoun?: (n: number) => string;
  tone?: "waiting" | "live" | "failed";
  phase?: Phase;
}

interface NavGroup {
  /** The caption over the group; the top group has none. */
  group?: string;
  /** `foot` pins the group to the bottom of the sidebar, above Shortcuts. */
  placement?: "foot";
  items: NavItem[];
}

/**
 * The sitemap (D20, AGH-201 D3), regrouped by what the developer comes to do: Portfolio on top, the
 * agents' Work (Sessions carries the live badge, ADR 0033; runs sit next to the workflows that start
 * them), the project's Knowledge as flat items (Brain and Skills follow the project in scope, see
 * `brainLink` and `skillsLink`), and the hub's own Health and Settings in the footer. Metrics,
 * Bench and Tracker queue are not shipped and not shown.
 */
export const NAV: readonly NavGroup[] = [
  {
    items: [{ id: "portfolio", label: "Portfolio", to: "/", icon: "layout-dashboard" }],
  },
  {
    group: "Work",
    items: [
      {
        id: "sessions",
        label: "Sessions",
        to: "/sessions",
        icon: "square-terminal",
        countKey: "live",
        countNoun: () => "live",
        tone: "live",
      },
      { id: "runs", label: "Workflow runs", to: "/runs", icon: "route" },
      { id: "workflows", label: "Workflows", to: "/workflows", icon: "workflow" },
      { id: "features", label: "Features", to: "/features", icon: "list-checks" },
    ],
  },
  {
    group: "Knowledge",
    items: [
      {
        id: "learnings",
        label: "Learnings",
        to: "/knowledge/learnings",
        icon: "lightbulb",
        countKey: "learnings",
        countNoun: () => "to triage",
        tone: "waiting",
      },
      { id: BRAIN_ID, label: "Brain", to: BRAIN_PICKER, icon: "book-open" },
      { id: SKILLS_ID, label: "Skills", to: SKILLS_PICKER, icon: "package" },
    ],
  },
  {
    group: "Hub",
    placement: "foot",
    items: [
      {
        id: "health",
        label: "Health",
        to: "/health",
        icon: "stethoscope",
        countKey: "health",
        countNoun: (n) => (n === 1 ? "doctor error" : "doctor errors"),
        tone: "failed",
      },
      { id: "settings", label: "Settings", to: "/settings", icon: "settings" },
    ],
  },
];

function badge(n: number): string {
  return n > 99 ? "99+" : String(n);
}

function accessibleName(item: NavItem, count: number | undefined): string | undefined {
  if (!count || !item.countNoun) return undefined;
  return `${item.label}, ${String(count)} ${item.countNoun(count)}`;
}

export interface SidebarProps {
  counts: SidebarCounts;
  onShortcuts: () => void;
}

export function Sidebar({ counts, onShortcuts }: SidebarProps) {
  const [scope] = useScope();
  const openBrain = useMatch("/projects/:project/brain/*");
  const brainTo = brainLink(openBrain?.params.project ?? null, scope);
  const openSkills = useMatch("/projects/:project/skills/*");
  const skillsTo = skillsLink(openSkills?.params.project ?? null, scope);
  const itemTo = (item: NavItem): string =>
    item.id === BRAIN_ID ? brainTo : item.id === SKILLS_ID ? skillsTo : item.to;

  const renderItem = (item: NavItem) => {
    const count = item.countKey ? counts[item.countKey] : undefined;
    return (
      <NavLink
        key={item.id}
        to={itemTo(item)}
        end={item.to === "/"}
        className="ah-nav-item"
        title={item.label}
        aria-label={accessibleName(item, count)}
      >
        <Icon name={item.icon} />
        <span className="ah-nav-label">{item.label}</span>
        {item.phase && <PhaseTag phase={item.phase} />}
        {count ? (
          <span className="ah-nav-count" data-tone={item.tone}>
            {item.tone === "live" && (
              <span className="ah-dot ah-pulse" style={{ width: 6, height: 6 }} />
            )}
            {badge(count)}
          </span>
        ) : null}
      </NavLink>
    );
  };

  return (
    <nav className="ah-sidebar" aria-label="Main">
      <div className="ah-brand">
        <span className="ah-brand-mark" aria-hidden="true">
          ah
        </span>
        <span className="ah-brand-name">agent-hub</span>
      </div>
      <div className="ah-nav">
        {NAV.filter((group) => group.placement !== "foot").map((group, index) => (
          <div key={group.group ?? index} className="ah-nav-group">
            {group.group && <div className="ah-nav-group-title">{group.group}</div>}
            {group.items.map(renderItem)}
          </div>
        ))}
      </div>
      <div className="ah-sidebar-foot">
        {NAV.filter((group) => group.placement === "foot").flatMap((group) =>
          group.items.map(renderItem),
        )}
        <button type="button" className="ah-nav-item ah-nav-button" onClick={onShortcuts}>
          <Icon name="keyboard" />
          <span className="ah-nav-label">Shortcuts</span>
          <span className="ah-nav-count" style={{ background: "none" }}>
            <Kbd>?</Kbd>
          </span>
        </button>
      </div>
    </nav>
  );
}
