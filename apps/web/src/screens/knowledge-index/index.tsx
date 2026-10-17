/* The All-projects state of Knowledge › Skills and Knowledge › Brain: one row per project with
 * counts that say what is inside before it is opened. Each screen gives its own columns; a cell
 * that needs the project's catalog or tree fetches it itself, so the names work at once. */
import { useNavigate } from "react-router";
import type { ReactNode } from "react";

import {
  AppLink,
  DataTable,
  EmptyState,
  Icon,
  ProblemError,
  Skeleton,
  Tooltip,
  type DataTableColumn,
} from "../../components";
import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";

export type ProjectSummary = components["schemas"]["ProjectSummary"];

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

export function KnowledgeProjectIndex({
  title,
  intro,
  caption,
  emptyLine,
  tip,
  href,
  columns,
}: {
  title: string;
  intro: string;
  caption: string;
  emptyLine: string;
  tip: string;
  href: (project: string) => string;
  columns: DataTableColumn<ProjectSummary>[];
}) {
  const navigate = useNavigate();
  const projects = useApi("/api/v1/projects");
  let body;
  if (projects.isError) {
    body = (
      <ProblemError
        title={projects.error.title}
        detail={projects.error.detail}
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
    body = (
      <>
        <DataTable<ProjectSummary>
          caption={caption}
          loading={projects.isPending}
          rows={projects.data?.items ?? []}
          rowKey={(project) => project.name}
          onRowClick={(project) => void navigate(href(project.name))}
          columns={[
            {
              id: "name",
              label: "Project",
              render: (project) => (
                <AppLink
                  href={href(project.name)}
                  className="ah-row"
                  style={{ gap: 8, fontWeight: 500 }}
                >
                  <Icon name="folder-kanban" size="sm" />
                  <span>{project.name}</span>
                </AppLink>
              ),
            },
            ...columns,
          ]}
        />
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          {tip}
        </p>
      </>
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
