"""Links to a hub's feature records on GitHub, for the PR bodies people read.

A PR body that cites an acceptance criterion, a decision or a plan step links it to its record:
``https://github.com/<hub repo>/blob/<hub default branch>/brain/features/<slug>/``, then the
file and its section. The hub's repo and its default branch come from ``hub.json``'s project;
nothing here names a project. A record that is not on the hub's default branch yet has no page
there, so the link works only once the record's hub PR has merged.
"""

import re
from typing import Final

FEATURES_PATH: Final = "brain/features"
# A feature folder's name, as the ticket records accept it (``hub step``'s ``--feature``).
FEATURE_SLUG: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def features_url(*, hub_repo: str, branch: str) -> str:
    """The web address of the hub's ``brain/features`` folder on ``branch``, no trailing slash."""
    return f"https://github.com/{hub_repo}/blob/{branch}/{FEATURES_PATH}"


def feature_url(*, hub_repo: str, branch: str, slug: str) -> str:
    """The web address of one feature's folder, ending with a slash.

    Raises ValueError when ``slug`` is not a feature folder name (``FEATURE_SLUG``).
    """
    if FEATURE_SLUG.fullmatch(slug) is None:
        raise ValueError(f"not a feature folder name: {slug[:64]!r}")
    return f"{features_url(hub_repo=hub_repo, branch=branch)}/{slug}/"
