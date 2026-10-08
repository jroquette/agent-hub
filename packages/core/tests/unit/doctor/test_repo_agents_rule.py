"""``repos.agents``: each listed repo checkout has an ``AGENTS.md`` at its root.

Only the checkout's listing is read: the exact root path ``AGENTS.md``, a file or a link (not
followed), empty or not. A gitignored or deleted file is not listed, so it does not count; an
unreadable one is listed, so it does (plan E5). A missing or unlistable checkout is the runner's.
Every text here is synthetic (AGENTS.md rule 4).
"""

from collections.abc import Callable

import pytest

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.links_rule import LINKS_DEAD
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.repo_agents_rule import REPOS_AGENTS
from agent_hub.core.doctor.run_rules import Selection, run_rules
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document, a_second_repo

type SnapshotFactory = Callable[..., DoctorSnapshot]

MESSAGE = "no AGENTS.md at the repo root (hub agent loads none for it)"


def a_config(*repos: tuple[str, str, str]) -> HubConfig:
    """``a_hub_document`` whose repos are ``(dir, check_fast, check)``, in that order.

    The guard is emptied: its path names ``demo-api``, which these repos replace.
    """
    document = a_hub_document()
    document["guard"] = {}
    document["repos"] = [
        a_second_repo() | {"dir": repo_dir, "check_fast": fast, "check": full}
        for repo_dir, fast, full in repos
    ]
    return HubConfig.model_validate(document)


def found(snapshot: DoctorSnapshot) -> list[Finding]:
    return list(REPOS_AGENTS.check(snapshot))


def missing_in(repo_dir: str, *, fast: str, full: str) -> Finding:
    return Finding(
        rule="repos.agents",
        severity=Severity.WARNING,
        path=f"../{repo_dir}",
        line=None,
        message=MESSAGE,
        fix=f"copy docs/app-repo-AGENTS.md to ../{repo_dir}/AGENTS.md and fill it in;"
        f" check_fast: {fast}, check: {full}",
    )


DEMO_API_MISSING = missing_in("demo-api", fast="make check-fast", full="make check")


def test_declares_design_fields_when_repo_agents_rule_read() -> None:
    assert REPOS_AGENTS.id == "repos.agents"
    assert REPOS_AGENTS.severity is Severity.WARNING
    assert REPOS_AGENTS.reads == frozenset({Read.REPOS})
    assert REPOS_AGENTS.module is None


def test_warns_missing_repo_agents_when_listing_lacks_file(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        config=a_config(
            ("api", "make check-fast", "make check"), ("web", "npm test", "npm run ci")
        ),
        repos={"api": {"README.md": b"# api\n"}, "web": {"AGENTS.md": b"# web\n"}},
    )

    assert found(snapshot) == [
        Finding(
            rule="repos.agents",
            severity=Severity.WARNING,
            path="../api",
            line=None,
            message="no AGENTS.md at the repo root (hub agent loads none for it)",
            fix="copy docs/app-repo-AGENTS.md to ../api/AGENTS.md and fill it in;"
            " check_fast: make check-fast, check: make check",
        )
    ]


def test_names_each_repo_checks_when_repo_agents_missing_in_two(
    snapshot_of: SnapshotFactory,
) -> None:
    # In hub.json order; a lookup that swapped the repos would swap the commands.
    snapshot = snapshot_of(
        config=a_config(
            ("web", "npm test", "npm run ci"), ("api", "make check-fast", "make check")
        ),
        repos={"web": {"README.md": b"# web\n"}, "api": {"README.md": b"# api\n"}},
    )

    assert found(snapshot) == [
        missing_in("web", fast="npm test", full="npm run ci"),
        missing_in("api", fast="make check-fast", full="make check"),
    ]


@pytest.mark.parametrize(
    ("files", "links"),
    [
        ({"AGENTS.md": b"# x\n"}, {}),
        ({}, {"AGENTS.md": "docs/AGENTS.md"}),
        ({"AGENTS.md": b""}, {}),
    ],
    ids=["regular", "link", "empty"],
)
def test_passes_repo_agents_listing_when_root_file_present(
    snapshot_of: SnapshotFactory, files: dict[str, bytes], links: dict[str, str]
) -> None:
    snapshot = snapshot_of(repos={"demo-api": files}, repo_links={"demo-api": links})

    assert found(snapshot) == []


@pytest.mark.parametrize(
    "path", ["CLAUDE.md", "docs/AGENTS.md", "agents.md"], ids=["claude", "nested", "lowercase"]
)
def test_warns_repo_agents_listing_when_only_other_name(
    snapshot_of: SnapshotFactory, path: str
) -> None:
    snapshot = snapshot_of(repos={"demo-api": {path: b"# x\n"}})

    assert found(snapshot) == [DEMO_API_MISSING]


def test_warns_repo_agents_listing_when_file_not_listed(snapshot_of: SnapshotFactory) -> None:
    # Present but not listed: gitignored, or tracked and deleted from the work tree (plan E5).
    snapshot = snapshot_of(
        repos={"demo-api": {"AGENTS.md": b"x", "README.md": b"x"}},
        repo_listed={"demo-api": ("README.md",)},
    )

    assert found(snapshot) == [DEMO_API_MISSING]


@pytest.mark.parametrize(
    ("files", "problems"),
    [(None, {}), ({}, {"demo-api": "could not list the files: x"})],
    ids=["missing", "unlistable"],
)
def test_skips_repo_agents_checkout_when_missing_or_unlistable(
    snapshot_of: SnapshotFactory, files: dict[str, bytes] | None, problems: dict[str, str]
) -> None:
    snapshot = snapshot_of(repos={"demo-api": files}, repo_problems=problems)

    assert found(snapshot) == []


def test_skips_repo_agents_when_config_failed(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        config=ConfigFailure(problems=(), pin=None), repos={"demo-api": {"README.md": b"x"}}
    )

    assert found(snapshot) == []


@pytest.mark.parametrize(
    ("rules", "reporter"),
    [
        ((*REGISTRY, REPOS_AGENTS), "brain.leak"),
        ((LINKS_DEAD, REPOS_AGENTS), "links.dead"),
        ((REPOS_AGENTS,), "repos.agents"),
    ],
    ids=["all", "links_dead", "only"],
)
def test_reports_checkout_on_first_repo_reader_when_repo_agents_selected(
    snapshot_of: SnapshotFactory, rules: tuple[Rule, ...], reporter: str
) -> None:
    snapshot = snapshot_of(repos={"demo-api": None})
    selection = Selection(rules=rules, notes=(), severities={})

    at_checkout = [
        (finding.rule, finding.severity)
        for finding in run_rules(selection, snapshot)
        if finding.path == "../demo-api"
    ]

    assert at_checkout == [(reporter, Severity.INFO)]


@pytest.mark.parametrize(
    ("check", "shown"),
    [
        ("x" * 100, "x" * 79 + "…"),
        ("make check x", "make check\\u2028x"),
        ("make check\x85x", "make check\\x85x"),
    ],
    ids=["long", "u2028", "nel"],
)
def test_cuts_echo_when_repo_agents_check_long_or_not_printable(
    snapshot_of: SnapshotFactory, check: str, shown: str
) -> None:
    snapshot = snapshot_of(
        config=a_config(("api", "make check-fast", check)),
        repos={"api": {"README.md": b"# api\n"}},
    )

    fixes = [finding.fix for finding in found(snapshot)]

    assert len(fixes) == 1
    assert fixes[0].endswith("check: " + shown)
    assert fixes[0].splitlines() == [fixes[0]]
    selection = Selection(rules=(REPOS_AGENTS,), notes=(), severities={})
    messages = [finding.message for finding in run_rules(selection, snapshot)]
    assert not any(message.startswith("rule crashed") for message in messages)
