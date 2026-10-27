import copy
from typing import Any

from agent_hub.core.hub_config.environment_edits import EditRefusal
from agent_hub.core.hub_config.repo_edits import (
    add_repo,
    remove_repo,
    repo_references,
    set_repo,
)
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.repo_edit_cases import a_referenced_document, a_repos_document

_UNSET_KEYS = "role, check_fast, check_fast_timeout, default_branch"


def _d() -> dict[str, Any]:
    """``D`` with a comment key and ``demo-web`` holding the keys no ``hub repo`` edit takes."""
    document: dict[str, Any] = {"_comment": "first", **a_repos_document()}
    document["repos"][1]["services"] = {"web": {"kind": "http"}}
    document["repos"][1]["ui_paths"] = ["src/screens/**"]
    return document


def test_appends_repo_in_model_key_order_when_added() -> None:
    document = {"_comment": "first", **a_hub_document()}
    before = copy.deepcopy(document)

    edited = add_repo(
        document,
        {
            "default_branch": "trunk",
            "check": "make check",
            "check_fast": "make check-fast",
            "github": "acme/demo-web",
            "dir": "demo-web",
        },
    )

    assert isinstance(edited, dict)
    assert list(edited) == list(document)
    assert edited["repos"] == [
        document["repos"][0],
        {
            "dir": "demo-web",
            "github": "acme/demo-web",
            "check_fast": "make check-fast",
            "check": "make check",
            "default_branch": "trunk",
        },
    ]
    assert list(edited["repos"][1]) == ["dir", "github", "check_fast", "check", "default_branch"]
    # Pure: the document given is not changed.
    assert document == before


def test_refuses_add_when_dir_equal_ignoring_case() -> None:
    refused = add_repo(
        a_hub_document(), {"dir": "Demo-API", "github": "acme/demo-api", "check": "make check"}
    )

    assert refused == (
        EditRefusal(
            "repo dir Demo-API is already used by repos[0] (demo-api), ignoring case",
            "repos[0].dir",
        ),
    )


def test_leaves_document_untouched_when_add_refused() -> None:
    document = a_hub_document()
    before = copy.deepcopy(document)

    refused = add_repo(document, {"dir": "demo-api", "github": "acme/x", "check": "make check"})

    assert isinstance(refused, tuple)
    assert document == before


def test_changes_keys_in_place_when_set() -> None:
    document = _d()
    before = copy.deepcopy(document)

    edited = set_repo(document, "demo-web", {"github": "acme/web2", "check": "make ci"})

    assert isinstance(edited, dict)
    assert edited["repos"][0] == document["repos"][0]
    assert edited["repos"][1] == {
        "dir": "demo-web",
        "github": "acme/web2",
        "check": "make ci",
        "default_branch": "trunk",
        "services": {"web": {"kind": "http"}},
        "ui_paths": ["src/screens/**"],
    }
    assert list(edited["repos"][1]) == list(document["repos"][1])
    assert {key: value for key, value in edited.items() if key != "repos"} == {
        key: value for key, value in document.items() if key != "repos"
    }
    assert document == before


def test_appends_new_key_last_when_set() -> None:
    edited = set_repo(_d(), "demo-web", {"role": "app", "check_fast_timeout": 120})

    assert isinstance(edited, dict)
    assert list(edited["repos"][1]) == [
        "dir",
        "github",
        "check",
        "default_branch",
        "services",
        "ui_paths",
        "role",
        "check_fast_timeout",
    ]
    assert edited["repos"][1]["role"] == "app"
    assert edited["repos"][1]["check_fast_timeout"] == 120


def test_suggests_dir_when_case_differs() -> None:
    assert set_repo(_d(), "Demo-Web", {"role": "app"}) == (
        EditRefusal("no repo Demo-Web in hub.json; did you mean demo-web?"),
    )
    assert set_repo(_d(), "demo-nope", {"role": "app"}) == (
        EditRefusal("no repo demo-nope in hub.json"),
    )


def test_refuses_unset_when_key_required() -> None:
    refused = set_repo(_d(), "demo-web", {}, unset=("github", "check"))

    assert refused == (
        EditRefusal("github cannot be unset: hub.json needs it", "repos[1].github"),
        EditRefusal("check cannot be unset: hub.json needs it", "repos[1].check"),
    )


def test_refuses_unset_when_key_unknown() -> None:
    refused = set_repo(_d(), "demo-web", {}, unset=("services", "colour"))

    assert refused == (
        EditRefusal(f"services is not a key --unset takes: {_UNSET_KEYS}"),
        EditRefusal(f"colour is not a key --unset takes: {_UNSET_KEYS}"),
    )


def test_refuses_unset_when_key_also_set() -> None:
    refused = set_repo(_d(), "demo-web", {"role": "app"}, unset=("role",))

    assert refused == (EditRefusal("role is both set and unset", "repos[1].role"),)


def test_removes_keys_when_unset() -> None:
    document = _d()
    document["repos"][1]["check_fast"] = "make check-fast"

    edited = set_repo(document, "demo-web", {}, unset=("check_fast", "default_branch"))

    assert isinstance(edited, dict)
    assert edited["repos"][1] == {
        "dir": "demo-web",
        "github": "acme/demo-web",
        "check": "make check",
        "services": {"web": {"kind": "http"}},
        "ui_paths": ["src/screens/**"],
    }


def test_names_every_reference_when_remove_refused() -> None:
    document, local = a_referenced_document()
    document["guard"]["deny_paths"] = ["demo-api/secrets", "demo-web/secrets"]
    before = copy.deepcopy((document, local))

    refused = remove_repo(document, "demo-web", local_document=local)

    assert refused == (
        EditRefusal(
            "repo demo-web is still named at guard.ask_before_edit[0]", "guard.ask_before_edit[0]"
        ),
        EditRefusal("repo demo-web is still named at guard.deny_paths[1]", "guard.deny_paths[1]"),
        EditRefusal("repo demo-web is still named at events[0].repo", "events[0].repo"),
        EditRefusal(
            "repo demo-web is still named at modules.contract-sync.target",
            "modules.contract-sync.target",
        ),
        EditRefusal(
            "repo demo-web is still named in hub.local.json at repos[0].dir", "repos[0].dir"
        ),
    )
    assert repo_references(document, local, "demo-web") == refused
    assert (document, local) == before


def test_refuses_remove_when_last_repo() -> None:
    refused = remove_repo(a_hub_document(), "demo-api", local_document=None)

    assert refused == (
        EditRefusal("demo-api is the only repo; hub.json needs at least one", "repos"),
    )


def test_removes_entry_with_services_when_unreferenced() -> None:
    document = _d()

    edited = remove_repo(document, "demo-web", local_document={"repos": []})

    assert isinstance(edited, dict)
    assert edited == {**document, "repos": [document["repos"][0]]}
    assert list(edited) == list(document)


def test_refuses_remove_when_dir_unknown() -> None:
    assert remove_repo(_d(), "Demo-Web", local_document=None) == (
        EditRefusal("no repo Demo-Web in hub.json; did you mean demo-web?"),
    )
    assert remove_repo(_d(), "demo-nope", local_document=None) == (
        EditRefusal("no repo demo-nope in hub.json"),
    )


def test_ignores_reference_when_other_dir_shares_prefix() -> None:
    document = _d()
    document["guard"] = {
        "ask_before_edit": ["demo-web2/x"],
        "deny_paths": ["demo-webx", "Demo-Web"],
    }
    document["events"] = [{"workflow": "x", "on": "merge", "repo": "demo-web2"}]
    local = {"repos": [{"dir": "demo-web2", "services": {}}]}

    assert repo_references(document, local, "demo-web") == ()
