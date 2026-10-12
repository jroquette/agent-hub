import pytest

from agent_hub.core.runner.run_texts import WORKSPACE_WORDS
from agent_hub.core.runner.ship_texts import (
    MAX_ISSUE_URL_CHARS,
    RELATED_END,
    RELATED_START,
    ship_body,
    ship_comment,
    with_related,
)

WORKSPACE = "/work/ws"
# The url cap, written once: the boundary urls are built from it, not from the module.
URL_CAP = 2_048
URL_START = "https://linear.app/"
ISSUE_URL = "https://linear.app/acme/issue/DEM-7/x"
API_PR = "https://github.com/acme/demo-api/pull/101"
WEB_PR = "https://github.com/acme/demo-web/pull/102"
EMPTY_SECTION = f"{RELATED_START}\n## Related PRs\n{RELATED_END}"
# Assembled, so the repo holds no attribution line (as test_text_rules.py does).
CO_AUTHOR_LINE = "Co-" + "Authored-By: " + "Claude" + " <noreply@example.com>"


def section(*urls: str) -> str:
    listed = "".join(f"- {url}\n" for url in urls)
    return f"{RELATED_START}\n## Related PRs\n{listed}{RELATED_END}"


def test_pins_markers_and_cap_when_module_loaded() -> None:
    assert RELATED_START == "<!-- hub-ship:related-prs:start -->"
    assert RELATED_END == "<!-- hub-ship:related-prs:end -->"
    assert MAX_ISSUE_URL_CHARS == URL_CAP


def test_holds_issue_and_empty_section_when_body_built() -> None:
    body = ship_body(issue_id="DEM-7", issue_url=ISSUE_URL)

    assert body == f"DEM-7 {ISSUE_URL}\n\n{EMPTY_SECTION}"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://linear.app/acme/issue/DEM-7",
        "https://linear.app/a b",
        "https://linear.app/a\nforged",
        URL_START + "x" * (URL_CAP + 1 - len(URL_START)),
        "https://linear.app/x/\N{ROBOT FACE}",
        "https://linear.app/a/" + "claude" + "/fix-1",
        "https://linear.app/\u00e9t\u00e9",
    ],
)
def test_omits_url_when_not_https(url: str | None) -> None:
    assert ship_body(issue_id="DEM-7", issue_url=url) == f"DEM-7\n\n{EMPTY_SECTION}"


def test_keeps_url_when_at_length_cap() -> None:
    url = URL_START + "x" * (URL_CAP - len(URL_START))

    assert len(url) == URL_CAP
    assert ship_body(issue_id="DEM-7", issue_url=url) == f"DEM-7 {url}\n\n{EMPTY_SECTION}"


def test_lists_urls_when_section_replaced() -> None:
    body = ship_body(issue_id="DEM-7", issue_url=ISSUE_URL)

    linked = with_related(body, urls=[API_PR, WEB_PR], workspace=WORKSPACE)

    assert linked == f"DEM-7 {ISSUE_URL}\n\n{section(API_PR, WEB_PR)}"


def test_keeps_outside_text_when_section_replaced() -> None:
    before = "Intro \t*kept*\r\n\n  spaced  é\n\n"
    after = "\n\nTrailing note\n"
    body = f"{before}{section(API_PR)}{after}"

    linked = with_related(body, urls=[WEB_PR], workspace=WORKSPACE)

    assert linked == f"{before}{section(WEB_PR)}{after}"


def test_appends_section_once_when_markers_absent() -> None:
    body = "Written by hand.\n"

    linked = with_related(body, urls=[API_PR], workspace=WORKSPACE)

    assert linked == f"Written by hand.\n\n\n{section(API_PR)}"
    assert with_related(linked, urls=[API_PR], workspace=WORKSPACE) == linked


def test_gives_section_alone_when_body_empty() -> None:
    assert with_related("", urls=[API_PR], workspace=WORKSPACE) == section(API_PR)


def test_keeps_one_pair_when_body_has_two() -> None:
    body = f"Top\n{section(API_PR)}\nMiddle\n{section(WEB_PR)}\nEnd"

    linked = with_related(body, urls=[WEB_PR], workspace=WORKSPACE)

    assert linked == f"Top\n{section(WEB_PR)}\nMiddle\n\nEnd"
    assert linked.count(RELATED_START) == linked.count(RELATED_END) == 1


def test_runs_section_to_end_when_end_marker_missing() -> None:
    body = f"Top\n{RELATED_START}\n- {API_PR}\nlost tail"

    linked = with_related(body, urls=[WEB_PR], workspace=WORKSPACE)

    assert linked == f"Top\n{section(WEB_PR)}"


def test_returns_same_body_when_links_unchanged() -> None:
    body = with_related(
        f"Note\n\n{ship_body(issue_id='DEM-7', issue_url=ISSUE_URL)}",
        urls=[WEB_PR],
        workspace=WORKSPACE,
    )

    assert with_related(body, urls=[WEB_PR], workspace=WORKSPACE) == body


def test_drops_attribution_line_when_outside_text_has_one() -> None:
    body = f"Kept\n{CO_AUTHOR_LINE}\n\N{ROBOT FACE} done\n{section()}\nAfter\n{CO_AUTHOR_LINE}"

    linked = with_related(body, urls=[API_PR], workspace=WORKSPACE)

    assert linked == f"Kept\n{section(API_PR)}\nAfter"


def test_replaces_workspace_path_when_outside_text_names_it() -> None:
    body = f"See file://{WORKSPACE}/demo-api/x.py in {WORKSPACE}.\x00\ud800\n{section()}"

    linked = with_related(body, urls=[API_PR], workspace=WORKSPACE)

    assert linked == f"See demo-api/x.py in {WORKSPACE_WORDS}.�\n{section(API_PR)}"
    assert WORKSPACE not in linked


def test_lists_urls_in_order_when_comment_built() -> None:
    comment = ship_comment(urls=[WEB_PR, API_PR], workspace=WORKSPACE)

    assert comment == f"Pull requests:\n- {WEB_PR}\n- {API_PR}"


def test_omits_agent_word_when_comment_built() -> None:
    dirty = f"https://github.com/acme/demo-api/pull/1\u202e\n{CO_AUTHOR_LINE}"

    comment = ship_comment(urls=[API_PR, dirty], workspace=WORKSPACE)

    assert "agent" not in comment.lower()
    assert comment == f"Pull requests:\n- {API_PR}\n- https://github.com/acme/demo-api/pull/1"
