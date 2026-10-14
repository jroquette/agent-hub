import { Navigate, Outlet } from "react-router";
import type { RouteObject } from "react-router";

import { useApi } from "./lib/api";
import { AgentSessionScreen } from "./screens/agent-session";
import { ApprovalsScreen } from "./screens/approvals";
import { BrainPickerScreen, BrainScreen } from "./screens/brain";
import { FeatureDetailScreen } from "./screens/feature-detail";
import { FeaturesScreen } from "./screens/features";
import { HealthScreen } from "./screens/health";
import { KnowledgePhase3Screen } from "./screens/knowledge-phase3";
import { LearningsScreen } from "./screens/learnings";
import { LiveSessionsScreen } from "./screens/live-sessions";
import { NotFoundScreen } from "./screens/not-found";
import { PortfolioScreen } from "./screens/portfolio";
import { ProjectOverviewScreen } from "./screens/project-overview";
import { RunDetailScreen } from "./screens/run-detail";
import { RunsListScreen } from "./screens/runs-list";
import { SessionDetailScreen } from "./screens/session-detail";
import { SessionsListScreen } from "./screens/sessions-list";
import { SettingsScreen } from "./screens/settings";
import { SkillDetailScreen, SkillsPickerScreen, SkillsScreen } from "./screens/skills";
import { WelcomeScreen } from "./screens/welcome";
import { AppShell } from "./shell/AppShell";

/**
 * With no registered hub every route but `/settings/*` (and `/welcome` itself) redirects to
 * `/welcome` (AC-200.54). While the hub list loads, or when it cannot be read, the page shows.
 */
export function HubGate() {
  const hubs = useApi("/api/v1/hubs");
  if (hubs.data?.items.length === 0) return <Navigate to="/welcome" replace />;
  return <Outlet />;
}

/**
 * The Phase 2 routes (D20, spec 01 sitemap). Screens live in `src/screens/<name>/index.tsx`
 * and export `<Name>Screen`; hidden destinations (Metrics, Bench, Tracker, Workflows) fall to 404.
 * A project's Brain is `projects/:project/brain/<note path>` (AGH-201 D3); its Skills are
 * `projects/:project/skills[/<kind>/<source>/<name>]` (AGH-164).
 */
export const appRoutes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      {
        element: <HubGate />,
        children: [
          { index: true, element: <PortfolioScreen /> },
          { path: "projects/:project", element: <ProjectOverviewScreen /> },
          { path: "projects/:project/brain/*", element: <BrainScreen /> },
          { path: "projects/:project/skills", element: <SkillsScreen /> },
          { path: "projects/:project/skills/:kind/:source/:name", element: <SkillDetailScreen /> },
          { path: "approvals", element: <ApprovalsScreen /> },
          { path: "approvals/:approvalId", element: <ApprovalsScreen /> },
          { path: "live", element: <LiveSessionsScreen /> },
          { path: "sessions", element: <SessionsListScreen /> },
          { path: "sessions/:sessionId", element: <SessionDetailScreen /> },
          { path: "agent-sessions/:agentSessionId", element: <AgentSessionScreen /> },
          { path: "runs", element: <RunsListScreen /> },
          { path: "runs/:runId", element: <RunDetailScreen /> },
          { path: "knowledge", element: <Navigate to="/knowledge/learnings" replace /> },
          { path: "knowledge/learnings", element: <LearningsScreen /> },
          { path: "knowledge/learnings/:learningId", element: <LearningsScreen /> },
          { path: "knowledge/brain", element: <BrainPickerScreen /> },
          // Before `knowledge/:section`, which would show the Phase 3 placeholder.
          { path: "knowledge/skills", element: <SkillsPickerScreen /> },
          { path: "knowledge/:section", element: <KnowledgePhase3Screen /> },
          { path: "features", element: <FeaturesScreen /> },
          { path: "features/:project/:slug", element: <FeatureDetailScreen /> },
          { path: "health", element: <HealthScreen /> },
          { path: "*", element: <NotFoundScreen /> },
        ],
      },
      { path: "settings", element: <Navigate to="/settings/hubs" replace /> },
      { path: "settings/:section", element: <SettingsScreen /> },
      { path: "welcome", element: <WelcomeScreen /> },
    ],
  },
];
