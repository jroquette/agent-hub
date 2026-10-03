"""The shared identity cases: what the CLI and the hooks' reader each resolve, from the same inputs.

Each case is a ``hub.json`` project's identity keys (the rest of the document is the builders'
synthetic one), the hub's ``tracker.transport``, an optional ``hub.local.json`` text and the hub
repo's git ``user.name``/``user.email``. ``expected`` holds the effective value of each local key
(``None`` when no source gives one) as the hooks' reader gives it; for a valid local file the CLI
gives the same, for an invalid one the CLI reports one problem, at ``problem_path``, instead.
Git values are as git prints them, less one trailing newline: neither side strips spaces, and a
value without ``FreeString``'s or ``EmailAddress``'s shape counts as unset. Synthetic values only.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from agent_hub.core.hub_config.local_config import LOCAL_FILE_MAX_BYTES

LOCAL_KEYS: Final = (
    "project.branch_prefix",
    "project.author_name",
    "project.author_email",
    "tracker.transport",
)

# The builders' ``hub.json`` identity.
_HUB_PROJECT: Final[Mapping[str, str]] = MappingProxyType(
    {"branch_prefix": "jdoe/", "author_name": "Jane Doe", "author_email": "jane@example.com"}
)
_GIT_NAME: Final = "Jane Roe"
_GIT_EMAIL: Final = "jane.doe@example.com"


@dataclass(frozen=True, slots=True)
class IdentityCase:
    """One set of identity sources and the effective values they give."""

    name: str
    hub_project: Mapping[str, str]
    hub_transport: str | None
    local_text: str | None
    git_name: str | None
    git_email: str | None
    expected: Mapping[str, str | None]
    # ``hub.local.json``, ``hub.json``, ``derived``, or ``None`` when there is no prefix.
    prefix_source: str | None
    # The JSON path of the one problem the CLI reports; ``None`` for a valid or absent file.
    problem_path: str | None = None

    @property
    def local_is_valid(self) -> bool:
        """Whether the CLI accepts the ``hub.local.json`` (an absent one included)."""
        return self.problem_path is None


def _values(
    prefix: str | None, name: str | None, email: str | None, *, transport: str = "api"
) -> Mapping[str, str | None]:
    return MappingProxyType(dict(zip(LOCAL_KEYS, (prefix, name, email, transport), strict=True)))


def _project(**keys: str) -> Mapping[str, str]:
    return MappingProxyType(keys)


def _oversize_local_text() -> str:
    """A valid file that sets ``branch_prefix``, one byte over the readers' cap."""
    head, tail = '{"project": {"branch_prefix": "me/"}, "_note": "', '"}'
    return head + "x" * (LOCAL_FILE_MAX_BYTES + 1 - len(head) - len(tail)) + tail


_HUB_VALUES: Final = _values("jdoe/", "Jane Doe", "jane@example.com")

IDENTITY_CASES: Final[tuple[IdentityCase, ...]] = (
    # A valid hub.local.json, or none.
    IdentityCase(
        name="hub-identity",
        hub_project=_HUB_PROJECT,
        hub_transport="mcp",
        local_text=None,
        git_name=_GIT_NAME,
        git_email=_GIT_EMAIL,
        expected=_values("jdoe/", "Jane Doe", "jane@example.com", transport="mcp"),
        prefix_source="hub.json",
    ),
    IdentityCase(
        name="local-prefix",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text='{"project": {"branch_prefix": "me/"}}',
        git_name=None,
        git_email=None,
        expected=_values("me/", "Jane Doe", "jane@example.com"),
        prefix_source="hub.local.json",
    ),
    IdentityCase(
        name="local-name",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text='{"project": {"author_name": "Jane Roe"}}',
        git_name=None,
        git_email=None,
        expected=_values("jdoe/", "Jane Roe", "jane@example.com"),
        prefix_source="hub.json",
    ),
    IdentityCase(
        name="local-email",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text='{"project": {"author_email": "me@example.com"}}',
        git_name=None,
        git_email=None,
        # hub.json sets the prefix: a local email does not derive another.
        expected=_values("jdoe/", "Jane Doe", "me@example.com"),
        prefix_source="hub.json",
    ),
    IdentityCase(
        name="local-transport",
        hub_project=_HUB_PROJECT,
        hub_transport="api",
        local_text='{"_note": "mine", "tracker": {"_note": "mine", "transport": "mcp"}}',
        git_name=None,
        git_email=None,
        expected=_values("jdoe/", "Jane Doe", "jane@example.com", transport="mcp"),
        prefix_source="hub.json",
    ),
    IdentityCase(
        name="team-git",
        hub_project=_project(),
        hub_transport=None,
        local_text=None,
        git_name=_GIT_NAME,
        git_email=_GIT_EMAIL,
        expected=_values("jane.doe/", _GIT_NAME, _GIT_EMAIL),
        prefix_source="derived",
    ),
    IdentityCase(
        name="team-local-email-derives",
        hub_project=_project(),
        hub_transport=None,
        local_text='{"project": {"author_email": "me@example.com"}}',
        git_name=_GIT_NAME,
        git_email=_GIT_EMAIL,
        expected=_values("me/", _GIT_NAME, "me@example.com"),
        prefix_source="derived",
    ),
    IdentityCase(
        name="team-mixed",
        hub_project=_project(author_name="Jane Doe"),
        hub_transport=None,
        local_text=None,
        git_name=_GIT_NAME,
        git_email="jane@example.com",
        expected=_values("jane/", "Jane Doe", "jane@example.com"),
        prefix_source="derived",
    ),
    IdentityCase(
        name="team-derived-invalid",
        hub_project=_project(),
        hub_transport=None,
        local_text=None,
        git_name=_GIT_NAME,
        git_email="j+x@example.com",
        expected=_values(None, _GIT_NAME, "j+x@example.com"),
        prefix_source=None,
    ),
    IdentityCase(
        name="team-git-email-spaced",
        hub_project=_project(),
        hub_transport=None,
        local_text=None,
        git_name=_GIT_NAME,
        git_email=f"{_GIT_EMAIL} ",
        # Not stripped: the trailing space fails EmailAddress, so there is no email to derive from.
        expected=_values(None, _GIT_NAME, None),
        prefix_source=None,
    ),
    IdentityCase(
        name="team-git-bad-shape",
        hub_project=_project(),
        hub_transport=None,
        local_text=None,
        git_name="Jane\u0007",
        git_email="Jane <jane@example.com>",
        expected=_values(None, None, None),
        prefix_source=None,
    ),
    IdentityCase(
        name="team-git-name-spaced",
        hub_project=_project(),
        hub_transport=None,
        local_text=None,
        git_name=f"{_GIT_NAME} ",
        git_email=_GIT_EMAIL,
        # FreeString allows spaces: the name is kept as git gives it.
        expected=_values("jane.doe/", f"{_GIT_NAME} ", _GIT_EMAIL),
        prefix_source="derived",
    ),
    IdentityCase(
        name="team-hub-email-derives",
        hub_project=_project(author_email="jane@example.com"),
        hub_transport=None,
        local_text=None,
        git_name=_GIT_NAME,
        git_email=_GIT_EMAIL,
        # hub.json's email wins over git's, and the prefix derives from it.
        expected=_values("jane/", _GIT_NAME, "jane@example.com"),
        prefix_source="derived",
    ),
    IdentityCase(
        name="team-no-source",
        hub_project=_project(),
        hub_transport=None,
        local_text=None,
        git_name=None,
        git_email=None,
        expected=_values(None, None, None),
        prefix_source=None,
    ),
    # An invalid hub.local.json: the CLI reports it; the reader ignores it whole or per key.
    IdentityCase(
        name="local-not-json",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text='{"project": {"branch_prefix": "me/"',
        git_name=None,
        git_email=None,
        expected=_HUB_VALUES,
        prefix_source="hub.json",
        problem_path="$",
    ),
    IdentityCase(
        name="local-array",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text='[{"project": {"branch_prefix": "me/"}}]',
        git_name=None,
        git_email=None,
        expected=_HUB_VALUES,
        prefix_source="hub.json",
        problem_path="$",
    ),
    IdentityCase(
        name="local-unknown-key",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text='{"guard": {}, "project": {"branch_prefix": "me/"}}',
        git_name=None,
        git_email=None,
        expected=_values("me/", "Jane Doe", "jane@example.com"),
        prefix_source="hub.local.json",
        problem_path="guard",
    ),
    IdentityCase(
        name="local-bad-prefix",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text='{"project": {"branch_prefix": "-x/"}}',
        git_name=None,
        git_email=None,
        expected=_HUB_VALUES,
        prefix_source="hub.json",
        problem_path="project.branch_prefix",
    ),
    IdentityCase(
        name="local-bad-transport",
        hub_project=_HUB_PROJECT,
        hub_transport="mcp",
        local_text='{"tracker": {"transport": "ftp"}}',
        git_name=None,
        git_email=None,
        expected=_values("jdoe/", "Jane Doe", "jane@example.com", transport="mcp"),
        prefix_source="hub.json",
        problem_path="tracker.transport",
    ),
    IdentityCase(
        name="local-empty-name",
        hub_project=_project(),
        hub_transport=None,
        local_text='{"project": {"author_name": ""}}',
        git_name=_GIT_NAME,
        git_email=_GIT_EMAIL,
        # No hub.json value either: the name falls through to git.
        expected=_values("jane.doe/", _GIT_NAME, _GIT_EMAIL),
        prefix_source="derived",
        problem_path="project.author_name",
    ),
    IdentityCase(
        name="local-wrong-type-email",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text='{"project": {"author_email": 7}}',
        git_name=None,
        git_email=None,
        expected=_HUB_VALUES,
        prefix_source="hub.json",
        problem_path="project.author_email",
    ),
    IdentityCase(
        name="local-bad-email",
        hub_project=_project(),
        hub_transport=None,
        local_text='{"project": {"author_email": "Jane <j@example.com>"}}',
        git_name=None,
        git_email=_GIT_EMAIL,
        # The email falls through to git, and the prefix derives from git's email.
        expected=_values("jane.doe/", None, _GIT_EMAIL),
        prefix_source="derived",
        problem_path="project.author_email",
    ),
    IdentityCase(
        name="local-oversize",
        hub_project=_HUB_PROJECT,
        hub_transport=None,
        local_text=_oversize_local_text(),
        git_name=None,
        git_email=None,
        # Over the cap the file is not read at all, so its valid prefix is not applied.
        expected=_HUB_VALUES,
        prefix_source="hub.json",
        problem_path="$",
    ),
)
