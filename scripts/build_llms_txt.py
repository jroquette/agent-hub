"""Build ``llms.txt`` and ``llms-full.txt``, the docs for AI agents (https://llmstxt.org).

``llms.txt`` is an index: what agent-hub is, then one link per doc with its title. ``llms-full.txt``
is the text of the docs a user of agent-hub needs (``USER_DOCS``), one after the other, so an agent
setting up a hub reads one file. Titles come from each doc's first ``# `` heading.

Run ``make llms-txt`` (``python -m scripts.build_llms_txt``) after changing a listed doc and commit
both files; ``test_build_llms_txt.py`` (in ``make check-fast``) fails until you do.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = "llms.txt"
FULL_FILE = "llms-full.txt"
RAW_BASE = "https://raw.githubusercontent.com/jroquette/agent-hub/main/"

SUMMARY = (
    "A home base for AI coding agents, for developers who run Claude Code across several repos. "
    "One command gives each project shared rules, memory and workflow, pinned to a version and "
    "kept up to date."
)
INSTALL = "git+https://github.com/jroquette/agent-hub@vX.Y.Z#subdirectory=packages/agent-hub"
INTRO = f"""\
agent-hub is a Python CLI, `hub`, installed from a git tag with uv (no PyPI package):
`uvx --from '{INSTALL}' hub --help`.
`hub init` creates a hub: a repo next to the project's code repos that holds `hub.json` (the
project config), a brain (curated project memory), the hub-workflow Claude Code plugin (skills,
agents and guard hooks) and per-task worktrees. `hub sync` keeps a hub up to date with its pinned
release, and `hub web` serves a local control plane of the agents' sessions.

If you are an agent setting up a hub for a project, read the usage guide first. The repo's own
AGENTS.md is for agents changing agent-hub itself, not for users of it.
License: Apache-2.0."""

# (section, [paths]) in the order llms.txt lists them; USER_DOCS also go into llms-full.txt.
USER_DOCS = (
    "docs/USING.md",
    "README.md",
    "docs/design/project-config.md",
    "docs/design/developer-identity.md",
    "docs/design/hub-setup.md",
    "docs/design/hub-start.md",
    "docs/design/hub-sync.md",
    "docs/design/hub-adopt.md",
    "docs/design/hub-doctor.md",
    "docs/design/worktree-environment.md",
    "docs/design/memory-layers.md",
    "SECURITY.md",
)
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Use agent-hub", USER_DOCS),
    ("Product and design", ("docs/SPEC.md", "CHANGELOG.md", "docs/design/README.md")),
    (
        "Contribute to agent-hub",
        (
            "AGENTS.md",
            "docs/ARCHITECTURE.md",
            "docs/CONVENTIONS.md",
            "docs/TESTING.md",
            "docs/CONTRIBUTING.md",
            "docs/API.md",
        ),
    ),
)
ADR_DIR = "docs/adr"


# The README opens with an HTML banner instead of a ``# `` heading.
TITLES = {"README.md": "agent-hub README: Quick Start, daily workflow, recipes and configuration"}


def title_of(text: str, path: str) -> str:
    """The first ``# `` heading of a markdown doc; the file name when it has none."""
    if path in TITLES:
        return TITLES[path]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path


def build(root: Path) -> dict[str, str]:
    """The two files' contents, by file name, built from the docs under ``root``."""
    texts: dict[str, str] = {}
    adrs = sorted(path.relative_to(root).as_posix() for path in (root / ADR_DIR).glob("*.md"))
    for path in [*(p for _, paths in SECTIONS for p in paths), *adrs]:
        texts[path] = (root / path).read_text(encoding="utf-8")

    index = [f"# agent-hub\n\n> {SUMMARY}\n\n{INTRO}\n"]
    sections = [*SECTIONS, ("Optional", tuple(adrs))]
    for section, paths in sections:
        index.append(f"\n## {section}\n\n")
        index.extend(f"- [{title_of(texts[p], p)}]({RAW_BASE}{p}): `{p}`\n" for p in paths)

    full = [f"# agent-hub\n\n> {SUMMARY}\n\n{INTRO}\n"]
    for path in USER_DOCS:
        full.append(f"\n---\n\nSource: `{path}` ({RAW_BASE}{path})\n\n{texts[path].rstrip()}\n")
    return {INDEX_FILE: "".join(index), FULL_FILE: "".join(full)}


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    """Write both files under ``root``; ``argv`` takes no arguments."""
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("usage: python -m scripts.build_llms_txt", file=sys.stderr)
        return 2
    for name, text in build(root).items():
        # newline="\n": the same bytes on every platform, so git sees no change.
        (root / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
