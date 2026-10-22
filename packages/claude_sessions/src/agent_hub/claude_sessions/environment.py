"""The environment of a ``claude`` child (L5): ``hub web``'s own, minus the hub's declared
credentials, plus the variables the server adds so the hub's hook sensor posts back to it.

Only ``AGENT_HUB_WEB_URL`` is ever added: the access token and the cookie name stay in
``hub web``'s memory, so any other extra a caller hands in is dropped. Every declared
``credentials.env`` name, and an ``AWS_PROFILE`` naming a declared profile, is removed
(``StartSpec.hidden_environment``, AM-13, P-9). Nothing here reads a value of the environment
beyond that comparison; it is copied.

The SDK starts the child from this process's own environment and only adds ``env`` on top, so
``masked_names`` lists the hidden names a parent environment holds: the options override each
with an empty value, the only way the child does not inherit it.
"""

from collections.abc import Iterable, Mapping
from typing import Final

from agent_hub.core.scenarios.credentials import NO_CREDENTIALS, CredentialNames, hidden_environment

WEB_URL_VARIABLE: Final = "AGENT_HUB_WEB_URL"
PASSED_EXTRAS: Final = frozenset({WEB_URL_VARIABLE})


def child_environment(
    environ: Mapping[str, str],
    extra: Mapping[str, str],
    *,
    hidden: CredentialNames = NO_CREDENTIALS,
) -> dict[str, str]:
    """``environ`` without the ``hidden`` credentials, plus the allowed ``extra`` variables,
    as a new mapping."""
    child = hidden_environment(environ, hidden)
    child.update((key, value) for key, value in extra.items() if key in PASSED_EXTRAS)
    return child


def masked_names(parents: Iterable[Mapping[str, str]], hidden: CredentialNames) -> frozenset[str]:
    """The names ``hidden`` removes from any of the ``parents`` environments."""
    return frozenset(
        name
        for environ in parents
        for name in environ
        if name not in hidden_environment({name: environ[name]}, hidden)
    )
