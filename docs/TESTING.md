# Testing

How agent-hub is tested: the levels, where tests live, how they are named and which gate runs them. The decision is
[ADR 0005](adr/0005-testing-strategy.md). Commands below use `R="uv run --locked --all-packages"`, the same runner the
Makefile uses.

## Principles

- **TDD.** Write the failing test first, run it and see it fail for the expected reason, then implement. A new module's
  first red run usually fails at collection (import error, pytest exit 2); that counts as red.
- **Never weaken an assertion** to make a test pass. Fix the code, or change the test in the open with the reason.
- **Synthetic fixtures only.** Test data comes from builders in `agent_hub.core.testing.builders`. No real transcripts,
  no `*.jsonl` copied from `~/.claude/projects`, no real tokens, keys or personal data, anywhere in the repo.
- **Hermetic.** Unit and contract tests have no network (sockets are blocked). No test reads or writes the real database
  or `~/.claude`; files go under pytest's `tmp_path`. The real database is the file `hub collect` picks: `--db PATH`,
  else `AGENT_HUB_DB`, else `$XDG_DATA_HOME/agent-hub/agent-hub.db` (when `XDG_DATA_HOME` is absolute), else
  `~/.local/share/agent-hub/agent-hub.db`. `packages/cli/tests/conftest.py` has an autouse fixture that points `HOME`
  and `XDG_DATA_HOME` under `tmp_path` and unsets `AGENT_HUB_DB` for every cli test; a test that needs other values
  passes them to `CliRunner.invoke(env=...)`. JSON Lines inputs are written to `tmp_path` at test time from the
  builders (`an_event`, `events_to_jsonl`); no `*.jsonl` file is committed.

## Levels

| Level | What it tests | Where | Runs in |
|---|---|---|---|
| unit | Core logic against in-memory fakes; one module at a time; no I/O, no network | `packages/<pkg>/tests/unit/`, root `tests/unit/` (repo scripts) | `make check-fast` |
| contract | A port's behavior: one suite in `agent_hub.core.testing.contracts`, run against the fake (`agent_hub.core.testing.fakes`) and against the real adapter; no network | `packages/<pkg>/tests/contract/` | `make check-fast` |
| integration | Adapters against real infrastructure: a SQLite file under `tmp_path`, Alembic upgrade and downgrade | `packages/<pkg>/tests/integration/` | `make check` |
| e2e | The installed product and the gates as subprocesses: `hub` installed with `uv tool install`, ruff and mypy run with the repo's configs | root `tests/e2e/` | `make check` |
| web (later) | The React app: Vitest for components, Playwright end to end | `apps/web` (Phase 2) | added with `apps/web` |

A port's suite is written once, as reusable tests in `agent_hub.core.testing.contracts`, and each implementation's
`tests/contract/` runs it against that implementation, so the fake used by unit tests is proven to behave like the real
adapter. The first suite is `EventStoreContract`: a class of tests that take an `event_store` fixture. Each
implementation's `tests/contract/conftest.py` provides that fixture (`packages/core/tests/contract/` returns an
`InMemoryEventStore`; `packages/storage/tests/contract/` returns `open_event_store(tmp_path / "events.db")`, a migrated
SQLite file), and a test module subclasses the suite (`class TestSqliteEventStore(EventStoreContract)`).

## Layout

```
packages/<pkg>/tests/unit/          # mirrors packages/<pkg>/src/agent_hub/<pkg>/
packages/<pkg>/tests/contract/
packages/<pkg>/tests/integration/
tests/unit/scripts/                 # mirrors scripts/
tests/e2e/
```

- A test file lives under exactly one `tests` folder, at the repo root or right under `packages/<name>/`, followed by a
  level folder allowed there: `unit`, `contract` or `integration` in a package; `unit` or `e2e` at the root.
- Test modules are named `test_*.py`. The only other Python files allowed in a tests tree are `conftest.py` and
  `__init__.py`, so shared fixtures and helpers go in a `conftest.py` (for example `tests/e2e/conftest.py` provides the
  `repo_root` and `run` fixtures).
- **Mirroring (unit tests).** A unit test file mirrors an existing src module:
  `packages/core/src/agent_hub/core/ingestion/ingest_transcript.py` →
  `packages/core/tests/unit/ingestion/test_ingest_transcript.py`. A package `foo/__init__.py` is mirrored by
  `test_foo.py`. Root unit tests mirror the repo root: `tests/unit/scripts/test_check_coverage.py` ↔
  `scripts/check_coverage.py`. Contract, integration and e2e tests are named after the behavior, not a module.

## Markers

The folder decides the level; nobody writes level markers by hand.

- `conftest.py` at the root loads `scripts/pytest_levels.py`. Its `level_of(path)` takes the path segment right after
  the last `tests` segment, and its `pytest_collection_modifyitems` hook adds that marker (`unit`, `contract`,
  `integration` or `e2e`) to every collected test. Unit and contract tests also get pytest-socket's `disable_socket`
  marker, so opening a socket raises `SocketBlockedError`.
- The markers are registered in `pytest.ini`, which sets `strict = true` (pytest 9: strict config, strict markers,
  strict parametrization ids, strict xfail). An unregistered marker fails collection.
- `pytest.ini` also sets `--import-mode=importlib` (test basenames repeat across packages and there are no
  `__init__.py` files in tests trees), `testpaths = packages tests` and `pythonpath = .`.
- The layout checker uses the same `level_of`, so a test the checker accepts always gets the marker it expects.

Select a level with `-m`: `$R pytest -m unit`, `$R pytest -m "unit or contract"`, `$R pytest -m integration`,
`$R pytest -m e2e`. A single file: `$R pytest packages/core/tests/unit/test_errors.py`.

## Names

- Test functions (module level, or methods of `Test*` classes) match `test_<behavior>_when_<condition>`, all lowercase:
  regex `^test_[a-z0-9]+(_[a-z0-9]+)*_when_[a-z0-9]+(_[a-z0-9]+)*$`. Example:
  `test_prints_version_when_version_option_given`.
- Forbidden in test file names and test function names:
  - ticket or PR names: `test_pr_987.py`, `test_agh_12.py` (any of `pr`, `agh`, `gh`, `issue`, `bug`, `ticket` followed
    by a number);
  - generic names: `test_misc`, `test_utils`, `test_new`, `test_temp` (also `util`, `helper(s)`, `common`, `tmp`,
    `stuff`);
  - numbered names: `test_ingest_2`, `test_ingest_2_when_x` (a `_<digits>` ending on the behavior or the condition).
- Because test file names mirror src modules, a src module name cannot end in `_<digits>`: write `rfc9457.py`, not
  `rfc_9457.py` (whose test `test_rfc_9457.py` would be a numbered name).
- **Regression tests** go in the test file of the affected module, named after the behavior that broke; the issue id
  goes only in the docstring:

  ```python
  def test_keeps_order_when_events_share_timestamp() -> None:
      """Regression: AGH-42."""
  ```

## Layout checker

`scripts/check_test_layout.py` enforces the layout and names. It runs in `make layout` (part of `make check-fast`),
lists files with `git ls-files` (tracked and untracked, not ignored), prints `<path>: <rule> <message>` for each
violation and exits 1 if there is any. Run it alone with `$R python -m scripts.check_test_layout`.

| Rule id | Fails when |
|---|---|
| `level-folder` | a test file is not under exactly one `tests` folder followed by an allowed level folder |
| `test-file-name` | a Python file in a tests tree is not `test_*.py`, `conftest.py` or `__init__.py` |
| `mirror` | a unit test file has no matching src module (or, at the root, repo file) |
| `test-name` | a test function does not match `test_<behavior>_when_<condition>` |
| `ticket-name` | a test file or function is named after a ticket or PR |
| `generic-name` | the behavior part of a test file or function name is only a generic word (`test_misc.py`, `test_utils_when_empty`) |
| `numbered-name` | a test file or function name ends a part in `_<digits>` |
| `forbidden-module` | a module or folder in `scripts/`, `tests/` or a package's `src/`/`tests/` is named `utils`, `util`, `helpers`, `helper`, `common` or `misc` |
| `package-registered` | a `packages/*/src/agent_hub/<name>/` package is missing from `mypy.ini` (`files`, `mypy_path`), from the `.importlinter` contracts or from the Makefile `COV` list |

At most one of `ticket-name`, `generic-name` and `numbered-name` is reported per name, in that order. The checker's own
tests (`tests/unit/scripts/test_check_test_layout.py`) have a failing and a passing case for every rule.

## Property tests

Hypothesis property tests are required for secret redaction and for the transcript parser. Hypothesis is added as a
dev dependency with the first of them; neither exists yet.

## Coverage

Floors, counting lines and branches together (`(covered_lines + covered_branches) / (num_statements + num_branches)`)
per package directory:

| Package | Floor |
|---|---|
| `core` | 90% |
| every other package | 80% |

- `make test-fast` erases the coverage data, then measures unit and contract tests with branch coverage for every
  `agent_hub` package (the Makefile `COV` list).
- `make test-integration` appends integration tests to the same data. e2e tests run in subprocesses and are not counted.
- Alembic loads the migration scripts by path, under module names no package source matches, so the migrations
  directory is a source of its own in `COV` (`--cov=packages/storage/src/agent_hub/storage/migrations`) and counts
  towards the storage floor.
- `make coverage` writes `coverage.json` and runs `python -m scripts.check_coverage coverage.json`. It prints one line
  per package and fails when a package is under its floor or has no data, when a `packages/*/src/agent_hub/**/*.py` file
  is missing from the report, or when the report has no branch data. Run it after `test-fast` and `test-integration`,
  as `make check` does; on its own it checks stale data.

coverage.py and pytest-cov only offer a global `--fail-under`, which is why the floors are a script.

## Gates

`make check-fast` (while working) runs, in order: `format` (`ruff format --check`), `lint`
(`ruff check`), `typecheck` (`mypy`, strict), `layout` (the layout checker) and `test-fast` (unit and contract tests with
coverage).

`make check` (before a PR, and in CI) runs `check-fast`, then `test-integration`, `test-e2e`, `imports`
(`lint-imports`), `migrations` (upgrade a scratch SQLite database to head, then `alembic check`) and `coverage` (the
floors). The OpenAPI staleness step is added when `packages/api` exists.

Make runs the steps left to right and stops at the first failure. Never run the gate targets with `-j`.

Notes:

- `test-e2e` installs `hub` with `uv tool install` into temporary tool dirs, so it needs the package index or a warm uv
  cache. Offline, `make check` can fail there while `make check-fast` passes.
- `tests/e2e/test_quality_gates.py` runs ruff and mypy with the repo's configs against scratch modules that break each
  convention (complexity, positional params, boolean flags, swallowed exceptions, commented-out code, formatting, missing
  annotations). A config change that switches a rule off fails `make check`. See [CONVENTIONS.md](CONVENTIONS.md).
- `packages/storage/tests/integration/test_migrations.py` upgrades a `tmp_path` database to `head` and downgrades it
  to `base` through `agent_hub.storage.migration.alembic_config`, checks that `alembic check` finds no pending changes,
  covers the offline (`--sql`) mode of `env.py` and runs `python -m agent_hub.storage.migration` as a module.
- `tests/e2e/test_hub_cli.py` installs `hub` once per module (the `installed_hub` fixture in `tests/e2e/conftest.py`),
  then checks `hub --version` and runs `hub collect` twice with `HOME` and `XDG_DATA_HOME` under `tmp_path` and a working
  directory outside the repo: the second run reports only duplicates, and the default database is at the Alembic head.
  This proves the installed package ships and applies its own migrations.
- Redirect gate output to a file and check the exit code: `make check > check.log 2>&1; echo $?`. `make check | tail`
  hides a failure.
