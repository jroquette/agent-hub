/* The Skills tab (D2-D4, AC-164.13): a project's catalog, an item's detail, and the All-projects
 * picker. Items are addressed by `kind/source/name` (L5); files only by the ids the server issued. */
import "./Skills.css";
import "./SkillDetail.css";

import { useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router";

import { AppLink, Button, EmptyState, Icon, ProblemError, Skeleton } from "../../components";
import type { MarkdownProps } from "../../components";
import type { components } from "../../api/schema";
import { useNow } from "../../lib/clock";
import { useScope } from "../../lib/scope";
import { bundledFileAnchor, resolveSkillLink } from "../../lib/skillLinks";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { CountCell, KnowledgeProjectIndex } from "../knowledge-index";
import { NotFoundBody } from "../not-found";
import { AboutRail } from "./AboutRail";
import { BodyView, scrollToAnchor, type BodyMode } from "./BodyView";
import { BundledFiles } from "./BundledFiles";
import { Catalog } from "./Catalog";
import { DetailHeader } from "./DetailHeader";
import { Diagnostics } from "./Diagnostics";
import { KINDS, type ItemKind } from "./filters";
import { FrontmatterTable } from "./FrontmatterTable";
import { HookDetail } from "./HookDetail";
import { useSkillCatalog, useSkillDetail, type SkillRef } from "./queries";
import { StructurePanel } from "./StructurePanel";
import { editDraftRoute } from "./Studio";
import { CreateMenu } from "./CreateMenu";

type SkillDetail = components["schemas"]["SkillDetail"];

/** The usage window the server counts over (P2, `USAGE_DAYS`); the detail does not carry it. */
export const USAGE_DAYS = 30;

/** The in-app route of a project's Skills catalog. */
export function skillsHome(project: string): string {
  return `/projects/${encodeURIComponent(project)}/skills`;
}

function isKind(value: string): value is ItemKind {
  return KINDS.some((kind) => kind === value);
}

/** A project's catalog of skills, agents and hooks (D3); search and facets live in the URL. */
export function SkillsScreen() {
  const { project = "" } = useParams();
  const catalog = useSkillCatalog(project);
  let body;
  if (catalog.isError) {
    body =
      catalog.error.status === 404 ? (
        <div className="ah-card">
          <EmptyState icon="book-open" title="Project not found.">
            {catalog.error.detail ?? `No project ${project}.`}
          </EmptyState>
        </div>
      ) : (
        <ProblemError
          title={catalog.error.title}
          detail={catalog.error.detail}
          status={catalog.error.status}
          onRetry={() => void catalog.refetch()}
        />
      );
  } else if (catalog.isPending) {
    body = (
      <div aria-busy="true" aria-label="Loading the catalog" role="status">
        <Skeleton lines={6} />
      </div>
    );
  } else {
    body = <Catalog catalog={catalog.data} />;
  }
  return (
    <div className="ah-page" style={{ gap: 16 }}>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: project, href: `/projects/${encodeURIComponent(project)}` },
          { label: "Toolkit" },
        ]}
      />
      <header className="ah-skills-head">
        <div className="ah-stack ah-grow" style={{ gap: 4 }}>
          <h1 className="ah-h1">Toolkit</h1>
          <p className="ah-muted" style={{ margin: 0 }}>
            The agents, skills and hooks {project}&apos;s agents work with, read from its hub&apos;s
            files. Nothing here runs them.
          </p>
        </div>
        <CreateMenu project={project} />
      </header>
      {body}
    </div>
  );
}

function DetailBody({
  project,
  item,
  detail,
}: {
  project: string;
  item: SkillRef;
  detail: SkillDetail;
}) {
  const now = useNow(60_000);
  const navigate = useNavigate();
  const [view, setView] = useState<BodyMode>("rendered");
  const [openId, setOpenId] = useState<string | null>(null);
  const isSkill = detail.kind === "skill";
  useDiscussTarget({
    key: `${detail.kind}:${project}:${item.source}/${item.name}`,
    project,
    kind: detail.kind === "skill" ? "Skill" : detail.kind === "agent" ? "Agent" : "Hook",
    title: `${item.source}/${item.name}`,
    path: detail.source_path,
    brief:
      detail.origin === "managed"
        ? "It is managed by hub.lock: a local edit is overwritten by the next sync, so say so before changing it and propose where the change should live instead."
        : undefined,
  });
  const localLink: MarkdownProps["localLink"] = isSkill
    ? (href) => {
        const file = resolveSkillLink(href, detail.files);
        if (file === null) return null;
        return {
          href: `#${bundledFileAnchor(file.id)}`,
          open: () => {
            setOpenId(file.id);
          },
        };
      }
    : undefined;
  const onStep = (anchor: string) => {
    setView("rendered");
    // The rendered body mounts on the next frame when the view was Raw.
    requestAnimationFrame(() => {
      scrollToAnchor(anchor);
    });
  };
  return (
    <div className="ah-stack" style={{ gap: 16 }}>
      <DetailHeader
        detail={detail}
        now={now}
        usageDays={USAGE_DAYS}
        action={
          <>
            <DiscussButton />
            <Button
              size="sm"
              variant="primary"
              icon="file-pen"
              onClick={() => void navigate(editDraftRoute(project, item))}
            >
              Edit with Claude
            </Button>
          </>
        }
      />
      <div className="ah-skill-layout">
        <div className="ah-skill-main">
          <Diagnostics diagnostics={detail.diagnostics} />
          {detail.hook ? (
            <HookDetail hook={detail.hook} />
          ) : (
            <>
              <StructurePanel structure={detail.structure ?? null} onStep={onStep} />
              <BodyView
                body={detail.body ?? null}
                raw={detail.raw ?? null}
                toc={detail.toc}
                localLink={localLink}
                view={view}
                onViewChange={setView}
              />
            </>
          )}
          {isSkill && detail.files.length > 0 && (
            <BundledFiles
              project={project}
              item={item}
              files={detail.files}
              openId={openId}
              onOpenChange={setOpenId}
            />
          )}
          {detail.frontmatter.length > 0 && (
            <details className="ah-card ah-skill-section ah-skill-fold">
              <summary className="ah-card-head">
                <Icon name="chevron-right" size="sm" />
                <span className="ah-h3">Frontmatter</span>
                <span className="ah-small ah-muted">
                  {detail.frontmatter.length} {detail.frontmatter.length === 1 ? "key" : "keys"}
                </span>
              </summary>
              <div className="ah-card-body">
                <FrontmatterTable pairs={detail.frontmatter} />
              </div>
            </details>
          )}
        </div>
        <AboutRail project={project} detail={detail} />
      </div>
    </div>
  );
}

/** The detail's loading shape: the header, then the main column beside the About rail. */
function DetailSkeleton({ name }: { name: string }) {
  return (
    <div
      aria-busy="true"
      aria-label={`Loading ${name}`}
      role="status"
      className="ah-stack"
      style={{ gap: 16 }}
    >
      <div className="ah-card ah-skill-header">
        <Skeleton lines={4} />
      </div>
      <div className="ah-skill-layout">
        <div className="ah-skill-main">
          <div className="ah-card ah-card-body">
            <Skeleton lines={5} />
          </div>
          <div className="ah-card ah-card-body">
            <Skeleton lines={8} />
          </div>
        </div>
        <div className="ah-skill-rail">
          <Skeleton lines={8} />
        </div>
      </div>
    </div>
  );
}

function DetailLoaded({ project, item }: { project: string; item: SkillRef }) {
  const detail = useSkillDetail(project, item);
  const label = `${item.kind} ${item.source}/${item.name}`;
  if (detail.isError) {
    if (detail.error.status === 404) {
      return <NotFoundBody line={`No ${label} in ${project}.`} query={item.name} />;
    }
    return (
      <ProblemError
        title={detail.error.title}
        detail={detail.error.detail}
        status={detail.error.status}
        onRetry={() => void detail.refetch()}
      />
    );
  }
  if (detail.isPending) {
    return <DetailSkeleton name={item.name} />;
  }
  return <DetailBody project={project} item={item} detail={detail.data} />;
}

/** One item's detail (D4): header, text with TOC, structure, relations, files or hook facts. */
export function SkillDetailScreen() {
  const { project = "", kind = "", source = "", name = "" } = useParams();
  if (!isKind(kind)) {
    return <NotFoundBody line={`No ${kind} ${source}/${name} in ${project}.`} query={name} />;
  }
  const item: SkillRef = { kind, source, name };
  return (
    <div className="ah-page" style={{ gap: 16 }}>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: project, href: `/projects/${encodeURIComponent(project)}` },
          { label: "Toolkit", href: skillsHome(project) },
          { label: name, mono: true },
        ]}
      />
      <DetailLoaded key={`${kind}/${source}/${name}`} project={project} item={item} />
    </div>
  );
}

/** One project's catalog, counted for the All-projects index; React Query shares the request. */
function useCatalogCounts(project: string) {
  const catalog = useSkillCatalog(project);
  const items = catalog.data?.items ?? [];
  const count = (kind: ItemKind) => items.filter((item) => item.kind === kind).length;
  return {
    pending: catalog.isPending,
    error: catalog.isError ? `Could not read this catalog: ${catalog.error.title}` : null,
    incomplete: catalog.data?.truncated
      ? "The catalog is incomplete: the hub is over its bounds."
      : null,
    skills: count("skill"),
    agents: count("agent"),
    hooks: count("hook"),
    used: items.filter((item) => item.kind !== "hook" && (item.usage?.count ?? 0) > 0).length,
    withProblems: items.filter((item) => item.diagnostics_count > 0).length,
  };
}

function KindCount({ project, kind }: { project: string; kind: ItemKind }) {
  const counts = useCatalogCounts(project);
  const value = kind === "skill" ? counts.skills : kind === "agent" ? counts.agents : counts.hooks;
  return <CountCell {...counts} value={value} />;
}

function UsedCount({ project }: { project: string }) {
  const counts = useCatalogCounts(project);
  return <CountCell {...counts} value={counts.used} />;
}

function ProblemsCell({ project }: { project: string }) {
  const counts = useCatalogCounts(project);
  if (counts.pending || counts.error !== null || counts.withProblems === 0) {
    return (
      <CountCell {...counts} incomplete={null} value={<span className="ah-muted">None</span>} />
    );
  }
  const n = counts.withProblems;
  return (
    <AppLink
      href={`${skillsHome(project)}?diag=1`}
      className="ah-row"
      style={{ gap: 4 }}
      aria-label={`${String(n)} ${n === 1 ? "item" : "items"} with problems in ${project}`}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <Icon name="circle-alert" size="sm" />
      <span>{n} with problems</span>
    </AppLink>
  );
}

/**
 * Knowledge › Skills: with a project in scope it opens that project's catalog; with All projects
 * it lists the projects with what each one holds, to choose one (as Brain's index does).
 */
export function SkillsPickerScreen() {
  const [scope] = useScope();
  if (scope !== null) return <Navigate to={skillsHome(scope)} replace />;
  return (
    <KnowledgeProjectIndex
      title="Toolkit"
      intro="What each project's agents can do: the skills, agents and hooks its hub installs. Open a project to browse them."
      caption="Projects and their skills, agents and hooks"
      emptyLine="Register a hub to see its skills."
      tip="Tip: pick a project in the scope switcher to open its skills directly."
      href={skillsHome}
      columns={[
        {
          id: "hub_repo",
          label: "Hub repo",
          render: (project) => (
            <span className="ah-mono ah-small ah-muted">{project.hub_repo}</span>
          ),
        },
        {
          id: "agents",
          label: "Agents",
          align: "right",
          width: 90,
          render: (project) => <KindCount project={project.name} kind="agent" />,
        },
        {
          id: "skills",
          label: "Skills",
          align: "right",
          width: 90,
          render: (project) => <KindCount project={project.name} kind="skill" />,
        },
        {
          id: "hooks",
          label: "Hooks",
          align: "right",
          width: 90,
          render: (project) => <KindCount project={project.name} kind="hook" />,
        },
        {
          id: "used",
          label: `Used in ${String(USAGE_DAYS)} days`,
          hint: "Skills and agents used at least once in this window. Hooks are not counted.",
          align: "right",
          width: 150,
          render: (project) => <UsedCount project={project.name} />,
        },
        {
          id: "diagnostics",
          label: "Diagnostics",
          width: 180,
          render: (project) => <ProblemsCell project={project.name} />,
        },
      ]}
    />
  );
}
