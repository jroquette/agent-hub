"""The hub CI's ``Repos beside the hub`` step lets ``hub doctor``'s repo rules run (AGH-699 A-13).

Without the repos beside the hub, ``hub doctor`` reports each one as not checked out (info) and
exits 0, so a repo that copies a brain line passes CI. The case runs the step's ``run: |`` block of
the ``ci.yml`` that ``hub init`` wrote into the two-repo demo hub, on ``bash`` with Actions'
default flags, the repos' GitHub URLs sent to local repositories by a global git config under the
case's own ``HOME``; then the doctor ``make check`` runs fails on ``brain.leak``.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from typer.testing import Result

type DoctorRunner = Callable[..., Result]

TIMEOUT = 60
STEP = "      - name: Repos beside the hub\n"
RUN_HEAD = "        run: |\n"
BLOCK_INDENT = " " * 10
BASH_FLAGS = ("--noprofile", "--norc", "-eo", "pipefail")
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
BRAIN_LINE = "A synthetic brain line, long enough for brain.leak to compare it."
LEAK = (
    "error brain.leak ../demo-api/LEAK.md:1: line also in the brain at brain/note.md:3"
    " Fix: reword or remove the line here, or reword the brain note if it quotes this file"
)
NOT_CHECKED_OUT = "is not checked out next to the hub"


def repos_block(ci: str) -> str:
    """The step's ``run: |`` block as bash reads it: its lines at the block's indent, dedented."""
    step = ci[ci.index(STEP) :]
    body = step[step.index(RUN_HEAD) + len(RUN_HEAD) :]
    lines: list[str] = []
    for line in body.splitlines(keepends=True):
        if line.strip() and not line.startswith(BLOCK_INDENT):
            break
        lines.append(line.removeprefix(BLOCK_INDENT))
    assert lines, ci
    return "".join(lines)


def real(name: str) -> str:
    found = shutil.which(name)
    assert found is not None, f"the repos step runs {name}: install it"
    return os.path.realpath(found)


def origin(root: Path, files: dict[str, str]) -> Path:
    """A repository at ``root`` with ``files`` committed on ``main``."""
    root.mkdir(parents=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    env = {
        "PATH": os.pathsep.join(SYSTEM_PATH),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Jane Doe",
        "GIT_AUTHOR_EMAIL": "jane@example.com",
        "GIT_COMMITTER_NAME": "Jane Doe",
        "GIT_COMMITTER_EMAIL": "jane@example.com",
    }
    for arguments in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "init")):
        subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
            [real("git"), *arguments], cwd=root, env=env, check=True, capture_output=True
        )
    return root


def run_repos_step(hub: Path, home: Path) -> subprocess.CompletedProcess[str]:
    """Run the hub's own rendered repos step in the hub, as the CI job does, without a token."""
    bin_dir = home.parent / "ci-bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(os.path.realpath(sys.executable))
    ci = (hub / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return subprocess.run(  # noqa: S603 - absolute bash, the rendered block, no shell
        [real("bash"), *BASH_FLAGS, "-c", repos_block(ci)],
        capture_output=True,
        text=True,
        check=False,
        cwd=hub,
        env={
            "PATH": os.pathsep.join((str(bin_dir), *SYSTEM_PATH)),
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_CEILING_DIRECTORIES": str(hub.parent),
        },
        timeout=TIMEOUT,
    )


def test_fails_on_brain_leak_when_ci_repos_step_ran(
    demo_two_repo_hub: Path, run_doctor: DoctorRunner, tmp_path: Path
) -> None:
    hub = demo_two_repo_hub
    (hub / "brain" / "note.md").write_text(f"# Note\n\n{BRAIN_LINE}\n", encoding="utf-8")
    home = tmp_path / "ci-home"
    home.mkdir()
    origins = {
        "acme/demo-api": {"AGENTS.md": "# demo-api\n", "LEAK.md": f"{BRAIN_LINE}\n"},
        "acme/demo-web": {"AGENTS.md": "# demo-web\n"},
    }
    with (home / ".gitconfig").open("w", encoding="utf-8") as config:
        for github, files in origins.items():
            path = origin(tmp_path / "origins" / github, files)
            config.write(f'[url "{path}"]\n\tinsteadOf = https://github.com/{github}.git\n')

    before = run_doctor(hub, "--only", "brain.leak")
    completed = run_repos_step(hub, home)
    after = run_doctor(hub, "--only", "brain.leak")

    # Before: no repo beside the hub, so brain.leak cannot run and doctor passes.
    assert before.exit_code == 0, before.output
    assert before.output.count(NOT_CHECKED_OUT) == 2
    assert completed.returncode == 0, completed.stderr
    assert sorted(path.name for path in tmp_path.iterdir() if path.name.startswith("demo-")) == [
        "demo-api",
        "demo-web",
    ]
    assert after.exit_code == 1, after.output
    assert LEAK in after.output.splitlines()
    assert NOT_CHECKED_OUT not in after.output
