# Conventions

How agent-hub code is written. The decision is [ADR 0006](adr/0006-conventions-and-english.md): Clean Code, enforced by a
tool wherever a tool can check it. Each rule below is marked **enforced by <tool/rule>** (a gate fails) or
**review-only** (the reviewer checks it). Test conventions are in [TESTING.md](TESTING.md); where code goes is in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Names

| Rule | Enforcement |
|---|---|
| Names reveal intent and are pronounceable. No abbreviations, except `id`, `url`, `http` and `api` (`session_id`, not `sess_id`; `transcript`, not `tx`). | review-only (casing is enforced by ruff `N`) |
| Classes are nouns (`TranscriptParser`); use cases are verb + object (`IngestTranscript`, `GenerateHub`); functions are verbs (`parse_line`); booleans are questions (`is_active`, `has_cost`). | review-only |
| One term per concept, matching the SPEC glossary below. "run", "job" and "execution" are never synonyms for Session; a workflow execution is a `WorkflowRun`. | review-only |
| No modules or folders named `utils.py`, `helpers.py`, `common.py`, `misc.py` (nor `util`, `helper`); name the module after what it does. | enforced by the layout checker (`forbidden-module`) |
| A src module name does not end in `_<digits>` (`rfc9457.py`, not `rfc_9457.py`), because its mirrored test would be a numbered name. | enforced by the layout checker, indirectly (`numbered-name` on the mirrored test) |

### Glossary

The terms of the [SPEC](SPEC.md). Code, docs, API paths and log fields use exactly these words.

| Term | Meaning |
|---|---|
| Project | A product with 1 to N repos and a task tracker |
| Hub | The project's control repo: rules, brain, workflows, plugin, scripts |
| Repo | A code repository managed by the hub, with its own `AGENTS.md` |
| Workflow | A sequence of steps with gates, approvers and limits |
| WorkflowRun | One execution of a workflow; it contains Sessions |
| Agent | A role with instructions, tools and a model |
| Session | One concrete execution of an agent, with a transcript, cost and outcome |
| Brain | Curated, versioned knowledge with provenance |
| Learning | Something learned in a session, proposed and then accepted or rejected |

## Functions

| Rule | Enforcement |
|---|---|
| Small functions that do one thing, at one level of abstraction. | review-only |
| McCabe complexity at most 8. | enforced by ruff `C901` (`max-complexity = 8`) |
| At most 3 positional parameters; pass the rest as keyword-only (after `*`) or as a model. | enforced by ruff `PLR0917` (`max-positional-args = 3`) |
| No boolean flag parameters that switch behavior; write two functions, or make the option keyword-only. | enforced by ruff `FBT` (`FBT001`, `FBT002`, `FBT003`) |

**Why `PLR0917` is spelled out.** `pyproject.toml` selects the exact code `"PLR0917"`, never a prefix. Before ruff 0.16
it was a preview rule, and with `explicit-preview-rules = true` the prefix `"PLR"` would enable nothing; from ruff 0.16
(the lockfile pins 0.16.x) it is stable, and `"PLR"` would switch on every other pylint refactor rule as well, which is a
different policy. `tests/e2e/test_quality_gates.py` fails if the exact code is removed or replaced by a prefix.

## Types and data

| Rule | Enforcement |
|---|---|
| Full static typing: every function annotated, generic types parameterized. | enforced by mypy strict (`mypy.ini`: `strict = True`; e.g. `no-untyped-def`) |
| Domain models are frozen Pydantic models (`model_config = ConfigDict(frozen=True)`). | review-only |
| No bare dicts across package boundaries: public functions and ports take and return models or typed values. | review-only (mypy strict makes `dict[str, Any]` visible) |

## Errors

| Rule | Enforcement |
|---|---|
| Named domain exceptions in a per-package hierarchy: `agent_hub.core.errors.AgentHubError` is the root; each package has `errors.py` with its own base (`StorageError`, `CollectorError`) and subclasses. | review-only |
| Never swallow errors: no `except Exception: pass`, no bare `except`. | enforced by ruff `BLE001` and `S110` |
| Adapters translate external errors (database, HTTP, file formats) into the package's domain exceptions at the boundary; core never sees a library exception. | review-only |

## Comments

| Rule | Enforcement |
|---|---|
| Comments explain why, not what; the code says what. | review-only |
| No commented-out code; git keeps history. | enforced by ruff `ERA001` |
| A `# noqa: <code>` or per-file ignore names the exact code and carries a comment with the reason. | review-only |

## Logging

| Rule | Enforcement |
|---|---|
| Structured JSON logs, with `session_id` and project context on every record that has them. | review-only |
| Never log secrets, tokens or raw transcript content. | review-only |

The logging library is chosen with the first logging code (likely `structlog`); these rules apply from then on.

## Language

| Rule | Enforcement |
|---|---|
| English everywhere: code, comments, docs, ADRs, commits, PRs and issues. | review-only |

## Formatting and other lint

| Rule | Enforcement |
|---|---|
| Code is formatted by ruff (line length 100). | enforced by ruff format (`ruff format --check`) |
| Imports are sorted, `agent_hub` first-party. | enforced by ruff `I` |
| Modern syntax for the target version (py314). | enforced by ruff `UP` |
| Common bugs and simplifications. | enforced by ruff `B`, `SIM`, `E`, `F`, `W` |
| Security checks (`S`), with `assert` allowed in tests and subprocess calls of known tools in `scripts/` and `tests/e2e/`. | enforced by ruff `S` (per-file ignores `S101`, `S603`, `S607`) |

Run everything with `make check-fast`; the rules are configured in `pyproject.toml` (`[tool.ruff]`) and `mypy.ini`.
`tests/e2e/test_quality_gates.py` (in `make check`) runs ruff and mypy with these configs against scratch modules that
break `C901`, `PLR0917`, `FBT001`, `BLE001`, `S110`, `ERA001`, the formatter and `no-untyped-def`, so a config change that
switches one of them off fails the gate. It reads ruff's JSON output (`ruff check --output-format json`), because the
text output names the rules instead of printing their codes.
