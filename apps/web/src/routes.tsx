import { Navigate, Outlet, useLocation } from "react-router";
import type { RouteObject } from "react-router";

import { useApi } from "./lib/api";
import { liveRedirectTarget } from "./screens/sessions-list/liveRedirect";
import { AppShell } from "./shell/AppShell";
import { RouteError } from "./shell/RouteError";
import { lazyScreen, RouteSkeleton } from "./shell/routeLoading";

/**
 * With no registered hub every route but `/settings/*` (and `/welcome` itself) redirects to
 * `/welcome` (AC-200.54). While the hub list loads, or when it cannot be read, the page shows.
 */
export function HubGate() {
  const hubs = useApi("/api/v1/hubs");
  if (hubs.data?.items.length === 0) return <Navigate to="/welcome" replace />;
  return <Outlet />;
}

/** A `/live` bookmark opens the Sessions grid; a replace, so Back skips it (AC-234.2). */
function LiveRedirect() {
  const { search } = useLocation();
  return <Navigate to={liveRedirectTarget(search)} replace />;
}

/**
 * The Phase 2 routes (D20, spec 01 sitemap). Screens live in `src/screens/<name>/index.tsx`
 * and export `<Name>Screen`; hidden destinations (Metrics, Bench, Tracker) fall to 404.
 * A project's Brain is `projects/:project/brain/<note path>` (AGH-201 D3); its Skills are
 * `projects/:project/skills[/<kind>/<source>/<name>]` (AGH-164).
 *
 * Each screen's module loads on demand, in its own chunk (AGH-614); only the shell and the
 * redirects defined here are in the entry. Under the shell, a route whose code does not load, or
 * whose screen throws, shows `RouteError`, and a first load shows the page skeleton until its
 * screen's code arrives.
 */
export const appRoutes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      {
        errorElement: <RouteError />,
        hydrateFallbackElement: <RouteSkeleton />,
        children: [
          {
            element: <HubGate />,
            children: [
              {
                index: true,
                ...lazyScreen(() => import("./screens/portfolio"), "PortfolioScreen"),
              },
              {
                path: "projects/:project",
                ...lazyScreen(() => import("./screens/project-overview"), "ProjectOverviewScreen"),
              },
              {
                path: "projects/:project/brain/*",
                ...lazyScreen(() => import("./screens/brain"), "BrainScreen"),
              },
              {
                path: "projects/:project/config",
                ...lazyScreen(() => import("./screens/hub-config"), "HubConfigScreen"),
              },
              {
                path: "projects/:project/environments/new",
                ...lazyScreen(
                  () => import("./screens/hub-config/AddEnvironmentFlow"),
                  "AddEnvironmentScreen",
                ),
              },
              {
                path: "projects/:project/environments/services/new",
                ...lazyScreen(
                  () => import("./screens/hub-config/AddServiceFlow"),
                  "AddServiceScreen",
                ),
              },
              {
                path: "config",
                ...lazyScreen(() => import("./screens/hub-config"), "HubConfigPickerScreen"),
              },
              {
                path: "projects/:project/environments",
                ...lazyScreen(() => import("./screens/environments"), "EnvironmentsScreen"),
              },
              {
                path: "projects/:project/environment/:name",
                ...lazyScreen(
                  () => import("./screens/environments/EnvironmentPage"),
                  "EnvironmentScreen",
                ),
              },
              {
                path: "projects/:project/environments/discover",
                ...lazyScreen(
                  () => import("./screens/environments/DiscoverPage"),
                  "DiscoverScreen",
                ),
              },
              {
                path: "projects/:project/environments/discover/:discoveryId",
                ...lazyScreen(() => import("./screens/environments/ReviewPage"), "ReviewScreen"),
              },
              {
                path: "environments",
                ...lazyScreen(() => import("./screens/environments"), "EnvironmentsPickerScreen"),
              },
              {
                path: "projects/:project/skills",
                ...lazyScreen(() => import("./screens/skills"), "SkillsScreen"),
              },
              {
                path: "projects/:project/skills/new/:kind",
                ...lazyScreen(() => import("./screens/skills/Studio"), "NewDraftScreen"),
              },
              {
                path: "projects/:project/skills/drafts/:draftId",
                ...lazyScreen(() => import("./screens/skills/Studio"), "StudioScreen"),
              },
              // Workflows are a tab of the Toolkit; static segments rank before `:kind/:source/:name`.
              {
                path: "projects/:project/skills/workflows/new",
                ...lazyScreen(() => import("./screens/workflows/NewWorkflow"), "NewWorkflowScreen"),
              },
              {
                path: "projects/:project/skills/workflows/:name",
                ...lazyScreen(() => import("./screens/workflows"), "WorkflowDetailScreen"),
              },
              {
                path: "projects/:project/skills/:kind/:source/:name",
                ...lazyScreen(() => import("./screens/skills"), "SkillDetailScreen"),
              },
              {
                path: "projects/:project/skills/:kind/:source/:name/edit",
                ...lazyScreen(() => import("./screens/skills/Studio"), "EditDraftScreen"),
              },
              { path: "live", element: <LiveRedirect /> },
              {
                path: "sessions",
                ...lazyScreen(() => import("./screens/sessions-list"), "SessionsListScreen"),
              },
              {
                path: "sessions/:sessionId",
                ...lazyScreen(() => import("./screens/session-detail"), "SessionDetailScreen"),
              },
              {
                path: "agent-sessions/:agentSessionId",
                ...lazyScreen(() => import("./screens/agent-session"), "AgentSessionScreen"),
              },
              {
                path: "runs",
                ...lazyScreen(() => import("./screens/runs-list"), "RunsListScreen"),
              },
              {
                path: "runs/:runId",
                ...lazyScreen(() => import("./screens/run-detail"), "RunDetailScreen"),
              },
              // Scenarios carry their project (AM-17): names are unique per project only.
              {
                path: "scenarios",
                ...lazyScreen(() => import("./screens/scenarios"), "ScenariosScreen"),
              },
              {
                path: "scenarios/new",
                ...lazyScreen(() => import("./screens/scenarios"), "NewScenarioScreen"),
              },
              {
                path: "scenarios/:project/:name",
                ...lazyScreen(() => import("./screens/scenarios"), "ScenarioDetailScreen"),
              },
              {
                path: "scenarios/:project/:name/runs/:runId",
                ...lazyScreen(() => import("./screens/scenarios"), "ScenarioRunScreen"),
              },
              { path: "knowledge", element: <Navigate to="/knowledge/learnings" replace /> },
              {
                path: "knowledge/learnings",
                ...lazyScreen(() => import("./screens/learnings"), "LearningsScreen"),
              },
              {
                path: "knowledge/learnings/:learningId",
                ...lazyScreen(() => import("./screens/learnings"), "LearningsScreen"),
              },
              {
                path: "knowledge/brain",
                ...lazyScreen(() => import("./screens/brain"), "BrainPickerScreen"),
              },
              // Before `knowledge/:section`, which would show the Phase 3 placeholder.
              {
                path: "knowledge/skills",
                ...lazyScreen(() => import("./screens/skills"), "SkillsPickerScreen"),
              },
              {
                path: "knowledge/:section",
                ...lazyScreen(() => import("./screens/knowledge-phase3"), "KnowledgePhase3Screen"),
              },
              {
                path: "features",
                ...lazyScreen(() => import("./screens/features"), "FeaturesScreen"),
              },
              {
                path: "features/new",
                ...lazyScreen(() => import("./screens/features/NewFeature"), "NewFeatureScreen"),
              },
              {
                path: "features/:project/:slug",
                ...lazyScreen(() => import("./screens/feature-detail"), "FeatureDetailScreen"),
              },
              {
                path: "tickets",
                ...lazyScreen(() => import("./screens/tickets"), "TicketsScreen"),
              },
              {
                path: "tickets/:project/:issue",
                ...lazyScreen(() => import("./screens/ticket-detail"), "TicketDetailScreen"),
              },
              // Older links: Workflows moved into the Toolkit.
              {
                path: "workflows",
                ...lazyScreen(() => import("./screens/workflows"), "WorkflowsScreen"),
              },
              {
                path: "workflows/new",
                ...lazyScreen(() => import("./screens/workflows/NewWorkflow"), "NewWorkflowScreen"),
              },
              {
                path: "workflows/:project/:name",
                ...lazyScreen(() => import("./screens/workflows"), "LegacyWorkflowRedirect"),
              },
              {
                path: "health",
                ...lazyScreen(() => import("./screens/health"), "HealthScreen"),
              },
              {
                path: "*",
                ...lazyScreen(() => import("./screens/not-found"), "NotFoundScreen"),
              },
            ],
          },
          { path: "settings", element: <Navigate to="/settings/hubs" replace /> },
          {
            path: "settings/:section",
            ...lazyScreen(() => import("./screens/settings"), "SettingsScreen"),
          },
          {
            path: "welcome",
            ...lazyScreen(() => import("./screens/welcome"), "WelcomeScreen"),
          },
        ],
      },
    ],
  },
];
