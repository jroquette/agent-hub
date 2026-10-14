/* The Skills tab (D2-D4, AC-164.13): a project's catalog, an item's detail, and the All-projects
 * picker. Items are addressed by `kind/source/name` (L5); files only by the ids the server issued. */
import "./Skills.css";
import "./SkillDetail.css";

import { useState } from "react";
import { Link, Navigate, useParams } from "react-router";

import { EmptyState, Icon, ProblemError, Skeleton } from "../../components";
import type { MarkdownProps } from "../../components";
import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";
import { useNow } from "../../lib/clock";
import { useScope } from "../../lib/scope";
import { bundledFileAnchor, resolveSkillLink } from "../../lib/skillLinks";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { NotFoundBody } from "../not-found";
import { BodyView, scrollToAnchor, type BodyMode } from "./BodyView";
import { BundledFiles } from "./BundledFiles";
import { Catalog } from "./Catalog";
import { ContextCost } from "./ContextCost";
import { DetailHeader } from "./DetailHeader";
import { Diagnostics } from "./Diagnostics";
import { KINDS, type ItemKind } from "./filters";
import { FrontmatterTable } from "./FrontmatterTable";
import { HookDetail } from "./HookDetail";
import { useSkillCatalog, useSkillDetail, type SkillRef } from "./queries";
import { Relations } from "./Relations";
import { StructurePanel } from "./StructurePanel";

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
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 className="ah-h1">Skills</h1>
        <span className="ah-small ah-muted">{project}</span>
      </div>
      <p className="ah-muted" style={{ margin: 0 }}>
        The skills, agents and hooks of this hub, read from its files. Nothing here runs them.
      </p>
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
  const [view, setView] = useState<BodyMode>("rendered");
  const [openId, setOpenId] = useState<string | null>(null);
  const isSkill = detail.kind === "skill";
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
      <DetailHeader detail={detail} now={now} usageDays={USAGE_DAYS} />
      <Diagnostics diagnostics={detail.diagnostics} />
      {detail.hook ? (
        <HookDetail hook={detail.hook} sourcePath={detail.source_path} />
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
      {detail.frontmatter.length > 0 && <FrontmatterTable pairs={detail.frontmatter} />}
      {detail.kind !== "hook" && (
        <ContextCost cost={detail.context_cost ?? null} kind={detail.kind} />
      )}
      {detail.kind !== "hook" && (
        <Relations project={project} uses={detail.uses} usedBy={detail.used_by} />
      )}
      {isSkill && (
        <BundledFiles
          project={project}
          item={item}
          files={detail.files}
          openId={openId}
          onOpenChange={setOpenId}
        />
      )}
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
    return (
      <div aria-busy="true" aria-label={`Loading ${item.name}`} role="status">
        <Skeleton lines={8} />
      </div>
    );
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
          { label: "Skills", href: skillsHome(project) },
          { label: name, mono: true },
        ]}
      />
      <DetailLoaded key={`${kind}/${source}/${name}`} project={project} item={item} />
    </div>
  );
}

/**
 * Knowledge › Skills: with a project in scope it opens that project's catalog; with All projects
 * it lists the projects to choose one, as Brain's picker does.
 */
export function SkillsPickerScreen() {
  const [scope] = useScope();
  const projects = useApi("/api/v1/projects", undefined, { enabled: scope === null });
  if (scope !== null) return <Navigate to={skillsHome(scope)} replace />;
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
  } else if (projects.isPending) {
    body = <Skeleton lines={3} />;
  } else if (projects.data.items.length === 0) {
    body = (
      <div className="ah-card">
        <EmptyState icon="book-open" title="No projects yet.">
          Register a hub in Settings to see its skills.
        </EmptyState>
      </div>
    );
  } else {
    body = (
      <ul
        aria-label="Projects"
        className="ah-card ah-pad ah-stack"
        style={{ listStyle: "none", margin: 0, gap: 4 }}
      >
        {projects.data.items.map((project) => (
          <li key={project.name}>
            <Link to={skillsHome(project.name)} className="ah-skills-pick">
              <Icon name="book-open" size="sm" />
              <span>{project.name}</span>
            </Link>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="ah-page" style={{ gap: 16 }}>
      <h1 className="ah-h1">Skills</h1>
      <p className="ah-muted" style={{ margin: 0 }}>
        Pick a project to see its skills, agents and hooks, or choose one in the project scope.
      </p>
      {body}
    </div>
  );
}
