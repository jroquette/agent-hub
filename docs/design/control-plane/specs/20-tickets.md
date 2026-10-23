# Tickets

As built (AGH-426). The Tickets list (`/tickets`, sidebar **Work** → Tickets) shows the single-ticket work the
sessions did outside a feature: maintenance, fixes and small changes (`/fix`, `/refactor`, `/upgrade`, `/incident`,
`/triage`, `/deliver`, `/review`, hub runs), one row per tracker issue, and starts a new one with **Start ticket**.

A feature's own tickets stay on the feature (the Tickets tab and the ticket panel, ADR 0043,
[17-features.md](17-features.md)); this list never shows them, so no ticket shows twice. It writes nothing and has
no API of its own: it groups the sessions `GET /api/v1/sessions` returns, by the issue their label derives (first
prompt, branch or worktree name, [10-session-detail.md](10-session-detail.md)).

## Purpose and primary user

The owner, between features: which small tickets wait on them, which are running, which ended and what they cost;
and a one-step way to start the next fix in the hub folder.

## Layout (1440 px)

```
Tickets  [+ Start ticket]                            2 need you · 1 in progress · 4 ended  derived
[Find by issue, title, repo or skill]  [Kind ▾]  (3 of 7 tickets)
Needs you · 2
  ✋ AGH-112  Tracker team cap  Fix  agent-hub                                              $1.25
     /fix · 2 sessions · PR #41 open · a permission prompt
In progress · 1
  ▶ AGH-7  Upgrade  agent-hub                                                               $0.40
     /upgrade · 1 session · active 3m
Ended · 4
  AGH-3  Review  agent-hub  (muted)                                                         $2.10
     /review · 1 session · ended done 2h
```

It reuses the Features list's look (`features.css`: `ft-head`, `ft-summary`, `ft-toolbar`, `ft-group`, `ft-row`) and
the shared `FacetMenu`, `DerivedLabel`, `EmptyState`, `ProblemError` and `Skeleton`.

## Acceptance criteria

**Sidebar**

- **AC-426.1** Given the sidebar, when it is shown, then **Work** lists Tickets (`list-todo`, no badge) right after
  Features, and it opens `/tickets`.

**What the list holds**

- **AC-426.2** Given the newest 200 sessions in scope (`sort=-last_activity_at`, the project in scope or every
  project), when the list is drawn, then their sessions are grouped by project and tracker issue (the label's issue,
  else the session's, in upper case) into one row each, newest activity first; the row opens the ticket's newest
  session (`/sessions/<id>`), and a session with no issue is left out.
- **AC-426.3** Given a ticket one of the hub's features plans (its `issues`), or whose sessions ran a feature-path
  skill (`/feature`, `/implement`, `/research`, `/create-plan`, `/summarize`), when the list is drawn, then it is left
  out: it belongs to Features.
- **AC-426.4** Given the tickets, when the list is drawn, then they sit in three groups, in this order: **Needs you**
  (a session of the ticket waits on the owner), **In progress** (one is not ended), **Ended** (all ended); each group
  heading carries its count, and an empty group says so ("No ticket waits on you.", "No session is working on a ticket
  now.", "No ended ticket work in the sessions read."). The header summary reads "N need you · N in progress · N
  ended" with a `derived` label that explains the grouping.

**A row**

- **AC-426.5** Given a ticket row, when it is drawn, then it shows the issue (a link to the newest session), the
  newest session's short name when one has it, its kind, its project (only when tickets of several projects show) and
  its repos; a line "<skills, oldest first, joined by →, else "no skill"> · N sessions · PR #n <state> · <state>",
  where the state is the waiting reason ("waits on you" without one) in the waiting tone under Needs you, "active
  <ago>" under In progress and "ended <outcome> <ago>" under Ended; and the sessions' summed cost at the end. An ended
  row is muted.
- **AC-426.6** Given a ticket's skills (routine commands such as `/kickoff`, `/handoff`, `/learn` left out), when its
  kind is named, then it is the first of Fix, Refactor, Upgrade, Incident, Triage, Deliver, Review whose skill ran;
  else Hub run when a workflow run started one of its sessions; else Other.

**Finding**

- **AC-426.7** Given tickets, when the owner types in "Find tickets" (issue, title, project, repo or skill, any case)
  or checks kinds in the Kind menu (each with its count among the searched tickets), then only the matching rows show,
  a status reads "N of M tickets", groups with no match hide, and the URL keeps `?q=` and `?kind=` (a comma list),
  replacing the history entry.

**States**

- **AC-426.8** Given no session worked on a ticket outside a feature, when the list opens, then it shows "No ticket
  work yet." with how to start one (`/fix AGH-112`, a single-ticket skill and the issue id, or a branch named after the
  issue); while the sessions load, each group shows skeleton rows; when they cannot be read, the problem shows with
  Retry.
- **AC-426.9** Given the list open, when sessions change, then it rereads them every 10 s; each row is one keyboard
  stop: Enter or `o` opens it, `j` / `k` move between rows.

**Start ticket**

- **AC-426.10** Given a machine that can drive Claude sessions, when the owner clicks **Start ticket** in the header,
  then the New session dialog opens titled "Start ticket", on the project's hub folder, with `/fix ` in the prompt and
  a note on writing the issue after the skill; the dialog's skill buttons switch the skill (`/refactor`, `/upgrade`,
  `/incident`, `/triage`, as the hub offers), and starting it creates the session there and opens its chat. Where
  sessions cannot be driven, there is no Start ticket.

- **AC-521.8.7 Every ticket a session worked on** (AGH-521, wins over AC-426.3 on the list). Given sessions that
  worked on a feature's ticket, then the Tickets list keeps that ticket too, tagged Feature and linked to the ticket in
  its feature (`?doc=tickets&ticket=<issue>`); each row's session count opens the list of every session that worked
  on it, and the row opens the ticket page. The Portfolio's recent tickets still leave a feature's tickets to the feature's row.
- **AC-521.8.8 Ticket page.** Given a ticket row, when the owner opens it, then `/tickets/<project>/<issue>` shows what
  was done for that issue, read from its sessions (the newest 100): a Changes tab with the commits, files and pull
  requests its sessions changed; a Sessions tab with each session, its status and what it did; and, for a feature's
  ticket, a Feature tab linking the feature's records. An issue no session names shows "No session worked on <issue>
  yet."; sessions run outside hub web show no changes, with a line that says why; the page rereads every 10 s.

## Departures

- Feature tickets start from the feature (main's `StartTicketButton`: a named ticket, `/feature <id>` at step 5, a
  stacked branch when its blocker is in review). Start ticket here has no ticket row yet, so it opens the New session
  dialog instead and the owner writes the issue.
- The list is derived on the client from the newest 200 sessions: an older ticket drops off until a session works on
  it again. A server read model for tickets outside features is not built.
