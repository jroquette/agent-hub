# 0067. A refused launcher run is denied before the blocked-word rule

- Status: proposed
- Date: 2026-11-14
- Deciders: José Henrique Roquette (change request 2 of AGH-805, 2026-11-14)
- Partially supersedes: [ADR 0038](0038-declared-environments-and-blocked-words.md), for the rule order on a Bash
  call that the launcher-folder rule refuses (0038 is not edited)

## Context and Problem Statement

`./hub pr-watch` runs with no permission prompt and outside the sandbox
([ADR 0063](0063-session-follows-its-own-pr.md)). `./hub` is found in the folder the call runs in. A sandboxed
command can write a file named `hub` in a repo, so the guard has a rule, `launcher_folder`: it denies
`./hub pr-watch` and `./hub worktree` unless the call is the bare command, run from the hub root, with no folder
change.

ADR 0038 says the blocked-word rule runs first on every surface. That rule and the env-file rule read the disk, and a
sandboxed command can make them slow: a folder of many links, or a wildcard over a wide folder. Measured on a copy of
the hooks on 2026-11-14: 15 to 31 seconds. The hook has 10 seconds. Past that, Claude Code goes on with no verdict,
and the allow rule lets the call run. So a rule that answers after those two can be timed out.

Which rule answers first on a Bash call that the launcher-folder rule refuses?

## Considered Options

1. The launcher-folder rule answers first on such a call.
2. The order stays, and a timer stops the two earlier rules when they run long.
3. The order stays, and the two earlier rules stop looking up very long words.

## Decision Outcome

Option 1. On a Bash call, the guard first asks the launcher-folder rule. When that rule refuses the call, the guard
denies at once, with that rule's reason and rule id. In every other case nothing changes: the blocked-word rule runs
first, on every surface, as ADR 0038 says.

- The launcher-folder rule reads the command text and the event's folder. It compares that folder with the hub root
  and opens no other file.
- Its reason names the verb and never repeats the command text, so it shows no blocked word.
- A call that it refuses is denied under either order. Only the reason and the rule id differ.

### Consequences

- Good: the deny arrives in well under a second, whatever the other rules cost (0.13 to 0.19 seconds measured).
- Good: the blocked-word rule, the env-file rule and their bounds do not change.
- Bad: "one rule order" has one exception. A reader of ADR 0038 needs this ADR too.
- Bad: a call that holds a blocked word and a refused launcher run is counted under `launcher_folder` in the guard's
  decisions, not under the blocked-word rule.
- Open: a slow rule can still time the guard out for its other denies. This ADR closes that only for the one command
  that is pre-allowed and runs outside the sandbox. The tracker issues AGH-184 and AGH-841 hold the rest.

### Why not the others

- **Option 2.** It puts a signal timer in the hook's two earliest rules and changes what they answer under load. It
  answered in 1 to 2 seconds on the same copy, and it was not checked against the existing tests.
- **Option 3.** Measured, it fails. Three commands still keep the hook past 10 seconds, each with files a sandboxed
  command can write.

## More Information

- [ADR 0038](0038-declared-environments-and-blocked-words.md): the blocked-word rule and its order.
- [ADR 0063](0063-session-follows-its-own-pr.md): the watch, pre-allowed and outside the sandbox.
- `docs/design/hub-generator.md`: what the launcher-folder rule stops and what stays open at the hub root.
