/*
 * Every control of an operation that needs the launch cookie locks itself up front (the web side
 * of the API's write route inventory). The scan finds each write call (`apiPost`, `apiPut`,
 * `apiDelete`, `apiCommand`, by literal path or a path constant) whose operation the API marks
 * (`LAUNCH_COOKIE_ROUTES`); `CONTROLS` names, for each file that makes such a call, the files
 * that render its controls, and each of those must read the lock. A new call fails here until its
 * controls are listed and locked; a listed caller that no longer calls fails too.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { needsLaunchCookie } from "./lib/launchCookie";

// Vitest runs from apps/web, as the other tests that read sources assume.
const SRC = join(process.cwd(), "src");

/** How a file reads the lock: the launch cookie hook, or the agent sessions' own check (its 401,
 * through `sessionControlUnavailable` or the hooks built on it). */
const LOCK_READS = [
  /useLaunchCookie\(/,
  /sessionControlUnavailable\(/,
  /useHubSessionStart\(/,
  /useDriving\(/,
];

/** Each caller of a launch-cookie write, and the files that render the controls behind it. */
const CONTROLS: Record<string, readonly string[]> = {
  // Agent sessions: started, driven and ended where the session control check runs.
  "screens/agent-session/queries.ts": [
    "screens/agent-session/index.tsx",
    "shell/discussSession.ts",
    "screens/scenarios/Investigation.tsx",
    "screens/skills/Studio.tsx",
  ],
  "screens/sessions-list/queries.ts": [
    "screens/sessions-list/DrivenControls.tsx",
    "screens/tickets/StartTicket.tsx",
    "shell/ShakeToSession.tsx",
    "shell/discussSession.ts",
    "screens/feature-detail/StartTicket.tsx",
    "screens/feature-detail/EvalTab.tsx",
    "screens/feature-detail/CheckRun.tsx",
    "screens/learnings/triage.tsx",
    "screens/learnings/ReviewPanel.tsx",
    "screens/skills/Studio.tsx",
  ],
  "shell/DiscussPanel.tsx": ["shell/discussSession.ts"],
  "screens/session-detail/ContinueInChat.tsx": ["screens/session-detail/ContinueInChat.tsx"],
  "screens/feature-detail/ApproveRecord.tsx": ["screens/feature-detail/ApproveRecord.tsx"],
  "screens/environments/DiscoverPage.tsx": ["screens/environments/DiscoverPage.tsx"],
  "screens/environments/ReviewPage.tsx": ["screens/environments/ReviewPage.tsx"],
  // Runs: workflow runs, gates, checks and change requests.
  "screens/runs-list/StartRun.tsx": ["screens/runs-list/StartRun.tsx"],
  "screens/run-detail/RunCommands.tsx": ["screens/run-detail/RunCommands.tsx"],
  "screens/approvals/queries.ts": ["screens/approvals/GateDecision.tsx"],
  "screens/feature-detail/CheckRun.tsx": ["screens/feature-detail/CheckRun.tsx"],
  "screens/feature-detail/queries.ts": ["screens/feature-detail/TicketPanel.tsx"],
  // The owner's sign-off.
  "screens/feature-detail/EvalTab.tsx": ["screens/feature-detail/EvalTab.tsx"],
  "screens/feature-detail/MarkAcPassing.tsx": ["screens/feature-detail/MarkAcPassing.tsx"],
  // The owner's writes: Hub config, hub actions, learnings, the Linear key, nicknames.
  "screens/hub-config/LocalSettingsDialog.tsx": [
    "screens/hub-config/LocalSettingsDialog.tsx",
    "screens/hub-config/parts.tsx",
    "screens/hub-config/index.tsx",
  ],
  "screens/hub-config/repos.ts": [
    "screens/hub-config/index.tsx",
    "screens/hub-config/RepoForm.tsx",
  ],
  "screens/hub-config/environments.ts": [
    "screens/hub-config/SetupFlow.tsx",
    "screens/hub-config/EnvironmentsSection.tsx",
    "screens/hub-config/ServicePanel.tsx",
    "screens/environments/ReviewPage.tsx",
    "screens/scenarios/builder/ScenarioBuilder.tsx",
  ],
  "screens/settings/queries.ts": ["screens/settings/index.tsx"],
  "screens/health/queries.ts": ["screens/health/index.tsx"],
  "screens/learnings/queries.ts": ["screens/learnings/LearningDetail.tsx"],
  "screens/learnings/staged.ts": ["screens/learnings/TriageBatch.tsx"],
  "screens/features/names.tsx": ["screens/features/names.tsx"],
  // The owner's status decision (shipped, closed, paused, reopened): the Status menu, the
  // bulk bar of the Features list and the dialog they open, which reads the lock.
  "screens/features/ownerStatus.tsx": ["screens/features/ownerStatus.tsx"],
  // Items written into a hub: scenarios, actions, skills, restores.
  "screens/scenarios/queries.ts": [
    "screens/scenarios/DebugBar.tsx",
    "screens/scenarios/RunBlocks.tsx",
    "screens/scenarios/Findings.tsx",
    "screens/scenarios/RunPanel.tsx",
    "screens/scenarios/DeleteScenario.tsx",
    "screens/scenarios/Investigation.tsx",
    "screens/scenarios/builder/ScenarioBuilder.tsx",
    "screens/scenarios/builder/MigrateDialog.tsx",
  ],
  "screens/scenarios/builder/useScenarioDraft.ts": [
    "screens/scenarios/builder/ScenarioBuilder.tsx",
  ],
  "screens/scenarios/NewScenario.tsx": ["screens/scenarios/NewScenario.tsx"],
  "screens/scenarios/builder/ClaudeDialogs.tsx": ["screens/scenarios/builder/ClaudeDialogs.tsx"],
  "screens/scenarios/Investigation.tsx": ["screens/scenarios/Investigation.tsx"],
  "screens/skills/queries.ts": ["screens/skills/Studio.tsx"],
  "screens/item-history/queries.ts": ["screens/item-history/index.tsx"],
};

const VERBS: Record<string, string> = {
  Post: "POST",
  Command: "POST",
  Put: "PUT",
  Delete: "DELETE",
};

function sources(folder: string): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) return entry.name === "testing" ? [] : sources(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

/** The launch-cookie writes a source file calls, as `METHOD /path`. */
export function launchCookieCalls(text: string): string[] {
  const constants = new Map(
    [...text.matchAll(/const ([A-Z][A-Z0-9_]*)\s*=\s*"(\/api\/v1[^"]*)"/g)].map((m) => [
      m[1] ?? "",
      m[2] ?? "",
    ]),
  );
  const calls = text.matchAll(
    /api(Post|Put|Delete|Command)(?:<[^>]*>)?\(\s*(?:"(\/api\/v1[^"]*)"|([A-Z][A-Z0-9_]*)\b)/g,
  );
  return [...calls]
    .map((m) => [VERBS[m[1] ?? ""] ?? "", m[2] ?? constants.get(m[3] ?? "") ?? ""] as const)
    .filter(([verb, path]) => path !== "" && needsLaunchCookie(verb, path))
    .map(([verb, path]) => `${verb} ${path}`);
}

const callers = new Map(
  sources(SRC)
    .filter((path) => !path.endsWith("lib/api.ts"))
    .map((path) => [relative(SRC, path), launchCookieCalls(readFileSync(path, "utf8"))] as const)
    .filter(([, calls]) => calls.length > 0),
);

describe("the launch cookie controls", () => {
  it("lists every caller of a launch-cookie write, and no other file", () => {
    expect(Object.keys(CONTROLS).sort()).toEqual([...callers.keys()].sort());
  });

  it.each(Object.entries(CONTROLS).flatMap(([caller, files]) => files.map((f) => [caller, f])))(
    "locks the controls of %s in %s",
    (_caller, file) => {
      const text = readFileSync(join(SRC, file), "utf8");

      expect(LOCK_READS.some((read) => read.test(text))).toBe(true);
    },
  );

  it("finds a literal and a constant write, and leaves out the writes that need no cookie", () => {
    const text = [
      'const CANCEL = "/api/v1/workflow-runs/{run_id}/cancel";',
      "apiCommand(CANCEL, params);",
      'apiPut("/api/v1/feature-names", body);',
      'apiPost("/api/v1/hubs", body);',
      'apiGet("/api/v1/feature-names");',
    ].join("\n");

    expect(launchCookieCalls(text)).toEqual([
      "POST /api/v1/workflow-runs/{run_id}/cancel",
      "PUT /api/v1/feature-names",
    ]);
  });
});
