# Environments

**Phase:** P2 shell + ADR 0040 writes · **Routes:** `/environments` (project picker),
`/projects/:project/environments`, `/projects/:project/environment/:name` (`?service=<repo>/<name>` opens the service
panel), `/projects/:project/environments/new`, `/projects/:project/environments/services/new[?repo=]` · **Answers:**
"Where do this project's systems run, what may agents do in each, and how do I fix any of it where it is shown?"

The screens of the declared environments and services (contract: [environments.md](../../environments.md), its
"From hub web" section and AGH-416's API). For a developer who is not an infra person: environments, access and
addresses above the fold, and the action that matters is changing the one wrong thing where it is shown. The UI says
**address**, never endpoint (`endpoints` stays the `hub.json` key). Every write goes through
`POST /projects/{project}/config/environments`: `hub.json` (the team's, left uncommitted with a notice to run
`./hub sync` and open a hub PR) or `hub.local.json` (only me, never committed; it may add its own environments and
only make a team environment stricter).

Built from the playground's UX designs v2 (overview, setup flows), v3 (environment page, service panel) and the Hub
config change (AGH-417, in parts); the find-services part of v3 is AGH-418. This part holds the address display; the
screens follow.

## Addresses and other long values

A service's address is shown **whole when it fits**; else it is cut in the middle with an ellipsis, its last 18
characters (the host's end) always whole, the whole address in a tooltip while it is cut, and a copy button beside it.
The cut follows the box as it is resized (the browser measures it, not a character count). The shared `FitText`
component does it; the chat's files list uses it for its root line, folders and file names (the extension stays
whole, the whole name in a native title).

## Acceptance criteria (AGH-417)

- **AC-417.1** Given a long value in a box of any width, when `FitText` renders it, then the whole text is on the
  line, its `tail` characters in a part that never shrinks and the rest cut in the middle when it does not fit, with
  the whole text as a native title; with `tooltip`, the whole text shows in a tooltip only while the line is cut. The
  chat's files list shows its names this way (the extension whole).
