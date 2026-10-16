import { Fragment } from "react";
import { NavLink, useMatch } from "react-router";

import { Kbd, PhaseTag, type Phase } from "../components/core";
import { Icon, type IconName } from "../components/Icon";
import { useScope } from "../lib/scope";

/** Badge counts from the global stream's `counts` message. */
export interface SidebarCounts {
  approvals?: number | undefined;
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
  icon?: IconName;
  countKey?: CountKey;
  /** How the count reads in the accessible name, e.g. "waiting". */
  countNoun?: (n: number) => string;
  tone?: "waiting" | "live" | "failed";
  phase?: Phase;
  children?: NavItem[];
}

/**
 * The sitemap (D20, AGH-201 D3): Metrics, Bench and Tracker queue are not shipped and not shown;
 * Workflows sits in Improve (AGH-226); Knowledge holds Learnings, the selected project's Brain
 * (`BRAIN_ID`, see `brainLink`) and its Skills (`SKILLS_ID`, see `skillsLink`).
 */
export const NAV: readonly { group: string; items: NavItem[] }[] = [
  {
    group: "Overview",
    items: [
      { id: "portfolio", label: "Portfolio", to: "/", icon: "layout-dashboard" },
      {
        id: "approvals",
        label: "Approvals",
        to: "/approvals",
        icon: "stamp",
        countKey: "approvals",
        countNoun: () => "waiting",
        tone: "waiting",
      },
    ],
  },
  {
    group: "Observe",
    items: [
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
      { id: "runs", label: "Workflow runs", to: "/runs", icon: "route" },
    ],
  },
  {
    group: "Understand",
    items: [
      {
        id: "knowledge",
        label: "Knowledge",
        to: "/knowledge/learnings",
        icon: "library",
        children: [
          {
            id: "learnings",
            label: "Learnings",
            to: "/knowledge/learnings",
            countKey: "learnings",
            countNoun: () => "to triage",
          },
          { id: BRAIN_ID, label: "Brain", to: BRAIN_PICKER },
          { id: SKILLS_ID, label: "Skills", to: SKILLS_PICKER },
        ],
      },
      { id: "features", label: "Features", to: "/features", icon: "list-checks" },
    ],
  },
  {
    group: "Improve",
    items: [{ id: "workflows", label: "Workflows", to: "/workflows", icon: "workflow" }],
  },
  {
    group: "Hub",
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
  const childTo = (child: NavItem): string =>
    child.id === BRAIN_ID ? brainTo : child.id === SKILLS_ID ? skillsTo : child.to;
  return (
    <nav className="ah-sidebar" aria-label="Main">
      <div className="ah-brand">
        <span className="ah-brand-mark" aria-hidden="true">
          ah
        </span>
        <span className="ah-brand-name">agent-hub</span>
      </div>
      <div className="ah-nav">
        {NAV.map((group) => (
          <div key={group.group}>
            <div className="ah-nav-group-title">{group.group}</div>
            {group.items.map((item) => {
              const count = item.countKey ? counts[item.countKey] : undefined;
              return (
                <Fragment key={item.id}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/" || Boolean(item.children)}
                    className="ah-nav-item"
                    title={item.label}
                    aria-label={accessibleName(item, count)}
                    aria-current={
                      // Knowledge is a group: its sub-item, not the group, is the page.
                      item.children ? false : undefined
                    }
                  >
                    {item.icon && <Icon name={item.icon} />}
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
                  {item.children?.map((child) => {
                    const childCount = child.countKey ? counts[child.countKey] : undefined;
                    return (
                      <NavLink
                        key={child.id}
                        to={childTo(child)}
                        className="ah-nav-item ah-nav-sub"
                        aria-label={accessibleName(child, childCount)}
                      >
                        <span className="ah-nav-label">{child.label}</span>
                        {childCount ? (
                          <span className="ah-nav-count">{badge(childCount)}</span>
                        ) : null}
                      </NavLink>
                    );
                  })}
                </Fragment>
              );
            })}
          </div>
        ))}
      </div>
      <div className="ah-sidebar-foot">
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
