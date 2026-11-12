# 0062. The model may load the hub's read-only skills, and a skill named anywhere in a prompt runs

- Status: proposed
- Date: 2026-11-12
- Deciders: José Henrique Roquette

## Context and Problem Statement

In a `hub web` session in the tipple hub (pinned to v0.35.1), the owner wrote a message that started with "claude, …"
and asked, in the middle of the text: "vamos usar a /overengineering-review para fazer uma review". The model answered
"There is no `/overengineering-review` skill in this session" and did the review by hand. Two causes, checked in the
session's transcript and in the code:

1. **The skill was hidden from the model.** It was loaded (`.claude/skills/overengineering-review` links into the base
   plugin), but its frontmatter had `disable-model-invocation: true`. Claude Code then leaves a skill out of the model's
   skill listing, and the `Skill` tool refuses it. Of the hub's 28 base skills, only 5 were in the listing
   (`create-plan`, `plain-language`, `recall`, `research`, `summarize`). The flag became the generator's default in
   `83a3da444` ("base plugin skills") with no ADR and no recorded reason, and a unit test pinned it as the default.
2. **A `/name` that does not start the message is plain text.** Claude Code expands `/<name>` only at position 0 of the
   prompt; checked with `claude -p` 2.1.322: `"/userskill hello"` runs the skill, `"  /userskill hello"` makes the
   model answer that no such skill exists. `hub web` does the same: `claude_sessions/invocations.py` rewrites only a
   leading `/<name>` (to `/<plugin>:<name>`) and `/agent-<name>` mentions.

The owner wants a more autonomous agent to use the skills and subagents the hub already has, deciding by itself when a
skill is needed, in every session the hub starts or serves (a terminal in the hub, `hub web` in and outside the hub,
cloud sessions), and a skill he names anywhere in a message to run as if he had typed it first.

## Considered Options

For which skills the model may load:

- **(A1) Keep every flow user-only.** Safe, but the model cannot reach the review and design skills the hub ships, and
  the owner has to know and type each one.
- **(A2) Open every skill.** The model could start `/review` (which posts on a PR) or `/deliver` (which pushes and
  replies on threads) by itself. The owner never lets an agent post on PRs.
- **(A3) Open the skills that act only inside the session; keep user-only those that act outside it.** Chosen.

For a skill named mid-message:

- **(B1) A `hub web`-only rewrite** in `invocations.py`. Fixes one surface; a terminal session and any session started
  by `hub run` or the autonomous mode keep the bug.
- **(B2) A rule in the hub's instructions alone.** Works in every session that loads the hub's instructions, but leaves the model
  to notice the token, decide it is a skill and find a user-only skill's file by itself.
- **(B3) A `UserPromptSubmit` hook in the base plugin, plus the short rule.** Chosen. The hook runs wherever the hub's
  hooks run (the hub's `.claude/settings.json`, and the plugin's `hooks.json` that `hub web` loads outside the hub
  through `StartSpec.plugin_dirs`); the rule covers the sessions that load the hub's instructions but not its hooks.

## Decision Outcome

Chosen: **A3 and B3**.

### The split

A base skill has no `disable-model-invocation` (the model may load it) when it only reads, or writes what stays in the
session's own working tree for the user to review. Its own gates still hold.

| Model-invocable | Why it is safe |
|---|---|
| `design-fit` | Read-only; answers in at most five lines |
| `overengineering-review`, `ux-review` | "never edits, commits, pushes or posts" |
| `premortem`, `context-audit` | "edits nothing" |
| `test-strength` | Reads the suite; mutation runs cost time, not changes |
| `property-based-testing` | Writes test files only; no commit, never production code |
| `kickoff` | Reads, runs `check_fast`, asks before starting ("Never start editing during /kickoff") |
| `learn` | The default route writes a proposal in `brain/_inbox/`, which the hub's `AGENTS.md` already asks agents to do; `promote` opens the hub PR only after the owner's gate |
| `create-plan`, `plain-language`, `recall`, `research`, `summarize` | Already model-invocable |

A base skill keeps `disable-model-invocation: true` (user-only) when it acts outside the session:

| User-only | What it does outside the session |
|---|---|
| `review` | Posts PR reviews; the owner never lets an agent post on PRs |
| `deliver` | Replies to review threads, pushes, moves issues to Done |
| `handoff` | Moves issues to Done, may open a hub PR |
| `release` | Dispatches the tag workflow |
| `feature`, `implement`, `fix`, `refactor`, `upgrade`, `adr` | Worktree, commit, push, PR, tracker state |
| `triage`, `incident`, `retro`, `onboard` | Write to the tracker; `retro` and `onboard` also open hub PRs |

`test_render_hub.py` holds both sets explicitly (their union is every base skill, so a new skill must be placed), and
fails when a model-invocable skill's text names an outward act (`git push`, `gh pr create|review|comment|merge|edit`,
`gh workflow run`, a GitHub or Linear write tool, `hub run`, "open the PR", "push the branch", "post the review", "move
it to Done", "create the tracker issue", …), except the two owner-gated acts named above for `learn` and `kickoff`.

### The hook

`plugin/hub-workflow/hooks/prompt_skills.py`, a second group on `UserPromptSubmit` after the event sensor's (5 s), in
both the managed `.claude/settings.json` and the plugin's `hooks.json`:

- **Tokens.** `/<name>` or `/<plugin>:<name>`, names of letters, digits, `_` and `-`; whitespace or the start of the
  prompt before it; the end, whitespace, or trailing punctuation followed by one of those after it. `/usr/bin/fix`,
  `a/fix`, `/fix.py`, URLs, `"/fix"` and `` `/fix` `` do not count.
- **The leading command is skipped.** `UserPromptSubmit` receives the raw prompt, the CLI's own leading `/<name>`
  included (checked: the hook's input for `"/userskill hello"` is that string), so the token at position 0 is the
  CLI's and is not named twice. With any character before it the CLI does not expand it, so it counts.
- **Only existing skills.** Each name is looked up as a folder, never globbed: the hub's
  `.claude/skills/<name>/SKILL.md`, then `skills/<name>/` of the hook's own plugin and of each `<hub>/plugin/<p>/`. An
  unknown name adds nothing.
- **Output.** One `additionalContext` listing each skill in order, once, at most 10: "the user invoked these skills by
  name in this message; run each one, in this order, as if the message had started with it; its own gates and approvals
  still hold", with, per skill, the `Skill` tool and the name it takes (bare in the hub, `<plugin>:<name>` when
  `CLAUDE_PLUGIN_ROOT` shows the hooks run from the plugin), or, for a user-only skill, which the `Skill` tool refuses,
  "Read `<path>/SKILL.md` and follow it".
- **Every skill the user names runs, the 14 user-only ones included.** The owner typing a skill's name is user
  invocation, wherever it is. The reason for the user-only flag (the model starting an outward flow by itself) does not
  apply, and each skill's own gates still hold.
- **Bounds.** Stdlib only, Python 3.9, through `hubhooks.run_hook` (fail open: an error prints one stderr line and
  exits 0, never blocks the prompt); the prompt is scanned up to 100,000 characters; a few `stat` calls and at most 10
  frontmatter reads of 8 KiB.

B3 was chosen over B1 because the hook covers every session that runs the hub's hooks with one piece of code, and
`invocations.py` needs no change: a mid-message name stays plain text there and the hook names it.

### The rule

Two short texts, since every session pays for them; the skill descriptions carry the "when":

- Step 6 of the hub's `AGENTS.md` Workflow, one line: use the hub's skills and subagents as the work needs; a push, PR
  or tracker flow runs only when the user names it. The rendered `AGENTS.md` stays within the doctor's 100-line cap
  (`instructions.size`) in its largest test shape because the `brain/` line was shortened to one line.
- A bullet in the hub's `CLAUDE.md` Claude Code notes, two lines: a `/<skill>` the user writes anywhere in a message runs
  as if typed first, with the `Skill` tool, or by reading its `SKILL.md` when the tool refuses it (a user-only skill).
  It is about Claude Code's tools, so it lives in `CLAUDE.md`, which Claude Code loads also where the hub's hooks do
  not run (multi-repo cloud sessions load the attached hub's `CLAUDE.md`).

### Consequences

- Good: the model sees 14 of the hub's skills instead of 5 and can run `design-fit` before code or
  `overengineering-review` before a PR by itself; the owner can name any skill anywhere in a message.
- Good: the outward flows stay behind the owner, and a test fails if one of them, or a skill whose text acts outside the
  session, is opened by mistake.
- Bad: every session pays for 9 more skill descriptions, about 3,200 characters (~800 tokens). Each stays under the
  1,024-character limit `/context-audit` checks.
- Bad: one more hook process on every prompt (a Python start and a few `stat` calls).
- Cloud sessions opened multi-repo (`/home/user` with the hub attached) load the hub's `.claude/skills/` from the
  additional directory, so they list the 9 skills once the hub is synced; they load none of the hub's hooks (playbook
  `cloud-and-local.md`, AGH-699 E-22/E-23), so there the hook does not fire and the `CLAUDE.md` bullet is what makes a
  mid-message name run. Loading the hub's hooks in cloud sessions is an environment change left to the owner.

## More Information

- Tracker: AGH-838.
- Autonomous mode (AGH-698): its sessions run with the hub's hooks (its invariant 7), so they get the hook and the
  split. The split is what the conductor may rely on: a model-invocable skill can be loaded by the conductor's sessions
  on their own judgement, while the 14 user-only flows still start only from a named invocation (the owner's, or the
  conductor's explicit `/implement` prompt, which leads its message). Nothing here changes AGH-698's gates.
- Verification (2026-11-12, Claude Code 2.1.322, a hub rendered by `hub init`): in the hub, the skill listing held the
  14 skills and "claude, … vamos usar a /overengineering-review para fazer uma review …" called
  `Skill(overengineering-review)`; "… depois faz o /deliver do PR 1 …" read `.claude/skills/deliver/SKILL.md`; in an
  app repo with `--plugin-dir <hub>/plugin/hub-workflow` (what `hub web` passes as `plugins`), the listing held the
  `hub-workflow:` names and "… vamos usar a /premortem …" called `Skill(hub-workflow:premortem)`.
- Proof in the suite: `packages/generator/tests/integration/test_prompt_skills_hook.py`,
  `test_hooks_fail_open.py`, and in `test_render_hub.py` the two skill sets and the outward-act test.
