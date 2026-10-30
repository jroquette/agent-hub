"""The variables hidden from the hub's children, and the helper that drops them.

Every child loses ``LINEAR_API_KEY`` (D10); what runs code the implementing session may have
written also loses ``GH_TOKEN`` and ``GITHUB_TOKEN``. This is the only definition: ``run_children``
re-exports it, so the commands that only read config need not load the runner.
"""

from collections.abc import Iterable, Mapping
from typing import Final

KEY_VARIABLE: Final = "LINEAR_API_KEY"
# Hidden from every child; the implementing session also loses the GitHub tokens.
CHILD_HIDDEN: Final = (KEY_VARIABLE,)
SESSION_HIDDEN: Final = (KEY_VARIABLE, "GH_TOKEN", "GITHUB_TOKEN")


def without(environ: Mapping[str, str], names: Iterable[str]) -> dict[str, str]:
    """A copy of ``environ`` without ``names``."""
    hidden = set(names)
    return {name: value for name, value in environ.items() if name not in hidden}
