import pytest

from agent_hub.core.features.record_links import feature_url, features_url


def test_builds_features_url_when_hub_repo_and_branch_given() -> None:
    assert features_url(hub_repo="acme/demo-hub", branch="main") == (
        "https://github.com/acme/demo-hub/blob/main/brain/features"
    )


def test_keeps_branch_path_when_branch_has_slash() -> None:
    assert features_url(hub_repo="acme/demo-hub", branch="release/2") == (
        "https://github.com/acme/demo-hub/blob/release/2/brain/features"
    )


def test_builds_feature_url_when_slug_valid() -> None:
    assert feature_url(hub_repo="acme/demo-hub", branch="trunk", slug="pr-links") == (
        "https://github.com/acme/demo-hub/blob/trunk/brain/features/pr-links/"
    )


@pytest.mark.parametrize("slug", ["", "../x", "a/b", "-x", "a b", "x" * 129])
def test_refuses_feature_url_when_slug_not_a_folder_name(slug: str) -> None:
    with pytest.raises(ValueError, match="not a feature folder name"):
        feature_url(hub_repo="acme/demo-hub", branch="main", slug=slug)
