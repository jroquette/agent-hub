---
type: ux-design
status: implemented
change: change
screen: new-feature
base_spec: apps/web/src/screens/features/NewFeature.tsx (no screen spec exists; the code is the base)
repos: [agent-hub]
linear: []
---

# New feature: the brief is the screen (change)

**Phase:** P2 (driven sessions, ADR 0031) · **Route:** `/features/new` (from the Features list's "New feature"
button) · **Answers:** "What do I want built, and has Claude started on it?"

> `needs a spec change`: `/features/new` is in `routes.tsx` but not in the sitemap of `01-navigation.md`, and
> `17-features.md` has no section for it. Once this design is approved, add the route under `/features` in the sitemap
> and a short "New feature" section to `17-features.md` (from this file), in the same PR as the code.

## What changes

| Section | Before (code today) | After |
| --- | --- | --- |
| Header | Breadcrumb, H1, a four-line paragraph on the golden path | Breadcrumb, H1, one line: "Say what to build. Claude writes the brief and the spec with you, one question at a time." |
| Hierarchy | One card, every field the same weight; the idea is a plain 5-row textarea | The **brief box** is the hero: a composer-shaped box (text + attachments + Attach button), first and widest. Options sit below it, smaller |
| Attachments | None: images, PDFs and text files cannot be given | Paste, drop or pick images, PDFs and UTF-8 text files into the brief box, shown as the chat's thumbnails and file chips, same limits and refusal messages as the chat composer |
| Project | Full-width select above the idea, when more than one project | Same rule (shown only with more than one project), now one compact labelled select in the header row, right of the title, preselected from the scope |
| Tracker issue | One of three equal fields | Stays visible, one compact field under the brief box ("Start from an issue"), because it changes Claude's first step (it reads the issue's brief instead of writing one) |
| Slug, Size | Two of three equal fields, always shown | Folded into **More options** (closed by default; opens by itself when one has a value or an error). Size becomes a `SegmentedControl`, its hint under it |
| Primary action | "Start with Claude" composes a message, writes it as the panel's draft and adds a "Start it" starter: the owner must find the panel and press it | "Start with Claude" **starts the session itself** with the brief, the attachments and the options, then opens the Discuss panel on that conversation. One press, nothing left to resend |
| What happens next | A long status sentence beside the button | Before the press, a one-line note under the button says what will happen. After it, the form gives way to a **sent card**: the brief as sent, its attachments, and one status line |
| Keyboard | Enter in a field submits the form; no shortcut | Ctrl+Enter / ⌘+Enter from any field starts (as in New session); Enter in the brief is a new line |
| Styling | Inline `style={{}}` throughout | Classes in `features.css` (`ft-new-*`) on the spacing and type tokens; no inline style |

## What stays

- The route, the breadcrumb "Features › New", the H1 "New feature".
- `composeFeatureMessage` and `BRIEF`: the request text Claude gets is built the same way (the attachments ride beside
  it, not inside it). Size ids (`spike`, `bounded`, `architectural`) and their hints.
- Validation: the slug's kebab rule and "already exists" check, the issue id rule, "idea of 10 characters or an issue".
- One conversation per request (`feature-new:<project>:<time>` key), in the project's hub folder, through the Discuss
  panel and `discussPrompt`.
- Watching the feature records (3 s refetch while waiting) and the "has its record" result.
- The Discuss panel itself (`DiscussPanel`, `DiscussChat`): no change to how it looks or behaves once a session exists.

## Purpose and primary user

The project owner, about to start a feature, often with material in hand: a screenshot of the bug, a PDF of the
client's request, a CSV sample. The screen's job is to take that idea and material in one place and hand it to
Claude, then say plainly where the conversation continues. Most important action: **Start with Claude**.

## Layout

### Desktop, 1440 (sidebar expanded, panel closed: content 1136 px; the form column is max 760 px, left-aligned)

```
Features › New
New feature                                                     Project [agent-hub ▾]   (only with > 1 project)
Say what to build. Claude writes the brief and the spec with you, one question at a time.

What do you want to build?
┌──────────────────────────────────────────────────────────────────────────────┐
│ [img 72][img 72] [▤ client-brief.pdf  1.2 MB ⨯] [▤ orders.csv  4 KB ⨯]        │  attachments, only when any
│                                                                              │
│ Owners can export the orders of a period as CSV from the admin portal,       │  textarea, 6 rows, grows to 40vh
│ with the same filters as the list.                                           │
│                                                                              │
│ ──────────────────────────────────────────────────────────────────────────── │
│ [+ Attach]  Paste or drop images, PDFs and text files                        │  bar
└──────────────────────────────────────────────────────────────────────────────┘
  Up to 10 images and 10 files of 5 MB each.                                         hint / error line

Start from an issue (optional)
[DEMO-1600        ]  Left empty, Claude writes the brief with you and creates it.

▸ More options · Slug: Claude picks · Size: Let Claude ask

[▸ Start with Claude]   Opens the Discuss panel. Claude asks before writing any file.      Ctrl+Enter
```

More options, open:

```
▾ More options
  Slug (optional)            [orders-csv-export     ]  Left empty, Claude picks one.
  Size                       [Let Claude ask | Spike | Bounded | Architectural]
                             Claude proposes a size and asks you.
```

After the press (the panel docks on the right, `--discuss-width` min(460 px, 40vw)):

```
Features › New
New feature                                                       ┃ Discuss with Claude          ⨯
                                                                  ┃ New feature · a new feature
┌ Sent to Claude ────────────────────────────── 2 min ago ─┐      ┃ ┌ chat: Claude's first        ┐
│ Owners can export the orders of a period as CSV from…    │      ┃ │ question about the brief…    │
│ [img][img] [▤ client-brief.pdf] [▤ orders.csv]           │      ┃ └──────────────────────────────┘
│ Issue: none · Slug: Claude picks · Size: Let Claude ask  │      ┃
│                                                          │      ┃
│ (message-square) Claude is working on the brief with you │      ┃
│ in the panel.   [Open the panel]  Open the full chat     │      ┃ [ message box (focused) ] [Send]
└──────────────────────────────────────────────────────────┘      ┃
[+ Start another feature]
```

Once the record exists, the status line becomes:
`(circle-check) orders-csv has its record.  Open orders-csv` (link to `/features/<project>/<slug>`).

### Breakpoints (`31-responsive.md`)

- **Wide ≥ 1600:** as drawn; page padding `space-8`.
- **Desktop 1280–1599:** sidebar collapses to 56 px below 1360; padding `space-6`. With the panel docked at 1280 the
  content is 1280 − 56 − 460 − 48 = 716 px: the form column takes the full width (its 760 cap is not reached); the
  issue field and its hint wrap to two lines; the Ctrl+Enter hint drops under the button. No horizontal scroll.
- **Tablet 768–1279 (best effort):** one column, full width; the Project select moves under the H1; the Discuss panel
  is a full-height overlay (tablet rule) instead of docking, so the sent card stays behind it. See open question 3.
- **Mobile < 768:** not a glance screen: "This view needs a wider screen." with [Open Live sessions] [Open Approvals];
  the deep link is kept.

## Components

| Piece | Decision | What it shows / why |
| --- | --- | --- |
| `Breadcrumbs` | reuse | Features › New |
| `Button` | reuse | Primary "Start with Claude" (`message-square` icon, the view's only accent); ghost "Attach" (`plus`); default "Open the panel"; ghost "Start another feature" (`plus`) |
| `AppLink` | reuse | "Open the full chat" (`/agent-sessions/:id`), "Open <slug>" |
| `ScreenshotThumb` | reuse | Each image, opens the lightbox to mark it up (as in the chat) |
| `Icon` | reuse | `file-text` (file chip), `x` (remove), `loader` (reading), `message-square`, `circle-check`, `chevron-right/down` (disclosure) |
| `SegmentedControl` | reuse | Size, four segments; replaces the select so all four sizes are visible at once |
| `Banner` (`warning`, `boxed`) | reuse | Sessions unavailable, with `sessionControlUnavailable()`'s title and detail |
| `Skeleton` | reuse | Loading shape (see States) |
| `EmptyState` | reuse | No project registered |
| `Kbd` | reuse | `Ctrl` `Enter` / `⌘` `Enter` hint |
| `<details>` disclosure | reuse (pattern) | "More options": the same native `<details>` the app uses in TicketsTab, StepList, DrivenControls |
| `.as-composer` box styles | reuse | The brief box borrows the composer's frame, focus-within ring, drop highlight (`as-composer-drop`) and bar, so it reads as "the same box as the chat" (H4) |
| **`AttachmentList`** + **`useMessageAttachments`** | **new (extracted)** | Today the attachment state (images, files, reading count, error, the limits, paste/drop/pick handlers) and the `<ul>` of thumbs and chips live inside `Composer.tsx`. Extract both, unchanged in behaviour, to `apps/web/src/components/AttachmentList.tsx` (+ `AttachmentList.css`, the `as-composer-image*`/`as-composer-file*` block moved from `agent-session.css`, class names kept), and use them in `Composer` and here. Considered: copying the code (two copies of the limit and refusal rules would drift, K5); passing a `Composer` instance (it carries mode, model, Stop, Send and Enter-to-send, none of which fit a brief). Flagged `new` for approval |
| **`useStartDiscussion`** | **extend (extracted)** | `StartDiscussion.start` in `DiscussPanel.tsx` already does capabilities → hub workdir → `POST /agent-sessions` with `screenshots[]`, `files[]` and `discussPrompt`. Extract it into a hook in `shell/` returning `{ unavailable, reason, start(target, text, images, files), pending, error }`, plus `rememberDiscussSession(target, id)` (today's private `writeStored`). `StartDiscussion` and this screen both call it. Considered: the target carrying the attachments to the panel's composer (`DiscussTarget` is JSON-stringified on every render by `useDiscussTarget` and drafts live in localStorage: megabytes of base64 there is wrong, and the owner would still have to press a second button) |

The remove button on thumbs and chips is 20 × 20 today, under the 24 px minimum (`control-sm`, WCAG 2.5.8): the
extracted `AttachmentList` keeps the 20 px circle but gives it a 24 × 24 hit area. This also fixes the chat.

## Content

| Element | Copy |
| --- | --- |
| Lead | "Say what to build. Claude writes the brief and the spec with you, one question at a time." |
| Project label | "Project" |
| Brief label | "What do you want to build?" |
| Brief placeholder | "Owners can export the orders of a period as CSV from the admin portal, with the same filters as the list." With images: "Say what to build, and what Claude should see in the image." With files: "Say what to build, and what Claude should take from the file." |
| Bar note | "Paste or drop images, PDFs and text files" |
| Attach button | "Attach" (accessible name "Attach a file", title "Attach images, PDFs or text files up to 5 MB (or paste or drop them in the box)", as in the chat) |
| Attachment list name | "Attached to this request" |
| Hint line (default) | "Up to 10 images and 10 files of 5 MB each." |
| Issue label / hint | "Start from an issue (optional)" / "Left empty, Claude writes the brief with you and creates it." Invalid: "An issue id, like DEMO-1600." |
| Disclosure summary | "More options · Slug: <slug or 'Claude picks'> · Size: <size label>" |
| Slug label / hints | "Slug (optional)" / "Left empty, Claude picks one." / "Lowercase letters, digits and dashes, starting with a letter." / "A feature with this slug already exists." |
| Size label / hints | "Size" / the four existing hints |
| Primary | "Start with Claude"; while pending "Starting…" |
| Note beside the primary | "Opens the Discuss panel. Claude asks before writing any file." |
| Why disabled (shown in place of the note, `aria-describedby` of the button) | "Write at least a sentence, or give an issue." · "Add a sentence on what to build with the attachments." · "Wait for the files to be read." · "Checking whether this machine can drive Claude…" · "Looking for the hub folder…" · "Project <p> has no hub folder to work in." |
| Sent card title | "Sent to Claude" + relative time (`Time ago`) |
| Sent card options line | "Issue: <id or 'none'> · Slug: <slug or 'Claude picks'> · Size: <label>" |
| Waiting status | "Claude is working on the brief with you in the panel." + [Open the panel] (only when the panel is closed) + "Open the full chat" |
| Found status | "<slug> has its record." + link "Open <slug>" |
| Second request | "Start another feature" |

Refusals reuse the chat's words exactly: "A message takes up to 10 images." · "A message takes up to 10 files." ·
"“<name>” is <size>: files go up to 5 MB." · "“<name>” is empty." · "Claude reads PDFs and text files here, and
“<name>” is neither." · "Could not read that image. Try another one." · "Could not read that file. Try again."
(Open question 2: "message" in the first two.)

## Data mapping

| Field | Source | Missing / not connected |
| --- | --- | --- |
| Projects | `GET /api/v1/projects` | Pending: select skeleton; none: `EmptyState` (States) |
| Default project | `useScope()`, else the first project | — |
| Can start | `useAgentCapabilities()` + `sessionControlUnavailable()` | `Banner` with its title and detail; primary disabled |
| Hub folder | `useWorkdirs(project)` → `kind: "hub"` | Reason "Project <p> has no hub folder to work in." |
| Slug taken | `useFeatures(project)` | Query failed: the "taken" check is skipped (the API still refuses a duplicate record later); no error shown for it |
| Start | `POST /agent-sessions` `{project, workdir_id, mode: "default", fork: false, prompt: discussPrompt(target, composeFeatureMessage(...)), screenshots[], files[]}` | Problem Details shown inline under the button |
| Conversation | session id stored as `ah.discuss.session.<key>` before the target is set, so the panel opens straight on `DiscussChat` | — |
| Images in the first bubble | `rememberMessageScreenshots(id, 1, images)` (as the panel does) | — |
| New record | `GET /api/v1/features?project=` every 3 s while waiting; first slug not known before (or the asked slug) | Never appears: the waiting line stays; the conversation is still in the panel |
| Brief text across reloads | `useDraft("feature-new.<project>")` (`ah.chat.draft.feature-new.<project>`), cleared once started | Attachments are not kept across a reload (they are not stored, by design) |

Mode is `default` (every file edit asks), model the default: the screen offers neither; the panel's composer has
both once the conversation runs.

## Interactions and keyboard

- **Attach:** paste into the brief (images and files; a copied file's name-as-text is not pasted), drop anywhere on
  the brief box (`as-composer-drop` highlight while dragging), or Attach → file picker. Each image opens the lightbox
  to mark it up; ⨯ removes one and returns focus to the brief.
- **Start:** "Start with Claude" or Ctrl+Enter / ⌘+Enter from any field of the form (precedent: New session dialog;
  no clash in `01-navigation.md`'s map). Enter in the brief is a new line; Enter in the issue or slug field does
  nothing (no accidental start). IME composition never starts.
- **After start:** the form is replaced by the sent card (not editable: what was sent is sent); the panel opens on
  the conversation and its message box takes focus (`DiscussChat` focuses on open), so the owner answers Claude's
  first question without a click. Closing the panel (its ⨯, Esc in the panel) returns focus to "Open the panel".
- **Start another feature:** clears the screen to an empty form with a new conversation key; the previous
  conversation stays reachable from the session list and from the panel's history for its key.
- **More options:** native `<details>`; Space/Enter on the summary toggles. It opens itself when the slug has a value
  or an error.
- Tab order: Project → brief → Attach → each attachment's open / remove → issue → More options (slug, size segments)
  → Start with Claude.

## States

| State | What shows |
| --- | --- |
| Loading | Projects pending: the header row shows a `Skeleton` 160 × 30 where the select goes; the brief box renders at once (typing never waits). Primary disabled, reason "Checking whether this machine can drive Claude…". No spinner |
| Empty (no project) | `EmptyState` `folder-kanban`: "No project yet" · "Register a hub to start features in it." · link "Open Welcome" (`/welcome`) |
| Empty form | Primary disabled with "Write at least a sentence, or give an issue." |
| Invalid | Issue or slug: `aria-invalid`, hint turns `failed` text (with the `circle-x` icon, not color alone), primary disabled; the slug error opens More options |
| Reading files | A 72 px `loader` tile in the attachment list ("Reading…" for screen readers); primary disabled with "Wait for the files to be read." |
| File refused | The refusal sentence in the hint line (`role="alert"`, `failed` text, icon), the others stay attached |
| Over limits | Extra items are not taken; "A message takes up to 10 images." / "… 10 files."; Attach disabled once both limits are reached |
| Sessions unavailable | `Banner warning boxed` above the form: "<title>. <detail>" from `sessionControlUnavailable` (e.g. "Sessions cannot start here. claude is not available on this machine."). Brief, attachments and options stay editable; primary disabled |
| No hub folder | Primary disabled with "Project <p> has no hub folder to work in." |
| Start failed | Under the button, `role="alert"`: the Problem Details `detail` (or `title`); everything stays as typed and attached; the button is enabled again |
| Waiting for Claude | Sent card, waiting line (see Content); polite live region; no pulse (the pulse is for live sessions only) |
| Record found | `circle-check` + "<slug> has its record." + "Open <slug>"; announced once |
| Offline / stale | App-wide rules of `22-first-run-and-errors.md` (the API is `hub web` itself: if it is down, the full-page "not responding" error); nothing screen-specific |
| First run | Same as empty (no project) |

## Accessibility notes

- The brief textarea has the visible label "What do you want to build?"; the attachment list is a `ul` named
  "Attached to this request"; each remove button is named "Remove <file name>" / "Remove image <n>"; each thumbnail's
  alt is "Image <n>".
- The disabled primary is `aria-describedby` its reason, so a screen reader hears why.
- The hint/error line is one element: refusals are `role="alert"`, the default hint is plain text.
- The sent card's status line is `role="status"` (polite); it changes twice at most (waiting, found).
- Drop is never the only way: the Attach button and paste do the same (WCAG 2.1.1).
- Targets: remove buttons get a 24 × 24 hit area; segments and buttons are ≥ 24 px (WCAG 2.5.8).
- Focus ring on the brief box via `.as-composer:focus-within`; on `<summary>` the standard 2 px ring.
- The axe test (`NewFeature.test.tsx` "a11y") covers the empty form, the form with attachments and an error, and the
  sent card.

## UX principles applied

| Choice | Why |
| --- | --- |
| Brief box first and widest, options below and folded | Five-second test, H8 (aesthetic and minimalist), L4 (progressive disclosure) |
| Attachments in the same box, same thumbnails, chips, limits and words as the chat | H4 (consistency), K5, U1 (reuse) |
| Slug and size folded, with their values in the summary | H6 (recognition over recall): the choice is visible while closed |
| Size as a segmented control | H6: all four options seen at once, hint under the chosen one |
| One press starts the session, panel opens on it, focus in its box | H1 (system status), removes a second "Start it" step; the human still answers every gate in the chat (Principle 2) |
| Sent card instead of an editable form after start | H1 and honesty: what Claude got is shown as sent, not as something still editable |
| Disabled button says why, next to it | H9, C6 |
| Refusals name the file and the limit | H9: what happened and how to fix it |
| Draft kept across reloads | Context kept (H3) |
| No inline style, token spacing | L2, S2 |
| Status by icon + label | Visual foundations › Status, WCAG 1.4.1 |

## Requests mapped

The feature has no `spec.md` with ACs (playground request). The developer's asks map as follows.

| Ask | Element and state |
| --- | --- |
| Attach PDFs, images and other files to the prompt | Brief box + `AttachmentList` + `useMessageAttachments`; reaches `POST /agent-sessions` `screenshots[]`/`files[]` via `useStartDiscussion` |
| More organized, better laid out | Hero brief box, one column max 760, options below, header one line |
| Only the options that matter | Project only with > 1; issue visible; slug and size under More options; mode and model left to the panel |
| Clear primary action and what happens next | "Start with Claude" + note "Opens the Discuss panel…", then the sent card and its status line |

## Open questions

1. Principle 1 in `README.md` still says "No chat and no 'talk to the agent' box, anywhere", while ADRs 0031 and 0033
   and the Discuss panel ship one. This screen follows the shipped panel; should the principle (or the Departures
   list) be updated through `/adr`?
2. The refusal copy reuses the chat's "A message takes up to 10 images." Keep one shared wording (simplest, one
   source), or let `AttachmentList` take a noun so this screen says "A request takes…"?
3. Tablet is "read, no editing" in `31-responsive.md`. Should this form work at tablet width (as designed here, best
   effort) or show "Editing needs a desktop screen."?
4. Starting the session from the screen drops the chance to read the composed request before it is sent (today it
   waits as a draft in the panel). The sent card shows it afterwards. Is that acceptable, or should the request be
   previewable before the press (a "Show what Claude gets" disclosure)?

## Alternatives considered

1. **Hand the attachments to the panel and keep the "Start it" starter.** `DiscussTarget` gains `attachments`, the
   panel's composer preloads them. Lost: the target is stringified on every render and drafts live in localStorage
   (megabytes of base64), `Composer` would need an initial-attachments prop, and the owner still has to find and
   press a second button in another place.
2. **Make the screen a full-page chat (embed `Composer` here).** Lost: the composer carries mode, model, Stop and
   Enter-to-send, which do not belong to a brief, and the conversation would live in two places (this page and the
   panel).
