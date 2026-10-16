import { useState } from "react";
import { useNavigate } from "react-router";

import {
  Button,
  IconButton,
  Kbd,
  MenuItem,
  Popover,
  SegmentedControl,
  Tooltip,
} from "../components/core";
import { CollectorPill } from "../components/CollectorPill";
import { Icon, type IconName } from "../components/Icon";
import { useApi } from "../lib/api";
import { useDiscuss } from "./discuss";
import { usePreferences, type ThemeChoice } from "../lib/preferences";
import type { StreamHealth } from "../lib/sse";

const THEME_ICON: Record<ThemeChoice, IconName> = { light: "sun", dark: "moon", system: "monitor" };

export interface ProjectSwitcherProps {
  scope: string | null;
  onScope: (project: string | null) => void;
}

/** The project scope: "All projects" or one project; it filters every list (spec 01). */
export function ProjectSwitcher({ scope, onScope }: ProjectSwitcherProps) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const projects = useApi("/api/v1/projects");
  const items = projects.data?.items ?? [];
  const pick = (project: string | null) => {
    setOpen(false);
    onScope(project);
  };
  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        className="ah-scope"
        onClick={() => {
          setOpen(!open);
        }}
        aria-expanded={open}
      >
        <Icon name="folder-kanban" size="sm" />
        {scope ?? "All projects"}
        <Icon name="chevron-down" size="sm" style={{ color: "var(--text-subtle)" }} />
      </button>
      <Popover open={open} style={{ top: 34, left: 0 }} label="Project scope">
        <MenuItem
          icon="layers"
          selected={scope === null}
          hint={<span className="ah-subtle ah-small">{items.length}</span>}
          onClick={() => {
            pick(null);
          }}
        >
          All projects
        </MenuItem>
        <div className="ah-menu-sep" />
        {items.map((project) => (
          <MenuItem
            key={project.name}
            icon="folder-kanban"
            selected={scope === project.name}
            onClick={() => {
              pick(project.name);
            }}
          >
            {project.name} · {project.live_sessions} live
          </MenuItem>
        ))}
        <div className="ah-menu-sep" />
        <MenuItem
          icon="plus"
          onClick={() => {
            setOpen(false);
            void navigate("/settings/hubs");
          }}
        >
          Manage hubs
        </MenuItem>
      </Popover>
    </div>
  );
}

/** Opens or closes the Discuss with Claude panel; it names what the screen offers to discuss. */
function DiscussToggle() {
  const { open, setOpen, target } = useDiscuss();
  const label = open
    ? "Close Discuss with Claude"
    : target
      ? `Discuss this ${target.kind.toLowerCase()} with Claude`
      : "Discuss with Claude";
  return (
    <Tooltip label={label}>
      <Button
        size="sm"
        variant={open ? "primary" : "default"}
        icon="message-square"
        aria-pressed={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        Discuss
      </Button>
    </Tooltip>
  );
}

export interface TopBarProps {
  scope: string | null;
  onScope: (project: string | null) => void;
  health: StreamHealth;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onPalette: () => void;
}

export function TopBar({
  scope,
  onScope,
  health,
  sidebarCollapsed,
  onToggleSidebar,
  onPalette,
}: TopBarProps) {
  const { theme, cycleTheme, tz, setTz } = usePreferences();
  return (
    <header className="ah-topbar">
      <IconButton
        icon="panel-left"
        label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        onClick={onToggleSidebar}
      />
      <ProjectSwitcher scope={scope} onScope={onScope} />
      <button type="button" className="ah-palette-trigger" onClick={onPalette}>
        <Icon name="search" size="sm" />
        Jump to session, run, issue, file…
        <Kbd>Ctrl K</Kbd>
      </button>
      <span className="ah-grow" />
      <DiscussToggle />
      <CollectorPill health={health} />
      <SegmentedControl
        label="Time zone"
        value={tz}
        onChange={(id) => {
          setTz(id === "utc" ? "utc" : "local");
        }}
        options={[
          { id: "local", label: "Local" },
          { id: "utc", label: "UTC" },
        ]}
      />
      <IconButton icon={THEME_ICON[theme]} label={`Theme: ${theme}`} onClick={cycleTheme} />
      <Tooltip label="Local single-user app on this machine">
        <span className="ah-identity" role="img" aria-label="You">
          <Icon name="user" size="sm" />
        </span>
      </Tooltip>
    </header>
  );
}
