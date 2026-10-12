// Generated from packages/api/openapi.json by scripts/gen-api.mjs (make openapi); do not edit.

export interface paths {
  "/api/v1/activity": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Activity
     * @description Notable events, newest first.
     */
    get: operations["list_activity_api_v1_activity_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/approvals": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Approvals
     * @description Approvals, oldest first.
     */
    get: operations["list_approvals_api_v1_approvals_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/approvals/{approval_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Approval
     * @description One approval.
     */
    get: operations["get_approval_api_v1_approvals__approval_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/collector/status": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Collector Status
     * @description The collector's counters and sources.
     */
    get: operations["get_collector_status_api_v1_collector_status_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/doctor/findings": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Doctor Findings
     * @description Findings of every (or one) project, as ``hub doctor --json`` reports them.
     */
    get: operations["list_doctor_findings_api_v1_doctor_findings_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/events/hooks": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Post Hook
     * @description Map one hook envelope to events and append them (redacted).
     */
    post: operations["post_hook_api_v1_events_hooks_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/events/stream": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Stream Events
     * @description The global stream.
     */
    get: operations["stream_events_api_v1_events_stream_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/features": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Features
     * @description Features of every (or one) project.
     */
    get: operations["list_features_api_v1_features_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/features/{project}/{slug}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Feature
     * @description One feature with its acceptance criteria.
     */
    get: operations["get_feature_api_v1_features__project___slug__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/hubs": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Hubs
     * @description Every registered hub, valid or not.
     */
    get: operations["list_hubs_api_v1_hubs_get"];
    put?: never;
    /**
     * Register Hub
     * @description Register a hub by its path.
     */
    post: operations["register_hub_api_v1_hubs_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/hubs/{hub_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    /**
     * Remove Hub
     * @description Forget a hub; its events stay in the store.
     */
    delete: operations["remove_hub_api_v1_hubs__hub_id__delete"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/learnings": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Learnings
     * @description Learnings, newest first.
     */
    get: operations["list_learnings_api_v1_learnings_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/learnings/{learning_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Learning
     * @description One learning.
     */
    get: operations["get_learning_api_v1_learnings__learning_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/live-sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Live Sessions
     * @description Live session tiles, waiting first.
     */
    get: operations["list_live_sessions_api_v1_live_sessions_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/live-sessions/stream": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Stream Live Sessions
     * @description Live tiles as they change.
     */
    get: operations["stream_live_sessions_api_v1_live_sessions_stream_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/needs-you": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Needs You
     * @description What waits for a person, oldest first.
     */
    get: operations["list_needs_you_api_v1_needs_you_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Projects
     * @description A card per registered project.
     */
    get: operations["list_projects_api_v1_projects_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Project
     * @description The Project overview header.
     */
    get: operations["get_project_api_v1_projects__project__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/now": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Project Now
     * @description The project's ``brain/now.md``.
     */
    get: operations["get_project_now_api_v1_projects__project__now_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/repos": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Project Repos
     * @description The project's repos.
     */
    get: operations["list_project_repos_api_v1_projects__project__repos_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/search": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Search
     * @description Search ids, paths, commands and tool names.
     */
    get: operations["search_api_v1_search_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Sessions
     * @description Sessions matching the filters, one page.
     */
    get: operations["list_sessions_api_v1_sessions_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/sessions/{session_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Session
     * @description One session.
     */
    get: operations["get_session_api_v1_sessions__session_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/sessions/{session_id}/cost": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Session Cost
     * @description The session's estimated cost.
     */
    get: operations["get_session_cost_api_v1_sessions__session_id__cost_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/sessions/{session_id}/events": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Session Events
     * @description The session's events in timestamp order.
     */
    get: operations["list_session_events_api_v1_sessions__session_id__events_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/sessions/{session_id}/events/stream": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Stream Session Events
     * @description One session's events as they arrive.
     */
    get: operations["stream_session_events_api_v1_sessions__session_id__events_stream_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/sessions/{session_id}/files": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Session Files
     * @description The paths the session touched.
     */
    get: operations["list_session_files_api_v1_sessions__session_id__files_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/sessions/{session_id}/summary": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Session Summary
     * @description The session's summary lines.
     */
    get: operations["get_session_summary_api_v1_sessions__session_id__summary_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/settings": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Settings
     * @description Paths, port, version and privacy rules.
     */
    get: operations["get_settings_api_v1_settings_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflow-runs": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Runs
     * @description Workflow runs matching the filters, newest first.
     */
    get: operations["list_runs_api_v1_workflow_runs_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflow-runs/{run_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Run
     * @description One workflow run with its steps.
     */
    get: operations["get_run_api_v1_workflow_runs__run_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflow-runs/{run_id}/stream": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Stream Run
     * @description One run's changes as they arrive.
     */
    get: operations["stream_run_api_v1_workflow_runs__run_id__stream_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /**
     * AcCounts
     * @description Passing and total acceptance criteria, and how many are owner steps.
     */
    AcCounts: {
      /** Owner Steps */
      owner_steps: number;
      /** Passing */
      passing: number;
      /** Total */
      total: number;
    };
    /**
     * AcRow
     * @description One acceptance criterion of ``features.json``.
     */
    AcRow: {
      /** Command */
      command?: string | null;
      /** Description */
      description: string;
      /** Evidence */
      evidence?: string | null;
      /** Id */
      id: string;
      /**
       * Manual
       * @default false
       */
      manual: boolean;
      /** Passes */
      passes: boolean;
      /** Repo */
      repo: string | null;
    };
    /**
     * ActivityItem
     * @description A notable event in the activity feed.
     */
    ActivityItem: {
      at: components["schemas"]["ApiTimestamp"];
      event_id?: components["schemas"]["EventId"] | null;
      /** Href */
      href: string | null;
      kind: components["schemas"]["ActivityKind"];
      /** Project */
      project: string;
      /** Text */
      text: string;
    };
    /** @enum {string} */
    ActivityKind: "reported" | "failed" | "learning" | "doctor" | "approval";
    /** Format: date-time */
    ApiTimestamp: string;
    /**
     * Approval
     * @description An approval. ``decided`` once a matching result exists; ``inferred`` when the decision is
     *     deduced (a guard ask with no tool run before the next prompt or stop is declined).
     *
     *     ``how_to_decide`` is the terminal command that answers it, since Phase 2 is read-only:
     *     ``cd <hub path> && claude --resume <session id>``.
     */
    Approval: {
      /** Decided */
      decided: boolean;
      decided_at?: components["schemas"]["ApiTimestamp"] | null;
      decision_event_id?: components["schemas"]["EventId"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Feature */
      feature?: string | null;
      /** Gate Id */
      gate_id: string;
      /** How To Decide */
      how_to_decide?: string | null;
      /** Hub Path */
      hub_path?: string | null;
      /** Id */
      id: string;
      /**
       * Inferred
       * @default false
       */
      inferred: boolean;
      /** Issue */
      issue?: string | null;
      kind: components["schemas"]["ApprovalKind"];
      /** Path */
      path?: string | null;
      /** Project */
      project: string;
      /** Repo */
      repo: string | null;
      request_event_id: components["schemas"]["EventId"];
      requested_at: components["schemas"]["ApiTimestamp"];
      /** Requested By */
      requested_by: string | null;
      /** Rule */
      rule?: string | null;
      /** Session Id */
      session_id: string;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      status: components["schemas"]["ApprovalStatus"];
      /** Title */
      title: string;
    };
    /**
     * ApprovalKind
     * @description The kinds of request D24 lists.
     * @enum {string}
     */
    ApprovalKind: "guard_ask" | "plan" | "spec" | "human_gate" | "permission";
    /** @enum {string} */
    ApprovalStatus: "open" | "approved" | "declined" | "changes_requested" | "rejected";
    /**
     * CollectorStatus
     * @description ``GET /collector/status``: what ``hub web`` received and stored since it started.
     */
    CollectorStatus: {
      /** Appended */
      appended: number;
      /** Db Path */
      db_path: string;
      /** Duplicates */
      duplicates: number;
      /** Events Total */
      events_total: number;
      /** Hooks Received */
      hooks_received: number;
      last_event_at: components["schemas"]["ApiTimestamp"] | null;
      /**
       * Redaction Ruleset
       * @default r1
       */
      redaction_ruleset: string;
      /** Running Version */
      running_version: string;
      /** Sources */
      sources: components["schemas"]["SourceStatus"][];
      started_at: components["schemas"]["ApiTimestamp"];
      /**
       * State
       * @default running
       * @constant
       */
      state: "running";
      /** Transcript Lines Skipped */
      transcript_lines_skipped: number;
      /** Transcript Refused */
      transcript_refused: number;
    };
    EventId: string;
    /**
     * EventSource
     * @description Where an event comes from; with ``source_id`` it identifies the event.
     * @enum {string}
     */
    EventSource:
      "claude_code" | "transcript" | "otel" | "executor" | "github" | "linear" | "control_plane";
    /**
     * EventType
     * @description The closed list of event types in the SPEC; widening it later is a compatible change.
     * @enum {string}
     */
    EventType:
      | "session.start"
      | "session.end"
      | "tool.call"
      | "tool.result"
      | "message"
      | "reasoning"
      | "decision"
      | "gate.request"
      | "gate.result"
      | "learning.proposed"
      | "learning.accepted"
      | "learning.rejected"
      | "step.start"
      | "step.end"
      | "run.end"
      | "session.summary";
    /**
     * FeatureDetail
     * @description A feature with its acceptance criteria rows.
     */
    FeatureDetail: {
      /**
       * Ac Rows
       * @default []
       */
      ac_rows: components["schemas"]["AcRow"][];
      acs: components["schemas"]["AcCounts"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Files */
      files: string[];
      /** Issues */
      issues: string[];
      phase: components["schemas"]["FeaturePhase"];
      /** Problem */
      problem?: string | null;
      /** Project */
      project: string;
      /** Repos */
      repos: string[];
      /** Size */
      size: ("spike" | "bounded" | "architectural") | null;
      /** Slug */
      slug: string;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      verdict: components["schemas"]["Verdict"] | null;
      /** Verdict Line */
      verdict_line: string | null;
    };
    /** @enum {string} */
    FeaturePhase:
      "spec" | "research" | "plan" | "tickets" | "implement" | "review" | "evaluate" | "shipped";
    /**
     * FeatureView
     * @description A feature as the Features list shows it; ``problem`` when a file of it is malformed.
     */
    FeatureView: {
      acs: components["schemas"]["AcCounts"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Files */
      files: string[];
      /** Issues */
      issues: string[];
      phase: components["schemas"]["FeaturePhase"];
      /** Problem */
      problem?: string | null;
      /** Project */
      project: string;
      /** Repos */
      repos: string[];
      /** Size */
      size: ("spike" | "bounded" | "architectural") | null;
      /** Slug */
      slug: string;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      verdict: components["schemas"]["Verdict"] | null;
      /** Verdict Line */
      verdict_line: string | null;
    };
    /** @enum {string} */
    FileOperation: "read" | "edited" | "created" | "written";
    /**
     * FindingView
     * @description A finding of a registered hub's doctor run.
     */
    FindingView: {
      /** Fix */
      fix: string;
      /** Line */
      line: number | null;
      /** Message */
      message: string;
      /** Path */
      path: string | null;
      /** Project */
      project: string;
      /** Rule */
      rule: string;
      severity: components["schemas"]["Severity"];
    };
    /**
     * HookAccepted
     * @description ``POST /events/hooks``: how many events the envelope added and how many were known.
     */
    HookAccepted: {
      /** Appended */
      appended: number;
      /** Duplicates */
      duplicates: number;
    };
    /**
     * HookDecision
     * @description What the guard or the Stop gate decided, sent with the hook input that caused it.
     */
    HookDecision: {
      /**
       * By
       * @enum {string}
       */
      by: "guard" | "stop_gate";
      /** Command */
      command?: string | null;
      /** Exit Code */
      exit_code?: number | null;
      /**
       * Kind
       * @enum {string}
       */
      kind: "deny" | "ask" | "block";
      /** Rule */
      rule?: string | null;
    };
    /**
     * HookEnvelope
     * @description Version 1 of the sensor's envelope.
     *
     *     ``project`` comes from the hub's ``hub.json``; ``repo`` from the hook's cwd (a repo checkout
     *     or one of its worktrees), else None; ``run``, ``step`` and ``attempt`` from the variables
     *     ``hub run`` sets for its session. ``hook`` is the Claude Code hook input as received, with
     *     oversized strings already omitted by the sensor.
     */
    HookEnvelope: {
      /** Attempt */
      attempt?: number | null;
      decision?: components["schemas"]["HookDecision"] | null;
      /** Hook */
      hook: {
        [key: string]: components["schemas"]["JsonValue"];
      };
      /** Project */
      project: string;
      /** Repo */
      repo?: string | null;
      /** Run */
      run?: string | null;
      sent_at: components["schemas"]["UtcTimestamp"];
      /** Step */
      step?: string | null;
      /**
       * V
       * @constant
       */
      v: 1;
    };
    /**
     * HubCreate
     * @description ``POST /hubs``: the absolute path of a hub to register.
     */
    HubCreate: {
      /** Path */
      path: string;
    };
    /** @enum {string} */
    HubHealth: "ok" | "warning" | "error";
    /**
     * HubView
     * @description A registered hub as read now.
     *
     *     ``valid`` is false when ``hub.json`` is unreadable or does not match the schema
     *     (``validation_errors``). A pin other than the running version is read anyway and shows as
     *     a warning ("pinned X, running Y").
     */
    HubView: {
      added_at: components["schemas"]["ApiTimestamp"];
      /** Guard Ask Before Edit */
      guard_ask_before_edit: string[];
      /** Id */
      id: string;
      lock_state: components["schemas"]["LockState"] | null;
      /** Lock Version */
      lock_version: string | null;
      /** Modules */
      modules: string[];
      /** Path */
      path: string;
      /** Platform Pin */
      platform_pin: string | null;
      /** Project */
      project: string | null;
      /** Repos */
      repos: string[];
      /** Running Version */
      running_version: string;
      /** Valid */
      valid: boolean;
      /**
       * Validation Errors
       * @default []
       */
      validation_errors: components["schemas"]["ValidationProblem"][];
      /**
       * Warnings
       * @default []
       */
      warnings: string[];
    };
    /**
     * IssueRef
     * @description The tracker issue a run works on; title and url need Linear (``null`` in Phase 2).
     */
    IssueRef: {
      /** Key */
      key: string;
      /** Title */
      title?: string | null;
      /** Url */
      url?: string | null;
    };
    JsonValue: unknown;
    /**
     * Learning
     * @description A learning; ``text`` is its title (120 characters at most, redacted).
     */
    Learning: {
      /** Author */
      author: string | null;
      /** Brain Path */
      brain_path?: string | null;
      /** Commit */
      commit?: string | null;
      decided_at?: components["schemas"]["ApiTimestamp"] | null;
      /** Decided By */
      decided_by?: string | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Id */
      id: string;
      /** Project */
      project: string;
      proposed_at: components["schemas"]["ApiTimestamp"] | null;
      /** Provenance */
      provenance: ("human" | "agent" | "agent-from-code" | "agent-from-external") | null;
      /** Rejection Reason */
      rejection_reason?: string | null;
      source_event_id: components["schemas"]["EventId"] | null;
      /** Source Session Id */
      source_session_id: string | null;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      status: components["schemas"]["LearningStatus"];
      target: components["schemas"]["LearningTarget"];
      /** Text */
      text: string;
    };
    /**
     * LearningStatus
     * @description Where a learning is: proposed until a terminal event in source order decides it.
     * @enum {string}
     */
    LearningStatus: "proposed" | "accepted" | "rejected";
    /**
     * LearningTarget
     * @description Where a learning would go: team brain, a repo's AGENTS.md, or personal memory.
     */
    LearningTarget: {
      /** Kind */
      kind: ("team" | "repo" | "personal") | null;
      /** Path */
      path: string | null;
    };
    /**
     * LiveTile
     * @description A session tile of the Live sessions screen.
     */
    LiveTile: {
      /** Agent */
      agent: string;
      /** Attempt */
      attempt?: number | null;
      budget_usd?: components["schemas"]["Money"] | null;
      cost_usd: components["schemas"]["Money"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      ended_at?: components["schemas"]["ApiTimestamp"] | null;
      /** Errors */
      errors: number;
      /** Failing Notice */
      failing_notice?: string | null;
      /** Files Touched */
      files_touched: number;
      group: components["schemas"]["TileGroup"];
      /** Guard Denials */
      guard_denials: number;
      /** Id */
      id: string;
      /**
       * Is Subagent
       * @default false
       */
      is_subagent: boolean;
      /** Issue */
      issue?: string | null;
      /** Last Action */
      last_action: string | null;
      last_activity_at: components["schemas"]["ApiTimestamp"];
      /** Last Tool */
      last_tool: string | null;
      outcome?: components["schemas"]["Outcome"] | null;
      /** Project */
      project: string;
      /** Repo */
      repo: string | null;
      /** Run Id */
      run_id?: string | null;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      /**
       * Sparkline 60S
       * @default []
       */
      sparkline_60s: number[];
      started_at: components["schemas"]["ApiTimestamp"];
      status: components["schemas"]["SessionStatus"];
      /** Step */
      step?: string | null;
      /** Tokens Total */
      tokens_total: number;
      /** Turns */
      turns: number;
      /** Waiting Reason */
      waiting_reason?: string | null;
    };
    /** @enum {string} */
    LockState: "in_sync" | "drift" | "sync_pending" | "not_adopted";
    Money: string;
    /**
     * NeedsYouItem
     * @description A verb-first line of the Needs you list.
     */
    NeedsYouItem: {
      /** Context */
      context: string;
      /** Href */
      href: string;
      kind: components["schemas"]["NeedsYouKind"];
      /** Project */
      project: string;
      since: components["schemas"]["ApiTimestamp"] | null;
      /** Verb */
      verb: string;
    };
    /** @enum {string} */
    NeedsYouKind: "approval" | "failed" | "waiting" | "blocked" | "doctor" | "learning";
    /**
     * NowItem
     * @description One line of ``brain/now.md``.
     */
    NowItem: {
      /** Last Verified */
      last_verified?: string | null;
      /** Provenance */
      provenance?: string | null;
      /** Text */
      text: string;
    };
    /**
     * Outcome
     * @description How an ended session ended; ``None`` when no source says.
     * @enum {string}
     */
    Outcome: "done" | "stopped" | "blocked" | "error";
    /** Page[ActivityItem] */
    Page_ActivityItem_: {
      /** Items */
      items: components["schemas"]["ActivityItem"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[Approval] */
    Page_Approval_: {
      /** Items */
      items: components["schemas"]["Approval"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[FeatureView] */
    Page_FeatureView_: {
      /** Items */
      items: components["schemas"]["FeatureView"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[FindingView] */
    Page_FindingView_: {
      /** Items */
      items: components["schemas"]["FindingView"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[HubView] */
    Page_HubView_: {
      /** Items */
      items: components["schemas"]["HubView"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[Learning] */
    Page_Learning_: {
      /** Items */
      items: components["schemas"]["Learning"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[LiveTile] */
    Page_LiveTile_: {
      /** Items */
      items: components["schemas"]["LiveTile"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[NeedsYouItem] */
    Page_NeedsYouItem_: {
      /** Items */
      items: components["schemas"]["NeedsYouItem"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[ProjectSummary] */
    Page_ProjectSummary_: {
      /** Items */
      items: components["schemas"]["ProjectSummary"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[RepoView] */
    Page_RepoView_: {
      /** Items */
      items: components["schemas"]["RepoView"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[SearchHit] */
    Page_SearchHit_: {
      /** Items */
      items: components["schemas"]["SearchHit"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[SessionFileChange] */
    Page_SessionFileChange_: {
      /** Items */
      items: components["schemas"]["SessionFileChange"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[Session] */
    Page_Session_: {
      /** Items */
      items: components["schemas"]["Session"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[TimelineEvent] */
    Page_TimelineEvent_: {
      /** Items */
      items: components["schemas"]["TimelineEvent"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /** Page[WorkflowRun] */
    Page_WorkflowRun_: {
      /** Items */
      items: components["schemas"]["WorkflowRun"][];
      /** Next Cursor */
      next_cursor?: string | null;
      /** Total Estimate */
      total_estimate: number;
    };
    /**
     * ProblemDetails
     * @description An RFC 9457 problem; extension members (``errors``) are allowed.
     */
    ProblemDetails: {
      /** Detail */
      detail?: string | null;
      /** Instance */
      instance?: string | null;
      /** Status */
      status: number;
      /** Title */
      title: string;
      /**
       * Type
       * @default about:blank
       */
      type: string;
    } & {
      [key: string]: unknown;
    };
    /**
     * ProjectDetail
     * @description The Project overview header.
     */
    ProjectDetail: {
      /** Branch Prefix */
      branch_prefix: string | null;
      /** Default Branch */
      default_branch: string | null;
      /** Hub Id */
      hub_id: string;
      /** Hub Path */
      hub_path: string;
      /** Hub Repo */
      hub_repo: string;
      lock_state: components["schemas"]["LockState"] | null;
      /** Lock Version */
      lock_version: string | null;
      /** Modules */
      modules: string[];
      /** Name */
      name: string;
      /** Platform Version */
      platform_version: string;
      tracker: components["schemas"]["TrackerView"];
      /**
       * Warnings
       * @default []
       */
      warnings: string[];
    };
    /**
     * ProjectNow
     * @description ``brain/now.md`` split into its sections; ``problem`` when it cannot be read.
     */
    ProjectNow: {
      /** Focus */
      focus: components["schemas"]["NowItem"][];
      /** Next */
      next: components["schemas"]["NowItem"][];
      /** Problem */
      problem?: string | null;
      /** Project */
      project: string;
      /** Source Path */
      source_path: string | null;
      /** Watch */
      watch: components["schemas"]["NowItem"][];
    };
    /**
     * ProjectSummary
     * @description A Portfolio card: hub config plus the project's activity; PRs and issues need sources
     *     not connected in Phase 2 (``null``).
     */
    ProjectSummary: {
      /**
       * Cost Daily
       * @default []
       */
      cost_daily: components["schemas"]["Money"][];
      cost_period: components["schemas"]["Money"] | null;
      cost_previous_period: components["schemas"]["Money"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Failed Runs 7D */
      failed_runs_7d: number;
      hub_health: components["schemas"]["HubHealth"] | null;
      /** Hub Id */
      hub_id: string;
      /** Hub Repo */
      hub_repo: string;
      /** Live Sessions */
      live_sessions: number;
      lock_state: components["schemas"]["LockState"] | null;
      /** Lock Version */
      lock_version: string | null;
      /** Name */
      name: string;
      /** Open Prs */
      open_prs?: number | null;
      /** Platform Version */
      platform_version: string;
      /** Ready Issues */
      ready_issues?: number | null;
      /** Repos */
      repos: string[];
      /** Runs In Flight By Stage */
      runs_in_flight_by_stage: {
        [key: string]: number;
      };
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      /** Tracker Teams */
      tracker_teams: string[];
    };
    /**
     * PullRequestRef
     * @description A pull request; GitHub is not connected in Phase 2, so sessions carry ``null``.
     */
    PullRequestRef: {
      /** Number */
      number: number;
      /** State */
      state: string;
      /** Url */
      url: string;
    };
    /**
     * RepoView
     * @description A repo of the project as ``hub.json`` and its checkout describe it.
     */
    RepoView: {
      /** Agents Md Lines */
      agents_md_lines: number | null;
      /** Agents Md Present */
      agents_md_present: boolean;
      /** Check */
      check: string;
      /** Check Fast */
      check_fast: string;
      /** Default Branch */
      default_branch: string | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Dir */
      dir: string;
      /** Github */
      github: string;
      /** Name */
      name: string;
      /** Open Prs */
      open_prs?: number | null;
      /** Role */
      role: string | null;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
    };
    /**
     * RunCaps
     * @description The limits a run started with.
     */
    RunCaps: {
      budget_usd: components["schemas"]["Money"] | null;
      /** Max Turns */
      max_turns: number | null;
      /** Model */
      model: string | null;
      /** Tracker Transport */
      tracker_transport: string | null;
    };
    /**
     * RunFailure
     * @description Where and why a run failed, and the event to open ("Open failing moment").
     */
    RunFailure: {
      /** Diagnosis Comment Url */
      diagnosis_comment_url?: string | null;
      failing_event_id: components["schemas"]["EventId"] | null;
      /** Reason */
      reason: string | null;
      stage: components["schemas"]["Stage"];
    };
    /**
     * RunGateResult
     * @description A gate the executor ran (``gate_ok`` or a failed check).
     */
    RunGateResult: {
      /** Command */
      command?: string | null;
      /** Duration Ms */
      duration_ms?: number | null;
      event_id: components["schemas"]["EventId"];
      /** Exit Code */
      exit_code?: number | null;
      /**
       * Result
       * @enum {string}
       */
      result: "passed" | "failed";
    };
    /**
     * RunStep
     * @description One step attempt, keyed ``(key, attempt)``; a loop back into verify is attempt 2.
     */
    RunStep: {
      /** Attempt */
      attempt: number;
      ended_at: components["schemas"]["ApiTimestamp"] | null;
      key: components["schemas"]["StepKey"];
      /** Max Attempts */
      max_attempts: number;
      /** Reason */
      reason?: string | null;
      /**
       * Session Ids
       * @default []
       */
      session_ids: string[];
      started_at: components["schemas"]["ApiTimestamp"];
      status: components["schemas"]["StepStatus"];
    };
    /**
     * SearchHit
     * @description A search result over ids, paths, commands and tool names; never payload bodies.
     */
    SearchHit: {
      /** Detail */
      detail: string | null;
      event_id?: components["schemas"]["EventId"] | null;
      /** Href */
      href: string;
      kind: components["schemas"]["SearchKind"];
      /** Label */
      label: string;
      /** Project */
      project: string | null;
    };
    /** @enum {string} */
    SearchKind:
      "session" | "run" | "approval" | "learning" | "feature" | "file" | "command" | "tool";
    /**
     * Session
     * @description A session folded from its events (status, counts, tokens, estimated cost).
     */
    Session: {
      /** Agent */
      agent: string;
      /** Attempt */
      attempt?: number | null;
      /** Cost Unknown Reason */
      cost_unknown_reason?: string | null;
      cost_usd: components["schemas"]["Money"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /**
       * End Inferred
       * @default false
       */
      end_inferred: boolean;
      /** End Reason */
      end_reason: string | null;
      ended_at: components["schemas"]["ApiTimestamp"] | null;
      /** Errors */
      errors: number;
      /** Files Touched */
      files_touched: number;
      /** Gates */
      gates: number;
      /** Guard Denials */
      guard_denials: number;
      /** Has Transcript */
      has_transcript: boolean;
      /** Id */
      id: string;
      /** Issue */
      issue?: string | null;
      last_activity_at: components["schemas"]["ApiTimestamp"];
      /** Learnings Proposed */
      learnings_proposed: number;
      /** Model */
      model: string | null;
      outcome: components["schemas"]["Outcome"] | null;
      /** Parent Session Id */
      parent_session_id?: string | null;
      pr?: components["schemas"]["PullRequestRef"] | null;
      /** Project */
      project: string;
      /** Repo */
      repo: string | null;
      /** Run Id */
      run_id?: string | null;
      /** Segments */
      segments: components["schemas"]["SessionSegment"][];
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      started_at: components["schemas"]["ApiTimestamp"];
      status: components["schemas"]["SessionStatus"];
      /** Step */
      step?: string | null;
      tokens: components["schemas"]["TokenUsage"] | null;
      /** Tool Counts */
      tool_counts: {
        [key: string]: number;
      };
      /** Turns */
      turns: number;
    };
    /**
     * SessionCost
     * @description The Cost tab: per-turn series and totals, always "Estimated from transcript" (D15).
     */
    SessionCost: {
      budget_usd?: components["schemas"]["Money"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Model */
      model: string | null;
      /** Prices As Of */
      prices_as_of: string | null;
      run_total_usd?: components["schemas"]["Money"] | null;
      /** Series */
      series: components["schemas"]["TurnCost"][];
      /** Session Id */
      session_id: string;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      total_usd: components["schemas"]["Money"] | null;
      /** Unknown Reason */
      unknown_reason?: string | null;
    };
    /**
     * SessionFileChange
     * @description A path a session touched, its operations and line counts (no content is stored).
     */
    SessionFileChange: {
      /** Added */
      added: number;
      /** Event Ids */
      event_ids: components["schemas"]["EventId"][];
      /** Ops */
      ops: components["schemas"]["FileOperation"][];
      /** Path */
      path: string;
      /** Removed */
      removed: number;
      /** Repo */
      repo: string | null;
    };
    /**
     * SessionSegment
     * @description One stretch of a session; a later event after an end reopens it as a new segment.
     */
    SessionSegment: {
      /**
       * End Inferred
       * @default false
       */
      end_inferred: boolean;
      /** End Reason */
      end_reason: string | null;
      ended_at: components["schemas"]["ApiTimestamp"] | null;
      /** Index */
      index: number;
      started_at: components["schemas"]["ApiTimestamp"];
    };
    /**
     * SessionStatus
     * @description Where a session is now (D14): waiting wins over live; ended is final until reopened.
     * @enum {string}
     */
    SessionStatus: "live" | "waiting" | "idle" | "ended";
    /**
     * SessionSummary
     * @description 3 to 5 deterministic lines (D17); a stored ``session.summary`` event wins (``stored``).
     */
    SessionSummary: {
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      generated_at: components["schemas"]["ApiTimestamp"];
      /** Lines */
      lines: components["schemas"]["SummaryLine"][];
      /** Session Id */
      session_id: string;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      /**
       * Stored
       * @default false
       */
      stored: boolean;
    };
    /**
     * SettingsView
     * @description Read-only settings of the running ``hub web`` (no ``PATCH`` in Phase 2).
     */
    SettingsView: {
      /** Db Path */
      db_path: string;
      /**
       * Metadata Only
       * @default true
       */
      metadata_only: boolean;
      /** Port */
      port: number;
      /** Prices As Of */
      prices_as_of: string | null;
      /** Redaction Kinds */
      redaction_kinds: string[];
      /**
       * Redaction Ruleset
       * @default r1
       */
      redaction_ruleset: string;
      /** Registry Path */
      registry_path: string;
      /** Running Version */
      running_version: string;
    };
    /**
     * Severity
     * @description The level of a finding.
     * @enum {string}
     */
    Severity: "error" | "warning" | "info";
    /**
     * SourceStatus
     * @description When a source last sent an event, and whether that is recent enough.
     */
    SourceStatus: {
      last_event_at: components["schemas"]["ApiTimestamp"] | null;
      source: components["schemas"]["EventSource"];
      /**
       * State
       * @enum {string}
       */
      state: "fresh" | "stale" | "never";
    };
    /**
     * Stage
     * @description A state of the run's machine; any stage before ``REPORTED`` can end in ``FAILED``.
     * @enum {string}
     */
    Stage: "PICKED" | "WORKTREE" | "IMPLEMENTING" | "VERIFYING" | "PR_OPEN" | "REPORTED" | "FAILED";
    /** @enum {string} */
    StepKey: "pick" | "worktree" | "implement" | "verify" | "pr";
    /** @enum {string} */
    StepStatus: "running" | "ok" | "failed";
    /**
     * SummaryLine
     * @description One line of a session summary and the event it comes from.
     */
    SummaryLine: {
      event_id: components["schemas"]["EventId"];
      /** Text */
      text: string;
    };
    /** @enum {string} */
    TileGroup: "waiting" | "live" | "idle" | "ended_recently";
    /**
     * TimelineEvent
     * @description One stored event as the timeline and Raw events show it.
     *
     *     ``fact_key`` groups copies of the same fact from several sources; ``merged_sources`` lists
     *     them on the winner; a loser has ``conflict`` set (D16). ``latency_ms`` is ``received_at``
     *     minus ``timestamp`` when both exist.
     */
    TimelineEvent: {
      /** Agent */
      agent: string | null;
      /**
       * Conflict
       * @default false
       */
      conflict: boolean;
      event_id: components["schemas"]["EventId"];
      /** Fact Key */
      fact_key?: string | null;
      /** Latency Ms */
      latency_ms: number | null;
      /**
       * Merged Sources
       * @default []
       */
      merged_sources: components["schemas"]["EventSource"][];
      /** Payload */
      payload: {
        [key: string]: components["schemas"]["JsonValue"];
      };
      /** Project */
      project: string;
      received_at: components["schemas"]["ApiTimestamp"] | null;
      /** Repo */
      repo: string | null;
      /** Seq */
      seq: number;
      /** Session */
      session: string;
      source: components["schemas"]["EventSource"];
      /** Source Id */
      source_id: string;
      /** Step */
      step: string | null;
      timestamp: components["schemas"]["ApiTimestamp"];
      type: components["schemas"]["EventType"];
      /** Workflow */
      workflow: string | null;
    };
    /**
     * TokenUsage
     * @description Tokens counted from transcript usage, once per message id.
     */
    TokenUsage: {
      /** Cache Read */
      cache_read: number;
      /** Cache Write */
      cache_write: number;
      /** Input */
      input: number;
      /** Output */
      output: number;
    };
    /**
     * TrackerView
     * @description The project's tracker settings from ``hub.json``.
     */
    TrackerView: {
      /** Failed Label */
      failed_label: string | null;
      /** Kind */
      kind: string;
      /** Ready Label */
      ready_label: string | null;
      /** Teams */
      teams: string[];
    };
    /**
     * TurnCost
     * @description Tokens and estimated cost of one turn.
     */
    TurnCost: {
      /** Cache Read */
      cache_read: number;
      /** Cache Write */
      cache_write: number;
      cost_usd: components["schemas"]["Money"] | null;
      /** Input */
      input: number;
      /** Output */
      output: number;
      /** Turn */
      turn: number;
    };
    /** Format: date-time */
    UtcTimestamp: string;
    /**
     * ValidationProblem
     * @description One problem of a hub's ``hub.json``, located by a JSON pointer.
     */
    ValidationProblem: {
      /** Message */
      message: string;
      /** Pointer */
      pointer: string;
    };
    /** @enum {string} */
    Verdict: "SHIP" | "SHIP-WITH-OWNER-STEPS" | "NO-SHIP";
    /**
     * WorkflowRun
     * @description A run folded from executor events (D9, D16): the first ``run.end`` wins.
     */
    WorkflowRun: {
      caps: components["schemas"]["RunCaps"] | null;
      /** Cost Source */
      cost_source?: ("sessions" | "executor") | null;
      cost_usd: components["schemas"]["Money"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      ended_at: components["schemas"]["ApiTimestamp"] | null;
      failure: components["schemas"]["RunFailure"] | null;
      /**
       * Gate Results
       * @default []
       */
      gate_results: components["schemas"]["RunGateResult"][];
      /** Id */
      id: string;
      issue: components["schemas"]["IssueRef"] | null;
      last_activity_at: components["schemas"]["ApiTimestamp"];
      /** Mode */
      mode: ("live" | "dry_run") | null;
      /** Pr Url */
      pr_url?: string | null;
      /** Project */
      project: string;
      /** Repo */
      repo: string | null;
      /**
       * Session Ids
       * @default []
       */
      session_ids: string[];
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      stage: components["schemas"]["Stage"];
      started_at: components["schemas"]["ApiTimestamp"];
      /** Steps */
      steps: components["schemas"]["RunStep"][];
      /** Workflow */
      workflow: string;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  list_activity_api_v1_activity_get: {
    parameters: {
      query?: {
        project?: string | null;
        cursor?: string | null;
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_ActivityItem_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_approvals_api_v1_approvals_get: {
    parameters: {
      query?: {
        project?: string | null;
        kind?: components["schemas"]["ApprovalKind"] | null;
        status?: "open" | "decided" | "all";
        cursor?: string | null;
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_Approval_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_approval_api_v1_approvals__approval_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        approval_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Approval"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_collector_status_api_v1_collector_status_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["CollectorStatus"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_doctor_findings_api_v1_doctor_findings_get: {
    parameters: {
      query?: {
        project?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_FindingView_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  post_hook_api_v1_events_hooks_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["HookEnvelope"];
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HookAccepted"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  stream_events_api_v1_events_stream_get: {
    parameters: {
      query?: {
        project?: string | null;
      };
      header?: {
        "Last-Event-ID"?: string | null;
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Server-Sent Events: heartbeat, counts, collector */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "text/event-stream": string;
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_features_api_v1_features_get: {
    parameters: {
      query?: {
        project?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_FeatureView_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_feature_api_v1_features__project___slug__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        slug: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FeatureDetail"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_hubs_api_v1_hubs_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_HubView_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  register_hub_api_v1_hubs_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["HubCreate"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HubView"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  remove_hub_api_v1_hubs__hub_id__delete: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        hub_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_learnings_api_v1_learnings_get: {
    parameters: {
      query?: {
        project?: string | null;
        status?: components["schemas"]["LearningStatus"] | null;
        cursor?: string | null;
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_Learning_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_learning_api_v1_learnings__learning_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        learning_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Learning"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_live_sessions_api_v1_live_sessions_get: {
    parameters: {
      query?: {
        project?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_LiveTile_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  stream_live_sessions_api_v1_live_sessions_stream_get: {
    parameters: {
      query?: {
        project?: string | null;
      };
      header?: {
        "Last-Event-ID"?: string | null;
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Server-Sent Events: tile.upsert, tile.remove, heartbeat */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "text/event-stream": string;
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_needs_you_api_v1_needs_you_get: {
    parameters: {
      query?: {
        project?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_NeedsYouItem_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_projects_api_v1_projects_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_ProjectSummary_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_project_api_v1_projects__project__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProjectDetail"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_project_now_api_v1_projects__project__now_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProjectNow"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_project_repos_api_v1_projects__project__repos_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_RepoView_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  search_api_v1_search_get: {
    parameters: {
      query: {
        q: string;
        project?: string | null;
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_SearchHit_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_sessions_api_v1_sessions_get: {
    parameters: {
      query?: {
        project?: string | null;
        repo?: string | null;
        agent?: string | null;
        status?: components["schemas"]["SessionStatus"] | null;
        outcome?: components["schemas"]["Outcome"] | null;
        workflow?: string | null;
        run_id?: string | null;
        from?: string | null;
        to?: string | null;
        cost_min?: number | string | null;
        cost_max?: number | string | null;
        file?: string | null;
        tool?: string | null;
        guard_denial?: boolean | null;
        sort?:
          | "started_at"
          | "-started_at"
          | "last_activity_at"
          | "-last_activity_at"
          | "cost"
          | "-cost";
        cursor?: string | null;
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_Session_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_session_api_v1_sessions__session_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Session"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_session_cost_api_v1_sessions__session_id__cost_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SessionCost"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_session_events_api_v1_sessions__session_id__events_get: {
    parameters: {
      query?: {
        types?: components["schemas"]["EventType"][] | null;
        cursor?: string | null;
        limit?: number;
      };
      header?: never;
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_TimelineEvent_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  stream_session_events_api_v1_sessions__session_id__events_stream_get: {
    parameters: {
      query?: never;
      header?: {
        "Last-Event-ID"?: string | null;
      };
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Server-Sent Events: event, session, end, heartbeat */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "text/event-stream": string;
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_session_files_api_v1_sessions__session_id__files_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_SessionFileChange_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_session_summary_api_v1_sessions__session_id__summary_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SessionSummary"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_settings_api_v1_settings_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SettingsView"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  list_runs_api_v1_workflow_runs_get: {
    parameters: {
      query?: {
        project?: string | null;
        repo?: string | null;
        stage?: components["schemas"]["Stage"] | null;
        outcome?: ("done" | "failed") | null;
        failure_stage?: components["schemas"]["Stage"] | null;
        mode?: ("live" | "dry_run") | null;
        issue?: string | null;
        cursor?: string | null;
        limit?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page_WorkflowRun_"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  get_run_api_v1_workflow_runs__run_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["WorkflowRun"];
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
  stream_run_api_v1_workflow_runs__run_id__stream_get: {
    parameters: {
      query?: never;
      header?: {
        "Last-Event-ID"?: string | null;
      };
      path: {
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Server-Sent Events: run, step, gate, heartbeat */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "text/event-stream": string;
        };
      };
      /** @description A client error, as an RFC 9457 problem */
      "4XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description A server error, as an RFC 9457 problem */
      "5XX": {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
    };
  };
}
