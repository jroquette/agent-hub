import re
from typing import Any

import pytest

from agent_hub.core.hub_config.conventions import MAX_PATTERN_CHARS
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.platform_repository import (
    DEFAULT_PLATFORM_REPOSITORY,
    PLATFORM_REPOSITORY_FORM,
    PLATFORM_REPOSITORY_PATTERN,
)
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.runner.title_pattern import TitleParts, render_title
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_second_repo,
    a_two_team_document,
)
from agent_hub.core.testing.platform_repository_cases import CUSTOM_REPOSITORY
from agent_hub.generator.placeholders import PLATFORM_REPOSITORY, substitution_mapping

# AC-3.9: the Rendered values of project-config.md, the platform repository (erratum E3), the
# derived module includes (erratum E2), contract-sync's two repo dirs (AGH-17 G8) and the module
# files AGENTS.md names (AGH-17 2.11), AGENTS.md's two branch mentions (AGH-46), and its commit
# author and prefix note (AGH-65). author_name, check_fast, check and platform.version are read at
# run time or quoted per format, never placeholders; author_email is per developer and no template
# names it (AGH-65). The team mentions of AGENTS.md and the plugin name every tracker team (AGH-56).
# The branch rule, kickoff's branch and the Conventions block show the conventions (AGH-57).
# The runtime readers check platform.repository against core's pattern and name its form (AGH-49).
RENDERED_KEYS = {
    "project_name",
    "project_hub_repo",
    "project_branch_prefix",
    "project_default_branch",
    "tracker_team",
    "tracker_team_mention",
    "tracker_team_rule",
    "tracker_team_key",
    "tracker_team_key_named",
    "tracker_team_key_assigned",
    "repo_dirs",
    "repo_githubs",
    "guard_deny_hosts",
    "platform_repository",
    "platform_repository_pattern",
    "platform_repository_form",
    "module_includes",
    "module_files",
    "module_seeded_files",
    "contract_sync_source",
    "contract_sync_target",
    "worktree_base",
    "protected_branches",
    "commit_author",
    "prefix_note",
    "identity_email",
    "branch_rule",
    "kickoff_branch",
    "conventions_section",
}

# Rule 1's branch as the template held it before AGH-57, with the demo's one team.
DEMO_BRANCH_RULE = (
    "Branch: `jdoe/<team>-<n>-<desc>`, where `<team>` is the\n   tracker team DEM in lowercase."
)


def config_with(**sections: Any) -> HubConfig:
    document = a_hub_document()
    document.update(sections)
    return HubConfig.model_validate(document)


def test_lists_rendered_values_when_mapping_built(
    demo_config: HubConfig, variant_config: HubConfig
) -> None:
    for config in (demo_config, variant_config):
        assert set(substitution_mapping(config)) == RENDERED_KEYS


def test_takes_values_from_model_when_demo_mapped(demo_config: HubConfig) -> None:
    mapping = substitution_mapping(demo_config)

    # default_branch is absent from the document: the model's default proves the source.
    assert mapping == {
        "project_name": "demo",
        "project_hub_repo": "acme/demo-hub",
        "project_branch_prefix": "jdoe/",
        "project_default_branch": "main",
        "tracker_team": "DEM",
        "tracker_team_mention": " team DEM",
        "tracker_team_rule": " the\n   tracker team DEM",
        "tracker_team_key": "`tracker.team` in `hub.json`",
        "tracker_team_key_named": "team `tracker.team` in `hub.json`",
        "tracker_team_key_assigned": "team = `tracker.team` in `hub.json`",
        "repo_dirs": "demo-api",
        "repo_githubs": "acme/demo-api",
        "guard_deny_hosts": "",
        "platform_repository": PLATFORM_REPOSITORY,
        "platform_repository_pattern": PLATFORM_REPOSITORY_PATTERN,
        "platform_repository_form": PLATFORM_REPOSITORY_FORM,
        "module_includes": "include mk/bench.mk\ninclude mk/cloud.mk\n",
        "module_files": (
            ",\n  and each selected module's files (`mk/<id>.mk`, `scripts/cloud-setup.sh`)"
        ),
        "module_seeded_files": "",
        "contract_sync_source": "",
        "contract_sync_target": "",
        "worktree_base": "`origin/main`",
        "protected_branches": "`main`",
        "commit_author": "the user (`hub.json` → `project.author_name`, `project.author_email`)",
        "prefix_note": "",
        "identity_email": "`hub.json` → `project.author_email`",
        "branch_rule": DEMO_BRANCH_RULE,
        "kickoff_branch": "`jdoe/<team>-<n>-<desc>`",
        "conventions_section": "",
    }


def test_joins_repos_in_config_order_when_variant_mapped(variant_config: HubConfig) -> None:
    mapping = substitution_mapping(variant_config)

    assert mapping["repo_dirs"] == "demo-api, demo-web"
    assert mapping["repo_githubs"] == "acme/demo-api, acme/demo-web"
    assert mapping["project_default_branch"] == "trunk"


def test_mentions_project_branch_when_no_repo_sets_one(variant_config: HubConfig) -> None:
    mapping = substitution_mapping(variant_config)

    # Today's AGENTS.md bytes: one project branch for every repo.
    assert (mapping["worktree_base"], mapping["protected_branches"]) == (
        "`origin/trunk`",
        "`trunk`",
    )


def test_mentions_each_repo_branch_when_one_sets_it() -> None:
    document = a_hub_document()
    document["repos"][0]["default_branch"] = "master"
    document["repos"].append(a_second_repo())

    mapping = substitution_mapping(HubConfig.model_validate(document))

    assert mapping["worktree_base"] == (
        "`origin/<the repo's default branch>` (demo-api: `master`, demo-web: `main`)"
    )
    assert mapping["protected_branches"] == "`main` or `master`"


def test_lists_protected_branches_once_when_branches_repeat() -> None:
    document = a_hub_document()
    document["project"]["default_branch"] = "trunk"
    document["repos"][0]["default_branch"] = "trunk"
    document["repos"].append({**a_second_repo(), "default_branch": "release/2"})

    mapping = substitution_mapping(HubConfig.model_validate(document))

    assert mapping["protected_branches"] == "`main`, `master`, `release/2` or `trunk`"
    assert mapping["worktree_base"] == (
        "`origin/<the repo's default branch>` (demo-api: `trunk`, demo-web: `release/2`)"
    )


def test_joins_repos_in_config_order_when_order_reversed() -> None:
    document = a_hub_document()
    document["repos"].insert(
        0,
        {"dir": "zeta", "github": "acme/zeta", "check_fast": "make f", "check": "make c"},
    )

    mapping = substitution_mapping(HubConfig.model_validate(document))

    assert mapping["repo_dirs"] == "zeta, demo-api"
    assert mapping["repo_githubs"] == "acme/zeta, acme/demo-api"


@pytest.mark.parametrize(
    ("hosts", "expected"),
    [
        (["a.example.com", "b.example.com"], "a.example.com, b.example.com"),
        ([], ""),
    ],
)
def test_joins_deny_hosts_when_hosts_listed(hosts: list[str], expected: str) -> None:
    config = config_with(guard={"deny_hosts": hosts})

    assert substitution_mapping(config)["guard_deny_hosts"] == expected


@pytest.mark.parametrize(
    ("modules", "expected"),
    [
        ({"cloud": {}, "bench": {}}, "include mk/bench.mk\ninclude mk/cloud.mk\n"),
        (
            {"contract-sync": {"source": "demo-api", "target": "demo-web"}},
            "include mk/contract-sync.mk\n",
        ),
        ({}, ""),
    ],
)
def test_lists_sorted_includes_when_modules_selected(
    modules: dict[str, dict[str, object]], expected: str
) -> None:
    config = config_with(modules=modules, repos=[*a_hub_document()["repos"], a_second_repo()])

    assert substitution_mapping(config)["module_includes"] == expected


def test_names_contract_sync_repos_when_module_selected(all_modules_config: HubConfig) -> None:
    mapping = substitution_mapping(all_modules_config)

    assert (mapping["contract_sync_source"], mapping["contract_sync_target"]) == (
        "demo-api",
        "demo-web",
    )


def test_names_no_contract_sync_repo_when_module_unselected(variant_config: HubConfig) -> None:
    mapping = substitution_mapping(variant_config)

    assert (mapping["contract_sync_source"], mapping["contract_sync_target"]) == ("", "")


def test_matches_core_release_command_when_source_formatted() -> None:
    expected = f"uvx --from {PLATFORM_REPOSITORY}@v1.2.3#subdirectory=packages/agent-hub hub"

    assert PINNED_RELEASE_COMMAND.format(version="1.2.3") == expected


def test_takes_platform_values_from_core_when_mapped(demo_config: HubConfig) -> None:
    mapping = substitution_mapping(demo_config)

    # The same objects, not equal copies: core holds the one default, pattern and form (AGH-49).
    assert PLATFORM_REPOSITORY is DEFAULT_PLATFORM_REPOSITORY
    assert mapping["platform_repository_pattern"] is PLATFORM_REPOSITORY_PATTERN
    assert mapping["platform_repository_form"] is PLATFORM_REPOSITORY_FORM


def test_renders_no_run_time_value_when_variant_mapped(variant_config: HubConfig) -> None:
    document = variant_config.model_dump(mode="json", by_alias=True, exclude_none=True)
    document["platform"]["repository"] = CUSTOM_REPOSITORY
    custom = HubConfig.model_validate(document)

    # platform.repository is read at run time by the hub's readers, never rendered (AGH-49).
    for config in (variant_config, custom):
        values = substitution_mapping(config).values()
        for never_rendered in (
            "sentinel-fast-q7",
            "sentinel-full-q7",
            "9.8.7",
            "Sentinel Author Q7",
            CUSTOM_REPOSITORY,
            "git.acme.test",
        ):
            assert not any(never_rendered in value for value in values)


def test_renders_prefix_placeholder_when_hub_sets_no_prefix() -> None:
    document = a_hub_document()
    del document["project"]["branch_prefix"]

    mapping = substitution_mapping(HubConfig.model_validate(document))

    assert mapping["project_branch_prefix"] == "<prefix>"


# AGH-65 (plan E14): a team hub's AGENTS.md names the developer, not hub.json.
USER_AUTHOR = "the user (`hub.json` → `project.author_name`, `project.author_email`)"
DEVELOPER_AUTHOR = (
    "the developer running the session (`hub.local.json` → `project.author_name`,\n"
    "   `project.author_email`, else their `git config user.name`, `user.email`)"
)
PREFIX_NOTE = (
    "\n   `<prefix>` is `hub.local.json` → `project.branch_prefix`, else the local part of your"
    " author email plus `/`."
)


def mapping_without(*keys: str) -> dict[str, str]:
    document = a_hub_document()
    for key in keys:
        del document["project"][key]
    return substitution_mapping(HubConfig.model_validate(document))


@pytest.mark.parametrize(
    "absent",
    [("author_name", "author_email"), ("author_email",), ("author_name",)],
    ids=["both", "email", "name"],
)
def test_names_developer_when_hub_sets_no_author(absent: tuple[str, ...]) -> None:
    assert mapping_without(*absent)["commit_author"] == DEVELOPER_AUTHOR


def test_names_developer_email_when_hub_sets_no_email() -> None:
    assert mapping_without("author_email")["identity_email"] == (
        "your author email (`hub.local.json` →\n"
        "   `project.author_email`, else your own address, not an agent's or the container's)"
    )
    # Only the email decides: a hub.json email keeps kickoff's check on hub.json.
    assert mapping_without("author_name")["identity_email"] == "`hub.json` → `project.author_email`"


def test_explains_prefix_when_hub_sets_no_prefix() -> None:
    mapping = mapping_without("branch_prefix")

    assert (mapping["project_branch_prefix"], mapping["prefix_note"]) == ("<prefix>", PREFIX_NOTE)
    # The author still comes from hub.json: the two keys are independent.
    assert mapping["commit_author"] == USER_AUTHOR


def test_keeps_user_wording_when_hub_sets_author(variant_config: HubConfig) -> None:
    mapping = substitution_mapping(variant_config)

    assert (mapping["commit_author"], mapping["prefix_note"]) == (USER_AUTHOR, "")


# AGH-56 (plan § Design 7): a hub with several tracker teams names them all, the default first.
# Each AGENTS.md value starts on its own line, so the template text before it only gets shorter.
MENTION_SUFFIX = "). Update it when starting, finishing"
RULE_SUFFIX = " in lowercase."
# The plugin texts' parenthetical, the same at every site once a hub lists several teams.
SEVERAL_TEAMS_KEY = (
    "the issue's team: a key of `tracker.teams` in `hub.json`, the first being the default"
)


def test_names_every_team_when_tracker_lists_teams() -> None:
    mapping = substitution_mapping(HubConfig.model_validate(a_two_team_document()))

    assert (
        mapping["tracker_team"],
        mapping["tracker_team_mention"],
        mapping["tracker_team_rule"],
        mapping["tracker_team_key"],
        mapping["tracker_team_key_named"],
        mapping["tracker_team_key_assigned"],
    ) == (
        "APP",
        "\n   team APP, OPS (default APP)",
        "\n   one of the tracker teams APP, OPS",
        SEVERAL_TEAMS_KEY,
        SEVERAL_TEAMS_KEY,
        SEVERAL_TEAMS_KEY,
    )


def test_wraps_team_list_when_keys_long() -> None:
    # 8 keys: with the suffix ignored, the last line of both values would pass 120 characters.
    keys = [f"TEAMKEY{chr(65 + n // 26)}{chr(65 + n % 26)}" for n in range(8)]
    document = a_hub_document()
    document["tracker"] = {"kind": "linear", "teams": keys}

    mapping = substitution_mapping(HubConfig.model_validate(document))

    for key, suffix in (
        ("tracker_team_mention", MENTION_SUFFIX),
        ("tracker_team_rule", RULE_SUFFIX),
    ):
        text = mapping[key] + suffix
        assert text.startswith("\n   "), key
        assert [line for line in text.splitlines() if len(line) > 120] == [], key
        assert ", ".join(keys) in " ".join(text.split()), key


# AGH-98: the end of the names line, the same whatever repos it names.
OVERRIDE_TAIL = (
    " some keys: `hub.json` → `repos[].conventions`; `hub worktree` and `hub run` apply them;"
    " a `pr_title` neither layer sets follows the repo's own `commit_title`."
)

# AGH-57 (plan § Design 7, E11): the mixed hub's branch rule, kickoff branch and Conventions block.
MIXED_CONVENTIONS_SECTION = (
    "\n\n## Conventions\n\n"
    "`hub.json` → `project.conventions`, overridden per repo by `repos[].conventions`;"
    " `hub worktree`, `hub run` and its\n"
    "session follow them. `{ISSUE}` is the issue id, `{issue_lower}` the same in lowercase,"
    " `{slug}` the worktree's `<desc>`.\n\n"
    "- Branch: `jdoe/{ISSUE}-{slug}`, e.g. `jdoe/DEM-7-collector`.\n"
    "- Commit title: `{ISSUE}: {type}({scope}): {summary}`,"
    " e.g. `DEM-7: feat(core): add the collector`.\n"
    "- PR title: `{ISSUE}: {type}({scope}): {summary}`,"
    " e.g. `DEM-7: feat(core): add the collector`.\n"
    "- `demo-api` overrides some keys: `hub.json` → `repos[].conventions`; `hub worktree` and"
    " `hub run` apply them;\n"
    "  a `pr_title` neither layer sets follows the repo's own `commit_title`."
)


def test_shows_conventions_when_hub_sets_them() -> None:
    mapping = substitution_mapping(HubConfig.model_validate(a_conventions_document()))

    assert (mapping["branch_rule"], mapping["kickoff_branch"], mapping["conventions_section"]) == (
        "Branch: `jdoe/{ISSUE}-{slug}`, or the repo's own (see Conventions above).",
        "`jdoe/{ISSUE}-{slug}` (or the repo's own, `hub.json` → `repos[].conventions`)",
        MIXED_CONVENTIONS_SECTION,
    )


@pytest.mark.parametrize(
    ("document", "branch_rule"),
    [
        (a_hub_document(), DEMO_BRANCH_RULE),
        (
            a_two_team_document(),
            "Branch: `jdoe/<team>-<n>-<desc>`, where `<team>` is\n"
            "   one of the tracker teams APP, OPS in lowercase.",
        ),
    ],
    ids=["one-team", "two-teams"],
)
def test_keeps_branch_text_when_hub_unconfigured(
    document: dict[str, Any], branch_rule: str
) -> None:
    mapping = substitution_mapping(HubConfig.model_validate(document))

    # The template text these values replaced, with the team rule it held.
    assert mapping["branch_rule"] == branch_rule
    assert mapping["kickoff_branch"] == "`jdoe/<team>-<n>-<desc>`"
    assert mapping["conventions_section"] == ""


def section_with(project: dict[str, str] | None, repo: dict[str, str]) -> str:
    """The Conventions block of the demo with ``project`` and ``repos[0]`` conventions."""
    document = a_hub_document()
    if project is not None:
        document["project"]["conventions"] = project
    document["repos"][0]["conventions"] = repo
    return substitution_mapping(HubConfig.model_validate(document))["conventions_section"]


# The project's effective PR title line stays when a repo overrides commit_title; the repo's own
# title (and E14's PR title that follows it) stays in hub.json (AGH-98).
@pytest.mark.parametrize(
    ("project", "pr_line"),
    [
        (
            {"commit_title": "{ISSUE}: {summary}"},
            "- PR title: `{ISSUE}: {summary}`, e.g. `DEM-7: add the collector`.",
        ),
        (
            None,
            "- PR title: `{type}({scope}): {summary} ({ISSUE})`,"
            " e.g. `feat(core): add the collector (DEM-7)`.",
        ),
        (
            {"branch": "{prefix}{ISSUE}-{slug}"},
            "- PR title: `{type}({scope}): {summary} ({ISSUE})`,"
            " e.g. `feat(core): add the collector (DEM-7)`.",
        ),
    ],
    ids=["project-commit-title", "project-unset", "project-branch-only"],
)
def test_shows_project_pr_title_when_repo_overrides_commit_title(
    project: dict[str, str] | None, pr_line: str
) -> None:
    section = section_with(project, {"commit_title": "[{ISSUE}] {type}: {summary}"})

    lines = section.splitlines()
    assert pr_line in lines
    assert last_bullet(section) == f"- `demo-api` overrides{OVERRIDE_TAIL}"
    assert "[{ISSUE}] {type}: {summary}" not in section


def test_names_repo_without_its_title_when_project_sets_pr_title() -> None:
    section = section_with(
        {"pr_title": "{ISSUE}: {summary}"}, {"commit_title": "[{ISSUE}] {type}: {summary}"}
    )

    assert last_bullet(section) == f"- `demo-api` overrides{OVERRIDE_TAIL}"
    assert section.count("follows") == 1
    assert "[{ISSUE}] {type}: {summary}" not in section


def test_lists_no_override_line_when_repo_conventions_empty() -> None:
    section = section_with({"branch": "{prefix}{ISSUE}-{slug}"}, {})

    assert "overrides" not in section
    # AGH-98: no repo named, no PR-title clause.
    assert "follows" not in section
    assert section.splitlines()[-1] == "- PR title: `{type}({scope}): {summary} ({ISSUE})`," + (
        " e.g. `feat(core): add the collector (DEM-7)`."
    )


# AGH-98: one line names the overriding repos and points to hub.json, so the block stays the same
# size whatever the repos' patterns; a repo with no override is not named.
def test_names_overriding_repos_in_one_line_when_several_repos_override() -> None:
    document = a_conventions_document()
    document["repos"][1]["conventions"] = {"branch": "web/{ISSUE}", "pr_title": "web: {summary}"}
    document["repos"].append({**a_second_repo(), "dir": "demo-docs", "github": "acme/demo-docs"})

    section = substitution_mapping(HubConfig.model_validate(document))["conventions_section"]

    bullets = section.split("\n\n")[-1].split("\n- ")
    assert len(bullets) == 4
    assert last_bullet(section) == f"- `demo-api`, `demo-web` override{OVERRIDE_TAIL}"
    assert all(len(line) <= 120 for line in section.splitlines())
    for pattern in ("feature/{issue_lower}/{slug}", "web/{ISSUE}", "web: {summary}"):
        assert pattern not in section, pattern
    assert "demo-docs" not in section


def test_names_overriding_repo_in_singular_when_one_repo_overrides() -> None:
    section = substitution_mapping(HubConfig.model_validate(a_conventions_document()))[
        "conventions_section"
    ]

    assert last_bullet(section) == f"- `demo-api` overrides{OVERRIDE_TAIL}"
    assert "demo-web" not in section


def a_document_with_overriding_repos(count: int) -> dict[str, Any]:
    """The mixed hub plus repos up to ``count`` overriding ones, ``demo-web`` still not one."""
    document = a_conventions_document()
    for n in range(2, count + 1):
        repo = {**a_second_repo(), "dir": f"repo-{n}", "github": f"acme/repo-{n}"}
        document["repos"].append({**repo, "conventions": {"branch": f"r{n}/{{ISSUE}}"}})
    return document


# AGH-98: at most three names, so the line keeps its size however many repos override.
@pytest.mark.parametrize(
    ("count", "names"),
    [
        (3, "`demo-api`, `repo-2`, `repo-3` override"),
        (4, "`demo-api`, `repo-2`, `repo-3` and 1 more repo override"),
        (6, "`demo-api`, `repo-2`, `repo-3` and 3 more repos override"),
    ],
    ids=["three", "one-more", "three-more"],
)
def test_names_three_repos_then_counts_rest_when_repos_override(count: int, names: str) -> None:
    document = a_document_with_overriding_repos(count)

    section = substitution_mapping(HubConfig.model_validate(document))["conventions_section"]

    assert last_bullet(section) == f"- {names}{OVERRIDE_TAIL}"
    assert "demo-web" not in section
    assert "repo-4" not in section


def last_bullet(section: str) -> str:
    """The Conventions block's last list item, its wrapped lines joined by single spaces."""
    return "- " + " ".join(section.rsplit("\n- ", 1)[1].split())


EXAMPLE_TITLE = {"type": "feat", "scope": "core", "summary": "add the collector"}
# A line past 120 characters holds one code span and only what stays glued to it: its indent, a
# list label or `e.g.` before it, its punctuation after it (AGH-98, plan P-1).
SINGLE_SPAN_LINE = re.compile(r"^ *(?:- (?:Branch|Commit title|PR title): |e\.g\. )?`[^`]*`[,.]$")
MARKDOWN_MARKER = re.compile(r"^\s*(?:#{1,6}|[-*+>]|\d+[.)])(?: |$)")


@pytest.mark.parametrize(
    "title",
    [
        pytest.param("{ISSUE} " + "w" * 82 + " # {summary}", id="heading"),
        pytest.param("{ISSUE} " + "w" * 33 + "  * {summary}", id="double-space-star"),
        pytest.param("{ISSUE} " + "w" * 32 + "  1. {summary}", id="double-space-dot"),
        pytest.param("{ISSUE} " + "w" * 32 + "  2) {summary}", id="double-space-paren"),
        pytest.param("{ISSUE} " + "w" * 31 + " <!-- {summary}", id="html-comment"),
        pytest.param("{ISSUE} " + "w" * 80 + "     {summary}", id="space-run"),
    ],
)
def test_starts_no_continuation_line_with_markdown_marker_when_wrapped(title: str) -> None:
    section = section_with({"commit_title": title, "pr_title": title}, {"branch": "x/{ISSUE}"})

    bullets = section.split("\n\n")[-1].splitlines()
    continuations = [line for line in bullets if not line.startswith("- ")]
    assert continuations, bullets
    assert [line for line in continuations if MARKDOWN_MARKER.match(line)] == []
    assert [line for line in continuations if line.lstrip().startswith("<")] == []
    example = render_title(title, TitleParts(issue="DEM-7", **EXAMPLE_TITLE))
    assert section.count(f"`{title}`") == 2
    assert section.count(f"`{example}`") == 2
    assert [span for span in re.findall("`[^`]*`", section) if "\n" in span] == []
    # AGH-98: a line passes 120 characters only as one span glued to its label or `e.g.`.
    assert [line for line in bullets if len(line) > 120 and not SINGLE_SPAN_LINE.match(line)] == []


def test_keeps_code_span_on_its_own_line_when_longer_than_width() -> None:
    branch = "{prefix}" + "x" * (MAX_PATTERN_CHARS - len("{prefix}/{ISSUE}")) + "/{ISSUE}"
    assert len(branch) == MAX_PATTERN_CHARS

    section = section_with({"branch": branch}, {"commit_title": "{summary}"})

    shape = branch.replace("{prefix}", "jdoe/")
    lines = section.splitlines()
    # AGH-98: the label stays on the span's line.
    assert f"- Branch: `{shape}`," in lines
    assert [line for line in lines if line != line.rstrip()] == []


# AGH-98: at the longest patterns each project item takes two lines, its label on the shape's line
# and `e.g.` on the example's, never alone on a line.
def test_keeps_label_and_example_with_their_spans_when_patterns_longest() -> None:
    branch = "{prefix}" + "x" * (MAX_PATTERN_CHARS - len("{prefix}/{ISSUE}")) + "/{ISSUE}"
    title = "{ISSUE}: {summary} " + "w" * (MAX_PATTERN_CHARS - len("{ISSUE}: {summary} "))
    assert len(branch) == len(title) == MAX_PATTERN_CHARS

    section = section_with(
        {"branch": branch, "commit_title": title, "pr_title": title}, {"branch": "x/{ISSUE}"}
    )

    items = section.split("\n\n")[-1].split("\n- ")[:3]
    assert [len(item.splitlines()) for item in items] == [2, 2, 2]
    lines = section.splitlines()
    assert [line for line in lines if line.strip() in ("e.g.", "-", "- Branch:")] == []
    assert [item.splitlines()[1].startswith("  e.g. `") for item in items] == [True] * 3
    assert sum(line.startswith("  e.g. `") for line in lines) == 3
