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
  `~/.local/share/agent-hub/agent-hub.db`, where `~` is `HOME` when it is non-empty and absolute, else the account's
  home from the password database. `packages/cli/tests/conftest.py` has an autouse fixture that points `HOME`
  and `XDG_DATA_HOME` under `tmp_path` and unsets `AGENT_HUB_DB` for every cli test; a test that needs other values
  passes them to `CliRunner.invoke(env=...)`. JSON Lines inputs are written to `tmp_path` at test time from the
  builders (`an_event`, `events_to_jsonl`); no `*.jsonl` file is committed.

## Levels

| Level | What it tests | Where | Runs in |
|---|---|---|---|
| unit | Core logic against in-memory fakes; one module at a time; no I/O, no network | `packages/<pkg>/tests/unit/`, root `tests/unit/` (repo scripts) | `make check-fast` |
| contract | A port's behavior: one suite in `agent_hub.core.testing.contracts`, run against the fake (`agent_hub.core.testing.fakes`) and against the real adapter; no network | `packages/<pkg>/tests/contract/` | `make check-fast` |
| integration | Adapters against real infrastructure: a SQLite file under `tmp_path`, Alembic upgrade and downgrade; the generator's rendered hooks, scripts and `./hub` shim run in a temporary hub, with the characterization goldens; the CLI commands against local bare repos | `packages/<pkg>/tests/integration/` | `make check` |
| e2e | The installed product and the gates as subprocesses: `hub` installed with `uv tool install`; `docs/USING.md`'s runbook run line by line; ruff and mypy run with the repo's configs; the import-linter contracts; the rendered hooks and scripts linted for Python 3.9; the package data the built wheels ship; `make demo`'s seed against `hub web` | root `tests/e2e/` | `make check` |
| docker | The image and its Compose service, built and run, checked from the host (`tests/e2e/test_docker.py`, marker `docker`) | root `tests/e2e/` | `make test-docker` and its CI job, never `make check` |
| live agent | A real `claude -p` session in a temp hub, seen through `hub web`, and a session `hub web` drives whose `git push origin main` the guard denies (`tests/e2e/test_live_agent.py`, marker `live("claude")`) | root `tests/e2e/` | `make test-live`, by hand |
| web | The React app: Vitest + Testing Library in jsdom for components and screens (states, a11y with `axe-core`), against `src/testing/builders.ts` fixtures and a mocked API (`renderWithApi`) | `apps/web/src/**/*.test.{ts,tsx}` beside the code | `make check-fast` (`web-fast`) |
| web smoke | The built app on an installed `hub web`: Playwright (Chromium) opens the printed token URL, visits the nine P2 pages of a synthetic scenario, and drives an agent session against the stub `claude` through two reloads | `apps/web/e2e/smoke.spec.ts`, driven by root `tests/e2e/test_web_smoke.py` | `make check` (`test-e2e`) |

A port's suite is written once, as reusable tests in `agent_hub.core.testing.contracts`, and each implementation's
`tests/contract/` runs it against that implementation, so the fake used by unit tests is proven to behave like the real
adapter. The first suite is `EventStoreContract`: a class of tests that take an `event_store` fixture. Each
implementation's `tests/contract/conftest.py` provides that fixture (`packages/core/tests/contract/` returns an
`InMemoryEventStore`; `packages/storage/tests/contract/` returns `open_event_store(tmp_path / "events.db")`, a migrated
SQLite file), and a test module subclasses the suite (`class TestSqliteEventStore(EventStoreContract)`).
The second is `TrackerClientContract`, whose tests take a `tracker_client` fixture and the `tracker_backend` it reads and
writes (`a_seeded_tracker_backend()`, synthetic issues only); the suite asserts on the backend's state. It runs against
`InMemoryTrackerClient` (`packages/core/tests/contract/`) and against `LinearGraphqlTrackerClient`
(`packages/tracker_linear/tests/contract/`), whose transport is `FakeLinearApi`, an in-process fake of Linear's GraphQL
API over the same backend (`packages/tracker_linear/tests/conftest.py`), so no socket opens, and against
`McpTrackerClient`, whose runner is `FakeClaude`, an honest model over the same backend in the same conftest, so no
`claude` process starts.
The third is `BrainChangeRequestsContract` (`agent_hub.core.testing.brain_change_requests_contract`), whose tests take a
`brain_change_requests` fixture and a `brain_origin` that reads what reached the hub's `origin` (its commits and the
pull requests opened). It runs against `InMemoryBrainChangeRequests` with `FakeBrainOrigin`
(`packages/core/tests/contract/`) and against `GitBrainChangeRequests` (`packages/hub_git/tests/contract/`), with real
`git` over a git-backed origin.
The fourth is `TrackerReaderContract` (`agent_hub.core.testing.tracker_reader_contract`, ADR 0025), whose tests take a
`tracker_reader` fixture and the `issue_board` it reads (`a_seeded_issue_board()`, synthetic issues with "blocks"
relations; `FakeIssueBoard` in `agent_hub.core.testing.tracker_reader_fakes`). It runs against `InMemoryTrackerReader`
(`packages/core/tests/contract/`) and against `LinearGraphqlTrackerReader` (`packages/tracker_linear/tests/contract/`)
over `FakeLinearApi`, which serves the board with Linear's field names (`relations` and `inverseRelations` of type
`blocks`, a float `priority`, `assignee { displayName }`). Because the fake is written from the same reading of the
schema as the adapter, the reader's strict shape check is also run against `SYNTHETIC_SUMMARIES_ANSWER`, a
hand-written answer in the shape of Linear's public schema (in the same conftest; no recorded Linear data). The real
schema is checked only by the by-hand `live` test (`test_linear_live.py -k summaries`, with a real key; never in a gate).
The same fakes module holds what the app's tests use instead of Linear: `CountingTrackerReader` (counts reads, for the
cache), `FailingTrackerReader(kind, http_status=)` (each failure kind) and `InMemoryTicketSnapshots`. The API's tests
reach the GraphQL reader end to end through `build_app(linear_post=…)`, an injected transport, with a synthetic key in
the injected environment: no socket opens and no real key is read.

The fifth and sixth are the agent sessions' (ADR 0027). `SessionDriverContract`
(`agent_hub.core.testing.session_driver_contract`) takes `session_driver` and `scenario` fixtures and checks event order, `init`
before text, a `result` with cost and usage ending each turn, `exited` after close, and a permission request parked
until answered. It runs against `InMemorySessionDriver` (`agent_hub.core.testing.session_driver_fakes`, scripted turns
per message, `Hold` to park a turn; `packages/core/tests/contract/`) and against `ClaudeSdkSessionDriver`
(`packages/claude_sessions/tests/contract/`) driving the **stub CLI**: `agent_hub.claude_sessions.testing.stub_claude`,
run by a `claude` shim on `PATH` (`scenarios.write_shim`), plays a synthetic `Scenario` (`STUB_CLAUDE_SCENARIO`) over
Claude Code's stream-json and control protocol, answers `--version`, `--help` and the `--cloud` forms, can spawn a
tool grandchild, and appends what it saw to `STUB_CLAUDE_RECORD`. No recorded real output is committed, and no test
calls a model. A subclass sets `pytestmark = pytest.mark.anyio`. `AgentSessionStoreContract`
(`agent_hub.core.testing.agent_session_store_contract`) takes an `agent_session_store` fixture and runs against
`InMemoryAgentSessionStore` and `SqliteAgentSessionStore`. `agent_hub.core.testing.agent_session_rig` (`build_rig`)
puts `AgentSessionControl` over the in-memory driver and store with a clock the test moves; the API's
`agent_session_app` fixture serves the routes over it with the cookie and `Origin` preset. The e2e tests run the
installed `hub web` (with the `sessions` extra) against the stub on `PATH` (the `stub_claude` fixture), never a fake
driver selected in production.

**Async tests.** The use case and the adapter are async: such tests are `@pytest.mark.anyio` and run on asyncio only
(the root `conftest.py`'s `anyio_backend`, as `hub web`'s loop); time is a fake clock and `sweep(now)`, never a sleep.

`hub_git` is tested at three levels, all without the network and without a real GitHub account:

- **unit** (`packages/hub_git/tests/unit/`): the push guard (`test_refspec_guard.py -k refuses`: the default branch, a
  `+` or `:` refspec, `--force` and `-f`, an invalid name and a branch outside `<prefix>learning-` raise before git
  runs), the runner over an injected `Launch` and clock (deadline, argv, environment), the remote parsing, and the
  adapter's refusals before any git runs;
- **contract**: the suite above;
- **integration** (`packages/hub_git/tests/integration/`): the adapter against a real bare repository in `tmp_path` as
  the hub's `origin`, the user's checkout cloned from it, and a fake `gh` on `PATH` (`packages/hub_git/tests/conftest.py`).
  The origin's URL stays `https://github.com/acme/demo-hub.git`, as a real hub's is; a global git config under the
  test's own `HOME` rewrites it to the bare repository (`url.<bare>.insteadOf`), so git never reaches the network. The
  fake `gh` is a stdlib script that records its calls, answers `gh auth token` unless a `logged-out` switch is set, and
  for `gh pr create` checks that the head branch is on the origin and prints a PR URL, or fails (`fail`) or prints
  something else (`garbage`). The tests check the branch's one commit (the hub author, no trailer), that
  `origin/main` is unchanged, that the user's checkout is unchanged (`HEAD`, `git status`, `git for-each-ref`), that a
  failed `gh` deletes the pushed branch, and that no temporary folder is left.

The API's integration tests for the learning decisions and the web smoke drive the same kind of synthetic hub (a bare
`origin` and a fake `gh`) through `hub web`.

A test that runs a rendered hook or script takes the `hook_python` fixture, so it runs on the current Python and on a
real Python 3.9 (the system `python3` on macOS); without a 3.9 on `PATH` that case skips, and under `CI` it fails. A
characterization case compares a hook's or script's exit code, stdout, stderr, files and calls to fake tools with
`packages/generator/tests/integration/golden/<file>/<case>.golden`, stored byte-exact (`-text` in `.gitattributes`).
`GOLDEN_UPDATE=1` rewrites the goldens (refused under `CI`; review and commit the diff) and `GOLDEN_KEEP=1` keeps each
case's temporary root and prints its path. The `hub init` golden,
`packages/cli/tests/integration/golden/init/demo.hub.lock`, is the synthetic `demo` init's `hub.lock` with
`platform_version` as `<VERSION>` and every hash kept, so a template change shows as a reviewed hash diff; it is `-text`
too, and `GOLDEN_UPDATE=1` rewrites it the same way (the cli conftest's own harness, refused under `CI`).
The text a two-team hub renders where it names the tracker teams, the text a hub with conventions renders where
it shows them, and the seeded starter `AGENTS.md` for app repos are checked in byte-exact under
`packages/generator/tests/integration/rendered/two_teams/<path>.golden`, `rendered/conventions/<path>.golden` and
`rendered/app_repo_agents/<path>.golden` (`-text`) by `test_rendered_text.py`; `GOLDEN_UPDATE=1` rewrites them (refused
under `CI`).

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
  `packages/core/src/agent_hub/core/ingestion/ingest_events.py` →
  `packages/core/tests/unit/ingestion/test_ingest_events.py`. A package `foo/__init__.py` is mirrored by
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
- `live` is the one marker written by hand: a test that calls a real external API (the Linear smoke test,
  `packages/tracker_linear/tests/integration/test_linear_live.py`). Under `integration/` it also gets `integration`,
  but `make test-integration` selects `integration and not live`, so `make check` never reaches Linear, even with the
  variables exported. Any other pytest run that collects it (for example
  `$R pytest -m live packages/tracker_linear/tests/integration`) reaches Linear only when `LINEAR_API_KEY`,
  `AGENT_HUB_LIVE_ISSUE` and `AGENT_HUB_LIVE_LABEL` are set and `AGENT_HUB_LIVE=1`; otherwise the same plugin skips each
  case, naming the first missing variable. A test marked `live("mcp")` reaches Linear through its MCP server instead
  of the key, so it needs the same variables except `LINEAR_API_KEY`, plus `AGENT_HUB_LIVE_HUB`, the hub root `claude`
  runs from (the cwd production uses). Both smoke tests flip `AGENT_HUB_LIVE_LABEL` on the issue, so it is never the
  ready label; the MCP one fails at setup when it is `agent-ready` or the hub's `tracker.ready_label`.

`live("claude")` marks `tests/e2e/test_live_agent.py`: it needs only `AGENT_HUB_LIVE=1` (`make test-live` sets it)
and skips itself when `claude` is missing or not logged in for a fresh `CLAUDE_CONFIG_DIR`. Its hub, database, Claude
Code config and transcript live in one temp folder that is deleted afterwards; it costs a few cents (Claude Haiku 4.5,
at most three turns; `AGENT_HUB_LIVE_MODEL` picks another model).

`docker` is the other hand-written marker: `tests/e2e/test_docker.py` builds the image (`agent-hub:local`), starts the
Compose service under its own project name, port, hubs root and data volume, and removes them afterwards. Without a
Docker daemon it skips, and under `CI` it fails. `make test-e2e` selects `e2e and not docker and not live`.

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

Hypothesis property tests are required for secret redaction and for the transcript parser, and are named
`test_<behavior>_when_<condition>_property` (`-k property` selects them): secrets inserted at random offsets never
survive and redacting twice equals redacting once (`core:tests/unit/redaction/test_redact.py`); arbitrary transcript
lines never raise and keep only the "Payload kept" keys (`collector:tests/unit/test_transcript.py`). Hypothesis is a
dev dependency of the workspace.

## Web tests

- Every screen has a `-t states` test (loading skeleton after 300 ms, empty copy, a region-scoped problem with "Try
  again", stale and offline) and a `-t a11y` test (no `axe-core` violation of impact serious or critical,
  `src/testing/axe.ts`). Fixtures come only from `src/testing/builders.ts`; ESLint refuses a `*.json` import in a test.
- Coverage: Vitest with V8, 80% of lines and of branches over `src/` (the generated `schema.d.ts`, `main.tsx` and
  `src/testing/` excluded), in `web-fast`.
- The smoke: `tests/e2e/test_web_smoke.py` installs `hub`, starts `hub web` on a temp database and registry, registers
  two synthetic hubs (`hub init`), ingests a synthetic scenario (two projects, one live session with a guard denial,
  one session waiting on a guard ask, one failed run, one 5,000-event session) through `POST /events/hooks` and
  `hub collect`, and runs `npm --prefix apps/web exec playwright test` with `AGENT_HUB_WEB_URL`. Each page must load
  with no console error, no page error, no request to another host and no serious or critical axe violation; Session
  detail of the 5,000-event session must be complete in under 2 s. Playwright never downloads a browser here: the test
  passes the Chromium headless shell found under `PLAYWRIGHT_BROWSERS_PATH` (else Playwright's cache) as
  `AGENT_HUB_CHROMIUM`. Without npm or a Chromium it skips locally and fails under `CI`.
- The same module checks the committed bundle for absolute URLs (AC-200.56): only an exact list of inert strings is
  allowed (React's and React Router's error-text doc links, XML namespace ids, React Router's `http://localhost`
  parsing base); any other URL, such as an external font, script or API, fails.

## Coverage

Floors, counting lines and branches together (`(covered_lines + covered_branches) / (num_statements + num_branches)`)
per package directory:

| Package | Floor |
|---|---|
| `core` | 90% |
| every other package (`api` included) | 80% |
| `apps/web` (Vitest, lines and branches separately) | 80% |

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
(`ruff check`), `typecheck` (`mypy`, strict), `layout` (the layout checker), `lockstep` (the cli and meta versions are
equal), `openapi-check` (the committed `openapi.json` and `schema.d.ts` match the app), `test-fast` (unit and contract
tests with coverage) and `web-fast` (`npm ci`, then typecheck, ESLint, Prettier check, tokens drift and Vitest with
coverage).

`make check` (before a PR, and in CI) runs `check-fast`, then `test-integration`, `test-e2e`, `imports`
(`lint-imports`), `migrations` (upgrade a scratch SQLite database to head, then `alembic check`), `coverage` (the
floors) and `web-dist-check` (rebuild the web app in a scratch folder and diff it with the committed `web_dist/`).
The API's integration tests (including `test_performance.py`, the NFR budgets on 10,000 synthetic events) run in
`test-integration`, and the web smoke in `test-e2e`.

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
- `tests/e2e/test_hub_cli.py` installs `hub` once per module (the `installed_hub` fixture in `tests/e2e/conftest.py`,
  which rebuilds every workspace package, so a stale uv cache entry is never installed),
  then checks `hub --version` and runs `hub collect` twice with `HOME` and `XDG_DATA_HOME` under `tmp_path` and a working
  directory outside the repo: the second run reports only duplicates, and the default database is at the Alembic head.
  This proves the installed package ships and applies its own migrations. It also runs `hub init` of the `demo` flags
  and checks that the installed `hub` writes the same `hub.lock` as an in-process run, and that `hub doctor` on a
  fresh `demo` hub exits 0 and prints only `0 errors, 0 warnings, 0 infos`.
- Redirect gate output to a file and check the exit code: `make check > check.log 2>&1; echo $?`. `make check | tail`
  hides a failure.
