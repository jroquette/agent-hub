# Chat: the Discuss panel, the full chat and the sessions rail (AGH-422)

The chat's design: the Discuss panel (every screen) and the full chat page (`/agent-sessions/:id`), which share one
reading anatomy. It builds on [agent-sessions.md](../../agent-sessions.md#chat-behaviour) (the chat's behaviour, ADR
0033), the Discuss section of [01-navigation.md](01-navigation.md#discuss-with-claude-on-any-screen-agh-273) and
[31-responsive.md](31-responsive.md). The acceptance criteria live with the screen that owns them (AC-422.1 in
[17-features.md](17-features.md), AC-422.2 to .7 in [01-navigation.md](01-navigation.md)); this file holds the
design they come from. Where it says otherwise than the README's foundations, the README's AGH-422 Departures entry
applies.

**Answers (panel):** "What does Claude say about what I am looking at, and what do I answer?"
**Answers (full page):** "What is this session doing now, and what does it need from me?"

Both views share one job: read Claude's reply, then answer. The primary action is Send; while a permission card
waits, the answer on that card (principle 2). The conversation is the biggest thing on screen and the chrome gets out
of its way (deference); status stays visible, and nothing moves that the owner did not cause. The direction follows
Apple's HIG (clarity, deference, depth) and the calm of chat apps: Claude's prose without a bubble, the owner's turn
as a soft card, a floating rounded composer, a restrained accent. Not taken on purpose: translucent materials (nothing
scrolls behind the header or the composer), a warm palette (the cool neutrals and the one indigo accent stay), another
font (Geist stays), any Claude brand colour.

## Owner's answers

| Question | Answer |
|---|---|
| Principle 1 says "no chat" while ADRs 0031 and 0033 have one | Do the redesign now; recorded in the README's AGH-422 entry |
| Reading size of the reply | `reading` 15/24 on a chat at least 560 px wide, 14/22 narrower |
| Radius of the owner's turn and the composer | 16 px (`radius-2xl`), with round Send, Stop and attach buttons |
| Escape while the panel is docked | Closes it only from inside it; over the page, from anywhere |

## Discuss panel

### What changes

| Part | Before | After |
|---|---|---|
| Size | Fixed `min(460px, 40vw)`, docked at every width | Resizable from its left edge, 320 px up to `min(720, viewport − sidebar − 640)`; default 480. Docked from 1280, over the page below, full width below 768 |
| Closing | The X only; focus fell to `<body>` | Escape (rules below); focus goes back to the opener; the logic is shared with `SidePanel` |
| Header | Up to six bands before the first message | Two rows: title + Widen + Close; then target · status · cost · one menu |
| Ground | `bg` | `surface`, the reading ground |
| Compact chat | No live activity bar; errors showed their title only | The live bar and the todo list above the composer; `ProblemError` with its detail and Try again |
| Start state | A 50-word note, chips, then the composer | A title and one line, the starters as full-width rows under "Start with", then the composer |
| Discuss toggle | An accent `primary` button while open | The pressed state of a default button |
| Feature pages | The panel's own conversation only | The feature's own session first (AC-422.1), a new conversation one click away |

### Layout at 480 px, 1440 × 900, sidebar expanded

```
+--------+-----------------------------------------------------++--------------------------------------------+
| side   | [project v] [Search Ctrl K]                [Discuss]  || top bar 48                                 |
| bar    +-----------------------------------------------------+|+--------------------------------------------+
| 240    | page, reflowed: 1440 − 240 − 480 = 720 px            |║ (msg) Discuss with Claude        [⤢]  [×] |  row 1, 40
|        | (margin-right = the panel's width)                  |║ Spec · layered-memory · ● Running $0.42 [⋯]|  row 2, small
|        |                                                     |║────────────────────────────────────────────| the one divider
|        |                                                     |║              (the conversation)            |
|        |                                                     |║ ● Reading spec.md · 3 s          Steps 2 › |  live bar
|        |                                                     |║ ╭────────────────────────────────────────╮ |
|        |                                                     |║ │ Message Claude                          │ |  composer
|        |                                                     |║ ╰────────────────────────────────────────╯ |
+--------+-----------------------------------------------------+╨--------------------------------------------+
                                                               ^ resize edge: the panel's left edge, full height
```

- **Row 1** (40 px): `message-square`, "Discuss with Claude" (strong), then Widen/Narrow (`maximize-2`) and Close.
- **Row 2** (`small`, one line): "<Kind> · <title>" (truncated, the whole text in its `title`), or `square-terminal`
  "Feature session · <name>"; then `AgentStatusBadge` and `CostMeter`; then the menu `ellipsis` "More for this
  conversation". Below a 400 px panel the cost gives way. The hairline under row 2 is the panel's only divider.
- **Menu:** "Open the full chat", "New conversation", "Back to the feature session" (only on another conversation of
  a feature with its own session), and the target's path as a `PathText` row that copies on click.

### Resizing

- **Edge:** the panel's left edge at full height, the drawers' `.as-drawer-handle` (a 9 px hit area, a 3 px accent
  line on hover and focus, `col-resize`).
- **Widths:** min 320 (`DRAWER_MIN`); default 480 (`panel`); docked max `min(720, viewport − sidebar − 640)` so the
  page keeps 640 px; over the page max `viewport − 96` so 96 px of the page stay in view; never under 320.
- **Kept:** `ah.discuss.width` holds the width chosen; the width shown is it, clamped to the current max by CSS. A
  narrower window or an expanded sidebar clamps without rewriting it.
- **Keys:** ←/→ by 40 px, Home back to the default, End the widest (End is new for the drawers too); a double click
  goes back to the default; Widen/Narrow toggles the widest width (WCAG 2.5.7).
- **Separator:** `role="separator"`, vertical, "Resize the Discuss panel", `aria-controls` the panel, and
  `aria-valuemin`, `aria-valuemax`, `aria-valuenow` and `aria-valuetext` ("480 pixels wide") always set (the drawers'
  separators gain the same).

### Closing

- **Focus return:** opening records the element that had focus (the top bar's toggle, an in-page Discuss button);
  closing by Close, Escape or the toggle puts focus back on it, or on the top bar's Discuss toggle when it is gone,
  unless the reader already moved focus elsewhere on the page.
- **Escape, docked:** from inside the panel, after any layer above it (the `/` menu, the steps drawer, the lightbox,
  the conversation menu) and the chat's own rule (an empty composer while a turn can be stopped stops it; a composer
  with text keeps its Escape). Escape on the page leaves a docked panel open: it is a tool beside the page.
- **Escape, over the page:** from anywhere, after any layer above it.
- **Shared:** `usePanelDismiss` (components) holds Escape and focus return for `SidePanel` and the Discuss panel.

### Components

| Piece | Decision | Where |
|---|---|---|
| `useDrawerWidth` | extend: options for the storage key, the CSS variable, the label, the default and the bounds; End; separator values always | `screens/agent-session/DrawerResize.tsx` |
| `usePanelDismiss` | new hook, extracted from `SidePanel` | `components/usePanelDismiss.ts` |
| Panel header and menu | change: two rows, `Popover` + `MenuItem`, `PathText` | `shell/DiscussPanel.tsx`, `shell/discuss.css` |
| `LiveActivityBar`, `StepsPanel`, `TodoList` | reuse in the compact chat | `screens/agent-session/DiscussChat.tsx` |
| `ProblemError` | reuse, `compact` | `components/feedback.tsx` |
| `AgentStatusBadge`, `CostMeter` | reuse, portalled into row 2 | `DiscussChat.tsx` (`metaSlot`) |
| Starters | change: full-width rows | `DiscussPanel.tsx` |
| Discuss toggle | change: `variant="default"` with the pressed look | `shell/TopBar.tsx`, `discuss.css` |
| The feature's session | new query `useFeatureSession` (the writers of spec, research, plan), `ownerSession` on the target | `screens/feature-detail/queries.ts`, `shell/discuss.tsx` |

### Content

| Place | String |
|---|---|
| Row 2 | "<Kind> · <title>"; or "Feature session · <name>" |
| Widen / Narrow | "Widen panel" / "Narrow panel" |
| Menu | "More for this conversation": "Open the full chat", "New conversation", "Back to the feature session", "<path>" (Copy) |
| Edge | "Resize the Discuss panel"; "<n> pixels wide" |
| Start title | "Ask about this screen"; else "Ask about this <kind>" |
| Start line | Screen: "Your first message takes this screen's text and a screenshot. Edits ask you first." Else: "Claude works in the hub folder of <project>. Edits ask you first." |
| Starters | group "Start with"; each row its label, tooltip "Sends this message now" |
| Error | "Could not load this conversation", the problem's detail, "Try again" |
| Feature header | "Session" <name>; tooltip "Talk with the session that wrote this feature's records: <name>" |

### States

| State | Panel |
|---|---|
| No project | `EmptyState` "Open something to discuss" (unchanged) |
| Start | Title, one line, starters, composer |
| Working | The live bar ("Running make check · 12 s") and the todo list above the composer |
| Waiting for you | The permission card in the conversation; the live bar reads "Waiting for you" |
| Error | `ProblemError compact` with detail and Try again; a 404 starts over |
| Unavailable | `Banner` warning (unchanged) |
| Over the page | `shadow-overlay`, no scrim, no `margin-right` on the page |

### Accessibility

The panel is an `aside` named "Discuss with Claude" (a landmark, no focus trap). The edge is a full separator, its
hit area the panel's full height; Widen is the single-pointer way. The status keeps icon and label. The shell's axe
test runs with the panel open (`AppShell.test.tsx`, a11y).
