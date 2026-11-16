import { useCallback } from "react";
import { useMatch, useNavigate } from "react-router";

import { useScope } from "../lib/scope";

const SECTIONS = {
  brain: {
    picker: "/knowledge/brain",
    home: (p: string) => `/projects/${encodeURIComponent(p)}/brain`,
  },
  skills: {
    picker: "/knowledge/skills",
    home: (p: string) => `/projects/${encodeURIComponent(p)}/skills`,
  },
} as const;

/**
 * The scope the switcher shows and sets. On a project's Brain or Skills page the project in the
 * route is the scope, so the switcher never contradicts the page; choosing another project opens
 * the same section of that project, and "All projects" opens the section's project index (spec 01:
 * changing scope on a project route navigates to that project's page of the same kind).
 */
export function usePageScope(): [string | null, (project: string | null) => void] {
  const [scope, setScope] = useScope();
  const navigate = useNavigate();
  const brain = useMatch("/projects/:project/brain/*");
  const skills = useMatch("/projects/:project/skills/*");
  const open = brain
    ? { kind: "brain" as const, match: brain }
    : skills
      ? { kind: "skills" as const, match: skills }
      : null;
  const routeProject = open?.match.params.project ?? null;
  const kind = open?.kind ?? null;
  const onScope = useCallback(
    (project: string | null) => {
      setScope(project);
      if (kind === null) return;
      const section = SECTIONS[kind];
      void navigate(project === null ? section.picker : section.home(project));
    },
    [kind, navigate, setScope],
  );
  return [routeProject ?? scope, onScope];
}
