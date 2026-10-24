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
  "/api/v1/agent-sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Agent Sessions
     * @description Agent sessions, newest first; with ``wrote``, the ones that changed that file (a path
     *     relative to any workdir, such as ``brain/features/<slug>/spec.md``).
     */
    get: operations["list_agent_sessions_api_v1_agent_sessions_get"];
    put?: never;
    /**
     * Create Agent Session
     * @description Start a session in a listed workdir, optionally with a first prompt or a resume.
     */
    post: operations["create_agent_session_api_v1_agent_sessions_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/capabilities": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Capabilities
     * @description Whether sessions can start on this machine (and why not), the models, the cloud.
     */
    get: operations["get_capabilities_api_v1_agent_sessions_capabilities_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/cloud": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Cloud Sessions
     * @description The cloud sessions started from here, newest first, at most 50.
     */
    get: operations["list_cloud_sessions_api_v1_agent_sessions_cloud_get"];
    put?: never;
    /**
     * Start Cloud Session
     * @description Start a cloud session with a task; answers its claude.ai/code link and teleport command.
     */
    post: operations["start_cloud_session_api_v1_agent_sessions_cloud_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/cloud/{cloud_id}/messages": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Follow Up Cloud Session
     * @description Send one follow-up message to a cloud session (cloud: limited control).
     */
    post: operations["follow_up_cloud_session_api_v1_agent_sessions_cloud__cloud_id__messages_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/resumable": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Resumable
     * @description Past Claude sessions of a workdir that can be resumed or forked.
     */
    get: operations["list_resumable_api_v1_agent_sessions_resumable_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/workdirs": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Workdirs
     * @description The folders a session may start in: the hub, its repos and their worktrees (D6).
     */
    get: operations["list_workdirs_api_v1_agent_sessions_workdirs_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Agent Session
     * @description One session, with the permission request it waits on while live.
     */
    get: operations["get_agent_session_api_v1_agent_sessions__agent_session_id__get"];
    put?: never;
    post?: never;
    /**
     * Delete Agent Session
     * @description Remove an ended session and its stored conversation.
     */
    delete: operations["delete_agent_session_api_v1_agent_sessions__agent_session_id__delete"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/close": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Close Agent Session
     * @description End the session; its log is kept and it can be resumed.
     */
    post: operations["close_agent_session_api_v1_agent_sessions__agent_session_id__close_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/events": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Agent Session Events
     * @description The stored log after ``after``, in ``seq`` order (redacted).
     */
    get: operations["list_agent_session_events_api_v1_agent_sessions__agent_session_id__events_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/interrupt": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Interrupt Agent Session
     * @description Interrupt the running turn; its result follows on the stream.
     */
    post: operations["interrupt_agent_session_api_v1_agent_sessions__agent_session_id__interrupt_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/messages": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Send Agent Session Message
     * @description Send a message; it plays after the running turn.
     */
    post: operations["send_agent_session_message_api_v1_agent_sessions__agent_session_id__messages_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/permissions/{request_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Answer Agent Session Permission
     * @description Answer a permission request: allow, deny (with a message) or always (a suggestion).
     */
    post: operations["answer_agent_session_permission_api_v1_agent_sessions__agent_session_id__permissions__request_id__post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/repo-changes": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Agent Session Repo Changes
     * @description What the repositories the session worked in change against their base branch, as git
     *     reads them: the pull request's files, whoever changed them.
     */
    get: operations["get_agent_session_repo_changes_api_v1_agent_sessions__agent_session_id__repo_changes_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/repo-changes/commit": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Agent Session Repo Commit Diff
     * @description What one commit changed in one file of the session's repositories (``path`` absolute,
     *     ``old_path`` its name before a rename).
     */
    get: operations["get_agent_session_repo_commit_diff_api_v1_agent_sessions__agent_session_id__repo_changes_commit_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/repo-changes/file": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Agent Session Repo File
     * @description One file of the session's repositories (``path`` absolute) as commit ``sha`` has it: the
     *     lines a review expands around a pull request's diff.
     */
    get: operations["get_agent_session_repo_file_api_v1_agent_sessions__agent_session_id__repo_changes_file_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/settings": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Change Agent Session Settings
     * @description Change the permission mode or the model.
     */
    post: operations["change_agent_session_settings_api_v1_agent_sessions__agent_session_id__settings_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/stream": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Stream Agent Session
     * @description The session's records and deltas as they happen, after a replay from the position.
     */
    get: operations["stream_agent_session_api_v1_agent_sessions__agent_session_id__stream_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agent-sessions/{agent_session_id}/tasks/{task_id}/stop": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Stop Agent Session Task
     * @description Stop a background task (an agent or a command); its end follows on the stream.
     */
    post: operations["stop_agent_session_task_api_v1_agent_sessions__agent_session_id__tasks__task_id__stop_post"];
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
     * @description Approvals, oldest first; an engine run's open gate names its kind (``gate_kind``) when
     *     its run's record does.
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
  "/api/v1/approvals/{approval_id}/decision": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Decide Gate
     * @description Record a person's answer to an open workflow gate, then resume its run; its events tell
     *     the rest.
     */
    post: operations["decide_gate_api_v1_approvals__approval_id__decision_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/approvals/{approval_id}/gate": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Gate
     * @description What answers an open workflow gate: its decisions or options and whether it takes text.
     */
    get: operations["get_gate_api_v1_approvals__approval_id__gate_get"];
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
  "/api/v1/feature-names": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Feature Names
     * @description The nicknames the owner gave features on this machine (the slug stays the identity).
     */
    get: operations["list_feature_names_api_v1_feature_names_get"];
    /**
     * Set Feature Name
     * @description Give a feature a nickname, or clear it with an empty name.
     */
    put: operations["set_feature_name_api_v1_feature_names_put"];
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
     * @description One feature with its acceptance criteria; each open change request carries the open gate
     *     of its run that answers it (``approval_id``), and whether its run is gone, so hub web
     *     decides it (``decidable_here``); ``cost`` adds up what its sessions cost.
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
  "/api/v1/features/{project}/{slug}/acs/{ac}/check-runs": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Run Ac Check
     * @description Run the check ``features.json`` records for one AC in its repo's checkout and answer its
     *     exit code and output (nothing is recorded; 409 for a manual AC or one with no command).
     */
    post: operations["run_ac_check_api_v1_features__project___slug__acs__ac__check_runs_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/features/{project}/{slug}/change-requests/{n}/decision": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Decide Change Request
     * @description The owner decides a plan change request whose run is gone (lost, or ended, and held by no
     *     child): creates ``change-requests/<n>.decision.md`` once with the hub's person as
     *     ``decided_by``, never editing the request; the next ``/implement`` of its ticket reads it.
     *     409 while the run's gate is open (answer it through ``approval_id``), while the run lives,
     *     once decided, or with no person to record; 422 for a decline without a note.
     */
    post: operations["decide_change_request_api_v1_features__project___slug__change_requests__n__decision_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/features/{project}/{slug}/owner-signoff": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Sign Off Owner Steps
     * @description The owner settles the owner steps. Without a body: writes an ``owner-signoff`` SHIP eval
     *     over the ACs the Acceptance step waits on; 409 with a one-line reason, writing nothing, when
     *     none waits or the feature lists no AC, when one of them has a NO-SHIP as its latest eval, when
     *     the acceptance eval is undated or future-dated, or when not every eval was read. With
     *     ``delivery``, settles that SHIP-WITH-OWNER-STEPS eval only: ``decision`` ``done`` writes a SHIP
     *     over its waiting ACs, ``more_work`` a NO-SHIP; ``note`` is the owner's words. A ``delivery``
     *     naming the acceptance eval covers what the Acceptance step waits on, with the no-body
     *     refusals, except that ``more_work`` is not refused over ACs an agent's eval reopened; either
     *     decision there is refused once an owner decision newer than the acceptance eval settled it
     *     (its SHIP signed every waiting AC off, or its NO-SHIP is still the latest eval of one). With
     *     ``acs``, signs off those criteria as checked by hand (AGH-425), with the same refusals over
     *     them: an unknown AC, a NO-SHIP as the latest eval of one (``done``), an eval naming one that
     *     the note would not rank newer than, evals left unread.
     */
    post: operations["sign_off_owner_steps_api_v1_features__project___slug__owner_signoff_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/features/{project}/{slug}/tickets": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Feature Tickets
     * @description One feature's tickets with their planning and golden path; Linear when connected, else
     *     the plan with a notice (always 200 for a known feature).
     */
    get: operations["get_feature_tickets_api_v1_features__project___slug__tickets_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/features/{project}/{slug}/tickets/{ticket}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Ticket Records
     * @description One ticket's records the ticket panel shows: its context brief and ticket plan, every
     *     preflight run (local notes, discoveries) and the change requests it asks or is held by, each
     *     open one with its run's open gate; 404 when the feature does not list the ticket.
     */
    get: operations["get_ticket_records_api_v1_features__project___slug__tickets__ticket__get"];
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
  "/api/v1/hubs/{hub_id}/doctor-fix": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Fix Hub Findings
     * @description Run ``hub doctor --fix`` in the hub: every auto-fixable finding; nothing committed.
     */
    post: operations["fix_hub_findings_api_v1_hubs__hub_id__doctor_fix_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/hubs/{hub_id}/platform-sync": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Sync Hub Platform
     * @description Pin the hub to the running release and run ``hub sync`` in it; nothing is committed.
     */
    post: operations["sync_hub_platform_api_v1_hubs__hub_id__platform_sync_post"];
    delete?: never;
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
     * @description Learnings, newest first, each with its note's summary or why the note is unavailable;
     *     with ``brain_path`` (with or without ``brain/``), only those whose note is that one.
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
     * @description One learning with its note, the suggested target and the target choices.
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
  "/api/v1/learnings/{learning_id}/accept": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Accept Learning
     * @description Open a hub PR that moves the note into the brain, with the edited body when one is sent;
     *     nothing changes until it is merged.
     */
    post: operations["accept_learning_api_v1_learnings__learning_id__accept_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/learnings/{learning_id}/reject": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Reject Learning
     * @description Open a hub PR that archives the note with the reason.
     */
    post: operations["reject_learning_api_v1_learnings__learning_id__reject_post"];
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
  "/api/v1/projects/{project}/actions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Actions
     * @description The hub's actions (the builder's palette), with output fields and their scenarios.
     */
    get: operations["list_actions_api_v1_projects__project__actions_get"];
    put?: never;
    /**
     * Post Action
     * @description Writes a new action (its document and its script) into the hub as a draft: a strict
     *     write that needs the launch cookie; it runs nothing and commits nothing.
     */
    post: operations["post_action_api_v1_projects__project__actions_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/actions/{pack}/{name}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /**
     * Put Action
     * @description Rewrites an action of the hub (its document and its script): a strict write; the
     *     action is a draft until it is committed again.
     */
    put: operations["put_action_api_v1_projects__project__actions__pack___name__put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/brain": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Brain Tree
     * @description The ``.md`` notes of the project's hub brain (``auto/`` excluded).
     */
    get: operations["get_brain_tree_api_v1_projects__project__brain_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/brain/backlinks": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Brain Backlinks
     * @description The documents linking to the note at ``path`` under ``brain/``, by path, at most 100,
     *     with the full count; the note need not exist.
     */
    get: operations["get_brain_backlinks_api_v1_projects__project__brain_backlinks_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/brain/note": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Brain Note
     * @description One brain note by its path under ``brain/``: frontmatter, markdown body and size.
     */
    get: operations["get_brain_note_api_v1_projects__project__brain_note_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/config": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Project Config
     * @description The project's hub config: team (``hub.json``) and local (``hub.local.json``) values.
     */
    get: operations["get_project_config_api_v1_projects__project__config_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/config/environments": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Post Project Environment Edit
     * @description Add, change or remove an environment or a service endpoint, in ``hub.json`` (the team's,
     *     left uncommitted) or ``hub.local.json`` (this developer's), as ``hub env`` does.
     */
    post: operations["post_project_environment_edit_api_v1_projects__project__config_environments_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/config/local": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /**
     * Put Project Local Config
     * @description Save this developer's ``hub.local.json`` values; the team's ``hub.json`` is untouched.
     */
    put: operations["put_project_local_config_api_v1_projects__project__config_local_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/env-file-keys": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Env File Keys
     * @description The variable NAMES an env file holds, never a value: only a regular file of at most
     *     64 KiB inside the hub or one of its repos, with whether git ignores it there.
     */
    get: operations["get_env_file_keys_api_v1_projects__project__env_file_keys_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/environment-discoveries": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Environment Discoveries
     * @description The project's discoveries not discarded, newest first.
     */
    get: operations["list_environment_discoveries_api_v1_projects__project__environment_discoveries_get"];
    put?: never;
    /**
     * Start Environment Discovery
     * @description Start a read-only Claude session that reads the picked repos and proposes environments,
     *     services and addresses; 422 naming each repo or environment the config does not hold.
     */
    post: operations["start_environment_discovery_api_v1_projects__project__environment_discoveries_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/environment-discoveries/{discovery_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Environment Discovery
     * @description One discovery: its session's state and, once Claude finished, the checked proposal with
     *     each item's status against the config of now.
     */
    get: operations["get_environment_discovery_api_v1_projects__project__environment_discoveries__discovery_id__get"];
    put?: never;
    post?: never;
    /**
     * Discard Environment Discovery
     * @description Discard a discovery (its session is ended when it still works).
     */
    delete: operations["discard_environment_discovery_api_v1_projects__project__environment_discoveries__discovery_id__delete"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/knowledge/search": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Search Project Knowledge
     * @description The hub's notes and repo docs holding every word of ``q``, best first, after the index
     *     is brought up to date with the checkout; ``q``'s words only, never search syntax.
     */
    get: operations["search_project_knowledge_api_v1_projects__project__knowledge_search_get"];
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
  "/api/v1/projects/{project}/scenarios/validate": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Validate Scenario
     * @description The scenario builder's check: the document as the YAML Save would write, whether it
     *     loads, and each problem on its node. Writes nothing.
     */
    post: operations["validate_scenario_api_v1_projects__project__scenarios_validate_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/skills": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Skill Catalog
     * @description The project's skills, agents and hooks, with 30-day usage and third-party plugins.
     */
    get: operations["get_skill_catalog_api_v1_projects__project__skills_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/skills/drafts/{draft_id}/publish": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Publish Draft
     * @description Land the Studio draft on its target (``null``: a new item), record a ``publish``
     *     version naming the draft, then remove the draft.
     */
    post: operations["publish_draft_api_v1_projects__project__skills_drafts__draft_id__publish_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/skills/{kind}/{source}/{name}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Skill Detail
     * @description One skill, agent or hook by its id: header fields, text, structure, relations, files.
     */
    get: operations["get_skill_detail_api_v1_projects__project__skills__kind___source___name__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/files/{file_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Skill File
     * @description One bundled file of a skill by the id its detail issued; its text is inert.
     */
    get: operations["get_skill_file_api_v1_projects__project__skills__kind___source___name__files__file_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/versions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Skill Versions
     * @description The versions of the item's unit, newest first, and what its disk holds now.
     */
    get: operations["list_skill_versions_api_v1_projects__project__skills__kind___source___name__versions_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/versions/{version_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Skill Version
     * @description One version of the item's unit: its files, their texts and executable bits.
     */
    get: operations["get_skill_version_api_v1_projects__project__skills__kind___source___name__versions__version_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/versions/{version_id}/restore": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Restore Skill Version
     * @description Write the version back into the hub and record a ``restore`` version naming it.
     */
    post: operations["restore_skill_version_api_v1_projects__project__skills__kind___source___name__versions__version_id__restore_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenario-runs/{run_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Scenario Run
     * @description A scenario run as its record holds it: timeline, polls, captures, decisions, findings,
     *     investigations, the latest proposal's options and the workarounds.
     */
    get: operations["get_scenario_run_api_v1_scenario_runs__run_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenario-runs/{run_id}/answer": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Answer Investigation
     * @description Answer the open investigation (pick an option, retry the step or stop the run), then
     *     resume the run; a pick that cannot stand is 409 with its reason and records nothing.
     */
    post: operations["answer_investigation_api_v1_scenario_runs__run_id__answer_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenario-runs/{run_id}/findings/{finding_id}/inbox": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Finding Inbox
     * @description Write the finding as a ``brain/_inbox/`` note (``provenance: agent-from-external``),
     *     never over another.
     */
    post: operations["finding_inbox_api_v1_scenario_runs__run_id__findings__finding_id__inbox_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenario-runs/{run_id}/findings/{finding_id}/issue": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Finding Issue
     * @description A finding's tracker issue draft; with ``confirm: true``, the issue created once (201).
     */
    post: operations["finding_issue_api_v1_scenario_runs__run_id__findings__finding_id__issue_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenario-runs/{run_id}/investigation": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Open Investigation
     * @description Start the investigation session of a scenario run paused at an open investigation, or
     *     answer the one already started (200); 409 when the run is not paused there.
     */
    post: operations["open_investigation_api_v1_scenario_runs__run_id__investigation_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenarios": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Scenarios
     * @description The scenarios of every (or one) project, each with its last scenario run, and the
     *     files that do not load.
     */
    get: operations["list_scenarios_api_v1_scenarios_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenarios/{project}/{name}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Scenario
     * @description One scenario: its steps and its scenario runs, newest first.
     */
    get: operations["get_scenario_api_v1_scenarios__project___name__get"];
    /**
     * Save Scenario
     * @description Write the scenario file from the builder's document (a strict write that needs the
     *     launch cookie): only a document that loads, over the file the builder last read
     *     (409 ``stale_document`` else), recorded as a version; no git command runs.
     */
    put: operations["save_scenario_api_v1_scenarios__project___name__put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenarios/{project}/{name}/plan": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Plan Scenario
     * @description What each step would do in the environment, and the policy's decision; nothing runs
     *     but the scripts' plan mode, with no credential and only when a step's args are known.
     */
    post: operations["plan_scenario_api_v1_scenarios__project___name__plan_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenarios/{project}/{name}/proposal": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Proposal
     * @description Claude's proposal for the scenario (a file in the hub's ignored ``.agent-runs/``),
     *     checked as Save would check it; 404 when there is none.
     */
    get: operations["get_proposal_api_v1_scenarios__project___name__proposal_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenarios/{project}/{name}/proposal/dismiss": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Delete Proposal
     * @description Removes Claude's proposal once the owner accepted it into the draft or rejected it.
     */
    post: operations["delete_proposal_api_v1_scenarios__project___name__proposal_dismiss_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/scenarios/{project}/{name}/runs": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Start Scenario
     * @description Start a scenario run once its plan holds no problem and no deny (409 naming the denied
     *     steps, no run created); its events tell the rest.
     */
    post: operations["start_scenario_api_v1_scenarios__project___name__runs_post"];
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
  "/api/v1/sessions/{session_id}/problems": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Session Problems
     * @description The session's problems: up to 5 summary lines (none if all went well), then each by time.
     */
    get: operations["get_session_problems_api_v1_sessions__session_id__problems_get"];
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
  "/api/v1/skill-usage": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Skill Usage
     * @description The skills and agents of every (or one) project's hub, never used in ``days`` first.
     */
    get: operations["get_skill_usage_api_v1_skill_usage_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/tracker/linear": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Linear Connection
     * @description Whether hub web reads Linear, as whom, or why not (checked against Linear).
     */
    get: operations["get_linear_connection_api_v1_tracker_linear_get"];
    /**
     * Connect Linear
     * @description Check a Linear API key and save it on this machine when Linear accepts it.
     */
    put: operations["connect_linear_api_v1_tracker_linear_put"];
    post?: never;
    /**
     * Disconnect Linear
     * @description Forget the key saved from Settings.
     */
    delete: operations["disconnect_linear_api_v1_tracker_linear_delete"];
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
     * @description Workflow runs matching the filters, newest first; ``kind`` keeps scenario runs or
     *     workflow runs only (absent: both).
     */
    get: operations["list_runs_api_v1_workflow_runs_get"];
    put?: never;
    /**
     * Start Run
     * @description Start a project's workflow as a ``hub workflow run`` child; its events tell its status.
     */
    post: operations["start_run_api_v1_workflow_runs_post"];
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
     * @description One workflow run with its steps, and the environment its record names (when any).
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
  "/api/v1/workflow-runs/{run_id}/abandon": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Abandon Run
     * @description End a failed or unended run cancelled.
     */
    post: operations["abandon_run_api_v1_workflow_runs__run_id__abandon_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflow-runs/{run_id}/cancel": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Cancel Run
     * @description Stop the run's child (SIGINT, then SIGKILL), then end the run cancelled.
     */
    post: operations["cancel_run_api_v1_workflow_runs__run_id__cancel_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflow-runs/{run_id}/resume": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Resume Run
     * @description Continue a failed or unended run in a new child, reusing what completed.
     */
    post: operations["resume_run_api_v1_workflow_runs__run_id__resume_post"];
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
  "/api/v1/workflows": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Workflows
     * @description The workflows of every (or one) project, and the files that do not load.
     */
    get: operations["list_workflows_api_v1_workflows_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflows/{project}/{name}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Workflow
     * @description One workflow: its document and its layers.
     */
    get: operations["get_workflow_api_v1_workflows__project___name__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflows/{project}/{name}/versions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Workflow Versions
     * @description The versions of the hub workflow's file, newest first, and what the disk holds now.
     */
    get: operations["list_workflow_versions_api_v1_workflows__project___name__versions_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflows/{project}/{name}/versions/{version_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Workflow Version
     * @description One version of the hub workflow's file.
     */
    get: operations["get_workflow_version_api_v1_workflows__project___name__versions__version_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/workflows/{project}/{name}/versions/{version_id}/restore": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Restore Workflow Version
     * @description Write the version back into the hub workflow's file and record a ``restore`` version.
     */
    post: operations["restore_workflow_version_api_v1_workflows__project___name__versions__version_id__restore_post"];
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
     * AcCheckRun
     * @description One run of an AC's check: what ran, where, and what it answered.
     */
    AcCheckRun: {
      /** Ac */
      ac: string;
      /** Branch */
      branch: string | null;
      /** Command */
      command: string;
      /** Commit */
      commit: string | null;
      /** Duration Ms */
      duration_ms: number;
      /** Exit Code */
      exit_code: number | null;
      /** Output */
      output: string;
      /** Passed */
      passed: boolean;
      /** Repo */
      repo: string;
      /** Timed Out */
      timed_out: boolean;
      /** Truncated */
      truncated: boolean;
    };
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
     * @description One acceptance criterion of ``features.json``; ``signed_off`` when it does not pass there
     *     but the owner's latest eval of it (``provenance: owner``) says SHIP: checked by hand.
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
      /**
       * Signed Off
       * @default false
       */
      signed_off: boolean;
    };
    /**
     * AcceptLearningBody
     * @description ``POST /learnings/{learning_id}/accept``: the brain folder (or ``.md`` path) to move the
     *     note to, relative to ``brain/``, and optionally the note's edited text after its frontmatter
     *     (the frontmatter itself is kept; ``status`` and ``last_verified`` are set as for any accept).
     */
    AcceptLearningBody: {
      /** Note Body */
      note_body?: string | null;
      /** Target */
      target: string;
    };
    /**
     * AcceptanceEval
     * @description The feature's acceptance eval (AC-1.6): the latest whole-feature eval (``acs: all``, or a
     *     legacy ``eval.md`` with no scope), by its ``delivery`` (``legacy`` for ``eval.md``);
     *     ``owner_wait`` is None when it waits on no owner decision the app can take.
     */
    AcceptanceEval: {
      /** Delivery */
      delivery: string;
      owner_wait?: components["schemas"]["OwnerWaitView"] | null;
      verdict: components["schemas"]["Verdict"];
    };
    /** @enum {string} */
    Access: "read" | "write" | "ask";
    /**
     * ActionCallEntry
     * @description An action call's policy facts, from its record line: never its inputs or output.
     */
    ActionCallEntry: {
      /** Action */
      action: string | null;
      /** Approver */
      approver: string | null;
      /** At */
      at: string | null;
      /** Attempt */
      attempt: number | null;
      /** Content Hash */
      content_hash: string | null;
      /** Decision */
      decision: string | null;
      /** Effect */
      effect: string | null;
      /** Failure Kind */
      failure_kind: string | null;
      /** Node */
      node: string;
      /** Origin */
      origin: string | null;
      /** Poll */
      poll: number | null;
      /** Reason Kind */
      reason_kind: string | null;
      /** Status */
      status: string | null;
    };
    /** ActionInputDraft */
    ActionInputDraft: {
      /** Description */
      description?: string | null;
      /** Name */
      name: string;
      /**
       * Required
       * @default false
       */
      required: boolean;
      /**
       * Type
       * @default string
       * @enum {string}
       */
      type: "string" | "integer" | "number" | "boolean" | "service";
    };
    /**
     * ActionInputSpec
     * @description An action input as its document declares it.
     */
    ActionInputSpec: {
      default?: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
      /** Description */
      description?: string | null;
      /** Name */
      name: string;
      /** Required */
      required: boolean;
      /** Type */
      type: string;
    };
    /** ActionLibrary */
    ActionLibrary: {
      /** Items */
      items: components["schemas"]["LibraryAction"][];
      /** Problems */
      problems: string[];
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
    /**
     * Actor
     * @description Who acted in a session (S2): the main agent, or a subagent of a type.
     *
     *     A subagent carries its ``agent_id`` and, when its start is linked to the main agent's
     *     Agent tool call, that call's ``description`` and ``started_by_event_id``.
     */
    Actor: {
      /** Agent Id */
      agent_id?: string | null;
      /** Description */
      description?: string | null;
      kind: components["schemas"]["ActorKind"];
      started_by_event_id?: components["schemas"]["EventId"] | null;
      /** Type */
      type?: string | null;
    };
    /** @enum {string} */
    ActorKind: "main" | "subagent";
    /**
     * AddEndpoint
     * @description A service's endpoint in one environment; the service is added when new.
     */
    AddEndpoint: {
      /** Environment */
      environment: string;
      /** Kind */
      kind?: string | null;
      /** Note */
      note?: string | null;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "add_endpoint";
      /**
       * Replace
       * @default false
       */
      replace: boolean;
      /** Repo */
      repo: string;
      /** Resource */
      resource?: string | null;
      scope: components["schemas"]["Scope"];
      /** Service */
      service: string;
      /** Url */
      url?: string | null;
    };
    /**
     * AddEnvironment
     * @description A new environment, with its credentials by name only.
     */
    AddEnvironment: {
      access: components["schemas"]["Access"];
      /** Aws Profile */
      aws_profile?: string | null;
      /**
       * Credential Env
       * @default []
       */
      credential_env: string[];
      /** Description */
      description?: string | null;
      /** Env File */
      env_file?: string | null;
      /** Name */
      name: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "add_environment";
      /**
       * Production
       * @default false
       */
      production: boolean;
      scope: components["schemas"]["Scope"];
      /** Values */
      values?: {
        [key: string]: string;
      };
    };
    /**
     * AddService
     * @description A new service of a repo with its address in one or more environments, in one step.
     *
     *     Each address goes to the file of its environment: a team environment's to ``hub.json``, the
     *     developer's own to ``hub.local.json``; both files are checked before either is written.
     */
    AddService: {
      /** Addresses */
      addresses: components["schemas"]["ServiceAddress"][];
      /** Description */
      description?: string | null;
      /** Kind */
      kind?: string | null;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "add_service";
      /** Repo */
      repo: string;
      /** Service */
      service: string;
    };
    /**
     * AgentModelView
     * @description A plugin agent's tier, when ``models.agents`` moves it off its template's.
     */
    AgentModelView: {
      /** Agent */
      agent: string;
      /** Tier */
      tier: string;
    };
    /**
     * AgentSession
     * @description One session ``hub web`` started (or one cloud start, ``kind="cloud"``).
     *
     *     ``claude_session_id`` links it to the hook-observed Session once ``init`` arrives (or at
     *     start when the id is given, P13); ``observed_session_id`` is that Session's id once it has
     *     been observed, else ``null`` (a twin may never arrive, D2). ``last_seq`` is the last
     *     persisted record's ``seq``. ``cost_usd`` and ``usage`` add up the turns' results (an estimate).
     *     ``last_prompt`` and ``last_reply`` are the latest ``user.message`` and assistant ``text`` of
     *     the stored (redacted) log as one line of at most 280 characters, the reply's markdown
     *     marks dropped; ``changed_files`` the files changed, latest change first, at most 200
     *     (``digest``). ``tool_access`` is the tools it may use, kept so a reopened session keeps
     *     them; it is the server's own (``exclude``: never in an answer, so the contract is unchanged).
     */
    AgentSession: {
      /**
       * Changed Files
       * @default []
       */
      changed_files: components["schemas"]["ChangedFile"][];
      /** Claude Session Id */
      claude_session_id?: string | null;
      /** Cloud Id */
      cloud_id?: string | null;
      cost_usd?: components["schemas"]["Money"] | null;
      created_at: components["schemas"]["ApiTimestamp"];
      end_reason?: components["schemas"]["EndReason"] | null;
      ended_at?: components["schemas"]["ApiTimestamp"] | null;
      /** Id */
      id: string;
      /** @default local */
      kind: components["schemas"]["AgentSessionKind"];
      /** Last Prompt */
      last_prompt?: string | null;
      /** Last Reply */
      last_reply?: string | null;
      /**
       * Last Seq
       * @default 0
       */
      last_seq: number;
      mode: components["schemas"]["PermissionMode"];
      /** Model */
      model?: string | null;
      /** Observed Session Id */
      observed_session_id?: string | null;
      open_permission?: components["schemas"]["OpenPermission"] | null;
      /** Project */
      project: string;
      /** Restricted */
      restricted?: boolean | null;
      /**
       * Review Targets
       * @default []
       */
      review_targets: components["schemas"]["ReviewTarget"][];
      status: components["schemas"]["AgentSessionStatus"];
      /** Title */
      title?: string | null;
      updated_at: components["schemas"]["ApiTimestamp"];
      /** Url */
      url?: string | null;
      usage?: components["schemas"]["TokenUsage"] | null;
      /** Workdir Id */
      workdir_id: string;
      /** Workdir Label */
      workdir_label: string;
    };
    /** @enum {string} */
    AgentSessionKind: "local" | "cloud";
    /**
     * AgentSessionList
     * @description ``GET /agent-sessions``: newest first.
     */
    AgentSessionList: {
      /** Items */
      items: components["schemas"]["AgentSession"][];
    };
    /**
     * AgentSessionStatus
     * @description Where a session is (P18): ``idle`` between turns, ``running`` in a turn,
     *     ``waiting_permission`` while a request is unanswered; ``ended`` and ``failed`` are final.
     * @enum {string}
     */
    AgentSessionStatus: "running" | "idle" | "waiting_permission" | "ended" | "failed";
    /**
     * AmendmentView
     * @description One ``A<n> (<date>, <who>): <title>`` entry of the plan's ``## Amendments``; ``anchor`` is
     *     the text of that ``## Amendments…`` heading, which the Plan record view links to.
     */
    AmendmentView: {
      /** Anchor */
      anchor: string;
      /** Date */
      date: string;
      /** Id */
      id: string;
      /** Title */
      title: string;
      /** Who */
      who: string;
    };
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
      gate_kind?: components["schemas"]["GateKindName"] | null;
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
     * BrainEntry
     * @description One ``.md`` note of the tree and its size in bytes.
     */
    BrainEntry: {
      /** Path */
      path: string;
      /** Size */
      size: number;
    };
    /**
     * BrainNote
     * @description One note: its frontmatter fields, its markdown body (without the frontmatter) and size.
     *
     *     ``frontmatter_problem`` says why the frontmatter could not be read (then ``frontmatter`` is
     *     empty and ``markdown`` is the whole text).
     */
    BrainNote: {
      /** Frontmatter */
      frontmatter: {
        [key: string]: components["schemas"]["FrontmatterValue"];
      };
      /** Frontmatter Problem */
      frontmatter_problem?: string | null;
      /** Markdown */
      markdown: string;
      /** Path */
      path: string;
      /** Project */
      project: string;
      /** Sha256 */
      sha256?: string | null;
      /** Size */
      size: number;
    };
    /**
     * BrainTree
     * @description The ``.md`` notes of a hub's brain, sorted by path (``auto/`` and hidden names excluded).
     *
     *     ``truncated`` says the listing stopped at a cap; ``skipped`` counts what was left out
     *     (unreadable folders, entries past a cap).
     */
    BrainTree: {
      /** Entries */
      entries: components["schemas"]["BrainEntry"][];
      /** Project */
      project: string;
      /**
       * Skipped
       * @default 0
       */
      skipped: number;
      /**
       * Truncated
       * @default false
       */
      truncated: boolean;
    };
    /**
     * BuilderProblem
     * @description A reason the document does not load (``error``) or will not plan (``warning``), on the
     *     node it names (``node`` None for the document).
     */
    BuilderProblem: {
      /** Key */
      key: string | null;
      /** Line */
      line: number | null;
      /** Message */
      message: string;
      /** Node */
      node: string | null;
      /**
       * Severity
       * @default error
       */
      severity: string;
    };
    /**
     * BundledFile
     * @description A file of a skill folder other than ``SKILL.md`` (S7): ``path`` is relative to the skill
     *     folder, ``id`` server-issued; ``link`` when it is a link (never read), ``too_large`` when over
     *     the per-file cap.
     */
    BundledFile: {
      /** Id */
      id: string;
      /**
       * Link
       * @default false
       */
      link: boolean;
      /** Path */
      path: string;
      role: components["schemas"]["FileRole"];
      /** Size */
      size: number;
      /**
       * Too Large
       * @default false
       */
      too_large: boolean;
    };
    /**
     * BundledFileText
     * @description A bundled file's text, inert (S7); ``binary`` (NUL or not UTF-8) gives no text.
     */
    BundledFileText: {
      /**
       * Binary
       * @default false
       */
      binary: boolean;
      /** Id */
      id: string;
      /** Path */
      path: string;
      role: components["schemas"]["FileRole"];
      /** Size */
      size: number;
      /** Text */
      text: string | null;
    };
    /** CaptureEntry */
    CaptureEntry: {
      /** Attempt */
      attempt: number | null;
      /** Name */
      name: string;
      /** Node */
      node: string;
      value: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
    };
    /**
     * CatalogItem
     * @description One card of the catalog (D3, AC-164.7).
     *
     *     ``description`` is the first line, at most 200 characters; ``invocation`` is
     *     ``/<name> <argument-hint>`` for a skill, None for an agent or a hook; ``mode`` is None for an
     *     agent or a hook; ``usage`` is None for a hook. ``linked_from`` lists the ``.claude/`` links
     *     that point at the item; ``active`` is false for a plugin hook whose plugin is not enabled;
     *     ``state`` is set for hooks only.
     */
    CatalogItem: {
      /**
       * Active
       * @default true
       */
      active: boolean;
      /** Description */
      description: string | null;
      /** Diagnostics Count */
      diagnostics_count: number;
      /** Id */
      id: string;
      /** Invocation */
      invocation: string | null;
      kind: components["schemas"]["ItemKind"];
      /**
       * Linked From
       * @default []
       */
      linked_from: string[];
      mode: components["schemas"]["Mode"] | null;
      /** Name */
      name: string;
      origin: components["schemas"]["Origin"];
      /** Source */
      source: string;
      /** Source Path */
      source_path: string;
      state?: components["schemas"]["HookState"] | null;
      usage: components["schemas"]["Usage"] | null;
    };
    /**
     * ChangeDecisionView
     * @description The owner's decision on a plan change request (``<n>.decision.md``, D-11).
     */
    ChangeDecisionView: {
      /** Decided At */
      decided_at: string;
      /** Decided By */
      decided_by: string;
      /**
       * Decision
       * @enum {string}
       */
      decision: "approved" | "declined";
      /** Note */
      note: string | null;
    };
    /**
     * ChangeRequestDecisionBody
     * @description ``POST .../change-requests/{n}/decision``: approved or declined, and the owner's note
     *     (required to decline).
     */
    ChangeRequestDecisionBody: {
      /**
       * Decision
       * @enum {string}
       */
      decision: "approved" | "declined";
      /** Note */
      note?: string | null;
    };
    /**
     * ChangeRequestView
     * @description A plan change request (``change-requests/<n>.md``, two-level-flows S2): its asking
     *     ``ticket``, ``status`` folded from its decision (None when the request cannot be read,
     *     ``problem`` then says why), the plan versions, the tickets it affects, when it was opened and
     *     by which ``run_id``. ``approval_id`` is the open gate of that run that answers it (P8, A5);
     *     ``decidable_here`` says the run is gone (lost, or ended), so hub web records the decision
     *     itself (AC-2.14). ``path`` is relative to the hub's ``brain/``; ``body`` (the ticket route
     *     only) is the request's evidence and proposal, as markdown within its 16 KiB head; ``body_cut``
     *     says the file goes on past it.
     */
    ChangeRequestView: {
      /** Affected */
      affected: string[];
      /** Approval Id */
      approval_id?: string | null;
      /** Body */
      body?: string | null;
      /**
       * Body Cut
       * @default false
       */
      body_cut: boolean;
      /**
       * Decidable Here
       * @default false
       */
      decidable_here: boolean;
      decision: components["schemas"]["ChangeDecisionView"] | null;
      /** N */
      n: number;
      /** Opened At */
      opened_at: string | null;
      /** Path */
      path: string;
      /** Plan From */
      plan_from: number | null;
      /** Plan To */
      plan_to: number | null;
      /** Problem */
      problem: string | null;
      /** Run Id */
      run_id: string | null;
      /** Status */
      status: ("open" | "approved" | "declined") | null;
      /** Ticket */
      ticket: string | null;
    };
    /**
     * ChangedFile
     * @description A file the session's tool calls changed (``Edit``, ``MultiEdit``, ``Write``,
     *     ``NotebookEdit``, subagents' included); ``last_change_id`` is the ``tool_use_id`` of the
     *     latest change to it, the id the chat's review marks compare with.
     */
    ChangedFile: {
      /** Last Change Id */
      last_change_id: string;
      /** Path */
      path: string;
    };
    /** @enum {string} */
    Choice: "pick" | "retry" | "stop";
    /**
     * CloudMessage
     * @description ``POST /agent-sessions/cloud/{cloud_id}/messages``: a one-shot follow-up.
     */
    CloudMessage: {
      /** Text */
      text: string;
    };
    /**
     * CloudSession
     * @description A session started in the cloud (D8): where to open it and how to teleport it here.
     */
    CloudSession: {
      /** Cloud Id */
      cloud_id: string;
      created_at: components["schemas"]["ApiTimestamp"];
      /**
       * Followups
       * @default 0
       */
      followups: number;
      /** Id */
      id: string;
      /** Project */
      project: string;
      /** Teleport Command */
      teleport_command: string;
      /** Title */
      title?: string | null;
      /** Url */
      url?: string | null;
      /** Workdir Id */
      workdir_id: string;
    };
    /**
     * CloudSessionList
     * @description ``GET /agent-sessions/cloud``: the persisted cloud starts, newest first, at most 50.
     */
    CloudSessionList: {
      /** Items */
      items: components["schemas"]["CloudSession"][];
    };
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
    Commit: string;
    /**
     * ConfigFileView
     * @description One of the two files: its path and, when it cannot be used, its problems.
     */
    ConfigFileView: {
      /** Name */
      name: string;
      /** Path */
      path: string;
      /**
       * Problems
       * @default []
       */
      problems: string[];
    };
    /**
     * ContextCost
     * @description Approximate tokens (characters / 4, P8): ``always_loaded_tokens`` from the description (0
     *     when the model cannot invoke the skill), ``on_invoke_tokens`` from the body.
     */
    ContextCost: {
      /** Always Loaded Tokens */
      always_loaded_tokens: number;
      /**
       * Approximate
       * @default true
       * @constant
       */
      approximate: true;
      /** On Invoke Tokens */
      on_invoke_tokens: number;
    };
    /**
     * CreateAgentSession
     * @description ``POST /agent-sessions``: where, how, and an optional first prompt (its byte size is
     *     checked against the message limit, 413), or a past session to resume (and fork).
     *     ``screenshot`` (the screen's capture), ``screenshots`` (images pasted in the first
     *     message) and ``files`` go with the first prompt, so they need one.
     */
    CreateAgentSession: {
      /** Files */
      files?: components["schemas"]["MessageFile"][] | null;
      /**
       * Fork
       * @default false
       */
      fork: boolean;
      /** @default default */
      mode: components["schemas"]["PermissionMode"];
      model?: components["schemas"]["ModelName"] | null;
      /** Project */
      project: string;
      /** Prompt */
      prompt?: string | null;
      /** Resume Session Id */
      resume_session_id?: string | null;
      screenshot?: components["schemas"]["Screenshot"] | null;
      /** Screenshots */
      screenshots?: components["schemas"]["Screenshot"][] | null;
      /** Workdir Id */
      workdir_id: string;
    };
    /** CreatedIssue */
    CreatedIssue: {
      /** Id */
      id: string;
      /** Url */
      url: string;
    };
    /**
     * Credentials
     * @description Where the credentials of an environment come from: names, never values.
     */
    Credentials: {
      /** @description An AWS profile name. */
      aws_profile?: string;
      /**
       * Env
       * @description Names of the environment variables that hold credentials.
       * @default []
       */
      env: string[];
      /** @description A dotenv file, relative to the folder holding the hub and its repos, that only actions read; at most 200 characters, no '..', no leading '/' or '~'. */
      env_file?: string;
    } & {
      [key: string]: unknown;
    };
    /** DecisionEntry */
    DecisionEntry: {
      /** Approver */
      approver: string | null;
      /** At */
      at: string | null;
      /** Attempt */
      attempt: number | null;
      /** Choice */
      choice: string | null;
      /** Node */
      node: string;
      /** Text */
      text: string | null;
      /** Where */
      where: string | null;
    };
    /**
     * Diagnostic
     * @description One informational finding on an item, in one hub-relative line (D5, P6).
     */
    Diagnostic: {
      code: components["schemas"]["DiagnosticCode"];
      /** Message */
      message: string;
      severity: components["schemas"]["DiagnosticSeverity"];
    };
    /**
     * DiagnosticCode
     * @description Every diagnostic an item can carry (P6).
     * @enum {string}
     */
    DiagnosticCode:
      | "name_invalid"
      | "name_mismatch"
      | "description_missing"
      | "description_too_long"
      | "frontmatter_unparseable"
      | "link_outside_hub"
      | "too_large"
      | "not_regular"
      | "not_text"
      | "body_too_long"
      | "reference_not_found"
      | "unknown_key"
      | "duplicate_name"
      | "not_linked"
      | "modified_since_sync"
      | "over_budget";
    /**
     * DiagnosticSeverity
     * @description How much a diagnostic matters; never blocking (D5).
     * @enum {string}
     */
    DiagnosticSeverity: "info" | "warning";
    /**
     * DiscoveryProposal
     * @description What Claude proposed, as the server checked it.
     */
    DiscoveryProposal: {
      /**
       * Dropped
       * @default []
       */
      dropped: components["schemas"]["Dropped"][];
      /**
       * Environments
       * @default []
       */
      environments: components["schemas"]["ProposedEnvironment"][];
      /**
       * Missing
       * @default []
       */
      missing: components["schemas"]["MissingService"][];
      /**
       * Not Read
       * @default []
       */
      not_read: components["schemas"]["NotRead"][];
      /**
       * Services
       * @default []
       */
      services: components["schemas"]["ProposedService"][];
    };
    /** @enum {string} */
    DiscoveryState: "running" | "finished" | "failed" | "stopped";
    /**
     * DoctorFixRequest
     * @description The empty JSON body of the fix: a cross-site form cannot send one (S7).
     */
    DoctorFixRequest: Record<string, never>;
    /**
     * DoctorFixResult
     * @description What one fix did, and what the check after it found.
     */
    DoctorFixResult: {
      /** Changed Files */
      changed_files: string[];
      /** Errors Left */
      errors_left: number | null;
      /** Exit Code */
      exit_code: number;
      /** Hub Id */
      hub_id: string;
      /** Ok */
      ok: boolean;
      /** Output */
      output: string[];
      /** Warnings Left */
      warnings_left: number | null;
    };
    /**
     * DriverCapabilities
     * @description What this machine can do: whether sessions can start (and why not), the engine, the
     *     ``claude`` version, the model aliases offered, and the cloud commands the CLI lists.
     */
    DriverCapabilities: {
      /** Available */
      available: boolean;
      /** Cli Version */
      cli_version?: string | null;
      /**
       * Cloud
       * @default false
       */
      cloud: boolean;
      /**
       * Cloud Followup
       * @default false
       */
      cloud_followup: boolean;
      /** Engine */
      engine?: string | null;
      /**
       * Models
       * @default [
       *       "default",
       *       "opus",
       *       "sonnet",
       *       "haiku"
       *     ]
       */
      models: string[];
      /** Reason */
      reason?: string | null;
    };
    /**
     * Dropped
     * @description An item, or one field of it, the server refused while checking the proposal.
     */
    Dropped: {
      /** Reason */
      reason: string;
      /** What */
      what: string;
    };
    /** @enum {string} */
    EdgeSource: "plan" | "linear" | "both";
    /**
     * EditBatch
     * @description Edits made in order and written together: both files or neither.
     */
    EditBatch: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "batch";
      /** Ops */
      ops: components["schemas"]["SingleEdit"][];
    };
    /**
     * EffectiveEnvironments
     * @description The union of both files: committed entries first, then the developer's (P-5).
     */
    EffectiveEnvironments: {
      /** Blocked Env */
      blocked_env: components["schemas"]["LayeredEntry"][];
      /** Blocked Files */
      blocked_files: components["schemas"]["LayeredEntry"][];
      /** Blocked Words */
      blocked_words: components["schemas"]["LayeredEntry"][];
      /** Environments */
      environments: components["schemas"]["SourcedEnvironment"][];
      /** Services */
      services: components["schemas"]["SourcedService"][];
    };
    /**
     * EndReason
     * @description Why a session ended.
     * @enum {string}
     */
    EndReason: "closed" | "idle_timeout" | "server_stopped" | "failed" | "log_full";
    /**
     * Endpoint
     * @description How a service is reached in one environment: a url, a resource name, or both.
     */
    Endpoint:
      | ({
          /** @description Names of the credentials to use here; never a value. */
          credentials?: components["schemas"]["Credentials"];
          note?: string;
          /** @description A resource name, such as a table or a function. */
          resource?: string;
          /** @description scheme://host[:port][/path], at most 200 characters; no user info, query or fragment. */
          url?: string;
        } & {
          [key: string]: unknown;
        })
      | unknown
      | unknown;
    /**
     * EnvFileKeys
     * @description What hub web may show of an env file: whether it is found where it may be, whether git
     *     ignores it, and its variable names. ``problem`` says, in words, why no names are shown.
     */
    EnvFileKeys: {
      /** Exists */
      exists: boolean;
      /** Holder */
      holder: string | null;
      /** Ignored */
      ignored: boolean | null;
      /**
       * Keys
       * @default []
       */
      keys: string[];
      /** Path */
      path: string;
      /** Problem */
      problem?: string | null;
      /**
       * Truncated
       * @default false
       */
      truncated: boolean;
    };
    /**
     * EnvironmentDiscovery
     * @description ``/projects/{project}/environment-discoveries``: a discovery, where its session is, and
     *     its checked proposal once there is one; ``problem`` says in plain words why it failed.
     */
    EnvironmentDiscovery: {
      /** Agent Session Id */
      agent_session_id: string;
      created_at: components["schemas"]["ApiTimestamp"];
      /** Environments */
      environments: string[];
      /** Id */
      id: string;
      /** Problem */
      problem?: string | null;
      /** Project */
      project: string;
      proposal?: components["schemas"]["DiscoveryProposal"] | null;
      /** Repos */
      repos: string[];
      state: components["schemas"]["DiscoveryState"];
      /** Suggest Environments */
      suggest_environments: boolean;
    };
    EnvironmentEdit:
      | components["schemas"]["AddEnvironment"]
      | components["schemas"]["SetEnvironment"]
      | components["schemas"]["RenameEnvironment"]
      | components["schemas"]["RemoveEnvironment"]
      | components["schemas"]["AddEndpoint"]
      | components["schemas"]["RemoveEndpoint"]
      | components["schemas"]["AddService"]
      | components["schemas"]["SetService"]
      | components["schemas"]["EditBatch"];
    /**
     * EvalRecord
     * @description One evaluation of a delivery: ``evals/<delivery>.md``, or the legacy ``eval.md``.
     *
     *     ``path`` is relative to the hub's ``brain/``. ``acs`` is the AC ids evaluated or ``"all"``;
     *     ``evaluated_at`` is the frontmatter's text (an ISO date or time). ``provenance`` says who ran
     *     it (e.g. ``agent``, ``agent-evaluator``, ``owner``), None when the note does not say.
     *     ``problem`` says why the file could not be read or parsed; its other fields are then empty.
     */
    EvalRecord: {
      /** Acs */
      acs: string[] | "all";
      /** Commit */
      commit: string | null;
      /** Delivery */
      delivery: string;
      /** Evaluated At */
      evaluated_at: string | null;
      /** Legacy */
      legacy: boolean;
      /** Path */
      path: string;
      /** Problem */
      problem: string | null;
      /** Provenance */
      provenance?: string | null;
      /** Prs */
      prs: string[];
      /** Tickets */
      tickets: string[];
      verdict: components["schemas"]["Verdict"] | null;
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
      | "session.summary"
      | "session.title"
      | "expect.poll"
      | "context.capture"
      | "action.start"
      | "action.end"
      | "policy.decision"
      | "finding"
      | "workaround.start"
      | "workaround.end";
    /**
     * Evidence
     * @description Where Claude saw something: a file relative to the workspace, inside a picked repo.
     */
    Evidence: {
      /** Line */
      line?: number | null;
      /** Path */
      path: string;
    };
    /**
     * ExternalBlocker
     * @description A blocker outside the feature's tickets, with its status when Linear returned it.
     */
    ExternalBlocker: {
      /** Done */
      done: boolean;
      /** Id */
      id: string;
      state: components["schemas"]["IssueState"] | null;
      /** Title */
      title: string | null;
      /** Url */
      url: string | null;
    };
    /**
     * ExternalPlugin
     * @description A third-party plugin named by ``enabledPlugins`` or the marketplace (D1, P7); its content
     *     is not in the hub and is never fetched. ``pin`` is the pinned sha or ref, or None.
     */
    ExternalPlugin: {
      /**
       * Content
       * @default not in this hub
       * @constant
       */
      content: "not in this hub";
      /** Enabled */
      enabled: boolean;
      /** Marketplace */
      marketplace: string | null;
      /** Name */
      name: string;
      /** Pin */
      pin: string | null;
    };
    /** @enum {string} */
    FailureKind:
      | "transient"
      | "timeout"
      | "rate_limited"
      | "overloaded"
      | "exec_failed"
      | "output_contract"
      | "max_iterations"
      | "unknown"
      | "config"
      | "auth"
      | "cancelled"
      | "fatal";
    /**
     * FeatureCost
     * @description What building the feature cost so far, estimated from its sessions' transcripts: the
     *     sessions that touched its folder or worked on one of its tickets. ``total_usd`` adds up the
     *     priced ones (None when none is); ``unpriced`` counts the rest.
     */
    FeatureCost: {
      /** Sessions */
      sessions: number;
      total_usd: components["schemas"]["Money"] | null;
      /** Unpriced */
      unpriced: number;
    };
    /**
     * FeatureDetail
     * @description A feature with its acceptance criteria rows, its records (D3) and every eval; ``plan``
     *     (None without ``plan.md``) and ``acceptance_eval`` (None before one exists), whose verdict is
     *     the header's ``verdict``; ``change_requests`` by number; ``cost`` what its sessions cost
     *     (None when the events are not read).
     */
    FeatureDetail: {
      /**
       * Ac Rows
       * @default []
       */
      ac_rows: components["schemas"]["AcRow"][];
      acceptance_eval?: components["schemas"]["AcceptanceEval"] | null;
      acs: components["schemas"]["AcCounts"] | null;
      /**
       * Change Requests
       * @default []
       */
      change_requests: components["schemas"]["ChangeRequestView"][];
      cost?: components["schemas"]["FeatureCost"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /**
       * Evals
       * @default []
       */
      evals: components["schemas"]["EvalRecord"][];
      /** Files */
      files: string[];
      golden_path: components["schemas"]["GoldenPath"];
      /** Issues */
      issues: string[];
      phase: components["schemas"]["FeaturePhase"];
      plan?: components["schemas"]["PlanView"] | null;
      /** Problem */
      problem?: string | null;
      /** Project */
      project: string;
      /**
       * Records
       * @default []
       */
      records: components["schemas"]["FeatureRecord"][];
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
      tickets_source: components["schemas"]["TicketsSource"];
      verdict: components["schemas"]["Verdict"] | null;
      /** Verdict Line */
      verdict_line: string | null;
      waiting_on_owner?: components["schemas"]["WaitingOnOwner"] | null;
    };
    /**
     * FeatureName
     * @description One feature's nickname.
     */
    FeatureName: {
      /** Name */
      name: string;
      /** Project */
      project: string;
      /** Slug */
      slug: string;
    };
    /**
     * FeatureNameBody
     * @description ``PUT /feature-names``: the feature and its new name ("" clears it).
     */
    FeatureNameBody: {
      /** Name */
      name: string;
      /** Project */
      project: string;
      /** Slug */
      slug: string;
    };
    /**
     * FeatureNamesView
     * @description ``GET /feature-names``: every nickname set on this machine.
     */
    FeatureNamesView: {
      /** Items */
      items: components["schemas"]["FeatureName"][];
    };
    /** @enum {string} */
    FeaturePhase:
      "spec" | "ux_design" | "research" | "plan" | "tickets" | "build" | "acceptance" | "shipped";
    /**
     * FeatureRecord
     * @description One record file of a feature folder; ``path`` is relative to the hub's ``brain/``, so the
     *     brain note route reads it.
     */
    FeatureRecord: {
      name: components["schemas"]["FeatureRecordName"];
      /** Path */
      path: string;
      /** Present */
      present: boolean;
    };
    /** @enum {string} */
    FeatureRecordName: "spec" | "research" | "plan" | "eval" | "issues";
    /**
     * FeatureTickets
     * @description ``GET /features/{project}/{slug}/tickets``: the tickets, their planning and the golden
     *     path computed with them.
     *
     *     ``source`` is ``linear`` when a snapshot was used (``stale`` when it is the last good one
     *     after a failure; ``as_of`` is when it was read), else ``plan``, with a ``notice`` and the
     *     ``tracker_problem`` naming the cause.
     */
    FeatureTickets: {
      as_of: components["schemas"]["ApiTimestamp"] | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      golden_path: components["schemas"]["GoldenPath"];
      /** Notice */
      notice: string | null;
      planning: components["schemas"]["TicketPlan"];
      /** Project */
      project: string;
      /** Slug */
      slug: string;
      source: components["schemas"]["TicketsSource"];
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      /** Stale */
      stale: boolean;
      /** Tickets */
      tickets: components["schemas"]["TicketRow"][];
      tracker_problem: components["schemas"]["TrackerProblem"] | null;
    };
    /**
     * FeatureView
     * @description A feature as the Features list shows it; ``problem`` when a file of it is malformed.
     *
     *     ``phase`` equals ``golden_path.phase``; ``tickets_source`` says whether the ticket counts
     *     behind the golden path came from Linear or from the plan; ``waiting_on_owner`` what it waits
     *     on from the owner, None when nothing.
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
      golden_path: components["schemas"]["GoldenPath"];
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
      tickets_source: components["schemas"]["TicketsSource"];
      verdict: components["schemas"]["Verdict"] | null;
      /** Verdict Line */
      verdict_line: string | null;
      waiting_on_owner?: components["schemas"]["WaitingOnOwner"] | null;
    };
    /** @enum {string} */
    FileOperation: "read" | "edited" | "created" | "written";
    /** @enum {string} */
    FileRole: "scripts" | "references" | "assets" | "other";
    /** FindingEntry */
    FindingEntry: {
      /** Evidence */
      evidence: string;
      /** Finding Id */
      finding_id: string;
      /** Step */
      step: string;
      /** Text */
      text: string;
      /** Title */
      title: string;
    };
    /**
     * FindingIssue
     * @description A finding's tracker issue: its draft, the team it goes to, and the issue once created.
     *     ``recorded`` is whether the created issue reached its marker (``None`` before a create);
     *     when it did not, ``warning`` says so: the issue exists, do not create it again.
     */
    FindingIssue: {
      created: components["schemas"]["CreatedIssue"] | null;
      /** Description */
      description: string;
      /** Finding Id */
      finding_id: string;
      /** Recorded */
      recorded?: boolean | null;
      /** Run Id */
      run_id: string;
      /** Team */
      team: string | null;
      /** Title */
      title: string;
      /** Warning */
      warning?: string | null;
    };
    /**
     * FindingIssueRequest
     * @description ``confirm: true`` creates the issue (the terminal's ``y``); without it, the draft.
     */
    FindingIssueRequest: {
      /**
       * Confirm
       * @default false
       */
      confirm: boolean;
    };
    /**
     * FindingNote
     * @description The inbox note written for a finding, hub-relative.
     */
    FindingNote: {
      /** Finding Id */
      finding_id: string;
      /** Path */
      path: string;
      /** Run Id */
      run_id: string;
    };
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
     * FrontmatterPair
     * @description One frontmatter key in file order; ``known`` when Claude Code understands the key.
     */
    FrontmatterPair: {
      /** Key */
      key: string;
      /**
       * Known
       * @default false
       */
      known: boolean;
      value: components["schemas"]["SkillFrontmatterValue"];
    };
    FrontmatterValue: string | string[];
    /**
     * GateChoice
     * @description A decision or option a person may pick, with its label.
     */
    GateChoice: {
      /** Id */
      id: string;
      /** Label */
      label: string;
    };
    /**
     * GateDecided
     * @description What a decision did: the gate's approval, its run and project, and the answer's id.
     */
    GateDecided: {
      /** Approval Id */
      approval_id: string;
      /** Decision */
      decision: string | null;
      /** Project */
      project: string;
      /** Run Id */
      run_id: string;
    };
    /**
     * GateDecisionRequest
     * @description The body of ``POST /approvals/{id}/decision``: a decision or option id and/or a text.
     */
    GateDecisionRequest: {
      /** Decision */
      decision?: string | null;
      /** Text */
      text?: string | null;
    };
    /** @enum {string} */
    GateForm: "decision" | "choice" | "text" | "timer";
    /** @enum {string} */
    GateKindName: "policy" | "investigation";
    /**
     * GoldenPath
     * @description The feature's steps in their fixed order; ``phase`` is the first step neither done nor
     *     skipped (``shipped`` when all are).
     */
    GoldenPath: {
      phase: components["schemas"]["FeaturePhase"];
      /** Steps */
      steps: components["schemas"]["GoldenStep"][];
    };
    /**
     * GoldenStep
     * @description One step of the golden path: its state, a short ``meta`` text and the ``reason`` it is
     *     not done (naming the failing gate), its ``progress`` when it counts something, and the one
     *     ``signal`` that needs attention (Plan: "v3 waits for you" while a change request is open).
     */
    GoldenStep: {
      /** Meta */
      meta: string | null;
      name: components["schemas"]["FeaturePhase"];
      progress: components["schemas"]["StepProgress"] | null;
      /** Reason */
      reason: string | null;
      /** Signal */
      signal?: string | null;
      state: components["schemas"]["StepState"];
    };
    /**
     * GuardConfigView
     * @description The guard's lists: the blocked entries are layered, the rest are team only.
     */
    GuardConfigView: {
      /** Ask Before Edit */
      ask_before_edit: string[];
      blocked_words: components["schemas"]["LayeredList"];
      blocked_words_env: components["schemas"]["LayeredList"];
      blocked_words_files: components["schemas"]["LayeredList"];
      /** Deny Hosts */
      deny_hosts: string[];
      /** Deny Paths */
      deny_paths: string[];
      /** Infra On */
      infra_on: boolean;
      /** Readable Env Files */
      readable_env_files: string[];
      /** Secret Env Files */
      secret_env_files: string[];
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
        [key: string]: components["schemas"]["pydantic__types__JsonValue"];
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
     * HookFacts
     * @description A hook as configured (D4): ``command`` is inert text, never run.
     */
    HookFacts: {
      /** Active */
      active: boolean;
      /** Command */
      command: string | null;
      /** Event */
      event: string;
      /** Matcher */
      matcher: string | null;
      state: components["schemas"]["HookState"];
      /** Timeout */
      timeout: number | null;
      /** Type */
      type: string;
    };
    /** @enum {string} */
    HookState: "synced" | "not synced";
    /**
     * HubConfigView
     * @description The whole Hub config screen of one project.
     */
    HubConfigView: {
      /** Agent Models */
      agent_models: components["schemas"]["AgentModelView"][];
      author_email: components["schemas"]["SourcedValue"];
      author_name: components["schemas"]["SourcedValue"];
      branch_prefix: components["schemas"]["SourcedValue"];
      /** Conventions */
      conventions: [
        components["schemas"]["PatternView"],
        components["schemas"]["PatternView"],
        components["schemas"]["PatternView"],
      ];
      default_branch: components["schemas"]["SourcedValue"];
      environments: components["schemas"]["EffectiveEnvironments"];
      guard: components["schemas"]["GuardConfigView"];
      /** Hub Path */
      hub_path: string;
      /** Hub Repo */
      hub_repo: string;
      local_file: components["schemas"]["ConfigFileView"];
      /** Model Tiers */
      model_tiers: {
        [key: string]: string;
      };
      /**
       * Model Tiers Set
       * @default []
       */
      model_tiers_set: string[];
      /** Modules */
      modules: string[];
      /** Platform Version */
      platform_version: string;
      /** Project */
      project: string;
      /** Repos */
      repos: components["schemas"]["RepoConfigView"][];
      team_file: components["schemas"]["ConfigFileView"];
      tracker: components["schemas"]["TrackerConfigView"];
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
    InputName: string;
    InputNumber: number;
    InputText: string;
    InputValue:
      boolean | number | components["schemas"]["InputNumber"] | components["schemas"]["InputText"];
    Inputs: {
      [key: string]: components["schemas"]["InputValue"];
    };
    /**
     * InvestigationAnswer
     * @description The answer to an open investigation: ``pick`` with an option id, ``retry`` or ``stop``.
     */
    InvestigationAnswer: {
      choice: components["schemas"]["Choice"];
      option?: components["schemas"]["OptionId"] | null;
    };
    /**
     * InvestigationAnswered
     * @description What an answer did: recorded for the investigation, and the run resumed.
     */
    InvestigationAnswered: {
      choice: components["schemas"]["Choice"];
      /** Investigation */
      investigation: number;
      /** Option */
      option: string | null;
      /** Project */
      project: string;
      /** Run Id */
      run_id: string;
      /** Step */
      step: string;
    };
    /**
     * InvestigationEntry
     * @description An investigation; ``agent_session_id`` is the session its link file names, if any.
     */
    InvestigationEntry: {
      /** Agent Session Id */
      agent_session_id?: string | null;
      /** Approver */
      approver: string | null;
      /** Choice */
      choice: string | null;
      /** Closed */
      closed: boolean;
      /** Failure Kind */
      failure_kind: string | null;
      /** Gate */
      gate: string;
      /** Number */
      number: number;
      /** Step */
      step: string;
      /** Text */
      text: string | null;
    };
    /**
     * InvestigationSession
     * @description The session of a scenario run's open investigation: ``started`` when this call
     *     started it.
     */
    InvestigationSession: {
      /** Agent Session Id */
      agent_session_id: string;
      /** Investigation */
      investigation: number;
      /** Project */
      project: string;
      /** Run Id */
      run_id: string;
      /** Started */
      started: boolean;
      /** Step */
      step: string;
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
    /**
     * IssueState
     * @description An issue's workflow state: its ``name`` in the team and Linear's state ``type``.
     */
    IssueState: {
      /** Name */
      name: string;
      type: components["schemas"]["IssueStateType"];
    };
    /** @enum {string} */
    IssueStateType:
      "triage" | "backlog" | "unstarted" | "started" | "completed" | "canceled" | "duplicate";
    /**
     * ItemKind
     * @description What an item is.
     * @enum {string}
     */
    ItemKind: "skill" | "agent" | "hook";
    /** @enum {string} */
    ItemStatus: "new" | "differs" | "declared";
    /**
     * ItemVersionContent
     * @description A version's content: a file unit's one file, or a folder's files in path order (S6).
     */
    ItemVersionContent: {
      /** Files */
      files: components["schemas"]["VersionFileView"][];
      /** Id */
      id: string;
      unit_kind: components["schemas"]["UnitKind"];
    };
    /**
     * ItemVersionPage
     * @description A page of a unit's versions, newest first, with what the disk holds now: ``state`` (S8,
     *     S10, A1), ``managed`` (A4), the unit and how many items share it.
     */
    ItemVersionPage: {
      /** Items */
      items: components["schemas"]["ItemVersionView"][];
      /** Managed */
      managed: boolean;
      /** Next Cursor */
      next_cursor?: string | null;
      /** Shared By */
      shared_by: number;
      state: components["schemas"]["UnitState"];
      /** Total Estimate */
      total_estimate: number;
      unit_kind: components["schemas"]["UnitKind"];
      /** Unit Path */
      unit_path: string;
    };
    /**
     * ItemVersionView
     * @description One version as the history lists it (``author`` None for ``external``, D11).
     */
    ItemVersionView: {
      author: components["schemas"]["VersionAuthor"] | null;
      /** Content Hash */
      content_hash: string;
      /** Draft Id */
      draft_id?: string | null;
      /** First */
      first: boolean;
      /** Id */
      id: string;
      origin: components["schemas"]["VersionOrigin"];
      recorded_at: components["schemas"]["ApiTimestamp"];
      /** Restored From */
      restored_from: string | null;
      /** Size */
      size: number;
    };
    /**
     * ItemWriteResult
     * @description What a Publish or Restore did: ``changed`` False when the content was equal (nothing
     *     written or recorded, D12); ``versioned`` False with its ``reason`` when the written content
     *     was not stored (D9, A2); ``version`` the version recorded.
     */
    ItemWriteResult: {
      /** Changed */
      changed: boolean;
      reason: components["schemas"]["UnversionedReason"] | null;
      version: components["schemas"]["ItemVersionView"] | null;
      /** Versioned */
      versioned: boolean;
    };
    /** @enum {string} */
    KeySource: "environment" | "settings";
    /** @enum {string} */
    Kind:
      | "adr"
      | "decision"
      | "doc"
      | "domain"
      | "feature"
      | "inbox"
      | "journal"
      | "learning"
      | "playbook"
      | "system";
    /**
     * KnowledgeResult
     * @description One search result: the document and a one-line plain-text snippet of its body.
     */
    KnowledgeResult: {
      kind: components["schemas"]["Kind"];
      /** Path */
      path: string;
      /** Provenance */
      provenance: string | null;
      /** Snippet */
      snippet: string;
      /** Status */
      status: string | null;
      /** Title */
      title: string;
    };
    /**
     * KnowledgeSearch
     * @description A search of the project's hub: ``hub search --json``'s object, ``project`` for ``hub``,
     *     plus a warning per repo that is not checked out.
     */
    KnowledgeSearch: {
      /** Project */
      project: string;
      /** Query */
      query: string;
      /** Results */
      results: components["schemas"]["KnowledgeResult"][];
      /** Skipped */
      skipped: components["schemas"]["KnowledgeSkip"][];
      sync: components["schemas"]["KnowledgeSyncCounts"];
      /** Warnings */
      warnings: string[];
    };
    /**
     * KnowledgeSkip
     * @description A listed file the index left out, and why.
     */
    KnowledgeSkip: {
      /** Path */
      path: string;
      /** Reason */
      reason: string;
    };
    /**
     * KnowledgeSyncCounts
     * @description What the sync before the read did: files listed, read, indexed and rows dropped.
     */
    KnowledgeSyncCounts: {
      /** Dropped */
      dropped: number;
      /** Indexed */
      indexed: number;
      /** Listed */
      listed: number;
      /** Read */
      read: number;
    };
    /**
     * LayeredEntry
     * @description A blocked word, glob or variable name, and the first layer that lists it.
     */
    LayeredEntry: {
      /** Layer */
      layer: string;
      /** Value */
      value: string;
    };
    /**
     * LayeredList
     * @description A list the team sets and this developer adds to.
     */
    LayeredList: {
      /** Local */
      local: string[];
      /** Team */
      team: string[];
    };
    /**
     * Learning
     * @description A learning; ``text`` is its title (120 characters at most, redacted).
     *
     *     ``target`` is deprecated (it names the inbox note); ``note_path`` says so explicitly (L12).
     *     ``state`` is ``None`` until read with the hub. ``summary`` is the note's first paragraph,
     *     read on request; ``note_unavailable`` and ``actions_unavailable`` give the reason the note
     *     cannot be read or the learning cannot be accepted or rejected here.
     */
    Learning: {
      /** Actions Unavailable */
      actions_unavailable?: string | null;
      /** Author */
      author: string | null;
      /** Brain Path */
      brain_path?: string | null;
      /** Branch */
      branch?: string | null;
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
      /** Note Path */
      note_path?: string | null;
      /** Note Unavailable */
      note_unavailable?: string | null;
      /** Pr Url */
      pr_url?: string | null;
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
      state?: components["schemas"]["LearningState"] | null;
      status: components["schemas"]["LearningStatus"];
      /** Summary */
      summary?: string | null;
      /** @deprecated */
      target: components["schemas"]["LearningTarget"];
      /** Text */
      text: string;
    };
    /**
     * LearningActionResult
     * @description What an accept or reject did: the pull request it opened and its branch.
     */
    LearningActionResult: {
      /** Branch */
      branch: string;
      /** Pr Url */
      pr_url: string;
      state: components["schemas"]["LearningState"];
    };
    /**
     * LearningDetail
     * @description A learning with its note (``None`` when unavailable), the destination folder the accept
     *     dialog suggests and the folders it offers (L9).
     */
    LearningDetail: {
      /** Actions Unavailable */
      actions_unavailable?: string | null;
      /** Author */
      author: string | null;
      /** Brain Path */
      brain_path?: string | null;
      /** Branch */
      branch?: string | null;
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
      note?: components["schemas"]["BrainNote"] | null;
      /** Note Path */
      note_path?: string | null;
      /** Note Unavailable */
      note_unavailable?: string | null;
      /** Pr Url */
      pr_url?: string | null;
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
      state?: components["schemas"]["LearningState"] | null;
      status: components["schemas"]["LearningStatus"];
      /** Suggested Target */
      suggested_target: string;
      /** Summary */
      summary?: string | null;
      /** @deprecated */
      target: components["schemas"]["LearningTarget"];
      /**
       * Target Choices
       * @default []
       */
      target_choices: string[];
      /** Text */
      text: string;
    };
    /**
     * LearningState
     * @description Where the learning's note is (L11): in the inbox, in an open PR, or moved by a merge.
     *
     *     ``in_brain`` and ``archived`` are inferred from the hub checkout (the note sits at its
     *     destination), since GitHub is not connected.
     * @enum {string}
     */
    LearningState: "proposed" | "accepted_pr_open" | "rejected_pr_open" | "in_brain" | "archived";
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
     * LibraryAction
     * @description An action of the hub as the palette lists it.
     */
    LibraryAction: {
      action: components["schemas"]["ScenarioActionView"];
      /** Output Fields */
      output_fields: components["schemas"]["OutputField"][];
      /** Used By */
      used_by: string[];
    };
    /**
     * LinearAccountView
     * @description The key's user and workspace.
     */
    LinearAccountView: {
      /** Email */
      email: string;
      /** Name */
      name: string;
      /** Url */
      url: string;
      /** Workspace */
      workspace: string;
    };
    /**
     * LinearConnectionView
     * @description ``GET /tracker/linear``: whether hub web reads Linear, as whom, or why not.
     */
    LinearConnectionView: {
      account: components["schemas"]["LinearAccountView"] | null;
      /** Checked At */
      checked_at: string | null;
      /** Connected */
      connected: boolean;
      /** Key Path */
      key_path: string;
      /** Problem */
      problem: string | null;
      /** Problem Kind */
      problem_kind: string | null;
      source: components["schemas"]["KeySource"] | null;
    };
    /**
     * LinearKeyBody
     * @description ``PUT /tracker/linear``: a Linear personal API key.
     */
    LinearKeyBody: {
      /** Api Key */
      api_key: string;
    };
    /**
     * LiveTile
     * @description A session tile of the Live sessions screen.
     *
     *     ``agent`` is deprecated (``label`` and ``actors``); ``needs_you_problem`` is the owner-facing
     *     line of the first problem that needs the owner ("Needs you: <kind> in <where>");
     *     ``agent_session_id`` is the agent session ``hub web`` drives it from, when there is one.
     */
    LiveTile: {
      /**
       * Actors
       * @default []
       */
      actors: components["schemas"]["Actor"][];
      /**
       * Agent
       * @deprecated
       */
      agent: string;
      /** Agent Session Id */
      agent_session_id?: string | null;
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
      label?: components["schemas"]["SessionLabel"] | null;
      /** Last Action */
      last_action: string | null;
      last_activity_at: components["schemas"]["ApiTimestamp"];
      /** Last Tool */
      last_tool: string | null;
      /** Needs You Problem */
      needs_you_problem?: string | null;
      outcome?: components["schemas"]["Outcome"] | null;
      /**
       * @default {
       *       "by_you": 0,
       *       "handled": 0,
       *       "needs_you": 0,
       *       "open": 0
       *     }
       */
      problems: components["schemas"]["ProblemCounts"];
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
    /**
     * LocalSettings
     * @description What the screen edits; an empty text or ``None`` removes the key from the file.
     */
    LocalSettings: {
      /** Author Email */
      author_email?: string | null;
      /** Author Name */
      author_name?: string | null;
      /**
       * Blocked Words
       * @default []
       */
      blocked_words: string[];
      /**
       * Blocked Words Env
       * @default []
       */
      blocked_words_env: string[];
      /**
       * Blocked Words Files
       * @default []
       */
      blocked_words_files: string[];
      /** Branch Prefix */
      branch_prefix?: string | null;
      /** Transport */
      transport?: ("api" | "mcp") | null;
    };
    /**
     * LockFacts
     * @description What ``hub.lock`` says of the item's file: its ownership and, when managed, its sha256.
     */
    LockFacts: {
      /** Ownership */
      ownership: string;
      /** Sha256 */
      sha256: string | null;
    };
    /** @enum {string} */
    LockState: "in_sync" | "drift" | "sync_pending" | "not_adopted";
    /**
     * LogRecord
     * @description One persisted record of a session's log.
     */
    LogRecord: {
      at: components["schemas"]["ApiTimestamp"];
      /** Body */
      body: {
        [key: string]: components["schemas"]["pydantic__types__JsonValue"];
      };
      by?: components["schemas"]["RecordBy"] | null;
      kind: components["schemas"]["RecordKind"];
      /** Seq */
      seq: number;
      /**
       * Text Bytes
       * @default 0
       */
      text_bytes: number;
    };
    /**
     * LogRecordPage
     * @description ``GET /{id}/events``: records after ``after`` in ``seq`` order; ``next_after`` is the
     *     ``after`` of the next page, None on the last one.
     */
    LogRecordPage: {
      /** Items */
      items: components["schemas"]["LogRecord"][];
      /** Next After */
      next_after?: number | null;
    };
    /**
     * MessageAccepted
     * @description ``POST /{id}/messages`` (202): the ``seq`` of the ``user.message`` record.
     */
    MessageAccepted: {
      /** Seq */
      seq: number;
    };
    /**
     * MessageFile
     * @description A file attached to a message for Claude to read: a PDF or a UTF-8 text, base64-encoded;
     *     its decoded size and content are checked by ``decode_message_file`` (413, 422).
     */
    MessageFile: {
      /** Data */
      data: string;
      /**
       * Media Type
       * @enum {string}
       */
      media_type: "application/pdf" | "text/plain";
      /** Name */
      name: string;
    };
    /**
     * MissingService
     * @description A service Claude saw a sign of but could not place: no address it could read.
     */
    MissingService: {
      /**
       * Evidence
       * @default []
       */
      evidence: components["schemas"]["Evidence"][];
      /** Kind */
      kind?: string | null;
      /** Name */
      name: string;
      /** Repo */
      repo: string;
      /** Why */
      why: string;
    };
    /**
     * Mode
     * @description Who can invoke a skill (S5, L2); ``neither`` reads "Hidden" in the UI.
     * @enum {string}
     */
    Mode: "user-only" | "model-only" | "both" | "neither";
    ModelName: string;
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
     * NewAction
     * @description A new action from the builder: its facts and its script's text.
     */
    NewAction: {
      /** Description */
      description: string;
      /**
       * Effect
       * @enum {string}
       */
      effect: "read" | "write" | "destroy";
      /** Inputs */
      inputs?: components["schemas"]["ActionInputDraft"][];
      /** Name */
      name: string;
      /** Outputs */
      outputs?: components["schemas"]["OutputFieldDraft"][];
      /** Pack */
      pack: string;
      /**
       * Runtime
       * @default python
       * @enum {string}
       */
      runtime: "python" | "sh";
      /** Script Text */
      script_text: string;
      /**
       * Timeout
       * @default 5m
       */
      timeout: string;
    };
    /** NodeLines */
    NodeLines: {
      /** First Line */
      first_line: number;
      /** Id */
      id: string;
      /** Last Line */
      last_line: number;
    };
    /**
     * NotRead
     * @description A file Claude could not read, and why.
     */
    NotRead: {
      /** Path */
      path: string;
      /** Reason */
      reason: string;
    };
    /**
     * NoteBacklink
     * @description A document holding a link to the note: its hub-relative path, kind and title.
     */
    NoteBacklink: {
      kind: components["schemas"]["Kind"];
      /** Path */
      path: string;
      /** Title */
      title: string;
    };
    /**
     * NoteBacklinks
     * @description The documents linking to the note at ``path`` (under ``brain/``), by path, at most
     *     ``MAX_BACKLINKS``; ``total`` counts them all.
     */
    NoteBacklinks: {
      /** Items */
      items: components["schemas"]["NoteBacklink"][];
      /** Path */
      path: string;
      /** Project */
      project: string;
      /** Total */
      total: number;
    };
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
    OneLine1000: string;
    /**
     * OpenPermission
     * @description The permission request a live session waits on, as memory holds it (E10).
     *
     *     ``summary`` is the input summary (at most 4 KiB); ``input`` is the tool input only for an
     *     ``AskUserQuestion`` (its questions) or a plan approval (its plan), None for a tool.
     */
    OpenPermission: {
      asked_at: components["schemas"]["ApiTimestamp"];
      deadline_at: components["schemas"]["ApiTimestamp"];
      /** Input */
      input?: {
        [key: string]: components["schemas"]["pydantic__types__JsonValue"];
      } | null;
      /** Request Id */
      request_id: string;
      request_kind: components["schemas"]["RequestKind"];
      /**
       * Suggestions
       * @default []
       */
      suggestions: components["schemas"]["PermissionSuggestion"][];
      /** Summary */
      summary: string;
      /** Tool */
      tool: string;
    };
    /**
     * OptionEntry
     * @description An option of the latest proposal: its steps and their plan as shown, whether a step runs
     *     a draft action (``needs_acceptance``, with the commit lines that accept those still
     *     drafts), and whether it can be picked now, or why not.
     */
    OptionEntry: {
      /** Accept Commands */
      accept_commands: string[];
      /** Needs Acceptance */
      needs_acceptance: boolean;
      /** Option Id */
      option_id: string;
      /** Pickable */
      pickable: boolean;
      /** Plan */
      plan: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
      }[];
      /** Refusal */
      refusal: string | null;
      /** Steps */
      steps: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
      }[];
      /** Summary */
      summary: string;
    };
    OptionId: string;
    /**
     * Origin
     * @description Who owns an item (S4): ``managed`` per ``hub.lock``, ``project-owned`` (any other plugin
     *     folder, ``settings.project.json``), ``local`` (a real entry in ``.claude/``).
     * @enum {string}
     */
    Origin: "managed" | "project-owned" | "local";
    /**
     * Outcome
     * @description How an ended session ended; ``None`` when no source says.
     * @enum {string}
     */
    Outcome: "done" | "stopped" | "blocked" | "error";
    /** OutputField */
    OutputField: {
      /** Path */
      path: string;
      /** Type */
      type: string | null;
    };
    /** OutputFieldDraft */
    OutputFieldDraft: {
      /** Name */
      name: string;
      /**
       * Type
       * @default string
       * @enum {string}
       */
      type: "string" | "integer" | "number" | "boolean" | "object" | "array";
    };
    /**
     * OwnerSignOffBody
     * @description ``POST .../owner-signoff``: the eval to settle (or the ACs the owner checked by hand), the
     *     owner's decision and an optional note.
     */
    OwnerSignOffBody: {
      /** Acs */
      acs?: string[] | null;
      /**
       * Decision
       * @default done
       * @enum {string}
       */
      decision: "done" | "more_work";
      /** Delivery */
      delivery?: string | null;
      /** Note */
      note?: string | null;
    };
    /** @enum {string} */
    OwnerWaitKind: "change_request" | "owner_signoff" | "owner_signoff_manual";
    /** @enum {string} */
    OwnerWaitState: "sign_off" | "reopened" | "undated" | "future" | "no_acs";
    /**
     * OwnerWaitView
     * @description What the acceptance eval waits on from the owner (A9-A11, A15), the state the Eval tab's
     *     prompt shows: ``sign_off`` (the one state a sign-off can be recorded in), ``reopened`` (a
     *     later eval says NO-SHIP for ``reopened``: only "more work" can be recorded), ``undated`` and
     *     ``future`` (no sign-off can rank newer than an eval with no ``evaluated_at``, or one dated
     *     after the read), ``no_acs`` (no live AC to sign off, A10). ``acs`` are the ACs it waits on;
     *     ``signable_after`` (``future`` only) the whole minute after which a sign-off can follow it.
     */
    OwnerWaitView: {
      /**
       * Acs
       * @default []
       */
      acs: string[];
      /**
       * Reopened
       * @default []
       */
      reopened: string[];
      /** Signable After */
      signable_after?: string | null;
      state: components["schemas"]["OwnerWaitState"];
    };
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
    /** Page[EnvironmentDiscovery] */
    Page_EnvironmentDiscovery_: {
      /** Items */
      items: components["schemas"]["EnvironmentDiscovery"][];
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
     * PastSession
     * @description A Claude session of a working directory that can be resumed; ``title`` is redacted and
     *     at most 200 characters.
     */
    PastSession: {
      /** Cwd */
      cwd: string;
      last_activity: components["schemas"]["ApiTimestamp"];
      /** Session Id */
      session_id: string;
      /** Title */
      title?: string | null;
    };
    /** @enum {string} */
    PatternSource: "repo" | "project" | "default" | "commit_title";
    /**
     * PatternView
     * @description An effective convention pattern, which layer sets it, and a rendered example.
     */
    PatternView: {
      /** Example */
      example: string | null;
      /** Pattern */
      pattern: string;
      source: components["schemas"]["PatternSource"];
      /** Where */
      where: string;
    };
    /**
     * PermissionDecision
     * @description ``POST /{id}/permissions/{request_id}`` (E7).
     *
     *     ``allow`` may carry ``answers`` (an ``AskUserQuestion``) or ``mode`` (a plan approval);
     *     ``deny`` may carry ``message``; ``always`` needs ``suggestion``, the index of the
     *     ``localSettings`` rule to keep. Any other combination is refused (422); whether the fields
     *     fit the request is the permission policy's check.
     */
    PermissionDecision: {
      /** Answers */
      answers?: {
        [key: string]: string;
      } | null;
      /**
       * Decision
       * @enum {string}
       */
      decision: "allow" | "deny" | "always";
      /** Message */
      message?: string | null;
      /** Mode */
      mode?: ("default" | "acceptEdits") | null;
      /** Suggestion */
      suggestion?: number | null;
    };
    /** @enum {string} */
    PermissionMode: "default" | "acceptEdits" | "plan" | "auto";
    /**
     * PermissionSuggestion
     * @description A rule Claude suggests for "always allow"; ``index`` is its position in the request,
     *     ``rule`` is passed back to the CLI verbatim. Only ``localSettings`` ones are offered (D5).
     */
    PermissionSuggestion: {
      /** Destination */
      destination: string;
      /** Index */
      index: number;
      rule: components["schemas"]["pydantic__types__JsonValue"];
    };
    /** PlanEndpoint */
    PlanEndpoint: {
      /** Resource */
      resource: string | null;
      /** Service */
      service: string;
      /** Url */
      url: string | null;
    };
    /**
     * PlanView
     * @description The plan's version (AC-1.4): ``v<amendments + 1>``. ``version`` is None and ``problem``
     *     says why when ``plan.md`` could not be read (larger than its cap).
     */
    PlanView: {
      /**
       * Amendments
       * @default []
       */
      amendments: components["schemas"]["AmendmentView"][];
      /** Problem */
      problem?: string | null;
      /** Version */
      version: number | null;
    };
    /**
     * PlatformSyncRequest
     * @description The empty JSON body of the sync: a cross-site form cannot send one (S7).
     */
    PlatformSyncRequest: Record<string, never>;
    /**
     * PlatformSyncResult
     * @description What one platform sync did: the pin before and after, and ``hub sync``'s report.
     */
    PlatformSyncResult: {
      /** Changed Files */
      changed_files: string[];
      /** Exit Code */
      exit_code: number;
      /** Hub Id */
      hub_id: string;
      /** Ok */
      ok: boolean;
      /** Output */
      output: string[];
      /** Previous Version */
      previous_version: string | null;
      /** Version */
      version: string;
    };
    /** PollEntry */
    PollEntry: {
      /** At */
      at: string | null;
      /** Attempt */
      attempt: number | null;
      /** Held */
      held: boolean | null;
      /** Node */
      node: string;
      /** Poll */
      poll: number | null;
    };
    /**
     * PreflightRun
     * @description One preflight run of a ticket: when it ran, the plan version and commit it checked, the
     *     blocker outcomes it read, the input it was given (a discovery or a declined change's note,
     *     ``input_text``; for ``none``, null or a note such as an approval another one superseded,
     *     two-level-flows A23), the drift it found with its local notes (at least one for
     *     ``local``), the change request it opened (required for ``plan``, unless a plain check with a
     *     note: a superseded approval's re-check, A24) and the workflow
     *     run it belongs to.
     */
    PreflightRun: {
      /** Blockers Read */
      blockers_read: components["schemas"]["TicketKey"][];
      /** Change Request */
      change_request: number | null;
      commit: components["schemas"]["Commit"];
      /**
       * Drift
       * @enum {string}
       */
      drift: "none" | "local" | "plan";
      /**
       * Input
       * @enum {string}
       */
      input: "none" | "discovery" | "declined_change";
      input_text: components["schemas"]["OneLine1000"] | null;
      /** Local Notes */
      local_notes: components["schemas"]["OneLine1000"][];
      /** Plan Version */
      plan_version: number;
      /**
       * Ran At
       * Format: date-time
       */
      ran_at: string;
      run_id: components["schemas"]["RunId"];
    };
    /**
     * PreflightView
     * @description A ticket's ``preflight.json``: every run, oldest first, or why it could not be read
     *     (``runs`` then empty).
     */
    PreflightView: {
      /** Problem */
      problem: string | null;
      /** Runs */
      runs: components["schemas"]["PreflightRun"][];
    };
    /** @enum {string} */
    Preset: "local" | "staging" | "production" | "mine" | "other";
    /**
     * Problem
     * @description One problem of a session and the event it comes from.
     *
     *     ``where`` is the command head, path, pattern, URL, MCP tool or skill of the paired tool
     *     call (derived on read, at most 120 characters); ``message`` is the stored ``error_message``,
     *     else ``error_line``, else the rule or the gate's command and exit code.
     */
    Problem: {
      actor: components["schemas"]["Actor"];
      at: components["schemas"]["ApiTimestamp"];
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      event_id: components["schemas"]["EventId"];
      kind: components["schemas"]["ProblemKind"];
      /** Message */
      message: string | null;
      resolution: components["schemas"]["Resolution"];
      resolved_by_event_id?: components["schemas"]["EventId"] | null;
      /** Tool */
      tool: string | null;
      /** Where */
      where: string | null;
    };
    /**
     * ProblemCounts
     * @description A session's problems by owner-facing status (S4, E5); ``handled`` = recovered or
     *     continued by the agent.
     */
    ProblemCounts: {
      /**
       * By You
       * @default 0
       */
      by_you: number;
      /**
       * Handled
       * @default 0
       */
      handled: number;
      /**
       * Needs You
       * @default 0
       */
      needs_you: number;
      /**
       * Open
       * @default 0
       */
      open: number;
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
     * ProblemKind
     * @description What went wrong (S4 with E4).
     * @enum {string}
     */
    ProblemKind:
      | "tool_failed"
      | "command_exit"
      | "guard_denied"
      | "guard_ask_open"
      | "guard_ask_declined"
      | "interrupted"
      | "gate_failed"
      | "hook_failed";
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
    /** ProposalEntry */
    ProposalEntry: {
      /** Investigation */
      investigation: number;
      /** Options */
      options: components["schemas"]["OptionEntry"][];
      /** Proposal */
      proposal: number;
    };
    /**
     * ProposalView
     * @description Claude's proposal for the scenario: the document it wrote, checked as Save would check
     *     it (never written to the scenario file until the owner accepts it and saves).
     */
    ProposalView: {
      check: components["schemas"]["ValidateResult"] | null;
      /** Document */
      document: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
      } | null;
      /** Path */
      path: string;
      /** Problem */
      problem?: string | null;
    };
    /** @enum {string} */
    ProposedAccess: "read" | "ask" | "write";
    /**
     * ProposedAddress
     * @description A service's address in one environment: a URL or a resource name.
     */
    ProposedAddress: {
      /** Address */
      address: string;
      /** Environment */
      environment: string;
      /**
       * Evidence
       * @default []
       */
      evidence: components["schemas"]["Evidence"][];
      /** Note */
      note?: string | null;
      status: components["schemas"]["ItemStatus"];
      /** Yours */
      yours: string | null;
    };
    /**
     * ProposedEnvironment
     * @description An environment Claude found. ``access`` and ``production`` come from ``preset``, never
     *     from Claude alone; ``yours`` describes the declared one when ``status`` is ``differs``.
     */
    ProposedEnvironment: {
      access: components["schemas"]["ProposedAccess"];
      /** Aws Profile */
      aws_profile?: string | null;
      /** Description */
      description?: string | null;
      /** Env File */
      env_file?: string | null;
      /**
       * Evidence
       * @default []
       */
      evidence: components["schemas"]["Evidence"][];
      /** Name */
      name: string;
      preset: components["schemas"]["Preset"];
      /** Production */
      production: boolean;
      status: components["schemas"]["ItemStatus"];
      /** Yours */
      yours: string | null;
    };
    /**
     * ProposedService
     * @description A service of a picked repo; ``declared`` when it and every address are declared already,
     *     ``differs`` when it is declared but an address is new or different.
     */
    ProposedService: {
      /**
       * Addresses
       * @default []
       */
      addresses: components["schemas"]["ProposedAddress"][];
      /** Description */
      description?: string | null;
      /**
       * Evidence
       * @default []
       */
      evidence: components["schemas"]["Evidence"][];
      /** Kind */
      kind?: string | null;
      /** Name */
      name: string;
      /** Repo */
      repo: string;
      status: components["schemas"]["ItemStatus"];
    };
    /**
     * PublishDraftBody
     * @description ``POST .../skills/drafts/{draft_id}/publish``: ``target`` the item the draft edits, or
     *     ``null`` for a new item (stated, never left out); ``confirm_managed`` as for a restore (S9),
     *     only JSON ``true`` confirms.
     */
    PublishDraftBody: {
      /**
       * Confirm Managed
       * @default false
       */
      confirm_managed: boolean;
      target: components["schemas"]["PublishTarget"] | null;
    };
    /**
     * PublishTarget
     * @description The item a Publish edits, by its catalog id (``kind/source/name``).
     */
    PublishTarget: {
      kind: components["schemas"]["ItemKind"];
      /** Name */
      name: string;
      /** Source */
      source: string;
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
    /** @enum {string} */
    Readiness:
      | "can_start"
      | "in_progress"
      | "waiting"
      | "done"
      | "canceled"
      | "in_cycle"
      | "epic"
      | "unknown";
    /** @enum {string} */
    RecordBy: "web" | "timeout" | "closed" | "driver" | "server";
    /** @enum {string} */
    RecordKind:
      | "init"
      | "text"
      | "thinking"
      | "tool.call"
      | "tool.result"
      | "todos"
      | "task"
      | "permission.request"
      | "result"
      | "error"
      | "exited"
      | "user.message"
      | "permission.decision"
      | "interrupt"
      | "settings"
      | "close"
      | "log.truncated"
      | "cloud.start"
      | "cloud.followup";
    /**
     * RejectLearningBody
     * @description ``POST /learnings/{learning_id}/reject``: why, 1 to 300 characters once stripped.
     */
    RejectLearningBody: {
      /** Reason */
      reason: string;
    };
    /**
     * Relation
     * @description A link to another item of the catalog (Uses / Used by).
     */
    Relation: {
      /** Id */
      id: string;
      kind: components["schemas"]["ItemKind"];
      /** Name */
      name: string;
      /** Source */
      source: string;
    };
    /**
     * RemoveEndpoint
     * @description A service's endpoint in one environment, or the whole service when none is named.
     */
    RemoveEndpoint: {
      /** Environment */
      environment?: string | null;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "remove_endpoint";
      /** Repo */
      repo: string;
      scope: components["schemas"]["Scope"];
      /** Service */
      service: string;
    };
    /**
     * RemoveEnvironment
     * @description An environment no endpoint uses any more.
     */
    RemoveEnvironment: {
      /** Name */
      name: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "remove_environment";
      scope: components["schemas"]["Scope"];
    };
    /**
     * RenameEnvironment
     * @description A new name for an environment; its endpoints in the same file follow it.
     */
    RenameEnvironment: {
      /** Name */
      name: string;
      /** New Name */
      new_name: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "rename_environment";
      scope: components["schemas"]["Scope"];
    };
    /**
     * RepoChanges
     * @description One repository's changes against its base. ``root`` is the folder git ran in, ``branch``
     *     its checked-out branch (null when detached), ``base`` the ref the branch is compared with
     *     (``origin/main``…, null when none was found: then nothing is compared and ``files`` is
     *     empty), ``base_sha`` the commit the branch forked from, ``head_sha`` the branch's last
     *     commit. ``truncated`` says commits or files were left out past the bounds.
     *
     *     ``source`` is ``worktree`` when git read the checkout as it is now (uncommitted changes
     *     included), ``recorded`` when that folder is gone and the review reads the commits it
     *     recorded from the repo's own checkout (``root`` is still the old folder, so the paths match
     *     the chat's). ``pull_request`` is the branch's pull request, when one is found.
     */
    RepoChanges: {
      /** Base */
      base?: string | null;
      /** Base Sha */
      base_sha?: string | null;
      /** Branch */
      branch?: string | null;
      /**
       * Commits
       * @default []
       */
      commits: components["schemas"]["RepoCommit"][];
      /**
       * Files
       * @default []
       */
      files: components["schemas"]["RepoFileChange"][];
      /** Head Sha */
      head_sha?: string | null;
      /** Label */
      label: string;
      pull_request?: components["schemas"]["RepoPullRequest"] | null;
      /** Root */
      root: string;
      /** @default worktree */
      source: components["schemas"]["RepoSource"];
      /**
       * Truncated
       * @default false
       */
      truncated: boolean;
    };
    /**
     * RepoCommit
     * @description A commit of the branch since its base, newest first.
     */
    RepoCommit: {
      /** Author */
      author: string;
      /** Authored At */
      authored_at: string;
      /** Sha */
      sha: string;
      /** Subject */
      subject: string;
    };
    /**
     * RepoCommitDiff
     * @description ``GET /agent-sessions/{id}/repo-changes/commit``: what one commit changed in one file, as a
     *     unified diff with the file's line numbers. ``diff`` is null for a binary file or one past
     *     ``REPO_DIFF_MAX_BYTES``, empty when the commit did not touch the file.
     */
    RepoCommitDiff: {
      /**
       * Binary
       * @default false
       */
      binary: boolean;
      /** Diff */
      diff?: string | null;
      /** Path */
      path: string;
      /** Sha */
      sha: string;
    };
    /**
     * RepoConfigView
     * @description One repo of ``hub.json`` with its effective branch and conventions.
     */
    RepoConfigView: {
      branch: components["schemas"]["PatternView"];
      /** Check */
      check: string;
      /** Check Fast */
      check_fast: string | null;
      /** Check Fast Timeout */
      check_fast_timeout: number | null;
      commit_title: components["schemas"]["PatternView"];
      default_branch: components["schemas"]["SourcedValue"];
      /** Dir */
      dir: string;
      /** Github */
      github: string;
      /** Index */
      index: number;
      pr_title: components["schemas"]["PatternView"];
      /** Role */
      role: string;
    };
    /**
     * RepoFileChange
     * @description A file that differs from the base: committed on the branch, staged, unstaged or
     *     untracked. ``path`` is absolute (the repository's folder joined with git's path), as Claude's
     *     file tools name it; ``old_path`` the name before a rename. ``diff`` is the unified diff from
     *     the base to the working tree, with the file's line numbers; null for a binary file or one
     *     past ``REPO_DIFF_MAX_BYTES``. ``fingerprint`` changes whenever the diff does (a review mark
     *     is kept against it). ``commits`` are the branch's commits that touched it, newest first;
     *     ``uncommitted`` says the working tree differs from ``HEAD`` too.
     */
    RepoFileChange: {
      /** Added */
      added: number;
      /**
       * Binary
       * @default false
       */
      binary: boolean;
      /**
       * Commits
       * @default []
       */
      commits: components["schemas"]["RepoFileCommit"][];
      /** Diff */
      diff?: string | null;
      /** Fingerprint */
      fingerprint: string;
      /** Old Path */
      old_path?: string | null;
      /** Path */
      path: string;
      /** Removed */
      removed: number;
      status: components["schemas"]["RepoFileStatus"];
      /**
       * Uncommitted
       * @default false
       */
      uncommitted: boolean;
    };
    /**
     * RepoFileCommit
     * @description A commit that touched a file, and the lines it added and removed there.
     */
    RepoFileCommit: {
      /** Added */
      added: number;
      /** Removed */
      removed: number;
      /** Sha */
      sha: string;
    };
    /** @enum {string} */
    RepoFileStatus: "added" | "modified" | "deleted" | "renamed";
    /**
     * RepoFileText
     * @description ``GET /agent-sessions/{id}/repo-changes/file``: a file as it is at one commit (the base a
     *     pull request's diff is read against), so a review can show the lines its diff leaves out.
     *     ``text`` is null for a binary file, one past ``REPO_DIFF_MAX_BYTES`` or one the commit does
     *     not have.
     */
    RepoFileText: {
      /**
       * Binary
       * @default false
       */
      binary: boolean;
      /** Path */
      path: string;
      /** Sha */
      sha: string;
      /** Text */
      text?: string | null;
    };
    /**
     * RepoPullRequest
     * @description The branch's pull request on GitHub: its number, link, state (``OPEN``, ``MERGED``,
     *     ``CLOSED``) and the commit it is at.
     */
    RepoPullRequest: {
      /** Head Sha */
      head_sha?: string | null;
      /** Number */
      number: number;
      /** State */
      state: string;
      /** Url */
      url: string;
    };
    /** @enum {string} */
    RepoSource: "worktree" | "recorded";
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
    /** @enum {string} */
    RequestKind: "tool" | "ask_user_question" | "plan_approval";
    /**
     * Resolution
     * @description How a problem ended (S4 with E5).
     *
     *     ``recovered`` and ``agent_continued`` show as "Handled by the agent", ``open`` as "Agent is
     *     on it", ``needs_you`` as "Needs you" and ``by_you`` as "You interrupted" or "You declined".
     * @enum {string}
     */
    Resolution: "recovered" | "agent_continued" | "open" | "needs_you" | "by_you";
    /**
     * RestoreVersionBody
     * @description ``POST .../versions/{version_id}/restore``: ``confirm_managed`` true writes over a unit
     *     ``hub.lock`` manages (S9), after the web's warning; only JSON ``true`` confirms.
     */
    RestoreVersionBody: {
      /**
       * Confirm Managed
       * @default false
       */
      confirm_managed: boolean;
    };
    /**
     * ResumableList
     * @description ``GET /agent-sessions/resumable``: past Claude sessions of a workdir, newest first.
     */
    ResumableList: {
      /** Items */
      items: components["schemas"]["PastSession"][];
    };
    /**
     * ReviewTarget
     * @description What a session's review read in one repository, kept so the review outlives the folder:
     *     the hub repo (``repo``, its ``hub.json`` name) and the checkout it read (``root``, a worktree
     *     that may be removed later), its branch, the ``base`` it was compared with and the commit it
     *     forked from (``base_sha``), the last commit read (``head_sha``) and the branch's pull request
     *     once one is found. With these the review reads the branch's commits from the repo's own
     *     checkout once the worktree is gone.
     */
    ReviewTarget: {
      /** Base */
      base?: string | null;
      /** Base Sha */
      base_sha?: string | null;
      /** Branch */
      branch?: string | null;
      /** Head Sha */
      head_sha?: string | null;
      /** Label */
      label: string;
      /** Pr Number */
      pr_number?: number | null;
      /** Pr Url */
      pr_url?: string | null;
      /** Repo */
      repo?: string | null;
      /** Root */
      root: string;
    };
    /**
     * RunAccepted
     * @description What a run command did: the run, its project and the action taken.
     */
    RunAccepted: {
      action: components["schemas"]["RunAction"];
      /** Project */
      project: string;
      /** Run Id */
      run_id: string;
    };
    /** @enum {string} */
    RunAction: "start" | "cancel" | "resume" | "abandon";
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
    /** @enum {string} */
    RunDelivery: "delivered" | "no_changes" | "blocked" | "failed";
    /**
     * RunEnvironment
     * @description The environment a run's own start record names (AGH-350 E-15, the best-effort banner),
     *     with its access and production flag in the hub's effective config as read now; both are
     *     ``None`` when that config cannot be read or no longer declares it.
     */
    RunEnvironment: {
      /** Access */
      access: string | null;
      /** Name */
      name: string;
      /** Production */
      production: boolean | null;
    };
    /**
     * RunFailure
     * @description Where and why a run failed, and the event to open ("Open failing moment").
     */
    RunFailure: {
      /** Diagnosis Comment Url */
      diagnosis_comment_url?: string | null;
      failing_event_id: components["schemas"]["EventId"] | null;
      failure_kind?: components["schemas"]["FailureKind"] | null;
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
    RunId: string;
    /** @enum {string} */
    RunKind: "workflow" | "scenario";
    /** @enum {string} */
    RunStatus: "done" | "failed" | "cancelled";
    /**
     * RunStep
     * @description One step attempt, keyed ``(key, attempt)``; a loop back into verify is attempt 2.
     */
    RunStep: {
      /** Attempt */
      attempt: number;
      ended_at: components["schemas"]["ApiTimestamp"] | null;
      failure_kind?: components["schemas"]["FailureKind"] | null;
      key: components["schemas"]["StepKey"];
      kind?: components["schemas"]["StepKind"] | null;
      /** Max Attempts */
      max_attempts: number;
      /** Reason */
      reason?: string | null;
      /**
       * Session Ids
       * @default []
       */
      session_ids: string[];
      skip_cause?: components["schemas"]["SkipCause"] | null;
      started_at: components["schemas"]["ApiTimestamp"];
      status: components["schemas"]["StepStatus"];
    };
    /**
     * SaveRequest
     * @description A save: the pack, the document and the content hash of the file the builder last read
     *     (None for a new scenario).
     */
    SaveRequest: {
      /** Base Content Hash */
      base_content_hash?: string | null;
      /** Document */
      document: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Input"];
      };
      /** Pack */
      pack: string;
    };
    /** SaveResult */
    SaveResult: {
      /** Changed */
      changed: boolean;
      /** Content Hash */
      content_hash: string;
      /** Path */
      path: string;
      /** Revision */
      revision: number;
      /** Versioned */
      versioned: boolean;
      /** Yaml */
      yaml: string;
    };
    /**
     * ScenarioActionView
     * @description An action the scenario's steps call (``ref`` as a step writes it), as the hub's files
     *     hold it now: its facts, whether it is committed (``draft`` else, with the line that
     *     accepts it), and the text of its document and script (each cut at ``ACTION_TEXT_BYTES``);
     *     ``problem`` says why it does not resolve, the other facts then empty.
     */
    ScenarioActionView: {
      /** Accept Command */
      accept_command?: string | null;
      /** Description */
      description?: string | null;
      /** Document Text */
      document_text?: string | null;
      /**
       * Draft
       * @default false
       */
      draft: boolean;
      /** Effect */
      effect?: string | null;
      /**
       * Inputs
       * @default []
       */
      inputs: components["schemas"]["ActionInputSpec"][];
      /** Name */
      name: string;
      /** Output Format */
      output_format?: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
      };
      /** Pack */
      pack?: string | null;
      /** Path */
      path?: string | null;
      /** Problem */
      problem?: string | null;
      /** Ref */
      ref: string;
      /** Runtime */
      runtime?: string | null;
      /** Script */
      script?: string | null;
      /** Script Text */
      script_text?: string | null;
      /**
       * Script Truncated
       * @default false
       */
      script_truncated: boolean;
      /** Timeout */
      timeout?: string | null;
    };
    /**
     * ScenarioCatalogView
     * @description The scenarios that load, by project then name, and every file that does not.
     */
    ScenarioCatalogView: {
      /** Items */
      items: components["schemas"]["ScenarioSummary"][];
      /** Problems */
      problems: components["schemas"]["WorkflowProblemView"][];
    };
    /**
     * ScenarioDetail
     * @description A scenario's steps, its scenario runs, newest first, and the environments it can be
     *     planned in (empty when ``hub.local.json`` or ``hub.json`` cannot be read), with its file
     *     (hub-relative ``path`` and raw ``document_text``) and the actions its steps call.
     */
    ScenarioDetail: {
      /**
       * Actions
       * @default []
       */
      actions: components["schemas"]["ScenarioActionView"][];
      /** Content Hash */
      content_hash?: string | null;
      /** Description */
      description: string | null;
      /** Document */
      document?: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
      } | null;
      /** Document Text */
      document_text?: string | null;
      /**
       * Environments
       * @default []
       */
      environments: components["schemas"]["ScenarioEnvironment"][];
      /**
       * Inputs
       * @default []
       */
      inputs: components["schemas"]["WorkflowInputView"][];
      last_run?: components["schemas"]["ScenarioRunRef"] | null;
      /** Name */
      name: string;
      /** Node Count */
      node_count: number;
      /** Pack */
      pack: string;
      /** Path */
      path?: string | null;
      /** Project */
      project: string;
      /** Revision */
      revision: number;
      /** Runs */
      runs: components["schemas"]["ScenarioRunRef"][];
      /** Steps */
      steps: components["schemas"]["ScenarioStepView"][];
    };
    /**
     * ScenarioEnvironment
     * @description An environment the project's hub declares, as the effective config reads now, with the
     *     values that fill a scenario's inputs of the same name there (hub.local.json's over
     *     hub.json's, per key).
     */
    ScenarioEnvironment: {
      /** Access */
      access: string;
      /** Name */
      name: string;
      /** Production */
      production: boolean;
      /** Values */
      values?: {
        [key: string]: string;
      };
    };
    /** @enum {string} */
    ScenarioMode: "interactive" | "regression";
    /**
     * ScenarioPlanRequest
     * @description The body of a plan: the environment and the inputs (``--input``).
     */
    ScenarioPlanRequest: {
      /** Environment */
      environment: string;
      inputs?: components["schemas"]["Inputs"];
    };
    /**
     * ScenarioPlanRow
     * @description One step of a plan, as ``hub scenario plan --json`` prints it, and whether its action
     *     needs acceptance (a draft), with the commit line that accepts it (AM-5).
     */
    ScenarioPlanRow: {
      /** Accept Command */
      accept_command: string | null;
      /** Action */
      action: string;
      /** Args */
      args: {
        [key: string]: string;
      };
      /** Content Hash */
      content_hash: string;
      /** Decision */
      decision: string;
      /** Draft */
      draft: boolean;
      /** Effect */
      effect: string;
      /** Endpoints */
      endpoints: {
        [key: string]: components["schemas"]["PlanEndpoint"];
      };
      /** Every */
      every: string | null;
      /** Needs Acceptance */
      needs_acceptance: boolean;
      /** Plan */
      plan: string;
      /** Reason */
      reason: string | null;
      /** Reason Kind */
      reason_kind: string | null;
      /** Step */
      step: string;
      /** Timeout */
      timeout: string | null;
      /** Type */
      type: string;
    };
    /**
     * ScenarioPlanView
     * @description A scenario planned in one environment; ``denied`` when it may not start.
     */
    ScenarioPlanView: {
      /** Access */
      access: string | null;
      /** Denied */
      denied: boolean;
      /** Environment */
      environment: string;
      /** Problems */
      problems: string[];
      /** Production */
      production: boolean;
      /** Project */
      project: string;
      /** Rows */
      rows: components["schemas"]["ScenarioPlanRow"][];
      /** Scenario */
      scenario: string;
    };
    /**
     * ScenarioRunDetail
     * @description A scenario run as its record holds it. ``status`` is its end's, ``None`` while it has
     *     none; ``open_investigation`` is the number of the investigation waiting for an answer.
     */
    ScenarioRunDetail: {
      /**
       * Actions
       * @default []
       */
      actions: components["schemas"]["ActionCallEntry"][];
      /** Captures */
      captures: components["schemas"]["CaptureEntry"][];
      /** Decisions */
      decisions: components["schemas"]["DecisionEntry"][];
      /** Environment */
      environment: string | null;
      /** Findings */
      findings: components["schemas"]["FindingEntry"][];
      /** Investigations */
      investigations: components["schemas"]["InvestigationEntry"][];
      /** Mode */
      mode: string | null;
      /** Open Investigation */
      open_investigation: number | null;
      /** Pack */
      pack: string | null;
      /** Paused Step */
      paused_step: string | null;
      /** Polls */
      polls: components["schemas"]["PollEntry"][];
      /** Project */
      project: string;
      proposal: components["schemas"]["ProposalEntry"] | null;
      /** Run Id */
      run_id: string;
      /** Scenario */
      scenario: string | null;
      /** Status */
      status: string | null;
      /** Timeline */
      timeline: components["schemas"]["TimelineEntry"][];
      /** Workarounds */
      workarounds: components["schemas"]["WorkaroundEntry"][];
    };
    /**
     * ScenarioRunRef
     * @description A scenario run as the folded events show it, with the environment and mode its start
     *     record names (``None`` when the record cannot be read).
     */
    ScenarioRunRef: {
      ended_at: components["schemas"]["ApiTimestamp"] | null;
      /** Environment */
      environment?: string | null;
      /** Mode */
      mode?: string | null;
      /** Run Id */
      run_id: string;
      started_at: components["schemas"]["ApiTimestamp"];
      status: components["schemas"]["WorkflowRunStatus"];
    };
    /**
     * ScenarioStartRequest
     * @description The body of a start: a plan's, and the mode (``interactive`` by default).
     */
    ScenarioStartRequest: {
      /** Environment */
      environment: string;
      inputs?: components["schemas"]["Inputs"];
      /** @default interactive */
      mode: components["schemas"]["ScenarioMode"];
    };
    /**
     * ScenarioStepView
     * @description A step in declaration order: its type, the action it calls (an action or expect step)
     *     and the steps it waits for, with the keys of its call as the document writes them (``with``
     *     values, ``capture`` refs, an expect's ``every``/``timeout``/``until_when``, ``retry``).
     */
    ScenarioStepView: {
      /** Action */
      action: string | null;
      /** Capture */
      capture?: {
        [key: string]: string;
      };
      /** Depends On */
      depends_on: string[];
      /** Description */
      description?: string | null;
      /** Every */
      every?: string | null;
      /** Id */
      id: string;
      retry?: components["schemas"]["StepRetryView"] | null;
      /** Timeout */
      timeout?: string | null;
      /** Type */
      type: string;
      /** Until When */
      until_when?: string | null;
      /** With */
      with?: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
      };
    };
    /**
     * ScenarioSummary
     * @description A scenario of a project's hub, its pack and its last scenario run.
     */
    ScenarioSummary: {
      /** Description */
      description: string | null;
      /**
       * Inputs
       * @default []
       */
      inputs: components["schemas"]["WorkflowInputView"][];
      last_run?: components["schemas"]["ScenarioRunRef"] | null;
      /** Name */
      name: string;
      /** Node Count */
      node_count: number;
      /** Pack */
      pack: string;
      /** Project */
      project: string;
      /** Revision */
      revision: number;
    };
    /** @enum {string} */
    Scope: "team" | "local";
    /**
     * Screenshot
     * @description A PNG image sent with a message (a screenshot, or an image pasted in the chat),
     *     base64-encoded; its decoded size and signature are checked by ``decode_screenshot`` (413,
     *     422).
     */
    Screenshot: {
      /** Data */
      data: string;
      /**
       * Media Type
       * @constant
       */
      media_type: "image/png";
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
     * SendMessage
     * @description ``POST /{id}/messages``: one user message (byte limit checked, 413), with the files and
     *     images attached to it, sent to Claude before the text.
     */
    SendMessage: {
      /** Files */
      files?: components["schemas"]["MessageFile"][] | null;
      /** Screenshots */
      screenshots?: components["schemas"]["Screenshot"][] | null;
      /** Text */
      text: string;
    };
    /**
     * ServiceAddress
     * @description Where a service is reached in one environment: a URL (holds ``://``) or a resource name.
     */
    ServiceAddress: {
      /** Address */
      address: string;
      /** Environment */
      environment: string;
      /** Note */
      note?: string | null;
    };
    /**
     * Session
     * @description A session folded from its events (status, counts, tokens, estimated cost).
     *
     *     ``agent`` is deprecated: ``actors`` and ``label`` say who acted and what the session is about.
     *     ``agent_session_id`` is the agent session ``hub web`` drives it from, when there is one.
     *     The tile fields (``waiting_reason`` to ``sparkline_60s``) are what a Live tile shows,
     *     derived by the same code (D5); lists and the session read fill them, other reads leave them
     *     ``null``. ``sparkline_60s`` is ``null`` once the session has ended.
     */
    Session: {
      /**
       * Actors
       * @default []
       */
      actors: components["schemas"]["Actor"][];
      /**
       * Agent
       * @deprecated
       */
      agent: string;
      /** Agent Session Id */
      agent_session_id?: string | null;
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
      /** Failing Notice */
      failing_notice?: string | null;
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
      label?: components["schemas"]["SessionLabel"] | null;
      /** Last Action */
      last_action?: string | null;
      last_activity_at: components["schemas"]["ApiTimestamp"];
      /** Last Tool */
      last_tool?: string | null;
      /** Learnings Proposed */
      learnings_proposed: number;
      /** Model */
      model: string | null;
      /** Needs You Problem */
      needs_you_problem?: string | null;
      outcome: components["schemas"]["Outcome"] | null;
      /** Parent Session Id */
      parent_session_id?: string | null;
      pr?: components["schemas"]["PullRequestRef"] | null;
      /**
       * @default {
       *       "by_you": 0,
       *       "handled": 0,
       *       "needs_you": 0,
       *       "open": 0
       *     }
       */
      problems: components["schemas"]["ProblemCounts"];
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
      /** Sparkline 60S */
      sparkline_60s?: number[] | null;
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
      /** Waiting Reason */
      waiting_reason?: string | null;
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
     * SessionLabel
     * @description What a session is about, derived on read (S1): issue, workflow, repo and branch.
     *
     *     ``issue`` is ``<TEAM>-<n>`` found in ``branch`` or ``worktree`` with the hub's tracker teams,
     *     else ``None``, never a guess. ``workflow`` is the session's main slash command or skill
     *     (``/feature``); ``workflows`` lists every one in order. ``worktree`` is the folder name under
     *     ``.claude/worktrees/`` in the session's ``cwd``. ``title`` is the session's short name: the
     *     one the user set (``/rename``), else the one Claude Code wrote (ADR 0035), else ``None``.
     */
    SessionLabel: {
      /** Branch */
      branch: string | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Issue */
      issue: string | null;
      /** Repo */
      repo: string | null;
      /** Title */
      title?: string | null;
      /** Workflow */
      workflow: string | null;
      /** Workflows */
      workflows: string[];
      /** Worktree */
      worktree: string | null;
    };
    /**
     * SessionProblems
     * @description The problems route: up to 5 deterministic summary lines, then every problem by time.
     *
     *     ``summary`` is empty when the session has no problem.
     */
    SessionProblems: {
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      /** Items */
      items: components["schemas"]["Problem"][];
      /** Session Id */
      session_id: string;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      /** Summary */
      summary: components["schemas"]["SummaryLine"][];
    };
    /**
     * SessionRepoChanges
     * @description ``GET /agent-sessions/{id}/repo-changes``: each repository the session worked in, and the
     *     ones that could not be read (``warnings``, named by folder label).
     */
    SessionRepoChanges: {
      /**
       * Repos
       * @default []
       */
      repos: components["schemas"]["RepoChanges"][];
      /**
       * Warnings
       * @default []
       */
      warnings: string[];
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
     * SessionSettings
     * @description ``POST /{id}/settings``: a new mode, a new model, or both (at least one).
     */
    SessionSettings: {
      mode?: components["schemas"]["PermissionMode"] | null;
      model?: components["schemas"]["ModelName"] | null;
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
     * SetEnvironment
     * @description A change to an environment: a field left out stays; an empty text removes the key.
     *
     *     On a ``hub.json`` environment, the ``local`` scope may change only ``access`` (stricter)
     *     and ``values`` (the developer's, which win per key over the team's).
     */
    SetEnvironment: {
      access?: components["schemas"]["Access"] | null;
      /** Aws Profile */
      aws_profile?: string | null;
      /** Credential Env */
      credential_env?: string[] | null;
      /** Description */
      description?: string | null;
      /** Env File */
      env_file?: string | null;
      /** Name */
      name: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "set_environment";
      /** Production */
      production?: boolean | null;
      scope: components["schemas"]["Scope"];
      /** Values */
      values?: {
        [key: string]: string;
      } | null;
    };
    /**
     * SetService
     * @description A change to a service: a field left out stays; an empty text removes the key.
     */
    SetService: {
      /** Description */
      description?: string | null;
      /** Kind */
      kind?: string | null;
      /** New Name */
      new_name?: string | null;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "set_service";
      /** Repo */
      repo: string;
      scope: components["schemas"]["Scope"];
      /** Service */
      service: string;
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
    SingleEdit:
      | components["schemas"]["AddEnvironment"]
      | components["schemas"]["SetEnvironment"]
      | components["schemas"]["RenameEnvironment"]
      | components["schemas"]["RemoveEnvironment"]
      | components["schemas"]["AddEndpoint"]
      | components["schemas"]["RemoveEndpoint"]
      | components["schemas"]["AddService"]
      | components["schemas"]["SetService"];
    /**
     * SkillCatalog
     * @description A project's skills, agents and hooks in stable order (kind, name, source).
     *
     *     ``truncated`` says a bound stopped the listing or the reads; ``notice`` is one line for the
     *     owner (an empty hub, a file not read), or None.
     */
    SkillCatalog: {
      /**
       * External Plugins
       * @default []
       */
      external_plugins: components["schemas"]["ExternalPlugin"][];
      /** Items */
      items: components["schemas"]["CatalogItem"][];
      /** Notice */
      notice?: string | null;
      /** Project */
      project: string;
      /**
       * Truncated
       * @default false
       */
      truncated: boolean;
      /**
       * Usage Days
       * @default 30
       */
      usage_days: number;
    };
    /**
     * SkillDetail
     * @description One item's detail page (D4, AC-164.8): the card's fields and what the file says.
     *
     *     ``body`` is the text after the frontmatter and ``raw`` the whole file decoded as UTF-8; both
     *     are None when the file was not read (too large, not regular, not text, over budget). A hook
     *     has ``hook`` set and no body, structure or cost.
     */
    SkillDetail: {
      /**
       * Active
       * @default true
       */
      active: boolean;
      /**
       * Allowed Tools
       * @default []
       */
      allowed_tools: string[];
      /** Argument Hint */
      argument_hint?: string | null;
      /** Body */
      body?: string | null;
      context_cost?: components["schemas"]["ContextCost"] | null;
      /** Description */
      description: string | null;
      /** Description Full */
      description_full?: string | null;
      /**
       * Diagnostics
       * @default []
       */
      diagnostics: components["schemas"]["Diagnostic"][];
      /** Diagnostics Count */
      diagnostics_count: number;
      /**
       * Files
       * @default []
       */
      files: components["schemas"]["BundledFile"][];
      /**
       * Frontmatter
       * @default []
       */
      frontmatter: components["schemas"]["FrontmatterPair"][];
      hook?: components["schemas"]["HookFacts"] | null;
      /** Id */
      id: string;
      /** Invocation */
      invocation: string | null;
      kind: components["schemas"]["ItemKind"];
      /**
       * Linked From
       * @default []
       */
      linked_from: string[];
      lock?: components["schemas"]["LockFacts"] | null;
      mode: components["schemas"]["Mode"] | null;
      /** Model */
      model?: string | null;
      /** Name */
      name: string;
      origin: components["schemas"]["Origin"];
      /** Raw */
      raw?: string | null;
      /** Source */
      source: string;
      /** Source Path */
      source_path: string;
      state?: components["schemas"]["HookState"] | null;
      structure?: components["schemas"]["SkillStructure"] | null;
      /**
       * Toc
       * @default []
       */
      toc: components["schemas"]["TocEntry"][];
      /**
       * Tools
       * @default []
       */
      tools: string[];
      usage: components["schemas"]["Usage"] | null;
      /**
       * Used By
       * @default []
       */
      used_by: components["schemas"]["Relation"][];
      /**
       * Uses
       * @default []
       */
      uses: components["schemas"]["Relation"][];
      /** When To Use */
      when_to_use?: string | null;
    };
    SkillFrontmatterValue:
      | string
      | string[]
      | {
          [key: string]: string;
        };
    /**
     * SkillStructure
     * @description What the body's text says it does, derived heuristically (S6): labelled so in the UI.
     *
     *     ``dynamic_context`` counts the ``!`…``` and ```` ```! ```` blocks that run at invocation (shown
     *     as text, never run); ``truncated`` when steps past the bound were dropped.
     */
    SkillStructure: {
      /**
       * Agents
       * @default []
       */
      agents: string[];
      /**
       * Commands
       * @default []
       */
      commands: string[];
      /**
       * Dynamic Context
       * @default 0
       */
      dynamic_context: number;
      /**
       * Gates
       * @default []
       */
      gates: string[];
      /**
       * Skills
       * @default []
       */
      skills: string[];
      /**
       * Steps
       * @default []
       */
      steps: components["schemas"]["Step"][];
      /**
       * Truncated
       * @default false
       */
      truncated: boolean;
    };
    /** @enum {string} */
    SkipCause:
      | "upstream_failed"
      | "upstream_skipped"
      | "condition"
      | "condition_parse_error"
      | "prior_success";
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
     * SourcedEndpoint
     * @description A service's endpoint in one environment, and the file that declares it.
     */
    SourcedEndpoint: {
      endpoint: components["schemas"]["Endpoint"];
      /** Environment */
      environment: string;
      /** Source */
      source: string;
    };
    /**
     * SourcedEnvironment
     * @description An effective environment and its source: the file its effective ``access`` comes from.
     */
    SourcedEnvironment: {
      /**
       * Access
       * @enum {string}
       */
      access: "read" | "write" | "ask";
      credentials: components["schemas"]["Credentials"] | null;
      /** Description */
      description: string | null;
      /** Name */
      name: string;
      /** Production */
      production: boolean;
      /** Source */
      source: string;
      /** Team Access */
      team_access?: ("read" | "write" | "ask") | null;
      /** Values */
      values?: {
        [key: string]: string;
      };
    };
    /**
     * SourcedService
     * @description A repo's service with its endpoints from both files, the committed ones first.
     */
    SourcedService: {
      /** Description */
      description: string | null;
      /** Endpoints */
      endpoints: components["schemas"]["SourcedEndpoint"][];
      /** Kind */
      kind: string | null;
      /** Name */
      name: string;
      /** Repo */
      repo: string;
    };
    /**
     * SourcedValue
     * @description An effective value (None when no source gives one) and where it comes from.
     */
    SourcedValue: {
      source: components["schemas"]["ValueSource"];
      /** Team Value */
      team_value?: string | null;
      /** Value */
      value: string | null;
      /** Where */
      where: string;
    };
    /**
     * Stage
     * @description A state of the run's machine; any stage before ``REPORTED`` can end in ``FAILED``.
     * @enum {string}
     */
    Stage: "PICKED" | "WORKTREE" | "IMPLEMENTING" | "VERIFYING" | "PR_OPEN" | "REPORTED" | "FAILED";
    /**
     * StartCloud
     * @description ``POST /agent-sessions/cloud``: a task for ``claude --cloud``, passed as one argument.
     */
    StartCloud: {
      /** Project */
      project: string;
      /** Task */
      task: string;
      /** Workdir Id */
      workdir_id: string;
    };
    /**
     * StartEnvironmentDiscovery
     * @description ``POST /projects/{project}/environment-discoveries``: the repos to read (``hub.json``
     *     repo folders), the declared environments to look for, and whether Claude may suggest
     *     environments not declared yet.
     */
    StartEnvironmentDiscovery: {
      /**
       * Environments
       * @default []
       */
      environments: string[];
      /** Repos */
      repos: string[];
      /**
       * Suggest Environments
       * @default false
       */
      suggest_environments: boolean;
    };
    /**
     * StartRunRequest
     * @description The body of ``POST /workflow-runs``: a project's workflow and its inputs (always live).
     */
    StartRunRequest: {
      /** Inputs */
      inputs?: {
        [key: string]: components["schemas"]["InputValue"];
      };
      /** Project */
      project: string;
      /** Workflow */
      workflow: string;
    };
    /**
     * Step
     * @description One top-level ordered list item of a body (S6); ``index`` is 1-based, as ``#step-<n>``.
     *
     *     ``declared_type`` is the type the step states itself, when it starts with one; ``summary`` is
     *     the rest of its first line as plain text (Markdown marks dropped), empty when there is none.
     */
    Step: {
      /**
       * Agents
       * @default []
       */
      agents: string[];
      /**
       * Commands
       * @default []
       */
      commands: string[];
      declared_type?: components["schemas"]["StepType"] | null;
      /** Index */
      index: number;
      /**
       * Scripts
       * @default []
       */
      scripts: string[];
      /**
       * Skills
       * @default []
       */
      skills: string[];
      /**
       * Summary
       * @default
       */
      summary: string;
      /**
       * Tags
       * @default []
       */
      tags: components["schemas"]["StepTag"][];
      /** Title */
      title: string;
    };
    StepKey: string;
    /** @enum {string} */
    StepKind: "agent" | "shell" | "script" | "loop" | "loop_group" | "approval" | "wait" | "halt";
    /**
     * StepProgress
     * @description How much of a step is done: ``done`` of ``total`` (tickets, ACs, reviews).
     */
    StepProgress: {
      /** Done */
      done: number;
      /** Total */
      total: number;
    };
    /**
     * StepRetryView
     * @description A step's ``retry``: retries after the first attempt, the first delay (doubling each
     *     time) and which errors it retries.
     */
    StepRetryView: {
      /** Delay */
      delay: string;
      /** Max Attempts */
      max_attempts: number;
      /** On Error */
      on_error: string;
    };
    /** @enum {string} */
    StepState:
      | "done"
      | "partial"
      | "current"
      | "pending"
      | "skipped"
      | "unknown"
      | "blocked"
      | "unrecorded"
      | "waiting"
      | "stale";
    /** @enum {string} */
    StepStatus: "running" | "ok" | "failed" | "skipped";
    /** @enum {string} */
    StepTag: "gate" | "agent" | "command" | "script" | "human";
    /** @enum {string} */
    StepType: "agent" | "script" | "gate" | "human";
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
    TextUse: "off" | "optional" | "required";
    /**
     * TicketEdge
     * @description A "blocked by" edge to the ticket ``ref`` (a row's ``ref`` or an external issue id).
     */
    TicketEdge: {
      /** Ref */
      ref: string;
      source: components["schemas"]["EdgeSource"];
    };
    /**
     * TicketFlow
     * @description A ticket's seven steps in their fixed order (``ticket_flow.py``); ``current`` is where the
     *     ticket is: the first step neither done nor unrecorded, the last when every step is.
     *     ``signal`` is the one line that needs attention, from its preflight and the plan change
     *     requests (waiting for the owner, held, re-run needed, local drift), None when none.
     */
    TicketFlow: {
      current: components["schemas"]["TicketStepName"];
      /** Signal */
      signal?: string | null;
      /** Steps */
      steps: components["schemas"]["TicketStep"][];
    };
    TicketKey: string;
    /**
     * TicketPlan
     * @description The planning of the feature's tickets, every ticket named by its row's ``ref``.
     *
     *     ``layers`` are the parallel groups (Kahn's layers over tickets not done or canceled);
     *     ``can_start`` the first layer's tickets that wait on nothing and are not started yet;
     *     ``order`` the recommended order; ``waiting`` the tickets with a blocker not done;
     *     ``cycles`` each dependency cycle (left out of the layers); ``critical_path`` the longest
     *     chain of tickets not done; ``epics`` the rows that are a parent of other rows: they track
     *     the work, are left out of the layers and never block.
     */
    TicketPlan: {
      /** Can Start */
      can_start: string[];
      /** Critical Path */
      critical_path: string[];
      /** Cycles */
      cycles: string[][];
      /**
       * Epics
       * @default []
       */
      epics: string[];
      /** External Blockers */
      external_blockers: components["schemas"]["ExternalBlocker"][];
      /** Layers */
      layers: string[][];
      /** Order */
      order: string[];
      /** Waiting */
      waiting: string[];
      /** Warnings */
      warnings: string[];
    };
    /**
     * TicketRecords
     * @description ``GET /features/{project}/{slug}/tickets/{ticket}`` (two-level-flows A7, A20): what the
     *     ticket panel shows that no tickets row carries: ``preflight``, its record (None without one),
     *     and ``change_requests``, the plan change requests it asks or is held by, each with its
     *     evidence and proposal (``body``).
     */
    TicketRecords: {
      /** Change Requests */
      change_requests: components["schemas"]["ChangeRequestView"][];
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      preflight: components["schemas"]["PreflightView"] | null;
      /** Project */
      project: string;
      /** Slug */
      slug: string;
      /**
       * Sources Missing
       * @default []
       */
      sources_missing: components["schemas"]["EventSource"][];
      /** Ticket */
      ticket: string;
    };
    /**
     * TicketRow
     * @description One ticket of the feature.
     *
     *     ``key`` is the plan's draft key (None for a ticket only Linear or ``linear`` lists), ``id``
     *     the tracker identifier (None until created). ``title``, ``state``, ``assignee`` and ``url``
     *     come from Linear when read, else ``title`` from the plan and the others None. ``acs`` are the
     *     AC ids whose ``ticket`` names it; ``blocks`` the refs it blocks; ``waiting_on`` the refs of
     *     its blockers not done yet. ``reviewed`` is None when unknown (no snapshot and no record).
     *     ``parent`` is the ref of the epic it belongs to (the plan's ``parent`` or Linear's parent
     *     issue), ``children`` the refs of the rows whose parent it is: a row with children is an epic.
     *     ``pr_url`` is the ticket's pull request on GitHub, from its review record, None when unknown.
     *     ``flow`` is the ticket's own steps, served by the tickets route (None for an epic).
     */
    TicketRow: {
      /** Acs */
      acs: string[];
      /** Assignee */
      assignee: string | null;
      /** Blocked By */
      blocked_by: components["schemas"]["TicketEdge"][];
      /** Blocks */
      blocks: string[];
      /**
       * Children
       * @default []
       */
      children: string[];
      /** Estimate */
      estimate: number | null;
      flow?: components["schemas"]["TicketFlow"] | null;
      /** Id */
      id: string | null;
      /** Key */
      key: string | null;
      /** Order */
      order: number | null;
      /** Parent */
      parent?: string | null;
      /** Pr Url */
      pr_url?: string | null;
      /** Priority */
      priority: number | null;
      readiness: components["schemas"]["Readiness"];
      /** Ref */
      ref: string;
      /** Repo */
      repo: string | null;
      /** Reviewed */
      reviewed: boolean | null;
      state: components["schemas"]["IssueState"] | null;
      /** Title */
      title: string | null;
      /** Url */
      url: string | null;
      /** Waiting On */
      waiting_on: string[];
    };
    /**
     * TicketStep
     * @description One step of a ticket's flow, in the golden path's state vocabulary, with a short ``meta``.
     */
    TicketStep: {
      /** Meta */
      meta: string | null;
      name: components["schemas"]["TicketStepName"];
      state: components["schemas"]["StepState"];
    };
    /** @enum {string} */
    TicketStepName: "context" | "preflight" | "implement" | "review" | "eval" | "pr" | "merged";
    /** @enum {string} */
    TicketsSource: "linear" | "plan";
    /** @enum {string} */
    TileGroup: "waiting" | "live" | "idle" | "ended_recently";
    /**
     * TimelineEntry
     * @description A line of the run's timeline; an investigation read (``agent_action``) names its action
     *     and effect.
     */
    TimelineEntry: {
      /** Action */
      action?: string | null;
      /** At */
      at: string | null;
      /** Attempt */
      attempt: number | null;
      /** Effect */
      effect?: string | null;
      /** Event */
      event: string;
      /** Node */
      node: string | null;
      /** Status */
      status: string | null;
    };
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
        [key: string]: components["schemas"]["pydantic__types__JsonValue"];
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
     * TocEntry
     * @description One heading of a body (outside fenced code); the web computes its anchor (P5).
     */
    TocEntry: {
      /** Level */
      level: number;
      /** Text */
      text: string;
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
     * TrackerConfigView
     * @description How the hub reaches its tracker.
     */
    TrackerConfigView: {
      /** Blocked Label */
      blocked_label: string | null;
      /** Failed Label */
      failed_label: string;
      /** Kind */
      kind: string;
      /** Ready Label */
      ready_label: string;
      /** Review State */
      review_state: string;
      /** Started State */
      started_state: string;
      /**
       * Team Set
       * @default []
       */
      team_set: string[];
      /** Teams */
      teams: string[];
      transport: components["schemas"]["SourcedValue"];
    };
    /**
     * TrackerProblem
     * @description Why Linear was not read, as RFC 9457 members: ``type`` is
     *     ``urn:agent-hub:problem:tracker-<kind>``, ``status`` Linear's HTTP status (or 503 when it did
     *     not answer, 504 on a timeout).
     */
    TrackerProblem: {
      /** Detail */
      detail: string;
      /** Status */
      status: number;
      /** Title */
      title: string;
      /** Type */
      type: string;
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
    /**
     * UnitKind
     * @description What a unit is: a skill's folder, an agent's file, a hook file, a hub workflow file, a
     *     scenario file, or an action's document or script (the scenario builder's saves).
     * @enum {string}
     */
    UnitKind: "skill" | "agent" | "hook" | "workflow" | "scenario" | "action";
    /**
     * UnitState
     * @description What the last read found in a unit: stored (or equal to its last version), or why not.
     * @enum {string}
     */
    UnitState: "ok" | "too_large" | "secret" | "unreadable";
    /** @enum {string} */
    UnversionedReason: "secret" | "too_large" | "script_only";
    /**
     * Usage
     * @description How often a skill or agent was used in the window: counts and a time only (D6, ADR 0019).
     *
     *     ``user_count`` counts invocations typed by a person, ``model_count`` the ones the model made.
     */
    Usage: {
      /** Count */
      count: number;
      last_used_at: components["schemas"]["ApiTimestamp"] | null;
      /** Model Count */
      model_count: number;
      /** User Count */
      user_count: number;
    };
    /** @enum {integer} */
    UsageDays: 7 | 30 | 90;
    /**
     * UsageReport
     * @description The hub's skills and agents with their runs, never used in ``days`` first (AGH-482).
     *
     *     ``truncated`` says the catalog or the usage fold was cut or not fully read.
     */
    UsageReport: {
      days: components["schemas"]["UsageDays"];
      /** Items */
      items: components["schemas"]["UsageRow"][];
      /**
       * Truncated
       * @default false
       */
      truncated: boolean;
    };
    /**
     * UsageRow
     * @description One hub skill or agent in the usage report: names, counts and a time only (AGH-482,
     *     ADR 0019). ``last_used_at`` is the last use within 90 days, or None.
     */
    UsageRow: {
      kind: components["schemas"]["ItemKind"];
      last_used_at: components["schemas"]["ApiTimestamp"] | null;
      /** Name */
      name: string;
      /** Project */
      project: string;
      /** Runs 30D */
      runs_30d: number;
      /** Runs 7D */
      runs_7d: number;
      /** Runs 90D */
      runs_90d: number;
    };
    /** Format: date-time */
    UtcTimestamp: string;
    /**
     * ValidateRequest
     * @description A scenario document to check: its pack and the document as the builder holds it.
     */
    ValidateRequest: {
      /** Document */
      document: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Input"];
      };
      /** Pack */
      pack: string;
    };
    /** ValidateResult */
    ValidateResult: {
      /** Loads */
      loads: boolean;
      /** Nodes */
      nodes: components["schemas"]["NodeLines"][];
      /** Problems */
      problems: components["schemas"]["BuilderProblem"][];
      /** Yaml */
      yaml: string;
    };
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
    ValueSource: "team" | "local" | "git" | "derived" | "default";
    /** @enum {string} */
    Verdict: "SHIP" | "SHIP-WITH-OWNER-STEPS" | "NO-SHIP";
    /**
     * VersionAuthor
     * @description Who wrote a ``publish`` or ``restore`` version: the hub's effective identity (ADR 0016).
     */
    VersionAuthor: {
      /** Email */
      email: string;
      /** Name */
      name: string;
    };
    /**
     * VersionFileView
     * @description One file of a version: ``text`` is None for a binary file (a NUL, or not UTF-8).
     */
    VersionFileView: {
      /** Executable */
      executable: boolean;
      /** Path */
      path: string;
      /** Size */
      size: number;
      /** Text */
      text: string | null;
    };
    /**
     * VersionOrigin
     * @description Where a version came from: the app's Publish or Restore, or the disk as the app read it.
     * @enum {string}
     */
    VersionOrigin: "publish" | "restore" | "external";
    /**
     * WaitingOnOwner
     * @description The owner decision a feature waits on; ``tickets`` are the open change requests' origin
     *     tickets (``change_request`` only).
     */
    WaitingOnOwner: {
      kind: components["schemas"]["OwnerWaitKind"];
      /**
       * Tickets
       * @default []
       */
      tickets: string[];
    };
    /** WorkaroundEntry */
    WorkaroundEntry: {
      /** Approver */
      approver: string | null;
      /** Number */
      number: number;
      /** Option */
      option: string;
      /** Status */
      status: string | null;
      /** Steps */
      steps: number;
      /** Workaround Id */
      workaround_id: string;
    };
    /**
     * Workdir
     * @description A folder a session may start in (D6): the hub, a repo checkout or one of its worktrees.
     *
     *     ``workdir_id`` is opaque and stable; the server resolves it only by lookup. ``skills`` are
     *     the names under its ``.claude/skills/`` (the ``/skill`` shortcut, P15).
     */
    Workdir: {
      /**
       * Kind
       * @enum {string}
       */
      kind: "hub" | "repo" | "worktree";
      /** Label */
      label: string;
      /** Repo */
      repo?: string | null;
      /**
       * Skills
       * @default []
       */
      skills: string[];
      /** Workdir Id */
      workdir_id: string;
      /** Worktree */
      worktree?: string | null;
    };
    /**
     * WorkdirList
     * @description ``GET /agent-sessions/workdirs``; ``warnings`` name folders that could not be read.
     */
    WorkdirList: {
      /** Items */
      items: components["schemas"]["Workdir"][];
      /**
       * Warnings
       * @default []
       */
      warnings: string[];
    };
    /**
     * WorkflowCatalogView
     * @description The workflows that load, by project then name, and every problem found.
     */
    WorkflowCatalogView: {
      /** Items */
      items: components["schemas"]["WorkflowSummary"][];
      /** Problems */
      problems: components["schemas"]["WorkflowProblemView"][];
    };
    /**
     * WorkflowDetail
     * @description A workflow's layers (in run order, nodes in declaration order) and its document as
     *     written (keys left out are not filled in); ``environment`` is the one a process workflow
     *     declares (P-18), None without one.
     */
    WorkflowDetail: {
      /** Description */
      description: string | null;
      /** Document */
      document: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
      };
      /** Environment */
      environment?: string | null;
      /**
       * Inputs
       * @default []
       */
      inputs: components["schemas"]["WorkflowInputView"][];
      /** Layer Count */
      layer_count: number;
      /** Layers */
      layers: components["schemas"]["WorkflowNodeView"][][];
      /** Name */
      name: string;
      /** Node Count */
      node_count: number;
      /** Project */
      project: string;
      /** Revision */
      revision: number;
      source: components["schemas"]["WorkflowOrigin"];
      /** Step Types */
      step_types?: {
        [key: string]: number;
      };
      /**
       * Steps
       * @default []
       */
      steps: components["schemas"]["WorkflowStepView"][];
    };
    /**
     * WorkflowGate
     * @description An open gate a person answers: where it is and what answers it.
     */
    WorkflowGate: {
      /** Approval Id */
      approval_id: string;
      /** Attempt */
      attempt: number;
      /** Choices */
      choices: components["schemas"]["GateChoice"][];
      form: components["schemas"]["GateForm"];
      /** Node */
      node: string;
      /** Project */
      project: string;
      /** Run Id */
      run_id: string;
      text: components["schemas"]["TextUse"];
      /** Workflow */
      workflow: string;
    };
    /**
     * WorkflowInputView
     * @description An input a run of the workflow takes: what to pass to ``hub workflow run``.
     */
    WorkflowInputView: {
      /** Description */
      description?: string | null;
      /** Name */
      name: string;
      /** Required */
      required: boolean;
      /** Type */
      type: string;
    };
    /**
     * WorkflowNodeView
     * @description A node as the graph shows it: its id, type and the nodes it waits for.
     */
    WorkflowNodeView: {
      /** Depends On */
      depends_on: string[];
      /** Description */
      description?: string | null;
      /** Id */
      id: string;
      /** Type */
      type: string;
    };
    /** @enum {string} */
    WorkflowOrigin: "hub" | "builtin";
    /**
     * WorkflowProblemView
     * @description Why a file of a project's hub is not a workflow: ``file`` is hub-relative (a built-in's
     *     starts ``<builtin>/``), ``line`` is 1-based when known, ``key`` is ``$`` for the file.
     */
    WorkflowProblemView: {
      /** File */
      file: string;
      /** Key */
      key: string;
      /** Line */
      line: number | null;
      /** Message */
      message: string;
      /** Project */
      project: string;
    };
    /**
     * WorkflowRun
     * @description A run folded from executor events (D9, D16): the first ``run.end`` wins, the highest
     *     ``n`` for an engine run. ``stage`` is issue-to-pr's machine (another workflow's live run is
     *     ``PICKED``); ``status`` and ``outcome`` hold for every workflow.
     */
    WorkflowRun: {
      caps: components["schemas"]["RunCaps"] | null;
      /** Content Hash */
      content_hash?: string | null;
      /** Cost Source */
      cost_source?: ("sessions" | "executor") | null;
      cost_usd: components["schemas"]["Money"] | null;
      delivery?: components["schemas"]["RunDelivery"] | null;
      /** Delivery Reason */
      delivery_reason?: string | null;
      /**
       * Derived
       * @default true
       */
      derived: boolean;
      ended_at: components["schemas"]["ApiTimestamp"] | null;
      environment?: components["schemas"]["RunEnvironment"] | null;
      failure: components["schemas"]["RunFailure"] | null;
      /**
       * Gate Results
       * @default []
       */
      gate_results: components["schemas"]["RunGateResult"][];
      /** Id */
      id: string;
      issue: components["schemas"]["IssueRef"] | null;
      /** @default workflow */
      kind: components["schemas"]["RunKind"];
      last_activity_at: components["schemas"]["ApiTimestamp"];
      /** Mode */
      mode: ("live" | "dry_run") | null;
      /** Outcome */
      outcome?: boolean | string | null;
      /** Pr Url */
      pr_url?: string | null;
      /** Project */
      project: string;
      /** Repo */
      repo: string | null;
      /** Revision */
      revision?: number | null;
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
      /** @default running */
      status: components["schemas"]["WorkflowRunStatus"];
      /** Steps */
      steps: components["schemas"]["RunStep"][];
      /** Workflow */
      workflow: string;
    };
    WorkflowRunStatus: "running" | components["schemas"]["RunStatus"];
    /**
     * WorkflowStepView
     * @description A step as the catalog outlines it: declaration order, a repeat's body nested (its ids
     *     without the ``<group>__`` prefix) and its round cap.
     */
    WorkflowStepView: {
      /**
       * Body
       * @default []
       */
      body: components["schemas"]["WorkflowStepView"][];
      /** Description */
      description?: string | null;
      /** Id */
      id: string;
      /** Max Iterations */
      max_iterations?: number | null;
      /** Type */
      type: string;
    };
    /**
     * WorkflowSummary
     * @description A workflow of a project's hub, and where it comes from (``source``). ``step_types``
     *     counts every step by type, a ``loop_group``'s body included; ``inputs`` is what a run takes.
     */
    WorkflowSummary: {
      /** Description */
      description: string | null;
      /**
       * Inputs
       * @default []
       */
      inputs: components["schemas"]["WorkflowInputView"][];
      /** Layer Count */
      layer_count: number;
      /** Name */
      name: string;
      /** Node Count */
      node_count: number;
      /** Project */
      project: string;
      /** Revision */
      revision: number;
      source: components["schemas"]["WorkflowOrigin"];
      /** Step Types */
      step_types?: {
        [key: string]: number;
      };
      /**
       * Steps
       * @default []
       */
      steps: components["schemas"]["WorkflowStepView"][];
    };
    "agent_hub__core__json_form__JsonValue-Input":
      | {
          [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Input"];
        }
      | components["schemas"]["agent_hub__core__json_form__JsonValue-Input"][]
      | string
      | number
      | boolean
      | null;
    "agent_hub__core__json_form__JsonValue-Output":
      | {
          [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue-Output"];
        }
      | components["schemas"]["agent_hub__core__json_form__JsonValue-Output"][]
      | string
      | number
      | boolean
      | null;
    pydantic__types__JsonValue: unknown;
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
  list_agent_sessions_api_v1_agent_sessions_get: {
    parameters: {
      query?: {
        project?: string | null;
        status?: components["schemas"]["AgentSessionStatus"] | null;
        wrote?: string | null;
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
          "application/json": components["schemas"]["AgentSessionList"];
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
  create_agent_session_api_v1_agent_sessions_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CreateAgentSession"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AgentSession"];
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
  get_capabilities_api_v1_agent_sessions_capabilities_get: {
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
          "application/json": components["schemas"]["DriverCapabilities"];
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
  list_cloud_sessions_api_v1_agent_sessions_cloud_get: {
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
          "application/json": components["schemas"]["CloudSessionList"];
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
  start_cloud_session_api_v1_agent_sessions_cloud_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["StartCloud"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["CloudSession"];
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
  follow_up_cloud_session_api_v1_agent_sessions_cloud__cloud_id__messages_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        cloud_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CloudMessage"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["CloudSession"];
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
  list_resumable_api_v1_agent_sessions_resumable_get: {
    parameters: {
      query: {
        project: string;
        workdir_id: string;
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
          "application/json": components["schemas"]["ResumableList"];
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
  list_workdirs_api_v1_agent_sessions_workdirs_get: {
    parameters: {
      query: {
        project: string;
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
          "application/json": components["schemas"]["WorkdirList"];
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
  get_agent_session_api_v1_agent_sessions__agent_session_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
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
          "application/json": components["schemas"]["AgentSession"];
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
  delete_agent_session_api_v1_agent_sessions__agent_session_id__delete: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
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
  close_agent_session_api_v1_agent_sessions__agent_session_id__close_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
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
          "application/json": components["schemas"]["AgentSession"];
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
  list_agent_session_events_api_v1_agent_sessions__agent_session_id__events_get: {
    parameters: {
      query?: {
        after?: number;
        limit?: number;
      };
      header?: never;
      path: {
        agent_session_id: string;
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
          "application/json": components["schemas"]["LogRecordPage"];
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
  interrupt_agent_session_api_v1_agent_sessions__agent_session_id__interrupt_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AgentSession"];
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
  send_agent_session_message_api_v1_agent_sessions__agent_session_id__messages_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SendMessage"];
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MessageAccepted"];
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
  answer_agent_session_permission_api_v1_agent_sessions__agent_session_id__permissions__request_id__post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
        request_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["PermissionDecision"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AgentSession"];
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
  get_agent_session_repo_changes_api_v1_agent_sessions__agent_session_id__repo_changes_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
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
          "application/json": components["schemas"]["SessionRepoChanges"];
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
  get_agent_session_repo_commit_diff_api_v1_agent_sessions__agent_session_id__repo_changes_commit_get: {
    parameters: {
      query: {
        path: string;
        sha: string;
        old_path?: string | null;
      };
      header?: never;
      path: {
        agent_session_id: string;
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
          "application/json": components["schemas"]["RepoCommitDiff"];
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
  get_agent_session_repo_file_api_v1_agent_sessions__agent_session_id__repo_changes_file_get: {
    parameters: {
      query: {
        path: string;
        sha: string;
      };
      header?: never;
      path: {
        agent_session_id: string;
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
          "application/json": components["schemas"]["RepoFileText"];
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
  change_agent_session_settings_api_v1_agent_sessions__agent_session_id__settings_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SessionSettings"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AgentSession"];
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
  stream_agent_session_api_v1_agent_sessions__agent_session_id__stream_get: {
    parameters: {
      query?: {
        after?: string | null;
      };
      header?: {
        "Last-Event-ID"?: string | null;
      };
      path: {
        agent_session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Server-Sent Events: record.<kind>, delta, status, reset, heartbeat */
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
  stop_agent_session_task_api_v1_agent_sessions__agent_session_id__tasks__task_id__stop_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        agent_session_id: string;
        task_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AgentSession"];
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
  decide_gate_api_v1_approvals__approval_id__decision_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        approval_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["GateDecisionRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["GateDecided"];
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
  get_gate_api_v1_approvals__approval_id__gate_get: {
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
          "application/json": components["schemas"]["WorkflowGate"];
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
  list_feature_names_api_v1_feature_names_get: {
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
          "application/json": components["schemas"]["FeatureNamesView"];
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
  set_feature_name_api_v1_feature_names_put: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["FeatureNameBody"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FeatureName"];
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
  run_ac_check_api_v1_features__project___slug__acs__ac__check_runs_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        slug: string;
        ac: string;
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
          "application/json": components["schemas"]["AcCheckRun"];
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
  decide_change_request_api_v1_features__project___slug__change_requests__n__decision_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        slug: string;
        n: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ChangeRequestDecisionBody"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ChangeRequestView"];
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
  sign_off_owner_steps_api_v1_features__project___slug__owner_signoff_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        slug: string;
      };
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": components["schemas"]["OwnerSignOffBody"] | null;
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EvalRecord"];
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
  get_feature_tickets_api_v1_features__project___slug__tickets_get: {
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
          "application/json": components["schemas"]["FeatureTickets"];
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
  get_ticket_records_api_v1_features__project___slug__tickets__ticket__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        slug: string;
        ticket: string;
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
          "application/json": components["schemas"]["TicketRecords"];
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
  fix_hub_findings_api_v1_hubs__hub_id__doctor_fix_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        hub_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["DoctorFixRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["DoctorFixResult"];
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
  sync_hub_platform_api_v1_hubs__hub_id__platform_sync_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        hub_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["PlatformSyncRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PlatformSyncResult"];
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
  list_learnings_api_v1_learnings_get: {
    parameters: {
      query?: {
        project?: string | null;
        status?: components["schemas"]["LearningStatus"] | null;
        cursor?: string | null;
        limit?: number;
        brain_path?: string | null;
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
          "application/json": components["schemas"]["LearningDetail"];
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
  accept_learning_api_v1_learnings__learning_id__accept_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        learning_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AcceptLearningBody"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["LearningActionResult"];
        };
      };
      /** @description Already decided, target refused, note not on the default branch, or actions unavailable for this hub */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The body is not application/json */
      415: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description Could not open the pull request */
      502: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The action passed its 60 s deadline */
      504: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
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
  reject_learning_api_v1_learnings__learning_id__reject_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        learning_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RejectLearningBody"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["LearningActionResult"];
        };
      };
      /** @description Already decided, target refused, note not on the default branch, or actions unavailable for this hub */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The body is not application/json */
      415: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description Could not open the pull request */
      502: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The action passed its 60 s deadline */
      504: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
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
  list_actions_api_v1_projects__project__actions_get: {
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
          "application/json": components["schemas"]["ActionLibrary"];
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
  post_action_api_v1_projects__project__actions_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["NewAction"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ScenarioActionView"];
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
  put_action_api_v1_projects__project__actions__pack___name__put: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        pack: string;
        name: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["NewAction"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ScenarioActionView"];
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
  get_brain_tree_api_v1_projects__project__brain_get: {
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
          "application/json": components["schemas"]["BrainTree"];
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
  get_brain_backlinks_api_v1_projects__project__brain_backlinks_get: {
    parameters: {
      query: {
        path: string;
      };
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
          "application/json": components["schemas"]["NoteBacklinks"];
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
  get_brain_note_api_v1_projects__project__brain_note_get: {
    parameters: {
      query: {
        path: string;
      };
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
          "application/json": components["schemas"]["BrainNote"];
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
  get_project_config_api_v1_projects__project__config_get: {
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
          "application/json": components["schemas"]["HubConfigView"];
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
  post_project_environment_edit_api_v1_projects__project__config_environments_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["EnvironmentEdit"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HubConfigView"];
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
  put_project_local_config_api_v1_projects__project__config_local_put: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["LocalSettings"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HubConfigView"];
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
  get_env_file_keys_api_v1_projects__project__env_file_keys_get: {
    parameters: {
      query: {
        path: string;
      };
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
          "application/json": components["schemas"]["EnvFileKeys"];
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
  list_environment_discoveries_api_v1_projects__project__environment_discoveries_get: {
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
          "application/json": components["schemas"]["Page_EnvironmentDiscovery_"];
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
  start_environment_discovery_api_v1_projects__project__environment_discoveries_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["StartEnvironmentDiscovery"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EnvironmentDiscovery"];
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
  get_environment_discovery_api_v1_projects__project__environment_discoveries__discovery_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        discovery_id: string;
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
          "application/json": components["schemas"]["EnvironmentDiscovery"];
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
  discard_environment_discovery_api_v1_projects__project__environment_discoveries__discovery_id__delete: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        discovery_id: string;
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
  search_project_knowledge_api_v1_projects__project__knowledge_search_get: {
    parameters: {
      query: {
        q: string;
        kind?: components["schemas"]["Kind"][] | null;
        limit?: number;
      };
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
          "application/json": components["schemas"]["KnowledgeSearch"];
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
  validate_scenario_api_v1_projects__project__scenarios_validate_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ValidateRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ValidateResult"];
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
  get_skill_catalog_api_v1_projects__project__skills_get: {
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
          "application/json": components["schemas"]["SkillCatalog"];
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
  publish_draft_api_v1_projects__project__skills_drafts__draft_id__publish_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        draft_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["PublishDraftBody"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ItemWriteResult"];
        };
      };
      /** @description No launch cookie (open hub web's address) */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description Unknown project or target item, or the draft folder missing or empty */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description Publish refused, with a code: hub_read_only, no_author, link_in_path, unit_unreadable, item_exists, draft_already_published or managed_confirmation_required */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The draft is past the bounds (limit) */
      413: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The body is not application/json */
      415: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The draft is not a valid item (draft_invalid), or the body is outside its shape */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description Write failed (write_failed: failed, rollback_failed, old_not_removed, draft_unreadable) or published with the draft kept (draft_not_removed) */
      500: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
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
  get_skill_detail_api_v1_projects__project__skills__kind___source___name__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        kind: components["schemas"]["ItemKind"];
        source: string;
        name: string;
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
          "application/json": components["schemas"]["SkillDetail"];
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
  get_skill_file_api_v1_projects__project__skills__kind___source___name__files__file_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        kind: components["schemas"]["ItemKind"];
        source: string;
        name: string;
        file_id: string;
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
          "application/json": components["schemas"]["BundledFileText"];
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
  list_skill_versions_api_v1_projects__project__skills__kind___source___name__versions_get: {
    parameters: {
      query?: {
        limit?: number;
        cursor?: string | null;
      };
      header?: never;
      path: {
        project: string;
        kind: components["schemas"]["ItemKind"];
        source: string;
        name: string;
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
          "application/json": components["schemas"]["ItemVersionPage"];
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
  get_skill_version_api_v1_projects__project__skills__kind___source___name__versions__version_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        kind: components["schemas"]["ItemKind"];
        source: string;
        name: string;
        version_id: string;
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
          "application/json": components["schemas"]["ItemVersionContent"];
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
  restore_skill_version_api_v1_projects__project__skills__kind___source___name__versions__version_id__restore_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        kind: components["schemas"]["ItemKind"];
        source: string;
        name: string;
        version_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RestoreVersionBody"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ItemWriteResult"];
        };
      };
      /** @description No launch cookie (open hub web's address) */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description Write refused, with a code: hub_read_only, no_author, link_in_path, unit_unreadable, secret_unversioned or managed_confirmation_required */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The body is not application/json */
      415: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
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
  get_scenario_run_api_v1_scenario_runs__run_id__get: {
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
          "application/json": components["schemas"]["ScenarioRunDetail"];
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
  answer_investigation_api_v1_scenario_runs__run_id__answer_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        run_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["InvestigationAnswer"];
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["InvestigationAnswered"];
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
  finding_inbox_api_v1_scenario_runs__run_id__findings__finding_id__inbox_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        run_id: string;
        finding_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FindingNote"];
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
  finding_issue_api_v1_scenario_runs__run_id__findings__finding_id__issue_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        run_id: string;
        finding_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["FindingIssueRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FindingIssue"];
        };
      };
      /** @description The issue was created */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FindingIssue"];
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
  open_investigation_api_v1_scenario_runs__run_id__investigation_post: {
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
      /** @description The session already started */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["InvestigationSession"];
        };
      };
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["InvestigationSession"];
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
  list_scenarios_api_v1_scenarios_get: {
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
          "application/json": components["schemas"]["ScenarioCatalogView"];
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
  get_scenario_api_v1_scenarios__project___name__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
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
          "application/json": components["schemas"]["ScenarioDetail"];
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
  save_scenario_api_v1_scenarios__project___name__put: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SaveRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SaveResult"];
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
  plan_scenario_api_v1_scenarios__project___name__plan_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ScenarioPlanRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ScenarioPlanView"];
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
  get_proposal_api_v1_scenarios__project___name__proposal_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
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
          "application/json": components["schemas"]["ProposalView"];
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
  delete_proposal_api_v1_scenarios__project___name__proposal_dismiss_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
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
  start_scenario_api_v1_scenarios__project___name__runs_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ScenarioStartRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RunAccepted"];
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
        issue?: string | null;
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
  get_session_problems_api_v1_sessions__session_id__problems_get: {
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
          "application/json": components["schemas"]["SessionProblems"];
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
  get_skill_usage_api_v1_skill_usage_get: {
    parameters: {
      query?: {
        project?: string | null;
        days?: components["schemas"]["UsageDays"];
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
          "application/json": components["schemas"]["UsageReport"];
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
  get_linear_connection_api_v1_tracker_linear_get: {
    parameters: {
      query?: {
        fresh?: boolean;
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
          "application/json": components["schemas"]["LinearConnectionView"];
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
  connect_linear_api_v1_tracker_linear_put: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["LinearKeyBody"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["LinearConnectionView"];
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
  disconnect_linear_api_v1_tracker_linear_delete: {
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
          "application/json": components["schemas"]["LinearConnectionView"];
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
        workflow?: string | null;
        failure_kind?: components["schemas"]["FailureKind"] | null;
        kind?: components["schemas"]["RunKind"] | null;
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
  start_run_api_v1_workflow_runs_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["StartRunRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RunAccepted"];
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
  abandon_run_api_v1_workflow_runs__run_id__abandon_post: {
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
          "application/json": components["schemas"]["RunAccepted"];
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
  cancel_run_api_v1_workflow_runs__run_id__cancel_post: {
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
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RunAccepted"];
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
  resume_run_api_v1_workflow_runs__run_id__resume_post: {
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
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RunAccepted"];
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
  list_workflows_api_v1_workflows_get: {
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
          "application/json": components["schemas"]["WorkflowCatalogView"];
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
  get_workflow_api_v1_workflows__project___name__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
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
          "application/json": components["schemas"]["WorkflowDetail"];
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
  list_workflow_versions_api_v1_workflows__project___name__versions_get: {
    parameters: {
      query?: {
        limit?: number;
        cursor?: string | null;
      };
      header?: never;
      path: {
        project: string;
        name: string;
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
          "application/json": components["schemas"]["ItemVersionPage"];
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
  get_workflow_version_api_v1_workflows__project___name__versions__version_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
        version_id: string;
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
          "application/json": components["schemas"]["ItemVersionContent"];
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
  restore_workflow_version_api_v1_workflows__project___name__versions__version_id__restore_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        project: string;
        name: string;
        version_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RestoreVersionBody"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ItemWriteResult"];
        };
      };
      /** @description No launch cookie (open hub web's address) */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description Write refused, with a code: hub_read_only, no_author, link_in_path, unit_unreadable, secret_unversioned or managed_confirmation_required */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
        };
      };
      /** @description The body is not application/json */
      415: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProblemDetails"];
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
