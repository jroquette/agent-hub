"""The environment of a ``claude`` child (L5): ``hub web``'s own, unchanged, plus the variables
the server adds so the hub's hook sensor posts back to it.

Only ``AGENT_HUB_WEB_URL`` is ever added: the access token and the cookie name stay in
``hub web``'s memory, so any other extra a caller hands in is dropped. Nothing here reads a value
of the environment; it is copied.
"""

from collections.abc import Mapping
from typing import Final

WEB_URL_VARIABLE: Final = "AGENT_HUB_WEB_URL"
PASSED_EXTRAS: Final = frozenset({WEB_URL_VARIABLE})


def child_environment(environ: Mapping[str, str], extra: Mapping[str, str]) -> dict[str, str]:
    """``environ`` plus the allowed ``extra`` variables, as a new mapping."""
    child = dict(environ)
    child.update((key, value) for key, value in extra.items() if key in PASSED_EXTRAS)
    return child
