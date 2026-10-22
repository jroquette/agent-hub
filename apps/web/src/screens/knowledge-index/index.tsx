/* The All-projects state of Toolkit, Brain, Environments and Hub config: one card per project,
 * with the Portfolio card's head so a project looks the same wherever it is chosen, then what
 * the section counts and a foot line for what needs a look. A figure or foot that needs the
 * project's catalog or tree fetches it itself, so the cards show at once. */
import { useNavigate } from "react-router";
import { useRef, type ReactNode } from "react";

import {
  AppLink,
  Button,
  CardStat,
  EmptyState,
  Icon,
  ProblemError,
  ProjectCardHead,
  Skeleton,
  Tooltip,
  type IconName,
} from "../../components";
import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";
import { useRowKeys } from "../../lib/useRowKeys";
import { projectCard } from "../portfolio/model";
import "./knowledge-index.css";

export type ProjectSummary = components["schemas"]["ProjectSummary"];

/** One figure of a project card: a `CardStat` whose value is usually a `CountCell`. */
export interface ProjectFigure {
  id: string;
  label: string;
  hint?: string;
  render: (project: ProjectSummary) => ReactNode;
}

/** A count cell: a skeleton while its source loads, "—" with the reason when it failed. */
export function CountCell({
  pending,
  error,
  value,
  incomplete,
}: {
  pending: boolean;
  error: string | null;
  value: ReactNode;
  incomplete?: string | null | undefined;
}) {
  if (pending) return <Skeleton lines={1} />;
  if (error !== null) {
    return (
      <Tooltip label={error}>
        <span className="ah-muted">—</span>
      </Tooltip>
    );
  }
  if (incomplete) {
    return (
      <Tooltip label={incomplete}>
        <span className="ah-num">{value}+</span>
      </Tooltip>
    );
  }
  return <span className="ah-num">{value}</span>;
}

/**
 * The foot line of a picker card. `tone="attention"` is a link to what needs a look; `quiet` says
 * nothing does; `error` gives the reason and a Retry that refetches only this project's source.
 */
export function PickFoot(
  props:
    | { tone: "attention"; icon?: IconName; href: string; label: string; children: ReactNode }
    | { tone: "quiet"; icon?: IconName; children: ReactNode }
    | { tone: "error"; children: ReactNode; onRetry: () => void },
) {
  const stop = (event: { stopPropagation: () => void }) => {
    event.stopPropagation();
  };
  if (props.tone === "error") {
    return (
      <div className="ah-pcard-foot ah-pick-foot" data-tone="error">
        <Icon name="circle-alert" size="sm" />
        <span className="ah-grow">{props.children}</span>
        <Button
          size="sm"
          variant="ghost"
          onClick={(event) => {
            stop(event);
            props.onRetry();
          }}
        >
          Retry
        </Button>
      </div>
    );
  }
  if (props.tone === "quiet") {
    return (
      <div className="ah-pcard-foot ah-pick-foot">
        <Icon name={props.icon ?? "circle-check"} size="sm" />
        <span>{props.children}</span>
      </div>
    );
  }
  return (
    <div className="ah-pcard-foot ah-pick-foot" data-tone="attention">
      <AppLink
        href={props.href}
        className="ah-row"
        style={{ gap: 6 }}
        aria-label={props.label}
        onClick={stop}
      >
        <Icon name={props.icon ?? "circle-alert"} size="sm" />
        <span>{props.children}</span>
      </AppLink>
    </div>
  );
}

function ProjectPickCard({
  project,
  href,
  lead,
  figures,
  foot,
}: {
  project: ProjectSummary;
  href: string;
  lead?: ((project: ProjectSummary) => ReactNode) | undefined;
  figures: ProjectFigure[];
  foot?: ((project: ProjectSummary) => ReactNode) | undefined;
}) {
  const navigate = useNavigate();
  const nameId = `pick-${project.name}`;
  return (
    <li>
      {/* A click anywhere opens the project; the name link is the keyboard and reader path. */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions */}
      <article className="ah-pcard" aria-labelledby={nameId} onClick={() => void navigate(href)}>
        <ProjectCardHead
          p={projectCard(project)}
          nameHref={href}
          nameId={nameId}
          trailing={<Icon name="chevron-right" size="sm" className="ah-pick-chevron" />}
        />
        {lead && <div className="ah-small ah-muted ah-pick-lead">{lead(project)}</div>}
        {figures.length > 0 && (
          <div className="ah-pcard-grid ah-pick-stats">
            {figures.map((figure) => (
              <CardStat key={figure.id} label={figure.label} hint={figure.hint}>
                {figure.render(project)}
              </CardStat>
            ))}
          </div>
        )}
        {foot?.(project)}
      </article>
    </li>
  );
}

function SkeletonCards() {
  return (
    <ul className="ah-pick-grid" aria-busy="true" aria-label="Loading projects">
      {[0, 1, 2].map((i) => (
        <li key={i}>
          <div className="ah-pcard" style={{ cursor: "default" }}>
            <Skeleton width="50%" height={18} />
            <Skeleton width="70%" />
            <Skeleton height={44} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function KnowledgeProjectIndex({
  title,
  intro,
  caption,
  emptyLine,
  tip,
  href,
  lead,
  figures = [],
  foot,
}: {
  title: string;
  intro: string;
  caption: string;
  emptyLine: string;
  tip: string;
  href: (project: string) => string;
  lead?: (project: ProjectSummary) => ReactNode;
  figures?: ProjectFigure[];
  foot?: (project: ProjectSummary) => ReactNode;
}) {
  const projects = useApi("/api/v1/projects");
  const listRef = useRef<HTMLDivElement>(null);
  useRowKeys(listRef);
  let body;
  if (projects.isError) {
    body = (
      <ProblemError
        title="Could not load projects"
        detail={projects.error.detail ?? projects.error.title}
        status={projects.error.status}
        onRetry={() => void projects.refetch()}
      />
    );
  } else if (!projects.isPending && projects.data.items.length === 0) {
    body = (
      <div className="ah-card">
        <EmptyState
          icon="folder-kanban"
          title="No projects yet."
          action={<AppLink href="/settings/hubs">Register a hub in Settings</AppLink>}
        >
          {emptyLine}
        </EmptyState>
      </div>
    );
  } else {
    const items = projects.data?.items ?? [];
    body = (
      <div ref={listRef}>
        <div className="ah-section-title">
          <h2 className="ah-h3" style={{ fontSize: 14 }}>
            {items.length === 1 ? "Project" : "Projects"}
          </h2>
          <span className="ah-grow" />
          <span className="ah-row ah-small ah-subtle" style={{ gap: 6 }}>
            <Icon name="folder-kanban" size="sm" />
            {tip}
          </span>
        </div>
        {projects.isPending ? (
          <SkeletonCards />
        ) : (
          <ul className="ah-pick-grid" aria-label={caption}>
            {items.map((project) => (
              <ProjectPickCard
                key={project.name}
                project={project}
                href={href(project.name)}
                lead={lead}
                figures={figures}
                foot={foot}
              />
            ))}
          </ul>
        )}
      </div>
    );
  }
  return (
    <div className="ah-page" style={{ gap: 16 }}>
      <div className="ah-stack" style={{ gap: 4 }}>
        <h1 className="ah-h1">{title}</h1>
        <p className="ah-muted" style={{ margin: 0, maxWidth: "80ch" }}>
          {intro}
        </p>
      </div>
      {body}
    </div>
  );
}
