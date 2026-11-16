"""Where a hub installs the platform's CLI from: ``platform.repository``, its form and default.

The value is the repository root as ``git+https://<host>/<path>``; the hub runs
``<repository>@v<platform.version>#subdirectory=packages/agent-hub``. A valid value cannot hold a
user, port, query, fragment or ``@ref``, so it never carries a credential and may be echoed; an
invalid one is never repeated (docs/design/project-config.md). The generator renders the pattern
and the form into the hub's runtime readers, so every reader checks these same bytes.
"""

import re
from typing import Final

# The one source file that names the default (the generator and the release command import it).
DEFAULT_PLATFORM_REPOSITORY: Final = "git+https://github.com/jroquette/agent-hub"
MAX_PLATFORM_REPOSITORY_CHARS: Final = 200
# ``guard.deny_hosts``'s host, then one or more of ``Repo.dir``'s safe segments, written out here
# because ``model.py`` imports this module. No anchors: readers use ``re.fullmatch``, since ``$``
# also matches before a final newline. The separators (``.``, ``/``, ``[.-]``) are in no label or
# segment class, so ``re`` cannot backtrack exponentially.
PLATFORM_REPOSITORY_PATTERN: Final = (
    r"git\+https://[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
    r"(?:/[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*)+"
)
PLATFORM_REPOSITORY_FORM: Final = (
    "git+https://<host>/<path> (the repository root: no user, port, query, fragment, @ref or"
    f" trailing /; at most {MAX_PLATFORM_REPOSITORY_CHARS} characters)"
)
PLATFORM_REPOSITORY_MESSAGE: Final = f"must be {PLATFORM_REPOSITORY_FORM}"

_PLATFORM_REPOSITORY = re.compile(PLATFORM_REPOSITORY_PATTERN)


def is_platform_repository(value: object) -> bool:
    """Whether a value from ``hub.json`` is an accepted ``platform.repository``.

    The length is checked before the pattern, so the pattern never sees an over-long value.
    """
    return (
        isinstance(value, str)
        and len(value) <= MAX_PLATFORM_REPOSITORY_CHARS
        and _PLATFORM_REPOSITORY.fullmatch(value) is not None
    )
