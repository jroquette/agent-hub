import { NavLink, useMatch } from "react-router";

import { Kbd, PhaseTag, type Phase } from "../components/core";
import { Icon, type IconName } from "../components/Icon";
import { useScope } from "../lib/scope";
import { SKILLS_PICKER } from "../screens/skills/routes";

/** Badge counts from the global stream's `counts` message. */
export interface SidebarCounts {
  live?: number | undefined;
  learnings?: number | undefined;
  /** Features that need you (a session waits on you, NO-SHIP, owner steps, a broken record). */
  features?: number | undefined;
  health?: number | undefined;
}

type CountKey = keyof SidebarCounts;

const OVERVIEW_ID = "portfolio";

/**
 * The top item: the Portfolio with All projects in scope, else the overview of the project open or
 * in scope, so a project's own page is one click away, as Brain and Toolkit are.
 */
export function overviewItem(
  open: string | null,
  scope: string | null,
): { label: string; to: string; icon: IconName } {
  const project = open ?? scope;
  return project === null
    ? { label: "Portfolio", to: "/", icon: "layout-dashboard" }
    : {
        label: `Overview · ${project}`,
        to: `/projects/${encodeURIComponent(project)}`,
        icon: "folder-kanban",
      };
}

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

/**
 * Skills' destination: the catalog of the project whose skills are open, else of the project in
 * scope, else the picker.
 */
export function skillsLink(open: string | null, scope: string | null): string {
  const project = open ?? scope;
  return project === null ? SKILLS_PICKER : `/projects/${encodeURIComponent(project)}/skills`;
}

const CONFIG_ID = "config";
/** Where Hub config goes with All projects in scope: a project picker. */
const CONFIG_PICKER = "/config";

/** Hub config's destination: the config of the project open, else in scope, else the picker. */
export function configLink(open: string | null, scope: string | null): string {
  const project = open ?? scope;
  return project === null ? CONFIG_PICKER : `/projects/${encodeURIComponent(project)}/config`;
}

const ENVIRONMENTS_ID = "environments";
/** Where Environments goes with All projects in scope: a project picker. */
const ENVIRONMENTS_PICKER = "/environments";

/** Environments' destination: the project open, else in scope, else the picker. */
export function environmentsLink(open: string | null, scope: string | null): string {
  const project = open ?? scope;
  return project === null
    ? ENVIRONMENTS_PICKER
    : `/projects/${encodeURIComponent(project)}/environments`;
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
  /** Shown only once there is something in it (Workflow runs, before the first run). */
  onlyWhenAny?: boolean;
}

interface NavGroup {
  /** The caption over the group; the top group has none. */
  group?: string;
  /** `foot` pins the group to the bottom of the sidebar, above Shortcuts. */
  placement?: "foot";
  items: NavItem[];
}

/**
 * The sitemap (D20, AGH-201 D3), grouped by what the developer comes to do: Portfolio on top (the
 * project overview once a project is open or in scope, see `overviewItem`); Work, everything about
 * the work in the codebase (Features carries the needs-you badge, then Tickets and Scenarios; the
 * Sessions and Workflow runs that carry it out, Sessions with the live badge, ADR 0033, Workflow
 * runs once a workflow has run; and the Environments it runs in, ADR 0038); Knowledge, what the
 * project knows (Brain, the Learnings that feed it, and the Toolkit of skills and workflows); and
 * the hub's own Health and Settings in the footer. Brain, Toolkit and Environments follow the
 * project in scope (see `brainLink`, `skillsLink`, `environmentsLink`). Metrics, Bench and Tracker
 * queue are not shipped and not shown.
 */
export const NAV: readonly NavGroup[] = [
  {
    items: [{ id: OVERVIEW_ID, label: "Portfolio", to: "/", icon: "layout-dashboard" }],
  },
  {
    group: "Work",
    items: [
      {
        id: "features",
        label: "Features",
        to: "/features",
        icon: "list-checks",
        countKey: "features",
        countNoun: () => "need you",
        tone: "waiting",
      },
      // Single-ticket work (/fix, /refactor, /upgrade, …), grouped from the sessions by issue.
      { id: "tickets", label: "Tickets", to: "/tickets", icon: "list-todo" },
      // Always shown: a place to start work, not a log (AGH-350 AM-17, E-15); no `g` key.
      { id: "scenarios", label: "Scenarios", to: "/scenarios", icon: "clipboard-list" },
      // One Sessions entry; it carries the live badge of the retired Live sessions (ADR 0033 D8).
      {
        id: "sessions",
        label: "Sessions",
        to: "/sessions",
        icon: "list",
        countKey: "live",
        countNoun: () => "live",
        tone: "live",
      },
      // Hidden until a workflow has run; the workflows themselves are a tab of Toolkit.
      { id: "runs", label: "Workflow runs", to: "/runs", icon: "route", onlyWhenAny: true },
      // Where the project's systems run and what agents may do there (ADR 0038).
      { id: ENVIRONMENTS_ID, label: "Environments", to: ENVIRONMENTS_PICKER, icon: "server" },
    ],
  },
  {
    group: "Knowledge",
    items: [
      { id: BRAIN_ID, label: "Brain", to: BRAIN_PICKER, icon: "book-open" },
      {
        id: "learnings",
        label: "Learnings",
        to: "/knowledge/learnings",
        icon: "lightbulb",
        countKey: "learnings",
        countNoun: () => "to triage",
        tone: "waiting",
      },
      { id: SKILLS_ID, label: "Toolkit", to: SKILLS_PICKER, icon: "package" },
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
      { id: CONFIG_ID, label: "Hub config", to: CONFIG_PICKER, icon: "sliders-horizontal" },
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
  /** Whether any workflow run exists, to show Workflow runs (default: shown). */
  showRuns?: boolean;
  onShortcuts: () => void;
}

export function Sidebar({ counts, showRuns = true, onShortcuts }: SidebarProps) {
  const [scope] = useScope();
  const openBrain = useMatch("/projects/:project/brain/*");
  const brainTo = brainLink(openBrain?.params.project ?? null, scope);
  const openSkills = useMatch("/projects/:project/skills/*");
  const skillsTo = skillsLink(openSkills?.params.project ?? null, scope);
  const openConfig = useMatch("/projects/:project/*");
  const configTo = configLink(openConfig?.params.project ?? null, scope);
  const environmentsTo = environmentsLink(openConfig?.params.project ?? null, scope);
  const overview = overviewItem(openConfig?.params.project ?? null, scope);
  const resolve = (item: NavItem): NavItem =>
    item.id === OVERVIEW_ID ? { ...item, ...overview } : item;
  const itemTo = (item: NavItem): string =>
    item.id === BRAIN_ID
      ? brainTo
      : item.id === SKILLS_ID
        ? skillsTo
        : item.id === CONFIG_ID
          ? configTo
          : item.id === ENVIRONMENTS_ID
            ? environmentsTo
            : item.to;

  const renderItem = (navItem: NavItem) => {
    const item = resolve(navItem);
    if (item.onlyWhenAny && !showRuns) return null;
    const count = item.countKey ? counts[item.countKey] : undefined;
    return (
      <NavLink
        key={item.id}
        to={itemTo(item)}
        end={item.id === OVERVIEW_ID}
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
