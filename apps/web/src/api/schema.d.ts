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
     * @description Agent sessions, newest first.
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
     * @description Learnings, newest first, each with its note's summary or why the note is unavailable.
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
     * AgentSession
     * @description One session ``hub web`` started (or one cloud start, ``kind="cloud"``).
     *
     *     ``claude_session_id`` links it to the hook-observed Session once ``init`` arrives (or at
     *     start when the id is given, P13); ``observed_session_id`` is that Session's id once it has
     *     been observed, else ``null`` (a twin may never arrive, D2). ``last_seq`` is the last
     *     persisted record's ``seq``. ``cost_usd`` and ``usage`` add up the turns' results (an estimate).
     */
    AgentSession: {
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
     *     ``screenshot`` goes with the first prompt as an image, so it needs one.
     */
    CreateAgentSession: {
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
      /** Workdir Id */
      workdir_id: string;
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
    /** @enum {string} */
    EdgeSource: "plan" | "linear" | "both";
    /**
     * EndReason
     * @description Why a session ended.
     * @enum {string}
     */
    EndReason: "closed" | "idle_timeout" | "server_stopped" | "failed" | "log_full";
    /**
     * EvalRecord
     * @description One evaluation of a delivery: ``evals/<delivery>.md``, or the legacy ``eval.md``.
     *
     *     ``path`` is relative to the hub's ``brain/``. ``acs`` is the AC ids evaluated or ``"all"``;
     *     ``evaluated_at`` is the frontmatter's text (an ISO date or time). ``problem`` says why the
     *     file could not be read or parsed; its other fields are then empty.
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
      | "session.title";
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
     * FeatureDetail
     * @description A feature with its acceptance criteria rows, its records (D3) and every eval.
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
    };
    /** @enum {string} */
    FeaturePhase:
      "spec" | "research" | "plan" | "tickets" | "implement" | "review" | "evaluate" | "shipped";
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
     *     behind the golden path came from Linear or from the plan.
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
    };
    /** @enum {string} */
    FileOperation: "read" | "edited" | "created" | "written";
    /** @enum {string} */
    FileRole: "scripts" | "references" | "assets" | "other";
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
     *     not done (naming the failing gate), and its ``progress`` when it counts something.
     */
    GoldenStep: {
      /** Meta */
      meta: string | null;
      name: components["schemas"]["FeaturePhase"];
      progress: components["schemas"]["StepProgress"] | null;
      /** Reason */
      reason: string | null;
      state: components["schemas"]["StepState"];
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
        [key: string]: components["schemas"]["JsonValue-Input"];
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
    "JsonValue-Input": unknown;
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
     * ResumableList
     * @description ``GET /agent-sessions/resumable``: past Claude sessions of a workdir, newest first.
     */
    ResumableList: {
      /** Items */
      items: components["schemas"]["PastSession"][];
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
     * @description ``POST /{id}/messages``: one user message (byte limit checked, 413), with the images
     *     pasted in it, sent to Claude before the text.
     */
    SendMessage: {
      /** Screenshots */
      screenshots?: components["schemas"]["Screenshot"][] | null;
      /** Text */
      text: string;
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
    /** @enum {string} */
    StepState: "done" | "partial" | "current" | "pending" | "skipped" | "unknown" | "blocked";
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
      /** Id */
      id: string | null;
      /** Key */
      key: string | null;
      /** Order */
      order: number | null;
      /** Parent */
      parent?: string | null;
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
    /** @enum {string} */
    TicketsSource: "linear" | "plan";
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
     *     written (keys left out are not filled in).
     */
    WorkflowDetail: {
      /** Description */
      description: string | null;
      /** Document */
      document: {
        [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue"];
      };
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
     * WorkflowSummary
     * @description A workflow of a project's hub, and where it comes from (``source``).
     */
    WorkflowSummary: {
      /** Description */
      description: string | null;
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
    };
    agent_hub__core__json_form__JsonValue:
      | {
          [key: string]: components["schemas"]["agent_hub__core__json_form__JsonValue"];
        }
      | components["schemas"]["agent_hub__core__json_form__JsonValue"][]
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
}
