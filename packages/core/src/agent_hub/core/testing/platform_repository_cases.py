"""The shared ``platform.repository`` cases: the values every reader accepts or rejects alike.

The model, the hooks' stdlib reader, the ``hub`` shim, cloud setup and the CI credential step
each run this one table (docs/design/project-config.md). ``value`` is the JSON value of the key;
``is_valid`` is whether a reader takes it as the repository. Synthetic hosts and paths only; the
credential values' user, password and token are in ``SECRET_PARTS``, which no output may hold,
and ``VALUE_PARTS`` adds the other parts of the bad values that an echo would show.
"""

from dataclasses import dataclass
from typing import Final

from agent_hub.core.hub_config.platform_repository import DEFAULT_PLATFORM_REPOSITORY

# A source on another host than github.com, as a company mirror would be.
CUSTOM_REPOSITORY: Final = "git+https://git.acme.test/tools/agent-hub"
CREDENTIAL_VALUE: Final = "git+https://alice:s3cr3t@github.com/acme/agent-hub"
# A token alone as userinfo, the way a pasted GitHub token would sit in the URL.
BARE_USERINFO_VALUE: Final = "git+https://ghp_tokenonly123@github.com/acme/agent-hub"
SECRET_PARTS: Final = ("alice", "s3cr3t", "ghp_tokenonly123")
# Parts of the bad values that a message echoing them would show (E10): the credential's user,
# password and token, a port, a query and a scheme. Every reader's bad-value test checks them.
VALUE_PARTS: Final = (*SECRET_PARTS, "8443", "ref=x", "git+ssh")
_ACME = "git+https://github.com/acme/"


@dataclass(frozen=True, slots=True)
class RepositoryCase:
    """One ``platform.repository`` value and whether it is accepted."""

    name: str
    value: object
    is_valid: bool


def _good(name: str, value: str) -> RepositoryCase:
    return RepositoryCase(name=name, value=value, is_valid=True)


def _bad(name: str, value: object) -> RepositoryCase:
    return RepositoryCase(name=name, value=value, is_valid=False)


REPOSITORY_CASES: Final[tuple[RepositoryCase, ...]] = (
    _good("default", DEFAULT_PLATFORM_REPOSITORY),
    _good("custom-host", CUSTOM_REPOSITORY),
    _good("other-org", _ACME + "agent-hub"),
    _good("git-suffix", _ACME + "agent-hub.git"),
    _good("subgroup", "git+https://git.acme.test/tools/platform/agent-hub"),
    _good("mixed-case", "git+https://GitHub.com/Acme/Agent_Hub"),
    # At the cap: the 200 is a literal here, so a changed cap fails these two rows.
    _good("200-chars", _ACME + "a" * 172),
    _bad("201-chars", _ACME + "a" * 173),
    _bad("credential", CREDENTIAL_VALUE),
    _bad("token-userinfo", BARE_USERINFO_VALUE),
    _bad("percent-at", _ACME + "agent%40hub"),
    _bad("at-in-path", "git+https://github.com/acme@x/agent-hub"),
    _bad("git-ssh", "git+ssh://git@github.com/acme/agent-hub"),
    _bad("ssh", "ssh://github.com/acme/agent-hub"),
    _bad("no-git-prefix", "https://github.com/acme/agent-hub"),
    _bad("git-http", "git+http://github.com/acme/agent-hub"),
    _bad("at-ref", _ACME + "agent-hub@v1.0.0"),
    _bad("query", _ACME + "agent-hub?ref=x"),
    _bad("fragment", _ACME + "agent-hub#subdirectory=x"),
    _bad("trailing-slash", _ACME + "agent-hub/"),
    _bad("port", "git+https://github.com:8443/acme/agent-hub"),
    _bad("no-path", "git+https://github.com"),
    _bad("dot-dot", _ACME + "../x"),
    _bad("empty", ""),
    _bad("number", 42),
    _bad("null", None),
    _bad("true", value=True),
    _bad("list", [CUSTOM_REPOSITORY]),
    # ``$`` would match before this newline; every reader uses ``fullmatch``.
    _bad("trailing-newline", _ACME + "agent-hub\n"),
    _bad("leading-space", " " + _ACME + "agent-hub"),
    _bad("dash-host", "git+https://-github.com/acme/x"),
    _bad("dot-segment", _ACME + ".hidden"),
    _bad("empty-segment", "git+https://github.com//acme"),
    _bad("non-ascii-host", "git+https://g\u00efthub.com/acme/agent-hub"),
    # A reader that uses ``re.IGNORECASE`` or lowercases the value accepts these two: the
    # Kelvin sign folds to ``k``.
    _bad("upper-scheme", "GIT+HTTPS://github.com/acme/agent-hub"),
    _bad("kelvin-sign", _ACME + "\u212a"),
    # A reader that splits lines or stops at NUL would see a valid first part.
    _bad("embedded-newline", _ACME + "x\ngit+https://github.com/acme/y"),
    _bad("nul", _ACME + "x\x00"),
    # Inputs that make an overlapping pattern backtrack; the result is exact, never timed.
    _bad("hostile-host", "git+https://" + "a-" * 90 + "!"),
    _bad("hostile-path", "git+https://h/" + "a." * 90 + "!"),
)
