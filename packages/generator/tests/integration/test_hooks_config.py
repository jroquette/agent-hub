"""The rendered hooks read ``hub.json`` through the rendered reader, from their own hub (AC-4.10).

Each hook runs as Claude Code runs it: a file on ``hook_python`` with the event on stdin, in an
environment built from scratch (``HOME`` and ``TMPDIR`` under ``tmp_path``). The hub is the demo
render at ``ws/demo-hub``; the config comes from the hub that holds the hook file (spec Q-4), so the
event's cwd, ``CLAUDE_PROJECT_DIR`` and the process cwd may all point into another hub.
"""

import ast
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterator, Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing import builders
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

HOOKS = "plugin/hub-workflow/hooks"
READER = "plugin/hub-workflow/hooks/stdlib_reader.py"
# The sources as installed (an editable install: the repo folder).
TEMPLATES = Path(str(files("agent_hub.generator").joinpath("templates")))
# AC-4.10's hub.json: three wrong-typed keys; every other key is valid and must be kept.
MISTYPED: dict[str, Any] = {
    "project": {"name": "demo", "branch_prefix": "me/", "default_branch": 7},
    "tracker": {"kind": "linear", "team": "DEM"},
    "repos": {},
    "guard": {
        "ask_before_edit": 5,
        "deny_hosts": ["prod.example.com"],
        "deny_paths": ["@hub/secret-notes"],
    },
}
# The calls that read a file's text: a hook reading hub.json itself would make one of them.
FILE_READS = frozenset({"open", "read_text", "read_bytes", "load", "loads"})
HUB_JSON_NAME = "hub.json"

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]


def write_hub_json(hub: Path, document: Mapping[str, Any]) -> None:
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")


def scratch_env(tmp_path: Path) -> dict[str, str]:
    """``HOME`` and ``TMPDIR`` under ``tmp_path`` (``PATH`` comes from ``child_env``)."""
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir(exist_ok=True)
    temp.mkdir(exist_ok=True)
    return {"HOME": str(home), "TMPDIR": str(temp)}


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub at ``ws/demo-hub``, without a ``hub.json`` yet."""
    rendered = rendered_hub(demo_config).resolve()
    assert rendered.name == "demo-hub"
    return rendered


@pytest.fixture
def elsewhere(tmp_path: Path) -> Path:
    """A folder with no hub above it or beside it: the process cwd when nothing else is given."""
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    return folder


@pytest.fixture
def run_hook(
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    elsewhere: Path,
    tmp_path: Path,
) -> Callable[..., subprocess.CompletedProcess[bytes]]:
    """Run ``<hub>/<HOOKS>/<name>.py`` with ``event`` as JSON; the cwd defaults to ``elsewhere``."""

    def run(
        name: str,
        event: Mapping[str, Any],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return run_hook_file(
            hook_python,
            hub / HOOKS / f"{name}.py",
            stdin=json.dumps(event).encode(),
            cwd=cwd or elsewhere,
            env=scratch_env(tmp_path) | dict(env or {}),
        )

    return run


def verdict_of(completed: subprocess.CompletedProcess[bytes]) -> tuple[str, str] | None:
    """The guard's ``(decision, reason)``, or ``None`` when it printed nothing."""
    assert completed.returncode == 0, completed.stderr
    if not completed.stdout.strip():
        return None
    output = json.loads(completed.stdout)["hookSpecificOutput"]
    return output["permissionDecision"], output["permissionDecisionReason"]


def bash_event(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def only_file(folder: Path) -> str:
    """The text of the one file in ``folder`` (the hooks name it after the day)."""
    files = sorted(folder.iterdir()) if folder.is_dir() else []
    assert len(files) == 1, files
    return files[0].read_text(encoding="utf-8")


def test_falls_back_per_key_when_hub_json_mistyped(
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]], hub: Path
) -> None:
    write_hub_json(hub, MISTYPED)
    # The render seeds the folder's `.gitkeep`; `only_file` counts the hook's file only.
    (hub / "brain" / "auto" / "workspace" / ".gitkeep").unlink()
    app = hub.parent / "demo-api" / "docs" / "adr"
    app.mkdir(parents=True)
    edit = {"file_path": str(app / "0001.md"), "old_string": "a", "new_string": "b"}

    guard = {
        "push_main": run_hook("guard", bash_event("git push origin main", hub)),
        "push_trunk": run_hook("guard", bash_event("git push origin trunk", hub)),
        "deny_host": run_hook("guard", bash_event("curl https://prod.example.com/x", hub)),
        "edit": run_hook("guard", {"tool_name": "Edit", "tool_input": edit, "cwd": str(hub)}),
    }
    stop = run_hook("stop_gate", {"cwd": str(hub), "session_id": "mistyped"})
    end = run_hook("session_end", {"session_id": "abcdef123456", "reason": "clear", "cwd": "/w"})
    compact = run_hook("pre_compact", {"trigger": "manual", "cwd": "/w"})

    verdicts = {name: verdict_of(completed) for name, completed in guard.items()}
    # default_branch 7 → "main"; the prefix and the team of the same file are kept.
    assert verdicts["push_main"] == (
        "deny",
        "[hub guard] pushing to main is not allowed; open a PR from a me/dem-<N>-<desc> branch",
    )
    assert verdicts["push_trunk"] is None
    assert verdicts["deny_host"] is not None
    assert verdicts["deny_host"][0] == "deny"
    # ask_before_edit 5 → (): nothing asks
    assert verdicts["edit"] is None
    # repos {} → (): no checkout to gate, so the stop gate is silent
    assert (stop.returncode, stop.stdout) == (0, b"")
    for completed in (*guard.values(), stop, end, compact):
        assert completed.stderr == b"", completed.stderr
    assert (end.returncode, end.stdout, compact.returncode, compact.stdout) == (0, b"", 0, b"")
    assert "session `abcdef12` ended (clear), cwd `/w`" in only_file(
        hub / "brain" / "_inbox" / "sessions"
    )
    assert "- cwd: `/w`" in only_file(hub / "brain" / "auto" / "workspace")


def test_denies_deny_path_when_hub_json_mistyped(
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]], hub: Path
) -> None:
    write_hub_json(hub, MISTYPED)
    notes = hub / "secret-notes" / "plan.md"
    read = {"tool_name": "Read", "tool_input": {"file_path": str(notes)}, "cwd": str(hub)}

    by_read = verdict_of(run_hook("guard", read))
    by_cat = verdict_of(run_hook("guard", bash_event("cat secret-notes/plan.md", hub), cwd=hub))
    other = verdict_of(run_hook("guard", bash_event("cat notes/plan.md", hub), cwd=hub))

    assert by_read == (
        "deny",
        f"[hub guard] {notes} is under guard.deny_paths `@hub/secret-notes` (hub.json); agents"
        " neither read nor change it",
    )
    assert by_cat is not None
    assert by_cat[0] == "deny"
    assert "secret-notes/plan.md" in by_cat[1]
    assert other is None


def test_reads_deny_paths_when_config_loaded(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], elsewhere: Path
) -> None:
    write_hub_json(hub, MISTYPED)
    code = (
        "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
        "print(json.dumps([str(cfg.hub), list(cfg.deny_paths), list(cfg.deny_hosts),"
        " list(cfg.ask_before_edit), list(cfg.repo_dirs), cfg.default_branch, cfg.branch_prefix,"
        " cfg.tracker_team, cfg.project_name]))\n"
    )

    found = run_python(hook_python, code, path=hub / HOOKS, cwd=elsewhere)

    assert found == [
        str(hub),
        ["@hub/secret-notes"],
        ["prod.example.com"],
        [],
        [],
        "main",
        "me/",
        "DEM",
        "demo",
    ]


def test_reads_every_team_when_config_loaded(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], elsewhere: Path
) -> None:
    write_hub_json(hub, MISTYPED | {"tracker": {"kind": "linear", "teams": ["APP", "OPS"]}})
    code = (
        "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
        "print(json.dumps([list(cfg.tracker_teams), cfg.tracker_team]))\n"
    )

    found = run_python(hook_python, code, path=hub / HOOKS, cwd=elsewhere)

    assert found == [["APP", "OPS"], "APP"]


def test_reads_hook_root_config_when_cwd_in_other_hub(
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]],
    hub: Path,
    *,
    rendered_tree: Callable[..., Path],
    tmp_path: Path,
) -> None:
    write_hub_json(hub, {"project": {"name": "demo", "default_branch": "trunk"}})
    document = a_hub_document()
    document["project"] |= {"name": "other", "hub_repo": "acme/other-hub"}
    other_root = tmp_path / "other" / "ws" / "other-hub"
    other = rendered_tree(render_hub(HubConfig.model_validate(document)), root=other_root)
    write_hub_json(other, {"project": {"name": "other", "default_branch": "release"}})
    inside = other / "brain"
    env = {"CLAUDE_PROJECT_DIR": str(other)}

    trunk = run_hook("guard", bash_event("git push origin trunk", inside), cwd=inside, env=env)
    release = run_hook("guard", bash_event("git push origin release", inside), cwd=inside, env=env)
    end = run_hook(
        "session_end", {"session_id": "abcdef123456", "cwd": str(inside)}, cwd=inside, env=env
    )

    verdict = verdict_of(trunk)
    assert verdict is not None
    assert verdict[0] == "deny"
    assert "pushing to trunk" in verdict[1]
    assert verdict_of(release) is None
    assert end.returncode == 0, end.stderr
    assert "session `abcdef12` ended" in only_file(hub / "brain" / "_inbox" / "sessions")
    assert not (other / "brain" / "_inbox" / "sessions").exists()


def test_imports_no_hubconfig_when_templates_read() -> None:
    sources = sorted(path for path in TEMPLATES.rglob("*") if path.is_file())

    naming = [
        str(path.relative_to(TEMPLATES))
        for path in sources
        if "hubconfig" in path.read_text(encoding="utf-8")
    ]

    assert len(sources) > 1
    assert naming == []


def names_in(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def mentions_hub_json(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Constant) and child.value == HUB_JSON_NAME for child in ast.walk(node)
    )


def hub_json_names(tree: ast.AST) -> set[str]:
    """Names bound, anywhere in the module, to an expression that mentions ``hub.json``."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if mentions_hub_json(node.value):
                bound |= {name for target in targets for name in names_in(target)}
    return bound


def call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def hub_json_reads(source: str) -> list[int]:
    """Lines of the calls that open or read ``hub.json``: a file read whose receiver or arguments
    mention ``"hub.json"`` or a name bound to such an expression."""
    tree = ast.parse(source)
    bound = hub_json_names(tree)

    def reads(call: ast.Call) -> bool:
        if call_name(call) not in FILE_READS:
            return False
        parts: list[ast.AST] = [*call.args, *(keyword.value for keyword in call.keywords)]
        if isinstance(call.func, ast.Attribute):
            parts.append(call.func.value)
        return any(mentions_hub_json(part) or names_in(part) & bound for part in parts)

    return sorted(
        {node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and reads(node)}
    )


def rendered_modules(config: HubConfig) -> Iterator[tuple[str, str]]:
    for file in render_hub(config).files:
        if file.path.endswith(".py"):
            yield file.path, file.content.decode("utf-8")


def test_opens_hub_json_only_in_reader_when_sources_read(demo_config: HubConfig) -> None:
    modules = dict(rendered_modules(demo_config))

    readers = {path: lines for path, source in modules.items() if (lines := hub_json_reads(source))}

    # the detector sees both forms, direct and through a name
    assert hub_json_reads('p = hub / "hub.json"\njson.loads(p.read_text())\n') == [2]
    assert hub_json_reads('open(os.path.join(d, "hub.json"))\n') == [1]
    assert READER in modules
    assert len(modules) > 1
    assert readers == {}


def test_reads_named_file_when_hub_config_names_other_json(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], tmp_path: Path
) -> None:
    write_hub_json(hub, {"project": {"name": "demo", "default_branch": "from-hook-root"}})
    folder = tmp_path / "conf" / "settings"
    folder.mkdir(parents=True)
    write_hub_json(folder, {"project": {"name": "x", "default_branch": "from-hub-json"}})
    custom = folder / "custom.json"
    custom.write_text(json.dumps({"project": {"default_branch": "from-custom"}}), encoding="utf-8")
    code = (
        "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
        "print(json.dumps([str(cfg.hub), cfg.default_branch]))\n"
    )

    found = run_python(
        hook_python, code, path=hub / HOOKS, cwd=folder, env={"HUB_CONFIG": str(custom)}
    )

    assert found == [str(folder), "from-custom"]


# Plugin-cache mode: the hooks sit where Claude Code's plugin cache would hold them, so no hub
# holds them and the walk decides. A hub found beside the start counts only for its own repos.
PLUGIN_CACHE = "home/.claude/plugins/cache/agent-hub/hub-workflow/0.1.0/hooks"
SIBLING_HUB_JSON: dict[str, Any] = {
    "project": {"name": "other", "default_branch": "release"},
    "repos": [{"dir": "listed"}],
    "guard": {"deny_hosts": ["prod.example.com"]},
}


@pytest.fixture
def cached_hooks(tmp_path: Path, demo_config: HubConfig) -> Path:
    """The rendered hooks copied into a plugin-cache folder, with no hub above them."""
    cache = tmp_path / PLUGIN_CACHE
    cache.mkdir(parents=True)
    for file in render_hub(demo_config).files:
        if file.path.startswith(f"{HOOKS}/"):
            (cache / Path(file.path).name).write_bytes(file.content)
    return cache


@pytest.fixture
def sibling_workspace(tmp_path: Path) -> Path:
    """``w2``: ``other-hub`` (hub.json + brain/), its listed repo ``listed``, ``unrelated/proj``."""
    workspace = tmp_path / "w2"
    (workspace / "other-hub" / "brain").mkdir(parents=True)
    write_hub_json(workspace / "other-hub", SIBLING_HUB_JSON)
    for folder in ("listed/src", "unrelated/proj"):
        (workspace / folder).mkdir(parents=True)
    return workspace


def run_cached(
    run_hook_file: RunHook,
    *,
    python: str,
    hook: Path,
    event: Mapping[str, Any],
    env: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    cwd = Path(event["cwd"])
    return run_hook_file(python, hook, stdin=json.dumps(event).encode(), cwd=cwd, env=env)


# Hand-edited repo dirs that are not one plain folder name: none may adopt the start.
ODD_DIRS = [None, ".", "..", "./unrelated"]


@pytest.mark.parametrize("odd_dir", ODD_DIRS)
def test_ignores_sibling_hub_when_start_outside_its_repos(
    odd_dir: str | None,
    cached_hooks: Path,
    sibling_workspace: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    tmp_path: Path,
) -> None:
    if odd_dir is not None:
        document = SIBLING_HUB_JSON | {"repos": [{"dir": "listed"}, {"dir": odd_dir}]}
        write_hub_json(sibling_workspace / "other-hub", document)
    project = sibling_workspace / "unrelated" / "proj"
    env = scratch_env(tmp_path) | {"CLAUDE_PROJECT_DIR": str(project)}

    def run(name: str, event: Mapping[str, Any]) -> subprocess.CompletedProcess[bytes]:
        hook = cached_hooks / f"{name}.py"
        return run_cached(run_hook_file, python=hook_python, hook=hook, event=event, env=env)

    host = run("guard", bash_event("curl https://prod.example.com/x", project))
    release = run("guard", bash_event("git push origin release", project))
    end = run("session_end", {"session_id": "abcdef123456", "cwd": str(project)})

    assert verdict_of(host) is None
    assert verdict_of(release) is None
    assert (end.returncode, end.stdout, end.stderr) == (0, b"", b"")
    assert sorted(path.name for path in (sibling_workspace / "other-hub").rglob("*")) == [
        "brain",
        "hub.json",
    ]


@pytest.mark.parametrize(
    "start", ["listed", "listed/src", "listed/.claude/worktrees/t", "other-hub"]
)
def test_finds_sibling_hub_when_start_in_listed_repo_or_hub(
    start: str,
    cached_hooks: Path,
    sibling_workspace: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    tmp_path: Path,
) -> None:
    folder = sibling_workspace / start
    folder.mkdir(parents=True, exist_ok=True)
    env = scratch_env(tmp_path)

    release = run_cached(
        run_hook_file,
        python=hook_python,
        hook=cached_hooks / "guard.py",
        event=bash_event("git push origin release", folder),
        env=env,
    )
    end = run_cached(
        run_hook_file,
        python=hook_python,
        hook=cached_hooks / "session_end.py",
        event={"session_id": "abcdef123456", "cwd": str(folder)},
        env=env,
    )

    verdict = verdict_of(release)
    assert verdict is not None
    assert verdict[0] == "deny"
    assert end.returncode == 0, end.stderr
    assert "session `abcdef12` ended" in only_file(
        sibling_workspace / "other-hub" / "brain" / "_inbox" / "sessions"
    )


# A crash forced inside a hook: ``read_input`` raises, whatever the event. The launcher runs the
# hook file as Claude Code does (``__main__``, ``argv[0]`` the hook) after patching the module.
CRASH_LAUNCHER = """\
import runpy
import sys
hook = sys.argv[1]
sys.path.insert(0, hook.rsplit("/", 1)[0])
import hubhooks
def boom():
    raise RuntimeError("forced")
hubhooks.read_input = boom
sys.argv = [hook]
runpy.run_path(hook, run_name="__main__")
"""
GUARD_CRASH_OUTPUT = (
    b'{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", '
    b'"permissionDecisionReason": "[hub guard] could not check this call (RuntimeError); '
    b'confirm"}}\n'
)


# The rendered hooks folder without the reader: every import of hubhooks fails.
def hooks_without_reader(hub: Path, tmp_path: Path) -> Path:
    broken = tmp_path / "broken" / HOOKS
    shutil.copytree(hub / HOOKS, broken)
    (broken / "stdlib_reader.py").unlink()
    return broken


def test_asks_when_guard_cannot_import_helpers(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, elsewhere: Path, tmp_path: Path
) -> None:
    hooks = hooks_without_reader(hub, tmp_path)

    completed = run_hook_file(
        hook_python,
        hooks / "guard.py",
        stdin=json.dumps(bash_event("git push --force origin main", elsewhere)).encode(),
        cwd=elsewhere,
        env=scratch_env(tmp_path),
    )

    assert (completed.returncode, completed.stdout, completed.stderr) == (
        0,
        GUARD_CRASH_OUTPUT.replace(b"RuntimeError", b"ModuleNotFoundError"),
        b"",
    )


@pytest.mark.parametrize(
    "name", ["post_edit", "stop_gate", "session_start", "session_end", "pre_compact"]
)
def test_prints_skip_line_when_hook_cannot_import_helpers(
    name: str,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    elsewhere: Path,
    tmp_path: Path,
) -> None:
    hooks = hooks_without_reader(hub, tmp_path)

    completed = run_hook_file(
        hook_python, hooks / f"{name}.py", stdin=b"{}", cwd=elsewhere, env=scratch_env(tmp_path)
    )

    assert (completed.returncode, completed.stdout, completed.stderr) == (
        0,
        b"",
        f"[hub {name}] skipped: ModuleNotFoundError\n".encode(),
    )


def run_crashing(
    hook: Path, *, python: str, cwd: Path, tmp_path: Path
) -> subprocess.CompletedProcess[bytes]:
    launcher = tmp_path / "support" / "crash_launcher.py"
    launcher.parent.mkdir(exist_ok=True)
    launcher.write_text(CRASH_LAUNCHER, encoding="utf-8")
    return subprocess.run(  # noqa: S603 - an interpreter from hook_python, a fixed launcher
        [python, str(launcher), str(hook)],
        input=b"{}",
        capture_output=True,
        check=False,
        cwd=cwd,
        env={"PATH": os.environ.get("PATH", os.defpath)} | scratch_env(tmp_path),
        timeout=60,
    )


def test_asks_when_guard_crashes(
    hub: Path, *, hook_python: str, elsewhere: Path, tmp_path: Path
) -> None:
    write_hub_json(hub, a_hub_document())

    completed = run_crashing(
        hub / HOOKS / "guard.py", python=hook_python, cwd=elsewhere, tmp_path=tmp_path
    )

    assert (completed.returncode, completed.stdout, completed.stderr) == (
        0,
        GUARD_CRASH_OUTPUT,
        b"",
    )


@pytest.mark.parametrize(
    "name", ["post_edit", "stop_gate", "session_start", "session_end", "pre_compact"]
)
def test_prints_skip_line_when_hook_crashes(
    name: str, hub: Path, *, hook_python: str, elsewhere: Path, tmp_path: Path
) -> None:
    write_hub_json(hub, a_hub_document())

    completed = run_crashing(
        hub / HOOKS / f"{name}.py", python=hook_python, cwd=elsewhere, tmp_path=tmp_path
    )

    assert (completed.returncode, completed.stdout, completed.stderr) == (
        0,
        b"",
        f"[hub {name}] skipped: RuntimeError\n".encode(),
    )


# Owner decision (2026-09-29): with a hook root, $HUB_CONFIG may only tighten the guard's lists.
# A settings ``env`` entry (an app repo's ``settings.local.json`` too) can reach the hooks, so the
# lists are the union of the hook root's and $HUB_CONFIG's; every other value keeps Q-4's order.
ROOT_GUARD: dict[str, Any] = {
    "project": {"name": "demo", "default_branch": "trunk"},
    "guard": {
        "ask_before_edit": ["demo-api/docs/adr"],
        "deny_hosts": ["prod.example.com"],
        "deny_paths": ["@hub/private"],
    },
}
LISTS_CODE = (
    "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
    "print(json.dumps([list(cfg.ask_before_edit), list(cfg.deny_hosts), list(cfg.deny_paths),"
    " cfg.default_branch, cfg.project_name]))\n"
)


def guard_calls(hub: Path) -> list[dict[str, Any]]:
    """A deny path read, a deny host, an ask path edit, a guard file edit, a push to trunk."""
    adr = hub.parent / "demo-api" / "docs" / "adr" / "0001.md"
    edit = {"file_path": str(adr), "old_string": "a", "new_string": "b"}
    extension = {"file_path": str(hub / "plugin" / "demo" / "hooks" / "x.py"), "content": "x"}
    return [
        {"tool_name": "Read", "tool_input": {"file_path": str(hub / "private" / "a.md")}},
        bash_event("curl https://prod.example.com/x", hub),
        {"tool_name": "Edit", "tool_input": edit},
        {"tool_name": "Write", "tool_input": extension},
        bash_event("git push origin trunk", hub),
    ]


def test_keeps_hook_root_guard_lists_when_hub_config_permissive(
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]],
    hub: Path,
    *,
    hook_python: str,
    run_python: Callable[..., Any],
    elsewhere: Path,
) -> None:
    write_hub_json(hub, ROOT_GUARD)
    permissive = elsewhere / "permissive.json"
    permissive.write_text(
        json.dumps(
            {
                "project": {"name": "other", "default_branch": "release"},
                "guard": {"ask_before_edit": [], "deny_hosts": [], "deny_paths": []},
            }
        ),
        encoding="utf-8",
    )
    env = {"HUB_CONFIG": str(permissive)}

    lists = run_python(hook_python, LISTS_CODE, path=hub / HOOKS, cwd=elsewhere, env=env)
    verdicts = [verdict_of(run_hook("guard", event, env=env)) for event in guard_calls(hub)]
    release = verdict_of(run_hook("guard", bash_event("git push origin release", hub), env=env))

    # the lists stay the hook root's; the other values are $HUB_CONFIG's (Q-4)
    assert lists == [
        ["demo-api/docs/adr"],
        ["prod.example.com"],
        ["@hub/private"],
        "release",
        "other",
    ]
    # plugin/demo/hooks/ is the hook root's project, whatever $HUB_CONFIG names; the root's
    # branch stays protected beside $HUB_CONFIG's (AGH-46 Q-1: that file only tightens)
    assert [verdict and verdict[0] for verdict in verdicts] == [
        "deny",
        "deny",
        "ask",
        "ask",
        "deny",
    ]
    assert release is not None
    assert release[0] == "deny"


def test_adds_hub_config_guard_lists_when_stricter(
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]],
    hub: Path,
    *,
    hook_python: str,
    run_python: Callable[..., Any],
    elsewhere: Path,
) -> None:
    write_hub_json(hub, ROOT_GUARD)
    stricter = elsewhere / "stricter.json"
    stricter.write_text(
        json.dumps(
            {
                "project": {"name": "demo", "default_branch": "trunk"},
                "guard": {
                    "ask_before_edit": ["demo-api/src", "demo-api/docs/adr"],
                    "deny_hosts": ["evil.example.org"],
                    "deny_paths": ["@hub/drafts", "@hub/private"],
                },
            }
        ),
        encoding="utf-8",
    )
    env = {"HUB_CONFIG": str(stricter)}
    source = hub.parent / "demo-api" / "src" / "a.py"
    added = [
        {"tool_name": "Read", "tool_input": {"file_path": str(hub / "drafts" / "a.md")}},
        bash_event("curl https://evil.example.org/x", hub),
        {"tool_name": "Write", "tool_input": {"file_path": str(source), "content": "x"}},
    ]

    lists = run_python(hook_python, LISTS_CODE, path=hub / HOOKS, cwd=elsewhere, env=env)
    kept = [verdict_of(run_hook("guard", event, env=env)) for event in guard_calls(hub)]
    tightened = [verdict_of(run_hook("guard", event, env=env)) for event in added]
    without = [verdict_of(run_hook("guard", event)) for event in added]

    # the hook root's entries first, then $HUB_CONFIG's new ones, each once
    assert lists == [
        ["demo-api/docs/adr", "demo-api/src"],
        ["prod.example.com", "evil.example.org"],
        ["@hub/private", "@hub/drafts"],
        "trunk",
        "demo",
    ]
    assert [verdict and verdict[0] for verdict in kept] == ["deny", "deny", "ask", "ask", "deny"]
    assert [verdict and verdict[0] for verdict in tightened] == ["deny", "deny", "ask"]
    assert without == [None, None, None]


# AGH-45 Q-2: ``$HUB_CONFIG`` cannot turn on or widen ``guard.infra``: the mode and ``allow`` are
# the hook root's, while ``$HUB_CONFIG``'s ``prod_markers`` and problem are added. With no hook
# root (plugin cache), the found file's ``guard.infra`` is used as is.
INFRA_CODE = (
    "import dataclasses, json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
    "print(json.dumps(dataclasses.asdict(cfg.infra) if cfg.infra else None))\n"
)


def with_guard_infra(document: Mapping[str, Any], infra: object) -> dict[str, Any]:
    """``document`` whose ``guard`` also sets ``infra``."""
    return dict(document) | {"guard": dict(document.get("guard", {})) | {"infra": infra}}


def test_keeps_hook_root_infra_when_hub_config_names_other_file(
    hub: Path,
    cached_hooks: Path,
    *,
    hook_python: str,
    run_python: Callable[..., Any],
    elsewhere: Path,
) -> None:
    infra = builders.a_guard_infra()
    other = elsewhere / "other.json"
    env = {"HUB_CONFIG": str(other)}

    def infra_with(root: Mapping[str, Any] | None, config_infra: object) -> Any:
        """``cfg.infra`` with ``root`` as the hook root's hub.json (``None``: the cached hooks)."""
        other.write_text(json.dumps(with_guard_infra(ROOT_GUARD, config_infra)), encoding="utf-8")
        if root is None:
            return run_python(hook_python, INFRA_CODE, path=cached_hooks, cwd=elsewhere, env=env)
        write_hub_json(hub, root)
        return run_python(hook_python, INFRA_CODE, path=hub / HOOKS, cwd=elsewhere, env=env)

    off = infra_with(ROOT_GUARD, infra)
    widened = infra_with(
        with_guard_infra(ROOT_GUARD, infra),
        {"allow": ["--profile[= ]other\\b"], "prod_markers": ["\\bdemo-dev\\b"]},
    )
    unusable = infra_with(with_guard_infra(ROOT_GUARD, infra), [])
    cached = infra_with(None, infra)

    assert off is None
    assert widened == {
        "allow": infra["allow"],
        "prod_markers": [*infra["prod_markers"], "\\bdemo-dev\\b"],
        "problem": "",
    }
    assert unusable == {
        "allow": infra["allow"],
        "prod_markers": infra["prod_markers"],
        "problem": "guard.infra",
    }
    assert cached == infra | {"problem": ""}


def test_keeps_hook_root_infra_problem_when_hub_config_file_valid(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], elsewhere: Path
) -> None:
    infra = builders.a_guard_infra()
    other = elsewhere / "other.json"
    env = {"HUB_CONFIG": str(other)}
    write_hub_json(
        hub, with_guard_infra(ROOT_GUARD, {"allow": infra["allow"], "prod_markers": [7]})
    )

    def infra_with(config: Mapping[str, Any]) -> Any:
        """``cfg.infra`` with ``config`` as the ``$HUB_CONFIG`` file."""
        other.write_text(json.dumps(config), encoding="utf-8")
        return run_python(hook_python, INFRA_CODE, path=hub / HOOKS, cwd=elsewhere, env=env)

    with_valid = infra_with(with_guard_infra(ROOT_GUARD, infra))
    without = infra_with(ROOT_GUARD)

    # E15: the hook root's own problem survives a usable $HUB_CONFIG guard.infra
    assert with_valid == {
        "allow": infra["allow"],
        "prod_markers": infra["prod_markers"],
        "problem": "guard.infra.prod_markers[0]",
    }
    assert without == {
        "allow": infra["allow"],
        "prod_markers": [],
        "problem": "guard.infra.prod_markers[0]",
    }


PROTECTED_CODE = (
    "import json\nfrom hubhooks import Config, load_config\n"
    "print(json.dumps([list(load_config(None).protected_branches),"
    " list(Config().protected_branches)]))\n"
)


def test_lists_protected_branches_when_config_loaded(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], elsewhere: Path
) -> None:
    repos = [("demo-api", "release/2"), ("demo-web", "trunk"), ("demo-ops", "main"), ("x", None)]
    write_hub_json(
        hub,
        {
            "project": {"name": "demo", "default_branch": "trunk"},
            "repos": [
                {"dir": name} | ({"default_branch": branch} if branch else {})
                for name, branch in repos
            ],
        },
    )

    configured, bare = run_python(hook_python, PROTECTED_CODE, path=hub / HOOKS, cwd=elsewhere)

    # sorted, each once; main and master always
    assert configured == ["main", "master", "release/2", "trunk"]
    assert bare == ["main", "master"]


def test_protects_root_and_config_branches_when_hub_config_elsewhere(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], elsewhere: Path
) -> None:
    write_hub_json(
        hub,
        {
            "project": {"name": "demo", "default_branch": "trunk"},
            "repos": [
                {"dir": "demo-api", "default_branch": "master"},
                {"dir": "demo-web", "default_branch": "release/2"},
            ],
        },
    )
    config = elsewhere / "release.json"
    config.write_text(
        json.dumps({"project": {"name": "other", "default_branch": "release"}}), encoding="utf-8"
    )
    env = {"HUB_CONFIG": str(config)}

    configured, _ = run_python(
        hook_python, PROTECTED_CODE, path=hub / HOOKS, cwd=elsewhere, env=env
    )

    # demo-web's release/2 shows the root file's repo branches are kept, not only its project's
    assert configured == ["main", "master", "release", "release/2", "trunk"]


# AGH-65: one developer's identity. The prefix (and author, transport) comes from
# ``hub.local.json`` in the hub's main checkout, else ``hub.json``, else that checkout's git
# config; never from a ``hub.local.json`` beside a ``$HUB_CONFIG`` file (E1). Git runs only to
# build the guard's deny hint (E16), once, with a 2 s timeout. ``child_env`` hides the system and
# user git config, so a test's git identity is the ``GIT_CONFIG_GLOBAL`` file it writes.
TEAM_HUB_JSON: dict[str, Any] = {
    "project": {"name": "demo", "default_branch": "trunk"},
    "tracker": {"kind": "linear", "team": "DEM"},
}
LOCAL_FILE_NAME = "hub.local.json"
PREFIX_CODE = (
    "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
    "print(json.dumps(cfg.branch_prefix))\n"
)
IDENTITY_CODE = (
    "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
    "print(json.dumps([cfg.author_name, cfg.author_email, cfg.branch_prefix]))\n"
)
PUSH_MAIN_REASON = (
    "[hub guard] pushing to main is not allowed; open a PR from a {}dem-<N>-<desc> branch"
)


def write_local_json(folder: Path, document: Mapping[str, Any]) -> None:
    (folder / LOCAL_FILE_NAME).write_text(json.dumps(document), encoding="utf-8")


def git_identity(tmp_path: Path, body: bytes) -> dict[str, str]:
    """A git config whose ``[user]`` section holds ``body``, as ``GIT_CONFIG_GLOBAL``."""
    config = tmp_path / "gitconfig"
    config.write_bytes(b"[user]\n" + body)
    return {"GIT_CONFIG_GLOBAL": str(config)}


def traced_git(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """A ``git`` first on ``PATH``: logs ``<cwd>|<args>`` to the returned file, then runs git."""
    real = shutil.which("git")
    assert real is not None
    folder, log = tmp_path / "traced-bin", tmp_path / "git.log"
    folder.mkdir()
    shim = folder / "git"
    shim.write_text(
        f'#!/bin/sh\nprintf \'%s|%s\\n\' "$(pwd -P)" "$*" >> "{log}"\nexec "{real}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return {"PATH": f"{folder}{os.pathsep}{os.environ.get('PATH', os.defpath)}"}, log


def git_calls(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_reads_local_file_from_main_checkout_when_hooks_in_hub_worktree(
    hub: Path,
    *,
    hook_python: str,
    run_python: Callable[..., Any],
    rendered_tree: Callable[..., Path],
    demo_config: HubConfig,
    elsewhere: Path,
) -> None:
    worktree = rendered_tree(render_hub(demo_config), root=hub / ".claude" / "worktrees" / "t")
    for checkout in (hub, worktree):
        write_hub_json(checkout, TEAM_HUB_JSON)
    write_local_json(hub, {"project": {"branch_prefix": "me/"}})

    found = run_python(hook_python, PREFIX_CODE, path=worktree / HOOKS, cwd=elsewhere)

    assert found == "me/"


def test_never_reads_local_file_beside_hub_config_when_hub_config_set(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], tmp_path: Path
) -> None:
    write_hub_json(hub, {"project": {"name": "demo", "branch_prefix": "root/"}})
    folder = tmp_path / "conf"
    folder.mkdir()
    write_hub_json(folder, {"project": {"name": "demo", "branch_prefix": "cfg/"}})
    write_local_json(folder, {"project": {"branch_prefix": "evil/"}})
    env = {"HUB_CONFIG": str(folder / HUB_JSON_NAME)}

    without_root_local = run_python(hook_python, PREFIX_CODE, path=hub / HOOKS, cwd=folder, env=env)
    write_local_json(hub, {"project": {"branch_prefix": "me/"}})
    with_root_local = run_python(hook_python, PREFIX_CODE, path=hub / HOOKS, cwd=folder, env=env)

    # the loaded file's value (Q-4), then the hook root's local file; never the one beside it
    assert without_root_local == "cfg/"
    assert with_root_local == "me/"


GUARD_LISTS_CODE = (
    "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
    "print(json.dumps([list(cfg.ask_before_edit), list(cfg.deny_hosts), list(cfg.deny_paths),"
    " list(cfg.protected_branches), list(cfg.repo_dirs)]))\n"
)


def test_keeps_guard_lists_when_local_file_holds_guard_keys(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], elsewhere: Path
) -> None:
    write_hub_json(hub, ROOT_GUARD | {"repos": [{"dir": "demo-api"}]})
    without = run_python(hook_python, GUARD_LISTS_CODE, path=hub / HOOKS, cwd=elsewhere)
    write_local_json(
        hub,
        {
            "guard": {"ask_before_edit": [], "deny_hosts": [], "deny_paths": []},
            "repos": [{"dir": "other", "default_branch": "y"}],
            "project": {"default_branch": "x"},
        },
    )

    with_file = run_python(hook_python, GUARD_LISTS_CODE, path=hub / HOOKS, cwd=elsewhere)

    assert without == [
        ["demo-api/docs/adr"],
        ["prod.example.com"],
        ["@hub/private"],
        ["main", "master", "trunk"],
        ["demo-api"],
    ]
    assert with_file == without


def test_runs_no_git_when_guard_allows_on_team_hub(
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]], hub: Path, tmp_path: Path
) -> None:
    write_hub_json(hub, TEAM_HUB_JSON)
    traced, log = traced_git(tmp_path)
    env = traced | git_identity(tmp_path, b"\temail = jane@example.com\n")

    verdicts = [
        verdict_of(run_hook("guard", bash_event(command, hub), env=env))
        for command in ("echo hi", "git push origin me/dem-1-x")
    ]

    assert verdicts == [None, None]
    assert git_calls(log) == []


def test_reads_git_email_in_hub_when_team_hub_denies(
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]], hub: Path, tmp_path: Path
) -> None:
    write_hub_json(hub, TEAM_HUB_JSON)
    traced, log = traced_git(tmp_path)
    env = traced | git_identity(tmp_path, b"\tname = Jane Roe\n\temail = jane@example.com\n")

    verdict = verdict_of(run_hook("guard", bash_event("git push origin main", hub), env=env))

    assert verdict == ("deny", PUSH_MAIN_REASON.format("jane/"))
    assert git_calls(log) == [f"{hub}|config --get user.email"]


# Git's raw output counts as the CLI counts it: one trailing newline dropped, then the model's
# shape, else no value. Bytes that are not UTF-8 are no value either; the guard still answers.
GIT_SHAPES = [
    pytest.param(
        b'\tname = Jane Roe\n\temail = "jane@example.com "\n',
        ["Jane Roe", "", ""],
        "",
        id="email-trailing-space",
    ),
    pytest.param(
        b"\tname = Jane \xff Roe\n\temail = jane@example.com\n",
        ["", "jane@example.com", "jane/"],
        "jane/",
        id="name-not-utf8",
    ),
    pytest.param(
        b"\tname = Jane Roe\n\temail = jan\xffe@example.com\n",
        ["Jane Roe", "", ""],
        "",
        id="email-not-utf8",
    ),
]


@pytest.mark.parametrize(("body", "identity", "prefix"), GIT_SHAPES)
def test_drops_git_value_when_shape_or_encoding_invalid(
    body: bytes,
    identity: list[str],
    prefix: str,
    *,
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]],
    hub: Path,
    hook_python: str,
    run_python: Callable[..., Any],
    elsewhere: Path,
    tmp_path: Path,
) -> None:
    write_hub_json(hub, TEAM_HUB_JSON)
    env = git_identity(tmp_path, body)

    found = run_python(hook_python, IDENTITY_CODE, path=hub / HOOKS, cwd=elsewhere, env=env)
    push = run_hook("guard", bash_event("git push origin main", hub), env=env)

    assert found == identity
    assert verdict_of(push) == ("deny", PUSH_MAIN_REASON.format(prefix))
    assert push.stderr == b""


def run_git(*args: str) -> None:
    real = shutil.which("git")
    assert real is not None
    subprocess.run([real, *args], check=True, capture_output=True)  # noqa: S603 - fixed arguments


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_COMMON_DIR"])
def test_reads_git_email_of_identity_home_when_git_location_exported(
    variable: str,
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]],
    *,
    hub: Path,
    tmp_path: Path,
) -> None:
    write_hub_json(hub, TEAM_HUB_JSON)
    other = tmp_path / "other-repo"
    # GIT_COMMON_DIR moves only a repo's shared state, so the hub is a repo in that row.
    for repo in [other, hub] if variable == "GIT_COMMON_DIR" else [other]:
        run_git("init", "-q", str(repo))
    run_git("-C", str(other), "config", "user.email", "evil@example.com")
    env = git_identity(tmp_path, b"\temail = jane@example.com\n") | {variable: str(other / ".git")}

    verdict = verdict_of(run_hook("guard", bash_event("git push origin main", hub), env=env))

    assert verdict == ("deny", PUSH_MAIN_REASON.format("jane/"))


def test_denies_with_bare_hint_when_git_missing(
    run_hook: Callable[..., subprocess.CompletedProcess[bytes]], hub: Path, tmp_path: Path
) -> None:
    write_hub_json(hub, TEAM_HUB_JSON)
    no_tools = tmp_path / "no-tools"
    no_tools.mkdir()
    env = git_identity(tmp_path, b"\temail = jane@example.com\n") | {"PATH": str(no_tools)}

    push = run_hook("guard", bash_event("git push origin main", hub), env=env)

    assert verdict_of(push) == ("deny", PUSH_MAIN_REASON.format(""))
    assert push.stderr == b""


# The identity read's subprocess.run records its keyword arguments, then times out.
TIMEOUT_CODE = """\
import json, subprocess
import hubhooks
calls = []
def timing_out(args, **kwargs):
    calls.append([args, kwargs.get("timeout")])
    raise subprocess.TimeoutExpired("git", 2)
hubhooks.subprocess.run = timing_out
cfg = hubhooks.load_config(None)
print(json.dumps([cfg.branch_prefix, calls]))
"""


def test_gives_no_prefix_when_identity_git_read_times_out(
    hub: Path,
    *,
    hook_python: str,
    run_python: Callable[..., Any],
    elsewhere: Path,
    tmp_path: Path,
) -> None:
    write_hub_json(hub, TEAM_HUB_JSON)
    env = git_identity(tmp_path, b"\temail = jane@example.com\n")

    prefix, calls = run_python(hook_python, TIMEOUT_CODE, path=hub / HOOKS, cwd=elsewhere, env=env)

    assert prefix == ""
    assert calls == [[["git", "config", "--get", "user.email"], 2]]


# Plugin-cache mode (no hook root): the identity home is the walked hub; with $HUB_CONFIG there is
# none, so neither the local file beside that file nor git is read (E1).
@pytest.mark.parametrize(("hub_prefix", "expected"), [("cfg/", "cfg/"), (None, "")])
def test_reads_no_identity_when_cached_hooks_use_hub_config(
    hub_prefix: str | None,
    expected: str,
    cached_hooks: Path,
    *,
    hook_python: str,
    run_python: Callable[..., Any],
    tmp_path: Path,
) -> None:
    folder = tmp_path / "conf"
    folder.mkdir()
    project = {"name": "demo"} | ({"branch_prefix": hub_prefix} if hub_prefix else {})
    write_hub_json(folder, {"project": project})
    write_local_json(folder, {"project": {"branch_prefix": "evil/"}})
    traced, log = traced_git(tmp_path)
    env = (
        traced
        | git_identity(tmp_path, b"\temail = jane@example.com\n")
        | {"HUB_CONFIG": str(folder / HUB_JSON_NAME)}
    )

    found = run_python(hook_python, PREFIX_CODE, path=cached_hooks, cwd=folder, env=env)

    assert found == expected
    assert git_calls(log) == []


def test_reads_walked_hub_local_file_when_cached_hooks_find_hub(
    cached_hooks: Path,
    sibling_workspace: Path,
    *,
    hook_python: str,
    run_python: Callable[..., Any],
) -> None:
    hub = sibling_workspace / "other-hub"
    write_local_json(hub, {"project": {"branch_prefix": "me/"}})

    found = run_python(hook_python, PREFIX_CODE, path=cached_hooks, cwd=hub / "brain")

    assert found == "me/"
